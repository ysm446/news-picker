"""RSS/Atom フィード取り込み。

カテゴリ設定の feeds (URL リスト) を feedparser で取得し、検索 (search_web)
と同じ {title, url, snippet, published_at, source} 形式に正規化して返す。
取り込みパイプライン (dedup / 採点 / SSE) には ingest 側で検索結果と
合流させる。

ETag / Last-Modified はプロセス内でキャッシュし、更新のないフィードは
304 で本文を取得しない (取得先への配慮)。プロセス再起動でキャッシュは
消えるが、重複は dedup が吸収する。
"""
from __future__ import annotations

import calendar
import html
import logging
import re

import feedparser

from . import http_headers

log = logging.getLogger(__name__)

# feedparser 既定の UA (feedparser/x.y.z +...) は明らかなボット扱いで
# 403 になる配信元があるため、ブラウザ相当のヘッダで取得する
_FEED_HEADERS = http_headers.browser_headers(http_headers.FEED_ACCEPT)

# フィード URL → (etag, modified 文字列)
_http_cache: dict[str, tuple[str | None, str | None]] = {}

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return html.unescape(_TAG_RE.sub("", text)).strip()


def _entry_epoch(entry) -> int | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed_time = entry.get(key)
        if parsed_time:
            return int(calendar.timegm(parsed_time))
    return None


def _entry_image(entry) -> str | None:
    """media:thumbnail / media:content / enclosure から画像 URL を探す。"""
    for thumb in entry.get("media_thumbnail") or []:
        if thumb.get("url"):
            return thumb["url"]
    for media in entry.get("media_content") or []:
        is_image = media.get("medium") == "image" or (media.get("type") or "").startswith("image/")
        if is_image and media.get("url"):
            return media["url"]
    for link in entry.get("links") or []:
        if link.get("rel") == "enclosure" and (link.get("type") or "").startswith("image/"):
            if link.get("href"):
                return link["href"]
    return None


def fetch_feed(url: str, max_entries: int = 30) -> list[dict]:
    """1フィード分の取得。失敗・未更新 (304) は空リストを返す。"""
    etag, modified = _http_cache.get(url, (None, None))
    try:
        parsed = feedparser.parse(
            url, etag=etag, modified=modified, request_headers=_FEED_HEADERS
        )
    except Exception as e:  # noqa: BLE001 - フィード失敗でワーカーを殺さない
        log.warning("fetch_feed failed for %s: %s", url, e)
        return []
    if getattr(parsed, "status", None) == 304:
        return []
    if parsed.get("bozo") and not parsed.entries:
        log.warning(
            "fetch_feed parse error for %s: %s", url, parsed.get("bozo_exception")
        )
        return []
    _http_cache[url] = (parsed.get("etag"), parsed.get("modified"))

    source = _strip_html(parsed.feed.get("title") or "") or None
    results: list[dict] = []
    for entry in parsed.entries[:max_entries]:
        link = (entry.get("link") or "").strip()
        title = _strip_html(entry.get("title") or "")
        if not link or not title:
            continue
        results.append(
            {
                "title": title,
                "url": link,
                "snippet": _strip_html(entry.get("summary") or "")[:500] or None,
                "published_at": _entry_epoch(entry),
                "source": source,
                "image_url": _entry_image(entry),
            }
        )
    return results
