"""llama-server のプロセス管理 (役割ベース)。

- standard: 常駐モデル。詳細生成・カテゴリ要約・キュレーション・チャット代行。
  バックエンド起動時に自動起動する。
- deep: 深堀りチャット用モデル。VRAM を占有するため既定では起動せず、
  ステータスバーのトグルから手動でロード/アンロードする。

使用するモデル (GGUF) は環境設定 (data/settings.json の model_standard /
model_deep、models/ からの相対パス) で差し替えられる。
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import psutil

from . import config, llm, settings_store

log = logging.getLogger(__name__)

_SERVER_EXE = config.ROOT / "runtime" / "llama.cpp" / "llama-server.exe"

ROLES: dict[str, dict] = {
    "standard": {
        "url": config.LLM_STANDARD_URL,
        "port": urlsplit(config.LLM_STANDARD_URL).port or 8081,
        "ctx": 32768,
        "settings_key": "model_standard",
    },
    "deep": {
        "url": config.LLM_DEEP_URL,
        "port": urlsplit(config.LLM_DEEP_URL).port or 8082,
        "ctx": 65536,
        "settings_key": "model_deep",
    },
}

_spawned: dict[str, subprocess.Popen] = {}


def model_path(role: str) -> Path | None:
    value = settings_store.get().get(ROLES[role]["settings_key"]) or ""
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else config.MODELS_DIR / path


def display_name(role: str) -> str:
    path = model_path(role)
    return path.stem if path else "(未設定)"


def is_running(role: str) -> bool:
    return llm.health(ROLES[role]["url"], timeout=1.0)


def _find_process(role: str) -> psutil.Process | None:
    """ポート引数でその役割の llama-server を特定する (exe 名は共通のため)。"""
    port = str(ROLES[role]["port"])
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            if p.info["name"] == "llama-server.exe" and port in (p.info["cmdline"] or []):
                return p
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def start(role: str) -> dict:
    """起動する (非同期: ロード完了は /system/resources の死活で分かる)。"""
    if is_running(role) or _find_process(role) is not None:
        return {"status": "already_running"}
    if not _SERVER_EXE.exists():
        raise RuntimeError("llama-server がありません (scripts/install-llama-server.ps1)")
    path = model_path(role)
    if path is None or not path.exists():
        raise RuntimeError(f"モデルがありません: {path} (設定画面で選択してください)")
    spec = ROLES[role]
    _spawned[role] = subprocess.Popen(
        [
            str(_SERVER_EXE),
            "-m", str(path),
            "--host", "127.0.0.1",
            "--port", str(spec["port"]),
            "-c", str(spec["ctx"]),
            "-ngl", "999",
            "--jinja",
            "--alias", path.stem,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    log.info("llama[%s] starting %s (pid %d)", role, path.name, _spawned[role].pid)
    return {"status": "starting", "model": display_name(role)}


def stop(role: str) -> dict:
    """停止して VRAM を解放する (誰が起動したものでも対象)。"""
    proc = _find_process(role)
    if proc is None:
        return {"status": "not_running"}
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except psutil.TimeoutExpired:
        proc.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
        log.warning("llama[%s] stop: %s", role, e)
    _spawned.pop(role, None)
    log.info("llama[%s] stopped", role)
    return {"status": "stopped"}


def restart(role: str) -> dict:
    """モデル差し替え反映用。deep は元々止まっていたら止まったままにする。"""
    was_running = is_running(role) or _find_process(role) is not None
    if was_running:
        stop(role)
    if role == "standard" or was_running:
        return start(role)
    return {"status": "not_running"}


def ensure_standard() -> None:
    """バックエンド起動時に常駐モデルを立ち上げる (既に動いていれば何もしない)。"""
    try:
        if not is_running("standard") and _find_process("standard") is None:
            start("standard")
    except RuntimeError as e:
        log.warning("ensure_standard skipped: %s", e)


def stop_if_spawned() -> None:
    """バックエンド終了時、自分で起動したプロセスだけを片付ける。

    standard はアプリの生命線なので、自分が起動した場合のみ止める
    (start.bat 等で外部起動されたものは残す)。
    """
    for proc in _spawned.values():
        if proc.poll() is None:
            proc.kill()
    _spawned.clear()


def list_models() -> list[dict]:
    """models/ 配下の GGUF を列挙する (埋め込みモデルのキャッシュは除外)。"""
    results = []
    if config.MODELS_DIR.exists():
        for path in sorted(config.MODELS_DIR.rglob("*.gguf")):
            if "embeddings" in path.parts:
                continue
            results.append(
                {
                    "path": path.relative_to(config.MODELS_DIR).as_posix(),
                    "size_gb": round(path.stat().st_size / (1024**3), 1),
                }
            )
    return results
