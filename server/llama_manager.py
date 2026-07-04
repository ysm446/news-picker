"""35B llama-server の手動ロード/アンロード (lm-chat の llama_manager を簡略移植)。

9B は常駐前提 (詳細生成・要約・キュレーションの基盤)。
35B は深堀りチャット用で、VRAM ~25GB を占有するため既定では起動せず、
ステータスバーのトグルから手動でロード/アンロードする。
オフの間の深堀りチャットは 9B が代行する (chat_agent 参照)。
"""
from __future__ import annotations

import logging
import subprocess
from urllib.parse import urlsplit

import psutil

from . import config, llm

log = logging.getLogger(__name__)

_SERVER_EXE = config.ROOT / "runtime" / "llama.cpp" / "llama-server.exe"
_MODEL_35B = config.ROOT / "models" / "Ornith-1.0-35B-GGUF" / "ornith-1.0-35b-Q4_K_M.gguf"
_PORT_35B = urlsplit(config.LLM_35B_URL).port or 8082
_CTX_35B = 65536

_spawned: subprocess.Popen | None = None


def is_running() -> bool:
    return llm.health(config.LLM_35B_URL, timeout=1.0)


def _find_35b_process() -> psutil.Process | None:
    """ポート引数で 35B の llama-server を特定する (9B と同名 exe のため)。"""
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            if p.info["name"] == "llama-server.exe" and str(_PORT_35B) in (
                p.info["cmdline"] or []
            ):
                return p
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def start_35b() -> dict:
    """35B を起動する (非同期: ロード完了は /system/resources の死活で分かる)。"""
    global _spawned
    if is_running() or _find_35b_process() is not None:
        return {"status": "already_running"}
    if not _SERVER_EXE.exists():
        raise RuntimeError("llama-server がありません (scripts/install-llama-server.ps1)")
    if not _MODEL_35B.exists():
        raise RuntimeError(f"モデルがありません: {_MODEL_35B}")
    _spawned = subprocess.Popen(
        [
            str(_SERVER_EXE),
            "-m", str(_MODEL_35B),
            "--host", "127.0.0.1",
            "--port", str(_PORT_35B),
            "-c", str(_CTX_35B),
            "-ngl", "999",
            "--jinja",
            "--alias", "ornith-35b",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    log.info("35B starting (pid %d)", _spawned.pid)
    return {"status": "starting"}


def stop_35b() -> dict:
    """35B を停止して VRAM を解放する (誰が起動したものでも対象)。"""
    global _spawned
    proc = _find_35b_process()
    if proc is None:
        return {"status": "not_running"}
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except psutil.TimeoutExpired:
        proc.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
        log.warning("stop_35b: %s", e)
    _spawned = None
    log.info("35B stopped")
    return {"status": "stopped"}


def stop_if_spawned() -> None:
    """バックエンド終了時、自分で起動した 35B だけを片付ける。"""
    if _spawned is not None and _spawned.poll() is None:
        _spawned.kill()
