"""清理运行期目录管线 (tasks 层)"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
from pathlib import Path
from loguru import logger as log

from .. import paths
from ..db.schema import resolve_db_path

def run_clean_pipeline(
    level: str = "standard",
    db_url: str | None = None,
) -> dict:
    """执行多级别的清理任务管线。

    参数：
      level: 清理级别。支持 "standard" (智能GC)、"reset" (除models/config全删)、"deep" (全清)。
      db_url: 自定义数据库连接 URL。

    返回结果字典：{
        "status": "success",
        "deleted_files_count": int,
        "freed_bytes": int,
        "deleted_db_stats": dict[str, int],  # 每张表删除的记录行数
        "deleted_tracts": list[str],         # 被删除的地块 ID 列表
        "deleted_runs": list[str],           # 被删除的运行 ID 列表
        "deleted_outputs": list[str],        # 被删除的 outputs 子目录名列表
    }
    """
    level = level.lower().strip()
    if level not in ("deep", "reset", "standard"):
        raise ValueError(f"不支持的清理级别 '{level}'。可选: deep, reset, standard")

    root = paths.home_dir()
    
    # 结果统计数据
    stats = {
        "status": "success",
        "deleted_files_count": 0,
        "freed_bytes": 0,
        "deleted_db_stats": {},
        "deleted_tracts": [],
        "deleted_runs": [],
        "deleted_outputs": [],
    }

    if not root.exists():
        return stats

    if level == "deep":
        # 1. 最高级别：整个 home_dir 全删
        file_count, total_bytes = _gather_dir_stats(root)
        stats["deleted_files_count"] = file_count
        stats["freed_bytes"] = total_bytes
        
        try:
            shutil.rmtree(root)
            log.info(f"成功深度清空运行期根目录: {root}，释放空间: {total_bytes / 1024 / 1024:.2f} MB")
        except Exception as e:
            log.error(f"清理根目录失败: {e}")
            raise e
        return stats

    elif level == "reset":
        # 2. 第二级别：除了 models 和 config 外全清理
        for item in root.iterdir():
            if item.is_dir():
                if item.name in ("models", "config"):
                    log.info(f"保留子目录: {item.name}")
                    continue
                # 统计大小
                file_count, total_bytes = _gather_dir_stats(item)
                stats["deleted_files_count"] += file_count
                stats["freed_bytes"] += total_bytes
                
                # 清空内容，但保留目录本身
                _clear_dir_contents(item)
                log.info(f"已清空目录内容: {item.name}")
            else:
                # 根目录下的直属文件全部删除
                try:
                    stats["deleted_files_count"] += 1
                    stats["freed_bytes"] += item.stat().st_size
                    item.unlink()
                except Exception as e:
                    log.warning(f"删除根目录下文件 {item.name} 失败: {e}")
        return stats

    else:
        # 3. 日常标准清理级别 (standard)：智能垃圾回收
        # a. 扫描 logs 目录，统计现有 run_id 作为活动 Root Set
        active_run_ids = set()
        logs_dir = paths.logs_dir()
        if logs_dir.exists():
            for item in logs_dir.iterdir():
                if item.is_file() and item.suffix == ".log":
                    # 文件名格式: {LAUNCH_TIME}__{CURRENT_RUN_ID}__{task_type}.log
                    parts = item.stem.split("__")
                    if len(parts) >= 2:
                        run_id = parts[1]
                        if re.match(r"^[0-9a-f]{5,6}$", run_id):
                            active_run_ids.add(run_id)
        
        log.info(f"活动运行日志分析完成。当前活跃 run_id 数量: {len(active_run_ids)}")
        
        # b. 清空 cache 和 tmp
        for name in ("cache", "tmp"):
            d = root / name
            if d.exists() and d.is_dir():
                file_count, total_bytes = _gather_dir_stats(d)
                stats["deleted_files_count"] += file_count
                stats["freed_bytes"] += total_bytes
                _clear_dir_contents(d)
                log.info(f"已清空临时目录内容: {name}")

        # c. 智能对齐清理数据库
        db_file = resolve_db_path(db_url)
        if db_file.exists():
            try:
                conn = sqlite3.connect(db_file)
                conn.row_factory = sqlite3.Row
                try:
                    conn.execute("PRAGMA foreign_keys = ON")
                    
                    # 统计清理前各表数量
                    tables = ["runs", "tree_observations", "tracts", "tract_phases", "tiffs", "tree_individuals"]
                    counts_before = {}
                    for t in tables:
                        try:
                            counts_before[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                        except Exception:
                            counts_before[t] = 0
                    
                    # 确定要删除的 run_id 列表，并记录到 stats
                    deleted_runs = []
                    if active_run_ids:
                        placeholders = ",".join("?" for _ in active_run_ids)
                        rows = conn.execute(
                            f"SELECT run_id, task_type FROM runs WHERE run_id NOT IN ({placeholders})",
                            tuple(active_run_ids)
                        ).fetchall()
                    else:
                        rows = conn.execute("SELECT run_id, task_type FROM runs").fetchall()
                    
                    for r in rows:
                        deleted_runs.append(f"{r['run_id']} ({r['task_type']})")
                    stats["deleted_runs"] = deleted_runs

                    # 预先统计各表按地块分组即将被删除的行数（级联删除前操作）
                    obs_del_by_tract = {}
                    try:
                        if active_run_ids:
                            placeholders = ",".join("?" for _ in active_run_ids)
                            obs_del_rows = conn.execute(
                                "SELECT tp.tract_id, COUNT(*) as cnt FROM tree_observations o "
                                "JOIN tract_phases tp ON tp.tract_phase_pk=o.tract_phase_pk "
                                f"WHERE o.run_id NOT IN ({placeholders}) GROUP BY tp.tract_id",
                                tuple(active_run_ids)
                            ).fetchall()
                        else:
                            obs_del_rows = conn.execute(
                                "SELECT tp.tract_id, COUNT(*) as cnt FROM tree_observations o "
                                "JOIN tract_phases tp ON tp.tract_phase_pk=o.tract_phase_pk "
                                "GROUP BY tp.tract_id"
                            ).fetchall()
                        
                        for r in obs_del_rows:
                            obs_del_by_tract[r["tract_id"]] = r["cnt"]
                    except Exception as stats_err:
                        log.warning(f"预先统计地块单木删除数量失败: {stats_err}")

                    stats["deleted_db_by_tract"] = {
                        "tree_observations": obs_del_by_tract,
                    }

                    # 执行删除无用 runs
                    if active_run_ids:
                        placeholders = ",".join("?" for _ in active_run_ids)
                        conn.execute(
                            f"DELETE FROM runs WHERE run_id NOT IN ({placeholders})",
                            tuple(active_run_ids)
                        )
                    else:
                        conn.execute("DELETE FROM runs")

                    # 记录并删除无用地块 tracts
                    rows_tracts = conn.execute(
                        "SELECT tr.tract_id FROM tracts tr "
                        "WHERE NOT EXISTS ("
                        "  SELECT 1 FROM tract_phases tp "
                        "  JOIN tree_observations o ON o.tract_phase_pk=tp.tract_phase_pk "
                        "  WHERE tp.tract_pk=tr.tract_pk"
                        ")"
                    ).fetchall()
                    deleted_tracts = [r["tract_id"] for r in rows_tracts]
                    stats["deleted_tracts"] = deleted_tracts
                    
                    conn.execute(
                        "DELETE FROM tracts WHERE tract_pk NOT IN ("
                        "  SELECT DISTINCT tp.tract_pk FROM tract_phases tp "
                        "  JOIN tree_observations o ON o.tract_phase_pk=tp.tract_phase_pk"
                        ")"
                    )

                    # 清理独立的无用 tree_individuals
                    conn.execute(
                        "DELETE FROM tree_individuals WHERE individual_id NOT IN "
                        "(SELECT DISTINCT individual_id FROM tree_observations WHERE individual_id IS NOT NULL)"
                    )

                    conn.commit()

                    # 统计清理后的各表行数
                    counts_after = {}
                    for t in tables:
                        try:
                            counts_after[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                        except Exception:
                            counts_after[t] = 0

                    stats["deleted_db_stats"] = {
                        t: counts_before[t] - counts_after[t] for t in tables
                    }
                finally:
                    conn.close()
            except Exception as dberr:
                log.warning(f"智能清理数据库记录时发生异常: {dberr}")

        # d. 智能清理 outputs 目录
        outputs_dir = root / "outputs"
        if outputs_dir.exists() and outputs_dir.is_dir():
            deleted_outputs = []
            for item in outputs_dir.iterdir():
                if item.is_dir():
                    # 检验目录名中的任何下划线分割部分是否属于活动 run_id
                    name_parts = item.name.split("_")
                    has_active_run = any(part in active_run_ids for part in name_parts)
                    if not has_active_run:
                        file_count, total_bytes = _gather_dir_stats(item)
                        stats["deleted_files_count"] += file_count
                        stats["freed_bytes"] += total_bytes
                        
                        try:
                            shutil.rmtree(item)
                            deleted_outputs.append(item.name)
                        except Exception as e:
                            log.warning(f"删除无效输出目录 {item.name} 失败: {e}")
                elif item.is_file():
                    name_parts = re.split(r"[_\.\-]", item.name)
                    has_active_run = any(part in active_run_ids for part in name_parts)
                    if not has_active_run:
                        stats["deleted_files_count"] += 1
                        stats["freed_bytes"] += item.stat().st_size
                        try:
                            item.unlink()
                        except Exception as e:
                            log.warning(f"删除无效输出文件 {item.name} 失败: {e}")
            stats["deleted_outputs"] = deleted_outputs

        return stats

def _gather_dir_stats(path: Path) -> tuple[int, int]:
    """递归遍历统计目录下文件总数和总字节数。"""
    file_count = 0
    total_bytes = 0
    if not path.exists():
        return file_count, total_bytes
    if path.is_file():
        return 1, path.stat().st_size
    
    for root_dir, _, files in os.walk(path):
        for f in files:
            fp = Path(root_dir) / f
            try:
                if fp.is_file() and not fp.is_symlink():
                    file_count += 1
                    total_bytes += fp.stat().st_size
            except Exception:
                pass
    return file_count, total_bytes

def _clear_dir_contents(path: Path) -> None:
    """清空文件夹内的所有文件和子文件夹，但保留该文件夹本身。"""
    if not path.is_dir():
        return
    for item in path.iterdir():
        try:
            if item.is_dir() and not item.is_symlink():
                shutil.rmtree(item)
            else:
                item.unlink()
        except Exception as e:
            log.warning(f"清空 {item} 失败: {e}")
