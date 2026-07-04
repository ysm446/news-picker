"""パスとカテゴリ設定の読み込み。

カテゴリはコード変更なしで追加できるよう config/categories.yaml 駆動
(docs/news-picker-spec.md §5)。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("NEWS_PICKER_DATA_DIR", ROOT / "data"))
VAULT_DIR = DATA_DIR / "news-vault"
DB_PATH = DATA_DIR / "news.db"
CATEGORIES_PATH = ROOT / "config" / "categories.yaml"

LLM_9B_URL = os.environ.get("NEWS_PICKER_LLM_9B", "http://127.0.0.1:8081")
LLM_35B_URL = os.environ.get("NEWS_PICKER_LLM_35B", "http://127.0.0.1:8082")

# 自動整理: new/seen のままこの日数を超えた記事をパージ (saved/hidden は対象外)
RETENTION_DAYS = int(os.environ.get("NEWS_PICKER_RETENTION_DAYS", "14"))


@dataclass
class Category:
    id: str
    label: str
    keywords: list[str] = field(default_factory=list)
    query_templates: list[str] = field(default_factory=list)
    poll_interval_sec: int = 300
    jitter_sec: int = 60
    impact_axis: list[str] = field(default_factory=lambda: ["notable", "minor"])
    max_window: int = 40
    summary_prompt: str = ""


def load_categories(path: Path | None = None) -> list[Category]:
    path = path or CATEGORIES_PATH
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return [Category(**entry) for entry in raw.get("categories", [])]
