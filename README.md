# 4estDS - 林木智能检测系统

4estDS 是面向红树林/林地正射影像的单木智能解译系统。当前代码已经形成三条可用入口:

- 命令行: `4estds infer/preprocess/report/export/track/...`
- 服务端: FastAPI `/api/v1` + Dramatiq/Redis GPU 队列
- 前端: React + Vite + MapLibre 的“一张图”业务控制台

系统目标是把超大 GeoTIFF、JPG、PNG 等影像处理为可追溯的单木观测、地块台账、统计报告、GIS 图层和跨时相生命周期结果。

## 快速开始

### 1. 安装后端

```bash
uv sync --all-extras
uv run 4estds --help
uv run 4estds db init
```

如果只做命令行/单测，`uv sync --all-extras` 可换成更轻的组合:

```bash
uv sync --extra detect --extra geo
```

### 2. 跑一次无权重冒烟推理

`mock` 后端不需要 GPU 和模型权重，适合确认切片、推理、WBF、入库、报告、导出链路是否能跑通。

```bash
uv run 4estds infer data/多源数据研究_徐闻/DOM/xuwen_1024px.jpg --arch mock --no-draw-box --export-format geojson
```

运行期数据默认写到 `~/.4estDS`，可用 `forestds_HOME=/path/to/workdir` 覆盖。目录结构包括:

- `config/config.yaml`: 用户级配置
- `db/4estds.sqlite`: 默认 SQLite 数据库
- `logs/`: 带 run_id 的任务日志
- `outputs/`: 推理报告、可视化、导出文件、静态切片等产物
- `models/`: 本地模型权重目录

### 3. 启动 API 与前端

终端 1:

```bash
uv run uvicorn forestds.api.main:app --reload --host 127.0.0.1 --port 8000
```

终端 2:

```bash
cd web
mise exec -- pnpm install --config.store-dir=/tmp/forestds-pnpm-store
mise exec -- pnpm run dev
```

浏览器打开 `http://127.0.0.1:5173`。Vite 会把 `/api` 代理到 `http://127.0.0.1:8000`。

### 4. 启动异步 Worker

前端任务中心提交推理作业时，需要 Redis 和 Dramatiq worker:

```bash
redis-server
REDIS_URL=redis://localhost:6379/0 uv run dramatiq forestds.worker.actors --processes 1 --threads 1
```

GPU 推理建议保持 `--processes 1 --threads 1`，当前 worker 会在进程内缓存检测器权重，避免每个作业重复加载模型。

## 完整教程

完整教程见 [docs/完整教程.md](docs/完整教程.md)。教程覆盖:

1. 本地环境准备与配置优先级
2. CLI 单图推理、批量推理、报告与 GIS 导出
3. 多源融合: CHM、DSM/DEM、LAS
4. 生命周期追踪: `db promote` 与 `track`
5. FastAPI、Worker、前端任务中心联调
6. 常见问题与验证命令

更短的上手版见 [docs/快速开始.md](docs/快速开始.md)。

## 当前架构

```text
Interface
  cli.py
  api/main.py + api/routers/*
  web/src/*

Application Service
  service.py
  contracts.py
  worker/actors.py

Use Cases
  tasks/infer.py
  tasks/batch.py
  tasks/preprocess_train.py
  tasks/train.py

Domain
  preprocess/     SCOPE 自标定、COG 路由、静态/动态切片
  engine/         统一 ImageSource + 窗口推理 + WBF 前坐标回写
  postprocess/    WBF 去重融合
  fusion/         CHM/DSM/DEM/LAS 树高与体积特征
  lifecycle/      跨时相单木匹配与生命周期
  report/         统计指标与报告渲染
  export/         GeoJSON/Shapefile/GPKG/CSV 导出

Infra
  db/             SQLite DDL/reader/writer，PostGIS 演进边界
  detect/         mock/ultralytics 检测器适配器
  api/storage.py  local/S3 风格对象存储抽象
  paths.py        ~/.4estDS 运行期目录
```

关键设计原则:

- CLI、Worker、未来 SDK 统一复用 `service.run_inference_job` 的 run 生命周期。
- API 层只做 HTTP 边界，业务下沉到 service、tasks、db。
- 推理内核只依赖 `ImageSource` 与 `BaseDetector`，不绑定具体文件格式或模型实现。
- 数据库采用“原始观测 -> 地块规范单木 -> 跨时相个体”的三层模型。

## 常用命令

```bash
# 数据库
uv run 4estds db init
uv run 4estds db promote --run-id <run_id>

# 预处理
uv run 4estds preprocess path/to/image.tif
uv run 4estds preprocess path/to/image.tif --action static --out-dir /tmp/forestds_tiles

# 单图推理
uv run 4estds infer path/to/image.tif --arch ultralytics
uv run 4estds infer path/to/image.tif --arch mock --tile-size 1024 --overlap-rate 0.1

# 目录或多图批量推理
uv run 4estds infer path/to/images_dir --arch ultralytics
uv run 4estds infer a.tif b.tif c.tif --arch mock
uv run 4estds batch --input-dir path/to/images_dir --glob "*.tif" --arch ultralytics

# 多源融合
uv run 4estds infer rgb.tif --dsm dsm.tif --dem dem.tif
uv run 4estds infer rgb.tif --chm chm.tif
uv run 4estds infer rgb.tif --las cloud.las --las-grid-size 0.05

# 报告与导出
uv run 4estds report --tract-id <tract_id> --run-id <run_id> --format pdf
uv run 4estds export --tract-id <tract_id> --run-id <run_id> --format geojson

# 生命周期追踪
uv run 4estds track --location <location>

# 测试
uv run pytest tests -q
cd web && mise exec -- pnpm run typecheck
cd web && mise exec -- pnpm run build
```

## API 入口

服务启动后:

- `GET /health`: 健康探针
- `POST /api/v1/uploads`: 上传影像
- `POST /api/v1/jobs/inspect-input`: 检查本地路径/目录并提取元数据
- `POST /api/v1/jobs/infer`: 提交异步推理作业
- `GET /api/v1/jobs`: 查询作业历史
- `GET /api/v1/jobs/{job_id}`: 查询作业状态
- `GET /api/v1/jobs/{job_id}/logs`: 增量读取日志
- `GET /api/v1/tracts`: 地块台账
- `GET /api/v1/tracts/summaries`: 全部地块摘要
- `GET /api/v1/tracts/{tract_id}/observations`: 单木 GeoJSON 图层
- `GET /api/v1/tracts/{tract_id}/report`: 在线生成报告
- `GET /api/v1/tracts/{tract_id}/export`: 导出 GIS 图层
- `GET /api/v1/tiles/tracts/{tract_id}/{z}/{x}/{y}`: 本地 GeoTIFF XYZ PNG 瓦片

## 前端功能

`web/` 当前是 React + Vite + Ant Design + MapLibre + TanStack Query:

- `/map`: 一张图工作台，地块、观测点/冠幅、时相对比、浮动分析模块
- `/dashboard`: 数据看板
- `/ledger`: 地块台账
- `/tasks`: 推理任务中心，路径检查、上传、参数控制、日志、产物浏览
- `/reports`: 报告中心
- `/alerts`: 预警中心
- `/invasion`: 入侵监测
- `/carbon`: 蓝碳/MRV
- `/admin`: 管理入口

前端环境变量示例在 `web/.env.example`。

## 配置

配置优先级从低到高:

1. `configs/default.yaml`
2. `~/.4estDS/config/config.yaml`
3. 环境变量 `forestds_SECTION__KEY=value`
4. CLI 显式参数

常见覆盖:

```bash
forestds_HOME=/data/forestds
forestds_CONFIG_FILE=/etc/forestds/config.yaml
forestds_detect__device=cuda
forestds_detect__verbose=false
forestds_postprocess__draw_box=false
REDIS_URL=redis://localhost:6379/0
```

## 文档地图

- [docs/README.md](docs/README.md): 文档索引
- [docs/快速开始.md](docs/快速开始.md): 最短上手
- [docs/完整教程.md](docs/完整教程.md): 端到端教程
- [docs/项目工作原理.md](docs/项目工作原理.md): 当前代码的数据流与架构说明
- [docs/数据库设计.md](docs/数据库设计.md): 新一代数据库表结构与层级设计
- [docs/实时方案.md](docs/实时方案.md): 当前技术方案快照
- [docs/有效区域与智能复核使用说明.md](docs/有效区域与智能复核使用说明.md): 有效区域、单 TIFF 复核、恢复发布与排错

## 开发验证

推荐验证顺序:

```bash
uv run pytest tests -q
cd web && mise exec -- pnpm run typecheck
cd web && mise exec -- pnpm run build
```

历史上全仓 `pytest` 可能会收集到 `scratch/` 下依赖本地数据的脚本；日常验证优先使用 `pytest tests -q`。
