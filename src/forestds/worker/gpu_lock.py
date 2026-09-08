"""跨进程 GPU 全局独占锁。

第一性原理：
- 本机（Linux / WSL）可能同时存在开发端与生产端进程，但物理 GPU 设备（CUDA 显存与计算核心）为有限共享资源。
- 采用 Linux 内核级文件排他锁（fcntl.flock）实现无死锁的跨进程互斥：
  1. 零网络依赖，零 TTL 超时误判风险（应对任意耗时的超大 TIFF 推理）；
  2. 进程异常退出、OOM 或被 SIGKILL (-9) 时，Linux 内核会在关闭文件描述符的瞬间自动释放锁；
  3. 内核级 FIFO 排队：未抢到锁的进程会被安全挂起，当前持有者释放后立即唤醒排队者。
"""
from __future__ import annotations

import fcntl
import os
import time
from contextlib import contextmanager
from pathlib import Path

from loguru import logger as log

DEFAULT_GPU_LOCK_PATH = "/tmp/4estds_gpu.lock"


@contextmanager
def gpu_exclusive_lock(lock_path: str | Path | None = None):
    """跨进程 GPU 独占排他锁上下文管理器。"""
    actual_path = Path(lock_path or os.environ.get("FORESTDS_GPU_LOCK_PATH", DEFAULT_GPU_LOCK_PATH))
    actual_path.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    fd = os.open(str(actual_path), os.O_CREAT | os.O_RDWR, 0o666)
    try:
        log.info("【GPU独占锁】正在请求独占锁 (path={})... 如有其他推理任务正在运行将自动排队", actual_path)
        fcntl.flock(fd, fcntl.LOCK_EX)
        waited_s = time.perf_counter() - t0
        if waited_s > 0.1:
            log.info("【GPU独占锁】排队等待结束，已成功获取 GPU 独占锁 (等待耗时: {:.2f}s)", waited_s)
        else:
            log.info("【GPU独占锁】已成功获取 GPU 独占锁，开始占用 GPU 执行计算")
        try:
            yield
        finally:
            log.info("【GPU独占锁】任务计算完毕，正在释放 GPU 独占锁")
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
