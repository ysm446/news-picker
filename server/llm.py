"""llama.cpp (llama-server) クライアント。2ポート構成 (spec §3)。

- 9B  (8081): 詳細生成・カテゴリ要約などの背景処理
- 35B (8082): 深堀りチャット

標準ライブラリ urllib のみで通信する (lm-chat の llm_proxy パターン)。
応答は content を本文、reasoning_content を思考として分離して返す。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import config

DEFAULT_SAMPLING = {"temperature": 0.6, "top_p": 0.95, "top_k": 20}


def health(base_url: str, timeout: float = 2.0) -> bool:
    try:
        req = urllib.request.Request(f"{base_url}/health")
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status == 200
    except (urllib.error.URLError, OSError):
        return False


def chat(
    messages: list[dict],
    *,
    base_url: str | None = None,
    max_tokens: int = 2048,
    timeout: float = 300.0,
    response_json_schema: dict | None = None,
    enable_thinking: bool | None = None,
    tools: list[dict] | None = None,
    **sampling,
) -> dict:
    """非ストリームの chat completion。{"content", "reasoning", "usage"} を返す。

    response_json_schema を渡すと llama-server の構造化出力
    (json_schema response_format) で JSON を強制する。
    enable_thinking=False で思考を無効化する (高頻度の要約タスク用。
    Ornith は一言の回答にも思考 ~1000 トークンを使うため必須。plan.md 参照)。
    """
    base_url = base_url or config.LLM_STANDARD_URL
    payload: dict = {
        "messages": messages,
        "max_tokens": max_tokens,
        **DEFAULT_SAMPLING,
        **sampling,
    }
    if enable_thinking is not None:
        payload["chat_template_kwargs"] = {"enable_thinking": enable_thinking}
    if tools is not None:
        payload["tools"] = tools
    if response_json_schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "result", "schema": response_json_schema},
        }

    req = urllib.request.Request(
        f"{base_url}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        data = json.loads(res.read().decode("utf-8"))

    message = data["choices"][0]["message"]
    return {
        "content": message.get("content") or "",
        "reasoning": message.get("reasoning_content"),
        "tool_calls": message.get("tool_calls"),
        "message": message,  # tool ループで会話履歴に積み直す用
        "usage": data.get("usage", {}),
    }
