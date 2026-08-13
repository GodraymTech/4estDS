# PLAN：批量推理重构 & 复核草稿删除优化

> 目标版本：v1.1.0（基于 e887cdc）
> 原则：单一真相、KISS/YAGNI、彻底删旧、无历史包袱。

---

## 一、现状诊断

### 1.1 批量推理（当前实现）

| 层 | 现状 | 问题 |
|---|---|---|
| `UploadForm.tsx` | 一套表单 → 一次 `POST /jobs/infer` | 只能一次提交一个输入；参数无法逐图差异化 |
| `jobsStore.ts` | 纯内存 zustand，注释写明「刷新即丢」 | 跨页/刷新丢失，无法支撑 ledger↔tasks 往返采集 |
| `TasksCenter.tsx`「作业队列」 | 展示的其实是**已提交作业**，不是队列 | 名不副实，没有「候命」概念 |
| `POST /jobs/infer` | 内部按 `inspect_input_path` 分叉：目录 → `batch_actor`，文件 → `infer_actor` | 「批量」= 目录扫描，**全目录共用同一套参数**，与需求矛盾 |
| `BatchInferenceRequest` | `input_path: str` + 一套全局参数 | 无法表达「每条 item 参数不同」 |
| `tasks/batch.py` | `resolve_images()` 目录扫描 + `build_batch_tract_id()` 前缀拼接 + 串行循环 | 目录扫描/前缀拼接是旧模型的产物，需删除 |
| 一键终止 | `cancel-all` 把所有 queued/running 的 run 一律写 `failed` | 批量子 run 停在 `running` 无人收尾；已完成的子项没有被正确保留统计 |

### 1.2 复核草稿删除

`session_service.delete()` 第 547 行：`status == "published"` 直接抛 `ReviewConflict` → HTTP 409。
前端 `ReviewPage.tsx` 对已发布行照样渲染删除按钮 → 点了必然报错，纯负体验。

---

## 二、目标模型（新架构）

**核心抽象：一切推理都是「批量作业」，单图 = 长度为 1 的批量。**

```
[推理参数表单] --加入队列--> [待命队列 pendingItems(前端持久化)]
                                    |
                            点击「开始推理」
                                    v
                POST /jobs/batch  { items: [ItemSpec, ItemSpec, ... ] }
                                    v
                    batch_actor(顶层 run_id, task_type="batch")
                                    v
            串行: item[i] -> 子 run_id -> run_infer_pipeline -> promote
```

- **前端待命队列**：真正的「候命」，持久化（localStorage），跨页面/刷新不丢。
- **后端只保留一条推理入口**：`POST /jobs/batch`，`infer_actor`/`enqueue_inference`/`submit_infer` 全部删除。
- **每条 item 自带完整参数**（input_path 或 image_key、phase_id、tract_id、tile_size、overlap_rate、dsm/dem/las、export_fmt、arch）。

---

## 三、后端改造清单

### 3.1 `contracts.py`
- **改**：`BatchInferenceRequest` 重构为
  ```python
  class BatchInferenceItem(BaseModel):   # 一条待命 = 一次单图推理的完整参数
      image_path: str
      arch / phase_id / tract_id / tile_size / overlap_rate / dsm / dem / las / export_fmt
      label: str | None        # 队列展示用（文件名）

  class BatchInferenceRequest(BaseModel):
      items: list[BatchInferenceItem] = Field(..., min_length=1)
      publish: bool = True
  ```
- **删**：`BatchInferenceRequest.input_path`（目录语义）、`tract_id` 前缀语义。
- `InferenceRequest` **保留**（CLI 单图 & pipeline 内核仍需要），不再用于队列投递。

### 3.2 `tasks/batch.py`
- **删**：`resolve_images()`（目录扫描）、`build_batch_tract_id()`（前缀拼接）、`_VALID_SUFFIXES`。
- **改**：`run_batch_pipeline(items, *, settings, publish, cancel_run_id)` —— 按 item 逐条执行；
  - detector 按 `arch` 惰性缓存于本次批量内（`dict[str, Detector]`），权重按需只加载一次；
  - `tract_id` 缺省回落到 `Path(image_path).stem`，**不再��前缀拼接**（每条自带）；
  - 同名 tract_id 去重后缀逻辑保留（`_2`、`_3`），但作用域为本批次。
- **新增取消善后**（关键）：
  - 每条 item 开跑前 `check_cancelled(cancel_run_id)`；
  - 捕获 `JobCancelled`：
    - 已完成项 → 保持 `succeeded`（不回滚，已发布的照旧激活）；
    - **正在跑的被夹断项 → 子 run `finish_run_log(failed, error="用户终止")`，计入 failed**；
    - 未开始项 → 标记 `canceled`（不建子 run，避免脏数据），计入 `canceled`；
    - `break` 后正常返回 `BatchSummary`，附带 `cancelled: bool`。
- `BatchItemSummary` 增加 `status ∈ {succeeded, failed, canceled}`、`index`。

### 3.3 `service.py`
- **改**：`run_batch_inference_job()` 适配新 `items` 契约；
- metrics 增加 `canceled` 计数与 `cancelled` 标记；
- 顶层 run 终态：被终止 → `failed`（error=「用户一键终止」），否则 `succeeded`。
- **删**：`run_inference_job` 是否保留？→ **保留**（CLI/单测/pipeline 复用），但不再被队列 actor 调用。

### 3.4 `worker/`
- **删**：`infer_actor`、`enqueue_inference`。
- **删**：`actors.py` 第 182-189 行**重复定义**的 `_get_review_adapter`（覆盖了带 TTL 的版本，属现存 bug，顺手清掉）。
- **改**：`batch_actor` 为唯一推理入口；`enqueue_batch_inference` 保留并成为唯一投递函数。

### 3.5 `api/routers/jobs.py` + `api/schemas.py`
- **删**：`POST /jobs/infer`、`InferSubmit`（旧单体 schema）。
- **新增**：`POST /jobs/batch`
  - body：`BatchSubmit { items: [BatchItemSubmit], }`；
  - 逐条校验：`image_key` 与 `input_path` 二选一；`input_path` 必须是**文件**（目录直接 400 提示「请在前端逐张加入队列」）；aux 路径校验复用 `_resolve_aux_path`；
  - 返回 `JobRef(job_id, status=queued)`。
- **改**：`/jobs/cancel-all` 的 run 过滤集合保持 `{"infer","batch"}`（历史 infer run 仍需可终止），但对 `batch` 顶层 run 不再粗暴写 failed —— 只 `request_cancel()`，由 worker 自己按 3.2 的善后规则落终态；仅对**孤儿 run**（无 worker 消费、超时无心跳）兜底写 failed。
  - 简化实现：`cancel-all` = flush 队列 + 对所有活跃 run `request_cancel()`；worker 在检查点收尾。对「已入队但 worker 从未启动」的 run（`started_at is None`）直接写 `canceled`。
- **改**：`/jobs/inspect-input` 保留（前端仍需读元数据/建议 tract_id/phase_id），但目录输入的返回值前端只用于提示「该目录含 N 张，请逐张加入队列」。

### 3.6 `cli.py`
- **改**：`cmd_batch` 与 `cmd_infer` 的批量分支适配新 `run_batch_pipeline(items=...)`（CLI 侧自己把目录展开成 items，目录扫描逻辑下沉到 `cli.py` 的一个小工具函数或 `utils/input_inspect`，避免 tasks 层保留旧语义）。

---

## 四、前端改造清单

### 4.1 `features/tasks/queueStore.ts`（重写 `jobsStore.ts`）
```ts
zustand + persist(localStorage, name: "4estds.tasks.queue.v1")
{
  draft: FormDraft,                 // 表单草稿(跨页保持)
  pending: PendingItem[],           // 待命队列
  submitted: SubmittedBatch[],      // 已提交批次 {jobId, items, submittedAt}
  addPending / removePending / movePending / clearPending
  setDraft / resetDraft
  addSubmitted / clearSubmitted
}
```
- **删**：旧 `jobsStore.ts`（内存版、`SubmittedJob`）。

### 4.2 `UploadForm.tsx`
- 表单状态改为**受控于 store 的 draft**（`setDraft`），实现「切页面回来参数还在」。
- `searchParams`（来自 ledger 的 `input_path/tract_id/phase_id`）**覆盖式写入 draft**，并在消费后 `setSearchParams({}, {replace:true})`，避免回到页面时重复填充。
- 按钮行：`[加入队列] [开始推理] [一键终止]`（加入队列在开始推理左边）。
  - **加入队列**：校验（路径存在性由 inspect 结果判定；目录 → 提示不支持，要求选具体文件）→ push 到 `pending` → 清空「输入路径/地块 ID」，保留其余参数（连续加图时最省事）→ `message.success("已加入队列(N)")`。
  - **开始推理**：
    - 若表单当前有有效输入 → 先隐式入队；
    - `pending` 为空 → 警告；
    - 否则 `POST /jobs/batch { items: pending }` → 成功后 `clearPending()` + `addSubmitted()` + 选中该 job 展示日志。
    - 这样「单图直接推理」= 直接点开始推理（长度 1 的批量），交互零成本。
  - **上传的本地文件**：先 `uploadImage` 拿 key 再入队（item 携带 `image_key`）。

### 4.3 `TasksCenter.tsx`「作业队列」面板（深入设计）

**结论：待命队列就放在「作业队列」面板里，不新开面板。**

理由：`tasks-console` 是 `form|history` + `main(queue+runtime)` 的两栏 Grid，`main` 纵向已被 `作业队列(220px)` 与 `运行追踪(日志 48vh)` 占满。再插一个面板会把日志区挤死；而且「待命」与「已提交」本就是同一件事的两个阶段，分开两处反而割裂心智模型。

#### 面板内部结构

```
┌─ 作业队列 ───────────────────────────────────────┐
│ [待命 3] [已提交 5]        清空待命  释放 Worker  │  ← Segmented + 右侧操作
├────────────────────────────────────────────┤
│ # │ 输入        │ 地块 ID  │ 时相     │ 参数 │ 操作   │
│ 1 │ A-01.tif    │ A-01     │ 20240513 │ 1024/20% │ ↑↓ ✎ ✕ │
│ 2 │ A-02.tif    │ A-02     │ 20240513 │ 自适应   │ ↑↓ ✎ ✕ │
└────────────────────────────────────────────┘
```

- 头部用 **antd `Segmented`** 切换两个视图，带数量徽标；共用同一个滚动窗口，**面板总高度不变**（`--queue` 从 220px 微调至 260px）。
- **默认选中规则**：`pending.length > 0` → 默认「待命」；提交成功后自动切到「已提交」。这样 ledger 往返采集时看到的总是待命列表。
- 右上角操作按视图切换：待命视图 → `清空待命`；已提交视图 → `释放 Worker`（保持现有）。

#### 待命视图列定义

| 列 | 内容 |
|---|---|
| `#` | 序号（执行顺序，所见即所得） |
| 输入 | 文件名（`Tooltip` 悬停显示完整路径；上传文件标 `Tag: 上传`） |
| 地块 ID | 缺省时灰字显示回落值（文件名 stem） |
| 时相 | `phase_id`，缺省显示「读元数据」 |
| 参数 | 紧凑摘要 `1024 / 20% / shp`，带 DSM/DEM/LAS 时追加小图标 |
| 操作 | 上移 / 下移 / **编辑** / **删除** |

#### ✅ 删除按钮（采纳，并扩展为一组行内操作）

1. **删除 `✕`**：单条移除。**不弹 Popconfirm**（候命条目是廉价草稿，二次确认反而碍事），改为 `message` 带 **5 秒「撤销」**按钮（store 保留 `lastRemoved` 快照）。
2. **编辑 `✎`**：把该条参数**回填到左侧表单**并从待命移除，改完再「加入队列」。解决「参数填错了只能删了重填」的痛点。
3. **上移/下移 `↑↓`**：调执行优先级（首/尾行自动禁用）。
4. **清空待命**：面板头部，**这个用 `Popconfirm`**（批量破坏性操作值得拦一下）。

> 交互原则：单条可逆 → 不拦截 + 可撤销；批量不可逆 → 确认拦截。

#### 已提交视图

- 行 = 一个批次（jobId）：条目数、总体状态（轮询 `GET /jobs/{id}`）、`成功/失败/已取消` 计数、提交时间。
- **可展开行**（`Table.expandable`）：展开后逐条显示 `metrics.items`（影像名 / 状态 / 单木数 / 子 run_id）。
- 点击行 → 右侧「运行追踪」切到该 job 的日志与指标。
- 「批量明细」`BatchItems` 组件复用到展开行，并补 `canceled` 状态色（灰色）。

#### CSS 变更
- `.task-scroll-window--queue { max-height: 260px; }`
- 新增 `.task-queue__toolbar`、`.task-queue__ops`（行内图标按钮紧凑排列，`opacity: .55` → `hover: 1`）。

### 4.4 一键终止（`UploadForm.cancelActiveJob`）
- `Modal.confirm` 二次确认，文案明确善后语义：
  > 已完成的影像保留为「成功」，正在推理的记为「失败」，尚未开始的记为「已取消」。待命队列中未提交的条目将保留（不会丢失）。
- 行为：`POST /jobs/cancel-all` → 刷新 job 状态；**不清空本地 pending**（用户未提交的劳动成果不该被销毁）。

### 4.5 `shared/api`
- `endpoints.submitInfer` → **删**，替换为 `endpoints.submitBatch(body: BatchSubmit)` → `POST /jobs/batch`。
- `types.ts`：删 `InferSubmit`，新增 `BatchItemSubmit` / `BatchSubmit`。

### 4.6 `LedgerTable.tsx`
- `taskInferPath(row)` 保持不变（`/tasks?input_path=&tract_id=&phase_id=`）——已满足往返流程；
- 补充：`未检测` 按钮 tooltip 改为「填入推理参数 → 加入队列」，明确新流程。

---

## 五、复核草稿删除（review）

**方案（推荐）：允许删除已发布会话的「会话记录」，但不动已发布成果。**

- `session_service.delete()`：移除 `status == "published"` 的 409 拦截；
  - 删除 `review_sessions` 行 + 草稿文件；
  - **不删** `published_run_id` 指向的 run 与 `tree_observations`（成果已是独立正式产物，由 ledger 管理）；
  - 保留 `ReviewNotFound`（不存在仍 404）。
- `ReviewPage.tsx`：删除确认文案按状态区分
  - `active`：「确定要永久删除此复核草稿吗？此操作无法撤销。」
  - `published`：「该会话已发布。删除仅移除复核记录，**不会影响已发布的检测成果**（run: xxx）。」
- 备选方案（若你更保守）：保留后端限制，前端对已发布行禁用删除按钮 + Tooltip 说明原因。

> ❓ **需要你确认选哪个**（默认按推荐方案实施）。

---

## 六、删除清单（彻底清理，无历史包袱）

| 文件 | 删除内容 |
|---|---|
| `contracts.py` | `BatchInferenceRequest.input_path` 目录语义字段 |
| `tasks/batch.py` | `resolve_images`、`build_batch_tract_id`、`_VALID_SUFFIXES` |
| `worker/actors.py` | `infer_actor`、重复定义的 `_get_review_adapter` |
| `worker/__init__.py` | `enqueue_inference` |
| `api/routers/jobs.py` | `submit_infer` 及其目录/文件分叉逻辑 |
| `api/schemas.py` | `InferSubmit` |
| `web/.../jobsStore.ts` | 整文件（由 `queueStore.ts` 取代） |
| `web/.../types.ts` | `InferSubmit` |
| `web/.../endpoints.ts` | `submitInfer` |

---

## 七、实施顺序与 Git 提交点

1. **commit 1** `refactor(batch): 重构批量推理契约与任务编排（后端）`
   - contracts / tasks.batch / service / worker / cli
2. **commit 2** `refactor(api): 统一推理入口为 POST /jobs/batch 并完善终止善后`
   - routers/jobs.py / schemas.py
3. **commit 3** `feat(web): 待命队列与加入队列交互`
   - queueStore / UploadForm / TasksCenter / api 层 / LedgerTable 文案
4. **commit 4** `fix(review): 已发布会话可删除且不影响已发布成果`
5. **commit 5** `docs: 更新 README 与时间线`（如涉及）

> 沙盒重置风险：每完成一个 commit 立即落盘，最后导出 bundle。

---

## 八、风险与取舍

1. **API 破坏性变更**：`POST /jobs/infer` 直接删除。按你「不要历史包袱」的要求不做兼容层；需确认无第三方脚本依赖该端点。
2. **`localStorage` 持久化**：待命队列存本地。若用户换浏览器/清缓存则丢失——符合「候命清单是客户端草稿」的定位，不引入服务端队列表（YAGNI）。
3. **`cancel-all` 语义变化**：从「立即写 failed」改为「请求取消 + worker 收尾」，前端状态会延迟 1~2 个检查点才落终态；会在 UI 上以「终止中」提示。

---

## 九、已确认的决策

1. ✅ 复核删除：**允许删除已发布会话**，不影响已发布成果。
2. ✅ 一键终止：**保留**前端未提交的待命条目。
3. ✅ 旧端点 `POST /jobs/infer`：**直接删除**，不留别名。
4. ✅ 待命队列展示位置：**内置于「作业队列」面板**，`Segmented` 切换「待命 / 已提交」。
5. ✅ 待命行操作：**删除（可撤销）+ 编辑回填 + 上移/下移 + 清空全部**。

---

## 十、实施结果（已完成）

### 后端（commit 1）
- `contracts.BatchInferenceRequest` 收敛为 `{ items: [InferenceRequest, ...] }`，旧平铺字段全部删除。
- `tasks/batch.py` 全文重写：`BatchItemSpec` 逐条参数、`run_batch_pipeline` 三态善后（成功 / 失败 / 已取消），所有失败分支补写子 run 终态，修掉原先「子 run 僵在 running」的既有缺陷。
- `cancellation.py` 新增父子 run 取消联动，终止信号能穿透正在执行的单图管线。
- `POST /jobs/infer` 删除，唯一提交入口为 `POST /jobs/batch`；整批先校验再入队，杜绝半提交。
- `/jobs/cancel-all` 不再粗暴把运行中的 run 写成 failed，改为发信号交 worker 收尾；仅 `/jobs/stop-worker` 强制写终态。
- `worker/` 删除 `infer_actor`，检测器工厂注入 `batch_actor`，保住进程内模型常驻缓存。
- `cli.py`、`tests/` 同步；`build_batch_tract_id` 等历史包袱清除。

### 前端（commit 2）
- `jobsStore.ts` 改为 `zustand/persist`：待命队列 + 已提交台账 + 表单草稿一起持久化，跨页跳转与刷新都不丢。
- `UploadForm`：新增「加入队列」；目录在前端展开为逐张待命项；提交走 `/jobs/batch`；一键终止加后果确认弹窗。
- `TasksCenter`：作业队列面板双视图（待命 N / 已提交 M），待命行支持删除（可撤销）、编辑回填、上移下移，头部「清空待命」二次确认。
- 作业与批量明细全面支持 `canceled` 三态；`useJob` 在已取消状态停止轮询。

### 复核（commit 3）
- `session_service.delete` 去掉「已发布不可删」限制；已发布成果存于 runs / 观测表，不随会话行消失。
- `ReviewPage` 对已发布行使用差异化确认文案，说明删除只移除复核记录。
