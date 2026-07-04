"""原子的ファイル書き込み(lm-chat の backend/atomic_io.py を移植)。

一時ファイルへ書いて fsync 後に os.replace で差し替えるため、
電源断や強制終了でもファイルが途中まで書かれた状態にならない。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path | str, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path | str, data) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False))


def read_json(path: Path | str, default):
    path = Path(path)
    if not path.exists():
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        # 壊れたファイルは .bak に退避して手動復旧の余地を残す
        try:
            path.replace(path.with_suffix(path.suffix + ".bak"))
        except OSError:
            pass
        return default
