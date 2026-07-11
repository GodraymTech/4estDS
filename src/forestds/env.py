"""Local environment loading helpers."""
from __future__ import annotations

import os
from pathlib import Path


def load_local_env() -> None:
    """Load a repo-level .env file without overriding existing environment variables."""
    candidates = (Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env")
    env_path = next((path for path in candidates if path.exists()), None)
    if env_path is None:
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")
