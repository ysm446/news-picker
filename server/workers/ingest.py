"""IngestWorker: 高速取り込みループ (spec §6.1)。

カテゴリごとに poll_interval_sec + ジッタで回り、query_templates を
ローテーションしながら検索 → dedup → status='new' で挿入 → SSE 配信。
LLM は一切通さない (二層カデンスの安い側)。
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import random
from datetime import datetime

from .. import config, curator, llm, settings_store, store
from ..search_web import search_news
from ..sse import EventBus

log = logging.getLogger(__name__)

_MIN_SLEEP_SEC = 30  # 設定ミスでも検索先を叩きすぎない下限


class IngestWorker:
    def __init__(self, category: config.Category, bus: EventBus) -> None:
        self.category = category
        self.bus = bus
        self._queries = itertools.cycle(category.query_templates)

    def _next_query(self) -> str:
        query = next(self._queries)
        return query.replace("{month}", datetime.now().strftime("%Y年%m月"))

    def ingest_once(self) -> list[dict]:
        """1回分の取り込み (同期)。挿入した記事の SSE ペイロードを返す。"""
        query = self._next_query()
        results = search_news(query)
        inserted: list[dict] = []
        conn = store.connect()
        try:
            for r in results:
                article_id = store.insert_article(
                    conn,
                    category=self.category.id,
                    title=r["title"],
                    url=r["url"],
                    source=r["source"],
                    snippet=r["snippet"],
                    published_at=r["published_at"],
                )
                if article_id is None:
                    continue
                row = store.get_article(conn, article_id)
                inserted.append(
                    {
                        "id": row["id"],
                        "title": row["title"],
                        "source": row["source"],
                        "snippet": row["snippet"],
                        "fetched_at": row["fetched_at"],
                    }
                )
        finally:
            conn.close()
        log.info(
            "ingest[%s] query=%r results=%d new=%d",
            self.category.id, query, len(results), len(inserted),
        )
        return inserted

    def publish_new(self, inserted: list[dict]) -> None:
        for article in inserted:
            self.bus.publish(
                {"type": "article.new", "category": self.category.id, "article": article}
            )

    def curate_sync(self, inserted: list[dict]) -> dict[int, dict]:
        """新着バッチを 9B で採点 (+設定オン時は日本語訳) して DB に反映する。"""
        if not inserted or not llm.health(config.LLM_STANDARD_URL):
            return {}
        translate = bool(settings_store.get().get("translate_titles"))
        conn = store.connect()
        try:
            examples = store.get_feedback_examples(conn, self.category.id)
        finally:
            conn.close()
        results = curator.score_articles(
            self.category, inserted, translate=translate, examples=examples
        )
        if results:
            conn = store.connect()
            try:
                store.set_curation(conn, results)
                if translate:
                    # 採点時に 9B が翻訳をサボることがあるため、漏れを翻訳専用パスで補完
                    missed = [
                        a for a in inserted
                        if curator.needs_translation(a["title"])
                        and not (results.get(a["id"]) or {}).get("title_ja")
                    ]
                    translations = curator.translate_titles(missed)
                    if translations:
                        store.set_title_ja(conn, translations)
                        for article_id, title_ja in translations.items():
                            entry = results.setdefault(article_id, {"score": None})
                            entry["title_ja"] = title_ja
            finally:
                conn.close()
        return results

    def publish_scores(self, results: dict[int, dict]) -> None:
        if results:
            self.bus.publish(
                {
                    "type": "article.curated",
                    "scores": [
                        {
                            "id": article_id,
                            "relevance": r["score"],
                            "title_ja": r.get("title_ja"),
                        }
                        for article_id, r in results.items()
                    ],
                }
            )

    async def run(self) -> None:
        """常駐ループ。個々の失敗はログして次周期で再試行する。"""
        # 起動直後の全カテゴリ同時叩きを避ける初期ジッタ
        await asyncio.sleep(random.uniform(0, min(30, self.category.jitter_sec)))
        while True:
            try:
                inserted = await asyncio.to_thread(self.ingest_once)
                self.publish_new(inserted)  # タイトルは採点を待たず即配信
                scores = await asyncio.to_thread(self.curate_sync, inserted)
                self.publish_scores(scores)
            except Exception:  # noqa: BLE001
                log.exception("ingest[%s] failed", self.category.id)
            delay = self.category.poll_interval_sec + random.uniform(
                -self.category.jitter_sec, self.category.jitter_sec
            )
            await asyncio.sleep(max(_MIN_SLEEP_SEC, delay))
