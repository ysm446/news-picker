"""Web ニュース検索 (ddgs)。

取り込みループ用の無料・API キー不要の検索。ddgs (旧 duckduckgo_search) の
news 検索を使い、仕様 §6.1 の {title, url, snippet, published_at, source}
形式に正規化して返す。

レート制限や一時エラーは空リストで返す (次のポーリングで再試行される)。
深堀りチャット用の高品質検索 (Tavily) はフェーズ6で別途足す。
"""
from __future__ import annotations

import logging
from datetime import datetime

from ddgs import DDGS

log = logging.getLogger(__name__)


def _parse_date(value) -> int | None:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def search_news(
    query: str,
    max_results: int = 20,
    region: str = "jp-jp",
    timelimit: str = "d",
) -> list[dict]:
    """ニュース検索。結果は新しい順とは限らない点に注意 (dedup 側で吸収)。"""
    try:
        with DDGS() as ddgs:
            raw = ddgs.news(
                query,
                region=region,
                safesearch="off",
                timelimit=timelimit,
                max_results=max_results,
            )
    except Exception as e:  # noqa: BLE001 - 検索失敗でワーカーを殺さない
        log.warning("search_news failed for %r: %s", query, e)
        return []

    results = []
    for r in raw or []:
        url = r.get("url") or r.get("href")
        title = (r.get("title") or "").strip()
        if not url or not title:
            continue
        results.append(
            {
                "title": title,
                "url": url,
                "snippet": (r.get("body") or "").strip() or None,
                "published_at": _parse_date(r.get("date")),
                "source": r.get("source") or None,
            }
        )
    return results
