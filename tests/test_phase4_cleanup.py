"""CleanupWorker の検証 (一時ディレクトリで完結)。

実行: .venv\\Scripts\\python tests\\test_phase4_cleanup.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="np-cleanup-")
os.environ["NEWS_PICKER_DATA_DIR"] = _tmp  # config 読み込み前に設定する

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import config, store, vault  # noqa: E402
from server.workers.cleanup import CleanupWorker  # noqa: E402


def insert(conn, title: str, url: str, fetched_at: int) -> int:
    aid = store.insert_article(
        conn, category="gpu", title=title, url=url, fetched_at=fetched_at
    )
    assert aid is not None
    return aid


def main() -> None:
    now = int(time.time())
    old = now - 20 * 86400
    conn = store.connect()
    try:
        a_old_new = insert(conn, "old new", "https://example.com/old-new", old)
        a_old_saved = insert(conn, "old saved", "https://example.com/old-saved", old)
        a_recent = insert(conn, "recent", "https://example.com/recent", now)
        store.set_status(conn, a_old_saved, "saved")

        # 古い記事に MD がある場合の削除も確認する
        md_rel = "gpu/2026-06-14/old-new.md"
        md_abs = config.VAULT_DIR / md_rel
        md_abs.parent.mkdir(parents=True, exist_ok=True)
        md_abs.write_text("dummy", encoding="utf-8")
        store.set_md_path(conn, a_old_new, md_rel)
        old_hash = store.get_article(conn, a_old_new)["url_hash"]

        purged = CleanupWorker(retention_days=14).cleanup_once()
        assert purged == 1, f"expected 1 purged, got {purged}"

        # 古い new は消え、saved と recent は残る
        assert store.get_article(conn, a_old_new) is None
        assert store.get_article(conn, a_old_saved) is not None
        assert store.get_article(conn, a_recent) is not None

        # tombstone (DB + vault) と MD 削除
        t = conn.execute(
            "SELECT reason FROM tombstones WHERE url_hash = ?", (old_hash,)
        ).fetchone()
        assert t and t["reason"] == "purged"
        assert any(
            e["url_hash"] == old_hash and e["reason"] == "purged"
            for e in vault.load_tombstones()
        )
        assert not md_abs.exists(), "MD not deleted"

        # tombstone により再取り込みされない
        assert store.insert_article(
            conn, category="gpu", title="revive?", url="https://example.com/old-new"
        ) is None

        # fts / vec からも消えている
        assert conn.execute(
            "SELECT 1 FROM fts_articles WHERE article_id = ?", (a_old_new,)
        ).fetchone() is None
    finally:
        conn.close()
    print("OK: cleanup purge / tombstone / MD deletion / retention all passed")


if __name__ == "__main__":
    main()
