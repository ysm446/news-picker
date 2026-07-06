"""パスとカテゴリ設定の読み込み。

カテゴリはコード変更なしで追加できるよう config/categories.yaml 駆動
(docs/news-picker-spec.md §5)。
"""
from __future__ import annotations

import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("NEWS_PICKER_DATA_DIR", ROOT / "data"))
VAULT_DIR = DATA_DIR / "news-vault"
DB_PATH = DATA_DIR / "news.db"

# カテゴリ設定は個人データなので data/ 側に置く (git 管理外)。
# リポジトリには雛形 (categories.example.yaml) のみを含め、初回起動時にコピーする
CATEGORIES_PATH = DATA_DIR / "categories.yaml"
_CATEGORIES_EXAMPLE = ROOT / "config" / "categories.example.yaml"
_CATEGORIES_LEGACY = ROOT / "config" / "categories.yaml"  # 旧配置からの移行用

# LLM は役割ベースの2ポート構成 (特定モデルに依存しない):
# - standard: 常駐。詳細生成・カテゴリ要約・キュレーション・チャット代行
# - deep:     深堀りチャット用。手動ロード/アンロード
LLM_STANDARD_URL = os.environ.get(
    "NEWS_PICKER_LLM_STANDARD",
    os.environ.get("NEWS_PICKER_LLM_9B", "http://127.0.0.1:8081"),
)
LLM_DEEP_URL = os.environ.get(
    "NEWS_PICKER_LLM_DEEP",
    os.environ.get("NEWS_PICKER_LLM_35B", "http://127.0.0.1:8082"),
)
MODELS_DIR = ROOT / "models"

# 自動整理: new/seen のままこの日数を超えた記事をパージ (saved/hidden は対象外)
RETENTION_DAYS = int(os.environ.get("NEWS_PICKER_RETENTION_DAYS", "14"))


@dataclass
class Category:
    id: str
    label: str
    description: str = ""  # カテゴリの狙い。キュレーション (採点) の基準にも渡される
    keywords: list[str] = field(default_factory=list)
    query_templates: list[str] = field(default_factory=list)
    feeds: list[str] = field(default_factory=list)  # RSS/Atom フィード URL (検索と併用可)
    poll_interval_sec: int = 300
    jitter_sec: int = 60
    impact_axis: list[str] = field(default_factory=lambda: ["notable", "minor"])
    max_window: int = 40
    summary_prompt: str = ""
    enabled: bool = True  # False で列を非表示 + 取り込み・要約も止める


def _ensure_categories_file(path: Path) -> None:
    """data/categories.yaml が無ければ旧配置 → 雛形の順でコピーして作る。"""
    if path.exists():
        return
    source = _CATEGORIES_LEGACY if _CATEGORIES_LEGACY.exists() else _CATEGORIES_EXAMPLE
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, path)


def load_categories(path: Path | None = None) -> list[Category]:
    if path is None:
        path = CATEGORIES_PATH
        _ensure_categories_file(path)
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return [Category(**entry) for entry in raw.get("categories", [])]


def save_categories(categories: list[Category], path: Path | None = None) -> None:
    """categories.yaml を書き戻す (UI からの追加・編集・削除用)。"""
    from .atomic_io import atomic_write_text

    data = {"categories": [asdict(c) for c in categories]}
    atomic_write_text(
        path or CATEGORIES_PATH,
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
    )
