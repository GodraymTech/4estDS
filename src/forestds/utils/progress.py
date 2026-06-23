import sys
from loguru import logger

def track_progress(iterable, desc="Processing", total=None, log_interval=0.1):
    """
    智能进度追踪器，取代项目内零散的 tqdm。
    
    能够自动识别 items 嵌套容器并累计底层元素个数。
    log_interval: 非 TTY 环境下，每隔多少比例记录一次 log (0.1 表示 10%)
    """
    items = list(iterable)
    
    # 自动计算实际元素总数
    if total is not None:
        tot = total
    else:
        if len(items) > 0 and isinstance(items[0], (list, tuple)):
            tot = sum(len(x) for x in items)
        else:
            tot = len(items)
            
    # 场景一：如果是交互式终端，使用标准的 tqdm 滚动
    if sys.stdout.isatty():
        from tqdm import tqdm
        with tqdm(total=tot, desc=desc, leave=False, ncols=80) as pbar:
            for item in items:
                yield item
                step = len(item) if isinstance(item, (list, tuple)) else 1
                pbar.update(step)
            
    # 场景二：如果是文件重定向或后台运行，静默 tqdm，打印周期性 log
    else:
        logger.info(f"开始任务 [{desc}]，总计 {tot} 个项...")
        log_step = max(1, int(tot * log_interval))
        current = 0
        for item in items:
            yield item
            step = len(item) if isinstance(item, (list, tuple)) else 1
            current += step
            # 跨过步长区间时或最后结束时，输出格式化日志
            if (current - step) // log_step < current // log_step or current >= tot:
                # 限制最大显示 100% 避免微小浮动偏差
                ratio = min(1.0, current / tot) if tot > 0 else 1.0
                logger.info(f"[{desc}] 进度: {current}/{tot} ({ratio:.0%})")
