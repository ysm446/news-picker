"""環境設定 (data/settings.json)。lm-chat の settings_store パターンを移植。

カテゴリ設定 (data/categories.yaml) とはファイルを分ける。
未知のキーは無視し、欠けているキーは既定値で補う。
"""
from __future__ import annotations

from . import config
from .atomic_io import atomic_write_json, read_json

DEFAULTS: dict = {
    "translate_titles": False,              # 見出しを日本語訳 (常駐モデル、キュレーション採点に相乗り)
    "noise_threshold": 30,                  # これ未満の relevance をノイズ扱い (UI フィルタ)
    "retention_days": config.RETENTION_DAYS,  # 自動整理の保持日数
    # 使用モデル (models/ からの相対パス)。役割: standard=常駐 / deep=深堀りチャット
    "model_standard": "Ornith-1.0-9B-GGUF/ornith-1.0-9b-Q4_K_M.gguf",
    "model_deep": "Ornith-1.0-35B-GGUF/ornith-1.0-35b-Q4_K_M.gguf",
}


def _path():
    return config.DATA_DIR / "settings.json"


def get() -> dict:
    data = read_json(_path(), {})
    return {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}


def update(values: dict) -> dict:
    current = get()
    for key, value in values.items():
        if key in DEFAULTS and value is not None:
            current[key] = value
    atomic_write_json(_path(), current)
    return current
