"""Cooperative cancellation for long-running jobs.

The worker may run in a different process from the API server. A tiny file flag
under the project runtime home gives both processes a shared, dependency-free
signal that can be checked inside hot loops.
"""
from __future__ import annotations

from pathlib import Path

from . import paths


class JobCancelled(RuntimeError):
    """Raised when a running job has been cancelled by the user."""


def _flag_path(run_id: str) -> Path:
    safe = "".join(ch for ch in run_id if ch.isalnum() or ch in ("-", "_"))
    return paths.home_dir() / "cancellations" / f"{safe}.cancel"


def request_cancel(run_id: str) -> None:
    flag = _flag_path(run_id)
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("cancelled\n", encoding="utf-8")


def clear_cancel(run_id: str) -> None:
    try:
        _flag_path(run_id).unlink()
    except FileNotFoundError:
        pass


def is_cancelled(run_id: str | None) -> bool:
    return bool(run_id) and _flag_path(run_id).exists()


def check_cancelled(run_id: str | None) -> None:
    if is_cancelled(run_id):
        raise JobCancelled(f"用户已终止推理作业: {run_id}")
