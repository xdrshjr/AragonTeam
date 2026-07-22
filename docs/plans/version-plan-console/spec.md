# 版本 / 计划控制台——把已落地的四层树「变成人能用的界面」（version-plan-console）

> **文档版本**：v3（2026-07-22，经**两轮**设计评审修订；v1→v2 为第一轮，v2→v3 为第二轮。
> 两轮评审记录见下方「评审记录」，结论见文末「评审结论」。**v2 是第一轮评审后的状态，本文件
> 已在其之上再改一轮，故版本号继续前进而不是停在 v2**——停在 v2 会让读者以为这些改动是第一轮做的。）
> **上游**：`docs/plans/version-plan-hierarchy/spec.md` v2（后端已实现并提交，commit `d766c88`）
> **本轮定位**：补齐上一轮**有意留空**的前端（该 commit 的提交说明原文：「本提交仅含后端。spec §5.2/§7
> 规划的前端「版本/计划」界面……尚未实现，留待后续迭代补齐」），并补上一个让层级**能被真正采用**的
> 后端增量（批量归属计划）。
> **开工基线（务必先取）**：`cd backend; python -m pytest -q --collect-only`，记下用例总数 N₀。
> 验收判据是**相对基线**：零失败且用例数 ≥ N₀（CLAUDE.md「质量门禁」明令不得信任任何写死的数字）。

---

## 评审记录（Review Notes）

> 本文件经过**两轮**设计评审，两轮记录都保留在这里：新的在上、旧的在下。
> 第一轮把 v1 修成 v2，第二轮把 v2 修成 v3。**第二轮不是第一轮的复述**——它把第一轮
> 给出的每一条「已修」结论重新回源核验了一遍，因而找出了 2 个第一轮**自己引入或漏判**的
> P0 与 4 个 P1。这正是二次评审存在的理由：第一轮的结论也是待验证的断言。

---

### 第二轮评审（v2 → v3）

> 评审人：Anthropic 工程团队资深评审 · 评审日期 2026-07-22 · 评审对象 v2（1204 行）
> 评审方法：**不信任第一轮的任何结论**，把 v2 全文的 `file:line` 断言（含第一轮新写进去的）
> 逐条重新打开核对；后端另加 `bulk_ops.py` 的**工作树实际状态**（`git diff`）、`hierarchy.py`
> 全文、`validation.py`、`versions.py`/`plans.py` 全文、`lifecycle.py:120-160`、
> `requirements.py:258-296`、`models/{requirement,plan,version}.py`、`board_page.py`、
> `search.py`；前端另加 `TicketDrawer.tsx` 的**全部六条写入路径**、`BulkToolbar.tsx` 全文、
> `useBoard.ts` 全文、`FilterBar.tsx` 全文、`Pagination.tsx`、`ProgressBar.tsx`、`Sidebar.tsx`、
> `requirements/page.tsx` 全文。
> **实测基线：`python -m pytest -q --collect-only` = 872 例**——与第一轮读数一致，
> 第一轮那个数字**今日重测仍成立**（这条也是核验过的，不是抄的）。
> **并且实跑了一遍 `python -m pytest -q`：872 例全过，退出码 0**。这一跑不是为了确认基线，
> 而是为了给 P0-3 取证——**带着那个半成品，门禁依然全绿**。
>
> **总体判断**：v2 的方向与范围仍然正确，第一轮的 P0-1（`plan_id` 必须显式存在）、P1-1
> （import 清单）、P1-2（`_ROLE_GATES["plan"] = None`）、P1-3（`plan` 降为可选）、P1-4
> （类型归属）**复核全部成立且改得对**。问题出在第一轮**修 P0-2 时选错了落点**，以及
> 第一轮**顺手写下的两句"善后建议"经不起回源**：
> **① `TicketDrawer.tsx:190` 根本不是"抽屉里改状态/改归属"的落点，它在 `onDelete()` 里**；
> **② 版本删除 409 的中文翻译照抄了后端一句错误的 hint，会把用户送进死循环**；
> **③ 第一轮为 P2-6 指定的翻译落点（`BulkPlanModal`）在既有架构里根本拿不到那个错误**。
> **④ v2 的 `BulkRequest.plan_id` 注释仍写着"省略 = 解除归属"，与它自己那一轮的 P0-1 结论相反**；
> **⑤ 拖拽路径的失效点挂在了一个可能执行不到的分支上**。
> 另有一条与文档无关但会**直接阻断实现**的现场状况：`backend/services/bulk_ops.py`
> 在当前工作树里已被**半落地**（详见 P0-3）。
> 合计 **2 个 P0 + 5 个 P1 + 7 个 P2**，其中 P0/P1 已在本轮（v3）**全部就地修复**；
> P2 修复 6 条、登记 1 条（P2-14 行号漂移，不影响结论）。

#### P0（必须修复，否则实现即错）

| # | 位置 | 问题 | 处置 |
|---|---|---|---|
| **P0-3** | 现场状况 · §5.1 / §8.1 / §10-5 | **`backend/services/bulk_ops.py` 在当前工作树里已被半落地，且这个半成品是可被外部触发的 500**。`git diff` 显示：三个 import（`Plan` / `hierarchy` / `want_int`）与 `_ROLE_GATES["plan"] = None` **已经写进去了**，但 `_build_params` 没有 `plan` 分支、`_Runner` 没有 `_do_plan`、`_handler()`（`:256-264`）的字典里**没有 `"plan"` 键**。由于 `ACTIONS = tuple(_ROLE_GATES)`（`:84`），`run()` 里的 `want_str(data, "action", choices=ACTIONS)`（`:333`）现在**接受** `action:"plan"`，角色门禁为 `None` 放行，`_build_params` 落到末行返回 `{}`，随后 `_handler()` 直接 `KeyError: 'plan'` → **500**。任何已登录用户都能打出来。**更糟的是质量门禁看不见它**：现有 33 条批量用例没有一条发 `action="plan"`——**评审当日实测：带着这个半成品跑 `python -m pytest -q`，872 例全过、退出码 0**。也就是说 CLAUDE.md 规定的后端门禁**对这个可被外部触发的 500 完全无感**。 | 已改：①§5.1 的 `bulk_ops.py` 行改写为「**四处扩展点必须一次落全**」并要求落地前先 `git diff backend/services/bulk_ops.py` 确认半成品的边界；②§10 第 5 步加一句同样的前置自查；③**§8.1 新增用例 8 `test_every_bulk_action_has_a_handler`**——遍历 `ACTIONS` 断言每个动作在 `_Runner._handler()` 里都有实现，把「加了门禁忘了处理器」这类半落地**永久钉死**（本轮的 `plan` 只是它第一个受害者，下一个动作还会踩）。评审只改 `spec.md`（任务约束），故此条以**文档 + 用例**的形式关闭，不在评审阶段动源码。 |
| **P0-4** | §3.2 落点表 / §5.5 `TicketDrawer` 行 / §8.3-4 | **失效落点锚错了函数**。v2（第一轮修 P0-2 时）把「抽屉里改状态 / 改归属」的落点写成「`TicketDrawer.tsx:190` 旁加一行」。实测 `:190` 在 **`onDelete()`（`:186-192`）** 内部——那是**删除**路径。抽屉另外五条写入路径 `onAdvance(:156)` / `onAssignChange(:173)` / `onSaveDetails(:205)` / `onLevelChange(:222)` / `onConvert(:232)` **一条都不调** `invalidateTicketViews`。照 v2 实现的直接后果：本轮新增的「抽屉里改计划归属」（§7.5 的 `PlanPicker` → `patch({plan_id})`）**不会触发任何层级失效**，`/versions` 的进度与计数照旧陈旧；而 `:190` 那一行只在**删单**时生效。第一轮把 P0-2 的病因诊断对了（前缀表加了也刷不到），却把药下到了另一个函数上。 | 已改：§3.2 的落点表由 4 行扩为 **5 行并逐行点名真实的宿主函数**（删除 `onDelete:190` / 改归属 `onPlanChange`（新增）/ Agent 推进 `onAdvance:156` / 看板拖拽 / 批量 / 建单），§5.5 的 `TicketDrawer` 行同步改写并明确「**不是**在 `:190` 加一行就完事」。 |

#### P1（必须修复，否则交付物达不到自述的标准）

| # | 位置 | 问题 | 处置 |
|---|---|---|---|
| **P1-5** | §3.5 / §2.2 | **版本删除 409 的中文翻译给了一条做不到的建议**。v2 §3.5 把 `version still has plans` 译成「请先删除**或归档**这些计划」——照抄了后端 hint（`lifecycle.py:137` 逐字为 `"delete or archive its plans first"`）。但 `lifecycle.version_references`（`:126-130`）是 `Plan.query.filter_by(version_id=…).count()`，**不看 `status`**：归档的计划照样计数。用户照着提示把计划一个个归档，再删版本，仍然 409，且那个数字**一个都没少**——这是把用户送进死循环，比甩一句英文更坏。（对照：计划侧的 `plan_references`（`:141-150`）同样不看状态，但它的建议「移到其他计划或删除」是**真的**有效，故那句文案不动。） | 已改：§3.5 的版本文案改为「该版本下还有 N 个计划，请先**删除**这些计划（把计划归档**不会**解除引用）」，并补一段说明「翻译层的职责是说**真话**，不是把后端 hint 转成中文」；§2.2 把「后端 hint 串本身有误导」登记为**上一轮遗留、本轮不改后端契约**，防止下一轮误判为本轮引入。 |
| **P1-6** | §6.2（第一轮 P2-6 的处置）/ §5.4 / §5.5 | **第一轮为请求级 400 中文化指定的落点拿不到那个错误**。v2 §6.2 要求「`BulkPlanModal` 在提交前捕获 `ApiError` 并就地翻译」。但既有三个批量弹窗（`BulkAssignModal` / `BulkStatusModal` / `BulkLevelModal`）**都只通过 `onConfirm` 把值交出去**，发请求、`catch`、`toast.error(err.message)` 全在 `BulkToolbar.applyFromModal`（`:87-93`）里——弹窗组件在调用栈上**根本看不到** `ApiError`。照 v2 写，`plan_id is invalid` 这句英文仍然会原样甩给用户，P2-6 等于没修。 | 已改：翻译落到 `lib/bulk.ts` **新增的 `requestErrorText(err)`**（与 `failureText` / `skipText` 并列，**default 分支原样返回 `err.message`**，故对既有四个动作零行为变化），由 `BulkToolbar.applyFromModal:91` 调用一次即可。§6.2、§4.3 末、§5.4 的 `BulkPlanModal` 行、§5.5 的 `lib/bulk.ts` 行（三处 → 四处）同步改写。 |
| **P1-7** | §5.5 `useBoard` 行 | **拖拽路径的失效点挂晚了一步**。v2 要求「**第二段重取成功后**（`:119`）加 `invalidateHierarchyViews`」。但 `useBoard.move` 的两段语义是逐字写明的（`:116`：「第二段：拉取权威数据。失败**不回滚**——写入已成功」）：第二段失败会走 `:120-123` 的 `catch`，此时**后端已经改完了**，却永远不会执行 `:119` 那一行——版本 / 计划进度就此永久陈旧，且用户看到的提示是「已提交，正在刷新」，更不会去怀疑。 | 已改：落点前移到**第一段成功之后**（`:114` 之后、第二段之前），与该函数自己的两段语义对齐：「写入已成功」这个事实一成立就该失效，而不是等一个可能失败的重取。 |
| **P1-8** | §7.1 / §8.3-4 与「条件一-3」 | **DoD 第 4 条的手测脚本第 ① 步在当前 UI 里做不出来**。v2 要求「① 抽屉里改状态 → ② 看板拖拽 → ③ 批量流转」，并两处断言「抽屉恰是三条里唯一本来就能工作的那条」。实测：**抽屉根本没有状态控件**——`ticket.status` 在 `:318` 只被渲染成一枚只读 `Badge`；抽屉内能改状态的只有 `onAdvance`（Agent 推进，要求 assignee 是 Agent）与 `onConvert`（转 BUG）。叠加 P0-4（抽屉的 `invalidateTicketViews` 只挂在删除上），那句「唯一本来就能工作」**两个半句都不成立**。照抄这份 DoD 去验收，第 ① 步会卡在「找不到那个下拉」，验收人多半会跳过它，于是本轮最关键的一条判据被静默放行。 | 已改：§8.3-4 的写入路径更正为**看板拖拽 / 批量「流转状态」/ Agent 推进**三条改**分子**的路径，外加**改归属**（抽屉 `PlanPicker`、批量「归属计划」、建单、删单）四条改**分母**的路径，逐条给出可执行的操作步骤；文末「条件一-3」同步改写，删去那句不成立的断言。 |
| **P1-9** | §4.2 `BulkRequest` | **v2 的类型注释和它自己的 P0-1 修复直接打架**。P0-1 用整整一段论证「缺 `plan_id` 键 ⇒ 整批 400，绝不当作解除归属」，但 §4.2 里那个字段的 JSDoc 仍是第一轮之前的原文：「`null` / **省略** = 解除归属」。一个照着类型定义写客户端的人会得到与契约**相反**的结论——而这正是 P0-1 要防的那类客户端。此外 `plan_id?:` 的可选性让 `tsc` 也帮不上忙。 | 已改：注释改写为「`number` = 归属；`null` = 解除；**键必须显式存在，缺键 ⇒ 400**（§6.2）」；并加一句硬要求「唯一调用点（`BulkPlanModal` → `applyFromModal`）必须显式构造该键」。**不**改成判别联合——`apply(body: Omit<BulkRequest,"ids">)` 那里会引出一串类型体操，代价大于收益。 |

#### P2（建议，本轮择要修复）

| # | 位置 | 问题 | 处置 |
|---|---|---|---|
| P2-10 | §7.1「计数即深链」 | 计划行的「需求 4」深链是 `/requirements?plan_id=<id>`，**不带 `project_id`**。而工单列表页的项目作用域来自全局 `ProjectSwitcher`：在「全部项目」视图里点了项目 B 的计划，落地后列表仍 AND 上当前作用域，很可能是空表——用户会以为「这 4 条需求丢了」。 | **已修**：§7.1 要求深链**同时带 `project_id=<plan.project_id>`**，并在 §3.3 的 mount 读取里一并接受（复用既有 `ProjectSwitcher` 的写法）。 |
| ~~P2-11~~ | — | **已升级为 P1-9**（见上表）：`BulkRequest.plan_id` 的注释与 P0-1 的契约直接矛盾，不只是「类型不够严」，而是**文档在教读者写一个会被 400 挡住的客户端**。编号留空以免与评审过程中的引用对不上。 | 见 P1-9 |
| P2-12 | §3.8 / §8.1-1 | 批量归属计划会**顺带把 `project_id` 为 NULL 的工单搬进计划所属项目**（`hierarchy.py:119-121`，与单条写路径同款语义）。复用是对的，但 v2 全文没登记这件事，用例也没覆盖——「一次操作把 N 张无项目工单搬进某个项目」值得被写下来。 | **已修**：§3.8 补一句语义说明，§8.1 用例 1 顺带断言。 |
| P2-13 | §6.1 | `PATCH /api/plans/<id>` 一行漏了「`version_id` 指向不存在的版本 → `400 {"error":"version not found"}`」（`plans.py:133-134`）。前端 `PlanFormModal` 的改挂路径要用到它。 | **已修**：契约表补齐。 |
| P2-14 | 全文行号 | 三处行号漂移一行：`versions.py:156`→`:157`、`plans.py:142`→`:143`（两处 `:156`/`:142` 都是 `if "position" in data:`，下一行才是裸赋值）、`ProgressBar.tsx:22`→`:21`（`aria-label` 那一行）。均不影响结论。 | **不改正文**（§5 图例已有「行号为改动落点，实施时以当前文件为准」的免责）；在此登记，供实施者对照。 |
| P2-15 | §5.5 需求页行 | 该行没写「versions / plans 两个下拉的数据从哪来」——`useHierarchyOptions()` 只在 §3.1 的数据流图里出现过一次。 | **已修**：§5.5 补上。 |
| P2-16 | §7.1 ⋯ 菜单 | **归档之后对象会凭空消失**。后端列表默认隐藏 `archived`（`versions.py:77-79`/`plans.py:57-58`），用户点完「归档」眼看着卡片蒸发，而「显示已归档」勾选此刻可能还是禁用的（P2-1）——一个可逆动作看起来像删除。 | **已修**：§7.1 要求归档成功后**自动勾上「显示已归档」**（必要时先清空「状态」下拉）并 toast 说明，让卡片留在原位、徽章变「已归档」、「取消归档」就在同一个菜单里。 |

#### 第二轮复核通过、维持原判的部分

- 第一轮的 **P0-1 / P1-1 / P1-2 / P1-3 / P1-4 全部复核成立**，且改法正确：
  `hierarchy.py:106-107` 确为「无 `plan_id` 键 → 不改」；`bulk_ops.py:52` 现已是
  `ValidationError, want_int, want_str`（P1-1 的三个 import 已随半落地进入工作树）；
  `requirements.py:266` 确为行级 `can_manage_ticket`；11 个裸 `to_dict()` 站点
  （`requirements.py:332/354/389/421/559/608`、`bugs.py:191/212/246/274`、`search.py:85-86`）
  **逐条命中**；`lib/hierarchy.ts` 作为唯一归属无依赖倒置。
- **`plan_id` 声明为必填是安全的**（本轮额外验证了第一轮没查的两处）：看板卡片是
  `{**row.to_dict(), "document_count": …}`（`board_page.py:65-66`），`/api/search` 是
  `[r.to_dict() for r in reqs]`（`search.py:85-86`）——**两处都带 `plan_id`**，故
  `Requirement`/`Bug`/`Card` 上把它标必填不会对任何真实端点说谎。
- §3.8 的 `_do_plan` 逐项接住 `ValidationError` 的设计**成立**：`resolve_plan_for_ticket`
  确为先校验后写入（`hierarchy.py:111-122`），跨项目分支在任何字段被改动前抛出，
  `bulk_ops.py:11-13` 的免 SAVEPOINT 不变量继续有效（第一轮 P2-9 的判断正确）。
- `_build_params` 里 `want_int` 抛出的 `ValidationError` 会经全局处理器变成整批 400——
  与 `_resolve_assignee`（`:151-159`）的既有先例同型，`run()` 的 docstring（`:330-331`）
  已把这条路径写明，无需额外 try。
- §6.1 的 as-built 契约表除 P2-13 一处遗漏外**逐行无误**；`Pagination` 确在
  `total <= limit` 时返回 `null`（`Pagination.tsx:23`）；`ui/` 确为 16 个原语，本轮零新增。
- `components/planning/` 与 `app/(app)/versions/` **确实都还不存在**，§5.4 的 11 个新建文件
  没有一个会覆盖既有文件。

---

### 第一轮评审（v1 → v2）

> 评审人：Anthropic 工程团队资深评审 · 评审日期 2026-07-22 · 评审对象 v1（916 行）
> 评审方法：**逐条回源核验**。文档里的每一处 `file:line` 断言都被打开对照过；后端 `bulk_ops.py`
> / `hierarchy.py` / `versions.py` / `plans.py` / `lifecycle.py` / `validation.py` / `scope.py`
> 与前端 `api.ts` / `swr-keys.ts` / `useTicket.ts` / `useBoard.ts` / `bulk.ts` / `FilterBar.tsx` /
> `ProgressBar.tsx` / `ConfirmDialog.tsx` / `Sidebar.tsx` / `permissions.ts` / `types.ts` /
> `constants.ts` / `requirements/page.tsx` / `projects/page.tsx` / `ProjectFormModal.tsx`
> 全部通读。**评审时的实测基线：`pytest -q --collect-only` = 872 例**（这个数字只作为本次评审的
> 现场读数，实施时必须按 §8.1 重新取，不得回抄）。
>
> **总体判断**：文档质量高于本仓库既往同类 spec 的平均线——四层树的取数策略、懒加载边界、
> 「当前值恒可见」陷阱、`ProgressBar` 的 `null` 语义、`FilterBar` 用单个可选对象属性扩展，
> 这些都是踩过坑才写得出来的判断，且 §5 的行号引用抽查**全部命中**。问题集中在两处：
> **一是 §3.8 那段「可直接粘贴」的后端代码有三处硬伤**（少一个 import、一个会造成批量误删归属的
> 默认值、一个与模块自身不变量冲突的门禁）；**二是 §3.2 断言的失效方案经核实并不能兑现 §8.3 第 4 条
> 验收**——`invalidateTicketViews` 的现网调用点根本不覆盖看板拖拽与批量这两条主路径。
> 下列 P0/P1 已在本轮修订中**全部就地修复**，P2 择要修复、其余作为「已知并接受」列入评审结论。

#### （第一轮）P0（必须修复，否则实现即错）

| # | 位置 | 问题 | 处置 |
|---|---|---|---|
| **P0-1** | §3.8 `_build_params` / §6.2 / §8.1-2 | **省略 `plan_id` 被定义为「批量解除归属」**——一个漏传字段的客户端会**静默清空整批工单的归属**。这既与它所复用的 `hierarchy.resolve_plan_for_ticket` 的契约**直接矛盾**（`services/hierarchy.py:106-107` 逐字写着「请求体**无** `plan_id` 键 → **不改**」），也与本仓库既有的 `assign` / `unassign` **拆成两个 action** 的先例相悖（`bulk_ops.py:68-75`）。破坏性语义绝不能是缺省值。 | 已改：**`plan_id` 键必须显式存在**，缺键 → 整批 400；显式 `null` 才是解除归属。§3.8 / §6.2 / §8.1 三处同步改写，并新增用例 7 钉死「缺键 → 400 且一行未改」。 |
| **P0-2** | §3.2 / R-2 / §8.3-4 | **失效方案不成立**。§3.2 断言「往两个前缀数组里各加 `/versions`、`/plans`」即可让进度实时刷新，但这两个数组只被 `invalidateTicketViews` / `invalidateAdminViews` 读取，而**现网 `invalidateTicketViews` 的全部调用点**是：`TicketDrawer.tsx:190`、`agents/page.tsx:69`、四个文档 hook——**看板拖拽（`useBoard.move`）、批量操作（`BulkToolbar.apply` → `onDone` → 页内 `mutate()`）、建单（`onCreated` → 页内 `mutate()`）三条路径全都不调它**。于是 §8.3 第 4 条「把最后一张需求推成 done → 回 `/versions` 看进度上涨」在最主流的拖拽路径上**必然失败**，而 G2 正是本轮目标之一。 | 已改：§3.2 增设第三个失效函数 `invalidateHierarchyViews`（只管 `/versions`、`/plans` 两个前缀，形状与理由完全照抄 `invalidateDocumentViews` 的既有先例，`swr-keys.ts:45-54`），并在 §5.5 明确把它挂到 `useBoard.move` 成功分支、`BulkToolbar.apply`、两个列表页的建单回调上；R-2 与 §8.3-4 同步改写。 |

#### （第一轮）P1（必须修复，否则交付物达不到自述的标准）

| # | 位置 | 问题 | 处置 |
|---|---|---|---|
| **P1-1** | §3.8 末「需要新增的 import」 | 该句**两个方向都错**：`want_int` 被断言「已在文件内」，实际 `bulk_ops.py:51` 只 `from services.validation import ValidationError, want_str`——照抄即 `NameError` → 500；而被列为「需新增」的 `ValidationError` **本来就已导入**，重复 import 会被 lint 挑出来。 | 已改：import 清单更正为 `Plan` / `hierarchy` / `want_int` 三项，并注明 `ValidationError` / `jsonify` / `db` 已在文件内（附 `:39/:41/:51` 溯源）。 |
| **P1-2** | §3.8 `_ROLE_GATES` / §6.2 / §5.5 / §8.1-6 / §8.3-7 | **门禁与单条端点不对齐**。`plan_id` 的单条写路径是 `PATCH /api/requirements/<id>`，其门禁为**行级** `can_manage_ticket`（`routes/requirements.py:266`），而非 `admin｜pm`。把批量 `plan` 的 `_ROLE_GATES` 设成 `("admin","pm")` 会让「一张一张改得动、一次改多张就 403」的成员产生认知断裂，并**违反 `bulk_ops.py:20-23` 逐字写明的模块不变量**（「门禁与单条端点逐一对齐…… move / priority / severity 逐项走 `can_manage_ticket`」）。`plan` 与 `priority`/`severity` 同型（都是「把工单的某个字段设成某值」），应当同门禁。 | 已改：`_ROLE_GATES["plan"] = None`（逐项 `can_manage_ticket` 裁决，`_do_plan` 内本就有），§6.2 鉴权行、§5.5 的 `BulkToolbar` 动作项（去掉 `requiresManage`）、§8.1 用例 6（403 → 逐项 `forbidden`）、§8.3-7 同步改写。 |
| **P1-3** | §4.2 末「为什么声明为必填」 | **论据经核实为假**。文档称 `plan` 在「**每一个**工单序列化站点都已无条件富化」，但实测**至少 11 个站点返回裸 `to_dict()`**：`requirements.py:332/354/389/421/559/608`、`bugs.py:191/212/246/274`、`services/search.py:85-86`、`routes/me.py:64-69`。其中 `/api/search` 与 `/api/me/work` 的响应在前端**正是**被声明为 `Requirement[]` / `Bug[]` 的（`types.ts:389-390`、`:370-371`）。把 `plan` 声明为必填 = 让类型系统对这两处**说谎**，而文档恰恰是拿「typecheck 能兜住漏富化」当作该决定的唯一理由。（`plan_id` 不受影响——它在 `to_dict()` 里，`models/requirement.py` 已核实。） | 已改：`plan` 降为可选 `plan?: PlanContext \| null`（与 `document_count?:` 同款理由，`types.ts:153` 有先例），`plan_id` 维持必填；§4.2 的论据整段重写为真实情况，并新增「消费侧一律按缺省为 `null` 渲染」的硬要求。 |
| **P1-4** | §3.3 / §5.2 / §6.3 | **新模块的公共类型有三个互相冲突的归属**：§3.3 定义 `HierarchyParam`（此后全文再未出现），§5.2 说 `HierarchyFilterValue` 住在 `lib/hierarchy.ts`，§6.3 却把它 `export` 在 `components/planning/HierarchySelects.tsx` 里。而 §5.5 要 `hooks/useBoard.ts` 用这个类型——hook 反向 import 一个 `"use client"` 组件的类型是层级倒置。 | 已改：**唯一归属定为 `lib/hierarchy.ts`**（无 React 依赖的纯逻辑层），§3.3 删去孤儿 `HierarchyParam`、§6.3 改为 `import type` 引用，并补一句层级方向说明。 |

#### （第一轮）P2（建议，本轮择要修复）

| # | 位置 | 问题 | 处置 |
|---|---|---|---|
| P2-1 | §7.1 筛选条 | 「状态」下拉与「显示已归档」勾选**会静默互相抵消**：后端是 `if status: … elif include_archived …`（`versions.py:74-79`、`plans.py:54-58`），选了具体状态后勾选框**完全不起作用**——一个点了没反应的死控件，正是本仓库反复警告的「会说谎的 UI」。 | **已修**：§7.1 明确「选中具体状态时把勾选框 `disabled` 并加 `title` 说明」。 |
| P2-2 | §7.1 线框 / §4.2 | 版本卡画了「👤 Ada」，但 `Version.to_dict()` **只有 `owner_id`、没有 owner 概要**（`models/version.py`）。文档没说名字从哪来。 | **已修**：§7.1 注明由 `USERS_KEY` 就地映射（同 `projects/page.tsx:33` 的既有做法），并给出取不到时的降级文案。 |
| P2-3 | §7.1 空态 | 只处理了 `scope="none"`，**漏了 `scope=null`（全部项目）**：此时列表会混排多个项目的版本，而版本卡上没有任何项目标识，两个项目各有一个「v1.0」就分不清。 | **已修**：§7.1 增加「全部项目作用域下版本卡显示项目徽章」。 |
| P2-4 | §5.3 / §5.5 表头 | 文件计数与表格行数对不上（§5.3 称「3 个文件」实为 4；§5.5 称「7 个文件」实为 11）。DoD 会照着数。 | **已修**：计数更正。 |
| P2-5 | §3.4 | 版本控制台的展开深链用 `?version=<id>`，与工单页的 `?version_id=` **命名不一致**，且全文**没有任何地方产生这个链接**。 | **已修**：统一为 `?version_id=`，并说明其产生方（`PlanBadge` 的版本段回跳）。 |
| P2-6 | §6.2 / §4.3 | `failureText` / `skipText` 只覆盖**逐项**桶；**请求级 400**（`plan_id is invalid`）走的是 `BulkToolbar.applyFromModal` 的 `toast.error(err.message)`（`BulkToolbar.tsx:91`），会把英文契约串直接甩给用户。 | **已修**：§6.2 要求 `BulkPlanModal` 就地翻译该 400（同 §3.5 的 hook 层翻译手法）。 |
| P2-7 | §2.2 非目标 | `PATCH /api/plans/<id> {version_id}` 改挂版本时**不重算 `position`**（`plans.py:140` 只赋 `version_id`），改挂后新版本组内会出现重复 position。属上一轮遗留，与本轮「不做排序」的非目标相关但未被点名。 | **不修**（本轮非目标）：已在 §2.2 显式登记为「已知遗留」，避免下一轮当成本轮引入的回归。 |
| P2-8 | §4.1 | `SEED_VERSION = "3"` 被写成在 `backend/seed.py`，实际在 `backend/models/seed_record.py:21`。 | **已修**：更正溯源。 |
| P2-9 | §3.8 | `_do_plan` 是本模块**第一个在逐项裁决中调用「共享写路径 helper」**的动作，与 `bulk_ops.py:11-13` 的「全部裁决都是纯读检查，故不需要 SAVEPOINT」这一不变量相邻。经核实 `resolve_plan_for_ticket` **先校验后写入**（`hierarchy.py:112-122`），不变量仍然成立，但文档应写明这条依赖。 | **已修**：§3.8 补一段不变量说明。 |

#### （第一轮）复核通过、无需改动的部分（供实施者放心引用）

- §5 全部行号引用抽查**命中**：`FilterBar.tsx:10-22`（确为 11 个字段）/`:39-40`/`:42-43`/`:94-99`、
  `requirements/page.tsx:37/42-49/52-71/62/80-91/98-99/111/216-219/258-270`、
  `ConfirmDialog.tsx:74-79/75/120-124`、`ProgressBar.tsx:15-16/21/33`、`useTicket.ts:94-95`、
  `useBoard.ts:23-24/118`、`bulk.ts:20/48/69`、`BulkToolbar.tsx:35/61-66`、`Sidebar.tsx:34/89-108`、
  `api.ts:41-46/48-59`、`swr-keys.ts:13/27`、`types.ts:139/153/158/511/520/536/567/581/591`、
  `constants.ts:18/74/151/218-220/238-242/341`、`ProjectFormModal.tsx:44-52`、`projects/page.tsx:34/86`。
- §3.5 引用的两个 409 契约体与 `services/lifecycle.py:133-138`/`:153-158` **逐字一致**；
  `ApiError` 确为可 `new` 的普通导出类且构造签名为 `(status, message, detail?, allowed?)`（`api.ts:48-59`）。
- §6.1 的 as-built 契约表**逐行核对无误**，包括「`/plans` 的 `version_id` 不接受 `none`」
  （`plans.py:51` 用的是 `want_query_int`）与「看板已支持层级过滤且已富化 `plan`」
  （`board_page.py:47-48`/`:64-65`）这两条容易写错的细节。
- §3.4 的分页判据成立：`pagination.py` 确为 `DEFAULT_LIMIT=50`/`MAX_LIMIT=200`/`clamp=True`。
- §3.9 指出的 `useTicket.patch` 缺陷**真实存在**且诊断正确：`PATCH` 走
  `with_plan_context_one`（由 `to_dict()` 构造、不含 `document_count`），整体覆盖确会抹掉富化字段。
- §3.7 的「侧栏不做角色门禁」与 `Sidebar.tsx:89-108`（`is_root` 是唯一例外）一致。
- §2.2 五条非目标的理由**全部经得起回源**，尤其「后端没有 reindex 端点所以不做拖拽排序」
  （`versions.py:156`/`plans.py:142` 确为裸赋值）。

---

## 1. 概述（Overview）

上一轮把「版本 → 计划 → 需求/BUG」这条层级链**在后端完整地立了起来**：`versions` / `plans` 两张新表、
工单侧一个可空无外键的 `plan_id`、两套 CRUD 路由、层级级联过滤、进度聚合、生命周期 409 守卫、
迁移与种子与清理的全链路登记，配套 `test_versions` / `test_plans` / `test_hierarchy` 三个新测试文件。
那一轮做对了最难的部分——**它把四层树坐落在既有 `Project` 之下，全程 additive，没有破坏任何既有契约**。

但它对用户是**完全不可见的**。今天在 `frontend/` 里搜 `plan_id` 一个字都搜不到：`lib/types.ts:139/158`
的 `Requirement` / `Bug` 没有 `plan_id`，`lib/constants.ts` 没有版本 / 计划的状态配色，`Sidebar.tsx:34`
的 `NAV` 没有入口，`app/(app)/` 下没有 `versions/` 目录。也就是说：产品需求里「**版本和计划都能够进行
人工管理，界面上对应的需求和 BUG 也能够正确分类和筛选**」这句话，**一个字都还没兑现**。当前状态下，
用户唯一能碰到版本 / 计划的方式是拿 curl 打 `/api/versions`——这不叫功能完成，这叫接口就绪。

本轮做的事情因此非常明确：**把已经存在的能力接出来，做成一个值得看、也经得起用的界面**。具体是三件事。
其一，新建「版本」主页 `/versions`：版本卡可折叠展开其计划行，两级都带真实进度条与计数，两级都能新建 /
编辑 / 归档 / 删除，删非空时把后端的 409 翻成一句能照着做的中文而不是把 `version still has plans` 甩在
用户脸上。其二，把层级接进工单的日常动线：需求 / BUG 列表页与看板页加「版本 → 计划」级联筛选（含
「未归属」），列表加「计划」徽章列，抽屉里能改归属、能看到「项目 · 版本 · 计划」的面包屑，建单表单能
预选计划。其三，一个**很小但决定成败**的后端增量：批量「归属计划」。没有它，一个已有 200 张工单的存量
项目要采用这套层级，就得开 200 次抽屉——层级会因为「迁移成本太高」而事实上无人使用。

**设计基调**沿用仓库既有的暖色浅色风（`tailwind.config.ts:10-42`：`bg #F7F4EE` / `surface #FFFFFF` /
`border #E7E1D6` / `ink #1A1A17` / `ink-muted #6E6A62` / `clay #C15F3C` + `clay-soft` + `clay-dark`，
标题衬线体）。所有新配色一律走 `lib/constants.ts:18` 的 `BadgeStyle {label,bg,fg}` **内联十六进制**写法，
**不引入第二套 Tailwind class 配色语言**（`constants.ts:218-220` 对此有明确警告）。所有交互控件复用
`components/ui/` 下已有的 16 个原语，**本轮不新增任何 UI 原语**——它们全都已经存在且被验证过。

---

## 2. 目标与非目标

### 2.1 目标（本轮交付）

| # | 目标 | 验收信号 |
|---|---|---|
| G1 | `/versions` 控制台：版本卡（可折叠）+ 计划行，两级 CRUD + 归档 | 能在 UI 建版本 → 建计划 → 编辑 → 归档 → 删除，删非空被中文 409 拦住 |
| G2 | 两级进度可视 | 版本卡进度读 `total_count`/`done_count`；计划行进度读 `requirement_count+bug_count`/`done_count` |
| G3 | 工单列表 / 看板的「版本 → 计划」级联筛选（含「未归属」） | 四个页面（需求列表 / BUG 列表 / 需求看板 / BUG 看板）都能按版本、按计划筛 |
| G4 | 工单侧的归属出口 | 列表「计划」徽章列；抽屉可改 `plan_id` 并显示层级面包屑；建单表单可预选计划 |
| G5 | 批量归属计划（**唯一的后端增量**） | 列表页选中 N 张 → 「归属计划」→ 一次请求落库，跨项目的逐项失败可读 |
| G6 | 零回归 | `npm run typecheck` 0 error、`npm run build` 成功；`pytest -q` 零失败且用例数 ≥ N₀ |

### 2.2 非目标（明确不做，附理由）

- **拖拽排序版本 / 计划**。后端只有 `PATCH {position}` 而**没有 swap / reindex 端点**
  （`routes/versions.py:156`、`routes/plans.py:142` 都是裸赋值），前端单改一行的 `position` 不会顺移
  兄弟节点，会立刻造出重复 position。要做对必须先在后端加一个 `_reindex` 语义——那是独立一轮的活。
  本轮排序恒按后端的 `position ASC, id ASC`（`versions.py:80`/`plans.py:59`），即**创建顺序**。
  **顺带登记一条已知遗留（评审 P2-7，本轮不修）**：`PATCH /api/plans/<id> {version_id}` 改挂版本时
  **不重算 `position`**（`plans.py:140` 只赋 `version_id`），改挂后计划在新版本组内可能与既有计划
  position 重复——由于列表二级排序是 `id ASC`，表现为顺序看起来随机而非报错。这是上一轮的遗留，
  与本轮「不做排序」同源，写在这里是为了**下一轮不要把它误判成本轮引入的回归**。
- **不修后端 409 的 hint 串**（评审 P1-5 的另一半）。`lifecycle.py:137` 的
  `"delete or archive its plans first"` 是**错的**——`version_references`（`:126-130`）不看
  `status`，归档计划照样计数，「archive」这条出路根本不存在。但那是一个已被
  `test_versions` 断言过的**稳定错误体**，改它属于契约变更。本轮的处理是
  **前端翻译层只说真话**（§3.5：只提「删除」），把后端串的更正留给专门的一轮。
  同样登记在此，防止下一轮把「中文和英文说的不一样」误判成翻译漏抄。
- **版本 / 计划进 `activities` / 通知 / 全局搜索 / 仪表盘统计**。上一轮 §2.2 已定死：它们走结构化日志
  （`log = logging.getLogger("aragon.versions")`，`versions.py:28`），不写 `activities`，以免撕开
  `TICKET_ENTITY_TYPES` 隔离让治理事件与工单事件互相泄漏。本轮**不得**顺手打开这个口子。
- **跨项目共享的版本**。`versions.project_id` 是 NOT NULL 真外键且创建后不可变（`versions.py:159-160`
  静默忽略请求体里的 `project_id`）。跨项目版本是一个更大的建模决策，不在本轮。
- **「解绑式删除」计划（`?detach=1`）**。后端目前是 409 守卫，与删项目的既有先例一致，也是最不易误删的
  一侧。若产品反馈更需要「删计划顺带把工单变未归属」，那是后端契约变更，另起一轮。
- **甘特图 / 燃尽图 / 版本发布说明聚合**。属于第二阶段的规划可视化，本轮只做「树 + 进度条」。

---

## 3. 技术设计（Technical design）

### 3.1 全景数据流

```
Header · ProjectSwitcher (lib/project-scope.tsx)
        └── scope: number | "none" | null  ──┐
                                             │ project_id=<scopeParam>
   ┌─────────────────────────────────────────┴──────────────────────────────────┐
   │                                                                            │
/versions 控制台                                     需求 / BUG 列表 · 看板 · 抽屉
   │                                                                            │
   ├─ useVersions(filters)                          ├─ useHierarchyOptions()  ← 下拉数据源
   │    key: /versions?project_id&status&…&limit&offset   key: /versions?project_id&limit=200
   │    → Version[] + total (X-Total-Count)                 /plans?project_id&limit=200
   │                                                 │
   └─ <VersionCard> 展开时挂载 <VersionPlans>        ├─ <HierarchySelects>（级联，受控）
        └─ usePlansOf(versionId)                     │      → { version, plan } 两个字符串
             key: /plans?version_id=<id>&limit=200   │      → listKey 拼 ?version_id= / ?plan_id=
                                                     │
                                                     └─ <PlanPicker>（赋值用，输出 plan_id|null）
```

**唯一真相约定（不可违反）**：

1. **版本进度只读 `/api/versions` 返回体上的 `total_count` / `done_count`**
   （`routes/versions.py:41-54` 富化，`services/hierarchy.py:194-217` 聚合）。
   **绝不在前端对分页的 plans 列表求和**——`hierarchy.py:198-199` 逐字写明了这一条，因为 plans 是分页的，
   客户端求和必然漏算。
2. **计划进度只读 `/api/plans` 返回体上的 `requirement_count` / `bug_count` / `done_count`**
   （`routes/plans.py:28-39`）。
3. **`released_at` 永不由前端发送**（服务端托管，`routes/versions.py:61-66`）。表单里连输入框都不给。
4. **`version.project_id` 编辑态不可改**（`versions.py:159-160` 静默忽略）。编辑弹窗里以只读文本显示。

### 3.2 SWR key 契约：为什么**不**新增 `VERSIONS_KEY` / `PLANS_KEY` 常量

上一轮 spec §5.2（`version-plan-hierarchy/spec.md:433`）建议加 `VERSIONS_KEY = "/versions?limit=200"`
与 `PLANS_KEY = "/plans?limit=200"` 两个字面量常量。**本轮推翻这一条**，理由在仓库里写得很清楚：

- `lib/api.ts:9-15` 的铁律是「一个 `*_KEY` ⇒ 一种响应形状」；`lib/api.ts:41-45` 更进一步用
  `GOVERNANCE_AUDIT_PREFIX` 做了示范——**分页 / 带筛选的视图不得复用 `*_KEY`，只固化前缀**。
- 版本 / 计划的下拉**必须带项目作用域**（`?project_id=<scopeParam>`），否则在项目 A 里会看到项目 B 的
  版本。一个不含 scope 的固定字面量常量做不到这件事；硬做就会退化成「切了项目，下拉不变」。

因此：

```ts
// lib/api.ts —— 紧挨 AGENTS_KEY(:28) 之后声明
/** `/versions` 的**路径前缀**（同 GOVERNANCE_AUDIT_PREFIX:46 的理由：版本列表带项目作用域 +
 *  分页 + 状态筛选，是「一个前缀多种 key」，故有意不叫 `*_KEY`）。完整 key 由 hooks 内联拼。 */
export const VERSIONS_PREFIX = "/versions";

/** `/plans` 的路径前缀（同上）。 */
export const PLANS_PREFIX = "/plans";
```

`lib/swr-keys.ts` 的改动分两半，**两半都必须做**——只做前一半是 v1 的错误（评审 P0-2）。

**前一半：`ADMIN_VIEW_PREFIXES` 追加两个字面量**，解决「版本 / 计划自身变了 → 列表与下拉该刷」：

```ts
const ADMIN_VIEW_PREFIXES = [
  "/users", "/projects", "/agents", "/stats", "/settings/audit",
  // 【version-plan-console §3.2】版本 / 计划的增删改要让所有挂着它们的下拉与列表一起刷新。
  "/versions", "/plans",
];
```

**后一半：新增第三个失效函数**，解决「工单变了 → 进度该刷」：

```ts
/** 工单的归属 / 状态变化后，失效版本与计划的进度视图（version-plan-console §3.2）。
 *
 *  **为什么不是往 `TICKET_VIEW_PREFIXES` 里塞两个前缀**（v1 的原方案，评审 P0-2 否决）：
 *  那个数组只被 `invalidateTicketViews` 读，而它的现网调用点只有 `TicketDrawer.tsx:190`、
 *  `agents/page.tsx:69` 与四个文档 hook——**看板拖拽、批量操作、建单三条路径根本不调它**，
 *  加了前缀也刷不到，§8.3 第 4 条验收会在最主流的拖拽路径上直接失败。
 *
 *  **为什么单独成函数而不是复用 `invalidateTicketViews`**：`useBoard.move` 成功后已经自己
 *  重取过 `/board/` 那一个 key（`useBoard.ts:117-119`），再走一遍含 `/board/` 的宽前缀表
 *  就是一次白白的重复请求。本函数只管两个前缀，形状与理由同 `invalidateDocumentViews`
 *  （见本文件 :45-54 的既有先例：窄函数 + 调用方按需叠加，而不是把前缀表越堆越宽）。 */
export function invalidateHierarchyViews(mutate: ScopedMutator) {
  return invalidateByPrefix(mutate, ["/versions", "/plans"]);
}
```

**调用点（缺一个就留下一类陈旧进度，§5.5 已逐行登记）**。

> **【评审 P0-4】落点必须按函数点名，不能按行号点名。** v2 曾把第一行写成
> 「`TicketDrawer.tsx:190` 旁加一行」——那一行在 **`onDelete()`（`:186-192`）** 里，是**删除**路径。
> 抽屉里 `invalidateTicketViews` **有且只有这一个调用点**；`onAdvance(:156)` / `onAssignChange(:173)`
> / `onSaveDetails(:205)` / `onLevelChange(:222)` / `onConvert(:232)` 一条都不调它。
> 照那句话实现，本轮新增的「抽屉里改计划归属」根本刷不到 `/versions`。

| # | 触发路径 | 宿主函数（改这里） | 它改变了什么 | 现状为何不够 |
|---|---|---|---|---|
| ① | 抽屉里**改计划归属** | **新增的 `onPlanChange()`**（§7.5，形状照抄 `onLevelChange:222-228`）在 `await patch({plan_id})` 成功之后 | 分母（计划 / 版本各自的工单总数，一进一出两边都变） | 这是本轮新增的路径，现状里不存在任何失效 |
| ② | 抽屉里**删除**工单 | `TicketDrawer.onDelete()`，`:190` 的 `invalidateTicketViews(mutate)` 旁 | 分母与分子同时减 | 它只调 `invalidateTicketViews`，前缀表里没有版本 / 计划 |
| ③ | 抽屉里 **Agent 推进** | `TicketDrawer.onAdvance()`（`:156-166`），`await advanceAgent()` 成功之后 | 分子（可能推进到终态） | 全程只 `mutate` 自己那两个 key + `onChanged?.()` |
| ④ | **看板拖拽**成功 | `useBoard.move()`，**第一段 `api.patch` 成功之后**（`:114` 之后，**不是** `:119`，见评审 P1-7） | 分子 | `move()` 全程只 `mutate` 自己那一个 key |
| ⑤ | **批量**（`plan` / `move` / `delete`） | `BulkToolbar.apply()` 内 `onDone()` 之后（`:76`） | 视动作而定，分子分母都可能变 | `onDone` 是页内 `mutate()`，只刷当前列表 |
| ⑥ | **建单**（可能带 `plan_id`） | 两个列表页的 `onCreated`（需求页 `:326-329`） | 分母 | 同上 |

> **为什么 ④ 要挂在第一段而不是第二段**（评审 P1-7）：`move()` 的两段语义在 `:116` 逐字写着
> 「第二段：拉取权威数据。失败**不回滚**——写入已成功」。第二段失败会走 `:120-123` 的 `catch`，
> 那里后端**已经改完了**，却永远执行不到 `:119`。判据应当是「写入成功」这个事实，
> 而不是「重取也成功」这个运气。

> **抽屉里没有「改状态」这回事**（评审 P1-8）：`ticket.status` 在 `TicketDrawer.tsx:318`
> 只被渲染成一枚**只读** `Badge`，抽屉不提供状态下拉。能在抽屉里改状态的只有 ③（Agent 推进）
> 与「转为 BUG」。§8.3 第 4 条的手测脚本据此重写，不要再去找一个不存在的控件。

> **注意方向**：`ADMIN_VIEW_PREFIXES` 解决「版本/计划变了 → 列表与下拉该刷」，
> `invalidateHierarchyViews` 解决「工单变了 → 进度该刷」。**这是两个不同方向**，
> 少做任何一侧都必然留下一类陈旧视图。

### 3.3 级联筛选的状态归属与 URL 契约

**筛选状态住在页面的 `useState` 里，不写回 URL**——这是本仓库既定的做法
（`requirements/page.tsx:42-49`，`router.replace` 在该页从未被用来回写筛选）。

URL 查询串只作为**一次性入口**被读取，这同样有先例：`requirements/page.tsx:52-71` 在 mount 时读
`?q=`（全局搜索跳转）与 `?status=`（看板截断列的「查看全部」出口），且 `?status` 经
`REQUIREMENT_COLUMNS.some(...)`（`:62`）白名单校验后才落地。本轮**照抄这个形状**：

```ts
// requirements/page.tsx —— 在既有 useEffect(:52-71) 内、读完 ?status 之后追加
// 【version-plan-console §3.3】承接 /versions 页计划行的「查看工单」深链。
// 只接受正整数或 "none" 两种形态：把任意串灌进筛选条会显示一个假筛选（后端也会 400）。
const v = search.get("version_id") || "";
if (isHierarchyParam(v)) setVersionFilter(v);
const p = search.get("plan_id") || "";
if (isHierarchyParam(p)) setPlanFilter(p);
// 【评审 P2-10】深链同时带 project_id：不切作用域的话，「全部项目」视图里点过来的
// 计划会被当前作用域 AND 成空表。setScope 来自 useProjectScope（lib/project-scope.tsx:19），
// 它会连带写 localStorage，正是「跟着链接走到那个项目」应有的行为。
const proj = search.get("project_id") || "";
if (/^[1-9]\d*$/.test(proj)) setScope(Number(proj));
```

其中守卫函数与两个筛选值的类型一并放在新模块 `lib/hierarchy.ts`（见 §5.2），
避免需求页与 BUG 页各抄一份：

```ts
// lib/hierarchy.ts —— 本模块是级联筛选类型与判据的**唯一归属**（评审 P1-4）
/** 单个层级筛选值的取值域：`""`=不过滤 · `"none"`=未归属 · `"<正整数>"`=具体 id。
 *  与后端 services/scope.py:17 的 UNASSIGNED 哨兵（"none"）逐字对齐。 */
export interface HierarchyFilterValue {
  version: string;
  plan: string;
}

export function isHierarchyParam(raw: string): boolean {
  return raw === "none" || /^[1-9]\d*$/.test(raw);
}
```

> **归属与层级方向（评审 P1-4 定死，勿再分叉）**：`HierarchyFilterValue` **只在 `lib/hierarchy.ts`
> 声明**，`HierarchySelects.tsx`、`useBoard.ts`、两个列表页、两个看板页一律 `import type` 引用。
> v1 曾在 §6.3 把它 `export` 在 `HierarchySelects.tsx` 里——那会让 `hooks/useBoard.ts` 反向依赖一个
> `"use client"` 组件的类型（层级倒置），也与 §5.2「`lib/hierarchy.ts` 是级联逻辑的单一真相」自相矛盾。
> 依赖方向恒为：`lib/hierarchy.ts`（纯函数，无 React）← `hooks/*` ← `components/*` ← `app/*`。

**级联语义（务必逐条实现，每一条都对应后端的一个真实分支）**，判据来自
`services/hierarchy.py:59-86`：

| 版本选择 | 计划下拉 | 发出的查询串 | 说明 |
|---|---|---|---|
| `""` 全部版本 | 全部计划 / 未归属 / 作用域内**所有**计划 | `plan_id` 按所选 | 计划可跨版本任选 |
| `"none"` 未归属版本 | **禁用**并复位为 `""` | 仅 `version_id=none` | 后端 `version_id=none` ⇒ `plan_id IS NULL`；再叠 `plan_id=<id>` 必然空集 |
| `"<id>"` 具体版本 | 只列该版本下的计划，**不提供「未归属」项** | `version_id=<id>` +（可选）`plan_id=<id>` | `plan_id=none` 与 `version_id=<id>` 同传必然空集，不给用户挖这个坑 |

切换版本时，若当前所选计划的 `version_id` 与新版本不符 → **把计划复位为 `""`**（否则会静默变成空列表）。

### 3.4 版本控制台的取数策略（避免 N+1 与首屏浪费）

- 版本列表：`/versions?project_id=&status=&include_archived=1&limit=20&offset=` （`PAGE_SIZE = 20`，
  版本卡比表格行高得多，20 张即一屏半）。后端 `paginate` 默认 50、上限 200（`services/pagination.py`），
  显式写进 key 是为了「一个 key 一种形状」在改上限时仍成立（同 `useBoard.ts:21-24` 的既有理由）。
- 计划：**只在版本卡展开时才请求**。做法是把子列表拆成独立组件 `<VersionPlans versionId>`，
  折叠时**根本不挂载**，展开时其内部 `useSWR('/plans?version_id=<id>&limit=200', listFetcher)` 才生效。
  这样 20 张版本卡的首屏只有 1 个请求，而不是 21 个。
- 展开态存在页面级的 `Set<number>`；**`?version_id=<id>`** 深链在 mount 时预置该 Set（用于从别处跳转到
  某个版本并直接看到它的计划）。**参数名与工单页的 `?version_id=` 保持一致**（评审 P2-5：v1 在此写的是
  `?version=`，全站出现两个名字表达同一件事，且当时没有任何地方产生这个链接）。
  **产生方**：`PlanBadge`（§5.4）的版本段渲染为 `<Link href="/versions?version_id=<plan.version_id>">`，
  于是「在需求列表看到一枚计划徽章 → 点它的版本段 → 落到 `/versions` 且该版本已展开」形成闭环；
  同一守卫 `isHierarchyParam` 复用（§3.3），非法值直接忽略而不是展开一个不存在的版本。

### 3.5 删除的 409：把英文契约翻成可执行的中文

后端 409 的体是**英文**（`services/lifecycle.py:133-138` / `:153-158`）：

```json
{"error": "version still has plans", "detail": {"plans": 3, "hint": "delete or archive its plans first"}}
{"error": "plan still has tickets", "detail": {"requirements": 5, "bugs": 2, "hint": "…"}}
```

`ui/ConfirmDialog.tsx:74-79` 的既有行为是：`onConfirm` 抛错时**不关闭对话框**，就地渲染
`err instanceof ApiError ? err.message : "操作失败，请重试"`。直接用会把 `version still has plans`
这句英文甩给用户。因此在 hook 的 `remove()` 里**就地翻译并重抛**（`ApiError` 可被 `new` 出来，
`lib/api.ts:48-59` 是普通导出类）：

```ts
// hooks/useVersions.ts
const remove = useCallback(async (versionId: number) => {
  try {
    await api.del(`/versions/${versionId}`);
  } catch (err) {
    // 409 的 detail 里带着「还有几个计划」——这正是用户下一步要做的事，必须原样呈现数字。
    if (err instanceof ApiError && err.status === 409) {
      const plans = (err.detail as { plans?: number } | undefined)?.plans ?? 0;
      // 【评审 P1-5】**只说「删除」，不说「或归档」**——见下方说明，归档不解除引用。
      throw new ApiError(409, `该版本下还有 ${plans} 个计划，请先删除这些计划。`, err.detail);
    }
    throw err;
  }
  settle();
}, [settle]);
```

计划侧同理：`该计划下还有 N 个需求、M 个 BUG，请先把它们移到其他计划或删除。`
（**这句不动**：移走或删除工单**确实**能让 `plan_references` 的计数下降。）

> **【评审 P1-5】翻译层的职责是说真话，不是把后端 hint 转成中文。**
> 后端版本 409 的 hint 逐字为 `"delete or archive its plans first"`（`lifecycle.py:137`），
> 但 `lifecycle.version_references`（`:126-130`）是
> `Plan.query.filter_by(version_id=version_id).count()`——**不看 `status`**。
> 归档的计划照样计数。用户照着「或归档」把计划一个个归档、再回来删版本，**仍然 409，
> 且那个数字一个都没少**：这是把人送进死循环，比甩一句英文更坏。
> 故本轮的中文**只保留「删除」这一条真的有效的出路**。
> 对照：计划侧的 `plan_references`（`:141-150`）同样不看状态，但它给的两条出路
> （移到其他计划 / 删除）都会真的让计数下降，所以那句照译无妨。
> **后端 hint 串本身的误导是上一轮的遗留，本轮不改后端契约**（§2.2 已登记）——
> 改它意味着动一个已被 `test_versions` 断言过的稳定错误体，那是独立一轮的事。

> **不要**把翻译写进 `ConfirmDialog`——那会让一个通用原语开始认识业务错误串。也**不要**只弹 toast：
> `ConfirmDialog.tsx:75` 的注释逐字写着「409（『还有 12 张单』）需要被读到的地方，弹一个转瞬即逝的
> toast 然后关窗是最差解」。

### 3.6 归档语义与「当前值必须可见」陷阱

归档不是独立动作，就是 `PATCH {status: "archived"}`。后端列表默认隐藏 `archived`
（`versions.py:77-79` / `plans.py:57-58`，`include_archived` 只认 `"1" | "true" | "yes"` 三个字面量）。

由此产生一个必须显式处理的陷阱：**一张工单归属的计划可能已被归档**，而 `PlanPicker` 的选项来自默认列表
（不含归档），于是 `<select>` 的 value 匹配不到任何 option，浏览器会静默显示第一项——用户会看到
「这张单归属计划 A」，而它其实归属已归档的计划 B。

**解法（与 `ProjectFormModal.tsx:44-52` 的 `ownerOptions` 同款手法：当前值恒保留）**：
`PlanPicker` 接收工单自带的只读 `plan: PlanContext | null`（后端已在每个序列化站点富化，
`services/hierarchy.py:127-143`），若其 `id` 不在选项列表里就把它**并入**选项并标注「（已归档）」。

### 3.7 权限门禁

后端写操作恒为 `@require_role("admin", "pm")`（`versions.py:87/128/170`、`plans.py:66/105/154`）。
前端沿用 `requirements/page.tsx:37` 与 `projects/page.tsx:34` 的既有判据：

```ts
const canManage = user?.role === "admin" || user?.role === "pm";
```

`member` 看得见整棵树与全部进度（读是 `@jwt_required()`），但看不到「新建 / 编辑 / 归档 / 删除」按钮。
**侧栏入口不做角色门禁**——本仓库从不靠隐藏导航做权限（`Sidebar.tsx:89-108` 只有 `is_root` 一处例外），
门禁一律在页面内以按钮可见性表达。

### 3.8 后端增量：批量「归属计划」

`services/bulk_ops.py` 的扩展点非常干净（`_ROLE_GATES:68` → `ACTIONS:77` → `_build_params:287` →
`_Runner._handler:249`），四处各加一小块即可：

```python
# 1) _ROLE_GATES(:68) 追加一行（放在 delete 之前，破坏性动作恒在最后）
#    值为 None = 不做粗粒度角色门禁，改由逐项 can_manage_ticket 裁决。
#    【评审 P1-2】**必须**是 None，不是 ("admin","pm")：plan_id 的单条写路径是
#    PATCH /api/{requirements,bugs}/<id>，其门禁为行级 can_manage_ticket
#    （routes/requirements.py:266），本模块 :20-23 的不变量逐字要求「门禁与单条端点
#    逐一对齐」。plan 与 priority/severity 同型（都是「把工单某字段设成某值」），故同门禁。
    "plan": None,

# 2) _build_params(:287) 在 `if action in ("priority","severity")` 之后追加分支
    if action == "plan":
        # 请求级参数：整批共用一个目标计划。
        # 【评审 P0-1】`plan_id` 键**必须显式存在**：缺键 → 400，而不是「当作解除归属」。
        # 理由有三：① 它复用的 hierarchy.resolve_plan_for_ticket 的契约是「无该键 → 不改」
        # （hierarchy.py:106-107），把缺键解释成「清空」会让本模块与它所复用的唯一判据打架；
        # ② 本模块既有先例是 assign / unassign **拆成两个 action**（:68-75），破坏性语义
        # 从不做缺省值；③ 一个漏传字段的客户端不该静默清空整批工单的归属。
        # 显式 `"plan_id": null` 仍然是解除归属——那是用户明确表达过的意图。
        if "plan_id" not in data:
            return None, (jsonify({"error": "plan_id is required",
                                   "detail": {"field": "plan_id",
                                              "expected": "an existing plan id, "
                                                          "or null to detach"}}), 400)
        if data.get("plan_id") is None:
            return {"plan": None}, None
        plan = db.session.get(Plan, want_int(data, "plan_id"))
        if plan is None:
            return None, (jsonify({"error": "plan_id is invalid",
                                   "detail": {"field": "plan_id",
                                              "expected": "an existing plan"}}), 400)
        return {"plan": plan}, None

# 3) _Runner 新增逐项方法（紧随 _do_level 之后）
    def _do_plan(self, ticket):
        """归属 / 解除归属到目标计划。跨项目是**逐项**失败（不同单可能属不同项目）。"""
        plan = self.params["plan"]
        target_id = plan.id if plan else None
        if not can_manage_ticket(self.user, ticket):
            return "failed", _fail(ticket.id, "forbidden",
                                   {"reason": f"cannot edit this {self.entity}"})
        if ticket.plan_id == target_id:
            return "skipped", _skip(ticket.id, "already in target plan")
        try:
            # 复用单条写路径的唯一判据（同项目不变量 / 无项目工单采纳计划项目），
            # 绝不在此内联第二份规则。ValidationError 在这里必须被**逐项**接住——
            # 让它冒到全局处理器会把整批变成一个 400，其余合法工单全被连坐。
            hierarchy.resolve_plan_for_ticket(ticket, {"plan_id": target_id})
        except ValidationError as exc:
            return "failed", _fail(ticket.id, exc.message,
                                   {"field": exc.field, "expected": exc.expected})
        Activity.log(self.entity, ticket.id, "updated", actor=self.actor,
                     to_status=ticket.status,
                     message=f"归属计划「{plan.name}」" if plan else "解除计划归属")
        return "succeeded", ticket.id

# 4) _handler(:250-257) 的字典追加
        "plan": self._do_plan,
```

**import 增量（评审 P1-1 更正）**——照抄 v1 那句会直接 `NameError`：

| 符号 | 现状 | 动作 |
|---|---|---|
| `Plan` | 未导入 | **新增** `from models.plan import Plan` |
| `hierarchy` | 未导入 | **新增** `from services import hierarchy`（现有行是 `from services import lifecycle, notifications, workflow`，就地加进去） |
| `want_int` | **未导入**（`:51` 只有 `ValidationError, want_str`） | **新增**：把 `:51` 改成 `from services.validation import ValidationError, want_int, want_str` |
| `ValidationError` | **已在 `:51`** | 不动（v1 误列为「需新增」） |
| `jsonify` / `db` | 已在 `:39` / `:41` | 不动 |

依赖方向无环：`bulk_ops → hierarchy → {models, workflow, scope, validation}`。

**不变量守住说明（评审 P2-9）**：`_do_plan` 是本模块第一个在逐项裁决中调用「共享写路径 helper」的
动作，而 `bulk_ops.py:11-13` 的免 SAVEPOINT 论证依赖「被判失败的单从未被写过」。经核实
`resolve_plan_for_ticket` 是**先校验后写入**（`hierarchy.py:112-122`：查计划 → 校验同项目 → 才赋值），
跨项目分支在**任何**字段被改动之前就抛出，故该不变量继续成立。若将来有人把校验挪到赋值之后，
这条论证就断了——改动那个函数时必须回头看这里。

**顺带写明一条被复用进来的语义（评审 P2-12）**：`resolve_plan_for_ticket` 对
**`project_id` 为 NULL 的工单会采纳计划的项目**（`hierarchy.py:119-121`）。这是单条写路径
的既定语义，批量复用它是对的——但后果值得写下来：一次「批量归属计划」可能**同时把 N 张
无项目工单搬进某个项目**。这不是 bug（那正是「让工单落进正确作用域」的设计意图），
但它是一次批量操作的**第二个副作用**，故 §8.1 用例 1 顺带断言这件事，
免得日后有人看到 `project_id` 变了以为是数据损坏。

**动作名用 `"plan"` 而不是 `"assign_plan"`**：与既有 `"priority"` / `"severity"`（也是「把某字段设成某值」）
的命名同型；`ACTIONS = tuple(_ROLE_GATES)`（`:77`）会自动带上它，`want_str(..., choices=ACTIONS)`
（`:326`）随之生效，无需第二处登记。

### 3.9 顺带修一个既有缺陷：`useTicket.patch` 会吞掉富化字段

`hooks/useTicket.ts:94-95` 用 PATCH 的返回体**整体覆盖** SWR 缓存。而后端 PATCH 工单走的是
`hierarchy.with_plan_context_one(...)`（`routes/requirements.py:294`），它由 `to_dict()` 构造，
**不含 `document_count`**（只有 GET 详情走 `attach_plan_context_one(document_counts.with_document_count(...))`
才有，`requirements.py:255-256`）。于是在抽屉里改一次标题，`ticket.document_count` 就变 `undefined`，
`TicketDrawer.tsx:262` 的 `documentCount` 归零，删除确认文案随之开始说假话。

这是**上一轮之前就存在**的缺陷，但本轮会把它的触发频率显著推高（用户将频繁在抽屉里改 `plan_id`）。
一行修复，语义严格更优：

```ts
// hooks/useTicket.ts:95 —— 由整体覆盖改为**合并**
// 后端 PATCH 返回体由 to_dict() 构造，不含 document_count 之类的序列化站点富化字段；
// 整体覆盖会把它们从缓存里抹掉（详情页徽章与删除确认文案随之说谎）。合并保留旧富化、
// 同时吃进新的 updated_at（乐观并发守卫仍然拿到新鲜时间戳）。
mutateTicket((prev) => ({ ...(prev ?? {}), ...updated } as Ticket), { revalidate: false });
```

---

## 4. 数据模型（Data model）

### 4.1 数据库

**本轮零 schema 变更。** 不新增表、不新增列，因此
**不触碰 `backend/services/schema_sync.py::ADDITIVE_COLUMNS`**（CLAUDE.md 的两步走硬约束在本轮无适用面）。
`versions` / `plans` 两张表与 `requirements.plan_id` / `bugs.plan_id` 两列均已在 `d766c88` 落地。
种子数据保持 10 行不变（写入方是 `backend/seed.py`；`SEED_VERSION = "3"` 的**声明处**是
`backend/models/seed_record.py:21`——评审 P2-8 更正），`tools/purge_demo_data.py` 亦无需再动。

### 4.2 前端类型（`frontend/lib/types.ts`）

追加在 `ProjectUpdate`（`:567`）之后、`DocumentKind`（`:581`）之前——即「工单域类型」与「文档域类型」
的接缝处。**命名注意**：本文件 `:591` 已有一个 `DocumentVersion`（文档改版，完全无关的概念），
新类型就叫 `Version` / `Plan`，注释里点明二者无关。

```ts
// —— version-plan-console：版本 / 计划（项目 → 版本 → 计划 → 需求/BUG 四层树的中间两层）——
// 注意：与本文件下方的 `DocumentVersion`（文档改版历史）是**完全不同的概念**，勿混。

/** 与后端 models/version.py:14 的 VERSION_STATUSES 逐字一致。 */
export type VersionStatus = "planning" | "active" | "released" | "archived";

/** 与后端 models/plan.py:13 的 PLAN_STATUSES 逐字一致。 */
export type PlanStatus = "planning" | "active" | "completed" | "archived";

export interface Version {
  id: number;
  project_id: number;
  name: string;
  description: string | null;
  status: VersionStatus;
  /** DATE，形如 "2026-08-01"，**无** Z 后缀（backend/models/version.py:58-60）。 */
  target_date: string | null;
  /** 服务端托管：随 status 进出 released 由后端 stamp / 清空，**前端永不发送**。 */
  released_at: string | null;
  owner_id: number | null;
  position: number;
  created_at: string;
  updated_at: string;
  /** 以下三项为列表 / 详情端点的富化字段（routes/versions.py:41-54），恒存在。 */
  plan_count: number;
  /** 该版本下**全部计划**名下的工单总数（后端两跳聚合，前端不得自行求和）。 */
  total_count: number;
  done_count: number;
}

export interface Plan {
  id: number;
  version_id: number;
  /** 反范式冗余，恒等于所属版本的 project_id（backend/models/plan.py:22-24）。 */
  project_id: number;
  name: string;
  description: string | null;
  status: PlanStatus;
  start_date: string | null;
  end_date: string | null;
  position: number;
  created_at: string;
  updated_at: string;
  /** 富化字段（routes/plans.py:28-39），恒存在。 */
  requirement_count: number;
  bug_count: number;
  done_count: number;
}

/** 工单上挂载的只读计划概要（services/hierarchy.py:142-143）。
 *  `version_name` 可为 null——版本行已不存在时的防御值。 */
export interface PlanContext {
  id: number;
  name: string;
  version_id: number;
  version_name: string | null;
}

/** POST /api/versions 的请求体。project_id 必填且创建后不可变。 */
export interface VersionCreate {
  name: string;
  project_id: number;
  description?: string;
  status?: VersionStatus;
  owner_id?: number | null;
  target_date?: string | null;
}

/** PATCH /api/versions/:id。**故意不含** project_id 与 released_at：
 *  前者被后端静默忽略（versions.py:159-160），后者服务端托管——把它们放进类型
 *  等于邀请调用方去发一个永远不生效的字段。 */
export interface VersionUpdate {
  name?: string;
  description?: string;
  status?: VersionStatus;
  owner_id?: number | null;
  target_date?: string | null;
  position?: number;
}

export interface PlanCreate {
  name: string;
  version_id: number;
  description?: string;
  status?: PlanStatus;
  start_date?: string | null;
  end_date?: string | null;
}

export interface PlanUpdate {
  name?: string;
  description?: string;
  status?: PlanStatus;
  start_date?: string | null;
  end_date?: string | null;
  /** 允许改挂版本，但必须同项目，否则后端 400（plans.py:135-139）。 */
  version_id?: number;
  position?: number;
}
```

同时修改三处既有类型：

```ts
// Requirement(:139) 与 Bug(:158) 各追加两个字段（放在 position 之前，与后端 to_dict 的键序对齐）
  /** 归属计划；未归属为 null。**必填**——它在 `to_dict()` 里，因而在每一个响应里都存在
   *  （backend/models/requirement.py 已核实）。 */
  plan_id: number | null;
  /** 只读层级概要，**仅在做了富化的序列化站点存在**（见下方说明），故为可选。
   *  plan_id 为 null 或指向已删计划时为 null；端点未富化时为 undefined。
   *  **消费侧一律按「缺省即无」渲染**：`ticket.plan ? … : "未归属"`，绝不写 `ticket.plan!.name`。 */
  plan?: PlanContext | null;

// BulkAction(:511) 追加一个成员（放在 severity 与 delete 之间）
  | "plan"

// BulkRequest(:520) 追加一个字段
  /** action=plan 的目标计划：`number` = 归属到该计划；`null` = 解除归属。
   *  **这个键必须显式存在——缺键是整批 400，不是「解除归属」**（§6.2 / 评审 P0-1）。
   *  语法上仍是可选（`BulkRequest` 是四种动作共用的一个宽结构，其他动作不带它），
   *  因而 `tsc` 兜不住漏传：**唯一调用点必须显式构造它**（评审 P1-9），见 §6.2 的调用形状。 */
  plan_id?: number | null;

// BulkFailure.detail(:536-541) 追加两个可选键（承载 ValidationError 的 field/expected）
    field?: string;
    expected?: string;
```

> **为什么 `plan_id` 必填、而 `plan` 可选（评审 P1-3 更正——v1 在这里论据是错的）**：
>
> - **`plan_id` 必填**是安全的：它在 `Requirement.to_dict()` / `Bug.to_dict()` 里，因而
>   **每一个**返回工单形状的端点都带着它，无一例外。
> - **`plan` 只能可选**。v1 声称它「在每一个工单序列化站点都已无条件富化」——**不成立**。
>   富化只发生在本轮关心的那几个站点（`requirements.py:194/246/255/294/475`、
>   `bugs.py:71/125/134/173`、`board_page.py:64-65`）；**至少 11 个站点仍返回裸 `to_dict()`**：
>   `requirements.py:332/354/389/421/559/608`、`bugs.py:191/212/246/274`、
>   `services/search.py:85-86`、`routes/me.py:64-69`。其中最后两个尤其要命——
>   `/api/search` 与 `/api/me/work` 的响应在前端**正是**被声明为 `Requirement[]` / `Bug[]`
>   （`types.ts:389-390` 的 `SearchResults`、`:370-371` 的 `MeWork`）。把 `plan` 声明为必填，
>   等于让类型系统对这两个真实存在的调用点说谎，而「typecheck 能兜住漏富化」恰恰是 v1
>   给出的唯一理由——那个理由在这里反过来打自己。
> - 因此采用 `document_count?: number`（`:153`）的既有先例：**渐进富化的字段一律可选**，
>   消费侧按缺省渲染。这不是妥协，而是把「不同端点富化程度不同」这个事实**如实**写进类型。
> - **本轮不顺手去富化那 11 个站点**：那会把「唯一的后端增量」从 1 处扩成 12 处，
>   且 `/search` / `/me/work` 的下拉与卡片本来就不展示计划。真需要时另起一轮，
>   届时把 `plan?` 收紧成 `plan` 是一次纯类型收窄，不破坏任何调用方。

### 4.3 状态配色（`frontend/lib/constants.ts`）

紧随 `SEVERITY_STYLES`（`:74`）之后追加。**必须**用穷尽的 `Record<VersionStatus, BadgeStyle>` 而非
`Record<string, BadgeStyle>`——这是 `NOTIFICATION_LABELS`（`:151`）与 `USER_ACTIVITY_LABELS`（`:341`）
两次踩坑后确立的做法：漏一个键就是编译错误，而不是界面上冒出一串英文原文。

```ts
// —— version-plan-console：版本 / 计划状态徽章 ——
// 色值全部取自既有明度基线（中性 / 蓝 / 绿），对比度 ≥ 4.5:1。
// `archived` 与 `planning` 同为中性，靠**更冷更深一档的底色 + 不同文案**区分——
// 归档是「收起来了」，不是「还没开始」，二者不可长得一样。

export const VERSION_STATUS_STYLES: Record<VersionStatus, BadgeStyle> = {
  planning: { label: "规划中", bg: "#EDEAE3", fg: "#6E6A62" },
  active:   { label: "进行中", bg: "#DCE7F2", fg: "#3B6EA5" },
  released: { label: "已发布", bg: "#D9EBDD", fg: "#3E7A4F" },
  archived: { label: "已归档", bg: "#E4E1DA", fg: "#5F5B54" },
};

export const PLAN_STATUS_STYLES: Record<PlanStatus, BadgeStyle> = {
  planning:  { label: "规划中", bg: "#EDEAE3", fg: "#6E6A62" },
  active:    { label: "进行中", bg: "#DCE7F2", fg: "#3B6EA5" },
  completed: { label: "已完成", bg: "#D9EBDD", fg: "#3E7A4F" },
  archived:  { label: "已归档", bg: "#E4E1DA", fg: "#5F5B54" },
};

/** 下拉选项从配色表派生（同 DOCUMENT_KIND_OPTIONS:238-242），确保文案永不分叉。 */
export const VERSION_STATUS_OPTIONS = (Object.keys(VERSION_STATUS_STYLES) as VersionStatus[])
  .map((k) => ({ value: k, label: VERSION_STATUS_STYLES[k].label }));

export const PLAN_STATUS_OPTIONS = (Object.keys(PLAN_STATUS_STYLES) as PlanStatus[])
  .map((k) => ({ value: k, label: PLAN_STATUS_STYLES[k].label }));
```

`lib/bulk.ts:20` 的 `BULK_ACTION_LABELS: Record<BulkAction, string>` 因为是穷尽 Record，
加了 `"plan"` 成员后**会编译失败直到补上标签**——正是我们要的：

```ts
  plan: "归属计划",
```

`lib/bulk.ts` 的 `skipText`（`:69`）追加一支：`case "already in target plan": return "本就归属该计划";`
`failureText`（`:48`）追加一支：`case "plan and ticket must be in the same project": return "该工单与目标计划不在同一个项目";`

**并新增第三个翻译函数（评审 P1-6）**——`failureText` / `skipText` 只服务**逐项三桶**，
够不着「整批 400」那条路径：

```ts
// lib/bulk.ts —— 与 failureText / skipText 并列声明
/** **请求级**错误（整批 400/403/404）→ 人话。与逐项三桶是两条不同的路径：
 *  三桶走 BulkResultDialog，本函数走 BulkToolbar.applyFromModal 的 toast。
 *
 *  **default 分支原样返回 `err.message`**，故对既有四个动作（assign/move/level/delete）
 *  **零行为变化**；这与 failureText「未知 error 原样透出，绝不吞掉后端说了什么」同款。 */
export function requestErrorText(err: unknown): string {
  if (!(err instanceof ApiError)) return "批量操作失败";
  switch (err.message) {
    case "plan_id is required":
      return "请先选择目标计划，或选择「解除归属」";
    case "plan_id is invalid":
      return "所选计划已不存在（可能刚被他人删除），请重新选择";
    default:
      return err.message;
  }
}
```

调用点是 `BulkToolbar.applyFromModal`（`:91`）那一行，把
`toast.error(err instanceof ApiError ? err.message : "批量操作失败")` 换成
`toast.error(requestErrorText(err))`——**一处改动覆盖全部动作**。

---

## 5. 文件 / 模块变更计划（File / module change plan）

> 图例：🆕 新建 · ✏️ 修改。行号引用为**改动落点**，实施时以当前文件为准。

### 5.1 后端（4 个文件）

| 文件 | 动作 | 一句话意图 |
|---|---|---|
| `backend/services/bulk_ops.py` | ✏️ | 四处（§3.8）：`_ROLE_GATES` 加 `"plan"`、`_build_params` 加请求级校验、`_Runner._do_plan`、`_handler` 注册；新增 3 个 import。**⚠️ 动手前先 `git diff backend/services/bulk_ops.py`（评审 P0-3）**：当前工作树里这四处**已经落了一半**——三个 import 与 `_ROLE_GATES["plan"] = None` 在，`_build_params` / `_do_plan` / `_handler` 三处**不在**。因为 `ACTIONS = tuple(_ROLE_GATES)`，这个半成品已经让 `action:"plan"` 通过校验并在 `_handler()` 撞 `KeyError` → **500**，而 `pytest` 全绿看不见它。**四处必须一次落全，不得再留半个**。 |
| `backend/tests/test_bulk_ops.py` | ✏️ | **八条**用例：批量归属 / 显式 null 解除 / 幂等跳过 / 跨项目逐项失败 / 非法 plan_id 400 / **行级权限（member 整体 200 且逐项分流）** / **缺 `plan_id` 键 → 400 且零改动** / **`ACTIONS` 与 `_handler()` 逐项对齐**（后三条分别为评审 P1-2、P0-1、P0-3 所加）。 |
| `backend/tests/test_requirements.py` | ✏️ | 一条守卫用例：PATCH 工单的响应体含 `plan` 且 `plan_id` 正确（配合 §3.9 的前端合并修复）。 |
| `docs/plans/version-plan-console/spec.md` | 🆕 | 本文件。 |

### 5.2 前端（数据与契约层，5 个文件）

| 文件 | 动作 | 一句话意图 |
|---|---|---|
| `frontend/lib/types.ts` | ✏️ | 加 `Version`/`Plan`/`PlanContext`/`VersionStatus`/`PlanStatus` + 四个 Create/Update；`Requirement`(`:139`)/`Bug`(`:158`) 加 `plan_id`/`plan`；`BulkAction`(`:511`)/`BulkRequest`(`:520`)/`BulkFailure`(`:536`) 三处增量。 |
| `frontend/lib/constants.ts` | ✏️ | 两张穷尽 `Record<…Status, BadgeStyle>` + 两个 OPTIONS（§4.3）。 |
| `frontend/lib/api.ts` | ✏️ | 加 `VERSIONS_PREFIX` / `PLANS_PREFIX` 两个**前缀**常量（§3.2，非 `*_KEY`）。 |
| `frontend/lib/swr-keys.ts` | ✏️ | ①`ADMIN_VIEW_PREFIXES`(`:27`) 追加 `/versions`、`/plans`；②**新增** `invalidateHierarchyViews`（§3.2 后一半，评审 P0-2）。**不动** `TICKET_VIEW_PREFIXES`(`:13`)。 |
| `frontend/lib/hierarchy.ts` | 🆕 | 级联筛选的纯逻辑单一真相，**也是 `HierarchyFilterValue` 的唯一声明处**（评审 P1-4）：`HierarchyFilterValue`、`isHierarchyParam`、`toHierarchyQuery(value)`、`plansOfVersion(plans, version)`、`nextValueOnVersionChange(...)`（§3.3 三条语义）。无 React 依赖，纯函数。 |

### 5.3 前端（hooks，4 个文件）

| 文件 | 动作 | 一句话意图 |
|---|---|---|
| `frontend/hooks/useVersions.ts` | 🆕 | 版本列表（filters + 分页）+ `create/update/remove`；`settle()` 同时调 `invalidateAdminViews`（版本/计划自身）与 `invalidateTicketViews`（工单侧的层级徽章与筛选下拉）（仿 `useDocumentLibrary.ts:53-58`）；`remove` 内翻译 409（§3.5）。 |
| `frontend/hooks/usePlans.ts` | 🆕 | 同型；另导出 `usePlansOfVersion(versionId \| null)` 供版本卡展开时懒加载（key 为 null 即不请求）。 |
| `frontend/hooks/useHierarchyOptions.ts` | 🆕 | 下拉数据源：按当前项目作用域取 `versions`/`plans`（`limit=200`），返回 `{versions, plans, versionsTruncated, plansTruncated, isLoading}`；截断标志由 `listFetcher` 的 `total > 200` 得出（§9 R-6）。 |
| `frontend/hooks/useTicket.ts` | ✏️ | `:95` 由整体覆盖改为合并（§3.9）。 |

### 5.4 前端（组件与页面，11 个文件）

| 文件 | 动作 | 一句话意图 |
|---|---|---|
| `frontend/app/(app)/versions/page.tsx` | 🆕 | 「版本 / 计划」控制台主页（§7.1）。骨架照抄 `app/(app)/projects/page.tsx`：角色门禁 → 弹窗状态三件套 → 数据 → `refresh()` → 四段渲染梯（`ErrorState`/`SkeletonRows`/`EmptyState`/正文）→ 底部弹窗群。 |
| `frontend/components/planning/VersionCard.tsx` | 🆕 | 可折叠版本卡：名称 + 状态徽章 + 目标日期 + 负责人 + 计划数 + 聚合进度条 + `⋯` 菜单；展开时渲染 `<VersionPlans>`。 |
| `frontend/components/planning/VersionPlans.tsx` | 🆕 | 展开后的计划列表容器（**独立组件 = 懒加载边界**，§3.4）：`usePlansOfVersion` + 空态 +「+ 新建计划」。 |
| `frontend/components/planning/PlanRow.tsx` | 🆕 | 单条计划行：名称 + 状态徽章 + 周期 + 需求/BUG 计数（同时是深链）+ 进度条 + 行内动作。 |
| `frontend/components/planning/VersionFormModal.tsx` | 🆕 | 版本增改弹窗，`state \| null` + `onSaved` 模式（照抄 `admin/ProjectFormModal.tsx:17-27,166-176` 的判别联合 + 双子组件 + `buildDiff` 三件套）。 |
| `frontend/components/planning/PlanFormModal.tsx` | 🆕 | 计划增改弹窗（父版本预填；编辑态可改挂同项目的其他版本）。 |
| `frontend/components/planning/HierarchySelects.tsx` | 🆕 | 受控级联双下拉（§3.3 语义）。样式复用 `FilterBar.tsx:42-43` 的 `selectCls` 字符串，供筛选条与看板页共用。 |
| `frontend/components/planning/PlanPicker.tsx` | 🆕 | **赋值**用的计划选择器（输出 `plan_id: number \| null`），含 §3.6 的「当前值恒可见」处理。 |
| `frontend/components/planning/PlanBadge.tsx` | 🆕 | 列表 / 看板卡上的计划徽章：`Badge` + `title="版本 · 计划"`；未归属渲染浅灰 `—`。 |
| `frontend/components/bulk/BulkPlanModal.tsx` | 🆕 | 批量归属计划弹窗（`PlanPicker` + 「解除归属」选项），形状照抄 `bulk/BulkLevelModal.tsx`：**只通过 `onConfirm(planId: number \| null)` 把值交出去，自己不发请求、不 catch**（评审 P1-6：既有三个批量弹窗都是这个形状，请求级错误由 `BulkToolbar.applyFromModal` 统一处理）。 |
| `frontend/components/layout/Sidebar.tsx` | ✏️ | `NAV`(`:34`) 在「需求」之前插入「版本」项（`href/label/match/icon` 四字段，图标用 18×18 内联 SVG）。 |

### 5.5 前端（把层级接进既有动线，11 个文件）

| 文件 | 动作 | 一句话意图 |
|---|---|---|
| `frontend/components/FilterBar.tsx` | ✏️ | `Props`(`:10-22`) 追加**一个可选对象属性** `hierarchy?`（缺省不渲染 → 既有调用点零改动）；`hasFilter`(`:39-40`) 与清空回调(`:94-99`) 各并入该维度。 |
| `frontend/app/(app)/requirements/page.tsx` | ✏️ | 两个筛选 state；**调 `useHierarchyOptions()` 取两个下拉的数据源**（评审 P2-15：v2 漏了这一句，它只在 §3.1 的数据流图里出现过）；mount 时读 `?version_id=`/`?plan_id=`(`:52-71` 内)；`listKey` 拼参(`:80-91`)；`filterSignature` 并入(`:98-99`)；表头(`:216-219`)与单元格(`:258-270`)旁加「计划」列；`FilterBar` 接 `hierarchy`；**建单回调 `onCreated`(`:326-329`) 内加 `invalidateHierarchyViews`**（评审 P0-2：新单可能带 `plan_id`，计划行的「需求 N」必须跟着变）。 |
| `frontend/app/(app)/bugs/page.tsx` | ✏️ | 与上完全同构（该页是需求页的镜像）。 |
| `frontend/app/(app)/requirements/board/page.tsx` | ✏️ | 看板顶部渲染 `<HierarchySelects>`，值透传给 `useBoard`。 |
| `frontend/app/(app)/bugs/board/page.tsx` | ✏️ | 同上。 |
| `frontend/hooks/useBoard.ts` | ✏️ | 签名加第三参 `hierarchy?: HierarchyFilterValue`（**从 `lib/hierarchy.ts` `import type`**，评审 P1-4），key(`:23-24`) 拼 `version_id`/`plan_id`；`move()` 里重取用的 `key`(`:118`) 自动跟随，无需另改；**第一段 `api.patch` 成功之后（`:114` 之后、第二段之前）加 `invalidateHierarchyViews`**（评审 P0-2 + **P1-7 更正落点**：v2 写的是「第二段重取成功后(`:119`)」，但第二段失败会走 `:120-123` 的 catch，那时写入**已经成功**却永远执行不到 `:119`，进度就此永久陈旧）。需在 hook 内取 `useSWRConfig().mutate` 作全局 mutate。 |
| `frontend/components/TicketDrawer.tsx` | ✏️ | 详情区在 `AssigneePicker`(`:398`) 与元信息行(`:400-416`) 之间插入「计划」`PlanPicker`（`disabled={!canManage}`——此处 `canManage` 是 `:147` 的**行级**判据 `canManageTicket(user, ticket)`，与后端 `PATCH /:id` 的门禁一致，**不要**换成 §3.7 那个 admin｜pm 判据）；元信息行的「项目：」之后追加「版本 · 计划」面包屑。**失效落点是三处，不是一处（评审 P0-4）**：①新增的 `onPlanChange()`（形状照抄 `onLevelChange:222-228`）在 `await patch({plan_id})` 成功后调 `invalidateHierarchyViews`；②`onDelete()` 的 `:190` 旁加一行（删单同时改分子分母）；③`onAdvance()`（`:156-166`）成功后加一行（Agent 推进可能把单推进终态）。**`:190` 在 `onDelete` 里，它不是「改状态/改归属」的落点**——v2 在这里锚错了函数。 |
| `frontend/components/bulk/BulkToolbar.tsx` | ✏️ | `BulkMode` 加 `"plan"`；`actions`(`:61-66`) 在「改级别」与「删除」之间插入 `{ key: "plan", label: "归属计划" }`——**不带 `requiresManage`**（评审 P1-2：后端 `_ROLE_GATES["plan"]` 为 `None`，逐项 `can_manage_ticket` 裁决，与既有 `move`/`level` 同型）；挂 `<BulkPlanModal>`；`apply()`(`:70-84`) 内 `onDone()` 之后加 `invalidateHierarchyViews`（评审 P0-2）；`applyFromModal`(`:91`) 的 toast 改用 `requestErrorText(err)`（评审 P1-6，§4.3 末给出实现）。 |
| `frontend/components/requirements/RequirementForm.tsx` / `bugs/BugForm.tsx` | ✏️ | 在项目 `Select`(`:105-114`) 之后加 `PlanPicker`；提交体带 `plan_id`（未选则省略，`undefined` 经 `JSON.stringify` 自动丢弃，与 `:57-58` 既有注释的处理一致）。 |
| `frontend/lib/bulk.ts` | ✏️ | **四处**：`BULK_ACTION_LABELS`(`:20`) 加 `plan`；`skipText`(`:69`)/`failureText`(`:48`) 各加一支；**新增 `requestErrorText(err)`** 承接「整批 400」的中文化（§4.3 末，评审 P1-6——这条路径 `failureText`/`skipText` 够不着）。 |

---

## 6. 接口设计（Interface design）

### 6.1 既有 REST 契约（as-built，前端照此编码，**本轮不改**）

所有列表返回**裸数组** + `X-Total-Count` 头；错误体恒 `{error, detail?}`。

| 方法 / 路径 | 鉴权 | 关键参数 / 返回 |
|---|---|---|
| `GET /api/versions` | `jwt_required` | `?project_id=<int\|none>` `?status=<∈VERSION_STATUSES>` `?include_archived=1\|true\|yes` `?limit=<1..200>` `?offset=`；项含 `plan_count`/`total_count`/`done_count` |
| `POST /api/versions` | `admin\|pm` | `{name*, project_id*, description?, status?, owner_id?, target_date?}` → `201`；project 不存在 → `400 {"error":"project not found"}`；owner 不存在 → `400 {"error":"owner not found"}` |
| `GET /api/versions/<id>` | `jwt_required` | `200` / `404 {"error":"version not found"}` |
| `PATCH /api/versions/<id>` | `admin\|pm` | 可改 `name/description/status/target_date/owner_id/position`；`project_id`、`released_at` **被忽略**；无可改字段 → `400 {"error":"no updatable field"}` |
| `DELETE /api/versions/<id>` | `admin\|pm` | `204`；有计划 → `409 {"error":"version still has plans","detail":{"plans":n,"hint":…}}`（**无 `allowed` 键**） |
| `GET /api/plans` | `jwt_required` | `?project_id=` `?version_id=<int>`（**不接受 `none`**）`?status=` `?include_archived=` `?limit=` `?offset=`；项含 `requirement_count`/`bug_count`/`done_count` |
| `POST /api/plans` | `admin\|pm` | `{name*, version_id*, description?, status?, start_date?, end_date?}` → `201`；`project_id` 由版本推导，**不接受客户端传值**；版本不存在 → `400 {"error":"version not found"}` |
| `PATCH /api/plans/<id>` | `admin\|pm` | 可改 `name/description/status/start_date/end_date/version_id/position`；改挂到**不存在**的版本 → `400 {"error":"version not found"}`（`plans.py:133-134`，评审 P2-13 补齐）；改挂**跨项目**版本 → `400 {"error":"plan and version must be in the same project","detail":{"field":"version_id"}}` |
| `DELETE /api/plans/<id>` | `admin\|pm` | `204`；有工单 → `409 {"error":"plan still has tickets","detail":{"requirements":n,"bugs":m,"hint":…}}` |
| `GET /api/requirements` · `GET /api/bugs` | `jwt_required` | 新增可选 `?version_id=<int\|none>` `?plan_id=<int\|none>`（与既有筛选 AND 叠加）；项含 `plan_id` 与只读 `plan` |
| `POST` / `PATCH` 工单 | 既有 | 体可选 `plan_id`（`int` 归属 / `null` 解除）；非法 → `400 {"error":"plan_id is invalid","detail":{"field":"plan_id","expected":"an existing plan"}}`；跨项目 → `400 {"error":"plan and ticket must be in the same project",…}` |
| `GET /api/board/<entity>` | `jwt_required` | 新增可选 `?version_id=` `?plan_id=`；卡片含 `plan` |

**日期字段一律 `YYYY-MM-DD` 且无 `Z`** → 表单用 `<input type="date">`，**不要**照抄
`admin/AuditFilterBar.tsx` 的 `datetime-local` 写法。

### 6.2 本轮唯一的接口增量

```
POST /api/requirements/bulk   |  POST /api/bugs/bulk
Body: { "ids": number[], "action": "plan", "plan_id": number | null }   ← plan_id 键必填
鉴权: jwt_required；**无请求级角色门禁**（_ROLE_GATES["plan"] = None），
      逐项走 can_manage_ticket——与单条 PATCH /:id 的门禁一致（评审 P1-2）
```

- **`plan_id` 键必须存在**（评审 P0-1）：
  - `"plan_id": <int>` ⇒ 批量归属到该计划；
  - `"plan_id": null` ⇒ 批量**解除**归属（这是用户明确表达过的意图）；
  - **缺键 ⇒ 整批 400**，`{"error":"plan_id is required","detail":{"field":"plan_id",
    "expected":"an existing plan id, or null to detach"}}`。
    v1 把缺键定义成「解除归属」，那会让一个漏传字段的客户端静默清空整批归属，
    且与 `hierarchy.resolve_plan_for_ticket`「无该键 → 不改」的契约（`hierarchy.py:106-107`）直接打架。
- 其余请求级错误（整批 400）：`plan_id` 非整数 / 超界（`want_int`）；计划不存在 →
  `{"error":"plan_id is invalid","detail":{"field":"plan_id","expected":"an existing plan"}}`。
- 逐项结果沿用既有三桶契约（`succeeded` / `skipped` / `failed`）：
  - `skipped`：`{"id":n,"reason":"already in target plan"}`
  - `failed`：`{"id":n,"error":"forbidden","detail":{"reason":"cannot edit this requirement"}}` 或
    `{"id":n,"error":"plan and ticket must be in the same project","detail":{"field":"plan_id","expected":…}}`
- **响应仍是 200**——批量端点的既有约定是「整批参数错才 400，逐项问题进三桶」。

> **请求级 400 的前端呈现（评审 P2-6，落点经 P1-6 更正）**：这两条整批 400 走的是
> `BulkToolbar.applyFromModal` 的 `toast.error(err.message)`（`BulkToolbar.tsx:91`），
> 会把 `plan_id is invalid` 这句英文契约串原样甩给用户。`lib/bulk.ts` 的
> `failureText`/`skipText` **只服务逐项三桶**，够不着这里。
>
> **翻译必须落在 `BulkToolbar.applyFromModal`，不能落在 `BulkPlanModal`**（评审 P1-6）：
> 既有三个批量弹窗（`BulkAssignModal` / `BulkStatusModal` / `BulkLevelModal`）都只通过
> `onConfirm` 把值交出去，**发请求与 catch 全在 `BulkToolbar` 里**——弹窗组件在调用栈上
> 根本看不到那个 `ApiError`，v2 让它「就地翻译」是一句实现不了的话。
> 正确做法见 §4.3 末的 `requestErrorText(err)`：`plan_id is invalid` → 「所选计划已不存在
>（可能刚被他人删除），请重新选择」；`plan_id is required` → 「请先选择目标计划，
> 或选择「解除归属」」；**其余原样透出**，故既有四个动作零行为变化。

**调用形状（评审 P1-9，必须显式构造 `plan_id` 键）**：

```ts
// BulkToolbar.tsx —— <BulkPlanModal onConfirm={…}>
onConfirm={(planId: number | null) =>
  // 显式写出这个键。`plan_id: planId ?? undefined` 之类的"顺手简化"会让
  // 「解除归属」退化成缺键 → 整批 400（§6.2），正是 P0-1 要防的那个客户端。
  void applyFromModal({ action: "plan", plan_id: planId })}
```

### 6.3 前端组件接口（本轮的「公共 API」）

```ts
// lib/hierarchy.ts —— HierarchyFilterValue 的**唯一**声明处（评审 P1-4）
// 每个字段的取值域：""=不过滤 | "none"=未归属 | "<正整数>"=具体 id
export interface HierarchyFilterValue { version: string; plan: string; }

// components/planning/HierarchySelects.tsx —— 受控级联，无内部数据请求
// **只 import type，不再重复声明**：hooks/useBoard.ts 也要用这个类型，
// 让 hook 反向依赖一个 "use client" 组件是层级倒置。
import type { HierarchyFilterValue } from "@/lib/hierarchy";

interface HierarchySelectsProps {
  value: HierarchyFilterValue;
  onChange: (next: HierarchyFilterValue) => void;
  versions: Version[];
  plans: Plan[];
  /** 数据未就绪时把两个 select 置灰（仿 ProjectSwitcher.tsx:22-28，不用骨架）。 */
  loading?: boolean;
}

// components/planning/PlanPicker.tsx —— 赋值用；自带数据（useHierarchyOptions）
interface PlanPickerProps {
  /** 当前归属的计划 id；null = 未归属。 */
  value: number | null;
  onChange: (planId: number | null) => void;
  /** 工单自带的只读概要：用于「当前值恒可见」（§3.6）与初始版本推断。 */
  context?: PlanContext | null;
  /** 限定到某项目（建单表单已选项目时传入）；缺省用全局作用域。 */
  projectId?: number | null;
  disabled?: boolean;
  label?: string;
}

// components/FilterBar.tsx —— 追加的**唯一**可选属性
  hierarchy?: {
    value: HierarchyFilterValue;
    onChange: (next: HierarchyFilterValue) => void;
    versions: Version[];
    plans: Plan[];
    loading?: boolean;
  };
```

> **为什么是一个对象属性而不是 6 个标量属性**：`FilterBar` 的 `Props`（`:10-22`）现在已有 11 个字段；
> 再摊平 6 个会让它逼近可读上限，且「这 6 个要么全给要么全不给」的耦合关系会丢失。
> 一个可选对象把「这是一个可选的整块能力」表达得刚好。

---

## 7. 界面与交互设计（UI/UX）

### 7.1 `/versions` 控制台

```
┌───────────────────────────────────────────────────────────────────────────┐
│ 版本 / 计划          共 3 个版本 · ARA · AragonTeam        [+ 新建版本]    │  ← Header
├───────────────────────────────────────────────────────────────────────────┤
│ [全部状态 ▾] [☐ 显示已归档]                                     [清空]     │  ← 轻量筛选条
│                                                                           │
│ ┌───────────────────────────────────────────────────────────────────┐     │
│ │ ▾  v1.0 首个可用版本   〔进行中〕   目标 2026-08-01   👤 Ada    ⋯ │     │  ← 版本卡（展开）
│ │    ████████████░░░░░░░░  8 / 12 已完成 · 3 个计划                 │     │
│ │  ┌─────────────────────────────────────────────────────────────┐  │     │
│ │  │ 迭代 1：打通主流程 〔进行中〕 07-01 ~ 07-14                  │  │     │  ← 计划行
│ │  │ ██████████████████░░  5/6   需求 4 · BUG 2      [编辑][⋯]   │  │     │
│ │  ├─────────────────────────────────────────────────────────────┤  │     │
│ │  │ 迭代 2：Agent 自动化 〔规划中〕 07-15 ~ 07-28               │  │     │
│ │  │ ░░░░░░░░░░░░░░░░░░░░  暂无工单                 [编辑][⋯]   │  │     │
│ │  └─────────────────────────────────────────────────────────────┘  │     │
│ │                                              [+ 在此版本下新建计划] │     │
│ └───────────────────────────────────────────────────────────────────┘     │
│ ┌───────────────────────────────────────────────────────────────────┐     │
│ │ ▸  v0.9 内测版本      〔已发布〕  发布于 2026-06-20  👤 —      ⋯ │     │  ← 折叠态
│ │    ████████████████████  20 / 20 已完成 · 2 个计划                │     │
│ └───────────────────────────────────────────────────────────────────┘     │
│                                                          ‹ 1 / 1 ›        │
└───────────────────────────────────────────────────────────────────────────┘
```

**逐条实现要点：**

- **容器**沿用全站卡片惯用法：`rounded-xl border border-border bg-surface shadow-card`
  （`requirements/page.tsx:185`、`projects/page.tsx:86` 同款）。版本卡之间 `space-y-3`。
- **折叠交互**：整个卡头是一个 `<button aria-expanded aria-controls>`，箭头 `▸/▾` 用 CSS `rotate-90`
  过渡。键盘可达（`Enter`/`Space`）。展开态在页面级 `Set<number>` 中；折叠即卸载 `<VersionPlans>`。
- **进度条**：`ui/ProgressBar`，**必须显式传 `label`**——它的默认 `aria-label` 是「上传进度」
  （`ProgressBar.tsx:22`），规划场景照抄会让读屏播报一句莫名其妙的话。传
  `label={`版本进度 ${done_count}/${total_count}`}`。
  **`total_count === 0` 时不渲染进度条**，改渲染一行 `text-ink-muted` 的「暂无工单」——
  给 `value={null}` 会进入 ProgressBar 的**不确定模式**（脉冲动画，`:15-16,33`），
  那语义是「还在传但不知道剩多少」，与「这里一张单都没有」南辕北辙。
- **⋯ 菜单**（版本 / 计划共用形状）：编辑 · 归档（status→archived，已归档则显示「取消归档」→ planning）·
  删除（danger）。仅 `canManage` 渲染。菜单用一个受控的绝对定位 `<div>`（本仓库无 Dropdown 原语，
  参考 `layout/Header.tsx` 的头像菜单写法），`Esc` 与失焦关闭。
- **归档之后不能让它凭空消失（评审 P2-16）**：后端列表默认隐藏 `archived`
  （`versions.py:77-79` / `plans.py:57-58`），所以「点归档 → 列表刷新 → 卡片当场蒸发」是默认行为，
  用户完全不知道东西去哪了，而「显示已归档」勾选框此刻可能还是灰的（见下条 P2-1）。
  **做法**：归档成功后**自动把「显示已归档」勾上**（若「状态」下拉选了具体值则先把它清空），
  再 `toast.success("已归档；已为你打开「显示已归档」")`。这样卡片留在原位、徽章变成「已归档」，
  「取消归档」就在同一个 ⋯ 菜单里——**归档是一个可逆动作，它的 UI 也必须看起来可逆**。
- **删除**：`ui/ConfirmDialog`，`description` 写清后果与范围；命中 409 时对话框保持打开并内联展示
  §3.5 翻译后的中文（`ConfirmDialog.tsx:120-124` 的既有错误块）。版本删除**不要求键入确认串**
  （它不像删项目那样级联毁灭数据，且非空时本就被 409 挡住）。
- **加载 / 空 / 错误**四段梯照抄 `projects/page.tsx:87-164`：
  `ErrorState(message="无法加载版本列表", onRetry)` → `SkeletonRows(rows=4)` → `EmptyState` → 正文。
- **空态文案分三种情形**（这是本页最容易做敷衍的地方）：
  1. 当前作用域是「未归属项目」→ 标题「版本必须归属一个项目」，提示「请在顶部切换到一个具体项目后再
     新建版本」，**不显示新建按钮**。理由：`versions.project_id` 是 NOT NULL，
     `?project_id=none` 的查询恒为空集（§9 R-3）。
  2. 有项目、无版本、`canManage` → 标题「还没有版本」，提示「先建一个版本，再在它下面排计划，
     最后把需求 / BUG 挂到计划上」，`action` 为「+ 新建版本」。
  3. 有项目、无版本、`member` → 同标题，提示改为「版本由项目经理或管理员创建」，无 action。
- **筛选条**：只有「状态」下拉与「显示已归档」勾选（`ui/Checkbox`），不复用 `FilterBar`
  （那是工单列表的形状，硬塞会把它变成一个什么都做的组件）。
  **两个控件会互相抵消，必须显式处理（评审 P2-1）**：后端是
  `if status: … elif include_archived …`（`versions.py:74-79`、`plans.py:54-58`），
  即**一旦选了具体状态，`include_archived` 完全不起作用**。故选中任一具体状态时，
  把勾选框 `disabled` 并给 `title="已按具体状态筛选，归档与否由该状态决定"`——
  一个点了没反应的控件就是在对用户说谎，本仓库对此有反复的先例警告。
- **版本卡上的负责人名字（评审 P2-2）**：`Version.to_dict()` **只回 `owner_id`，没有 owner 概要**
  （`models/version.py` 已核实）。名字由页面级的 `useSWR<User[]>(USERS_KEY)` 就地映射，
  做法与 `projects/page.tsx:33` 完全一致（该页也是拿 `USERS_KEY` 渲染项目负责人）。
  **映射不中时渲染 `—` 而不是 id**：一个裸数字对用户没有任何意义。
- **「全部项目」作用域下必须显示项目归属（评审 P2-3）**：`scope === null` 时
  `?project_id=` 被省略，列表会混排多个项目的版本，而两个项目各有一个「v1.0」是常态。
  此时（且**仅此时**）在版本卡标题右侧渲染一枚项目徽章（`project_id` → `PROJECTS_KEY` 映射取 `key`），
  已选定具体项目时不渲染（那是屏幕上的噪音，顶部 `scopeLabel` 已经说过一遍了）。
- **分页**：`ui/Pagination`（`total <= limit` 时自渲染为空，无需条件包裹）。
- **计数即深链**：计划行的「需求 4」「BUG 2」分别是
  `<Link href="/requirements?plan_id=<id>&project_id=<plan.project_id>">` 与同款的 `/bugs?…`；
  版本卡头的「3 个计划」不是链接（它就在下面）。
  **必须带 `project_id`（评审 P2-10）**：工单列表页的项目作用域来自全局 `ProjectSwitcher`，
  在「全部项目」视图里点了项目 B 的计划、而当前作用域停在项目 A，落地后两个条件 AND
  起来就是空表——用户会以为「刚才明明写着 4 条需求，怎么一条都没有」。深链既然知道
  计划属于哪个项目，就该把作用域一起带过去。接收侧见 §3.3。

### 7.2 新建 / 编辑弹窗

`VersionFormModal`：名称\*、描述、状态、**项目**（仅 create 态可选，默认取当前作用域；edit 态以只读文本
显示并附一句「版本创建后不可更换项目」）、负责人（选项来自 `USERS_KEY`，
**当前负责人恒保留**——照抄 `ProjectFormModal.tsx:44-52` 的 `ownerOptions`）、目标日期
（`<input type="date">`）。**没有 `released_at` 输入**。

`PlanFormModal`：名称\*、描述、状态、**所属版本**（create 态由父版本预填；edit 态可改挂，
选项**只列同项目版本**——前端先过滤能把 400 挡在提交前，但**不能因此省掉**对后端 400 的错误提示，
因为并发下版本可能刚被改）、开始 / 结束日期。

两者都实现 `buildDiff()`（`ProjectFormModal.tsx:123-138`）：只提交变化字段，空 diff 就地
`toast.info("没有需要保存的改动")`，不发那个必然 400 的请求。

### 7.3 需求 / BUG 列表

- 筛选条尾部（指派人之后、清空之前）多出两个 `<select>`：`全部版本 ▾` `全部计划 ▾`，
  样式与既有 select 完全一致（复用 `FilterBar.tsx:42-43` 的 `selectCls`）。
- 「全部版本」下拉的选项：`全部版本` / `未归属版本` / 各版本名（已归档版本默认不在其中）。
- 表格在「文档」列之前插入「计划」列：`<PlanBadge plan={r.plan} />`——`Badge` 展示 `plan.name`，
  `title` 属性为 `` `${plan.version_name ?? "—"} · ${plan.name}` ``；`plan` 为 null 时渲染
  `<span className="text-ink-muted/50">—</span>`（与文档列 `:267-269` 的未命中态同款）。
- **三处必须同步扩展**（漏一处就是隐性 bug）：`listKey` 的参数拼装、`filterSignature`
  （否则筛完停在 offset=50 看到空表）、以及经由 `filterSignature` 传入 `useBulkSelection`
  的选择作用域（否则动作栏上的数字与屏幕上的行对不上）。

### 7.4 看板

看板页目前**没有筛选条**。本轮在看板标题下方加一行 `<HierarchySelects>`（同一个组件，无 FilterBar），
值透传给 `useBoard(entity, scope, hierarchy)`。看板卡右下角加一枚小号 `PlanBadge`
（`kanban/KanbanCard.tsx`，与既有回形针徽章并排）。

### 7.5 工单抽屉

- 在 `AssigneePicker`（`:398`）之后插入 `<PlanPicker label="计划" value={ticket.plan_id}
  context={ticket.plan} onChange={…} disabled={!canManage} />`，变更即
  `patch({ plan_id })`（`null` = 解除）。
- 错误分流沿用 `handleWriteError`（`:195-203`）：跨项目 400 的中文来自后端，`toast.error(err.message)`
  即可（`failureText` 那套翻译只服务批量结果弹窗，不要在这里再搭一层）。
- 元信息行（`:400-416`）「项目：」之后追加：`版本 · 计划：{plan ? `${plan.version_name ?? "—"} · ${plan.name}` : "未归属"}`，
  让四层归属一眼可见。

### 7.6 可访问性与一致性清单

- 所有 `<select>`/`<input>` 走 `ui/` 原语（自带 `useId` 关联 label，`Select.tsx:18-21`）；
  在 `FilterBar` 内部因样式一致性使用裸 `<select>` 时，**必须**像既有代码那样给 `aria-label`
  （`FilterBar.tsx:67,79`）。
- 折叠按钮 `aria-expanded` / `aria-controls`；进度条显式 `label`；⋯ 菜单 `aria-haspopup="menu"`。
- 颜色语义全站统一：中性=未开始、蓝=进行中、绿=已完成/已发布、冷灰=已归档。
- 徽章对比度 ≥ 4.5:1（沿用既有明度基线，§4.3）。
- 侧栏「版本」图标用「层叠 / 分支」意象的 18×18 内联 SVG，`strokeWidth 1.8`，与 `Icon`
  （`Sidebar.tsx:17-32`）同风格。

---

## 8. 测试与验收标准（Testing & acceptance criteria）

### 8.1 后端（`backend/tests/`，pytest，真实集成测试）

**先取基线**：`python -m pytest -q --collect-only` 记下 N₀，收工时用例数必须 ≥ N₀ 且零失败。
禁止 mock 数据库与鉴权（CLAUDE.md 七）。

`backend/tests/test_bulk_ops.py` 追加（照抄同文件既有用例的 fixture 用法）：

1. `test_bulk_plan_assigns_all_selected_tickets` —— 建版本 + 计划 + 3 张同项目需求 →
   `POST /requirements/bulk {action:"plan", plan_id:P}` → `200`，`counts.succeeded == 3`，
   三张单的 `plan_id == P`，且响应 `action == "plan"`。
   **顺带断言 `project_id` 的采纳语义（评审 P2-12）**：再放一张 `project_id IS NULL` 的需求进同一批，
   断言它成功后 `project_id == plan.project_id`——这是 `resolve_plan_for_ticket`（`hierarchy.py:119-121`）
   的既定行为被批量复用后的**第二个副作用**，写进用例免得日后被当成数据损坏。
2. `test_bulk_plan_null_detaches` —— 已归属的 2 张 → `{action:"plan", plan_id: null}` →
   `succeeded == 2`，`plan_id is None`。**显式 `null` 才解除归属**。
3. `test_bulk_plan_skips_tickets_already_in_target_plan` —— 其中一张本就归属 P →
   进 `skipped` 桶，`reason == "already in target plan"`，且**不写第二条 activity**。
4. `test_bulk_plan_fails_per_item_on_cross_project` —— 一张属项目 A、一张属项目 B，目标计划在 A →
   **整体仍是 200**，A 的进 `succeeded`、B 的进 `failed` 且
   `error == "plan and ticket must be in the same project"`、`detail.field == "plan_id"`。
   **这是本组最重要的一条**：它守住「ValidationError 被逐项接住而不是冒成整批 400」（§3.8）。
5. `test_bulk_plan_rejects_unknown_plan` —— `plan_id` 指向不存在的计划 → 整批 `400`，
   `error == "plan_id is invalid"`。
6. `test_bulk_plan_uses_row_level_permission`（**评审 P1-2 改写**，原为「member → 403」）——
   以 `member` 身份提交两张单：一张是他自己报的（`reporter_id` 为他）、一张与他无关。
   → **整体 200**（无请求级角色门禁）；前者进 `succeeded` 且 `plan_id` 已改，
   后者进 `failed` 且 `error == "forbidden"`。这条钉死的是「批量门禁 == 单条 `PATCH /:id` 门禁」
   这一 `bulk_ops.py:20-23` 的模块不变量，**而不是**一个更严的角色墙。
7. `test_bulk_plan_requires_explicit_plan_id`（**评审 P0-1 新增**）——
   `{action:"plan"}`（**不带 `plan_id` 键**）→ 整批 `400`，`error == "plan_id is required"`，
   且**事后逐张核对：没有任何一张单的 `plan_id` 被改动**。
   这条是本组的**破坏性防线**：它挡住「一个漏传字段静默清空整批归属」。
8. `test_every_bulk_action_has_a_handler`（**评审 P0-3 新增，本组唯一一条结构性用例**）——
   不打 HTTP，直接断言 `set(bulk_ops.ACTIONS) == set(_Runner(…)._handler().keys())`
   （或逐个 `action` 构造一次 `_Runner` 并断言 `_handler()` 不抛 `KeyError`）。
   **它守的是「半落地」这一类事故**：`ACTIONS = tuple(_ROLE_GATES)`（`bulk_ops.py:84`）意味着
   **往 `_ROLE_GATES` 里加一行就等于对外公开了一个新动作**；若 `_handler()` 忘了注册，
   该动作会一路通过 `want_str(choices=ACTIONS)` 与角色门禁，最后在 `_handler()` 撞
   `KeyError` → **500**，而现有 33 条批量用例没有一条会碰到它。
   本轮的 `plan` 就是它的第一个受害者（评审 P0-3：当前工作树里正躺着这样一个半成品），
   下一个动作还会踩。**这条用例一旦存在，那类事故就再也过不了门禁。**

`backend/tests/test_requirements.py` 追加 1 条：
`test_patch_response_carries_plan_context` —— PATCH 改标题后响应体仍含 `plan_id` 与 `plan`
（守住 §3.9 前端合并修复所依赖的契约）。

> **注意这条用例守的是 `PATCH /:id` 这一个端点，不是全体端点**（评审 P1-3）：
> `/api/search`、`/api/me/work`、`/:id/move`、`/:id/assign` 等站点**确实**不富化 `plan`，
> 那是**已知且被接受**的现状，不要为了让类型「好看」而顺手改它们（那是另一轮的范围）。

### 8.2 前端

- `npm run typecheck`（`tsc --noEmit`）0 error；`npm run build` 成功。这是 CLAUDE.md 规定的前端门禁，
  **本仓库没有前端测试运行器**（`frontend/tests/` 下只有一个品牌资源校验脚本），所以类型系统就是唯一的
  自动化护栏——这也正是 §4.3 坚持用穷尽 `Record<Union, …>` 的原因：
  漏一个状态键会**编译失败**，而不是在界面上冒出英文。
- 逐条自查：`VERSION_STATUS_STYLES` / `PLAN_STATUS_STYLES` / `BULK_ACTION_LABELS` 三张穷尽表全覆盖；
  `Requirement`/`Bug` 新增 `plan_id`（**必填**）后，所有构造这两个类型的桩 / mock 均已补上该字段。
- **`plan` 是可选字段（评审 P1-3），typecheck 兜不住它**——这是本轮唯一一处「类型系统帮不上忙」的地方，
  故列为**人工自查项**：全仓库搜 `.plan`，确认每个消费点都写成 `x.plan ? … : …` 或 `x.plan?.name`，
  **没有一处 `x.plan!.` 或 `x.plan.`**。`/api/search`、`/api/me/work` 的响应里它确实是 `undefined`。

### 8.3 验收清单（Definition of Done，功能维度，逐条手测）

1. **建树**：在 `/versions` 建一个版本 → 在其下建两个计划 → 在需求页新建一张需求并预选计划 →
   该需求出现在计划行的「需求 N」计数里，点进去能筛出它。
2. **管理**：版本与计划都能改名 / 改状态 / 改日期 / 归档 / 取消归档；版本能改负责人；
   计划能改挂到同项目的另一个版本；改挂到别项目的版本被中文提示挡住。
3. **筛选**：需求列表、BUG 列表、需求看板、BUG 看板四处都能按版本、按计划筛；
   「未归属版本」能单独筛出 `plan_id IS NULL` 的单；选了具体版本后计划下拉只剩该版本的计划。
4. **进度**：把某计划下最后一张需求推进 `done` → 回到 `/versions`，该计划进度条与所属版本的聚合进度
   **同时**上涨（验证 §3.2 的双向失效）。**§3.2 落点表的六行，每一行都要亲手走一遍**——
   只要有一行不动，就是 `invalidateHierarchyViews` 漏挂了那个调用点。
   （评审 P1-8 更正：v2 这里写的是「① 抽屉里改状态」，**但抽屉根本没有状态控件**——
   `TicketDrawer.tsx:318` 只把 `status` 渲染成一枚只读 `Badge`；v2 还断言「抽屉是三条里唯一
   本来就能工作的」，那句话叠加评审 P0-4 后**两个半句都不成立**。按下表重做。）

   **改分子（把工单推进终态）的三条路径**：
   - ④ **看板拖拽**：在需求看板上把最后一张卡拖进 `done` 列 → 回 `/versions` 看进度。
     *（这条是最主流的路径，也是 v1 方案下必然失败的那条。）*
   - ⑤ **批量「流转状态」**：列表页勾选 → 「流转状态」→ `done` → 回 `/versions` 看进度。
   - ③ **Agent 推进**：把单指派给一个 Agent → 抽屉里「Agent 推进」→ 回 `/versions` 看进度。
     *（这是抽屉里唯一能改状态的入口，`onAdvance:156`。）*

   **改分母（改变归属）的三条路径**：
   - ① **抽屉里改归属**：抽屉的 `PlanPicker` 换一个计划 → `/versions` 上**两个**计划的
     「需求 N」一减一增。
   - ⑤ **批量「归属计划」**：同上，一次改多张。
   - ⑥ **建单**：在需求页新建一张预选了计划的需求 → 该计划的「需求 N」立刻 +1。
   - ② **删单**：抽屉里删掉一张已归属的需求 → 该计划的「需求 N」立刻 -1。
5. **删除守卫**：删非空版本 → 对话框保持打开并显示「该版本下还有 N 个计划，请先**删除**这些计划。」；
   删非空计划 → 显示需求 / BUG 两个数字。清空后再删成功。
   **额外验一条（评审 P1-5）**：把该版本下的计划全部**归档**（而不是删除）后再删版本 →
   仍然 409，且数字**一个都没少**。这正是文案里绝不能出现「或归档」的原因；
   若你在界面上看到了「或归档」，说明有人照着后端的英文 hint 又译了一遍。
6. **批量**：在需求列表勾选 3 张（其中 1 张属别的项目）→「归属计划」→ toast 报「成功 2 · 失败 1」，
   结果弹窗里那 1 条写着「该工单与目标计划不在同一个项目」。
7. **权限**（评审 P1-2 改写）：以 `member` 登录 →
   ① `/versions` 页：侧栏仍有「版本」入口，树与进度**完全可读**，但没有任何新建 / 编辑 / 归档 / 删除按钮
   （版本与计划的写操作后端确为 `admin|pm`）；
   ② 工单侧：**「归属计划」按钮可见且可用**——因为归属计划是工单写操作，门禁与单条
   `PATCH /:id` 一致（行级 `can_manage_ticket`）。对他自己报的单操作成功，对无关的单在结果详单里
   显示「你没有权限操作这张单」。抽屉里的 `PlanPicker` 同理：自己的单可改，别人的单置灰。
   **「一张一张改得动、一次改多张就 403」是不可接受的**，这正是本条要防的。
8. **向后兼容**：一个 `plan_id` 全为 NULL 的存量库，列表 / 看板 / 抽屉一切照旧，
   「计划」列整列显示 `—`，筛选默认不生效。
9. **门禁**：`pytest -q` 零失败且用例数 ≥ N₀；`npm run typecheck` + `npm run build` 通过。

---

## 9. 风险与缓解（Risks & mitigations）

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R-1 | **`ValidationError` 在批量里冒到全局处理器** | 一张跨项目的单让**整批** 400，其余合法工单全被连坐，用户看到「什么都没发生」 | §3.8 `_do_plan` 内 `try/except ValidationError` 逐项接住；§8.1 用例 4 是本轮**最重要**的一条测试 |
| R-2 | **失效只做了一半 / 挂错了地方**（评审 P0-2 重写，P0-4 + P1-7 再次更正） | 「推完最后一张单，版本进度不动」——而且**恰恰在最主流的看板拖拽路径上**。三层坑叠在一起：①`invalidateTicketViews` 的前缀表里没有版本/计划；②它的现网调用点根本不含 `useBoard.move` / `BulkToolbar.apply` / 建单回调；③抽屉里那个唯一的调用点在 **`onDelete`** 里，不是改归属的路径 | §3.2 分两半：`ADMIN_VIEW_PREFIXES` 扩前缀（版本/计划自身变了）+ **新增 `invalidateHierarchyViews` 并挂到 §3.2 落点表的 6 个工单写入点**（工单变了），每一行**按宿主函数点名而不是按行号**；拖拽那一行挂在**第一段写入成功后**而非第二段重取后（P1-7）；§5.5 逐行登记；§8.3 第 4 条手测**六条路径逐一走完** |
| R-3 | **作用域为「未归属项目」时版本页恒空** | `versions.project_id` NOT NULL ⇒ `?project_id=none` 查询恒为空集，用户看到空页却不知为何 | §7.1 空态情形 1：换一套文案并**隐藏新建按钮**，把「不可能有」说成人话 |
| R-4 | **归档的计划在选择器里消失，导致工单归属被静默改错** | 用户以为在确认现状，实际把 `plan_id` 改成了列表第一项 | §3.6「当前值恒可见」：`PlanPicker` 把 `context` 并入选项并标「（已归档）」（同 `ownerOptions` 先例） |
| R-5 | **`ProgressBar` 的 `value={null}` 被当成 0%** | 「暂无工单」的计划显示一条脉冲动画，读屏播报「进度未知 · 上传进度」 | §7.1：`total === 0` 时**不渲染进度条**；一律显式传 `label` |
| R-6 | **`limit=200` 静默截断下拉** | 项目里计划超过 200 个时，下拉少了选项而界面毫无提示 | `useHierarchyOptions` 用 `listFetcher` 拿 `total`，`total > 200` 时在下拉下方渲染一行灰字提示「仅显示前 200 个，请用状态筛选缩小范围」——**绝不静默截断** |
| R-7 | **`FilterBar` 改动波及既有两个调用点** | 需求 / BUG 现有筛选回归 | 只加**一个可选对象属性**，缺省不渲染；`hasFilter` 与清空回调各并入一行；typecheck 兜底 |
| R-8 | **级联的三条边界语义漏实现** | 「版本=未归属 + 计划=某个」这类组合永远返回空集，用户以为数据丢了 | §3.3 表格逐条列出；`lib/hierarchy.ts` 收敛为纯函数，两个列表页 + 两个看板页共用一份判据 |
| R-9 | **深链参数未做白名单** | `/requirements?plan_id=abc` 在筛选条里显示一个假筛选（后端会 400，但 UI 已经先说了谎） | `isHierarchyParam` 白名单（正整数或 `none`），照抄 `requirements/page.tsx:62` 对 `?status=` 的既有守卫 |
| R-10 | **`useTicket.patch` 合并改动引入新问题** | 若后端某天真的要「删除某字段」，合并会保留旧值 | 后端 `to_dict()` 恒返回全部列，字段只增不减；§8.1 追加的契约用例守住这一点 |
| R-11 | **版本 / 计划被顺手接进 `activities` / 通知** | 撕开 `TICKET_ENTITY_TYPES` 隔离，治理事件与工单事件互相泄漏进仪表盘 | §2.2 明确非目标；后端只写结构化日志（`versions.py:28,113,180`），本轮前端不新增任何 activity 消费点 |
| R-12 | **`versions/page.tsx` 一口气写成一个巨型文件** | 触 CLAUDE.md 二的 800 行 / 50 行红线 | §5.4 预先把页面拆成 `VersionCard` / `VersionPlans` / `PlanRow` / 两个 Modal 五个组件，页面本体只做「取数 → 编排 → 弹窗挂载」 |
| R-13 | **展开所有版本导致 N+1 请求** | 20 张卡全展开 = 20 个 `/plans` 请求 | §3.4 懒加载边界（折叠即卸载）+ 默认全部折叠；SWR 对同 key 有去重与缓存，重复展开不重发 |
| R-14 | **`bulk_ops.py` 的四处扩展点被落成"半个"**（评审 P0-3，**这不是假设，工作树里现在就是这个状态**） | `ACTIONS = tuple(_ROLE_GATES)` 让「加一行门禁」等于「对外公开一个新动作」；`_handler()` 忘了注册 → 任何登录用户发 `action:"plan"` 即 **500**，而 `pytest -q` **实测 872 例全过、退出码 0**，门禁完全看不见 | §5.1 要求动手前先 `git diff backend/services/bulk_ops.py` 认清半成品边界、四处一次落全；**§8.1 用例 8 `test_every_bulk_action_has_a_handler` 把这一类事故永久钉死**（遍历 `ACTIONS` 断言每个动作都有处理器），下一个新动作也受它保护 |
| R-15 | **归档后对象从列表凭空消失**（评审 P2-16） | 后端默认隐藏 `archived`，用户点完「归档」眼看着卡片蒸发，且此刻「显示已归档」可能还是灰的（P2-1），会以为自己误删了 | §7.1：归档成功后**自动勾上「显示已归档」**（必要时先清空「状态」下拉）并 toast 说明；卡片留在原位、徽章变「已归档」、「取消归档」就在同一个菜单里——可逆的动作必须看起来可逆 |

---

## 10. 落地顺序（实施 checklist）

0. **先取基线**：`cd backend; python -m pytest -q --collect-only`，记下 N₀。
   （评审当日现场读数为 **872**，仅供对照——**必须自己重取**，CLAUDE.md 明令不得信任写死的数字。）
1. **契约层**：`types.ts` → `constants.ts` → `api.ts` → `swr-keys.ts`（**扩 `ADMIN_VIEW_PREFIXES`
   + 新增 `invalidateHierarchyViews`，不动 `TICKET_VIEW_PREFIXES`**，§3.2）→ 新建 `lib/hierarchy.ts`
   （含 `HierarchyFilterValue` 的唯一声明）。此时 `npm run typecheck` 应当报出
   「`BULK_ACTION_LABELS` 缺 `plan` 键」等**预期中的**编译错误，逐个补齐。
2. **hooks**：`useVersions` / `usePlans` / `useHierarchyOptions`；顺手改 `useTicket.ts:95`（§3.9）。
3. **控制台页**：`Sidebar` 入口 → `versions/page.tsx` → `VersionCard` / `VersionPlans` / `PlanRow` →
   `VersionFormModal` / `PlanFormModal`。跑一次 `npm run dev` 手测 §8.3 第 1、2、5 条。
4. **接进动线**：`HierarchySelects` / `PlanPicker` / `PlanBadge` → `FilterBar` 可选槽 →
   需求页 / BUG 页（`useHierarchyOptions` + listKey + signature + 列 + 深链读取 + 建单回调挂失效）
   → `useBoard` + 两个看板页（**`move` 的第一段写入成功后挂 `invalidateHierarchyViews`，
   不是第二段重取后**，评审 P1-7）→ `TicketDrawer`（**三处**：新增的 `onPlanChange`、
   `onDelete:190`、`onAdvance:156`——**不是只在 `:190` 加一行**，评审 P0-4）→ 两个建单表单。
   手测 §8.3 第 3、8 条，并**照第 4 条的落点表把六条路径逐一验一遍**。
5. **后端增量**：**先 `git diff backend/services/bulk_ops.py` 看清工作树里已有的半成品**
   （评审 P0-3：三个 import 与 `_ROLE_GATES["plan"] = None` 已在，其余三处不在），
   再把 `bulk_ops.py` 的四处**一次落全**（含 §3.8 更正后的 import 清单）
   + `test_bulk_ops.py` **八条**（第 8 条 `test_every_bulk_action_has_a_handler` 会在你漏掉
   `_handler` 注册时立刻变红）+ `test_requirements.py` 一条。跑 `pytest -q`，对照 N₀。
6. **前端批量出口**：`lib/bulk.ts` **四处**（含新增的 `requestErrorText`，§4.3 末）→
   `BulkPlanModal`（**只发 `onConfirm`，不自己 catch**，评审 P1-6）→
   `BulkToolbar`（动作项**不带 `requiresManage`**；`apply` 后挂失效；
   `applyFromModal:91` 改用 `requestErrorText`）。手测 §8.3 第 6 条。
7. **收口**：`npm run typecheck` + `npm run build`；执行 §8.2 那条**人工自查**（全仓库搜 `.plan` 的
   非空断言）；以 `member` 账号跑一遍 §8.3 第 7 条（注意它现在要求「归属计划可用」而非「被藏起来」）；
   用一个 `plan_id` 全 NULL 的旧库跑一遍第 8 条。

> **若时间不足需要砍**：唯一可延后的是**第 5、6 步（批量归属计划）**——它是独立的一块，
> 砍掉不影响 1~4 步的任何交付，只是让存量项目的采纳成本变高。**不要**从第 4 步里砍，
> 那会让「界面上对应的需求和 BUG 也能够正确分类和筛选」这句需求落空。

---

## 附：本轮与上一轮 spec 的三处刻意分歧

1. **不加 `VERSIONS_KEY` / `PLANS_KEY` 字面量常量**（上一轮 §5.2 建议加）。改为
   `VERSIONS_PREFIX` / `PLANS_PREFIX`，理由见 §3.2：版本 / 计划的下拉必须带项目作用域，
   固定字面量做不到，且 `lib/api.ts:41-45` 已经为这种情况立过规矩。
2. **`total === 0` 时不画进度条**（上一轮 §7.1 写的是 `value = total ? … : 0`）。理由见 §7.1：
   `ProgressBar` 的 `null` 是「不确定」语义，`0` 又与「0% 完成」混淆，而「一张单都没有」是第三种事实，
   应当用文字说清楚。
3. **409 就地翻译成中文再抛**（上一轮 §7.1 写的是「把后端 detail 原样呈现」）。理由见 §3.5：
   后端 `error` 串是英文契约（给机器看的稳定标识），原样呈现等于把契约字符串当文案用。
   翻译发生在 hook 层，`ConfirmDialog` 这个通用原语不必认识任何业务错误串。

---

## 评审结论（Review Verdict）

### 第二轮结论（v3，**当前生效**）：**有条件通过**（Approved with conditions）

第一轮的判断**予以维持**：方向正确、范围恰当、可以开工。第二轮没有推翻任何一条设计决策——
四层树的取数策略、懒加载边界、「当前值恒可见」、`ProgressBar` 的 `null` 语义辨析、
把唯一后端增量收敛到「批量归属计划」一处，这些**全部复核成立**。

第二轮的价值不在于挑设计的毛病，而在于**验证第一轮的"已修"是不是真的修好了**——
结论是：**六条里有三条没修对**（P0-4 落点锚在了 `onDelete` 上、P1-5 把一句做不到的建议译成了中文、
P1-6 把翻译放在了一个拿不到错误的组件里），另有两条第一轮**自己留下的自相矛盾**
（P1-9 的类型注释、P1-7 的失效时机）。加上一条现场状况（P0-3：工作树里躺着一个可被外部触发
成 500 的半成品），**2 个 P0 + 5 个 P1 已在 v3 逐条就地修复**。

这件事本身值得记一笔：**第一轮的每一条"已修"都只是一个待验证的断言**。
本轮找到的 5 个问题里有 3 个就藏在第一轮的修复动作里，而它们全都长得像"已经处理过了"。

放行附带以下条件——它们不是建议，是合并前必须成立的判据：

#### 条件一：五条「防回退」的判据必须在代码里立住

1. **`test_bulk_plan_requires_explicit_plan_id`（§8.1-7）必须存在且为红→绿**。
   它挡的是「漏传一个字段 → 静默清空整批工单归属」这类不可逆的数据损坏。
   实现时若发现该用例难写，说明 `_build_params` 的缺键分支又被写回了「当作解除归属」。
   **配套**：§4.2 里 `plan_id` 的注释与 §6.2 的调用形状必须同时落地（评审 P1-9）——
   契约写对了、类型注释还在说反话，下一个人照着注释写客户端仍然会中招。
2. **`test_bulk_plan_uses_row_level_permission`（§8.1-6）必须断言整体 200 而非 403**。
   `bulk_ops.py:20-23` 的「门禁与单条端点逐一对齐」是这个模块存在的理由之一，
   一旦为了省事把 `plan` 设成 `("admin","pm")`，下一个动作也会照抄，模块不变量就此瓦解。
3. **`test_every_bulk_action_has_a_handler`（§8.1-8）必须存在**（评审 P0-3 新增）。
   这是本轮唯一一条**结构性**用例，也是唯一能挡住「半落地」的东西：
   `ACTIONS = tuple(_ROLE_GATES)` 让「加一行门禁」等于「对外公开一个新动作」，
   而现有 33 条批量用例没有一条会碰到未注册的动作。
   **动手前先 `git diff backend/services/bulk_ops.py`**——那个半成品现在就在工作树里。
4. **§8.3 第 4 条必须把 §3.2 落点表的六行逐一走完**（评审 P0-4 + P1-8）。
   第一轮那句「抽屉恰是三条里唯一本来就能工作的」**两个半句都不成立**：
   抽屉里 `invalidateTicketViews` 只挂在 `onDelete` 上，而抽屉**根本没有状态控件**。
   只测一条路径等于没测。
5. **删非空版本的中文里不得出现「或归档」**（评审 P1-5）。
   `version_references` 不看 `status`，归档不解除引用；照着后端 hint 译一遍
   就是把用户送进死循环。验收时按 §8.3-5 亲手试一次「全部归档后再删」。

#### 条件二：两处「类型系统兜不住」的地方必须人工过一遍

6. **`plan` 是可选字段**（`plan?: PlanContext | null`），`tsc` 不会替你检查任何一个消费点。
   合并前按 §8.2 全仓库搜一次 `.plan`，确认没有非空断言。若实现中发现某个页面**确实**需要
   `plan` 恒存在，正确的做法是**去后端补富化**并把它写进契约，而不是在类型里许一个空头承诺。
   （第二轮补验：`plan_id` 标必填是**安全**的——看板卡片与 `/api/search` 都走完整 `to_dict()`。）
7. **抽屉里的 `canManage` 是行级判据**（`TicketDrawer.tsx:147` 的 `canManageTicket`），
   **`/versions` 页的 `canManage` 是 admin｜pm**（§3.7）。两处同名不同义，
   §7.5 与 §3.7 相邻阅读时极易串。实现时确认 `PlanPicker` 在抽屉里拿到的是前者。

#### 条件三：四项已知偏差保持「已知」，不得在本轮顺手动手

8. `/api/search`、`/api/me/work` 等 11 个站点不富化 `plan` —— **本轮不修**（§8.1 末已登记）。
9. `PATCH /api/plans/<id> {version_id}` 改挂版本不重算 `position`（P2-7）—— **本轮不修**，
   已在 §2.2 登记为上一轮遗留，防止下一轮误判为本轮回归。
10. **后端 409 hint 串 `"delete or archive its plans first"` 本身是错的**（P1-5 的另一半）
    —— **本轮不改后端契约**，只在前端翻译层说真话。已在 §2.2 登记。
11. 版本 / 计划**不进** `activities` / 通知 / 全局搜索（§2.2 + R-11）—— 这条来自上一轮的
    `TICKET_ENTITY_TYPES` 隔离决策，本轮前端**不得**新增任何 activity 消费点。

#### 门禁（沿用 CLAUDE.md，不得放宽）

- 后端：**先取 N₀**（`pytest -q --collect-only`），收工时**零失败且用例数 ≥ N₀**。
  **第二轮当日重测仍为 872**（与第一轮读数一致），**该数字只用于对照，不得写进代码或回抄**。
  新增用例预期 **+9**（`test_bulk_ops.py` 8 条 + `test_requirements.py` 1 条）。
- 前端：`npm run typecheck` 0 error + `npm run build` 成功。
- 状态机神圣不可绕过：本轮**没有任何**新的状态迁移路径，`_do_plan` 只改 `plan_id`，
  不碰 `status`、不调 `next_position`——若实现中出现这两者，说明范围跑偏了。
- 本轮**零 schema 变更**，故 `schema_sync.py::ADDITIVE_COLUMNS` 不应出现在改动清单里；
  一旦它被改动，就意味着有人偷偷加了列，须回到设计评审。
- **`git status` 收工自查**：改动清单应当恰为 §5 的 30 个文件（后端 4 + 前端 26）。
  `backend/services/bulk_ops.py` 已在工作树里被动过——收工时它必须是**四处全落**的状态，
  不能再是现在这个半成品。

#### 若时间不足

§10 的可砍项判断**予以确认**：可延后第 5、6 步（批量归属计划），它是独立的一块。
但**砍掉批量的同时，条件一的第 1、2、3 条随之失效，必须在恢复该功能的那一轮重新执行**。
**注意一个新增的前提（评审 P0-3）**：砍掉第 5 步**不等于什么都不做**——工作树里那半个
`bulk_ops.py` 必须**回滚干净**（`git checkout -- backend/services/bulk_ops.py`），
否则留下的就是一个对外公开、一打就 500 的动作。**「砍掉」意味着回到零，不是停在一半。**
不得从第 4 步里砍——那会让产品需求原文「界面上对应的需求和 BUG 也能够正确分类和筛选」落空。

---

### 第一轮结论（v2，**存档**）：有条件通过

> 以下为第一轮评审的原文，保留以便对照。**其中三条已被第二轮更正**：
> 条件一-3 那句「抽屉恰是三条里唯一本来就能工作的」不成立（P0-4 / P1-8）；
> 「新增用例预期 +8」现为 +9（P0-3 加了一条）；
> 正文里 `versions.py:156` / `plans.py:142` 两处行号各差一行（P2-14，不影响结论）。

本设计**方向正确、范围恰当、可以开工**。它准确识别出上一轮「接口就绪 ≠ 功能完成」的缺口，
把交付定义在「让已存在的四层树变成人能用的界面」这件正确的事情上；§2.2 的五条非目标各自都有
经得起回源的理由（尤其「后端没有 reindex 端点所以不做拖拽排序」——`versions.py:156`/`plans.py:142`
确为裸赋值），没有为了显得完整而摊大摊子；把唯一的后端增量收敛到「批量归属计划」一处，
并说明了「不做它则存量项目采纳成本过高」，这是**右尺寸**的判断而不是妥协。
§3.4 的懒加载边界、§3.6 的「当前值恒可见」、§7.1 对 `ProgressBar` `null` 语义的辨析、
§3.9 对 `useTicket.patch` 既有缺陷的顺带诊断，都是踩过坑才写得出来的内容。

**2 个 P0 与 4 个 P1 已在本轮（v2）逐条就地修复**，文档主体现在与代码库的实际状态一致。
放行附带以下条件——它们不是建议，是合并前必须成立的判据：

#### （存档）条件一：三条「防回退」的判据必须在代码里立住

1. **`test_bulk_plan_requires_explicit_plan_id`（§8.1-7）必须存在且为红→绿**。
   它挡的是「漏传一个字段 → 静默清空整批工单归属」这类不可逆的数据损坏。
   实现时若发现该用例难写，说明 `_build_params` 的缺键分支又被写回了「当作解除归属」。
2. **`test_bulk_plan_uses_row_level_permission`（§8.1-6）必须断言整体 200 而非 403**。
   `bulk_ops.py:20-23` 的「门禁与单条端点逐一对齐」是这个模块存在的理由之一，
   一旦为了省事把 `plan` 设成 `("admin","pm")`，下一个动作也会照抄，模块不变量就此瓦解。
3. **§8.3 第 4 条必须走完抽屉 / 看板拖拽 / 批量三条路径**。只测抽屉等于没测——
   抽屉恰是三条里唯一在 v1 方案下本来就能工作的那条。

#### （存档）条件二：两处「类型系统兜不住」的地方必须人工过一遍

4. **`plan` 是可选字段**（`plan?: PlanContext | null`），`tsc` 不会替你检查任何一个消费点。
   合并前按 §8.2 全仓库搜一次 `.plan`，确认没有非空断言。若实现中发现某个页面**确实**需要
   `plan` 恒存在，正确的做法是**去后端补富化**并把它写进契约，而不是在类型里许一个空头承诺。
5. **抽屉里的 `canManage` 是行级判据**（`TicketDrawer.tsx:147` 的 `canManageTicket`），
   **`/versions` 页的 `canManage` 是 admin｜pm**（§3.7）。两处同名不同义，
   §7.5 与 §3.7 相邻阅读时极易串。实现时确认 `PlanPicker` 在抽屉里拿到的是前者。

#### （存档）条件三：三项已知偏差保持「已知」，不得在本轮顺手动手

6. `/api/search`、`/api/me/work` 等 11 个站点不富化 `plan` —— **本轮不修**（§8.1 末已登记）。
7. `PATCH /api/plans/<id> {version_id}` 改挂版本不重算 `position`（P2-7）—— **本轮不修**，
   已在 §2.2 登记为上一轮遗留，防止下一轮误判为本轮回归。
8. 版本 / 计划**不进** `activities` / 通知 / 全局搜索（§2.2 + R-11）—— 这条来自上一轮的
   `TICKET_ENTITY_TYPES` 隔离决策，本轮前端**不得**新增任何 activity 消费点。

#### （存档）门禁（沿用 CLAUDE.md，不得放宽）

- 后端：**先取 N₀**（`pytest -q --collect-only`），收工时**零失败且用例数 ≥ N₀**。
  评审当日现场读数为 872，**该数字只用于对照，不得写进代码或回抄**。
  新增用例预期 +8（`test_bulk_ops.py` 7 条 + `test_requirements.py` 1 条）。
- 前端：`npm run typecheck` 0 error + `npm run build` 成功。
- 状态机神圣不可绕过：本轮**没有任何**新的状态迁移路径，`_do_plan` 只改 `plan_id`，
  不碰 `status`、不调 `next_position`——若实现中出现这两者，说明范围跑偏了。
- 本轮**零 schema 变更**，故 `schema_sync.py::ADDITIVE_COLUMNS` 不应出现在改动清单里；
  一旦它被改动，就意味着有人偷偷加了列，须回到设计评审。

#### （存档）若时间不足

§10 的可砍项判断**予以确认**：可延后第 5、6 步（批量归属计划），它是独立的一块。
但**砍掉批量的同时，条件一的第 1、2 条随之失效，必须在恢复该功能的那一轮重新执行**。
不得从第 4 步里砍——那会让产品需求原文「界面上对应的需求和 BUG 也能够正确分类和筛选」落空。

---

## 实施过程发现的方案缺陷（Issues Found During Implementation）

> 记录人：实施者 · 2026-07-22 · 对象：v3（1533 行）
> 下列各条都是**在照着 v3 落地时撞上的**，不是重新评审。每条都写明「方案怎么说的 /
> 实际是什么 / 本轮怎么做的」。**方案的方向与全部 P0/P1 结论均成立**——包括 P0-3
> 那个半成品：动手前 `git diff backend/services/bulk_ops.py` 实测确为「三个 import +
> `_ROLE_GATES["plan"] = None` 已在，`_build_params` / `_do_plan` / `_handler` 三处不在」，
> 与 v3 的描述逐字一致；本轮已四处一次落全。
> **实测基线 N₀ = 872**（`python -m pytest -q --collect-only` 逐文件求和，49 个文件），
> 与两轮评审的读数一致。

### I-1（**必须偏离**）：`/plans?status=` 与版本状态枚举不是同一个集合，照 §7.1 直传会 **400**

**方案怎么说的**：§7.1 的筛选条只有「状态」下拉与「显示已归档」勾选，且（本轮实现把）
两级用同一套判据——版本卡与它下面的计划行都该受这两个控件约束。

**实际是什么**：`VERSION_STATUSES = (planning, active, **released**, archived)`，
`PLAN_STATUSES = (planning, active, **completed**, archived)`——两个枚举**各有一个对方没有的成员**。
而 `routes/plans.py:54` 是 `want_query_str("status", choices=PLAN_STATUSES)`，
`scope.want_query_str` 对不在 `choices` 内的取值**抛 `QueryParamError` → 400**（不是「筛不出东西」）。
于是「在版本页选『已发布』」会让每一张展开的版本卡的计划请求**整个 400**。

**本轮怎么做的**：`hooks/usePlans.ts::usePlansOfVersion` 只透传两个枚举的**交集**
（`status in PLAN_STATUS_STYLES` 才发），其余按「不筛状态」处理并回落到 `include_archived`。
判据写在 hook 里而不是页面里——`/plans` 的契约由它持有。

### I-2（**清单遗漏**）：§5.5 的表格漏了 `kanban/KanbanCard.tsx`

§7.4 正文明确要求「看板卡右下角加一枚小号 `PlanBadge`（`kanban/KanbanCard.tsx`，
与既有回形针徽章并排）」，但 §5.5 的 11 行文件表里**没有这一行**。文末门禁又说
「改动清单应当恰为 §5 的 30 个文件」——照那个数字去核对 `git status` 会把一个
**方案正文要求的**改动误判成越界。本轮按 §7.4 正文实现，文件数因此 +1。

### I-3（**新增一个文件**）：⋯ 菜单需要一个落点

§7.1 写「⋯ 菜单（版本 / 计划**共用形状**）……`Esc` 与失焦关闭」，但 §5.4 没有给它文件。
版本卡与计划行各写一份，就是两套 Esc / 失焦 / `aria-haspopup` 逻辑，改一处忘一处是必然
（本仓库没有 Dropdown 原语可复用）。本轮新增 `components/planning/RowMenu.tsx`（~90 行），
写法照抄 `layout/Header.tsx` 的头像菜单并补 Esc 关闭。**这是本轮唯一一个计划外的新文件**，
它不引入任何依赖，也不属于 §5.4 明令「本轮不新增任何 UI 原语」的 `components/ui/` 范围。

### I-4（**方案未言明，按既有先例补齐**）：看板加了筛选行之后的高度收敛

§7.4 只说「在看板标题下方加一行 `<HierarchySelects>`」。但两个看板页的 `<main>` 原本是
`flex-1 overflow-hidden`，而 `KanbanBoard` 根节点是 `h-full`——直接在其上方插一行会让看板
高出一整行的距离并把底部截掉。本轮把 `<main>` 改为 `flex flex-col`，看板包一层
`min-h-0 flex-1`。**纯布局收敛，不改看板任何行为**。

### I-5（**登记，不改**）：`PlanPicker` 的 `id` 必须走 `useId`

§6.3 给的 `PlanPickerProps` 没有 `id`，而该组件会**同时**出现在抽屉、建单弹窗、批量弹窗里。
写死一个字面量 `id` 会造出重复 DOM id（点标签聚焦到错误的控件）。本轮按 `ui/Select.tsx`
的既有做法用 `useId()`。记在这里是因为 §7.6 的 a11y 清单只说了「走 `ui/` 原语就自带
`useId` 关联」——而 `PlanPicker` 为了「当前值恒可见」用的是裸 `<select>`，那条豁免对它不成立。

### I-6（**新增一个文件**）：`lib/types.ts` 加完会越过 800 行硬阈值

**方案怎么说的**：§4.2 要求把 `Version` / `Plan` / `PlanContext` + 四个 Create/Update
（共 7 个类型）**追加进 `lib/types.ts`**，位置在 `ProjectUpdate` 之后、`DocumentKind` 之前。

**实际是什么**：`lib/types.ts` 落地前是 708 行，这 7 个类型连注释约 100 行 → **825 行**。
`.claude-index/config.md` 记的是 `MAX_FILE_LINES: 800`（strict 预设 ∩ Python 语言最小值），
CLAUDE.md 对该规则的处置逐字是「**超过即按职责拆分到新模块**」，且阈值的任何放宽
**必须**先写进 `.claude-index/config.md`。把注释压到极限也只能到 825——差的不是措辞。

**本轮怎么做的**：把这 7 个类型整体搬进新文件 `frontend/lib/planning-types.ts`，
并在 §4.2 指定的那个接缝处放一行 `export * from "@/lib/planning-types";`。
于是：① `lib/types.ts` 回到 737 行、新文件 106 行，两者都在阈值内；
② **设计里写的 `import type { Version } from "@/lib/types"` 逐字仍然成立**，
没有任何调用点需要知道这次拆分，§5.2 的契约面零变化。
（`Requirement.plan` 用到 `PlanContext`，故 `types.ts` 另需一次显式 `import type`——
`export *` 只做再导出，不把名字带进本文件作用域。）

**没有动阈值**：`.claude-index/config.md` 未被修改，本轮不为了省事去放宽一条门禁。

### 复核通过、无需偏离的部分

- **P0-3 的取证属实**：工作树里的半成品边界与 v3 描述逐字一致，四处已一次落全；
  §8.1 用例 8 `test_every_bulk_action_has_a_handler` 已实现为「遍历 `ACTIONS` 逐个构造
  `_Runner` 并断言 `_handler()` 可调用」——注意 `_handler()` 返回的是**单个**处理器
  而不是字典，故取 §8.1 括号里给的那种写法。
- **P0-4 的落点更正正确**：`TicketDrawer.tsx` 的 `invalidateTicketViews` 确实**只**在
  `onDelete()` 里；本轮把失效挂到了三处（新增的 `onPlanChange` / `onDelete` / `onAdvance`）。
- **P1-7 的落点更正正确**：`useBoard.move` 的失效已挂在**第一段 `api.patch` 成功之后**、
  第二段重取之前。
- **P1-6 的落点更正正确**：`requestErrorText` 落在 `lib/bulk.ts`，由
  `BulkToolbar.applyFromModal` 调用；`BulkPlanModal` 只 `onConfirm` 交值、不发请求不 catch。
- **P1-5 成立**：版本删除 409 的中文只说「删除」，未出现「或归档」。
- **§8.2 的人工自查已执行**：全仓库搜 `.plan`，全部消费点均为 `x.plan ? … : …`、
  `x.plan && …` 或传给按缺省渲染的 `PlanBadge`，**零处非空断言**。

---

> 评审人签署：Anthropic 工程团队 · 第一轮 2026-07-22 · **第二轮 2026-07-22**
> 两轮评审都**只修改了 `docs/plans/version-plan-console/spec.md`**，未触碰任何源代码，
> 未执行 `git commit`。第二轮发现的 `backend/services/bulk_ops.py` 半落地状态
> （评审 P0-3）**如实登记但未动手修**——评审阶段不改源码是本任务的硬约束，
> 该缺陷已通过 §5.1 / §8.1-8 / §10-5 / R-14 / 条件一-3 五处交叉登记交给实现者。
