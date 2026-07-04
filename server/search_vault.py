"""vault_search: ローカル記事庫のハイブリッド検索 (spec §8)。

lm-chat の search_memory を移植: FTS5 (trigram) とベクトル近傍
(vec_distance_cosine) を RRF (Reciprocal Rank Fusion) で融合し、
半減期式の時間減衰を掛ける。新しいニュースほど優先される。
"""
from __future__ import annotations

import logging
import math
import re
import struct
import time

from . import store

log = logging.getLogger(__name__)

_RRF_K = 60


def _fts_query(query: str) -> str:
    """空白区切りの各語を AND 検索にする。

    trigram は3文字未満の語をインデックスしないため、短い語は除外する
    (全語が短い場合はフレーズとしてそのまま試す)。
    """
    terms = [t for t in re.split(r"\s+", query.strip()) if len(t) >= 3]
    if terms:
        return " AND ".join('"' + t.replace('"', " ") + '"' for t in terms)
    return '"' + query.replace('"', " ") + '"'


def vault_search(query: str, top_k: int = 8, half_life_days: float = 30.0) -> list[dict]:
    conn = store.connect()
    try:
        scores: dict[int, float] = {}

        # FTS5 (trigram)。語単位 AND + 引用符でフレーズ化して構文エラーを回避
        try:
            rows = conn.execute(
                "SELECT article_id FROM fts_articles WHERE fts_articles MATCH ? "
                "ORDER BY rank LIMIT ?",
                (_fts_query(query), top_k * 4),
            ).fetchall()
            for rank, r in enumerate(rows):
                aid = r["article_id"]
                scores[aid] = scores.get(aid, 0.0) + 1.0 / (_RRF_K + rank + 1)
        except Exception as e:  # noqa: BLE001 - FTS 構文エラー等は vec のみで続行
            log.warning("vault_search fts failed for %r: %s", query, e)

        # ベクトル近傍 (enrich 済み記事のみ埋め込みがある)
        try:
            from . import embed  # 遅延 import (モデルロードが重い)

            vector = embed.embed_query(query)
            blob = struct.pack(f"{len(vector)}f", *vector)
            rows = conn.execute(
                "SELECT article_id, vec_distance_cosine(embedding, ?) AS distance "
                "FROM vec_articles ORDER BY distance ASC LIMIT ?",
                (blob, top_k * 4),
            ).fetchall()
            for rank, r in enumerate(rows):
                aid = r["article_id"]
                scores[aid] = scores.get(aid, 0.0) + 1.0 / (_RRF_K + rank + 1)
        except Exception as e:  # noqa: BLE001
            log.warning("vault_search vec failed for %r: %s", query, e)

        # 時間減衰を掛けてソート
        now = time.time()
        results = []
        for aid, score in scores.items():
            row = store.get_article(conn, aid)
            if row is None or row["status"] == "hidden":
                continue
            if half_life_days > 0:
                days = max(0.0, (now - row["fetched_at"]) / 86400)
                score *= math.pow(0.5, days / half_life_days)
            results.append((score, row))
        results.sort(key=lambda x: x[0], reverse=True)

        return [
            {
                "id": row["id"],
                "title": row["title"],
                "summary": row["summary"],
                "snippet": row["snippet"],
                "url": row["url"],
                "source": row["source"],
                "category": row["category"],
                "fetched_at": row["fetched_at"],
                "md_path": row["md_path"],
                "score": round(score, 6),
            }
            for score, row in results[:top_k]
        ]
    finally:
        conn.close()
