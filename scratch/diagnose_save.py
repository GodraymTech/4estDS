import sys
import io
import torch
import traceback
from pathlib import Path
from copy import deepcopy

# 导入项目的 run_train
from forestds.tasks.train import run_train

# 递归寻找导致 torch.save 报错的罪魁祸首
def diagnose_object(obj, path="obj"):
    try:
        buffer = io.BytesIO()
        torch.save(obj, buffer)
        # 如果成功保存，说明这个对象本身和它的子代都是可以保存的
        return True
    except Exception as e:
        print(f"FAILED to save at path: {path} | Error: {type(e)} {e}")
        
        # 如果是字典，递归查每个 key-value
        if isinstance(obj, dict):
            for k, v in obj.items():
                diagnose_object(v, f"{path}['{k}']")
        # 如果是 list / tuple
        elif isinstance(obj, (list, tuple)):
            for idx, item in enumerate(obj):
                diagnose_object(item, f"{path}[{idx}]")
        # 如果是 nn.Module
        elif isinstance(obj, torch.nn.Module):
            # 检查属性
            for attr_name in dir(obj):
                # 避开内置属性和方法
                if attr_name.startswith("__"):
                    continue
                try:
                    attr_val = getattr(obj, attr_name)
                    if not callable(attr_val):
                        diagnose_object(attr_val, f"{path}.{attr_name}")
                except Exception:
                    pass
            # 检查子模块
            for name, module in obj.named_children():
                diagnose_object(module, f"{path}.{name} (Module)")
            # 检查 parameters 和 buffers
            for name, param in obj.named_parameters(recurse=False):
                diagnose_object(param, f"{path}.{name} (Parameter)")
            for name, buf in obj.named_buffers(recurse=False):
                diagnose_object(buf, f"{path}.{name} (Buffer)")
        return False

# Monkeypatch torch.save
original_torch_save = torch.save
def patched_torch_save(obj, f, *args, **kwargs):
    try:
        return original_torch_save(obj, f, *args, **kwargs)
    except TypeError as e:
        if "persistent_id" in str(e):
            print("\n" + "="*50)
            print("DETECTED persistent_id TypeError in torch.save! Starting recursive diagnosis...")
            print("="*50)
            diagnose_object(obj)
            print("="*50 + "\n")
        raise e

torch.save = patched_torch_save

# 启动训练跑 1 个 epoch (我们可以通过修改 kwargs 或临时覆盖 cfg)
# 这里我们直接运行 run_train，但在此之前我们需要修改 configs/ultralytics_train.yaml，
# 或者我们在运行前临时修改读取出的 config 字典？
# 没关系，直接运行 run_train 即可，因为在 train.py 里会去读 configs/ultralytics_train.yaml。
# 我们可以临时把 epochs 强制改为 1，避免跑太久。
# 我们可以 monkeypatch yaml.safe_load 来在读取 configs/ultralytics_train.yaml 时强制将 epochs 改为 1。
import yaml
original_safe_load = yaml.safe_load
def patched_safe_load(stream):
    data = original_safe_load(stream)
    if isinstance(data, dict) and "epochs" in data:
        data["epochs"] = 1
        data["save"] = True
        print("Patched config to epochs=1, save=True for fast debugging.")
    return data
yaml.safe_load = patched_safe_load

if __name__ == "__main__":
    try:
        run_train(
            data_dir=".4estDS/outputs/20260623_0233_fdc28_train/dataset",
            model_path=".4estDS/outputs/20260623_0317_b8510_train/weights/last.pt",
            cfg_path="configs/ultralytics_train.yaml",
            dataset_format="YOLO"
        )
    except Exception as e:
        print("Training terminated with error:")
        traceback.print_exc()
