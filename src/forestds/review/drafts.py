"""复核草稿文件存储：原子快照是恢复事实源。"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .. import paths
from .domain import ReviewNotFound, ReviewWorkspace


class DraftStore:
    def __init__(self, root: Path | None = None):
        self.root = root or (paths.subdir("tmp") / "review_drafts")
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, session_id: str) -> Path:
        return self.root / f"{session_id}.json"

    def save(self, session_id: str, workspace: ReviewWorkspace) -> Path:
        target = self.path_for(session_id)
        payload = json.dumps(workspace.as_dict(), ensure_ascii=False, separators=(",", ":"))
        fd, raw_path = tempfile.mkstemp(prefix=f".{session_id}-", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(raw_path, target)
        finally:
            if os.path.exists(raw_path):
                os.unlink(raw_path)
        return target

    def load(self, session_id: str) -> ReviewWorkspace:
        path = self.path_for(session_id)
        if not path.exists():
            raise ReviewNotFound("复核草稿文件不存在。", code="draft_not_found", details={"session_id": session_id})
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return ReviewWorkspace.from_dict(value)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ReviewNotFound("复核草稿损坏，无法恢复。", code="draft_corrupt", details={"session_id": session_id}) from exc
