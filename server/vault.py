"""news-vault (MD 一次データ) の読み書きと SQLite 索引の再構築。

MD が真実の源。SQLite が壊れても rebuild_index() でここから全再構築できる
(docs/news-picker-spec.md §4.3 の必須要件)。

vault 構造:
  data/news-vault/
    {category}/{YYYY-MM-DD}/{slug}-{id}.md   -- 記事 (frontmatter + 本文)
    {category}/_category-brief.md            -- カテゴリ要約
    _tombstones.jsonl                        -- 削除/パージ済み url_hash (復活防止)
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import config, store
from .atomic_io import atomic_write_text

_TOMBSTONE_FILE = "_tombstones.jsonl"
_BRIEF_FILE = "_category-brief.md"


# ---------------------------------------------------------------- 時刻変換

def epoch_to_iso(epoch: int | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_to_epoch(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, datetime):
        return int(value.timestamp())
    return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())


# ---------------------------------------------------------------- 記事 MD

def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:48] or "article"


def _split_frontmatter(text: str) -> tuple[dict, str]:
    m = re.match(r"\A---\n(.*?)\n---\n?(.*)\Z", text, re.DOTALL)
    if not m:
        raise ValueError("frontmatter not found")
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


def _load_json_field(value) -> list | dict | None:
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


def write_article_md(article: dict, vault_dir: Path | None = None) -> Path:
    """DB 行 (dict) から記事 MD を書き出し、vault 相対の md_path を返す。

    md_path が既にあればその場所へ上書きする (保存/評価などの状態変更を
    MD へ書き戻す用途。「MD が真実の源」を rebuild 後も保つため)。
    """
    vault_dir = Path(vault_dir or config.VAULT_DIR)
    if article.get("md_path"):
        rel = Path(article["md_path"])
    else:
        date_dir = datetime.fromtimestamp(
            article["fetched_at"], tz=timezone.utc
        ).strftime("%Y-%m-%d")
        rel = (
            Path(article["category"]) / date_dir
            / f"{_slugify(article['title'])}-{article['id']}.md"
        )

    meta = {
        "id": article["id"],
        "category": article["category"],
        "title": article["title"],
        "url": article["url"],
        "source": article.get("source"),
        "snippet": article.get("snippet"),
        "image_url": article.get("image_url"),
        "published_at": epoch_to_iso(article.get("published_at")),
        "fetched_at": epoch_to_iso(article["fetched_at"]),
        "enriched_at": epoch_to_iso(article.get("enriched_at")),
        "status": article.get("status", "new"),
        "entities": _load_json_field(article.get("entities")),
        "impact": article.get("impact"),
        "tags": _load_json_field(article.get("tags")),
        "relevance": article.get("relevance"),
        "title_ja": article.get("title_ja"),
        "rating": article.get("rating"),
    }
    front = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()

    lines = [f"---\n{front}\n---", ""]
    lines += ["## 要約", "", article.get("summary") or "", ""]
    key_points = _load_json_field(article.get("key_points")) or []
    lines += ["## 要点", ""]
    lines += [f"- {p}" for p in key_points] or ["-"]
    lines += [""]
    if article.get("body"):
        lines += ["## 本文", "", article["body"], ""]
    lines += [f"出典: {article['url']}", ""]

    atomic_write_text(vault_dir / rel, "\n".join(lines))
    return rel


def sync_article_md(row, vault_dir: Path | None = None) -> None:
    """DB の記事行を MD へ書き戻す (MD が無い = 未 enrich の記事は何もしない)。

    保存・評価などの状態変更後に呼ぶ。これを怠ると rebuild で古い状態に
    巻き戻り、保存済み記事が自動整理の対象に戻ってしまう。
    """
    if row is None or not row["md_path"]:
        return
    write_article_md(dict(row), vault_dir)


def delete_article_md(md_path: str | None, vault_dir: Path | None = None) -> None:
    """記事 MD を削除する (非表示/パージと連動。残すと rebuild で復活する)。"""
    if not md_path:
        return
    vault_dir = Path(vault_dir or config.VAULT_DIR)
    (vault_dir / md_path).unlink(missing_ok=True)


def parse_article_md(path: Path) -> dict:
    """記事 MD を DB 行相当の dict に戻す (insert_full_article に渡せる形)。"""
    meta, body_text = _split_frontmatter(path.read_text(encoding="utf-8"))

    sections: dict[str, list[str]] = {}
    current = None
    for line in body_text.splitlines():
        m = re.match(r"^## (.+)$", line)
        if m:
            current = m.group(1).strip()
            sections[current] = []
        elif current is not None and not line.startswith("出典:"):
            sections[current].append(line)

    summary = "\n".join(sections.get("要約", [])).strip() or None
    key_points = [
        ln[2:].strip()
        for ln in sections.get("要点", [])
        if ln.startswith("- ") and ln[2:].strip()
    ]
    body = "\n".join(sections.get("本文", [])).strip() or None

    return {
        "id": meta["id"],
        "category": meta["category"],
        "title": meta["title"],
        "url": meta["url"],
        "url_hash": store.url_hash(meta["url"]),
        "source": meta.get("source"),
        "snippet": meta.get("snippet"),
        "image_url": meta.get("image_url"),
        "published_at": iso_to_epoch(meta.get("published_at")),
        "fetched_at": iso_to_epoch(meta.get("fetched_at")),
        "status": meta.get("status", "seen"),
        "summary": summary,
        "key_points": json.dumps(key_points, ensure_ascii=False) if key_points else None,
        "entities": (
            json.dumps(meta["entities"], ensure_ascii=False) if meta.get("entities") else None
        ),
        "impact": meta.get("impact"),
        "tags": json.dumps(meta["tags"], ensure_ascii=False) if meta.get("tags") else None,
        "body": body,
        "enriched_at": iso_to_epoch(meta.get("enriched_at")),
        "relevance": meta.get("relevance"),
        "title_ja": meta.get("title_ja"),
        "rating": meta.get("rating"),
    }


# ---------------------------------------------------------------- tombstone 永続化

def append_tombstone(
    h: str, reason: str, created_at: int | None = None, vault_dir: Path | None = None
) -> None:
    """tombstone を vault 側にも追記する (rebuild 後も削除が復活しないように)。"""
    vault_dir = Path(vault_dir or config.VAULT_DIR)
    vault_dir.mkdir(parents=True, exist_ok=True)
    entry = {"url_hash": h, "reason": reason, "created_at": created_at or int(time.time())}
    with open(vault_dir / _TOMBSTONE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        f.flush()


def load_tombstones(vault_dir: Path | None = None) -> list[dict]:
    path = Path(vault_dir or config.VAULT_DIR) / _TOMBSTONE_FILE
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


# ---------------------------------------------------------------- カテゴリ要約

def write_category_brief(
    category: str,
    brief: str,
    article_count: int,
    updated_at: int,
    vault_dir: Path | None = None,
) -> Path:
    vault_dir = Path(vault_dir or config.VAULT_DIR)
    rel = Path(category) / _BRIEF_FILE
    meta = {
        "category": category,
        "article_count": article_count,
        "updated_at": epoch_to_iso(updated_at),
    }
    front = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    atomic_write_text(vault_dir / rel, f"---\n{front}\n---\n\n{brief}\n")
    return rel


# ---------------------------------------------------------------- rebuild

def rebuild_index(conn: sqlite3.Connection, vault_dir: Path | None = None) -> dict:
    """SQLite 索引を vault から全再構築する (必須要件)。

    - tombstone に載っている記事 MD は復元しない (非表示/削除済みの復活防止)
    - 全体を1トランザクション (BEGIN IMMEDIATE) で包む: 他ワーカーの書き込みを
      ブロックして ID 衝突を防ぎ、途中失敗時は rollback で元の索引に戻す
    - 埋め込み (vec_articles) も復元する (enrich 済み記事のみ。EnrichWorker は
      enrich 済み記事を再処理しないため、ここで埋め直さないと永久に失われる)
    """
    vault_dir = Path(vault_dir or config.VAULT_DIR)

    # ---- 読み取りと埋め込み計算はトランザクションの外で済ませる (ロック時間短縮)
    tombstones = load_tombstones(vault_dir)
    dead = {t["url_hash"] for t in tombstones}

    rows: list[dict] = []
    brief_rows: list[dict] = []
    skipped = 0
    if vault_dir.exists():
        for md in sorted(vault_dir.glob("*/*/*.md")):
            if md.name.startswith("_"):
                continue
            row = parse_article_md(md)
            if row["url_hash"] in dead:
                skipped += 1
                continue
            row["md_path"] = md.relative_to(vault_dir).as_posix()
            rows.append(row)

        for brief_md in sorted(vault_dir.glob(f"*/{_BRIEF_FILE}")):
            meta, body = _split_frontmatter(brief_md.read_text(encoding="utf-8"))
            brief_rows.append(
                {
                    "category": meta["category"],
                    "brief": body.strip(),
                    "article_count": int(meta.get("article_count", 0)),
                    "updated_at": iso_to_epoch(meta.get("updated_at")) or int(time.time()),
                    "md_path": brief_md.relative_to(vault_dir).as_posix(),
                }
            )

    embeddings: dict[int, tuple] = {}
    enriched_rows = [r for r in rows if r.get("enriched_at")]
    if enriched_rows:
        from . import embed  # 遅延 import (モデルロードが重い)

        for row in enriched_rows:
            text = "\n".join(
                filter(None, [row["title"], row.get("summary"), (row.get("body") or "")[:2000]])
            )
            embeddings[row["id"]] = embed.embed_document(text)

    # ---- ここから1トランザクション。IMMEDIATE で書き込みロックを先取りし、
    # 稼働中の ingest/enrich と衝突しないようにする
    conn.execute("BEGIN IMMEDIATE")
    try:
        store.clear_index(conn)
        for t in tombstones:
            store.add_tombstone(conn, t["url_hash"], t["reason"], t.get("created_at"), commit=False)
        for row in rows:
            store.insert_full_article(conn, row)
            vec = embeddings.get(row["id"])
            if vec is not None:
                store.upsert_embedding(conn, row["id"], vec, commit=False)
        for b in brief_rows:
            store.upsert_category_brief(conn, **b, commit=False)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise

    return {
        "articles": len(rows),
        "briefs": len(brief_rows),
        "tombstones": len(tombstones),
        "skipped_tombstoned": skipped,
        "embeddings": len(embeddings),
    }
