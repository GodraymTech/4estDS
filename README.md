# 4estDS — 红树林单木智能解译平台

> Mangrove individual-tree intelligent interpretation platform.
> 从超大正射影像中,自动、可追溯地解译每一棵红树,并跨时相追踪其生命周期。

本仓库是分阶段构建的工程骨架。**每个阶段都保证可运行、可测试、可独立 commit**;尚未完成的功能以 `TODO` 显式标记,不影响整体运行。

---

## 为什么

红树林监测面临三个工程难点,本项目逐一对应:

1. **超大影像 + 固定输入的检测器** → 创新点 A:最优多尺度规则切片(本仓库已实现数学核心)。
2. **RGB 信息不足以判高/判种** → 创新点 B:RGB + CHM/多光谱跨模态融合。
3. **多期影像如何认出"同一棵树"** → 创新点 C:单木生命周期追踪(项目最核心价值)。

---

## 安装

推荐使用 [uv](https://github.com/astral-sh/uv):

```bash
# 仅核心(可跑 CLI / 切片优化 / 建库)
uv sync

# 按需安装重依赖(按模块分组,不必一次装全)
uv sync --extra geo --extra yolo --extra infer --extra preprocess --extra db
```

或用 pip:

```bash
pip install -e ".[dev]"
```

> ⚙️ **优雅降级设计**:`loguru / typer / pydantic-settings / sqlalchemy` 等重依赖在
> `pyproject.toml` 中声明。运行时**装了就用、没装自动回退到标准库**,因此最小环境下
> CLI、切片优化、`db init`、全部单元测试都能直接跑通。

---

## 快速开始

```bash
4estds --version
4estds db init                 # 在 ~/.4estDS/db 下创建三层单木模型
4estds preprocess              # 运行创新点 A 的切片优化演示
4estds infer --arch mock       # 端到端跑通:切片->推理->WBF去重->入库(无需 GPU/权重)
4estds infer --arch yolo12 --image ortho.tif   # 真实推理(需 pip install '4estds[yolo]')
4estds infer --arch rtdetr --image ortho.tif   # RT-DETR 后端
pytest -q                      # 跑全部单元测试
```

运行期数据目录默认 `~/.4estDS`(可用环境变量 `FOURESTDS_HOME` 覆盖),
子目录:`config / cache / logs / db / outputs / models / tmp`。

---

## 创新点 A:最优多尺度规则切片(已实现核心)

一句话:**给定影像 GSD 与检测器输入尺寸,自动算出最优的切片边长 T\* 与重叠 o\*,并给出可证明的最优性**,而不是拍脑袋设 1024/overlap=0.2。

关键函数(`src/fourestds/preprocess/slicing.py`,均为纯 Python、可单测):

| 步骤 | 函数 | 作用 |
|------|------|------|
| GSD 归一 | `crown_px_size` | 物理冠幅(米)→ 像素尺寸 |
| 截断概率 | `truncation_probability` / `expected_truncation` | 目标被网格切断的概率 |
| 最优参数 | `optimize_tile_params` | 约束优化求 (T\*, o\*):可检测性 + 完整性 + 算力代价 |
| 尺度聚类 | `cluster_scales` | log 域 1D k-means 得离散最优尺度集 |
| 四叉树 | `build_quadtree` | 规则 2×2 递归细分,每区只切一次;单尺度时退化为均匀网格 |
| nodata 跳过 | `integral_image` / `region_sum` | 积分图 O(1) 查询区域有效像素,全 nodata 直接跳过 |
| 特征尺度 | `characteristic_scale` | Lindeberg 归一化 LoG 自动尺度选择(可选,需 numpy) |

**优化目标**(对每个尺度档):

```
minimize   cost(T, o) = 算力代价(∝ 1/(T-o)²) + λ · 期望截断
subject to (可检测性) T ≤ model_input · scale_px / d_min
           (完整性)   截断概率(w_large, T, o) ≤ ε
```

---

## 数据库:三层单木模型(已实现建表)

解决"重复推理污染"——同一棵树在多张子图/多次 run 中被反复检出:

```
tree_observations   原始观测(可重复,每次 run / 每个切片都记)
      │  同一时相择优去重
      ▼
tract_trees         地块规范单木(某时相的"权威"株)
      │  跨时相同株匹配
      ▼
tree_individuals    跨时相独立个体(生命周期 / 生长轨迹)
```

外加 `run_logs`(全任务可追溯)、`tracts`(地块,`acquisition_time` YYYYMM + `location` 联合唯一)、`tract_sources`(多源:RGB/CHM/多光谱)。

- 本地:SQLAlchemy 2.0 ORM(`db/models.py`)+ Alembic(TODO)。
- 最小环境:标准库 sqlite3 DDL(`db/schema.py`),`4estds db init` 即建表。
- 几何列以 WKT/GeoJSON 文本存储,迁移 PostGIS 后转原生几何。

---

## 模型:双架构可插拔

`detect/` 下用 `BaseDetector` 抽象 + 注册表,CLI `--arch yolo12|rtdetr|mock` 选择后端。
上层(切片、后处理、入库)对具体架构无感知。重依赖(ultralytics/torch)延迟导入。

`engine/runner.py` 是推理编排器:四叉树 tile 清单 → `clamp_window` 裁边界 → 逐 tile 推理
→ `offset` 回写全图坐标 → WBF 去重 → `db/writer.py` 写 `tree_observations` + `run_logs`。
不落地裁切图,读窗按需取像素;`mock` 后端 + `SyntheticImageSource` 使整链路在无 GPU/无网端到端可跑。

---

## 商业化授权(规划)

采用 Supabase Auth 取代自建 users 表;权限按**功能(feature)**而非套餐(plan)授权——
*"Don't gate by plans, gate by features"*。`entitlements` + RLS / Edge Function 控制每个功能键,
FastAPI 中间件校验 JWT 与 feature key。(TODO,阶段后期)

---

## 阶段路线图

- [x] 阶段一 底座:配置/路径/日志/CLI 骨架(可运行)
- [x] 阶段二 数据库:三层单木模型建表 + ORM(`db init` 可用)
- [x] 阶段四 创新点 A:切片优化数学核心(可单测)
- [x] 阶段三 推理引擎:切片清单编排 + WBF 去重 + 观测入库;mock 端到端可跑;yolo12/rtdetr 真实后端 + 分批推理 + 栓格影像源已接(需装 ultralytics/rasterio)
- [~] 阶段五 后处理:尺度感知 WBF 基础(去重增强 TODO)
- [~] 阶段六 统计报告 / 批量处理(出图与导出 TODO)
- [~] 阶段七 创新点 B:多源融合(CHM 求树高已有标量,接入栅格 TODO)
- [~] 阶段八 创新点 C:生命周期追踪(最近邻匹配基础,匈牙利/生长曲线 TODO)

图例:`[x]` 已可用 · `[~]` 骨架就绪 + TODO

---

## 开发

```bash
ruff check src tests
pytest -q
```

CI 见 `.github/workflows/ci.yml`(ruff + pytest)。
