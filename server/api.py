"""FastAPI ルート (spec §10)。

起動: .venv\\Scripts\\python -m uvicorn server.api:app --port 8100
環境変数:
  NEWS_PICKER_NO_INGEST=1  取り込みループを起動しない (開発・テスト用。
                           POST /admin/ingest-now での手動取り込みは可能)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import config, store, vault
from .sse import EventBus, format_sse
from .workers.brief import BriefWorker
from .workers.cleanup import CleanupWorker
from .workers.enrich import EnrichWorker
from .workers.ingest import IngestWorker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logging.getLogger("primp").setLevel(logging.WARNING)  # ddgs の HTTP ログを抑制

bus = EventBus()
workers: dict[str, IngestWorker] = {}
enricher: EnrichWorker | None = None
briefer: BriefWorker | None = None
cleaner = CleanupWorker()


def _load_json(value):
    return json.loads(value) if value else None


def _article_to_dict(row) -> dict:
    d = dict(row)
    for key in ("key_points", "entities", "tags"):
        d[key] = _load_json(d.get(key))
    return d


@asynccontextmanager
async def lifespan(app: FastAPI):
    global enricher, briefer
    categories = config.load_categories()
    for cat in categories:
        workers[cat.id] = IngestWorker(cat, bus)
    enricher = EnrichWorker(bus, categories)
    briefer = BriefWorker(bus, categories)
    tasks: list[asyncio.Task] = [asyncio.create_task(enricher.run())]
    if not os.environ.get("NEWS_PICKER_NO_INGEST"):
        tasks += [asyncio.create_task(w.run()) for w in workers.values()]
        tasks.append(asyncio.create_task(briefer.run()))
        tasks.append(asyncio.create_task(cleaner.run()))
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="news-picker", lifespan=lifespan)

# ローカル専用 API。Electron renderer (vite dev / file://) からのアクセスを許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "null"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------- categories

@app.get("/categories")
def list_categories() -> list[dict]:
    conn = store.connect()
    try:
        counts = {
            r["category"]: r["n"]
            for r in conn.execute(
                "SELECT category, COUNT(*) AS n FROM articles WHERE status = 'new' GROUP BY category"
            )
        }
    finally:
        conn.close()
    return [
        {
            "id": c.id,
            "label": c.label,
            "poll_interval_sec": c.poll_interval_sec,
            "impact_axis": c.impact_axis,
            "unread": counts.get(c.id, 0),
        }
        for c in config.load_categories()
    ]


@app.get("/categories/{category_id}/brief")
def get_brief(category_id: str) -> dict:
    conn = store.connect()
    try:
        row = conn.execute(
            "SELECT * FROM category_briefs WHERE category = ?", (category_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404, f"no brief for category {category_id}")
    return dict(row)


# ---------------------------------------------------------------- articles

@app.get("/articles")
def list_articles(
    category: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    sql = "SELECT * FROM articles WHERE 1=1"
    args: list = []
    if category:
        sql += " AND category = ?"
        args.append(category)
    if status:
        sql += " AND status = ?"
        args.append(status)
    else:
        sql += " AND status != 'hidden'"
    sql += " ORDER BY fetched_at DESC LIMIT ? OFFSET ?"
    args += [min(limit, 500), offset]
    conn = store.connect()
    try:
        rows = conn.execute(sql, args).fetchall()
    finally:
        conn.close()
    return [_article_to_dict(r) for r in rows]


@app.get("/articles/{article_id}")
def get_article(article_id: int) -> dict:
    conn = store.connect()
    try:
        row = store.get_article(conn, article_id)
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404, f"article {article_id} not found")
    d = _article_to_dict(row)
    # 未 enrich なら詳細生成をトリガ (spec §10)。完了は SSE article.enriched で通知
    if not d["enriched_at"] and enricher is not None:
        d["enrich_queued"] = enricher.enqueue(article_id) or True
    return d


@app.post("/articles/{article_id}/enrich")
def enqueue_enrich(article_id: int) -> dict:
    conn = store.connect()
    try:
        row = store.get_article(conn, article_id)
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404, f"article {article_id} not found")
    if row["enriched_at"]:
        return {"id": article_id, "queued": False, "cached": True}
    assert enricher is not None
    return {"id": article_id, "queued": enricher.enqueue(article_id), "cached": False}


@app.post("/articles/{article_id}/save")
def save_article(article_id: int) -> dict:
    conn = store.connect()
    try:
        if store.get_article(conn, article_id) is None:
            raise HTTPException(404, f"article {article_id} not found")
        store.set_status(conn, article_id, "saved")
    finally:
        conn.close()
    bus.publish({"type": "article.status_changed", "id": article_id, "status": "saved"})
    return {"id": article_id, "status": "saved"}


@app.post("/articles/{article_id}/hide")
def hide_article(article_id: int) -> dict:
    conn = store.connect()
    try:
        url_hash = store.hide_article(conn, article_id)
    finally:
        conn.close()
    if url_hash is None:
        raise HTTPException(404, f"article {article_id} not found")
    vault.append_tombstone(url_hash, "deleted")  # rebuild 後も復活しないよう vault 側にも記録
    bus.publish({"type": "article.status_changed", "id": article_id, "status": "hidden"})
    return {"id": article_id, "status": "hidden"}


# ---------------------------------------------------------------- SSE

@app.get("/events")
async def events() -> StreamingResponse:
    q = bus.subscribe()

    async def gen():
        try:
            yield ": connected\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                    yield format_sse(event)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # 接続維持
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream")


# ---------------------------------------------------------------- admin

@app.post("/admin/rebuild-index")
def rebuild_index() -> dict:
    conn = store.connect()
    try:
        stats = vault.rebuild_index(conn)
    finally:
        conn.close()
    return stats


@app.post("/admin/ingest-now")
async def ingest_now(category: str) -> dict:
    """開発用: ポーリングを待たずに1回取り込む。"""
    worker = workers.get(category)
    if worker is None:
        raise HTTPException(404, f"unknown category {category}")
    inserted = await asyncio.to_thread(worker.ingest_once)
    worker.publish_new(inserted)
    return {"category": category, "new": len(inserted)}


@app.post("/admin/brief-now")
async def brief_now(category: str) -> dict:
    """開発用: デバウンスを無視してカテゴリ要約を生成する。"""
    assert briefer is not None
    target = next((c for c in briefer.categories if c.id == category), None)
    if target is None:
        raise HTTPException(404, f"unknown category {category}")
    result = await asyncio.to_thread(briefer.maybe_generate, target, True)
    if result:
        bus.publish({"type": "category.brief_updated", **result})
        return result
    return {"category": category, "brief": None}


@app.post("/admin/cleanup-now")
async def cleanup_now() -> dict:
    """開発用: 日次を待たずに自動整理を実行する。"""
    purged = await asyncio.to_thread(cleaner.cleanup_once)
    return {"purged": purged}
