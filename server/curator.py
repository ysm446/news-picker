"""キュレーション: 9B によるタイトル一括採点 (0-100)。

取り込み直後の記事バッチを1回の呼び出しでまとめて採点する。
タイトル配信 (article.new) はブロックせず、採点結果は後追いの
SSE (article.curated) で反映される。スコアの使い方 (閾値でのノイズ
非表示) は UI 側の責務で、ここでは記事を削除しない。
"""
from __future__ import annotations

import json
import logging
import re

from . import config, llm

log = logging.getLogger(__name__)

_KANA = re.compile(r"[ぁ-んァ-ヶ]")


def needs_translation(title: str) -> bool:
    """日本語見出しでない可能性が高いか (かな無し + ASCII 過半)。"""
    if _KANA.search(title):
        return False
    ascii_ratio = sum(c.isascii() for c in title) / max(1, len(title))
    return ascii_ratio > 0.5

_SYSTEM_PROMPT = """あなたはニュースキュレーター。指定カテゴリの購読者にとっての各記事の重要度を 0〜100 で採点する。

採点基準:
- カテゴリとの関連が薄い記事は 20 以下 (例: カテゴリと無関係な芸能・スポーツ・一般経済指標)
- セミナー告知・宣伝・アフィリエイト的な記事は 20 以下
- カテゴリに関連するが日常的・些末な話題は 30〜50
- 購読者の判断に影響しうる実質的なニュースは 60〜85
- 業界構造を変えるような重要ニュースは 90 以上"""

def _score_schema(translate: bool) -> dict:
    item_props: dict = {
        "id": {"type": "integer"},
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
    }
    required = ["id", "score"]
    if translate:
        item_props["title_ja"] = {
            "type": "string",
            "description": "見出しが日本語以外の場合のみ、自然な日本語訳。日本語なら空文字",
        }
        required.append("title_ja")
    return {
        "type": "object",
        "properties": {
            "scores": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": item_props,
                    "required": required,
                },
            }
        },
        "required": ["scores"],
    }


def score_articles(
    category: config.Category,
    articles: list[dict],
    translate: bool = False,
    examples: dict[str, list[str]] | None = None,
) -> dict[int, dict]:
    """記事バッチを採点して {article_id: {score, title_ja}} を返す。失敗時は {}。

    translate=True のとき、日本語以外の見出しには title_ja (日本語訳) が付く。
    examples はユーザーの過去の評価 (few-shot)。採点の個人化に使う。
    """
    if not articles:
        return {}
    lines = []
    for a in articles:
        line = f"{a['id']}: {a['title']}"
        if a.get("snippet"):
            line += f" — {a['snippet'][:100]}"
        lines.append(line)

    system_prompt = _SYSTEM_PROMPT
    task = "以下の記事 (id: タイトル — 抜粋) を全て採点せよ。"
    if translate:
        system_prompt += (
            "\n\n加えて、見出しが日本語以外の記事には title_ja として"
            "自然で簡潔な日本語訳を付ける。見出しが日本語なら title_ja は空文字にする。"
        )
        task = "以下の記事 (id: タイトル — 抜粋) を全て採点し、必要なら日本語訳を付けよ。"

    category_desc = f"カテゴリ: {category.label}\n"
    if category.description:
        category_desc += f"カテゴリの説明・採点基準: {category.description}\n"
    category_desc += f"カテゴリのキーワード: {', '.join(category.keywords) or 'なし'}\n"

    # ユーザーの過去の評価を few-shot として同梱 (採点の個人化)
    if examples and (examples.get("positive") or examples.get("negative")):
        category_desc += "\nこのユーザーの過去の評価 (傾向を採点に反映せよ):\n"
        for title in examples.get("positive") or []:
            category_desc += f"- [重要と評価] {title[:70]}\n"
        for title in examples.get("negative") or []:
            category_desc += f"- [不要と評価] {title[:70]}\n"

    try:
        result = llm.chat(
            [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"{category_desc}\n{task}\n\n" + "\n".join(lines),
                },
            ],
            base_url=config.LLM_STANDARD_URL,
            response_json_schema=_score_schema(translate),
            enable_thinking=False,
            max_tokens=3000 if translate else 1500,
            timeout=180,
        )
        data = json.loads(result["content"])
        valid_ids = {a["id"] for a in articles}
        results: dict[int, dict] = {}
        for s in data["scores"]:
            article_id = int(s["id"])
            if article_id not in valid_ids:
                continue
            title_ja = (s.get("title_ja") or "").strip() or None
            results[article_id] = {
                "score": max(0, min(100, int(s["score"]))),
                "title_ja": title_ja,
            }
        return results
    except Exception as e:  # noqa: BLE001 - 採点失敗は未採点として扱う (記事は普通に表示される)
        log.warning("score_articles failed for %s: %s", category.id, e)
        return {}


_TRANSLATE_SCHEMA = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "title_ja": {"type": "string"},
                },
                "required": ["id", "title_ja"],
            },
        }
    },
    "required": ["translations"],
}


def translate_titles(articles: list[dict]) -> dict[int, str]:
    """見出しの翻訳専用パス。採点時に 9B が title_ja を空で返した際の再試行に使う。"""
    if not articles:
        return {}
    lines = [f"{a['id']}: {a['title']}" for a in articles]
    try:
        result = llm.chat(
            [
                {
                    "role": "system",
                    "content": "あなたはニュース翻訳者。各見出しを自然で簡潔な日本語に訳す。",
                },
                {"role": "user", "content": "以下の見出しを全て日本語訳せよ。\n\n" + "\n".join(lines)},
            ],
            base_url=config.LLM_STANDARD_URL,
            response_json_schema=_TRANSLATE_SCHEMA,
            enable_thinking=False,
            max_tokens=2000,
            timeout=180,
        )
        data = json.loads(result["content"])
        valid_ids = {a["id"] for a in articles}
        return {
            int(t["id"]): t["title_ja"].strip()
            for t in data["translations"]
            if int(t["id"]) in valid_ids and t["title_ja"].strip()
        }
    except Exception as e:  # noqa: BLE001
        log.warning("translate_titles failed: %s", e)
        return {}
