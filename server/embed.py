"""Ruri v3-310m 埋め込み (lm-chat の embedder を改良して移植)。

lm-chat との違い: Ruri v3 は非対称エンコーダなので、クエリと文書で
プレフィックスを分ける (lm-chat はこれを付けておらず精度を落としていた。
plan.md 判断メモ参照)。次元数は 768 (store.EMBEDDING_DIM と一致必須)。
"""
from __future__ import annotations

import threading
from functools import lru_cache

from . import config

_MODEL_NAME = "cl-nagoya/ruri-v3-310m"
_CACHE_DIR = config.ROOT / "models" / "embeddings"

_QUERY_PREFIX = "検索クエリ: "
_DOCUMENT_PREFIX = "検索文書: "

_model = None
_lock = threading.Lock()


def _get_model():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer

                _model = SentenceTransformer(
                    _MODEL_NAME, cache_folder=str(_CACHE_DIR), device="cpu"
                )
    return _model


@lru_cache(maxsize=512)
def _embed(text: str) -> tuple[float, ...]:
    vector = _get_model().encode(
        text, normalize_embeddings=True, show_progress_bar=False
    )
    return tuple(float(x) for x in vector)


def embed_document(text: str) -> tuple[float, ...]:
    return _embed(_DOCUMENT_PREFIX + text)


def embed_query(text: str) -> tuple[float, ...]:
    return _embed(_QUERY_PREFIX + text)


def warmup() -> None:
    """起動時プリロード用 (初回はモデルダウンロードが走る)。"""
    _embed("warmup")
