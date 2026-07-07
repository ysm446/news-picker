"""外向き HTTP リクエストを実ブラウザ相当に整える共通ヘッダ。

RSS 配信元や画像ホストの anti-bot に、既定のライブラリ UA
(feedparser/x.y.z, "news-picker thumbnail fetcher" など) が
403 で弾かれるのを避ける。素直な最新 Chrome 相当の UA に加え、
実ブラウザなら必ず送る Accept / Accept-Language を添える。

ddgs 検索 (search_web.py) はここを使わない: primp が UA・Accept・
Accept-Language・TLS フィンガープリントまで自前で偽装するため、
ここで整える余地がない (弾かれる場合はレート制限側の問題)。
"""
from __future__ import annotations

# 素直な最新 Chrome 相当。奇をてらった偽装はせず、よくある UA に寄せる
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 日本語優先 + 英語フォールバック。ja サイトを主に見る前提
ACCEPT_LANGUAGE = "ja,en-US;q=0.8,en;q=0.5"


def browser_headers(accept: str) -> dict[str, str]:
    """UA + Accept-Language に、用途別の Accept を足したヘッダを返す。

    accept: 取得物に応じた Accept ヘッダ (RSS/XML なら application/xml 系、
            画像なら image/* 系) を呼び出し側から渡す。
    """
    return {
        "User-Agent": USER_AGENT,
        "Accept": accept,
        "Accept-Language": ACCEPT_LANGUAGE,
    }


# RSS/Atom 取得用 (XML を優先しつつ何でも受ける)
FEED_ACCEPT = "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5"

# 画像取得用
IMAGE_ACCEPT = "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"
