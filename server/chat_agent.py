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
from .search_web import search_news, search_text

log = logging.getLogger(__name__)

MAX_TOOL_STEPS = 8

_SYSTEM_PROMPT = """あなたはニュース分析アシスタント。ユーザーの質問に対し、必要に応じてツールで情報を集めながら日本語で答える。

ツールの使い分け:
- vault_search: ローカルに蓄積したニュース記事庫。ニュース系の質問はまずこちら
- web_search: 一般の Web 検索。価格・製品・技術情報など記事庫に無い情報
- news_search: 直近1週間のニュース記事に絞った検索

同じようなクエリで結果が空のときは、言い換えを繰り返しすぎず、
得られた情報で答えるか「見つからなかった」と答えること。

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
            "description": (
                "Web を検索する (ニュースに限らない一般検索。"
                "価格・製品情報・技術情報にも使える)。"
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
            "name": "news_search",
            "description": "Web のニュース記事に絞って検索する (過去1週間)。",
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
        return search_text(args.get("query", ""), max_results=8)
    if name == "news_search":
        return search_news(args.get("query", ""), max_results=8)
    return {"error": f"unknown tool: {name}"}


def run_chat(
    messages: list[dict],
    article_md: str | None,
    emit: Callable[[dict], None],
) -> None:
    """エージェンティックループ本体 (同期)。進捗と回答は emit で配信する。"""
    # 深堀りモデルが起動していればそちら、オフなら常駐モデルが代行する
    from . import llama_manager  # 循環 import 回避

    if llm.health(config.LLM_DEEP_URL, timeout=1.0):
        base_url, role = config.LLM_DEEP_URL, "deep"
    else:
        base_url, role = config.LLM_STANDARD_URL, "standard"
    emit(
        {
            "type": "chat.model",
            "model": llama_manager.display_name(role),
            "role": role,
        }
    )

    msgs: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]
    if article_md:
        msgs.append(
            {
                "role": "system",
                "content": f"ユーザーが現在開いている記事 (深堀り対象):\n\n{article_md}",
            }
        )
    msgs += messages

    def stream_turn(tools: list[dict] | None) -> dict:
        """1ターンをストリーミング実行。本文デルタを chat.delta で配信する。"""
        final: dict = {}
        streamed = False
        for kind, data in llm.chat_stream(
            msgs, base_url=base_url, tools=tools, max_tokens=4096, timeout=600
        ):
            if kind == "content":
                streamed = True
                emit({"type": "chat.delta", "text": data})
            elif kind == "done":
                final = data
        if final.get("reasoning"):
            emit({"type": "chat.thinking", "text": final["reasoning"]})
        # ツール呼び出しターンで本文が混ざっていた場合、描きかけを引っ込める
        if streamed and final.get("tool_calls"):
            emit({"type": "chat.turn_reset"})
        return final

    for _step in range(MAX_TOOL_STEPS):
        result = stream_turn(TOOLS)

        tool_calls = result.get("tool_calls")
        if not tool_calls:
            emit({"type": "chat.answer", "content": result.get("content", "")})
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

    # ツール上限到達: 打ち切らず、集めた情報で最終回答を生成させる (ツールなし)
    msgs.append(
        {
            "role": "user",
            "content": (
                "検索回数の上限に達した。これ以上ツールは使えない。"
                "ここまでに得られた情報だけで最終回答をまとめよ。"
                "情報が不足している点は不足していると明記すること。"
            ),
        }
    )
    result = stream_turn(None)
    emit({"type": "chat.answer", "content": result.get("content", "")})
