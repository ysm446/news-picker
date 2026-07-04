"""フェーズ1 基盤の検証: dedup / tombstone / MD 書き出し / rebuild。

pytest 不要のスタンドアロン検証。一時ディレクトリで完結し data/ を汚さない。
実行: .venv\\Scripts\\python tests\\test_phase1.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import store, vault  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        db_path = tmp / "news.db"
        vault_dir = tmp / "news-vault"
        conn = store.connect(db_path)
        try:
            run_checks(conn, vault_dir)
        finally:
            conn.close()

    print("OK: dedup / tombstone / MD roundtrip / rebuild / FTS all passed")


def run_checks(conn, vault_dir: Path) -> None:
        # --- 1. URL 正規化と dedup -------------------------------------
        url = "https://Example.com/article/123/?utm_source=x&utm_campaign=y"
        assert store.normalize_url(url) == "https://example.com/article/123"
        a1 = store.insert_article(
            conn, category="gpu", title="NVIDIA raises HBM orders", url=url,
            source="example.com", snippet="snippet text",
        )
        assert a1 is not None, "初回挿入が失敗"
        # トラッキングパラメータ違いの同一 URL は弾かれる
        dup = store.insert_article(
            conn, category="gpu", title="dup", url="https://example.com/article/123?utm_medium=rss",
        )
        assert dup is None, "dedup が効いていない"

        # --- 2. tombstone: 削除した記事は復活しない ---------------------
        a2 = store.insert_article(
            conn, category="gpu", title="To be hidden", url="https://example.com/hide-me",
        )
        h = store.hide_article(conn, a2)
        assert h is not None
        vault.append_tombstone(h, "deleted", vault_dir=vault_dir)
        revived = store.insert_article(
            conn, category="gpu", title="revive?", url="https://example.com/hide-me",
        )
        assert revived is None, "tombstone があるのに再挿入された"

        # --- 3. enrich 相当の更新 + MD 書き出し -------------------------
        now = int(time.time())
        with conn:
            conn.execute(
                """UPDATE articles SET status='seen', summary=?, key_points=?,
                   entities=?, impact=?, tags=?, body=?, enriched_at=? WHERE id=?""",
                (
                    "HBM 発注増の一行要約",
                    json.dumps(["要点その1", "要点その2"], ensure_ascii=False),
                    json.dumps({"tickers": ["NVDA"], "companies": ["NVIDIA"], "models": []},
                               ensure_ascii=False),
                    "bullish",
                    json.dumps(["HBM", "supply-chain"], ensure_ascii=False),
                    "取得した本文テキスト。\n複数行もある。",
                    now,
                    a1,
                ),
            )
        row = dict(store.get_article(conn, a1))
        md_rel = vault.write_article_md(row, vault_dir=vault_dir)
        with conn:
            conn.execute("UPDATE articles SET md_path=? WHERE id=?", (md_rel.as_posix(), a1))
        assert (vault_dir / md_rel).exists()

        # MD -> dict の往復が一致するか
        parsed = vault.parse_article_md(vault_dir / md_rel)
        for key in ("id", "category", "title", "url", "url_hash", "status",
                    "summary", "key_points", "entities", "impact", "tags", "body"):
            expected = dict(store.get_article(conn, a1))[key]
            assert parsed[key] == expected, f"往復不一致 {key}: {parsed[key]!r} != {expected!r}"

        # --- 4. カテゴリ要約 MD ----------------------------------------
        vault.write_category_brief("gpu", "今日の GPU 動向まとめ。", 1, now, vault_dir=vault_dir)

        # --- 5. rebuild: DB を消して vault から全再構築 ------------------
        before = dict(store.get_article(conn, a1))
        stats = vault.rebuild_index(conn, vault_dir=vault_dir)
        assert stats == {"articles": 1, "briefs": 1, "tombstones": 1}, stats

        after = store.get_article(conn, a1)
        assert after is not None, "rebuild 後に記事が消えた"
        after = dict(after)
        for key in ("category", "title", "url", "url_hash", "summary", "impact",
                    "tags", "entities", "key_points", "body", "status"):
            assert after[key] == before[key], f"rebuild 不一致 {key}"

        # rebuild 後も tombstone による復活防止が効く
        revived = store.insert_article(
            conn, category="gpu", title="revive?", url="https://example.com/hide-me",
        )
        assert revived is None, "rebuild 後に tombstone が失われた"

        # FTS が機能している (trigram は3文字以上のクエリで日本語部分一致)
        hit = conn.execute(
            "SELECT article_id FROM fts_articles WHERE fts_articles MATCH ?", ('"一行要約"',)
        ).fetchall()
        assert len(hit) == 1

        brief = conn.execute("SELECT * FROM category_briefs WHERE category='gpu'").fetchone()
        assert brief["brief"] == "今日の GPU 動向まとめ。"


if __name__ == "__main__":
    main()
