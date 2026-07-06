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
    timelimit: str = "w",
) -> list[dict]:
    """ニュース検索。結果は新しい順とは限らない点に注意 (dedup 側で吸収)。

    timelimit は既定で "w" (1週間)。"d" だとニッチな日本語クエリで 0 件に
    なりやすい。重複は dedup が吸収するので広めに取る。
    """
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
        if "no results" in str(e).lower():
            # 全バックエンド 0 件は正常系 (次のポーリングで別クエリを試す)
            log.info("search_news no results for %r", query)
        else:
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
                "image_url": r.get("image") or None,
            }
        )
    return results


def search_text(query: str, max_results: int = 8, region: str = "jp-jp") -> list[dict]:
    """一般 Web 検索 (ニュースに限らない)。深堀りチャットのツール用。

    価格・製品情報・ドキュメントなどニュース検索では 0 件になりやすい
    クエリをカバーする。
    """
    try:
        with DDGS() as ddgs:
            raw = ddgs.text(
                query, region=region, safesearch="off", max_results=max_results
            )
    except Exception as e:  # noqa: BLE001
        if "no results" in str(e).lower():
            log.info("search_text no results for %r", query)
        else:
            log.warning("search_text failed for %r: %s", query, e)
        return []

    results = []
    for r in raw or []:
        url = r.get("href") or r.get("url")
        title = (r.get("title") or "").strip()
        if not url or not title:
            continue
        results.append(
            {
                "title": title,
                "url": url,
                "snippet": (r.get("body") or "").strip() or None,
            }
        )
    return results
