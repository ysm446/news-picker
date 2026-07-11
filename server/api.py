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
import re
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import config, llama_manager, settings_store, store, system_stats, thumbs, vault
from .chat_agent import run_chat
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
_loop_tasks: list[asyncio.Task] = []


def _build_workers(categories: list[config.Category]) -> None:
    # 無効カテゴリは取り込み・要約の対象から外す (更新を止める)。
    # enrich は表示済み記事の詳細生成なので全カテゴリを持たせておく
    workers.clear()
    for cat in categories:
        if cat.enabled:
            workers[cat.id] = IngestWorker(cat, bus)
    if enricher is not None:
        enricher.categories = {c.id: c for c in categories}
    if briefer is not None:
        briefer.categories = [c for c in categories if c.enabled]


def _start_loops() -> None:
    if os.environ.get("NEWS_PICKER_NO_INGEST"):
        return
    _loop_tasks.extend(asyncio.ensure_future(w.run()) for w in workers.values())
    _loop_tasks.append(asyncio.ensure_future(briefer.run()))
    _loop_tasks.append(asyncio.ensure_future(cleaner.run()))


def _stop_loops() -> None:
    for t in _loop_tasks:
        t.cancel()
    _loop_tasks.clear()


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
    bus.attach_loop(asyncio.get_running_loop())  # スレッドプールからの publish 用
    categories = config.load_categories()
    enricher = EnrichWorker(bus, categories)
    briefer = BriefWorker(bus, categories)
    _build_workers(categories)
    enrich_task = asyncio.ensure_future(enricher.run())
    _start_loops()
    # 常駐モデルはバックエンドが自動起動する (start.bat / Electron は関与しない)
    await asyncio.to_thread(llama_manager.ensure_standard)
    yield
    _stop_loops()
    enrich_task.cancel()
    llama_manager.stop_if_spawned()


app = FastAPI(title="news-picker", lifespan=lifespan)

# ローカル専用 API。Electron renderer (vite dev / file://) からのアクセスを許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "null"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------- categories

class CategoryModel(BaseModel):
    id: str
    label: str
    description: str = ""
    keywords: list[str] = []
    query_templates: list[str] = []
    feeds: list[str] = []
    poll_interval_sec: int = 600
    jitter_sec: int = 60
    impact_axis: list[str] = ["notable", "minor"]
    max_window: int = 30
    summary_prompt: str = ""
    enabled: bool = True


_CATEGORY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _save_and_reload(categories: list[config.Category]) -> None:
    config.save_categories(categories)
    _stop_loops()
    _build_workers(categories)
    _start_loops()


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
            "description": c.description,
            "keywords": c.keywords,
            "query_templates": c.query_templates,
            "feeds": c.feeds,
            "poll_interval_sec": c.poll_interval_sec,
            "jitter_sec": c.jitter_sec,
            "impact_axis": c.impact_axis,
            "max_window": c.max_window,
            "summary_prompt": c.summary_prompt,
            "enabled": c.enabled,
            "unread": counts.get(c.id, 0),
        }
        for c in config.load_categories()
    ]


@app.post("/categories")
async def create_category(model: CategoryModel) -> dict:  # async: ワーカー再起動はイベントループ上で行う
    if not _CATEGORY_ID_RE.match(model.id):
        raise HTTPException(400, "id は小文字英数字とハイフンのみ (例: semiconductor-stocks)")
    if not model.query_templates and not model.feeds:
        raise HTTPException(400, "query_templates か feeds を1つ以上指定してください")
    categories = config.load_categories()
    if any(c.id == model.id for c in categories):
        raise HTTPException(409, f"カテゴリ {model.id} は既に存在します")
    categories.append(config.Category(**model.model_dump()))
    _save_and_reload(categories)
    return {"id": model.id, "created": True}


@app.put("/categories/{category_id}")
async def update_category(category_id: str, model: CategoryModel) -> dict:
    if not model.query_templates and not model.feeds:
        raise HTTPException(400, "query_templates か feeds を1つ以上指定してください")
    categories = config.load_categories()
    index = next((i for i, c in enumerate(categories) if c.id == category_id), None)
    if index is None:
        raise HTTPException(404, f"カテゴリ {category_id} が見つかりません")
    data = model.model_dump()
    data["id"] = category_id  # id は変更不可 (フォルダ名・DB値と紐づくため)
    categories[index] = config.Category(**data)
    _save_and_reload(categories)
    return {"id": category_id, "updated": True}


class EnabledModel(BaseModel):
    enabled: bool


@app.put("/categories/{category_id}/enabled")
async def set_category_enabled(category_id: str, model: EnabledModel) -> dict:
    """カテゴリの表示/非表示。非表示は取り込み・要約も止める。"""
    categories = config.load_categories()
    target = next((c for c in categories if c.id == category_id), None)
    if target is None:
        raise HTTPException(404, f"カテゴリ {category_id} が見つかりません")
    target.enabled = model.enabled
    _save_and_reload(categories)  # ワーカー構成が変わるので再構築する
    return {"id": category_id, "enabled": model.enabled}


class ReorderModel(BaseModel):
    order: list[str]


@app.post("/categories/reorder")
def reorder_categories(model: ReorderModel) -> dict:
    """カテゴリの表示順を保存する (yaml のリスト順 = ボードの列順)。

    順番は表示にしか影響しないため、ワーカーの再構築はしない
    (取り込みループを止めない)。
    """
    categories = config.load_categories()
    by_id = {c.id: c for c in categories}
    if set(model.order) != set(by_id) or len(model.order) != len(by_id):
        raise HTTPException(400, "order には全カテゴリの id を過不足なく含めてください")
    config.save_categories([by_id[i] for i in model.order])
    return {"order": model.order}


@app.delete("/categories/{category_id}")
async def delete_category(category_id: str) -> dict:
    categories = config.load_categories()
    remaining = [c for c in categories if c.id != category_id]
    if len(remaining) == len(categories):
        raise HTTPException(404, f"カテゴリ {category_id} が見つかりません")
    _save_and_reload(remaining)
    # 記事 (DB/vault) は消さない。カテゴリを再作成すれば再び表示される
    return {"id": category_id, "deleted": True}


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


@app.get("/articles/{article_id}/thumb")
def article_thumb(article_id: int) -> FileResponse:
    """サムネイル画像。初回はダウンロード・縮小して data/cache/images/ に保存。"""
    conn = store.connect()
    try:
        row = store.get_article(conn, article_id)
    finally:
        conn.close()
    if row is None or not row["image_url"]:
        raise HTTPException(404, "no image")
    path = thumbs.get_or_fetch(article_id, row["image_url"])
    if path is None:
        raise HTTPException(404, "image unavailable")
    return FileResponse(path, media_type="image/jpeg")


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
    """保存のトグル。解除時は enrich 済みなら seen、未処理なら new に戻す。"""
    conn = store.connect()
    try:
        row = store.get_article(conn, article_id)
        if row is None:
            raise HTTPException(404, f"article {article_id} not found")
        if row["status"] == "saved":
            status = "seen" if row["enriched_at"] else "new"
        else:
            status = "saved"
        store.set_status(conn, article_id, status)
        # MD へ書き戻す (rebuild で保存状態が巻き戻り、自動整理に消されないように)
        vault.sync_article_md(store.get_article(conn, article_id))
    finally:
        conn.close()
    # 保存時、未 enrich なら詳細生成をキューに積む。enrich 完了で MD が
    # vault に書かれ「保存 = vault に確実に書き残す」セマンティクスになる
    if status == "saved" and not row["enriched_at"] and enricher is not None:
        enricher.enqueue(article_id)
    bus.publish({"type": "article.status_changed", "id": article_id, "status": status})
    return {"id": article_id, "status": status}


@app.post("/articles/{article_id}/like")
def like_article(article_id: int) -> dict:
    """👍 のトグル (rating 1 <-> なし)。キュレーション学習の正例になる。"""
    conn = store.connect()
    try:
        row = store.get_article(conn, article_id)
        if row is None:
            raise HTTPException(404, f"article {article_id} not found")
        rating = None if row["rating"] == 1 else 1
        store.set_rating(conn, article_id, rating)
        vault.sync_article_md(store.get_article(conn, article_id))  # rebuild で評価が消えないように
    finally:
        conn.close()
    bus.publish({"type": "article.rated", "id": article_id, "rating": rating})
    return {"id": article_id, "rating": rating}


@app.post("/articles/{article_id}/dismiss")
def dismiss_article(article_id: int) -> dict:
    """興味なし (rating=-1 + 非表示 + tombstone)。キュレーション学習の負例になる。"""
    conn = store.connect()
    try:
        row = store.get_article(conn, article_id)
        if row is None:
            raise HTTPException(404, f"article {article_id} not found")
        store.set_rating(conn, article_id, -1)
        url_hash = store.hide_article(conn, article_id)
    finally:
        conn.close()
    vault.append_tombstone(url_hash, "deleted")
    vault.delete_article_md(row["md_path"])  # 残すと rebuild で復活する
    thumbs.delete(article_id)
    bus.publish({"type": "article.status_changed", "id": article_id, "status": "hidden"})
    return {"id": article_id, "rating": -1, "status": "hidden"}


@app.post("/articles/{article_id}/hide")
def hide_article(article_id: int) -> dict:
    conn = store.connect()
    try:
        row = store.get_article(conn, article_id)
        url_hash = store.hide_article(conn, article_id)
    finally:
        conn.close()
    if url_hash is None:
        raise HTTPException(404, f"article {article_id} not found")
    vault.append_tombstone(url_hash, "deleted")  # rebuild 後も復活しないよう vault 側にも記録
    vault.delete_article_md(row["md_path"])  # 残すと rebuild で復活する
    thumbs.delete(article_id)
    bus.publish({"type": "article.status_changed", "id": article_id, "status": "hidden"})
    return {"id": article_id, "status": "hidden"}


# ---------------------------------------------------------------- チャット

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    article_id: int | None = None


def _load_article_context(article_id: int) -> str | None:
    """深堀り対象の記事 MD を初期コンテキストとして読む (spec §8)。"""
    conn = store.connect()
    try:
        row = store.get_article(conn, article_id)
    finally:
        conn.close()
    if row is None:
        return None
    if row["md_path"]:
        md = config.VAULT_DIR / row["md_path"]
        if md.exists():
            return md.read_text(encoding="utf-8")
    # 未 enrich ならタイトル + スニペットだけでも渡す
    return f"# {row['title']}\n\n{row['snippet'] or ''}\n\n出典: {row['url']}"


@app.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    """深堀りチャット (35B エージェンティック)。SSE でステージイベントを流す。"""
    article_md = _load_article_context(req.article_id) if req.article_id else None
    messages = [m.model_dump() for m in req.messages]

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def emit(event: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def worker() -> None:
        try:
            run_chat(messages, article_md, emit)
        except Exception as e:  # noqa: BLE001
            emit({"type": "chat.error", "detail": str(e)[:300]})
        finally:
            emit({"type": "chat.done"})

    async def gen():
        task = asyncio.create_task(asyncio.to_thread(worker))
        try:
            while True:
                event = await queue.get()
                yield format_sse(event)
                if event["type"] == "chat.done":
                    break
        finally:
            await task

    return StreamingResponse(gen(), media_type="text/event-stream")


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


# ---------------------------------------------------------------- 環境設定

class SettingsModel(BaseModel):
    translate_titles: bool | None = None
    show_thumbnails: bool | None = None
    noise_threshold: int | None = Field(None, ge=0, le=100)
    retention_days: int | None = Field(None, ge=1, le=365)
    model_standard: str | None = None
    model_deep: str | None = None


@app.get("/settings")
def get_settings() -> dict:
    return settings_store.get()


@app.put("/settings")
def put_settings(model: SettingsModel) -> dict:
    """部分更新。渡されたキーだけ上書きする。"""
    return settings_store.update(model.model_dump(exclude_none=True))


# ---------------------------------------------------------------- system

@app.get("/system/resources")
def system_resources() -> dict:
    """ステータスバー用: CPU / RAM / GPU / VRAM / llama-server 死活。"""
    return system_stats.get_resources()


@app.get("/models")
def list_models() -> list[dict]:
    """models/ 配下の GGUF 一覧 (設定画面のモデル選択用)。"""
    return llama_manager.list_models()


def _validate_role(role: str) -> None:
    if role not in llama_manager.ROLES:
        raise HTTPException(404, f"unknown role {role} (standard | deep)")


@app.post("/llama/{role}/start")
def llama_start(role: str) -> dict:
    """モデルを手動ロード (完了は /system/resources の死活で確認)。"""
    _validate_role(role)
    try:
        return llama_manager.start(role)
    except RuntimeError as e:
        raise HTTPException(500, str(e)) from e


@app.post("/llama/{role}/stop")
def llama_stop(role: str) -> dict:
    """モデルを手動アンロードして VRAM を解放する。"""
    _validate_role(role)
    return llama_manager.stop(role)


@app.post("/llama/{role}/restart")
def llama_restart(role: str) -> dict:
    """モデル差し替えの反映用 (deep は停止中なら停止のまま)。"""
    _validate_role(role)
    try:
        return llama_manager.restart(role)
    except RuntimeError as e:
        raise HTTPException(500, str(e)) from e


# ---------------------------------------------------------------- admin

@app.post("/admin/shutdown")
def shutdown_backend() -> dict:
    """完全終了: llama-server を (誰が起動したものでも) 止めてから自分も exit する。

    トレイの「終了」から呼ばれる。バックエンドが Electron の子プロセスで
    なくなっている場合 (外部起動) でも、これで全部きれいに止まる。
    """
    for role in llama_manager.ROLES:
        try:
            llama_manager.stop(role)
        except Exception:  # noqa: BLE001 - 片方の停止失敗で終了を止めない
            logging.getLogger(__name__).exception("shutdown: llama %s stop failed", role)
    # 応答を返しきってから抜ける
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return {"shutting_down": True}


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
    """開発用: ポーリングを待たずに1回取り込む (採点込み)。"""
    worker = workers.get(category)
    if worker is None:
        raise HTTPException(404, f"unknown category {category}")
    inserted = await asyncio.to_thread(worker.ingest_once)
    worker.publish_new(inserted)
    scores = await asyncio.to_thread(worker.curate_sync, inserted)
    worker.publish_scores(scores)
    return {"category": category, "new": len(inserted), "scored": len(scores)}


@app.post("/admin/curate-now")
async def curate_now(category: str, force: bool = False) -> dict:
    """未採点の既存記事をまとめて採点する。force=True で直近50件を再採点
    (日本語訳を後から付けたい場合などに使う)。"""
    worker = workers.get(category)
    if worker is None:
        raise HTTPException(404, f"unknown category {category}")

    condition = "" if force else "AND relevance IS NULL"

    def backfill() -> dict[int, dict]:
        conn = store.connect()
        try:
            rows = conn.execute(
                f"""SELECT id, title, snippet FROM articles
                    WHERE category = ? {condition} AND status != 'hidden'
                    ORDER BY fetched_at DESC LIMIT 50""",
                (category,),
            ).fetchall()
        finally:
            conn.close()
        return worker.curate_sync([dict(r) for r in rows])

    results = await asyncio.to_thread(backfill)
    worker.publish_scores(results)
    return {"category": category, "scored": len(results)}


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


@app.post("/admin/reload-config")
async def reload_config() -> dict:
    """categories.yaml を再読み込みし、取り込みワーカーを再構築する。"""
    categories = config.load_categories()
    _stop_loops()
    _build_workers(categories)
    _start_loops()
    return {"categories": [c.id for c in categories]}
