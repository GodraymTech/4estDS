"""4estDS 模型训练任务模块。

基于极简原则，深度整合 Ultralytics 官方接口，主要实现：
1. VOC、COCO、YOLO 格式数据集的自适应规整、拆分与转换（使用软链接，零拷贝且不破坏用户原始数据）。
2. 自适应生成 YOLO 训练所需的 data.yaml 配置文件。
3. 调用 Ultralytics 训练接口，并将训练产物原生落盘至系统统一的 run 目录中。
"""
from __future__ import annotations

import json
import os
import random
import shutil
import xml.etree.ElementTree as ET
import yaml
from pathlib import Path
from typing import Any, Dict, List, Tuple
from loguru import logger
from PIL import Image

from ultralytics import YOLO
from ultralytics.data.converter import convert_coco
from forestds import paths
from forestds.db import writer
from forestds.utils.annotations import parse_voc_file
from ultralytics.utils.ops import xyxy2xywhn

# 启用 faulthandler 以在 segfault 时输出 Python traceback
import faulthandler as _faulthandler
_faulthandler.enable()


def patch_torch_save():
    import torch
    import torch.serialization
    import pickle

    try:
        original_save = torch.serialization._save

        def patched_save(obj, zip_file, pickle_module, pickle_protocol, _disable_byteorder_record):
            class WrappedPickleModule:
                def __init__(self, orig):
                    self.orig = orig

                def __getattr__(self, name):
                    if name == 'Pickler':
                        OrigPickler = getattr(self.orig, 'Pickler')

                        class InterceptingPickler(OrigPickler):
                            def __init_subclass__(cls, **kwargs):
                                super().__init_subclass__(**kwargs)
                                if 'persistent_id' in cls.__dict__:
                                    original_pid = cls.persistent_id

                                    def safe_persistent_id(*args, **kwargs):
                                        if len(args) >= 2:
                                            self_inst = args[0]
                                            obj = args[1]
                                        elif len(args) == 1:
                                            # 如果只有一个参数，根据它是否是 Pickler 实例来区分是 (self,) 还是 (obj,)
                                            if isinstance(args[0], OrigPickler):
                                                self_inst = args[0]
                                                obj = None
                                            else:
                                                self_inst = None
                                                obj = args[0]
                                        else:
                                            self_inst = None
                                            obj = None
                                        return original_pid(self_inst, obj)

                                    cls.persistent_id = safe_persistent_id

                        return InterceptingPickler
                    return getattr(self.orig, name)

            wrapped_pickle = WrappedPickleModule(pickle_module)
            return original_save(obj, zip_file, wrapped_pickle, pickle_protocol, _disable_byteorder_record)

        torch.serialization._save = patched_save
        logger.info("已成功应用动态 CPython 3.12 序列化兼容性补丁。")
    except Exception as e:
        logger.warning(f"应用序列化兼容性补丁失败: {e}")


def ensure_data_yaml(
    data_dir_str: str, 
    dataset_format: str, 
    run_dir: Path,
    old_data_dir: str | None = None,
    new_sample_rate: float | None = None,
    old_sample_rate: float | None = None,
    new_ratio_min: float | None = None,
    neg_ratio: float | None = None,
) -> Path:
    """数据集校验与自适应结构规整，并动态生成对应的 data.yaml。
    
    返回:
        生成的 data.yaml 的绝对路径。
    """
    from .preprocess_train import preprocess_train_dataset
    from forestds.config import load_settings
    
    settings = load_settings()
    tp_cfg = settings.get("train_preprocess", {})
    
    act_new_sr = new_sample_rate if new_sample_rate is not None else tp_cfg.get("new_sample_rate", 1.0)
    act_old_sr = old_sample_rate if old_sample_rate is not None else tp_cfg.get("old_sample_rate", 1.0)
    act_new_rm = new_ratio_min if new_ratio_min is not None else tp_cfg.get("new_ratio_min", 0.1)
    act_neg_r = neg_ratio if neg_ratio is not None else tp_cfg.get("neg_ratio", 0.1)

    dest_dir = run_dir / "dataset"
    data_yaml_path = preprocess_train_dataset(
        data_dir=data_dir_str,
        old_data_dir=old_data_dir,
        new_sample_rate=act_new_sr,
        old_sample_rate=act_old_sr,
        new_ratio_min=act_new_rm,
        neg_ratio=act_neg_r,
        dest_dir=dest_dir,
    )
    return data_yaml_path


def run_train(
    data_dir: str,
    model_path: str,
    cfg_path: str,
    dataset_format: str = "YOLO",
    run_id: str | None = None,
    old_data_dir: str | None = None,
    new_sample_rate: float | None = None,
    old_sample_rate: float | None = None,
    new_ratio_min: float | None = None,
    neg_ratio: float | None = None,
) -> Dict[str, Any]:
    """4estDS 模型训练入口。
    
    解析和规整数据集，装载配置文件参数，直接调用官方 Ultralytics YOLO 进行训练。
    """
    # 动态应用 CPython 3.12 序列化补丁以支持 YOLO 模型保存
    patch_torch_save()

    # 强制打通并重置 ultralytics 日志通道，使之能向上传播并写入项目日志文件
    import logging
    ultra_log = logging.getLogger("ultralytics")
    ultra_log.propagate = True
    ultra_log.handlers = []

    logger.info("=" * 60)
    logger.info("4estDS 模型训练启动中...")
    logger.info(f"输入数据集: {data_dir} (格式: {dataset_format})")
    logger.info(f"基底模型: {model_path}")
    logger.info(f"参数配置: {cfg_path}")
    logger.info("=" * 60)

    # 1. 验证配置文件
    actual_cfg_path = Path(cfg_path).resolve()
    if not actual_cfg_path.exists():
        # 如果传入的不是绝对路径，尝试从项目根目录 configs/ 下查找
        fallback_path = Path(__file__).resolve().parent.parent.parent.parent / "configs" / cfg_path
        if fallback_path.exists():
            actual_cfg_path = fallback_path
        else:
            raise FileNotFoundError(f"配置文件未找到: {cfg_path}")

    # 读取配置文件以获取用户覆盖的训练参数
    with open(actual_cfg_path, "r", encoding="utf-8") as f:
        train_config = yaml.safe_load(f) or {}

    # 获取当前运行目录
    current_run_dir = paths.run_dir()
    current_run_dir.mkdir(parents=True, exist_ok=True)

    # 2. 规整并校验数据集，生成对应的 data.yaml
    data_yaml_path = ensure_data_yaml(
        data_dir_str=data_dir,
        dataset_format=dataset_format,
        run_dir=current_run_dir,
        old_data_dir=old_data_dir,
        new_sample_rate=new_sample_rate,
        old_sample_rate=old_sample_rate,
        new_ratio_min=new_ratio_min,
        neg_ratio=neg_ratio,
    )


    # 3. 组装 Ultralytics YOLO 训练参数
    # 我们利用 YOLO 官方支持的 `project` 与 `name` 参数，实现产物直降 run_dir 目录
    train_kwargs = train_config.copy()
    
    # 强制覆盖的关键路径参数，使用 4estDS 体系路径
    train_kwargs["data"] = str(data_yaml_path)
    train_kwargs["project"] = str(paths.outputs_dir())
    train_kwargs["name"] = current_run_dir.name
    train_kwargs["exist_ok"] = True  # 避免 YOLO 添加数字后缀

    # 4. 加载基底模型并启动训练
    logger.info("载入模型权重并启动 YOLO 训练流程...")
    
    try:
        model = YOLO(model_path)
        # 写入运行日志 - 开始训练
        db_url = load_db_url()
        writer.start_run_log(
            run_id=run_id,
            task_type="train",
            model_arch=model_path,
            input_path=data_dir,
            params={
                "dataset_format": dataset_format,
                "config_file": str(actual_cfg_path),
                **train_config
            },
            url=db_url
        )
        
        # 执行训练
        # 这里的 **train_kwargs 已经包含了 yaml 配置里的全部林业推荐参数
        results = model.train(**train_kwargs)
        
        # 获取最终生成的模型路径
        best_pt_path = current_run_dir / "weights" / "best.pt"
        if not best_pt_path.exists():
            # 有可能未生成，查找 runs 结构
            logger.warning("在预期位置未找到 weights/best.pt，将扫描输出目录。")
            all_pt_files = list(current_run_dir.rglob("*.pt"))
            if all_pt_files:
                best_pt_path = all_pt_files[0]
                logger.info(f"定位到训练模型: {best_pt_path}")
            else:
                best_pt_path = None
                
        # 5. 更新运行日志 - 训练成功
        writer.finish_run_log(
            run_id=run_id,
            status="completed",
            error=None,
            url=db_url
        )
        
        logger.info(f"🎉 训练任务圆满完成！")
        if best_pt_path:
            logger.info(f"最佳模型权重位置: {best_pt_path}")
            
        return {
            "status": "success",
            "run_dir": str(current_run_dir),
            "best_model_path": str(best_pt_path) if best_pt_path else None,
            "results": results
        }
        
    except Exception as e:
        logger.exception("模型训练发生致命错误！")
        db_url = load_db_url()
        writer.finish_run_log(
            run_id=run_id,
            status="failed",
            error=str(e),
            url=db_url
        )
        raise e


def load_db_url() -> str | None:
    """载入数据库链接配置的辅助函数。"""
    try:
        from forestds.config import load_settings
        settings = load_settings()
        return settings.get("url", None)
    except Exception:
        return None
