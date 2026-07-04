"""フェーズ2 スモークテスト: API + SSE + 取り込み + rebuild。

uvicorn を一時データディレクトリで起動し、実際に HTTP/SSE でエンドツーエンド
確認する。ddgs のライブ検索を1回叩く (0件でもテスト自体は継続できる設計)。
実行: .venv\\Scripts\\python tests\\test_phase2_smoke.py
"""
from __future__ import annotations

import json
import queue
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PORT = 8199  # 開発中の本番バックエンド (8100) と衝突しないテスト専用ポート
BASE = f"http://127.0.0.1:{PORT}"


def req(method: str, path: str, timeout: float = 30.0):
    r = urllib.request.Request(f"{BASE}{path}", method=method)
    with urllib.request.urlopen(r, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8"))


def sse_reader(events: queue.Queue, stop: threading.Event) -> None:
    r = urllib.request.Request(f"{BASE}/events")
    with urllib.request.urlopen(r, timeout=60) as res:
        for raw in res:
            if stop.is_set():
                break
            line = raw.decode("utf-8").strip()
            if line.startswith("data: "):
                events.put(json.loads(line[6:]))


def wait_event(events: queue.Queue, event_type: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            ev = events.get(timeout=1.0)
        except queue.Empty:
            continue
        if ev.get("type") == event_type:
            return ev
    raise AssertionError(f"SSE event {event_type!r} not received in {timeout}s")


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="np-smoke-"))
    env = {
        "NEWS_PICKER_DATA_DIR": str(tmp),
        "NEWS_PICKER_NO_INGEST": "1",
        "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
        "PATH": __import__("os").environ.get("PATH", ""),
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.api:app", "--port", str(PORT)],
        cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    stop = threading.Event()
    try:
        # 起動待ち
        for _ in range(60):
            try:
                cats = req("GET", "/categories")
                break
            except OSError:
                time.sleep(0.5)
        else:
            raise AssertionError("server did not start")
        # 雛形 (categories.example.yaml) からコピーされたカテゴリで起動する
        assert {"semiconductor-stocks", "gpu", "local-llm"}.issubset({c["id"] for c in cats})
        assert all(c["unread"] == 0 for c in cats)

        # SSE 購読開始
        events: queue.Queue = queue.Queue()
        t = threading.Thread(target=sse_reader, args=(events, stop), daemon=True)
        t.start()
        time.sleep(1.0)

        # 取り込み (ddgs ライブ)。ネットワーク状況次第で 0 件もあり得る
        r = req("POST", "/admin/ingest-now?category=semiconductor-stocks", timeout=60)
        print(f"ingest-now: {r['new']} new articles (live ddgs)")
        if r["new"] > 0:
            ev = wait_event(events, "article.new")
            assert ev["category"] == "semiconductor-stocks"
            assert ev["article"]["title"]
            print(f"SSE article.new OK: {ev['article']['title'][:60]}")
        else:
            # ライブ検索が空でも API 検証は続ける
            from server import store
            conn = store.connect(tmp / "news.db")
            store.insert_article(
                conn, category="gpu", title="fallback article",
                url="https://example.com/fallback",
            )
            conn.close()
            print("WARN: ddgs returned 0 results; inserted fallback article")

        articles = req("GET", "/articles")
        assert len(articles) >= 1, "no articles listed"
        aid = articles[0]["id"]

        # 保存 → SSE
        r = req("POST", f"/articles/{aid}/save")
        assert r["status"] == "saved"
        ev = wait_event(events, "article.status_changed")
        assert ev["id"] == aid and ev["status"] == "saved"
        print("save + SSE status_changed OK")

        # 非表示 → tombstone (DB + vault) → SSE
        r = req("POST", f"/articles/{aid}/hide")
        assert r["status"] == "hidden"
        wait_event(events, "article.status_changed")
        assert (tmp / "news-vault" / "_tombstones.jsonl").exists()
        assert all(a["id"] != aid for a in req("GET", "/articles"))
        print("hide + vault tombstone OK")

        # rebuild: 未 enrich 記事は MD が無いので消え、tombstone は残る
        stats = req("POST", "/admin/rebuild-index")
        assert stats["tombstones"] >= 1, stats
        assert stats["articles"] == 0, stats
        print(f"rebuild OK: {stats}")

        print("OK: phase2 smoke test passed")
    finally:
        stop.set()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
