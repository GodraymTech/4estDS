"""读取层（阶段六）：为统计报告 / 导出提供查询。

纯标准库 sqlite3，返回普通 dict（与 ORM 解耦，保证无重依赖可跑）。
与 writer.py 对称： writer 管写、reader 管读。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ..logging_setup import get_logger
from .schema import init_db, resolve_db_path

log = get_logger(__name__)


def _connect(url: str | None) -> sqlite3.Connection:
    db_path: Path = resolve_db_path(url)
    if not db_path.exists():
        init_db(url)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


def get_tract(tract_id: str, *, url: str | None = None) -> dict | None:
    """取单个地块元信息。"""
    conn = _connect(url)
    try:
        row = conn.execute(
            "SELECT * FROM tracts WHERE tract_id=?", (tract_id,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def resolve_tract_id(
    *,
    tract_id: str | None = None,
    acquisition_time: str | None = None,
    location: str | None = None,
    url: str | None = None,
) -> str | None:
    """按 tract_id 或 (acquisition_time, location) 定位地块。"""
    if tract_id:
        return tract_id
    if not (acquisition_time and location):
        return None
    conn = _connect(url)
    try:
        row = conn.execute(
            "SELECT tract_id FROM tracts WHERE acquisition_time=? AND location=?",
            (acquisition_time, location),
        ).fetchone()
    finally:
        conn.close()
    return row["tract_id"] if row else None


def latest_run_for_tract(tract_id: str, *, url: str | None = None) -> str | None:
    """返回地块最近一次有观测的 run_id。"""
    conn = _connect(url)
    try:
        row = conn.execute(
            "SELECT o.run_id FROM tree_observations o "
            "JOIN run_logs r ON r.run_id = o.run_id "
            "WHERE o.tract_id=? ORDER BY r.started_at DESC LIMIT 1",
            (tract_id,),
        ).fetchone()
    finally:
        conn.close()
    return row["run_id"] if row else None


def fetch_observations(
    *,
    run_id: str | None = None,
    tract_id: str | None = None,
    url: str | None = None,
) -> list[dict]:
    """拉取观测记录。run_id / tract_id 至少传一个（可共同限定）。"""
    if not run_id and not tract_id:
        raise ValueError("fetch_observations 需要 run_id 或 tract_id")
    clauses, params = [], []
    if run_id:
        clauses.append("run_id=?")
        params.append(run_id)
    if tract_id:
        clauses.append("tract_id=?")
        params.append(tract_id)
    where = " AND ".join(clauses)
    conn = _connect(url)
    try:
        rows = conn.execute(
            f"SELECT * FROM tree_observations WHERE {where}", params
        ).fetchall()
    finally:
        conn.close()
    obs = _rows_to_dicts(rows)
    log.debug("fetch_observations: %d 条 (run_id=%s tract_id=%s)", len(obs), run_id, tract_id)
    return obs


def get_run(run_id: str, *, url: str | None = None) -> dict | None:
    conn = _connect(url)
    try:
        row = conn.execute(
            "SELECT * FROM run_logs WHERE run_id=?", (run_id,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def list_tracts(*, url: str | None = None) -> list[dict]:
    conn = _connect(url)
    try:
        rows = conn.execute(
            "SELECT * FROM tracts ORDER BY acquisition_time DESC, location"
        ).fetchall()
    finally:
        conn.close()
    return _rows_to_dicts(rows)
