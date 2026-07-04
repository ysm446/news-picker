"""記事本文の取得 (spec §6.2 の「web_fetch 相当」)。

trafilatura でダウンロード + 本文抽出。失敗時は None を返し、
呼び出し側が snippet で代替する。
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

MAX_BODY_CHARS = 8000  # 9B のプロンプトに入れる上限 (コンテキストと速度のバランス)


def fetch_body(url: str) -> str | None:
    try:
        import trafilatura

        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return None
        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
        )
        if not text:
            return None
        return text.strip()[:MAX_BODY_CHARS]
    except Exception as e:  # noqa: BLE001 - 本文が取れなくても enrich は続行できる
        log.warning("fetch_body failed for %s: %s", url, e)
        return None
