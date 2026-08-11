"""原子替换写操作工具库 (Atomic Write Utilities)。

用于确保在大文件、GeoJSON、配置文件落盘时，不会出现由于中途写被打断或并发冲突导致文件内容损坏的问题。
原理：写入同目录下的临时 `.tmp` 文件 + 强制 `fsync` 刷盘 + `os.replace` 原子覆写。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(target_path: str | Path, content: str, encoding: str = "utf-8") -> Path:
    """以原子替换 (`os.replace`) 方式写入文本文件。"""
    path = Path(target_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    return path


def atomic_write_json(target_path: str | Path, data: Any, encoding: str = "utf-8") -> Path:
    """以原子替换方式写入 JSON 数据文件。"""
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return atomic_write_text(target_path, payload, encoding=encoding)
