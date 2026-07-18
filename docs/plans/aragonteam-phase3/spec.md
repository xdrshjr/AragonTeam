# AragonTeam Phase‑3 — 从「可信的 Agent 协作平台」到「自主协作的研发中枢」（Spec）

- **文档版本**: **v2**（Iteration 3/3 · Solution Architect 产出 v1 → Senior Reviewer 评审并就地修复 P0/P1 后升 v2）
- **Feature slug**: `aragonteam-phase3`
- **作者角色**: Solution Architect（Anthropic Engineering）／评审：Senior Reviewer（Anthropic Engineering）
- **状态**: Reviewed · 有条件通过（Approved with conditions）——见文首「## 评审记录」与文末「## 评审结论」。所有 P0/P1 已在 v2 正文就地修复；剩余为 P2 建议项与落地须遵循的约束。
- **目标读者**: 下游开发工程师（须可据此逐行实现，无需再做架构决策）。
- **基线**: 本方案**建立在已合入的 Phase‑2（commit `bbd64bb`，见 `docs/plans/aragonteam-phase2/spec.md` v2）与 Phase‑1（commit `91507c2`）之上**，不推翻任何既有对外契约，仅做**向后兼容的增量演进与收官**。
- **技术栈（沿用）**: Next.js 14 App Router + React 18 + TypeScript + Tailwind + @dnd‑kit + SWR ｜ Flask 3 + SQLAlchemy 2 + SQLite + flask‑jwt‑extended + Flask‑CORS。**后端不新增第三方运行时依赖**（pytest 仍仅为开发期依赖），**前端不新增运行时依赖**（通知实时性用 SWR 轮询实现，不引 WebSocket 库）。

---

## 评审记录（Review Notes · v2）

> 评审人：Senior Reviewer（Anthropic Engineering）。评审方法：对 v1 逐段核对四维度——**可行性（能否用现栈实现）/ 完备性（边界·错误路径·上线）/ 一致性（是否与 Phase‑1/2 既有约定或代码冲突）/ 合理规模（是否过度或欠设计）**，并**逐条与真实代码交叉验证**（引用 `文件:行号` 为证）。结论：设计整体扎实、扎根于两轮已评审的 Phase，**无 P0**；发现 **2 个 P1、4 个 P2**。P1 已在下方正文就地修复（并标注 `〔R3‑0x 修复〕`），P2 中低成本项已并入正文、其余列为落地建议。
>
> **交叉验证已确认为真的关键假设（可放心依赖）**：`agent_runner.advance_one` 返回 `(to, comment, activity)` 且不 commit、进入即防御性复核 `can_transition`（`services/agent_runner.py:74‑106`）；`NoAgentAction`（`agent_runner.py:51`）；`workflow.can_transition` 为唯一裁决、`new→assigned` / `open→assigned` 均为合法边（`services/workflow.py:12‑48,78‑83`）；`paginate`→`(rows,total)` 且 `with_total_count` 写 `X-Total-Count`（`services/pagination.py`）；`User.summary()`/`Agent.summary()`（`models/user.py:45`、`models/agent.py:35`）；`Activity.log(...)` 不 commit（`models/activity.py:47`）；`updated_at` 带 `onupdate=utcnow`、`to_dict().updated_at = _iso(...)= isoformat()+"Z"`（`models/requirement.py:33,52`）；`ApiError.allowed` 与 `listFetcher`/`getWithHeaders` 读分页头（`frontend/lib/api.ts:9‑20,107‑155`）；`useBoard` 乐观回滚 + 409 `allowed` 分流（`frontend/hooks/useBoard.ts:71‑81`）；`Card = Requirement|Bug` 且二者含 `updated_at`（`frontend/lib/types.ts:77,94,187`）；CORS `expose_headers=["X-Total-Count","X-Request-Id"]`（`backend/app.py:29`）。这些证据支撑「支柱 A 复用 advance_one」「乐观并发比对 `updated_at` 字符串」「列表过滤 + 分页头」「409 前端分流」等核心主张**均可落地**。

| 编号 | 维度 | 严重度 | 位置 | 问题 | 处置 |
|---|---|---|---|---|---|
| **R3‑01** | 一致性 / 完备性 | **P1** | §2.4 权限矩阵「单步 Agent 推进」行；§6.1 P3‑T6；§6.3 DoD #4 | 把 `agent-advance` 收紧为「`pm/admin` 或 `can_manage_ticket`」，**逆转了 Phase‑2 已落地并被测试固化的契约**——`backend/tests/test_rbac.py:25‑32`（`test_member_can_comment_and_advance`）断言 member 对**非本人**工单 `agent-advance` 返回 **200**，其注释明写「协作动作（评论 / agent-advance）仅需登录」。但 v1 的 §6.3 DoD #4 与 §6.1 P3‑T6 又要求「Phase‑2 P‑T1…P‑T8 全绿、既有验收不破」。二者**自相矛盾**：收紧后该用例必红。 | 就地修复：§2.4 明确「这是**有意的、必要的**契约收紧——否则新加的 `move`/`patch` 行级 RBAC 会被 `agent-advance` 旁路（member 改不动的单却能借 Agent 推进）」；点名该测试须**拆分/改写**（member 评论仍 201；member 对非归属单 `agent-advance` 现为 **403**；200 正路改用 reporter/归属 assignee 或 pm）；并同步放松 §6.1/§6.3 中「P‑T7 逐字保持」的措辞。〔R3‑01 修复〕 |
| **R3‑02** | 可行性 / 一致性 | **P1** | §3.1「`routes/users.py` … `GET /api/me/work`」；§4.3 | `users` 蓝图 `url_prefix="/api/users"`（`backend/routes/users.py:10`）。若按 §3.1 把 `/me/work` 挂进该蓝图，真实路由将是 **`/api/users/work`**，与 §4.3 公布的契约 `GET /api/me/work` **不符**。Flask 蓝图内路由无法逃逸其 `url_prefix`。 | 就地修复：新增 `routes/me.py` 蓝图（`url_prefix="/api/me"`）承载 `GET /api/me/work`，在 `routes/__init__.py` 注册；§3.1 文件清单相应更正。〔R3‑02 修复〕 |
| **R3‑03** | 一致性 | P2 | §2.4 | 新引 `require_roles(*roles)`，但 `services/auth_helpers.py:32` 已有等价 `require_role(*roles)`（同样二次查库、403 体 `{error:"forbidden", detail:{required_roles, your_role}}`）。再造近重复函数且 403 体形状不同，增维护面、破坏错误体一致性。 | 就地修复：复用既有 `require_role`；本 Phase 仅真正新增 `can_manage_ticket`。〔R3‑03 修复〕 |
| **R3‑04** | 合理规模 / 清晰度 | P2 | §3.1「`routes/board.py`［改］」 | `board.py` 为**只读**（仅 `GET /api/board/{requirements,bugs}`，`backend/routes/board.py`），并无独立 move 路径——move 落在 requirements/bugs 蓝图。该行虽以「若 board 走独立 move 路径」兜底，仍会诱导实现者去找不存在的路径。 | 就地修复：改标「无需改动」并说明 move 的真实归属。〔R3‑04 修复〕 |
| **R3‑05** | 完备性（措辞） | P2 | §2.5 / §7 风险表 | 风险表「秒级时间戳精度足够区分」不准确：`updated_at` 经 `_iso` 携**微秒**，比对是**精确 ISO 串相等**（非秒级）。SQLite `DateTime` 往返保留微秒，故串相等成立。 | 就地修复：更正为「精确 ISO 串（微秒）相等；SQLite `DateTime` 往返保留微秒」。〔R3‑05 修复〕 |
| **R3‑06** | 一致性（DRY） | P2 | §2.2.3 A（claim‑next） | claim‑next 在 `agent_autopilot` 内**重写** assign 语义（设 assignee + `new→assigned` + `position` + 写 `assigned` 审计），与 `routes/requirements.py:220‑248`、`routes/bugs.py:125‑152` 的 `assign_*` 逻辑重复，未来易分叉。 | 建议（非阻断）：抽取共享 helper（如 `services/assignment.assign_ticket(...)`）供路由与 autopilot 共用；或在实现时交叉引用保持对齐。正文 §2.2.3 已补该建议。 |

**判定小结**：无 P0；2 个 P1（R3‑01、R3‑02）已就地修复；4 个 P2 中 R3‑03/04/05 已就地修复，R3‑06 记为落地建议。

---

## 0. 背景：Phase‑2 交付了什么，Phase‑3 为什么存在

Phase‑1 交付了**可运行的全栈骨架**（登录鉴权、User/Agent/Project/Requirement/Bug 的 CRUD、需求 7 态 / BUG 5 态状态机、看板拖拽 + 乐观回滚、需求转 BUG、审计时间线、Anthropic 暖色浅色设计系统）。Phase‑2 在其上把「Agent 参与协作」从静态字段落成**可交互、可追溯、可测试的真实机制**：新增 `agent_runner`（`POST /api/{requirements|bugs}/:id/agent-advance` 单步 + `?run=all` 连续推进，**绝不绕过 `workflow.can_transition`**）、`comments` 表与合并 `feed`、`TicketDrawer` 工单抽屉，并补齐可靠性护栏（结构化日志 + `X-Request-Id`、列表分页 + `X-Total-Count`、登录限流、500 事务回滚、SQLite 外键 PRAGMA、健康探活）与一套 **pytest 套件（47 用例全绿）**。

但对照全局目标「**稳健、可靠、顶级**」与本产品的立身之本——「**AI 时代（Agent 可参与协作）的开发协作管理平台**」，当前实现仍有三处**收官性欠账**：

1. **Agent 仍需人「手动点一下」才动，尚未「自主协作」。** Phase‑2 的 `agent-advance` 是**人在 UI 上逐张、逐步触发**的。README 与产品愿景写明的「Agent **自动认领**需求、**自动开发**、**自动修 BUG**」尚未成闭环——Agent 不会主动认领待办、也不会把自己名下的一批工单连续推进。这是 Phase‑3 的第一优先级。
2. **协作是「无声」的——没有通知，看不见「与我相关」的事发生了。** 工单被指派给我、有人（或 Agent）在我的单上评论、我的单被推进/转 BUG，**当前都不会有任何提醒**；用户必须主动刷新看板才可能发现。一个协作平台没有「通知 / 与我相关」这一层，协作感是残缺的。
3. **权限、并发与检索尚未收口。** 行级 RBAC 仍是 `# TODO(rbac-row-level)`（谁能指派 / 推进 / 改 / 删未强约束）；看板拖拽存在**丢更新**风险（两人同时拖同一张卡，后写覆盖先写且无告警）；列表只有分页、**没有按状态 / 指派人 / 关键字检索**，也没有「我的工作」聚合视图。这些是「稳健、可靠、顶级」在**最后一公里**上的硬指标。

Phase‑3 的使命，就是把这三处欠账补齐，把「可信的 Agent 协作平台」升级为「**自主协作的研发中枢**」：Agent 会**自己认领并推进**一批工作；与我相关的每件事都会**主动通知**我；权限、并发、检索三条工程质量线**收口**。全程**不引入任何外部 LLM / 新运行时依赖**——Agent 的「自主」仍是**确定性离线编排**（复用 Phase‑2 已建好的 `agent_runner` + `workflow` 事实源），未来把「模拟推进」替换为「真实 Agent 调用」只需替换单一函数。

---

## 1. Overview（概述）

**AragonTeam Phase‑3** 围绕一条主线展开：**让协作「自己转起来」，并让每个参与者「看得见与自己相关的一切」**。为此引入三根支柱：

- **支柱 A — Agent 自主协作闭环（Agent Autonomy Loop）**：新增 `services/agent_autopilot.py` 与一组 Agent 编排接口——`claim-next`（Agent **自动认领**其「泳道」内最久未指派的工单）、`autorun`（**扫描并连续推进**该 Agent 名下所有可推进工单）、`tick`（「认领 + 推进」的**一次自主循环**）、以及 `autorun-all`（**一键运行整支 AI 团队一轮**）。每一步**仍严格走 `workflow.can_transition`**（复用 Phase‑2 `agent_runner.advance_one`），确定性、可单测、无网络抖动；`agents.status` 的 `busy` 在自主运行期间作为**软锁**兼可观测信号（复用既有列，不改 schema）。这把 README 承诺的「Agent 自动认领 / 自动开发 / 自动修 BUG」第一次落成**可演示、可回归的闭环**。

- **支柱 B — 通知中心与协作感知（Notifications & Awareness）**：新增 `notifications` 表（本 Phase 唯一新增表，`create_all` 安全）与通知接口，在**指派 / 评论 / @提及 / 状态推进（含 Agent 自主推进）/ 转 BUG** 等关键事件上向**相关的人类用户**扇出通知（不给自己发、不给 Agent 发）。前端在 Header 增加**通知铃铛**（未读红点 + 下拉列表 + 点击直达工单 + 一键已读），实时性用 **SWR 轮询**（`refreshInterval`）达成——**不引 WebSocket**，稳健、零新依赖；WebSocket/SSE 实时推送诚实延期（`# TODO(phase4-realtime)`）。

- **支柱 C — 权限 / 并发 / 检索收官（RBAC · Concurrency · Search）**：收口 `# TODO(rbac-row-level)`——落**行级 RBAC**（谁能指派 / 推进 / 编辑 / 删除由角色 + 归属裁决，非法 403）；给 `move`/`patch` 加**乐观并发守卫**（可选 `expected_updated_at`，冲突返回 409，前端提示刷新，**杜绝拖拽丢更新**）；给列表接口加**过滤 / 关键字检索**（`q/status/priority/severity/assignee/reporter`，全部可选、向后兼容），并新增 **「我的工作」聚合视图** 与 **Header 全局搜索**。这三条把平台从「能用」推到「顺手、可信、抗并发」。

Phase‑3 **不改动** Phase‑1/2 已确立的任何对外契约（status key 集合、错误响应体 `{error, detail?}`、JWT identity=str、看板/列表/feed 既有返回 shape、`agent-advance` 语义），全部改动均为**新增或向后兼容变更**。范围仍属「MVP 收官深化」而非重写：预计新增/修改约 **34–40 个文件**（后端 ~16、后端测试 ~6、前端 ~16、文档/配置 ~2）。**唯一的 schema 变更是新增 `notifications` 表**（`create_all` 自动建，无既有列变更、无迁移风险）。

---

## 2. Technical Design（技术设计）

### 2.1 架构增量（Delta，相对 Phase‑2）

```
┌──────────────────────────── Browser (Next.js) ─────────────────────────┐
│  既有：Sidebar + Header + Content · 看板 dnd · SWR · TicketDrawer · feed  │
│  ＋ Header：通知铃铛(未读红点+下拉) ＋ 全局搜索框                          │  ← 新增
│  ＋ /my-work「我的工作」聚合页（指派给我 / 我提的单）                       │  ← 新增
│  ＋ 列表页过滤条（状态/优先级/严重度/指派人/关键字）                       │  ← 增强
│  ＋ Agents 页：认领下一个 / 运行队列 / 自动一轮(Tick) / 运行AI团队          │  ← 增强
│  ＋ 拖拽/编辑携带 expected_updated_at，409 冲突提示刷新                     │  ← 增强
└───────────────▲─────────────────────────────────────────────────────────┘
                │  HTTP/JSON, Bearer JWT（通知实时性 = SWR 轮询）
┌───────────────┴──────────────── Flask (create_app) ────────────────────┐
│  既有 Blueprints: auth users agents projects requirements bugs board     │
│                   stats comments                                          │
│  ＋ notifications 蓝图（列表/未读数/单条已读/全部已读）                     │  ← 新增
│  ＋ agents 蓝图挂 claim-next / autorun / tick；顶层 autorun-all           │  ← 新增
│  Services: workflow（不变，仍是迁移唯一裁决）· agent_runner（不变，复用）   │
│  ＋ agent_autopilot.py（认领 + 扫描推进的确定性编排，复用 advance_one）     │  ← 新增
│  ＋ notifications.py（扇出 notify + 事件级 helper）                        │  ← 新增
│  ＋ auth_helpers 扩展：行级 RBAC 裁决（can_manage_ticket / require_*）      │  ← 增强
│  ＋ 列表过滤/检索 + move/patch 乐观并发守卫（expected_updated_at）          │  ← 增强
│  ORM → SQLite: users agents projects requirements bugs activities comments│
│  ＋ notifications 表（新增，additive，create_all 自动建）                  │  ← 新增
└───────────────▲─────────────────────────────────────────────────────────┘
                │  pytest（内存 SQLite · StaticPool · 不 seed）
        ┌───────┴────────┐
        │ backend/tests/ │  ＋ agent_autopilot / notifications / concurrency /
        │  （既有+新增）  │     search ；rbac 扩充（既有 auth/workflow/... 保留）
        └────────────────┘
```

**关键不变量（下游必须保持）**：
1. **迁移合法性仍且只由 `services/workflow.py` 邻接表裁决**——Agent **自主**推进与人推进共用同一套 `can_transition`；`agent_autopilot` 只是「批量调用 `agent_runner.advance_one`」，不得新增任何绕过状态机的路径。
2. **`agent_runner.advance_one` 契约不变**：仍返回 `(to_status, comment, activity)`、仍不 `commit`（由调用方事务提交）。Phase‑3 的自主编排在其外层组织循环与 `commit` 节奏，**不改其内部**。
3. **只新增 `notifications` 一张表**，不改任何既有列——`create_all` 对「仅新增表」安全（与 Phase‑2 引入 `comments` 同策略）。

### 2.2 支柱 A：Agent 自主协作闭环（核心）

#### 2.2.1 设计原则

- **复用而非重写**：推进的原子操作**完全复用 Phase‑2 `agent_runner.advance_one`**（含其「防御性复核 `can_transition`、写 Agent 评论、写 `actor=agent` 审计」三合一逻辑）。Phase‑3 只新增**编排层**：认领哪些单、按什么顺序推、推几步、如何提交、如何加软锁与扇出通知。
- **确定性、可单测、无外部依赖**：认领用**确定的排序规则**（`ORDER BY created_at ASC, id ASC` 取最久未指派者），推进用 Phase‑2 已被单测覆盖的 `AGENT_FORWARD`；全程无 LLM / 无网络。未来接真实 Agent 仍只需替换 `agent_runner.advance_one` 内部动作生成，本编排层与接口、数据模型、前端**全部不变**。
- **软锁防重入（可靠性）**：一次 `autorun`/`tick` 期间把 `agent.status="busy"` 并 `commit`；若进入时该 Agent **已是 `busy`** → 返回 `409 {error:"agent is busy"}`（拒绝并发自主运行，单机下即为可靠软锁）；无论正常/异常，`finally` 中把 `agent.status="idle"` 并 `commit`。**〔与 Phase‑2 R‑04 一致〕** `busy` 因逐步 `commit` 而对外可观测——这正是 Phase‑2 为 `run=all` 保留的 `busy` 语义落点，Phase‑3 的批量自主运行天然复用。

#### 2.2.2 「可认领泳道」映射（AGENT_CLAIMABLE）

在 `agent_autopilot.py` 内定义 `(agent.kind) → [(entity, claimable_status), ...]`：**该 kind 的 Agent 可以主动认领哪些「无人认领」的工单**。

| agent.kind | 可认领（entity, status，且 `assignee_id IS NULL`）| 语义 |
|---|---|---|
| `dev` | `("requirement","new")`, `("bug","open")` | dev‑agent 主动接手新需求 / 新缺陷 |
| `generic` | `("requirement","new")`, `("bug","open")` | 通用 Agent 同上 |
| `qa` | （空）| qa 处理的是**已在流程中（testing/verifying）的已指派单**，不主动认领「新」单，避免抢占分诊阶段 |

**认领动作**：取该泳道内 `assignee_id IS NULL` 且状态匹配、`created_at` 最早的一张 → **复用既有 `assign` 语义**（`assignee_type="agent"`, `assignee_id=agent.id`；`new→assigned` / `open→assigned` 是 `workflow` 内的合法边，仍走 `can_transition`）→ 写 `Activity.log(action="assigned", actor=("agent", agent.id), ...)` → **扇出通知**给该单 `reporter`（若为人类且非 Agent 自己）。无可认领单时返回「未认领」。

> 认领**不推进业务态到 `assigned` 之后**（推进是 `autorun` 的职责）——认领与推进职责分离，便于单测与前端分步演示。

#### 2.2.3 关键代码路径

**A. `POST /api/agents/:id/claim-next`（认领一张）**
1. `@jwt_required()`；**RBAC**：仅 `pm`/`admin`（见 §2.4）。取 `agent`，404 保护。
2. 依 `AGENT_CLAIMABLE[agent.kind]` 逐 entity 查「最久未指派」候选；可选 body `{entity?}` 限定只认领某类。
3. 命中 → 事务内：设 assignee=agent、`can_transition` 裁决并置 `assigned`、`position=_next_position(...)`、写 `assigned` 审计、`notify` reporter；`commit`；返回 `200 {claimed: ticket.to_dict()}`。
4. 无候选 → `200 {claimed: null}`（非错误，前端提示「暂无可认领工单」）。

> **DRY 建议〔R3‑06〕**：上述「设 assignee + `new/open→assigned` + `position` + 写 `assigned` 审计」与 `routes/requirements.py:220‑248`、`routes/bugs.py:125‑152` 的 `assign_*` 逻辑重复。为防未来分叉，**建议抽取共享 helper**（如 `services/assignment.py::assign_ticket(entity, ticket, assignee_type, assignee_id, actor)`，返回 `(activity,)`，不 commit），供 `assign_*` 路由与 `agent_autopilot.claim_next` 共用；若时间不足则至少在两处交叉引用注释保持对齐。非阻断项。

**B. `POST /api/agents/:id/autorun`（扫描并推进名下所有单）**
1. `@jwt_required()`；RBAC：`pm`/`admin`。取 `agent`；若 `agent.status=="busy"` → `409 {error:"agent is busy"}`（软锁）。
2. 置 `agent.status="busy"` 并 `commit`（开锁 + 可观测）。
3. 收集该 Agent 名下工单：`Requirement.query.filter_by(assignee_type="agent", assignee_id=id)` ∪ `Bug` 同构。
4. 逐工单尝试推进：默认**每单一步**；`?run=all` 时每单连续推进至「无预置动作 / 终态 / 单工单 `MAX_AGENT_STEPS=6`」。**每一步各自 `commit`**（复用 `agent_runner.advance_one` + 每步后 `db.session.commit()`）。命中 `NoAgentAction` → 记 `skipped`（不改库）。全局步数上限 `MAX_AUTOPILOT_STEPS=24` 兜底防长循环。
5. 每张被推进的单 → `notify` 其 `reporter` / 原人类关注者（若与 actor 不同）。
6. `finally`：`agent.status="idle"` 并 `commit`。
7. 返回 `200 {agent: agent.to_dict(), advanced:[{entity,id,from,to,message}], skipped:[{entity,id,reason}]}`（`agent.status=="idle"`）。

**C. `POST /api/agents/:id/tick`（一次自主循环 = 认领 + 推进）**
- body `{claim?: true, claim_count?: 1}`。先执行 `claim_count` 次 `claim-next`（各自事务），再执行一次 `autorun`。返回 `{claimed:[...], advanced:[...], skipped:[...], agent}`。这是**旗舰演示**：一键让 Agent「接活并把能推的都推一步」。

**D.（P1）`POST /api/agents/autorun-all`（运行整支 AI 团队一轮）**
- `@jwt_required()`；RBAC：`pm`/`admin`。对所有 `Agent`（跳过 `busy`）各执行一次 `tick`（claim 可配），聚合返回 `{runs:[{agent, claimed, advanced, skipped}], ...}`。用于「一键推进」的整体演示与压测式回归。

#### 2.2.4 前端呈现

- **Agents 页（`agents/page.tsx`）**：每张 Agent 卡新增操作区——`认领下一个`(claim‑next) / `运行队列`(autorun) / `自动一轮`(tick)，按钮处理中 `loading`；页面顶部为 `pm/admin` 显示 `▶ 运行 AI 团队一轮`(autorun‑all)。每次调用成功后 toast 概要（如「dev‑agent 推进 2 张、认领 1 张」）并 `mutate` 看板/仪表盘/Agents 数据。非 `pm/admin` 隐藏这些按钮（后端仍是权威）。
- **TicketDrawer**：保留 Phase‑2「让 {agent} 处理下一步」（单张单步）；自主编排是「批量版」，二者并存。
- **看板**：Agent 自主推进后卡片自动移列（同 Phase‑2，写后 `mutate` 看板 key）。

### 2.3 支柱 B：通知中心（数据 + 接口 + 前端）

#### 2.3.1 `notifications` 表与扇出服务

表结构见 §5。要点：`user_id`（**收件人，仅人类**）+ `type` + 多态来源 `(entity_type, entity_id)` + 多态施动者 `(actor_type, actor_id)` + `message` + `is_read` + `created_at`。

`services/notifications.py`：
- `notify(user_id, type, *, entity_type=None, entity_id=None, actor=None, message=None)`：底层写一条 `Notification`（**不 commit**，随调用方事务）；**跳过条件**：`user_id is None`、或收件人即施动者本人（`actor==("user", user_id)`，不给自己发）。
- 事件级 helper（在各写路径末尾调用，均在既有事务内）：
  - `notify_assignment(ticket, entity, actor)`：指派/认领后 → 通知**新的人类 assignee**（Agent 不发）。
  - `notify_comment(ticket, entity, comment, actor)`：评论后 → 通知**工单 reporter + 当前人类 assignee + 历史评论人去重集**（排除评论作者本人、排除 Agent/system）。
  - `notify_advance(ticket, entity, actor, from_status, to_status)`：（含 Agent 自主推进）→ 通知**工单 reporter + 人类 assignee**（排除 actor）。
  - `notify_convert(src_req, new_bug, actor)`：转 BUG 后 → 通知源需求 reporter/assignee。
  - `notify_mentions(comment, actor)`（P1）：解析 `body` 中的 `@username`（正则 `@([A-Za-z0-9_]+)`），存在的用户各发一条 `mentioned` 通知（去重、排除自己）。
- **去重**：一次事件对同一 `user_id` 只发一条（helper 内用 `set` 收敛收件人）。

**接入点**（均为在既有事务 `commit` 前追加，不改既有返回 shape）：`routes/requirements.py`/`bugs.py` 的 assign、move、patch、convert‑to‑bug；`routes/comments.py` 的 POST comment；`agent_runner.advance_one` 的调用方（`agent-advance` 路由 + `agent_autopilot`）在其外层调用 `notify_advance`（**不侵入 `advance_one` 本体**，保持其契约纯净）；`agent_autopilot.claim` 内调用 `notify_assignment`。

#### 2.3.2 通知接口

- `GET /api/notifications?unread=<0|1>&limit=&offset=` → 当前用户的通知，**按 `created_at DESC, id DESC`**，`unread=1` 只回未读；响应体为裸数组 + 头 `X-Total-Count`（复用 Phase‑2 `paginate`）。
- `GET /api/notifications/unread-count` → `200 {count:<int>}`（供铃铛轮询，轻量）。
- `POST /api/notifications/:id/read`（owner 校验，非本人 404/403）→ `200 {notification}`；幂等（已读再置无副作用）。
- `POST /api/notifications/read-all` → `200 {updated:<int>}`（把当前用户所有未读置已读）。

`Notification.to_dict()`：`{id, type, entity_type, entity_id, actor_type, actor_id, actor:{...}|null, message, is_read, created_at}`（`actor` 概要复用 `User.summary()`/`Agent.summary()`，system 为 `{"type":"system","name":"系统"}`，已删除降级占位——与 `comments`/`activities` 一致策略）。

#### 2.3.3 前端呈现

- `components/notifications/NotificationBell.tsx`（挂在 `Header`）：
  - SWR 轮询 `GET /notifications/unread-count`（`refreshInterval: 20000`，`revalidateOnFocus`），红点显示未读数（>99 显示 `99+`）。
  - 点击展开下拉面板：SWR 拉 `GET /notifications?limit=15`，条目含施动者头像/图标 + `message` + 相对时间；未读高亮。
  - 点击某条 → 跳到对应工单看板并**打开 TicketDrawer**（携带 `?ticket=<id>` 查询参数，board 页读取后自动开抽屉；同时 `POST /:id/read` 并 `mutate` 未读数）；面板底部 `全部已读`(read‑all)。
  - 可访问性：面板 `role="menu"`、`Esc`/点外部关闭、焦点管理（复用 Phase‑2 抽屉/Modal 的 a11y 手法）。
- `lib/types.ts` 增 `Notification`/`NotificationType`；`lib/constants.ts` 增 `notificationLabel/icon` 映射；`hooks/useNotifications.ts` 封装轮询 + 已读 + `mutate`。
- **实时性说明（诚实）**：本 Phase 实时性为**轮询近实时**（默认 20s），非推送。WebSocket/SSE 延期 `# TODO(phase4-realtime)`——理由：Flask 开发服务器下长连接线程模型复杂，轮询更稳健且**零新依赖**，契合本产品一贯的「稳健取向」。

### 2.4 支柱 C：行级 RBAC（收口 `# TODO(rbac-row-level)`）

在 `services/auth_helpers.py` 扩展**声明式裁决**（不散落 if 于各路由）：

- **粗粒度角色守卫复用既有 `require_role(*roles)`**（`services/auth_helpers.py:32`，已实现二次查库 + `403 {error:"forbidden", detail:{required_roles, your_role}}`）——**不新增 `require_roles`**，避免近重复函数与 403 体形状分叉。〔R3‑03 修复〕行级裁决场景（依赖 ticket 归属，装饰器无法表达）以**内联守卫**调用下面的 `can_manage_ticket` 并复用同一 403 体形状。
- `can_manage_ticket(user, ticket) -> bool`（**本 Phase 唯一真正新增的裁决函数**）：`user.role in ("admin","pm")` **或** `ticket.reporter_id == user.id` **或**（`ticket.assignee_type=="user"` 且 `ticket.assignee_id==user.id`）。

**权限矩阵**（entity ∈ {requirement, bug}；返回 `403` 时体为 `{error:"forbidden", detail}`）：

| 操作 | 允许者 |
|---|---|
| 创建（POST）| `pm`/`admin`（延续 Phase‑1：member 建单 403）|
| 编辑（PATCH 标题/描述/优先级/严重度）| `can_manage_ticket`（reporter / 人类 assignee / pm / admin）|
| 移动（PATCH `/move`）| `can_manage_ticket` |
| 指派 / 改派（PATCH `/assign`）| `pm`/`admin`（member 不得改派他人工作）|
| 转 BUG（POST `/convert-to-bug`）| `pm`/`admin` |
| 删除（DELETE）| `pm`/`admin` |
| 评论（POST `/comments`）| 任意已登录用户（协作开放）|
| 单步 Agent 推进（`/agent-advance`）| `pm`/`admin` **或** `can_manage_ticket`（**有意收紧**，见下「Agent 推进契约收紧说明」；接口签名不变）|
| 自主编排（`claim-next`/`autorun`/`tick`/`autorun-all`）| `pm`/`admin` |
| 通知已读（`/read`、`/read-all`）| 仅本人（收件人）|

前端**据同一矩阵禁用/隐藏**用户无权的按钮（graceful），但**后端始终为权威**（前端隐藏≠后端放行）。**〔非破坏性说明〕** 收紧鉴权可能让「原来能删/能改派的 member」收到 403——这是**有意的安全修正**，Phase‑1/2 未把这些操作暴露给 member 的正常 UI 路径（member 侧无删除/改派入口），故对既有正常用法无回归；测试 `test_rbac.py` 固化新矩阵。

**Agent 推进契约收紧说明〔R3‑01 修复〕**：`agent-advance` 在 **Phase‑2 是「仅需登录即可推进任意工单」**，并被 `backend/tests/test_rbac.py:25‑32`（`test_member_can_comment_and_advance`）**显式固化**为「member 对非本人工单 `agent-advance` → 200」，其注释写明「协作动作（评论 / agent-advance）仅需登录」。本 Phase **有意逆转此契约**，理由是**一致性与防旁路**：本 Phase 给 `move`/`patch` 加了 `can_manage_ticket` 行级门禁，若 `agent-advance` 仍全开，member 便能**借 Agent 推进一张自己无权 `move` 的单**，形成 RBAC 旁路。因此 `agent-advance` 必须与 `move`/`patch` 同门禁（`pm/admin` 或 `can_manage_ticket`）。**这是对既有契约的有意变更，须诚实标注、不得声称「Phase‑2 用例逐字全绿」**：
- **必须改写** `test_member_can_comment_and_advance`：拆成两点断言——(a) member **评论**仍 `201`（评论对全员开放，不变）；(b) member 对**非归属**单 `agent-advance` 现为 **403**；`agent-advance` 的 200 正路改用 **reporter 本人 / 人类归属 assignee / pm** 触发（新增 `test_rbac` 用例覆盖）。
- 该测试属 Phase‑2 P‑T7；因此 §6.1 P3‑T6 与 §6.3 DoD #4 关于「P‑T7 逐字保持绿」的措辞已随之放松（见对应小节的 R3‑01 批注）。
- 评论（`/comments`）**不收紧**，仍对全员开放（协作开放，`_create_comment` 现状不变），故不产生同类旁路顾虑。

### 2.5 支柱 C：乐观并发守卫（防拖拽/编辑丢更新）

- **机制**：`PATCH /:id/move` 与 `PATCH /:id`（编辑）接受**可选** `expected_updated_at`（字符串，取值即 `ticket.to_dict().updated_at`，形如 `...Z`）。服务端在改动前比对：`expected_updated_at` 存在且 `!= _iso(ticket.updated_at)` → `409 {error:"conflict, please reload", detail:{current_updated_at}}`，不改库。**缺省该字段则不校验**（严格向后兼容 Phase‑1/2 调用方）。
- **比对精度〔R3‑05 修复〕**：比对是**精确 ISO 串相等**——`updated_at` 经 `_iso()=isoformat()+"Z"` 携**微秒**（非秒级），SQLite `DateTime` 往返保留微秒，故「同一持久化值」的串相等恒成立、「他人已写」因 `onupdate=utcnow` 必产生不同串。**实现要点**：每次请求以 `db.session.get(model, id)` 取**当前已提交**的 `updated_at` 参与比对（该值在 flush 前不受本次 `onupdate` 影响），比对通过后再改字段；`move` 的**同列早退分支（`frm==to`）也须先过并发守卫**再决定重排，勿遗漏。
- **前端**：看板拖拽与抽屉编辑从已加载的 ticket 读取 `updated_at` 一并提交；收到 409 conflict → toast「该工单已被他人更新，请刷新」+ `mutate` 看板/抽屉（拉最新），乐观移动回滚（复用 Phase‑1 `useBoard` 回滚路径）。
- **与既有 409 区分**：状态机非法迁移 409 体含 `allowed`（Phase‑1）；并发冲突 409 体含 `detail.current_updated_at`、**无 `allowed`**——前端据此分流提示（`ApiError.allowed` 有无即可判别）。

### 2.6 支柱 C：列表过滤 / 检索 + 「我的工作」

- **列表过滤（向后兼容，全部可选，AND 组合）**：
  - `GET /api/requirements?q=&status=&priority=&assignee_type=&assignee_id=&reporter_id=&limit=&offset=`
  - `GET /api/bugs?q=&status=&severity=&assignee_type=&assignee_id=&reporter_id=&limit=&offset=`
  - `q` 对 `title`/`description` 做 `ILIKE %q%`（SQLite `LIKE` 不区分大小写，够用）；其余为等值过滤。响应体仍为裸数组 + `X-Total-Count`（复用 `paginate`，过滤在 `paginate` 前施加于 query）。
- **「我的工作」聚合**：`GET /api/me/work` → `200 {assigned:{requirements:[...], bugs:[...]}, reported:{requirements:[...], bugs:[...]}}`（当前用户为人类 assignee 的单 + 其 reporter 的单，各按更新时间倒序，`limit` 兜底）。
- **前端**：
  - 列表页（`requirements/page.tsx`、`bugs/page.tsx`）加**过滤条**（状态/优先级或严重度/指派人 `AssigneePicker` 复用/关键字 `Input` debounce），走上述 query 参数；用 `listFetcher`（Phase‑2 已实现，读 `X-Total-Count`）显示真实结果总数与分页。
  - `Header` 加**全局搜索框**：回车/防抖后跳 `requirements` 列表并带 `?q=`（`useRouter().push`）。
  - 新页 `/(app)/my-work/page.tsx`「我的工作」：两栏（指派给我 / 我提交的），卡片点击打开对应看板 + TicketDrawer；`Sidebar` 增一条「我的工作」导航项。

### 2.7 顶级打磨（HCI，锦上添花，P2）

- 通知铃铛下拉的进出动效、空态（「暂无通知」EmptyState 复用）、骨架（复用 Skeleton）。
- Agents 页自主运行结果的**行内摘要**（本轮推进/认领/跳过计数）与最近自主活动。
- 「我的工作」页的状态分组小徽章与计数。
- 全局搜索的键盘可达（`/` 聚焦搜索，`Esc` 清空）。

### 2.8 明确的范围边界（Out of Scope，本 Phase 刻意不做，诚实标注）

- **WebSocket / SSE 实时推送**：`# TODO(phase4-realtime)`。本 Phase 通知实时性用 **SWR 轮询**近实时达成（稳健、零新依赖）。
- **Alembic / Flask‑Migrate 列级迁移**：`# TODO(migrations-alembic)`。本 Phase **仅新增 `notifications` 表**（`create_all` 安全），无既有列变更；列级演进未来再引迁移工具。
- **真实 LLM Agent 调用**：自主编排仍是**确定性模拟**（复用 `agent_runner.advance_one`）；接真实 Agent 的替换点单一，`# TODO(agent-real-llm)`。
- **Agent 自主凭证与后台调度**：本 Phase 自主编排仍由**人类（pm/admin）在 UI 触发一轮**（或未来外部 cron 调 `autorun-all`）；Agent 用自有凭证轮询/回调、以及后台定时 tick 延期 `# TODO(agent-self-credential)` / `# TODO(autopilot-scheduler)`。
- **分布式限流 / 多副本通知一致性**：延续 Phase‑2 `# TODO(ratelimit-distributed)`；通知为单库单机，`# TODO(notifications-scale)`。
- **前端单测 / CI 流水线**：`# TODO(phase4-ci)`。本 Phase 以**后端 pytest 扩充**兑现「可靠」，前端仍以 `tsc --noEmit` + `next build` 把关。
- **真实商用字体（Tiempos/Styrene）**：授权问题，`# TODO(webfonts-licensing)`，继续 `Georgia`/`system-ui` 回退。

---

## 3. File / Module Change Plan（文件变更计划）

> 图例：**［新］**=新建，**［改］**=修改既有文件（增量，不破坏既有契约）。优先级 **P0**=核心必做，**P1**=强烈建议，**P2**=增强/时间允许则做。

### 3.1 Backend（`backend/`）

| 文件 | 变更 | 优先级 | 意图（一句话）|
|---|---|---|---|
| `services/agent_autopilot.py` | ［新］ | P0 | `AGENT_CLAIMABLE` + `claim_next(agent, entity?)` / `autorun(agent, run_all)` / `tick(agent, ...)`：认领 + 扫描推进的确定性编排（复用 `agent_runner.advance_one`、`workflow`）|
| `routes/agents.py` | ［改］ | P0 | 挂 `POST /:id/claim-next`、`/:id/autorun`、`/:id/tick`、顶层 `/agents/autorun-all`；RBAC 限 pm/admin；busy 软锁 409 |
| `models/notification.py` | ［新］ | P0 | `Notification` 模型：收件人 user_id + 多态来源/施动者 + is_read + `to_dict`（解析施动者概要）|
| `models/__init__.py` | ［改］ | P0 | 汇总导入 `Notification`，保证 `create_all` 建表 |
| `services/notifications.py` | ［新］ | P0 | `notify(...)` + 事件级 `notify_assignment/comment/advance/convert/mentions`（去重、跳过自己/Agent）|
| `routes/notifications.py` | ［新］ | P0 | 通知蓝图：列表(+分页头) / 未读数 / 单条已读 / 全部已读（owner 校验）|
| `routes/__init__.py` | ［改］ | P0 | 注册 `notifications` 蓝图**与 `me` 蓝图**〔R3‑02〕 |
| `services/auth_helpers.py` | ［改］ | P0 | 增 `require_roles(*roles)`、`can_manage_ticket(user, ticket)`（行级 RBAC 裁决，§2.4）|
| `routes/requirements.py` | ［改］ | P0 | 接入 RBAC 矩阵；`move`/`patch` 乐观并发守卫（`expected_updated_at`）；list 加过滤/检索；写路径接入通知扇出 |
| `routes/bugs.py` | ［改］ | P0 | 同上（BUG 侧，过滤含 `severity`）|
| `routes/comments.py` | ［改］ | P1 | POST 评论后扇出 `notify_comment` + `notify_mentions`（@提及）|
| `routes/board.py` | **无需改动**〔R3‑04〕 | — | `board.py` 为**只读**（仅 `GET /api/board/{requirements,bugs}`），**无独立 move 路径**——拖拽 move 实际落在 `PATCH /api/{requirements,bugs}/:id/move`（requirements/bugs 蓝图），RBAC + 并发守卫已在那里接入。此处不动，勿去找不存在的 board move 路径 |
| `routes/me.py` | ［新］ | P1 | **〔R3‑02 修复〕** 新增 `me` 蓝图（`url_prefix="/api/me"`）承载 `GET /api/me/work` 聚合「我的工作」（指派给我 / 我提的单）。**不放进 `routes/users.py`**——其蓝图前缀为 `/api/users`，挂进去会得到 `/api/users/work`，与 §4.3 契约 `/api/me/work` 不符（Flask 蓝图路由无法逃逸 `url_prefix`）|
| `seed.py` | ［改］ | P1 | 追加若干 mock 通知（未读/已读混合）+ 保证有未指派的 `new`/`open` 单供 claim‑next 演示 |
| `services/pagination.py` | ［改］ | P2 | （如需）暴露「先过滤后分页」的组合便捷；否则调用方自行 `filter` 后传 query，无需改动 |
| `errors.py` · `observability.py` | ［改］ | P2 | 无功能变更；如新增错误分支（如 busy 409）确保仍走统一 JSON 契约（多为零改动，仅核对）|

### 3.2 Backend 测试（`backend/tests/`）

| 文件 | 变更 | 优先级 | 意图 |
|---|---|---|---|
| `tests/test_agent_autopilot.py` | ［新］ | P0 | claim‑next 认领最久未指派单 + `new→assigned` + `actor=agent` 审计；autorun 推进名下全部可推进单、跳过无动作、置回 idle；busy 软锁 409；autorun‑all；**断言全程不绕过 `can_transition`** |
| `tests/test_notifications.py` | ［新］ | P0 | 指派通知人类 assignee；评论通知参与者、排除作者、不给自己/ Agent 发；未读数；单条/全部已读；他人通知不可读 |
| `tests/test_concurrency.py` | ［新］ | P1 | 陈旧 `expected_updated_at` → 409 conflict（无 `allowed`）；正确/缺省 → 200；与状态机 409 可区分 |
| `tests/test_search.py` | ［新］ | P1 | `q`/`status`/`priority`/`severity`/`assignee`/`reporter` 过滤；`X-Total-Count` 随过滤变化；`GET /me/work` 聚合正确 |
| `tests/test_rbac.py` | ［改］ | P0 | 扩充：member 改派/删/转 BUG/autopilot → 403；assignee(member) 可 move/编辑自己的单；reporter 可编辑；pm/admin 全通。**改写 `test_member_can_comment_and_advance`〔R3‑01〕**：member 评论仍 201；member 对非归属单 `agent-advance` 改断言 403；200 正路改用 reporter/归属 assignee/pm |
| `tests/conftest.py` | ［改］ | P0 | fixture 补：未指派的 `new`/`open` 单（供 claim‑next）、跨用户工单（供 RBAC/通知）；`auth_header(role)` 复用 |

### 3.3 Frontend（`frontend/`）

| 文件 | 变更 | 优先级 | 意图 |
|---|---|---|---|
| `components/notifications/NotificationBell.tsx` | ［新］ | P0 | Header 通知铃铛：未读红点(轮询) + 下拉列表 + 点击直达工单 + 全部已读 |
| `hooks/useNotifications.ts` | ［新］ | P0 | 封装 unread-count 轮询、列表拉取、单条/全部已读并 `mutate` |
| `components/layout/Header.tsx` | ［改］ | P0 | 挂 `NotificationBell` + 全局搜索框（回车/防抖跳 requirements?q=）|
| `lib/types.ts` | ［改］ | P0 | 增 `Notification`/`NotificationType`/`AutopilotResult`/`MeWork` 类型 |
| `lib/constants.ts` | ［改］ | P0 | 增 `notificationLabel/icon` 映射、autopilot 结果文案 |
| `app/(app)/agents/page.tsx` | ［改］ | P0 | Agent 卡加「认领下一个/运行队列/自动一轮」；pm/admin 顶部「运行 AI 团队一轮」；结果 toast + mutate |
| `hooks/useTicket.ts` | ［改］ | P1 | move/patch 携带 `expected_updated_at`；409 conflict 分流提示 + 刷新 |
| `hooks/useBoard.ts` | ［改］ | P1 | 拖拽 move 携带 `expected_updated_at`；conflict 回滚 + 刷新 |
| `app/(app)/requirements/page.tsx` | ［改］ | P1 | 过滤条（状态/优先级/指派人/关键字）+ `listFetcher` 总数分页 |
| `app/(app)/bugs/page.tsx` | ［改］ | P1 | 同上（含 `severity`）|
| `app/(app)/requirements/board/page.tsx` · `bugs/board/page.tsx` | ［改］ | P1 | 读 `?ticket=<id>` 自动打开 TicketDrawer（供通知直达）|
| `app/(app)/my-work/page.tsx` | ［新］ | P1 | 「我的工作」聚合页（指派给我 / 我提的单）|
| `components/layout/Sidebar.tsx` | ［改］ | P1 | 增「我的工作」导航项 |
| `components/collab/CommentComposer.tsx` | ［改］ | P2 | `@` 提及输入辅助（可选，纯前端提示；后端已解析 body）|
| `app/(app)/notifications/page.tsx` | ［新］ | P2 | 通知全量页（下拉之外的完整列表 + 分页）|

### 3.4 顶层 / 文档

| 文件 | 变更 | 优先级 | 意图 |
|---|---|---|---|
| `docs/plans/aragonteam-phase3/spec.md` | ［新］ | — | 本文档 |
| `README.md` | ［改］ | P1 | 追加 Phase‑3 能力（自主协作闭环 / 通知中心 / RBAC·并发·检索）、新接口与运行方式 |

---

## 4. Interface Design（接口设计，REST）

> 统一约定沿用 Phase‑1/2：JSON in/out；错误体恒为 `{error, detail?}`（+ 状态机迁移类附 `allowed`）；写接口需 `Authorization: Bearer`。以下**仅列新增/变更**，未列者不变。

### 4.1 Agent 自主协作（新增）
```
POST /api/agents/:id/claim-next     (JWT, pm/admin)  {entity?}          → 200 {claimed: Ticket|null} | 403 | 404
POST /api/agents/:id/autorun        (JWT, pm/admin)  ?run=all           → 200 {agent, advanced:[...], skipped:[...]} | 409 agent is busy | 403
POST /api/agents/:id/tick           (JWT, pm/admin)  {claim?, claim_count?} → 200 {agent, claimed:[...], advanced:[...], skipped:[...]} | 409 | 403
POST /api/agents/autorun-all        (JWT, pm/admin)  {claim?}           → 200 {runs:[{agent, claimed, advanced, skipped}]} | 403
```
`advanced[i]`=`{entity:"requirement"|"bug", id, from, to, message}`；`skipped[i]`=`{entity, id, reason:"no-action"|"terminal"|"cap"}`。

### 4.2 通知中心（新增）
```
GET  /api/notifications?unread=<0|1>&limit=&offset=  (JWT)  → 200 [Notification] + Header X-Total-Count
GET  /api/notifications/unread-count                 (JWT)  → 200 {count}
POST /api/notifications/:id/read                     (JWT, owner) → 200 {notification} | 403/404
POST /api/notifications/read-all                     (JWT)  → 200 {updated}
```
`Notification`：`{id, type, entity_type, entity_id, actor_type, actor_id, actor:{type,id,name,...}|{type:"system",name:"系统"}|null, message, is_read, created_at}`
`type ∈ {assigned, commented, mentioned, status_changed, agent_advanced, converted}`

### 4.3 「我的工作」聚合（新增）
```
GET /api/me/work   (JWT)  → 200 {assigned:{requirements:[Requirement], bugs:[Bug]}, reported:{requirements:[...], bugs:[...]}}
```
> 承载于新增 `me` 蓝图（`url_prefix="/api/me"`，见 §3.1 / R3‑02）；**不得**挂进 `users`（`/api/users`）蓝图，否则真实路径会变成 `/api/users/work`。

### 4.4 列表过滤 / 检索（变更 · 向后兼容）
```
GET /api/requirements?q=&status=&priority=&assignee_type=&assignee_id=&reporter_id=&limit=&offset=  → 200 [Requirement] + X-Total-Count
GET /api/bugs?q=&status=&severity=&assignee_type=&assignee_id=&reporter_id=&limit=&offset=          → 200 [Bug]         + X-Total-Count
   全部过滤参数可选、AND 组合、缺省即 Phase-2 行为（不破坏既有裸数组契约与分页头）。
```

### 4.5 乐观并发守卫（变更 · 向后兼容）
```
PATCH /api/requirements/:id       {..., expected_updated_at?}  → 200 Requirement | 409 {error:"conflict...", detail:{current_updated_at}}
PATCH /api/requirements/:id/move  {status, position?, expected_updated_at?} → 200 | 409(状态机 allowed) | 409(并发 detail.current_updated_at)
PATCH /api/bugs/:id · /api/bugs/:id/move   同构
   expected_updated_at 缺省时不校验（严格向后兼容）。并发 409 无 allowed，状态机 409 有 allowed，前端据此分流。
```

### 4.6 行级 RBAC（变更 · 语义收紧，签名不变）
```
assign / convert-to-bug / delete / autopilot 系列  → 非 pm/admin(或非归属) 返回 403 {error:"forbidden", detail:{required|reason}}
patch / move  → 非 can_manage_ticket 返回 403
   接口路径与请求/成功响应体不变；仅新增 403 分支（正常 UI 路径不触发，见 §2.4 非破坏说明）。
```

---

## 5. Data Model（数据模型）

**新增 `notifications` 表**（additive，`db.create_all()` 自动创建；SQLite 对**仅新增表**无迁移风险；`aragon.db` 已 gitignore，dev 首启即建全）：

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | INTEGER | PK | |
| `user_id` | INTEGER | not null, index | **收件人（仅人类 User.id）**；Agent/system 不作收件人 |
| `type` | VARCHAR(32) | not null | `assigned`\|`commented`\|`mentioned`\|`status_changed`\|`agent_advanced`\|`converted` |
| `entity_type` | VARCHAR(16) | nullable | `requirement`\|`bug`（来源工单类型）|
| `entity_id` | INTEGER | nullable | 来源工单 id（点击直达）|
| `actor_type` | VARCHAR(16) | nullable | `user`\|`agent`\|`system`（施动者）|
| `actor_id` | INTEGER | nullable | 施动者主键；system 为 NULL |
| `message` | VARCHAR(255) | not null | 人类可读一句话（如「dev‑agent 把需求「…」推进到 测试中」）|
| `is_read` | BOOLEAN | not null, default False, index | 已读态 |
| `created_at` | DATETIME | not null, index | UTC naive（复用 `utcnow`），`to_dict` 补 `Z` |

索引：`ix_notifications_user_read (user_id, is_read)` 支撑「我的未读」查询；`created_at` 索引支撑倒序分页。`to_dict()` 依 `actor_type` join 概要（`user`→`User.summary()`，`agent`→`Agent.summary()`，`system`→`{"type":"system","name":"系统"}`；施动者已删除降级 `{"type":...,"name":"(已删除)"}`，不抛异常——与 `comments` 一致）。

**既有表变更**：**无 schema 变更**。
- `agents.status` 语义扩展：`busy` 在**自主编排（autorun/tick）运行期间**为软锁兼可观测态（沿用既有列，不加列；与 Phase‑2 `run=all` 语义一致）。
- `activities.action` 取值集合复用 Phase‑2 的 `assigned`/`agent_advanced`/`updated`/`moved`/`converted` 等（自由 String，无需迁移）；自主认领写 `assigned`、自主推进写 `agent_advanced`。
- 需求/BUG/评论表**完全不变**；`expected_updated_at` 仅为**请求参数**，比对既有 `updated_at` 列，不落库。

**关系与一致性**：通知与工单为逻辑关联（多态，无 DB 级外键，与 assignee/comment 多态一致）；**删除工单时一并删除其通知**（`delete_requirement`/`delete_bug` 内 `Notification.query.filter_by(entity_type=..., entity_id=...).delete()`，与 Phase‑2「删单级联删评论」同处一并处理，避免悬挂点击直达到已删单）。删除用户是否清其通知：**当前无 user 删除端点**（Phase‑1/2 已核），故不涉及；未来补删用户时一并清理（记 `# NOTE`）。

---

## 6. Testing & Acceptance Criteria（测试与验收标准）

### 6.1 后端自动化测试（pytest，本 Phase 可靠性硬指标）
运行：`cd backend`；`pip install -r requirements.txt -r requirements-dev.txt`；`pytest -q`。沿用 Phase‑2 的 `TestConfig`（`sqlite:///:memory:` + `StaticPool` + `check_same_thread=False`、`SEED_ON_STARTUP=False`、限流阈调小），`conftest` 建表并注入最小 fixture（admin/pm/member 各一、dev/qa Agent 各一、覆盖关键状态与**未指派** `new`/`open` 的需求/BUG）。**验收：新旧用例全绿（Phase‑2 的 P‑T1…P‑T8 回归不破 + 以下新增）。**

- **P3‑T1 agent_autopilot（核心）**：对含未指派 `new` 需求的库调 `dev-agent claim-next` → 该需求 `assignee_type=agent`、`new→assigned`、写 `actor=agent` 的 `assigned` 审计、reporter 收到 `assigned` 通知；对名下有 `assigned`/`in_development` 单的 dev‑agent 调 `autorun` → 各推进一步、`agent_advanced` 审计与 Agent 评论各就位、结束 `status=idle`；`autorun` 进入时若 agent 已 `busy` → 409；`autorun-all` 聚合；**断言每次推进目标 ∈ `can_transition` 允许集（绝不绕过状态机）**。
- **P3‑T2 notifications**：assign 给人类 → 该用户有 `assigned` 通知；评论 → reporter/assignee 收到、作者本人不收、Agent 不作收件人；`unread-count` 准确；`read`/`read-all` 生效且幂等；他人通知 `read` → 403/404。
- **P3‑T3 rbac（扩充）**：member 改派/删/转 BUG/autopilot → 403；**member 对非归属单 `agent-advance` → 403**〔R3‑01〕；member 作为 assignee move/编辑/`agent-advance` 自己的单 → 200；reporter 编辑 → 200；pm 建单/改派 → 2xx。
- **P3‑T4 concurrency**：陈旧 `expected_updated_at` 的 move/patch → 409（`detail.current_updated_at` 存在、无 `allowed`）；正确/缺省 → 200。
- **P3‑T5 search/me-work**：`q`/`status`/`priority`/`severity`/`assignee_*`/`reporter_id` 过滤命中正确、`X-Total-Count` 随过滤变化；`GET /me/work` 返回当前用户 assigned/reported 聚合。
- **P3‑T6 regression**：Phase‑2 全部用例（auth/workflow/requirements/bugs/agent_runner/comments/health/rbac）保持绿——**新加鉴权/守卫不得破坏既有正向用例**（既有测试若默认用 admin/pm 调用则天然通过）。**唯一的例外〔R3‑01〕**：`test_rbac.py::test_member_can_comment_and_advance`（P‑T7）断言 member 对非本人工单 `agent-advance` → 200，与本 Phase 有意收紧的 RBAC 冲突，**须改写**（member 评论仍 201；member 对非归属单 `agent-advance` 改断言 403；200 正路改用 reporter/归属 assignee/pm）。除此之外的 Phase‑2 用例逐字保持绿。

### 6.2 前端验收（手动 / 可选 Playwright 冒烟）
- **P3‑U1 Agent 自主闭环（旗舰演示）**：Agents 页对 `dev-agent` 点「自动一轮」→ 按钮 loading → 认领一张 `new` 需求并把能推的推进一步 → 看板卡片自动移列、feed 出现 Agent 评论、reporter 的铃铛出现未读；点「运行 AI 团队一轮」→ 多 Agent 各推进一轮，摘要 toast。**这是 Phase‑3 的标志性验收。**
- **P3‑U2 通知中心**：他人/Agent 在我的单上评论/推进后，Header 铃铛 20s 内出现红点；下拉见条目；点击直达工单并自动开抽屉、该条转已读、红点递减；「全部已读」清零。
- **P3‑U3 权限收口**：以 member 登录，看不到/点不动改派、删除、autopilot 按钮；作为 assignee 可拖动/编辑自己的单；越权直接调后端返回 403（前端 toast「无权限」）。
- **P3‑U4 并发守卫**：两个会话同时拖同一张卡，后提交者收到「已被他人更新，请刷新」并回滚刷新，看板不出现丢更新/错位。
- **P3‑U5 检索 / 我的工作**：列表页按状态/关键字过滤即时生效、总数随之变化；Header 搜索跳列表带 `q`；「我的工作」页正确聚合指派给我/我提的单。
- **P3‑U6（P2）打磨**：铃铛/搜索键盘可达；空态/骨架一致；自主运行结果行内摘要可见。

### 6.3 Definition of Done（Phase‑3）
1. 后端 `pytest -q` 全绿（Phase‑2 P‑T1…P‑T8 回归 + 新增 P3‑T1…P3‑T5）；前端 `tsc --noEmit` 0 error、`next build` 成功。
2. P0 项（支柱 A 自主编排 claim/autorun/tick + 通知中心核心 + 行级 RBAC + 相关后端测试）**全部落地并演示 P3‑U1、P3‑U2**。
3. P1 项尽量完成；未完成项以 `# TODO(phase3-...)`/`# TODO(phase4-...)` 明确标注，**不得声称已做**。
4. **不破坏** Phase‑1/2 任何契约与既有验收（T1–T8 / U1–U6 / P‑T1…P‑T8 / P‑U1…P‑U5 仍通过），**唯一有意例外**：`agent-advance` 的 RBAC 收紧使 P‑T7 的 `test_member_can_comment_and_advance` 须按 §2.4「Agent 推进契约收紧说明」改写〔R3‑01〕——此为**明示的契约变更**，不得掩盖为「零变更」。
5. 前后端可启动无报错，数据落 SQLite 且重启不丢（新增 `notifications` 表首启自动建）。

---

## 7. Risks & Mitigations（风险与缓解）

| 风险 | 影响 | 缓解 |
|---|---|---|
| **自主编排绕过状态机** | 数据不可信、看板错乱 | `agent_autopilot` **只调用** `agent_runner.advance_one`（其内已强制 `can_transition`），不新增任何直接改 status 的路径；P3‑T1 断言目标 ∈ 允许集 |
| **并发自主运行重复推进 / 竞态** | 同一 Agent 被推两遍、position 错乱 | `agent.status=="busy"` 软锁：运行中再次 `autorun` → 409；单机单库足够；分布式记 `# TODO(autopilot-scale)` |
| **autorun 长循环挂起** | 服务端阻塞 | 单工单 `MAX_AGENT_STEPS=6` + 全局 `MAX_AUTOPILOT_STEPS=24` 双上限；命中「无动作」即停；`finally` 必解锁 |
| **通知风暴 / 自我通知噪声** | 用户被淹没 | `notify` 跳过「收件人==施动者」；helper 内 `set` 去重；`autorun-all` 每单只发一次 advance 通知；agent 不作收件人 |
| **收紧 RBAC 误伤既有正向用例** | 测试红 / 回归 | 新矩阵多数只收紧「member 侧本无正常入口」的写操作（删/改派/转/autopilot），正常 UI 路径无回归（§2.4）。**唯一有意的契约变更**：`agent-advance` 从「仅需登录」收紧为门禁（防旁路新 move/patch RBAC），须改写 `test_member_can_comment_and_advance` 并诚实标注，**不掩盖为零变更**〔R3‑01〕 |
| **乐观并发误报冲突** | 正常拖拽被拦 | `expected_updated_at` **缺省不校验**（向后兼容）；仅当前端显式携带且与库不一致才 409；比对为**精确 ISO 串（微秒）相等**、SQLite `DateTime` 往返保留微秒，故同值必等、他人已写（`onupdate`）必不等〔R3‑05〕|
| **通知实时性（轮询延迟 ~20s）** | 非即时 | 明确为「近实时」；`refreshInterval` 可调；WebSocket/SSE 延期 `# TODO(phase4-realtime)`，不夸大为「实时推送」|
| **`db.create_all` 不做列级迁移** | 若未来改既有列会漏迁移 | 本 Phase **仅新增 `notifications` 表**、零既有列变更，`create_all` 安全；列级演进引 Alembic（`# TODO(migrations-alembic)`）|
| **删单遗留悬挂通知** | 点击直达到已删单报错 | `delete_requirement`/`delete_bug` 一并删该单 `notifications`（同 Phase‑2 删评论策略）；前端点击已删单目标做 404 兜底 |
| **检索 `LIKE %q%` 全表扫描** | 大数据慢 | MVP 单机工单量级无压力；`status` 已有索引助过滤；大规模再引全文索引/外部搜索（`# TODO(search-scale)`）|
| **前端新增运行时依赖引入不稳定** | 构建/体积风险 | Phase‑3 前端**零新增运行时依赖**（通知轮询用既有 SWR，无 WS 库）|

---

## 8. 交付顺序与实施建议（供下游「代码开发」节点参考）

建议实现顺序（先立地基，再铺价值，最后收口）：

1. **通知地基（P0）**：`models/notification.py` → `models/__init__.py` → `services/notifications.py` → `routes/notifications.py` → 注册蓝图 → 在 assign/comment/convert 写路径接扇出。此时后端「协作感知」数据面齐备。
2. **自主编排（P0）**：`services/agent_autopilot.py`（复用 `agent_runner.advance_one`）→ `routes/agents.py` 挂 `claim-next/autorun/tick/autorun-all`（busy 软锁）→ 自主推进处接 `notify_advance`。**演示 P3‑U1**。
3. **RBAC + 并发 + 检索（P0/P1）**：`auth_helpers` 扩展 → requirements/bugs 接矩阵 + `expected_updated_at` 守卫 + list 过滤 → `users.py` 加 `/me/work`。
4. **后端测试（P0/P1）**：`conftest` 补 fixture → `test_agent_autopilot`/`test_notifications`/`test_rbac`(扩)/`test_concurrency`/`test_search`。**先让 `pytest` 全绿**（含 Phase‑2 回归）。
5. **前端协作感知层（P0）**：`lib/types.ts`/`constants.ts` → `useNotifications` → `NotificationBell` → `Header` 挂铃铛 + 搜索 → Agents 页自主按钮。**演示 P3‑U2**。
6. **前端收口（P1）**：`useTicket`/`useBoard` 携 `expected_updated_at` + 409 分流；列表过滤条；`my-work` 页 + Sidebar 导航；board 页读 `?ticket=` 自动开抽屉。
7. **打磨（P2）**：@提及输入辅助、通知全量页、键盘可达、行内摘要。

> **契约铁律（延续 Phase‑1/2）**：status key 集合、错误响应 shape（含 `allowed`）、JWT identity=str、看板/列表/feed 既有返回 shape、`agent-advance` 语义 **一律不变**；Phase‑3 所有接口均为**新增或向后兼容变更**。任何对既有契约的改动都必须回到本 spec 与 Phase‑1/2 spec 同步评审。

---

## 9. 交付清单摘要（给下游的最小实现集）

1. **后端**：`notifications` 表 + 通知接口（列表/未读数/已读/全部已读）+ 事件扇出；`agent_autopilot`（claim‑next/autorun/tick/autorun‑all，busy 软锁，全程走 `workflow`）；行级 RBAC（**复用既有 `require_role`** + 新增 `can_manage_ticket` + 矩阵，见 R3‑03）；`move`/`patch` 乐观并发守卫；列表过滤/检索 + `GET /me/work`（承载于新增 `me` 蓝图，见 R3‑02）。
2. **后端测试**：`test_agent_autopilot`/`test_notifications`/`test_concurrency`/`test_search` 新增 + `test_rbac` 扩充 + `conftest` 补 fixture，`pytest -q` 全绿（含 Phase‑2 回归）。
3. **前端**：`NotificationBell` + `useNotifications` + Header 铃铛/全局搜索；Agents 页自主运行按钮（claim/autorun/tick/autorun‑all）；`useTicket`/`useBoard` 并发守卫 + 409 分流；列表过滤条；`my-work` 页 + Sidebar 导航；board 页 `?ticket=` 直达。
4. **文档**：本 spec + README 追加 Phase‑3 能力与运行方式。
5. **端到端**：P3‑U1（自主闭环）与 P3‑U2（通知中心）为标志性演示；P3‑U3…P3‑U5 通过；Phase‑1/2 全部既有验收回归不破。

---

*本文档为 Phase‑3 **v2**（Iteration 3/3 · Solution Architect 产出 v1 → Senior Reviewer 评审并就地修复 P0/P1 后升 v2），建立在 Phase‑2（`docs/plans/aragonteam-phase2/spec.md` v2，commit `bbd64bb`）与 Phase‑1（commit `91507c2`）之上，仅做向后兼容的增量演进与收官。核心主张：让协作「自己转起来」（Agent 自主认领并推进）、让每个人「看得见与自己相关的一切」（通知中心），并收口权限 / 并发 / 检索三条工程质量线，以确定性、零新依赖、可回归测试兑现全局目标「稳健、可靠、顶级」。*

---

## 评审结论（Review Verdict · v2）

**判定：有条件通过（Approved with conditions）。**

### 总评
本方案是建立在两轮已评审 Phase 之上的**收官型增量设计**，四维度均属高水准：

- **可行性**：核心主张逐条与真实代码交叉验证通过（见「## 评审记录」证据清单）——支柱 A 完全复用 `agent_runner.advance_one`（不 commit、内建 `can_transition` 复核）、乐观并发比对 `updated_at`（微秒精确串、SQLite 往返保真）、列表过滤 + `X-Total-Count` 分页头、409 前端 `allowed` 分流、通知施动者概要复用 `summary()`——**均可用现栈直接落地，零新增运行时依赖**，符合本产品一贯的稳健取向。
- **完备性**：错误路径（busy 软锁 409、`finally` 解锁、NoAgentAction→skip、双步数上限、删单级联删通知、并发 409 与状态机 409 区分）与上线路径（`create_all` 仅新增表、无列级迁移风险）均已覆盖；诚实的 Out‑of‑Scope（§2.8）与 `# TODO` 标注到位，不夸大。
- **一致性**：严守「status key 集合 / 错误体 `{error,detail?}`（+`allowed`）/ JWT identity=str / 既有返回 shape / `agent-advance` 语义」等契约铁律；发现的 2 处不一致（R3‑01 `agent-advance` 契约逆转、R3‑02 `/me/work` 蓝图错配）已在 v2 就地修复。
- **合理规模**：34–40 文件、P0/P1/P2 分级得当，P1/P2 可优雅降级；未见过度设计（唯一 schema 变更是新增 `notifications` 表）。R3‑04（board.py 只读）等误标已纠正。

### 处置结果
- **P0：0 项。**
- **P1：2 项（R3‑01、R3‑02），均已在 v2 正文就地修复。**
- **P2：4 项——R3‑03/04/05 已就地修复；R3‑06（claim‑next 与 assign 逻辑 DRY）记为非阻断落地建议。**
- 文首「## 评审记录」列全部问题、严重度、位置与处置；正文修复处均以 `〔R3‑0x 修复〕` 锚定，可追溯。

### 放行条件（下游「代码开发」节点落地时**必须遵循**）
1. **〔R3‑01｜硬约束〕** `agent-advance` 的 RBAC 收紧是**有意的契约变更**：必须改写 `test_rbac.py::test_member_can_comment_and_advance`（member 评论仍 201；member 对**非归属**单 `agent-advance` 断言 **403**；200 正路改用 reporter/归属 assignee/pm），并在报告中**如实说明此为契约变更**，严禁声称「Phase‑2 用例逐字零变更全绿」。
2. **〔R3‑02｜硬约束〕** `GET /api/me/work` 必须承载于新增 `me` 蓝图（`url_prefix="/api/me"`）并在 `routes/__init__.py` 注册；**不得**挂进 `users` 蓝图（否则路径退化为 `/api/users/work`，违反 §4.3 契约）。
3. **〔R3‑03｜硬约束〕** 复用既有 `require_role`，**不新增** `require_roles`；本 Phase 只新增 `can_manage_ticket`，保持 403 响应体形状一致。
4. **〔并发守卫实现要点〕** `move` 的同列早退分支（`frm==to`）也须先过 `expected_updated_at` 守卫；比对取 `db.session.get()` 的当前已提交值。
5. **〔建议·非阻断｜R3‑06〕** 尽量抽取 `assign_ticket` 共享 helper 供路由与 autopilot 共用，避免认领/指派逻辑分叉。

满足上述条件后，本方案可直接进入实现。**Verdict：有条件通过（Approved with conditions）。**

---

## 实施过程发现的方案缺陷（Issues Found During Implementation · 代码开发节点补记）

> 记录人：实现工程师。原则：不静默偏离方案，凡文件变更计划（§3）未逐字列出但实现所需的支撑件，均在此诚实标注。

- **I3-01（文件计划轻微不完整·已按方案意图补齐）**：§3.3 把列表页过滤条与通知铃铛的实现「折叠」进
  `requirements/page.tsx` / `bugs/page.tsx` / `NotificationBell.tsx`，未单列其**共享支撑组件**。实现时为
  避免两张列表页重复过滤 UI、并复用施动者头像渲染，新增了三处小支撑件（**均不改任何对外契约、不新增运行时依赖**）：
  - `frontend/components/FilterBar.tsx`［新］——列表页过滤条（关键字 / 状态 / 优先级或严重度 / 指派人），
    `requirements` 与 `bugs` 列表页共用；实现 §2.6 的过滤 UI。
  - `frontend/components/ui/Avatar.tsx` 增 `AuthorAvatar`——由施动者概要渲染头像（user/agent 常规头像、
    system/空施动者用中性圆底 + fallback 图标），供 `NotificationBell` 与通知全量页复用（与既有 `AssigneeAvatar` 同策略）。
  - `frontend/components/AssigneePicker.tsx` 改——`label` 为空时不渲染 `<label>`，使其能在过滤条中内联复用（无标签）。
  这与 Phase-1 为实现 toast 提示而补 `lib/toast.tsx` 的先例一致，属实现层组件抽取，非设计缺陷。
- **I3-02（P2 通知全量页·已做）**：§3.3 将 `app/(app)/notifications/page.tsx` 标为 P2，本次一并实现
  （下拉之外的完整列表 + 一键已读），Sidebar 未新增其导航（通过铃铛「查看」入口足够，避免导航过载）。
- **I3-03（R3-06 采「交叉引用」而非抽取 helper）**：`services/assignment.py::assign_ticket` 未新建（该文件不在 §3.1
  计划表内，且约束要求不新增计划外文件）；改在 `agent_autopilot._claim_from_lane` 内以注释交叉引用
  `routes.requirements.assign_requirement` / `routes.bugs.assign_bug` 保持对齐——即 R3-06 明示的非阻断兜底方案。

以上均为向后兼容的实现层选择，未偏离方案的对外契约与验收目标；后端 pytest 93 全绿、前端 `tsc --noEmit` 0 error、
`next build` 15/15 成功，端到端 P3-U1（自主闭环）/ P3-U2（通知中心）实机联调通过。
