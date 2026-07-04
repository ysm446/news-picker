"""BriefWorker: カテゴリ要約のロールアップ (spec §6.3)。

新着トリガ + デバウンス: 前回要約以降に新着があり、かつ N 件たまった or
T 分経過で生成する。差分ではなく直近 max_window 件全体を毎回渡して
作り直す (文脈の一貫性のため)。生成は 9B・thinking 無効。
"""
from __future__ import annotations

import asyncio
import logging
import time

from .. import config, llm, store, vault
from ..sse import EventBus

log = logging.getLogger(__name__)

CHECK_INTERVAL_SEC = 60   # デバウンス判定の周期
MIN_NEW_ARTICLES = 3      # これだけ新着がたまったら即生成
MAX_WAIT_SEC = 900        # 新着1件でも T 分経過したら生成


class BriefWorker:
    def __init__(self, bus: EventBus, categories: list[config.Category]) -> None:
        self.bus = bus
        self.categories = categories

    def maybe_generate(self, category: config.Category, force: bool = False) -> dict | None:
        """デバウンス条件を満たせばロールアップを生成。生成しなければ None。"""
        conn = store.connect()
        try:
            brief_row = conn.execute(
                "SELECT updated_at FROM category_briefs WHERE category = ?", (category.id,)
            ).fetchone()
            last_updated = brief_row["updated_at"] if brief_row else 0

            new_count = conn.execute(
                """SELECT COUNT(*) AS n FROM articles
                   WHERE category = ? AND status != 'hidden' AND fetched_at > ?""",
                (category.id, last_updated),
            ).fetchone()["n"]

            if not force:
                if new_count == 0:
                    return None
                waited = time.time() - last_updated
                if brief_row and new_count < MIN_NEW_ARTICLES and waited < MAX_WAIT_SEC:
                    return None

            rows = conn.execute(
                """SELECT title, summary, source FROM articles
                   WHERE category = ? AND status != 'hidden'
                   ORDER BY fetched_at DESC LIMIT ?""",
                (category.id, category.max_window),
            ).fetchall()
            if not rows:
                return None

            lines = []
            for r in rows:
                line = f"- {r['title']}"
                if r["source"]:
                    line += f" ({r['source']})"
                if r["summary"]:
                    line += f" — {r['summary']}"
                lines.append(line)

            result = llm.chat(
                [
                    {"role": "system", "content": category.summary_prompt.strip()},
                    {
                        "role": "user",
                        "content": (
                            f"以下は「{category.label}」カテゴリの直近記事一覧 ({len(rows)}件)。\n"
                            "この一覧から現在の状況を要約せよ。前置きは不要。\n\n"
                            + "\n".join(lines)
                        ),
                    },
                ],
                base_url=config.LLM_9B_URL,
                enable_thinking=False,
                max_tokens=600,
                timeout=180,
            )
            brief = result["content"].strip()
            if not brief:
                log.warning("brief[%s]: empty response", category.id)
                return None

            now = int(time.time())
            md_rel = vault.write_category_brief(category.id, brief, len(rows), now)
            store.upsert_category_brief(
                conn, category.id, brief, len(rows), now, md_rel.as_posix()
            )
            log.info("brief[%s] updated (%d articles)", category.id, len(rows))
            return {"category": category.id, "brief": brief, "updated_at": now}
        finally:
            conn.close()

    async def run(self) -> None:
        while True:
            for category in self.categories:
                try:
                    result = await asyncio.to_thread(self.maybe_generate, category)
                    if result:
                        self.bus.publish({"type": "category.brief_updated", **result})
                except Exception:  # noqa: BLE001
                    log.exception("brief[%s] failed", category.id)
            await asyncio.sleep(CHECK_INTERVAL_SEC)
