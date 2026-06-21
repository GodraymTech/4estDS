"""推理内核层（Tile-level inference kernel）。

职责（仅限于此，不可越界）：
  - 根据图像尺寸生成瓦片窗口清单（四叉树策略）
  - 逐 tile 从 image_source 读取像素窗口，调用 detect/ 模型推理
  - 将检测框坐标从瓦片局部坐标系回写到全图坐标系
  - 跨瓦片 WBF 加权框融合去重
  - 批量文件级串行循环（batch.py）

不感知（严禁引入）：
  - 数据库（db/）
  - 文件系统路径与配置（paths.py / config.py）
  - 报告（report/）、导出（export/）

调用关系：
  detect/ ← engine/ ← tasks/（单图 use-case）
                     ← engine/batch.py（批量 use-case，例外：含 DB 写入）
"""

from .batch import (
    BatchItemResult,
    BatchResult,
    discover_inputs,
    run_batch,
)
from .infer import (
    InferenceResult,
    run_inference,
)
from .sources import RasterImageSource

__all__ = [
    "BatchItemResult",
    "BatchResult",
    "InferenceResult",
    "RasterImageSource",
    "discover_inputs",
    "run_batch",
    "run_inference",
]
