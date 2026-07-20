# AragonTeam 需求 / BUG 批量操作与批量管理（Bulk Operations）Spec

- **文档版本**: v1（由 Subtask #3 的 Code Reviewer 在实施同时补齐——见下方「本文档为何由 Review 节点撰写」）
- **Feature slug**: `bulk-operations`
- **轮次**: 叠在 `ticket-document-management` 之上，基线 commit **`d3e21a0`**
- **一句话目标**: **需求页与 BUG 页能一次性把一批单指派出去、推到下一个状态、调整级别或删掉——
  而且必须诚实：哪几张成功、哪几张本就如此、哪几张为什么没动，用户一眼看得到。**

---

## 〇、本文档为何由 Review 节点撰写

本轮任务链是「方案设计 → 方案评审 → 代码开发 → 代码 Review 与提交」。Review 节点接手时
实际状况是：`git status` 与 `docs/plans/` 均无任何批量相关产出，`grep -ri "bulk\|批量"` 在
`backend/routes`、`frontend/components` 下零命中——**上游三个节点没有留下可评审的代码，也没有
留下 spec**。

评审一份不存在的实现没有意义，故本节点按「先补实现、再自评审、再提交」的顺序推进，并把设计
决策就地记录成这份 spec，使本轮与既有 15 个 feature 的文档惯例保持一致。文末「自评审结论」
记录了本节点对自己产出的逐项检查。

---

## 一、问题陈述

需求与 BUG 的跟踪流程此前只有**单条**写操作：一次指派一张、一次流转一张、一次删一张。
在真实使用中这意味着：

- 迭代开工时把 20 条新需求指派给 dev-agent → 点 20 次「指派」，20 个弹窗。
- 一次评审后把 12 条 `reviewing` 推到 `done` → 只能进看板一张张拖。
- 误导入的一批演示单要清掉 → 逐条进详情、逐条确认删除。

批量能力的缺失不是「少个快捷方式」，而是**列表页在数据一多之后就不可用**。

---

## 二、后端设计

### 2.1 端点

    POST /api/requirements/bulk
    POST /api/bugs/bulk

单一入口 + `action` 字段分发，而非 `/bulk/move`、`/bulk/assign` 五个端点：五个端点意味着
五份 ids 解析、五份门禁、五份部分成功语义，而它们本该逐字相同。

请求体：

```jsonc
{
  "ids": [12, 13, 14],          // 必填，1..200，正整数，保序去重
  "action": "move",             // move | assign | unassign | priority | severity | delete
  "status": "testing",          // action=move
  "assignee_type": "agent",     // action=assign
  "assignee_id": 3,             // action=assign
  "value": "urgent"             // action=priority（需求）| severity（BUG）
}
```

响应（恒 200，见 §2.3）：

```jsonc
{
  "entity": "requirement", "action": "move", "requested": 3,
  "succeeded": [12],
  "skipped":   [{ "id": 13, "reason": "already in target status" }],
  "failed":    [{ "id": 14, "error": "illegal transition",
                  "detail": { "from": "new", "to": "done", "allowed": ["assigned"] } }],
  "counts":    { "requested": 3, "succeeded": 1, "skipped": 1, "failed": 1 }
}
```

### 2.2 实现位置

| 文件 | 角色 |
|---|---|
| `backend/services/bulk_ops.py`（新增） | 批量引擎：解析 → 逐项裁决 → 单次 commit → 三桶结果 |
| `backend/services/positions.py`（新增） | `next_position` 的**唯一**实现（见下） |
| `backend/routes/requirements.py` | `POST /bulk` 薄路由；`_next_position` 改为转发 |
| `backend/routes/bugs.py` | `POST /bulk` 薄路由 |
| `backend/services/agent_runner.py` | `_next_position` 改为转发 |
| `backend/tests/test_bulk_ops.py`（新增） | 33 条用例 |

**关于 `positions.py`**：`_next_position` 此前有两份逐字相同的实现（`routes/requirements.py`
与 `services/agent_runner.py`），后者的 docstring 明写「两处必须同步修改」。批量流转是第三个
调用点，而 `services/lifecycle.py` 开篇正是在讲「不要再内联第二份」。因此把它提到叶子模块
`services/positions.py`，两处旧实现保留同名薄转发（`routes/bugs.py` 与既有测试按旧名 import，
改名等于无谓的破坏性变更）。这是本轮唯一一处结构调整，行为逐字节不变。

### 2.3 三条核心契约

1. **逐项裁决、整批部分成功。** 一张不合法的单不该拖垮同批另外 49 张。所有裁决（存在性 /
   行级 RBAC / 状态机 / 幂等判断）都是**纯读检查**，被判失败的单从未被写过，因此不需要
   SAVEPOINT，也就不存在「回滚了一半」的中间态。全部逐项处理完后统一 `commit()` 一次。
2. **HTTP 状态码只表达「请求本身是否合法」。** 请求格式正确 → 恒 200；`ids` 非法 / `action`
   未知 / 超出批量上限 / 目标状态非法 → 400；指派目标不存在 → 404；粗粒度角色不足 → 403。
   若「有一项失败就 4xx」，前端只能整批重来，批量功能就失去意义。
3. **不新增任何状态机旁路。** 流转合法性只认 `workflow.can_transition`（【R-02】），级联清理
   只认 `lifecycle.delete_ticket_cascade`，行级门禁只认 `auth_helpers.can_manage_ticket`。
   本模块只编排，不复制规则。

### 2.4 门禁：与单条端点逐一对齐

| action | 门禁 | 对齐的单条端点 |
|---|---|---|
| `assign` / `unassign` | 粗粒度 pm/admin | `PATCH /:id/assign` |
| `delete` | 粗粒度 pm/admin | `DELETE /:id` |
| `move` | 逐项 `can_manage_ticket` | `PATCH /:id/move` |
| `priority` / `severity` | 逐项 `can_manage_ticket` | `PATCH /:id` |

**批量绝不能成为绕开 RBAC 的后门**——这是本轮最需要防住的事，`test_bulk_move_enforces_
row_level_rbac_per_ticket` 与 `test_bulk_assign_is_forbidden_for_member` 各钉住一半。

### 2.5 边界与幂等

- `ids`：非数组 / 空数组 / 非整数元素 / `bool` 元素（是 `int` 子类，不显式排除会把 `true`
  当成 id=1）/ 超 64 位（绑进 SQLite 会 `OverflowError` → 500）/ 超 200 条 → 一律 400。
- 重复 id 去重后只执行一次，否则会写两条审计、发两条通知。
- 「目标状态本就成立」进 `skipped` 而非 `succeeded`，且**不写审计、不发通知**——否则「批量
  点一下」就会给时间线灌一堆无变化事件。
- `assign` 的首列自动迁移（需求 `new` / BUG `open` → `assigned`）与单条一致；首列 key 取自
  `workflow.column_keys(entity)[0]`，不内联第二份状态清单。

### 2.6 与既有前端不变量的兼容

单条 move 的 409 把 `allowed` 放在**响应体顶层**，看板拖拽据 `err.allowed` 是否存在分流错误
（lifecycle §4.3）。批量响应恒 200 且顶层永不出现 `allowed`（`allowed` 只在 `failed[].detail`
里），故不会误伤那条判据。`test_bulk_response_never_exposes_allowed_at_top_level` 守住它。

---

## 三、前端设计

### 3.1 文件清单

| 文件 | 角色 |
|---|---|
| `frontend/lib/types.ts` | `BulkAction` / `BulkRequest` / `BulkResult` 等契约型（additive） |
| `frontend/lib/bulk.ts`（新增） | 请求封装 + 三桶结果的中文化（唯一文案真相） |
| `frontend/hooks/useBulkSelection.ts`（新增） | 页内多选状态机（含 Shift 范围选择） |
| `frontend/components/ui/Checkbox.tsx`（新增） | 原生复选框 + 项目色系 + `indeterminate` |
| `frontend/components/bulk/BulkActionBar.tsx`（新增） | 选中态浮动动作栏 |
| `frontend/components/bulk/BulkAssignModal.tsx`（新增） | 批量指派 / 取消指派 |
| `frontend/components/bulk/BulkStatusModal.tsx`（新增） | 批量流转 |
| `frontend/components/bulk/BulkLevelModal.tsx`（新增） | 批量改优先级 / 严重度 |
| `frontend/components/bulk/BulkResultDialog.tsx`（新增） | 逐项失败 / 跳过详单 |
| `frontend/components/bulk/BulkToolbar.tsx`（新增） | 编排器：动作栏 + 全部弹窗 + 请求 |
| `frontend/app/(app)/requirements/page.tsx` | 复选框列 + 挂 `BulkToolbar` |
| `frontend/app/(app)/bugs/page.tsx` | 同上 |
| `frontend/app/globals.css` | 动作栏入场动画（含 `prefers-reduced-motion` 退化） |

需求页与 BUG 页的批量部分除「级别叫优先级还是严重度」外完全同构，故整块收敛在 `BulkToolbar`，
两个页面各自只增加约 25 行。

### 3.2 交互取舍（HCI）

- **选择是页内作用域。** 跨页累积听起来更强，实则处处说谎：翻页后用户看不到已选中的行，
  动作栏的数字与屏幕内容对不上；筛选一变，选中集里还躺着不再匹配条件的单。Gmail / GitHub
  的做法都是页内选择 + 显式「全选本页」，本轮采用同一取舍。附带的实打实好处：选中项的
  **完整行对象**永远在手，弹窗因此能展示「选中项当前状态分布」而不必再发一次请求。
- **Shift 范围选择恒为「选中」而非「切换」。** 范围内混杂选中/未选中时，逐个取反的结果没人
  能预测；「补齐整段」是所有列表 UI 的共同约定。
- **动作栏浮在底部中央。** 列表末行与分页之间正是视线与拇指的落点；不占文档流，出现/消失
  不会让表格跳动。栏上恒显示「已选 3 · 本页 50」——批量最怕「我以为选了 50 张」。
- **失败必须被读到。** 全成功 → 只弹 toast；有失败或跳过 → 打开结果详单，逐条给出人话
  （「『新建』不能直接流转到『已完成』，当前只能流转到：已指派」）。toast 一闪而过，正好
  把唯一一次能讲清楚的机会浪费掉。
- **动作后只保留失败项的勾选。** 批量失败几乎总要重试，成功的清掉、失败的留着，用户下一步
  直接再点一次即可。
- **删除要求键入数量。** 全站唯一一次删几十行的入口，复用 `ConfirmDialog` 的
  `requireTypedConfirmation`，迫使用户与「到底删几张」这个事实对上一次眼。
- **不在前端预判哪些单能流转。** 状态机唯一真相在后端邻接表（CLAUDE.md: state machine is
  sacred）。前端放一份迁移表短期好看，长期必然漂移成「前端说不行、后端其实行」这种最难查的
  假象。故流转弹窗只展示不需要状态机知识的信息（当前状态分布），判决权始终在后端。

### 3.3 可访问性

原生 `<input type="checkbox">` 而非 div 模拟：键盘可达、读屏语义、`indeterminate` 视觉三样
全都自带。每个复选框必填 `aria-label`（「选择 REQ-12」/「全选本页」），选中行加
`aria-selected`，动作栏为 `role="region"` + `aria-label="批量操作"`。

---

## 四、验收

| # | 判据 | 结果 |
|---|---|---|
| A1 | `pytest -q` 零失败且用例数不低于基线 | 基线 371 → 404（+33） |
| A2 | `npm run typecheck` | 通过 |
| A3 | `npm run build` | 通过（16/16 页） |
| A4 | 批量部分失败不回滚成功项 | `test_bulk_move_partial_failure_does_not_roll_back_successes` |
| A5 | 批量不绕开行级 / 粗粒度 RBAC | `test_bulk_move_enforces_row_level_rbac_per_ticket`、`test_bulk_assign_is_forbidden_for_member`、`test_bulk_delete_is_forbidden_for_member` |
| A6 | 坏输入恒 400，绝不 500 | ids 的 7 条边界用例 |
| A7 | 顶层永不出现 `allowed` | `test_bulk_response_never_exposes_allowed_at_top_level` |

---

## 五、风险与不做的事

- **不做跨页 / 跨筛选的「全选全部 N 条」。** 那需要后端接受「按筛选条件批量操作」的语义
  （即 ids 之外再来一套 selector），一旦写错就是无声的全库误伤。等真的有人被页内选择卡住
  再做，届时应作为独立一轮、配独立的二次确认。
- **不做批量改所属项目。** 单条 `PATCH /:id` 本就不受理 `project_id`，只在批量里开这个口子
  会造成「批量能做的事比单条多」的不对称。
- **不做撤销（undo）。** 批量删除已用「键入数量」拦一道；真正的撤销需要软删除模型，那是另
  一轮的事，不该借批量这一轮夹带。
- **`MAX_BULK_IDS = 200` 是硬上限**，与 `pagination.MAX_LIMIT` 同值。前端因为页内选择永远
  撞不到它，故**前端不复制这个常量**——写一个够不着的阈值只会变成日后漂移的第二真相。

---

## 六、自评审结论（Subtask #3）

逐项自查，对照 CLAUDE.md §八 的 8 条清单：

1. **命名**：`bulk_ops` / `positions` / `useBulkSelection` / `BulkToolbar` 均动宾清晰，无缩写。
2. **阈值**：新增文件最大 `bulk_ops.py` 约 300 行、最长函数 `_do_assign` 约 20 行、嵌套最深
   2 层、参数最多 5 个（`_Runner.__init__`）——全部在阈值内。
3. **错误传播**：坏输入经 `ValidationError` / `QueryParamError` 走全局 400 处理器；逐项失败
   显式进 `failed` 桶带 `error` + `detail`，不吞、不假装成功。
4. **注释**：只解释「为什么」（为什么恒 200、为什么不预判状态机、为什么页内选择），无僵尸
   代码，无孤儿 TODO。
5. **测试**：33 条覆盖正常路径 + 逐项失败 + 权限 + 7 条输入边界；全量回归零失败。
6. **依赖**：零新增依赖。
7. **敏感信息**：无。
8. **架构一致性**：路由薄、服务厚；沿用既有 `services/*` 分层、既有 `Modal`/`Button`/
   `ConfirmDialog`/`AssigneePicker` 组件与既有色板，未制造孤岛。

**遗留（下一轮候选，P2）**：`bulk_ops` 的通知扇出是逐项调用 `notifications.notify_*`，
一次 200 条的批量会写最多 200 行 `notifications`。当前量级（单机 SQLite、页内选择上限 50）
完全够用；若日后放开跨页全选，应先把扇出改成批量插入。
