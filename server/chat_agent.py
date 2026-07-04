"""深堀りチャットのエージェンティックループ (spec §8)。35B + 2ツール。

モデル自身が vault_search (ローカル記事庫) と web_search (Web ニュース) を
必要に応じて多段で呼び、引用付きで回答する。各ステージは emit コールバックで
SSE イベントとして配信される。

v1 は各ターン非ストリーム (ツール呼び出しのパースを堅牢にするため)。
トークン単位ストリーミングは今後の改善項目 (plan.md 参照)。
"""
from __future__ import annotations

import json
import logging
from typing import Callable

from . import config, llm
from .search_vault import vault_search
from .search_web import search_news

log = logging.getLogger(__name__)

MAX_TOOL_STEPS = 6

_SYSTEM_PROMPT = """あなたはニュース分析アシスタント。ユーザーの質問に対し、必要に応じてツールで情報を集めながら日本語で答える。

ツールの使い分け:
- vault_search: ローカルに蓄積したニュース記事庫。まずこちらで関連記事を探す
- web_search: 記事庫に無い最新情報や補足情報が必要なとき

回答のルール:
- 根拠にした記事の URL を回答末尾に「出典:」として必ず列挙する
- 記事庫にも Web にも情報が無ければ、無いと正直に言う
- 簡潔に、事実と推測を区別して書く"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "vault_search",
            "description": (
                "ローカルに蓄積したニュース記事をハイブリッド検索する "
                "(全文一致 + 意味検索 + 新しさ優先)。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "検索クエリ (日本語可)"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Web のニュースを検索する (過去1週間)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "検索クエリ (日本語可)"}
                },
                "required": ["query"],
            },
        },
    },
]


def _dispatch_tool(name: str, args: dict) -> list | dict:
    if name == "vault_search":
        return vault_search(args.get("query", ""), top_k=8)
    if name == "web_search":
        return search_news(args.get("query", ""), max_results=8)
    return {"error": f"unknown tool: {name}"}


def run_chat(
    messages: list[dict],
    article_md: str | None,
    emit: Callable[[dict], None],
) -> None:
    """エージェンティックループ本体 (同期)。進捗と回答は emit で配信する。"""
    msgs: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]
    if article_md:
        msgs.append(
            {
                "role": "system",
                "content": f"ユーザーが現在開いている記事 (深堀り対象):\n\n{article_md}",
            }
        )
    msgs += messages

    for _step in range(MAX_TOOL_STEPS):
        result = llm.chat(
            msgs,
            base_url=config.LLM_35B_URL,
            tools=TOOLS,
            max_tokens=4096,
            timeout=600,
        )
        if result["reasoning"]:
            emit({"type": "chat.thinking", "text": result["reasoning"]})

        tool_calls = result["tool_calls"]
        if not tool_calls:
            emit({"type": "chat.answer", "content": result["content"]})
            return

        msgs.append(result["message"])  # assistant ターン (tool_calls 込み)
        for tc in tool_calls:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            emit({"type": "chat.tool_call", "name": name, "args": args})
            try:
                tool_result = _dispatch_tool(name, args)
            except Exception as e:  # noqa: BLE001 - ツール失敗はモデルに伝えて続行
                log.exception("tool %s failed", name)
                tool_result = {"error": str(e)[:200]}
            count = len(tool_result) if isinstance(tool_result, list) else None
            emit({"type": "chat.tool_result", "name": name, "count": count})
            msgs.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id"),
                    "content": json.dumps(tool_result, ensure_ascii=False),
                }
            )

    emit(
        {
            "type": "chat.answer",
            "content": "(ツール呼び出しの上限に達したため、ここまでの情報で回答を打ち切りました)",
        }
    )
