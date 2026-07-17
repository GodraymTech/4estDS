# 有效区域与智能复核 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完整落实 `docs/有效区域与智能复核实施方案.md`，以 TIFF active run 为正式结果事实源，交付地块级有效区域闭环和单 TIFF 智能复核工作台。

**Architecture:** 保持现有模块化单体：HTTP 路由保持薄层，业务分别下沉到 effective-area 与 review 服务；SQLite/PostGIS 使用同一最终数据语义；前端按 FSD 增加实体、特性和懒加载页面。推理继续 window read，不建立全分辨率掩膜；复核草稿使用一张会话索引表加文件快照/增量日志，只有发布事务写 run 与 observations。

**Tech Stack:** Python 3.12、FastAPI、SQLite/PostGIS、Shapely、rasterio、pyogrio/GDAL、Dramatiq/Redis、Ultralytics YOLOE；React 18、TypeScript、MapLibre、Terra Draw、Turf、Zustand、React Query、Ant Design、Playwright。

## Global Constraints

- `effective_geom` 是地块级唯一现状值；空值等同 `boundary_geom`，不增加版本、来源或历史表。
- `tiffs.active_run_id` 是单 TIFF 正式结果唯一事实源；彻底删除 `tract_phases.active_run_id`，不迁移、不双写、不兼容旧数据库。
- 智能复核只支持 `phase_id + tiff_id` 定位的单图视野；attempt 不创建 run，发布才创建一条 `task_type=review` run。
- 发布必须在一个事务内创建 review run、写全量 observations、切换 TIFF active run、更新 session；失败全部回滚。
- 推理保持 on-the-fly window read；有效区域不生成整图掩膜，边界窗口仅生成局部 mask，结果按框中心点过滤。
- 首期检测框是人工编辑主对象；YOLOE-Seg mask 必须可预览和编辑，正负点不伪装成 YOLOE 能力，不预先建设 MVT。
- `/review`、Terra Draw、Turf 和复核编辑器使用动态 import，不进入普通页面首包；所有终端命令按仓库规则以 `rtk` 开头，Python 复用 `/home/ray/rays/repos/4estDS/.venv`，前端使用 `mise` 与 `pnpm`。
- Git 提交严格对应阶段 A-F，共六个功能提交；每个阶段在提交前完成对应 TDD、类型检查或构建验证，不为格式化或脚手架单独提交。

---

### Task 1: 阶段 A — TIFF active run 事实源与运行次数

**Files:**
- Modify: `src/forestds/db/models.py`
- Modify: `src/forestds/db/schema.py`
- Modify: `deploy/postgis/schema.sql`
- Modify: `src/forestds/db/reader.py`
- Modify: `src/forestds/db/writer.py`
- Modify: `src/forestds/api/schemas.py`
- Modify: `src/forestds/api/routers/assets.py`
- Modify: `src/forestds/api/routers/jobs.py`
- Modify: `src/forestds/api/routers/tracts.py`
- Modify: `src/forestds/report/metrics.py`
- Modify: `src/forestds/export/formats.py`
- Modify: `web/src/shared/api/types.ts`
- Modify: `web/src/shared/api/endpoints.ts`
- Modify: `web/src/features/ledger/LedgerTable.tsx`
- Modify: `web/src/features/tasks/TasksCenter.tsx`
- Test: `tests/test_tiff_active_runs.py`

**Interfaces:**
- Produces: `promote_run(run_id: str, *, url: str | None = None) -> None` 原子更新目标 `(phase_id, tiff_id)` 的 `tiffs.active_run_id`。
- Produces: `list_assets()` 每行返回 `active_run_id/run_id`, `run_count`, `run_status_counts`, `active_run_status`, `observation_count`, `detected_at`，聚合限定同一 `phase_id + tiff_id`。
- Produces: 作业历史支持 `phase_id` 与 `tiff_id` 过滤；台账“运行次数”链接使用这两个查询参数。

- [x] **Step 1: 写入失败测试，锁定多 TIFF 发布语义**

```python
def test_each_tiff_has_independent_active_run(clean_db):
    first, second = seed_two_tiffs_same_phase(clean_db)
    run_a = seed_succeeded_run(clean_db, first)
    run_b = seed_succeeded_run(clean_db, second)
    promote_run(run_a, url=clean_db)
    promote_run(run_b, url=clean_db)
    assert active_run(clean_db, first) == run_a
    assert active_run(clean_db, second) == run_b
    assert "active_run_id" not in table_columns(clean_db, "tract_phases")
```

同时覆盖：错误状态不能发布、run 缺少 TIFF 定位时报错、未发布 run 不影响地图/统计/导出、run_count 包含 infer/review 所有状态但不包含 attempt。

- [x] **Step 2: 运行测试确认因旧 phase 级事实源而失败**

Run: `rtk proxy env PYTHONPATH=<worktree>/src /home/ray/rays/repos/4estDS/.venv/bin/pytest tests/test_tiff_active_runs.py -q`

Expected: FAIL，原因包含 `tiffs.active_run_id` 不存在或仍写 `tract_phases.active_run_id`。

- [x] **Step 3: 最小实现 schema、发布和读取链路**

```sql
ALTERED FINAL SHAPE:
tiffs.active_run_id TEXT REFERENCES runs(run_id) ON DELETE SET NULL
runs.task_type CHECK (..., 'review')
-- tract_phases 不含 active_run_id
```

所有默认正式结果查询从 TIFF JOIN active run；显式 `run_id` 查询继续允许历史 run。台账使用一条分组查询聚合运行状态，不允许前端 N+1。

- [x] **Step 4: 接入台账与作业历史 UI 并回归**

Run: `rtk proxy mise exec -- pnpm run typecheck`（目录 `web`）

Run: `rtk proxy mise exec -- pnpm run build`（目录 `web`）

Run: `rtk proxy env PYTHONPATH=<worktree>/src /home/ray/rays/repos/4estDS/.venv/bin/pytest tests/test_tiff_active_runs.py tests/test_incremental_update.py -q`

Expected: 新增测试全部 PASS；若既有测试仍断言 phase active run，更新为 TIFF 语义。

- [x] **Step 5: 提交阶段 A**

```bash
rtk git add docs/superpowers/plans/2026-07-17-effective-area-smart-review.md src/forestds deploy/postgis web/src tests/test_tiff_active_runs.py tests/test_incremental_update.py
rtk git commit -m "feat(db): make TIFF active runs authoritative"
```

---

### Task 2: 阶段 B — 有效区域后端、推理、地图和导出闭环

**Files:**
- Modify: `src/forestds/db/models.py`
- Modify: `src/forestds/db/schema.py`
- Modify: `deploy/postgis/schema.sql`
- Create: `src/forestds/effective_area/__init__.py`
- Create: `src/forestds/effective_area/service.py`
- Create: `src/forestds/effective_area/importers.py`
- Create: `src/forestds/effective_area/windows.py`
- Modify: `src/forestds/api/schemas.py`
- Modify: `src/forestds/api/routers/tracts.py`
- Modify: `src/forestds/engine/sources.py`
- Modify: `src/forestds/engine/infer.py`
- Modify: `src/forestds/service.py`
- Modify: `src/forestds/report/metrics.py`
- Modify: `src/forestds/export/formats.py`
- Modify: `configs/default.yaml`
- Modify: `web/package.json`
- Modify: `web/pnpm-lock.yaml`
- Create: `web/src/entities/effective-area/index.ts`
- Create: `web/src/entities/effective-area/model.ts`
- Create: `web/src/features/effective-area-editor/GeometryEditorAdapter.ts`
- Create: `web/src/features/effective-area-editor/EffectiveAreaEditor.tsx`
- Create: `web/src/features/effective-area-editor/index.ts`
- Modify: `web/src/shared/api/types.ts`
- Modify: `web/src/shared/api/endpoints.ts`
- Modify: `web/src/pages/MapWorkspacePage.tsx`
- Modify: `web/src/features/ledger/LedgerTable.tsx`
- Modify: `web/src/features/tasks/TasksCenter.tsx`
- Modify: `web/src/app/layout/AppShell.tsx`
- Test: `tests/test_effective_area.py`
- Test: `tests/test_effective_area_windows.py`
- Test: `tests/test_effective_area_imports.py`

**Interfaces:**
- Produces: `EffectiveAreaService.get(tract_pk)`, `save(tract_pk, geometry, expected_updated_at)`, `inspect_import(tract_pk, source)`。
- Produces: `EffectiveWindowFilter.classify(window) -> Literal['inside','outside','boundary']` 与 `keep_detection(center_px) -> bool`；缓存键包含 `tract_pk + tracts.updated_at + tiff_id + geotransform`。
- Produces: `GET/PUT /tracts/{tract_pk}/effective-area` 与 `POST /tracts/{tract_pk}/effective-area/imports/inspect`。
- Produces: `GeometryEditorAdapter` 只暴露 `setTool/getDraft/replaceDraft/undo/redo/destroy/onChange`，第三方类型不泄漏到业务层。

- [ ] **Step 1: 写入有效区域失败测试**

```python
def test_effective_area_defaults_to_boundary(service, tract):
    result = service.get(tract.tract_pk)
    assert result.geometry == tract.boundary_geom
    assert result.is_default is True

def test_save_rejects_stale_or_outside_geometry(service, tract):
    with pytest.raises(EffectiveAreaConflict):
        service.save(tract.tract_pk, tract.boundary_geom, "stale")
    with pytest.raises(EffectiveAreaValidationError):
        service.save(tract.tract_pk, polygon_outside(tract), tract.updated_at)
```

再覆盖 Polygon/MultiPolygon、洞、多岛、空几何、自相交、重复点、CRS、越界裁剪确认与精确 hm²。

- [ ] **Step 2: 运行测试确认服务和字段尚不存在**

Run: `rtk proxy env PYTHONPATH=<worktree>/src /home/ray/rays/repos/4estDS/.venv/bin/pytest tests/test_effective_area.py tests/test_effective_area_imports.py -q`

Expected: FAIL，原因是模块/API/`effective_area_hm2` 缺失。

- [ ] **Step 3: 实现服务、API 与 GIS 导入**

```python
@dataclass(frozen=True)
class EffectiveAreaResult:
    tract_pk: str
    boundary_geometry: dict
    geometry: dict
    tract_area_hm2: float
    effective_area_hm2: float
    effective_ratio: float
    updated_at: str
    warnings: tuple[str, ...]
    is_default: bool
```

Shapely 负责最终规范化与验证；pyogrio 读取 GeoJSON/JSON、Shapefile sibling/zip、GPKG、KML、FGB，并返回可选图层和明确缺件/CRS错误。PUT 使用 `updated_at` 乐观并发，409 与 422 错误分离。

- [ ] **Step 4: 先写 window 调度失败测试，再接入 infer**

```python
def test_windows_skip_outside_and_mask_only_boundary(filter):
    assert filter.classify(inside_window) == "inside"
    assert filter.classify(outside_window) == "outside"
    assert filter.classify(edge_window) == "boundary"
    assert filter.local_mask(outside_window) is None
    assert filter.keep_detection(center_inside) is True
```

Run: `rtk proxy env PYTHONPATH=<worktree>/src /home/ray/rays/repos/4estDS/.venv/bin/pytest tests/test_effective_area_windows.py -q`

Expected: RED 后实现，GREEN 时证明完全外部 window 不读像素、边界 window 只建局部 mask、中心点规则过滤结果。

- [ ] **Step 5: 实现懒加载 GIS 编辑器与台账/任务入口**

Terra Draw + MapLibre adapter 承担绘制和顶点编辑；Turf 只做预览级面积/布尔辅助；支持选择、绘面、增加、挖洞、分割、合并、删除、100 步撤销重做、离开保护、导航自动收起与恢复。台账显示 `面积/有效面积(hm²)`，编辑弹窗提供入口；`/tasks` 只显示面积和跳转。

Run: `rtk proxy mise exec -- pnpm run typecheck`（目录 `web`）

Run: `rtk proxy mise exec -- pnpm run build`（目录 `web`）

Expected: 普通首包不包含编辑器 chunk；编辑器单独产出 lazy chunk。

- [ ] **Step 6: 扩展统计、地图过滤与既有导出后回归**

Run: `rtk proxy env PYTHONPATH=<worktree>/src /home/ray/rays/repos/4estDS/.venv/bin/pytest tests/test_effective_area.py tests/test_effective_area_windows.py tests/test_effective_area_imports.py -q`

Expected: PASS；密度读取 `effective_area_hm2`，旧 active run 地图按当前中心点过滤，导出按需带 effective-area 图层和溯源字段。

- [ ] **Step 7: 提交阶段 B**

```bash
rtk git add src/forestds deploy/postgis configs/default.yaml web/package.json web/pnpm-lock.yaml web/src tests/test_effective_area.py tests/test_effective_area_windows.py tests/test_effective_area_imports.py
rtk git commit -m "feat(map): enforce tract effective areas end to end"
```

---

### Task 3: 阶段 C — 单 TIFF 人工复核内核与原子发布

**Files:**
- Modify: `src/forestds/db/models.py`
- Modify: `src/forestds/db/schema.py`
- Modify: `deploy/postgis/schema.sql`
- Create: `src/forestds/review/__init__.py`
- Create: `src/forestds/review/domain.py`
- Create: `src/forestds/review/drafts.py`
- Create: `src/forestds/review/session_service.py`
- Create: `src/forestds/review/merge_service.py`
- Create: `src/forestds/review/publish_service.py`
- Create: `src/forestds/review/models/base.py`
- Create: `src/forestds/review/models/mock.py`
- Create: `src/forestds/api/routers/reviews.py`
- Modify: `src/forestds/api/main.py`
- Modify: `src/forestds/api/schemas.py`
- Create: `web/src/entities/review/index.ts`
- Create: `web/src/entities/review/model.ts`
- Create: `web/src/features/review-workbench/store.ts`
- Create: `web/src/features/review-workbench/ReviewWorkbench.tsx`
- Create: `web/src/features/review-workbench/index.ts`
- Create: `web/src/pages/ReviewPage.tsx`
- Modify: `web/src/app/router.tsx`
- Modify: `web/src/app/layout/navItems.ts`
- Modify: `web/src/shared/api/types.ts`
- Modify: `web/src/shared/api/endpoints.ts`
- Test: `tests/test_review_sessions.py`
- Test: `tests/test_review_publish.py`

**Interfaces:**
- Produces: `ReviewSessionService.create/get/workspace/apply_operations/undo/redo/cancel`，所有写操作接受 `revision + operation_id`。
- Produces: 草稿 schema 包含工作集、category_catalog、可见性、活动类别、prompt、visual exemplars、undo/redo 与 attempts；服务端文件是恢复事实源。
- Produces: `ReviewPublishService.publish(session_id)` 原子创建 review run、克隆最终全量 observations、切换 TIFF active run、更新 session。
- Produces: `/api/v1/reviews` 会话、workspace、operations、undo、redo、publish、cancel API；`/review` 一级懒加载入口和人工框编辑主路径。

- [ ] **Step 1: 写入会话、幂等、恢复和事务失败测试**

```python
def test_based_on_active_loads_parent_without_visual_prompts(service, seeded_active_run):
    session = service.create(mode="based_on_active", phase_id=PHASE, tiff_id=TIFF)
    assert session.base_run_id == seeded_active_run
    assert len(service.workspace(session.id).items) == seeded_count
    assert service.workspace(session.id).visual_exemplars == []

def test_duplicate_operation_is_idempotent(service, session):
    first = service.apply_operations(session.id, revision=0, operation_id="op-1", operations=[ADD])
    second = service.apply_operations(session.id, revision=0, operation_id="op-1", operations=[ADD])
    assert second.revision == first.revision
```

覆盖 from_scratch、revision 409、撤销重做、断线 checkpoint、进程重启恢复、质量门禁、发布回滚。

- [ ] **Step 2: 运行测试确认会话内核缺失**

Run: `rtk proxy env PYTHONPATH=<worktree>/src /home/ray/rays/repos/4estDS/.venv/bin/pytest tests/test_review_sessions.py tests/test_review_publish.py -q`

Expected: FAIL，原因是 review 模块和 `review_sessions` 缺失。

- [ ] **Step 3: 实现一表索引加文件草稿内核**

```python
class ReviewSessionService:
    def create(self, phase_id: str, tiff_id: str, mode: ReviewMode, base_run_id: str | None = None) -> ReviewSession: ...
    def apply_operations(self, session_id: str, revision: int, operation_id: str, operations: Sequence[ReviewOperation]) -> WorkspacePatch: ...
    def undo(self, session_id: str, revision: int, operation_id: str) -> WorkspacePatch: ...
    def redo(self, session_id: str, revision: int, operation_id: str) -> WorkspacePatch: ...
```

增量日志在 1 秒防抖或 50 操作时原子 checkpoint，快照压缩后截断日志；operation_id 持久化去重，重启恢复不能重复拼接。

- [ ] **Step 4: 实现质量门禁与原子发布并验证回滚**

发布拒绝冲突、有效区域外框、无类别框；review run 的 parent/TIFF/phase 与基线一致，父 observations 不变。用故障注入在 observation 批量插入后抛错，确认 run、active_run 与 session 均回滚。

- [ ] **Step 5: 实现 `/review` 首页和人工编辑工作台**

页面先列最近草稿与可复核 TIFF；工作台支持 based_on_active/from_scratch、类别目录、框新建/移动/缩放/删除/改类/备注、批量接受拒绝、筛选、快捷键、撤销重做、离开保护和导航收起。大数组使用按 ID 索引和增量 patch。

Run: `rtk proxy mise exec -- pnpm run typecheck`（目录 `web`）

Run: `rtk proxy mise exec -- pnpm run build`（目录 `web`）

- [ ] **Step 6: 运行阶段 C 回归并提交**

Run: `rtk proxy env PYTHONPATH=<worktree>/src /home/ray/rays/repos/4estDS/.venv/bin/pytest tests/test_review_sessions.py tests/test_review_publish.py -q`

```bash
rtk git add src/forestds deploy/postgis web/src tests/test_review_sessions.py tests/test_review_publish.py
rtk git commit -m "feat(review): add recoverable single-TIFF review sessions"
```

---

### Task 4: 阶段 D — YOLOE 文本/视觉 Prompt 与交互式 attempt

**Files:**
- Create: `src/forestds/review/models/yoloe.py`
- Create: `src/forestds/review/inference_service.py`
- Modify: `src/forestds/review/merge_service.py`
- Modify: `src/forestds/review/session_service.py`
- Modify: `src/forestds/api/routers/reviews.py`
- Modify: `src/forestds/api/schemas.py`
- Modify: `src/forestds/worker/actors.py`
- Modify: `src/forestds/worker/broker.py`
- Modify: `configs/default.yaml`
- Modify: `web/src/entities/review/model.ts`
- Modify: `web/src/features/review-workbench/store.ts`
- Modify: `web/src/features/review-workbench/ReviewWorkbench.tsx`
- Create: `web/src/features/review-workbench/PromptPanel.tsx`
- Create: `web/src/features/review-workbench/AttemptPanel.tsx`
- Modify: `web/src/shared/api/types.ts`
- Modify: `web/src/shared/api/endpoints.ts`
- Test: `tests/test_review_attempts.py`
- Test: `tests/test_review_yoloe_adapter.py`
- Test: `tests/test_review_viewport.py`

**Interfaces:**
- Produces: `ReviewModelAdapter.capabilities/load/prepare_text_prompts/prepare_visual_prompts/predict_batch/normalize`。
- Produces: YOLOE adapter 显式加载配置中的 26X/26L 和 MobileCLIP2，缓存 prompt embedding；视觉输入仅 `reference_image + bboxes + classes`。
- Produces: attempts create/get/cancel/apply/expand API；范围为 `viewport|full`，合并为 `append|replace_ai_in_scope`。
- Produces: `review_gpu` 队列，视口短任务优先；OOM 降 batch 一次，取消在分块边界生效。

- [ ] **Step 1: 写入 adapter、视口与合并失败测试**

```python
def test_visual_prompt_reuses_embedding_without_projecting_boxes(adapter, windows):
    context = adapter.prepare_visual_prompts(reference, [bbox], [0])
    adapter.predict_batch(windows, context)
    assert context.reference_boxes == [bbox]
    assert all(call.prompt_context is context for call in adapter.calls)

def test_replace_only_removes_unconfirmed_ai_in_scope(merge_service):
    result = merge_service.apply(REPLACE_AI_IN_SCOPE, existing, candidates, scope)
    assert parent_item in result.items
    assert human_confirmed_item in result.items
    assert old_unconfirmed_ai_in_scope not in result.items
```

覆盖文本 display_name/model_prompt 映射、embedding 单次编码、多 exemplar 同类聚合、viewport WGS84→TIFF pixel window、整图规范化、NMS/WBF/去重/冲突、expand 参数复用。

- [ ] **Step 2: 运行测试确认 attempt 和 adapter 缺失**

Run: `rtk proxy env PYTHONPATH=<worktree>/src /home/ray/rays/repos/4estDS/.venv/bin/pytest tests/test_review_attempts.py tests/test_review_yoloe_adapter.py tests/test_review_viewport.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现 adapter、范围调度和候选规范化**

```python
class ReviewModelAdapter(Protocol):
    def capabilities(self) -> ReviewCapabilities: ...
    def prepare_text_prompts(self, prompts: Sequence[TextPrompt]) -> PromptContext: ...
    def prepare_visual_prompts(self, reference_image: np.ndarray, bboxes: np.ndarray, classes: np.ndarray) -> PromptContext: ...
    def predict_batch(self, windows: Sequence[RasterWindow], prompt_context: PromptContext) -> Sequence[ReviewPrediction]: ...
```

当前视口与 TIFF footprint 求交后精确换算 pixel window；与有效区域共用 window provider。模型路径只来自配置，找不到权重时返回可操作错误，mock_review 始终可用于无 GPU 测试。

- [ ] **Step 4: 实现 Dramatiq 队列、取消、OOM 与 API**

attempt 状态和必要明细写草稿，不写 runs。视口任务使用高优先级 actor，整图任务低优先；OOM 仅降低 batch 重试当前批次一次，保留已完成分块和明确失败摘要。

- [ ] **Step 5: 实现 Prompt/Attempt 前端并回归**

文本与视觉工作流并列；执行前预览类别/范围/阈值；候选到达后必须明确选择追加或替换；显示基线、上轮累计、本轮变化、预计结果、日志、进度、取消和“扩散到全图”。

Run: `rtk proxy mise exec -- pnpm run typecheck`（目录 `web`）

Run: `rtk proxy mise exec -- pnpm run build`（目录 `web`）

- [ ] **Step 6: 运行阶段 D 回归并提交**

Run: `rtk proxy env PYTHONPATH=<worktree>/src /home/ray/rays/repos/4estDS/.venv/bin/pytest tests/test_review_attempts.py tests/test_review_yoloe_adapter.py tests/test_review_viewport.py -q`

```bash
rtk git add src/forestds/review src/forestds/api src/forestds/worker configs/default.yaml web/src tests/test_review_attempts.py tests/test_review_yoloe_adapter.py tests/test_review_viewport.py
rtk git commit -m "feat(review): add YOLOE prompt attempts and GPU scheduling"
```

---

### Task 5: 阶段 E — 实例 Mask 预览、编辑与发布

**Files:**
- Create: `src/forestds/review/masks.py`
- Modify: `src/forestds/review/domain.py`
- Modify: `src/forestds/review/models/base.py`
- Modify: `src/forestds/review/models/yoloe.py`
- Modify: `src/forestds/review/session_service.py`
- Modify: `src/forestds/review/publish_service.py`
- Modify: `src/forestds/api/routers/reviews.py`
- Modify: `web/src/entities/review/model.ts`
- Create: `web/src/features/review-workbench/MaskEditor.tsx`
- Modify: `web/src/features/review-workbench/ReviewWorkbench.tsx`
- Modify: `web/src/features/review-workbench/store.ts`
- Test: `tests/test_review_masks.py`

**Interfaces:**
- Produces: `mask_to_tiff_geometry(mask, source_window, transform)` 与 `normalize_crown_geometry(geometry, tolerance)`。
- Produces: mask 可见性、选中实例画笔增减、撤销重做；保存同步 `crown_geom/geom_crown` 和 mask 外接框。
- Does not produce: YOLOE 正负点、SAM adapter、复杂 Mask 精标或独立 mask 关系表。

- [ ] **Step 1: 写入坐标、轮廓和发布失败测试**

```python
def test_window_mask_maps_to_tiff_and_geo(mask, window, transform):
    result = mask_to_tiff_geometry(mask, window, transform)
    assert result.pixel_bounds == expected_global_pixel_bounds
    assert result.geometry.is_valid

def test_mask_edit_updates_crown_and_box(session_service, item):
    updated = session_service.apply_mask_operation(item, add_brush)
    assert updated.crown_geom is not None
    assert updated.box_px == bounds(updated.crown_geom)
```

- [ ] **Step 2: 运行测试确认 mask 编辑模块缺失**

Run: `rtk proxy env PYTHONPATH=<worktree>/src /home/ray/rays/repos/4estDS/.venv/bin/pytest tests/test_review_masks.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现 mask 规范化、地理转换和发布**

YOLOE 归一化输出保留实例 mask、来源 window 和坐标元数据；轮廓简化后必须仍为合法 Polygon/MultiPolygon，空轮廓拒绝；发布写 `crown_geom` 与 `geom_crown`，检测框同步外接矩形。

- [ ] **Step 4: 实现前端 Mask 图层和画笔编辑器**

提供 mask 显示开关、透明度、当前实例智能分割、画笔增加/擦除、局部撤销重做与确认；输入焦点时禁用快捷键。状态维度使用线型/图标，不与树种颜色混用。

Run: `rtk proxy mise exec -- pnpm run typecheck`（目录 `web`）

Run: `rtk proxy mise exec -- pnpm run build`（目录 `web`）

- [ ] **Step 5: 运行阶段 E 回归并提交**

Run: `rtk proxy env PYTHONPATH=<worktree>/src /home/ray/rays/repos/4estDS/.venv/bin/pytest tests/test_review_masks.py tests/test_review_publish.py -q`

```bash
rtk git add src/forestds/review src/forestds/api web/src tests/test_review_masks.py
rtk git commit -m "feat(review): edit and publish instance masks"
```

---

### Task 6: 阶段 F — 性能基线、端到端回归、配置与文档

**Files:**
- Modify: `configs/default.yaml`
- Modify: `docs/有效区域与智能复核实施方案.md`
- Create: `docs/有效区域与智能复核使用说明.md`
- Create: `tests/test_effective_area_review_http.py`
- Create: `tests/test_review_performance.py`
- Modify: `web/package.json`
- Modify: `web/pnpm-lock.yaml`
- Create: `web/playwright.config.ts`
- Create: `web/e2e/effective-area-review.spec.ts`
- Modify: touched implementation files only when verification exposes a defect

**Interfaces:**
- Produces: capabilities/config API 向前端返回用户可见配置，不复制默认值。
- Produces: 可重复的窗口吞吐、候选合并、万级 bbox 首屏与增量 patch 基线；实测结论决定是否需要 MVT。
- Produces: Playwright 覆盖有效区域保存、单图初始化、多轮追加/替换、扩散全图和发布。

- [ ] **Step 1: 写并运行 HTTP/E2E 失败测试**

```python
def test_effective_area_to_review_publish_http(client, seeded_tiff):
    area = client.put(f"/api/v1/tracts/{TRACT}/effective-area", json=VALID_AREA)
    session = client.post("/api/v1/reviews", json=FROM_ACTIVE).json()
    published = client.post(f"/api/v1/reviews/{session['session_id']}/publish", json={})
    assert published.status_code == 200
    assert active_run(seeded_tiff) == published.json()["run_id"]
```

Run: `rtk proxy env PYTHONPATH=<worktree>/src /home/ray/rays/repos/4estDS/.venv/bin/pytest tests/test_effective_area_review_http.py -q`

Expected: 若集成缺口存在则 FAIL；只修复真实缺口。

- [ ] **Step 2: 固化性能基线与 MVT 决策**

真实 `data/for_test` TIFF 上记录窗口数、跳过率、吞吐和峰值内存；mock_review 上记录 1 万/5 万候选 merge 与 bbox page；前端记录普通首包、review lazy chunk 和万级增量操作。只有 GeoJSON/bbox 实测不达标才实现 MVT，否则在文档中明确“不需要”。

- [ ] **Step 3: 完成配置约束与用户文档**

为每个 effective_area/review 配置记录单位、合法边界、性能影响和是否需要重启；说明恢复、冲突、发布、模型缺失/OOM/取消、Shapefile 缺件和从地图/台账/任务进入的路径。

- [ ] **Step 4: 执行完整验证**

Run: `rtk proxy mise exec -- pnpm run typecheck`（目录 `web`）

Run: `rtk proxy mise exec -- pnpm run build`（目录 `web`）

Run: `rtk proxy env PYTHONPATH=<worktree>/src /home/ray/rays/repos/4estDS/.venv/bin/pytest tests -q`

Run: `rtk proxy mise exec -- pnpm exec playwright test`（目录 `web`，使用现有浏览器；不得下载浏览器）

Expected: 新增测试、类型检查、构建和 E2E 全部通过；基线既有 `tests/test_tools.py::test_prepare_inference_image_routing` 若仍失败，明确列为本任务前已存在且未被本功能扩大。

- [ ] **Step 5: 自审方案逐条覆盖并提交阶段 F**

检查：无 `TBD/TODO/compat` 分支；普通页面不加载 review/editor；无全分辨率掩膜；attempt 不在 runs；所有 active 读取从 TIFF；草稿与发布故障路径有测试。

```bash
rtk git add configs/default.yaml docs tests web/package.json web/pnpm-lock.yaml web/playwright.config.ts web/e2e
rtk git commit -m "test: validate effective-area and review workflows"
```
