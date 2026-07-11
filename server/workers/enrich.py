"""EnrichWorker: 詳細生成 (spec §6.2)。二層カデンスの「高い側」。

カードクリック時のみキューに積まれ、9B で {summary, key_points, entities,
tags} を JSON 生成する。enrich 済みならキャッシュを返すだけ。

処理: 本文取得 → 9B (thinking 無効 + 構造化出力) → DB 更新 → MD 書き出し
→ 埋め込み (Ruri) + FTS 反映 → status 'seen' → SSE article.enriched。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from .. import config, llm, store, vault
from ..fetch_page import fetch_body
from ..sse import EventBus

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """あなたはニュース編集者。与えられた記事を分析し、指定された JSON 形式で出力する。
- summary: 記事の核心を伝える日本語の一行要約 (60字以内)
- key_points: 重要な事実 2〜5 個 (各 40字以内、日本語)
- entities: 記事に登場する tickers (株式ティッカー)、companies (企業名)、models (AI モデル名)
- tags: 内容を表す短いタグ 1〜5 個"""


def _result_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "key_points": {"type": "array", "items": {"type": "string"},
                           "minItems": 2, "maxItems": 5},
            "entities": {
                "type": "object",
                "properties": {
                    "tickers": {"type": "array", "items": {"type": "string"}},
                    "companies": {"type": "array", "items": {"type": "string"}},
                    "models": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["tickers", "companies", "models"],
            },
            "tags": {"type": "array", "items": {"type": "string"},
                     "minItems": 1, "maxItems": 5},
        },
        "required": ["summary", "key_points", "entities", "tags"],
    }


class EnrichWorker:
    def __init__(self, bus: EventBus, categories: list[config.Category]) -> None:
        self.bus = bus
        self.categories = {c.id: c for c in categories}
        self.queue: asyncio.Queue[int] = asyncio.Queue()
        self._pending: set[int] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def enqueue(self, article_id: int) -> bool:
        if article_id in self._pending:
            return False
        self._pending.add(article_id)
        # 同期エンドポイント (スレッドプール) から呼ばれるため、ループ外からは
        # call_soon_threadsafe で委譲する (asyncio.Queue はスレッドセーフではない)
        loop = self._loop
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if loop is not None and running is not loop:
            loop.call_soon_threadsafe(self.queue.put_nowait, article_id)
        else:
            self.queue.put_nowait(article_id)
        return True

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        while True:
            article_id = await self.queue.get()
            try:
                row = await asyncio.to_thread(self.enrich_sync, article_id)
                if row is not None:
                    self.bus.publish(
                        {
                            "type": "article.enriched",
                            "article": {
                                "id": row["id"],
                                "status": row["status"],
                                "summary": row["summary"],
                                "key_points": json.loads(row["key_points"] or "[]"),
                                "entities": json.loads(row["entities"] or "null"),
                                "tags": json.loads(row["tags"] or "[]"),
                                "enriched_at": row["enriched_at"],
                            },
                        }
                    )
            except Exception as e:  # noqa: BLE001
                log.exception("enrich[%d] failed", article_id)
                self.bus.publish(
                    {"type": "article.enrich_failed", "id": article_id, "detail": str(e)[:200]}
                )
            finally:
                self._pending.discard(article_id)

    def enrich_sync(self, article_id: int) -> dict | None:
        """同期の enrich 本体。enrich 済みなら何もせず None (再生成しない)。"""
        conn = store.connect()
        try:
            row = store.get_article(conn, article_id)
            if row is None:
                log.warning("enrich[%d]: article not found", article_id)
                return None
            if row["enriched_at"]:
                return None  # キャッシュ済み。イベントも不要 (クライアントは GET で取得済み)

            category = self.categories.get(row["category"])

            body = fetch_body(row["url"])
            source_text = body or row["snippet"] or ""

            result = llm.chat(
                [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"カテゴリ: {category.label if category else row['category']}\n\n"
                            f"タイトル: {row['title']}\n"
                            f"ソース: {row['source'] or '不明'}\n\n"
                            f"本文:\n{source_text}"
                        ),
                    },
                ],
                base_url=config.LLM_STANDARD_URL,
                response_json_schema=_result_schema(),
                enable_thinking=False,
                # 1024 だと長い記事で JSON が途中で切れることがあり、新しめの
                # llama.cpp はそれを出力パースエラー (500) にする。余裕を持たせる
                max_tokens=2048,
                timeout=180,
            )
            data = json.loads(result["content"])
            summary = data["summary"]

            # 埋め込みを先に計算する (ここで失敗しても DB は未 enrich のままなので
            # 再クリックで再試行できる。DB 確定後の失敗だと自己修復不能になる)
            from .. import embed  # 遅延 import (モデルロードが重い)

            embedding_text = "\n".join(
                filter(None, [row["title"], summary, (body or "")[:2000]])
            )
            vector = embed.embed_document(embedding_text)

            # MD (一次データ) を DB より先に書く。直後に落ちても DB は未 enrich の
            # ままで再実行が同じ MD を上書きして自己修復する。逆順だと
            # 「enrich 済みだが MD なし」で確定し rebuild で結果が消える
            enriched_at = int(time.time())
            fresh = dict(row)
            fresh.update(
                summary=summary,
                key_points=json.dumps(data["key_points"], ensure_ascii=False),
                entities=json.dumps(data["entities"], ensure_ascii=False),
                impact=None,  # 廃止項目 (DB 列と既存 MD の互換のため残置)
                tags=json.dumps(data["tags"], ensure_ascii=False),
                body=body,
                enriched_at=enriched_at,
                status="seen" if row["status"] == "new" else row["status"],
            )
            md_rel = vault.write_article_md(fresh)

            store.update_enrichment(
                conn,
                article_id,
                summary=summary,
                key_points=fresh["key_points"],
                entities=fresh["entities"],
                impact=None,
                tags=fresh["tags"],
                body=body,
                enriched_at=enriched_at,
            )
            store.set_md_path(conn, article_id, md_rel.as_posix())
            store.update_fts(conn, article_id, row["title"], summary, body)
            store.upsert_embedding(conn, article_id, vector)

            log.info("enrich[%d] done: %s", article_id, summary[:50])
            return store.get_article(conn, article_id)
        finally:
            conn.close()
