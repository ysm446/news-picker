"""カードサムネイルのダウンロード・縮小キャッシュ。

取り込み時に得た image_url (ddgs の image / RSS の media サムネイル) を
初回要求時にダウンロードして長辺 480px の JPEG に縮小し、
data/cache/images/ に保存する。以降はキャッシュを配信する。

ホットリンクしないのは: 表示のたびに外部ホストへ飛ばない、リンク切れに
強い、記事のパージ・非表示と連動して削除できる (「一時的に取得」) ため。
"""
from __future__ import annotations

import io
import logging
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

from . import config, http_headers

log = logging.getLogger(__name__)

CACHE_DIR = config.DATA_DIR / "cache" / "images"
_MAX_EDGE = 480  # カード幅 (~300px) の HiDPI 表示に足りる長辺
_MIN_EDGE = 50   # これ未満はロゴ・トラッキングピクセルとみなして捨てる
_MAX_BYTES = 10 * 1024 * 1024
_TIMEOUT_SEC = 10
# 正直すぎる UA だと画像ホストの anti-bot/anti-hotlink に弾かれるため
# ブラウザ相当のヘッダで取得する
_HEADERS = http_headers.browser_headers(http_headers.IMAGE_ACCEPT)


def thumb_path(article_id: int) -> Path:
    return CACHE_DIR / f"{article_id}.jpg"


def get_or_fetch(article_id: int, image_url: str) -> Path | None:
    """キャッシュがあれば返し、なければ取得・縮小して保存する。失敗は None。"""
    path = thumb_path(article_id)
    if path.exists():
        return path
    # image_url はフィード/検索結果由来の非信頼データ。http(s) 以外
    # (file:// でのローカル読み出し、UNC パス等) は拒否する
    if urllib.parse.urlsplit(image_url).scheme not in ("http", "https"):
        log.info("thumb[%d] non-http url rejected: %s", article_id, image_url[:100])
        return None
    try:
        req = urllib.request.Request(image_url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as res:
            raw = res.read(_MAX_BYTES)
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as e:  # noqa: BLE001 - 画像取得失敗は記事表示に影響させない
        log.info("thumb[%d] fetch failed (%s): %s", article_id, image_url, e)
        return None
    if min(img.size) < _MIN_EDGE:
        log.info("thumb[%d] too small (%dx%d), skipped", article_id, *img.size)
        return None
    img = img.convert("RGB")
    img.thumbnail((_MAX_EDGE, _MAX_EDGE))
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".jpg.tmp")
    img.save(tmp, "JPEG", quality=80)
    tmp.replace(path)
    return path


def delete(article_id: int) -> None:
    """記事のパージ・非表示と連動してキャッシュ画像を消す。"""
    thumb_path(article_id).unlink(missing_ok=True)
