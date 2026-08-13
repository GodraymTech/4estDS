"""Cooperative cancellation for long-running jobs.

The worker may run in a different process from the API server. A tiny file flag
under the project runtime home gives both processes a shared, dependency-free
signal that can be checked inside hot loops.

批量作业还需要「顶层终止能夹断正在跑的那一张影像」。子运行(单图)与顶层运行
(批量)总是位于同一个 worker 进程内，因此用一个进程内的父子登记表把子 run 的
取消判定挂到顶层 run 的文件标志上，无需为每个子 run 再写一份磁盘标志。
"""
from __future__ import annotations

from pathlib import Path

from . import paths


class JobCancelled(RuntimeError):
    """Raised when a running job has been cancelled by the user."""


# 子 run_id -> 顶层 run_id。仅在 worker 进程内有效，随进程退出自然消失。
_parent_links: dict[str, str] = {}


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


def link_cancel(child_run_id: str, parent_run_id: str | None) -> None:
    """把子运行的取消判定挂到顶层运行上(顶层被终止时子运行同步夹断)。"""
    if parent_run_id and child_run_id and child_run_id != parent_run_id:
        _parent_links[child_run_id] = parent_run_id


def unlink_cancel(child_run_id: str) -> None:
    """子运行结束后解除登记，避免进程内字典无限增长。"""
    _parent_links.pop(child_run_id, None)


def is_cancelled(run_id: str | None) -> bool:
    if not run_id:
        return False
    if _flag_path(run_id).exists():
        return True
    parent = _parent_links.get(run_id)
    return bool(parent) and _flag_path(parent).exists()


def check_cancelled(run_id: str | None) -> None:
    if is_cancelled(run_id):
        raise JobCancelled(f"用户已终止推理作业: {run_id}")
