"""林业遥感模型参数手术工具：将微调过的 YOLO26x 骨干与 Neck 权重移植到 YOLOE-26x 多模态模型中。"""
from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any

import torch


def transplant_yolo_to_yoloe(
    src_yolo_pt: str | Path,
    dst_yoloe_pt: str | Path,
    out_pt: str | Path,
) -> dict[str, Any]:
    src_path = Path(src_yolo_pt).resolve()
    dst_path = Path(dst_yoloe_pt).resolve()
    out_path = Path(out_pt).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    m_src = torch.load(src_path, map_location="cpu", weights_only=False)
    m_dst = torch.load(dst_path, map_location="cpu", weights_only=False)

    src_model = m_src.get("model", m_src)
    dst_model = m_dst.get("model", m_dst)

    src_sd = src_model.state_dict() if hasattr(src_model, "state_dict") else src_model
    dst_sd = dst_model.state_dict() if hasattr(dst_model, "state_dict") else dst_model

    new_sd = copy.deepcopy(dst_sd)
    transplanted = 0
    shape_mismatches = 0
    retained_dst = 0

    for k, v in dst_sd.items():
        if k in src_sd:
            src_v = src_sd[k]
            if v.shape == src_v.shape:
                new_sd[k] = src_v.clone()
                transplanted += 1
            else:
                shape_mismatches += 1
        else:
            retained_dst += 1

    new_dst = copy.deepcopy(m_dst)
    if hasattr(new_dst.get("model"), "load_state_dict"):
        new_dst["model"].load_state_dict(new_sd, strict=False)
    elif "model" in new_dst and isinstance(new_dst["model"], dict):
        new_dst["model"] = new_sd

    torch.save(new_dst, out_path)
    return {
        "transplanted": transplanted,
        "shape_mismatches": shape_mismatches,
        "retained_dst": retained_dst,
        "output_path": str(out_path),
        "output_size_mb": round(out_path.stat().st_size / (1024 * 1024), 2),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="移植微调 YOLO26x 骨干至 YOLOE-26x")
    parser.add_argument("--src", default=".4estDS/models/m07-yolo26x-7d20f-det-2cls-e152_baseTrain15.pt")
    parser.add_argument("--dst", default=".4estDS/models/multimodal/yoloe-26x-seg.pt")
    parser.add_argument("--out", default=".4estDS/models/multimodal/yoloe-26x-m07.pt")
    args = parser.parse_args()

    stats = transplant_yolo_to_yoloe(args.src, args.dst, args.out)
    print(f"移植完成: 移植张量={stats['transplanted']}, 输出={stats['output_path']} ({stats['output_size_mb']}MB)")
