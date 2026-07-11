"""本地开发模式下的 Dramatiq worker 进程控制。"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from .. import paths


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_worker_spawn_lock = threading.Lock()


def _local_worker_roots() -> list[int]:
    """返回当前项目、当前用户的 Dramatiq worker 主进程 PID。"""
    uid = os.getuid()
    candidates: dict[int, int] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == os.getpid():
            continue
        try:
            status = (entry / "status").read_text(encoding="utf-8", errors="ignore")
            if f"Uid:\t{uid}\t" not in status:
                continue
            cmdline = (
                (entry / "cmdline")
                .read_bytes()
                .decode("utf-8", errors="ignore")
                .replace("\0", " ")
            )
            cwd = Path(os.readlink(entry / "cwd")).resolve()
            stat = (entry / "stat").read_text(encoding="utf-8", errors="ignore").split()
        except (FileNotFoundError, PermissionError, OSError):
            continue
        if "dramatiq" not in cmdline or "forestds.worker.actors" not in cmdline:
            continue
        if cwd != _PROJECT_ROOT or len(stat) < 4:
            continue
        candidates[pid] = int(stat[3])

    return sorted(pid for pid, ppid in candidates.items() if ppid not in candidates)


def ensure_local_worker() -> bool:
    """按需启动当前项目的本机 GPU worker。

    返回值表示本次是否新建了进程。该能力仅用于本机一体化部署；已有
    worker 时不会干预其生命周期，也不会重复创建。
    """
    with _worker_spawn_lock:
        if _local_worker_roots():
            return False

        log_path = paths.logs_dir() / "worker.log"
        command = [
            sys.executable,
            "-m",
            "dramatiq",
            "forestds.worker.actors",
            "--queues",
            "gpu",
            "--processes",
            "1",
            "--threads",
            "1",
        ]
        with log_path.open("a", encoding="utf-8") as log_file:
            process = subprocess.Popen(
                command,
                cwd=_PROJECT_ROOT,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

        # Redis 不可用、依赖缺失等情况会在启动后立即退出，不能把一个无效 job_id
        # 交给前端。正常 worker 会在此期间保持运行并等待队列消息。
        time.sleep(0.2)
        exit_code = process.poll()
        if exit_code is not None:
            raise RuntimeError(
                f"本机推理 worker 启动失败（退出码 {exit_code}），请查看 {log_path}"
            )
        return True


def stop_local_workers() -> list[int]:
    """向当前项目、当前用户启动的 Dramatiq worker 主进程发送 SIGTERM。

    仅用于本机一体化部署。容器化/远程 worker 不共享 /proc，因此不会被误杀。
    """
    roots = _local_worker_roots()
    for pid in roots:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
    return roots
