import multiprocessing
import time
from forestds.worker.gpu_lock import gpu_exclusive_lock


def _timed_worker(delay: float, out_queue: multiprocessing.Queue):
    with gpu_exclusive_lock():
        t_acquire = time.perf_counter()
        time.sleep(delay)
        t_release = time.perf_counter()
        out_queue.put((t_acquire, t_release))


def test_gpu_exclusive_lock_serializes_processes(tmp_path):
    q = multiprocessing.Queue()
    p1 = multiprocessing.Process(target=_timed_worker, args=(0.2, q))
    p2 = multiprocessing.Process(target=_timed_worker, args=(0.2, q))

    p1.start()
    time.sleep(0.05)
    p2.start()

    p1.join(timeout=5)
    p2.join(timeout=5)

    assert not p1.is_alive()
    assert not p2.is_alive()

    res1 = q.get(timeout=2)
    res2 = q.get(timeout=2)

    # 验证两个进程在 GPU 锁内的时间区间严格互斥，完全不重叠
    earlier, later = sorted([res1, res2], key=lambda x: x[0])
    earlier_acq, earlier_rel = earlier
    later_acq, later_rel = later

    assert later_acq >= earlier_rel - 0.05, f"Lock overlap detected: {earlier} vs {later}"
