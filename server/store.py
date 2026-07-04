"""SQLite ストア: articles / tombstones / category_briefs / FTS5 / sqlite-vec。

設計原則: MD (news-vault) が真実の源で、この DB は再構築可能な派生索引
(docs/news-picker-spec.md §4)。dedup は articles と tombstones の両方を参照し、
削除・パージ済み記事が再取得で復活しないようにする。
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import struct
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import sqlite_vec

from . import config

EMBEDDING_DIM = 768  # Ruri v3-310m の出力次元。vec_articles の定義と一致させる

# FTS5 は外部コンテンツ表ではなく独立テーブル + 手動同期
# (lm-chat の実績パターン。trigram で日本語の分かち書きなし部分一致が効く)
_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS articles (
  id           INTEGER PRIMARY KEY,
  category     TEXT NOT NULL,
  title        TEXT NOT NULL,
  url          TEXT NOT NULL UNIQUE,
  url_hash     TEXT NOT NULL,
  source       TEXT,
  snippet      TEXT,
  published_at INTEGER,
  fetched_at   INTEGER NOT NULL,
  status       TEXT NOT NULL DEFAULT 'new',
  summary      TEXT,
  key_points   TEXT,
  entities     TEXT,
  impact       TEXT,
  tags         TEXT,
  body         TEXT,
  md_path      TEXT,
  enriched_at  INTEGER,
  relevance    INTEGER,                    -- キュレーション採点 0-100 (NULL = 未採点)
  title_ja     TEXT                        -- 見出しの日本語訳 (設定オン時のみ生成)
);
CREATE INDEX IF NOT EXISTS idx_articles_cat_status
  ON articles(category, status, fetched_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_hash ON articles(url_hash);

CREATE TABLE IF NOT EXISTS tombstones (
  url_hash   TEXT PRIMARY KEY,
  reason     TEXT NOT NULL,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS category_briefs (
  category      TEXT PRIMARY KEY,
  brief         TEXT NOT NULL,
  article_count INTEGER NOT NULL,
  updated_at    INTEGER NOT NULL,
  md_path       TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS fts_articles USING fts5(
  article_id UNINDEXED, title, summary, body, tokenize='trigram'
);

CREATE VIRTUAL TABLE IF NOT EXISTS vec_articles USING vec0(
  article_id INTEGER PRIMARY KEY,
  embedding  FLOAT[{EMBEDDING_DIM}]
);
"""

_TRACKING_PARAM = re.compile(r"^(utm_|fbclid$|gclid$|yclid$|igshid$|mc_cid$|mc_eid$)")


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    db_path = Path(db_path or config.DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(_SCHEMA)
    # 既存 DB へのカラム追加 (冪等)
    for ddl in (
        "ALTER TABLE articles ADD COLUMN relevance INTEGER",
        "ALTER TABLE articles ADD COLUMN title_ja TEXT",
    ):
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass
    return conn


# ---------------------------------------------------------------- dedup

def normalize_url(url: str) -> str:
    """utm 等のトラッキングパラメータ除去・末尾スラッシュ・大文字小文字を正規化。"""
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    host = parts.netloc.lower()
    if scheme == "http" and host.endswith(":80"):
        host = host[:-3]
    if scheme == "https" and host.endswith(":443"):
        host = host[:-4]
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(
        [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not _TRACKING_PARAM.match(k.lower())
        ]
    )
    return urlunsplit((scheme, host, path, query, ""))


def url_hash(url: str) -> str:
    return hashlib.sha1(normalize_url(url).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- articles

def insert_article(
    conn: sqlite3.Connection,
    *,
    category: str,
    title: str,
    url: str,
    source: str | None = None,
    snippet: str | None = None,
    published_at: int | None = None,
    fetched_at: int | None = None,
) -> int | None:
    """dedup を通った場合のみ status='new' で挿入。重複/墓石は None を返す。"""
    h = url_hash(url)
    if conn.execute("SELECT 1 FROM articles WHERE url_hash = ?", (h,)).fetchone():
        return None
    if conn.execute("SELECT 1 FROM tombstones WHERE url_hash = ?", (h,)).fetchone():
        return None
    fetched_at = fetched_at or int(time.time())
    try:
        with conn:
            cur = conn.execute(
                """INSERT INTO articles
                   (category, title, url, url_hash, source, snippet,
                    published_at, fetched_at, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new')""",
                (category, title, url, h, source, snippet, published_at, fetched_at),
            )
            article_id = cur.lastrowid
            conn.execute(
                "INSERT INTO fts_articles (article_id, title, summary, body) VALUES (?, ?, '', '')",
                (article_id, title),
            )
    except sqlite3.IntegrityError:
        return None  # 並行挿入とのレース。UNIQUE 制約側で弾く
    return article_id


def get_article(conn: sqlite3.Connection, article_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()


def set_status(conn: sqlite3.Connection, article_id: int, status: str) -> None:
    if status not in ("new", "seen", "saved", "hidden"):
        raise ValueError(f"invalid status: {status}")
    with conn:
        conn.execute("UPDATE articles SET status = ? WHERE id = ?", (status, article_id))


def hide_article(conn: sqlite3.Connection, article_id: int) -> str | None:
    """status='hidden' + tombstone('deleted') 登録。url_hash を返す(vault 側の記録用)。"""
    row = get_article(conn, article_id)
    if row is None:
        return None
    with conn:
        conn.execute("UPDATE articles SET status = 'hidden' WHERE id = ?", (article_id,))
        add_tombstone(conn, row["url_hash"], "deleted", commit=False)
    return row["url_hash"]


def set_curation(conn: sqlite3.Connection, results: dict[int, dict]) -> None:
    """キュレーション結果 (score + 任意の title_ja) を反映する。"""
    with conn:
        conn.executemany(
            "UPDATE articles SET relevance = ?, title_ja = COALESCE(?, title_ja) WHERE id = ?",
            [
                (r["score"], r.get("title_ja"), article_id)
                for article_id, r in results.items()
            ],
        )


def add_tombstone(
    conn: sqlite3.Connection,
    h: str,
    reason: str,
    created_at: int | None = None,
    commit: bool = True,
) -> None:
    sql = "INSERT OR IGNORE INTO tombstones (url_hash, reason, created_at) VALUES (?, ?, ?)"
    args = (h, reason, created_at or int(time.time()))
    if commit:
        with conn:
            conn.execute(sql, args)
    else:
        conn.execute(sql, args)


# ---------------------------------------------------------------- enrich

def update_enrichment(
    conn: sqlite3.Connection,
    article_id: int,
    *,
    summary: str,
    key_points: str,
    entities: str,
    impact: str | None,
    tags: str,
    body: str | None,
    enriched_at: int | None = None,
) -> None:
    """詳細生成の結果を反映し、status new は seen に進める。"""
    with conn:
        conn.execute(
            """UPDATE articles SET
                 summary = ?, key_points = ?, entities = ?, impact = ?, tags = ?,
                 body = ?, enriched_at = ?,
                 status = CASE WHEN status = 'new' THEN 'seen' ELSE status END
               WHERE id = ?""",
            (summary, key_points, entities, impact, tags, body,
             enriched_at or int(time.time()), article_id),
        )


def set_md_path(conn: sqlite3.Connection, article_id: int, md_path: str) -> None:
    with conn:
        conn.execute("UPDATE articles SET md_path = ? WHERE id = ?", (md_path, article_id))


def update_fts(
    conn: sqlite3.Connection,
    article_id: int,
    title: str,
    summary: str | None,
    body: str | None,
) -> None:
    with conn:
        conn.execute("DELETE FROM fts_articles WHERE article_id = ?", (article_id,))
        conn.execute(
            "INSERT INTO fts_articles (article_id, title, summary, body) VALUES (?, ?, ?, ?)",
            (article_id, title, summary or "", body or ""),
        )


def upsert_embedding(conn: sqlite3.Connection, article_id: int, vector) -> None:
    blob = struct.pack(f"{len(vector)}f", *vector)
    with conn:
        conn.execute("DELETE FROM vec_articles WHERE article_id = ?", (article_id,))
        conn.execute(
            "INSERT INTO vec_articles (article_id, embedding) VALUES (?, ?)",
            (article_id, blob),
        )


# ---------------------------------------------------------------- 自動整理

def find_purgeable(conn: sqlite3.Connection, retention_days: int) -> list[sqlite3.Row]:
    """パージ対象: status new/seen かつ fetched_at が retention_days より古い行。"""
    cutoff = int(time.time()) - retention_days * 86400
    return conn.execute(
        """SELECT id, url_hash, md_path FROM articles
           WHERE status IN ('new', 'seen') AND fetched_at < ?""",
        (cutoff,),
    ).fetchall()


def delete_article_index(conn: sqlite3.Connection, article_id: int) -> None:
    """記事を articles / fts / vec から削除する (tombstone 登録は呼び出し側)。"""
    with conn:
        conn.execute("DELETE FROM articles WHERE id = ?", (article_id,))
        conn.execute("DELETE FROM fts_articles WHERE article_id = ?", (article_id,))
        conn.execute("DELETE FROM vec_articles WHERE article_id = ?", (article_id,))


# ---------------------------------------------------------------- rebuild 用

def clear_index(conn: sqlite3.Connection) -> None:
    """全派生データを消す。vault からの rebuild 直前にのみ使う。"""
    with conn:
        conn.execute("DELETE FROM articles")
        conn.execute("DELETE FROM tombstones")
        conn.execute("DELETE FROM category_briefs")
        conn.execute("DELETE FROM fts_articles")
        conn.execute("DELETE FROM vec_articles")


def insert_full_article(conn: sqlite3.Connection, row: dict) -> None:
    """rebuild 用: MD frontmatter 由来の全カラムを id ごと復元する。"""
    cols = (
        "id", "category", "title", "url", "url_hash", "source", "snippet",
        "published_at", "fetched_at", "status", "summary", "key_points",
        "entities", "impact", "tags", "body", "md_path", "enriched_at",
        "relevance", "title_ja",
    )
    values = [row.get(c) for c in cols]
    with conn:
        conn.execute(
            f"INSERT INTO articles ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            values,
        )
        conn.execute(
            "INSERT INTO fts_articles (article_id, title, summary, body) VALUES (?, ?, ?, ?)",
            (row["id"], row.get("title", ""), row.get("summary") or "", row.get("body") or ""),
        )


def upsert_category_brief(
    conn: sqlite3.Connection,
    category: str,
    brief: str,
    article_count: int,
    updated_at: int,
    md_path: str | None = None,
) -> None:
    with conn:
        conn.execute(
            """INSERT INTO category_briefs (category, brief, article_count, updated_at, md_path)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(category) DO UPDATE SET
                 brief = excluded.brief,
                 article_count = excluded.article_count,
                 updated_at = excluded.updated_at,
                 md_path = excluded.md_path""",
            (category, brief, article_count, updated_at, md_path),
        )
