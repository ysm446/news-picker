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
    """DB 行 (dict) から記事 MD を書き出し、vault 相対の md_path を返す。"""
    vault_dir = Path(vault_dir or config.VAULT_DIR)
    date_dir = datetime.fromtimestamp(
        article["fetched_at"], tz=timezone.utc
    ).strftime("%Y-%m-%d")
    rel = Path(article["category"]) / date_dir / f"{_slugify(article['title'])}-{article['id']}.md"

    meta = {
        "id": article["id"],
        "category": article["category"],
        "title": article["title"],
        "url": article["url"],
        "source": article.get("source"),
        "snippet": article.get("snippet"),
        "published_at": epoch_to_iso(article.get("published_at")),
        "fetched_at": epoch_to_iso(article["fetched_at"]),
        "enriched_at": epoch_to_iso(article.get("enriched_at")),
        "status": article.get("status", "new"),
        "entities": _load_json_field(article.get("entities")),
        "impact": article.get("impact"),
        "tags": _load_json_field(article.get("tags")),
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

    埋め込み (vec_articles) はここでは復元しない。EnrichWorker/再埋め込み
    バッチが埋め直す (フェーズ3)。
    """
    vault_dir = Path(vault_dir or config.VAULT_DIR)
    store.clear_index(conn)

    articles = briefs = 0
    if vault_dir.exists():
        for md in sorted(vault_dir.glob("*/*/*.md")):
            if md.name.startswith("_"):
                continue
            row = parse_article_md(md)
            row["md_path"] = md.relative_to(vault_dir).as_posix()
            store.insert_full_article(conn, row)
            articles += 1

        for brief_md in sorted(vault_dir.glob(f"*/{_BRIEF_FILE}")):
            meta, body = _split_frontmatter(brief_md.read_text(encoding="utf-8"))
            store.upsert_category_brief(
                conn,
                category=meta["category"],
                brief=body.strip(),
                article_count=int(meta.get("article_count", 0)),
                updated_at=iso_to_epoch(meta.get("updated_at")) or int(time.time()),
                md_path=brief_md.relative_to(vault_dir).as_posix(),
            )
            briefs += 1

    tombstones = load_tombstones(vault_dir)
    for t in tombstones:
        store.add_tombstone(conn, t["url_hash"], t["reason"], t.get("created_at"))

    return {"articles": articles, "briefs": briefs, "tombstones": len(tombstones)}
