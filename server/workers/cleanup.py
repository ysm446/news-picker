"""CleanupWorker: 自動整理 (spec §6.4)。日次実行。

new/seen のまま retention_days を超えた記事を tombstones('purged') に退避して
DB (articles/fts/vec) から削除する。saved / hidden は対象外。

仕様からの拡張: 記事 MD も vault から削除する。残すと rebuild で復活して
tombstone と矛盾するため (「MD が真実の源」なので、消すなら MD ごと消す)。
tombstone は vault 側 (_tombstones.jsonl) にも記録する。
"""
from __future__ import annotations

import asyncio
import logging

from .. import config, settings_store, store, vault

log = logging.getLogger(__name__)

_INTERVAL_SEC = 24 * 3600


class CleanupWorker:
    def __init__(self, retention_days: int | None = None) -> None:
        # None なら実行のたびに環境設定 (data/settings.json) から読む
        self.retention_days = retention_days

    def cleanup_once(self) -> int:
        retention = self.retention_days or int(
            settings_store.get().get("retention_days", config.RETENTION_DAYS)
        )
        conn = store.connect()
        purged = 0
        try:
            for row in store.find_purgeable(conn, retention):
                store.add_tombstone(conn, row["url_hash"], "purged")
                vault.append_tombstone(row["url_hash"], "purged")
                store.delete_article_index(conn, row["id"])
                if row["md_path"]:
                    md = config.VAULT_DIR / row["md_path"]
                    md.unlink(missing_ok=True)
                purged += 1
        finally:
            conn.close()
        if purged:
            log.info("cleanup: purged %d articles (older than %dd)", purged, retention)
        return purged

    async def run(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.cleanup_once)
            except Exception:  # noqa: BLE001
                log.exception("cleanup failed")
            await asyncio.sleep(_INTERVAL_SEC)
