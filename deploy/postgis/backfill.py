#!/usr/bin/env python3
"""SQLite -> PostGIS 迁移 / 回填脚本 (v1.0 部署工具)。

职责: 把现有本地 SQLite (WKT/TEXT 几何) 的六张表搬进 PostGIS，并将
``geom_point`` / ``geom_crown`` / ``footprint_geom`` 的 WKT 文本转为原生 geometry
(由 PostGIS ``ST_GeomFromText(wkt, srid)`` 完成，无需自写几何解析)。

设计：
- 幂等 UPSERT (ON CONFLICT DO UPDATE)，可重复执行。
- SRID 取自地块 crs_epsg，缺省 0。
- 仅依赖 psycopg (v3) 与标准库；WKT 列为空时写 NULL。

用法:
    python deploy/postgis/backfill.py \
        --sqlite ~/.4estDS/db/4estds.sqlite \
        --pg 'postgresql://forestds:forestds@localhost:5432/forestds'
先执行 schema.sql 建表，再运行本脚本。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from typing import Any, Iterable

# WKT 几何列 -> 需要 ST_GeomFromText 包裹的列名
GEOM_COLS = {"geom_point", "geom_crown", "footprint_geom"}

# 搬迁顺序: 先父后子，满足外键依赖。
TABLE_ORDER = [
    "run_logs",
    "tree_individuals",
    "tracts",
    "tract_sources",
    "tree_observations",
    "tract_trees",
]


def _sqlite_rows(sqlite_path: str, table: str) -> tuple[list[str], list[sqlite3.Row]]:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(f"SELECT * FROM {table}")
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    finally:
        conn.close()
    return cols, rows


def _tract_srid_map(sqlite_path: str) -> dict[str, int]:
    """tract_id -> crs_epsg，用于观测/规范单木的 SRID。"""
    conn = sqlite3.connect(sqlite_path)
    try:
        rows = conn.execute("SELECT tract_id, crs_epsg FROM tracts").fetchall()
    finally:
        conn.close()
    return {r[0]: (r[1] or 0) for r in rows}


def _build_insert(table: str, cols: list[str], srid_for: dict[str, int]) -> str:
    """构造幂等 UPSERT 语句，几何列用 ST_GeomFromText(%s, %s) 占位。"""
    placeholders = []
    for c in cols:
        if c in GEOM_COLS:
            placeholders.append("ST_GeomFromText(%s, %s)")
        else:
            placeholders.append("%s")
    col_list = ", ".join(f'"{c}"' for c in cols)
    pk = cols[0]  # 每表首列均为主键
    updates = ", ".join(f'"{c}"=EXCLUDED."{c}"' for c in cols if c != pk)
    return (
        f'INSERT INTO {table} ({col_list}) VALUES ({", ".join(placeholders)}) '
        f'ON CONFLICT ("{pk}") DO UPDATE SET {updates}'
    )


def _row_params(
    table: str, cols: list[str], row: sqlite3.Row, srid_map: dict[str, int]
) -> list[Any]:
    """展开一行的参数；几何列额外追加 SRID 参数。"""
    # 行级 SRID: tracts 用自身 crs_epsg；子表用其 tract_id 对应的 SRID。
    if table == "tracts":
        srid = row["crs_epsg"] or 0
    elif "tract_id" in cols:
        srid = srid_map.get(row["tract_id"], 0)
    else:
        srid = 0
    params: list[Any] = []
    for c in cols:
        val = row[c]
        if c in GEOM_COLS:
            params.append(val)          # WKT 文本(可为 None)
            params.append(int(srid))     # SRID
        else:
            params.append(val)
    return params


def migrate(sqlite_path: str, pg_dsn: str) -> None:
    try:
        import psycopg  # psycopg v3
    except ImportError:
        sys.exit("需要 psycopg (v3): pip install 'psycopg[binary]'")

    srid_map = _tract_srid_map(sqlite_path)
    total = 0
    with psycopg.connect(pg_dsn) as pg:
        for table in TABLE_ORDER:
            try:
                cols, rows = _sqlite_rows(sqlite_path, table)
            except sqlite3.OperationalError:
                print(f"[skip] SQLite 无表 {table}")
                continue
            if not rows:
                print(f"[ok]   {table}: 0 行")
                continue
            sql = _build_insert(table, cols, srid_map)
            with pg.cursor() as cur:
                for row in rows:
                    cur.execute(sql, _row_params(table, cols, row, srid_map))
            pg.commit()
            total += len(rows)
            print(f"[ok]   {table}: {len(rows)} 行已搬迁")
    print(f"完成，共搬迁 {total} 行。")


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="SQLite -> PostGIS 迁移/回填")
    ap.add_argument("--sqlite", required=True, help="源 SQLite 文件路径")
    ap.add_argument("--pg", required=True, help="目标 PostGIS DSN")
    args = ap.parse_args(list(argv) if argv is not None else None)
    migrate(args.sqlite, args.pg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
