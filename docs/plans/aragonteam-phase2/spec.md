# AragonTeam Phase‑2 — 从「可运行骨架」到「可信的 Agent 协作平台」（Spec）

- **文档版本**: **v2**（Iteration 2/3 · Solution Architect 产出 → Senior Reviewer 评审并就地修复 P0/P1）
- **Feature slug**: `aragonteam-phase2`
- **作者角色**: Solution Architect（Anthropic Engineering）
- **状态**: Reviewed —— 已通过下游「方案评审与修复」节点评审（见 [§评审记录](#评审记录review-notes--senior-reviewer) / [§评审结论](#评审结论review-verdict)）：**有条件通过**，P0/P1 已在本 v2 就地修复，可进入实现
- **目标读者**: 下游开发工程师（须可据此逐行实现，无需再做架构决策）
- **基线**: 本方案**建立在已合入的 Phase‑1 MVP 之上**（commit `91507c2`，见 `docs/plans/aragonteam-mvp/spec.md` v2），不推翻既有契约，仅做**增量演进与加固**。
- **技术栈（沿用）**: Next.js 14 App Router + React 18 + TypeScript + Tailwind ｜ Flask 3 + SQLAlchemy 2 + SQLite ｜ flask‑jwt‑extended ｜ @dnd‑kit。**不新增后端第三方依赖**（pytest 仅为开发期依赖），前端**不新增运行时依赖**。

---

## 评审记录（Review Notes · Senior Reviewer）

> 评审人：Anthropic Engineering 资深评审（下游「方案评审与修复」节点）。评审维度：**可行性（Feasibility）/ 完备性（Completeness）/ 一致性（Consistency）/ 适度性（Right‑sizing）**。
> 评审方式：**逐文件核对 Phase‑1 实到代码**（`backend/` 24 个 py + `frontend/` TS/TSX），确认本方案对既有契约的引用**属实**——`workflow.can_transition/next_states/is_terminal` 邻接表、`Activity.log(entity_type, entity_id, action, actor=(type,id), …)` 签名、`Agent.summary()`/`User.summary()`、`_validate_assignee`/`_next_position`/`_actor`、`routes/requirements.py:90` 确未校验 `project_id`、`# TODO(board-reorder)` 确在 move、`AssigneeAvatar` 组件存在、`@dnd-kit/sortable`+`@dnd-kit/utilities` 确已在 `package.json` 声明、真实外键 `reporter_id`/`owner_id`/`related_requirement_id`/`project_id` 均存在。**AGENT_FORWARD 每条边已逐条对照邻接表确认为合法前进边。**
> **结论先行：方案整体可行、右尺寸得当、与 Phase‑1 契约一致；共记 4×P1 + 3×P2。P1 已在本 v2 正文就地修复，P2 列为实现期须遵守的条件。**

| # | 维度 | 严重度 | 位置 | 问题 | 处置 |
|---|---|---|---|---|---|
| R‑01 | 可行性 | **P1** | §2.5‑3 / §3.3 / §4.4 | 新增响应头 `X-Total-Count`、`X-Request-Id` 在**跨域**（前端 `:3000` → 后端 `:5000`）下浏览器 JS **默认不可读**，须 Flask‑CORS `expose_headers` 放行；且现有 `lib/api.ts` 的 `request()` 只回 body、**丢弃 response headers**，前端根本取不到。原文「前端可无感、渐进读取」在浏览器侧不成立（`pytest` test client 同源可过，故仅前端受影响）。 | 已修复：§2.5 增列 CORS `expose_headers` 硬要求；§3.3/§4.4 补「api.ts 需增返回 headers 的读取路径」。 |
| R‑02 | 可靠性 | **P1** | §2.5‑5 / §6.1 | `TestConfig` 用 `sqlite:///:memory:` **未固定连接池**：单线程 pytest 通常可用，但依赖 SQLAlchemy 对 `:memory:` 默认的 `SingletonThreadPool` 且**要求建表与请求同线程**；一旦 app‑fixture 跨线程或接 `pytest-xdist`，立即 `no such table`。测试套件是本 Phase 的可靠性硬指标，不容此类隐性抖动。 | 已修复：§2.5‑5 明确 `TestConfig` 固定 `poolclass=StaticPool` + `connect_args={"check_same_thread": False}`，conftest 在同一 app fixture 内建表。 |
| R‑03 | 可靠性 | **P1** | §2.5‑4 / §3.2 / §6.1 | 登录限流为**进程级模块字典**，跨用例不复位；`test_auth` 内多条「失败登录」用例会互相污染计数，P‑T2 的 429 断言**非确定**（测试顺序敏感）。 | 已修复：限流存储挂到 `app`（随每个测试 app 实例重建），并要求 conftest 提供 `autouse` 复位 fixture。 |
| R‑04 | 一致性/诚实 | **P1** | §2.2 / §2.2.3‑5 / §6.2 P‑U3 | 单步同步 `agent-advance` 内 `agent.status` 先 `busy` 后 `idle` 处于**同一事务、单次 commit**，外部观察者**永不可能看到 `busy`**；而 §2.2「busy↔idle 切换」与 P‑U3「Agent 状态短暂 busy」被列为**可验收项**，与 DoD 第 3 条「不得声称已做」相悖，且会诱导实现者用 `sleep` 造假 busy 窗口（损害「可靠」）。 | 已修复：单步终态明确为 `idle`；**可观测的进度信号改为前端按钮 loading 态**；`busy` 窗口仅在 `run=all`（每步 commit）下才有意义，据此改写 §2.2 / §2.2.3 / P‑U3。 |
| R‑05 | 完备性 | P2 | §2.8‑2 | `PRAGMA foreign_keys=ON` 的 `connect` 监听须**限 SQLite 方言**（未来接 Postgres 对非 SQLite 连接发 PRAGMA 会报错）；并须验证既有 `delete_requirement`（已先置空关联 BUG）/`delete_bug`/seed 插入顺序在强制开启后仍全绿。**已核：无 user/project 删除端点，删除路径安全、seed 依赖序正确**，风险低但须留守卫。 | 正文补方言守卫 + 验证说明；列为实现期条件。 |
| R‑06 | 一致性 | P2 | §2.8‑5 | 仅新增 `.eslintrc.json` 而 `package.json` **无 `eslint`/`eslint-config-next` 依赖**，`next lint` 首跑仍会**交互式**索求安装，与「避免交互式默认」初衷冲突。 | 正文改为：或同时补齐 eslint devDependencies，或仅保留 `typecheck` 作为唯一硬门禁（`next lint` 不作门禁）。 |
| R‑07 | 一致性 | P2 | §2.5‑5 | 既有 `config.py` 以 **`DATABASE_URL`** 环境变量读库 URI；§2.5‑5 却以 `SQLALCHEMY_DATABASE_URI` 命名，会引入**第二个冲突开关**。 | 正文统一沿用既有 `DATABASE_URL` 名，README 环境变量表对齐。 |

**其余审阅意见（无需改动，留痕）**：feed 的 activity `actor` / comment `author` 概要解析与既有 `_resolve_assignee` 同构、可行（N+1 查询在 MVP 单工单量级可接受，已有 `ix_activities_entity` + 新 `ix_comments_entity` 索引 + feed `limit` 兜底）；删单级联删评论、多态无外键 `to_dict` join 失败降级占位等策略与 Phase‑1 一致；`Activity.entity_id` 为普通整型（非外键），故 §2.8‑3 delete 补审计不受 FK 强制影响。范围（新增/改 ~30–36 文件）对「MVP 深化」适度，无过度设计。

---

## 0. 背景：Phase‑1 交付了什么，Phase‑2 为什么存在

Phase‑1（Iteration 1）已交付一套**可运行的全栈骨架**：登录鉴权、用户/Agent/项目/需求/BUG 的 CRUD、需求 7 态 / BUG 5 态的状态机（邻接表为唯一事实来源）、看板拖拽 + 乐观更新 + 409 回滚、需求转 BUG、审计时间线、以及已落地的 Anthropic 暖色浅色设计系统。后端 25 个 Python 文件、前端 44 个 TS/TSX 文件，端到端可跑通 T1–T8 / U1–U6。

但对照全局目标「**稳健、可靠、顶级**」以及本产品的立身之本——「**AI 时代（Agent 可参与协作）的开发协作管理平台**」——当前实现存在三处**结构性欠账**：

1. **Agent 只是一个静态字段，并未真正「参与协作」。** 现状里 `assignee_type='agent'` 仅表示「这张单被指派给了某个 Agent」，Agent 既不会推进工单、不会留下工作痕迹、也不会改变自身状态（seed 后恒为 `idle`）。产品的**核心差异化价值——Agent 作为一等执行者与人类混合协作——在 UI 与数据流上几乎不可见**。这是 Phase‑2 的第一优先级。
2. **缺少「讨论」与「工单详情」这一层协作基础设施。** 卡片不可点击，`GET /requirements/:id/activities` 有接口却无 UI 消费；人与 Agent 无法在工单上留言/评论。协作平台没有讨论区，是不完整的。
3. **缺少自动化测试与若干可靠性护栏。** 仓库内**没有提交任何后端测试**（Phase‑1 的 T1–T8 是一次性手测），列表接口无分页、无结构化日志/请求追踪、登录无限流、500 未显式回滚事务。这些是「稳健、可靠」的硬指标。

Phase‑2 的使命，就是把这三处欠账补齐，把「可运行的骨架」升级为「**可信的 Agent 协作平台**」：Agent 真的会干活、会说话、会在时间线里留痕；每张工单有详情抽屉与人机混合讨论流；核心链路由一套可回归的自动化测试守护。

---

## 1. Overview（概述）

**AragonTeam Phase‑2** 围绕一条主线展开：**让「Agent 参与协作」从一句 slogan 变成可交互、可追溯、可测试的真实机制**。为此引入三根支柱：

- **支柱 A — Agent 协作运行时（Agent Collaboration Runtime）**：新增 `agent_runner` 领域服务与 `POST /api/{requirements|bugs}/:id/agent-advance` 接口。当一张工单被指派给 Agent 后，用户（或 PM）可点「让 Agent 处理下一步」，Agent 便会**按状态机推进工单一步**、以自己的身份**发一条工作说明评论**、写一条 `actor_type=agent` 的审计记录。**〔R‑04 修订〕** 单步推进是**同步、单事务**的：Agent 的**已提交终态恒为 `idle`**，用户看到的「正在处理」进度信号来自**前端按钮的 loading 态**（可观测），而非后端瞬时 `busy`——在一次 commit 内 `busy→idle` 对任何外部观察者都不可见，故本方案**不以后端 `busy` 作为可验收项**。`busy` 仅在 `run=all`（每步各自 commit，见 §2.2.3）这种多步连续处理下才产生可观测窗口。该运行时是**确定性的离线模拟**（不依赖外部 LLM）——这是刻意的架构选择：它演示的是**协作的机制与数据落点**（Agent 会移动卡片、会留言、会进时间线），而机制一旦成立，未来把「模拟推进」替换为「真实 Agent 调用」只是替换 `agent_runner` 内部一个函数的实现，接口、数据模型与前端完全不变。确定性也意味着**可被单测覆盖、无网络抖动**，天然契合「稳健、可靠」。

- **支柱 B — 讨论与工单详情（Discussion & Ticket Detail）**：新增 `comments` 表与评论接口，新增一个统一的**协作时间流（feed）**接口，把「审计活动（activity）」与「评论（comment）」按时间合并成一条人/Agent/系统混合的可读流。前端新增一个 **TicketDrawer（工单详情右侧抽屉）**：点击任意看板卡片或列表行即可展开，内含「详情 / 协作」两区——协作区就是那条混合 feed，底部带评论输入框，指派给 Agent 时还带「让 Agent 处理」动作。这一层把产品的核心价值主张**第一次呈现在用户眼前**。

- **支柱 C — 可靠性加固与顶级打磨（Reliability & Polish）**：后端补齐结构化日志 + 请求 ID、列表分页（`limit/offset` + `X-Total-Count`，非破坏性）、登录限流、全局 500 事务回滚、按环境变量读取配置；并**提交一套 pytest 测试套件**覆盖鉴权、CRUD、状态机、Agent 运行时、评论、RBAC 等核心链路。前端补齐骨架屏、空状态、错误边界、看板同列拖拽重排（收口 Phase‑1 的 `board-reorder` TODO），并把仪表盘从纯数字升级为带分布可视化的一屏。

Phase‑2 **不改动** Phase‑1 已确立的任何对外契约（status key 集合、错误响应体 `{error, detail?}`、JWT identity=str、看板/列表返回 shape），全部改动均为**向后兼容的增量**。范围上仍属「MVP 深化」而非重写：预计新增/修改约 30–36 个文件，其中后端 ~14、前端 ~18、文档/配置 ~4。

---

## 2. Technical Design（技术设计）

### 2.1 架构增量（Delta，相对 Phase‑1）

```
┌──────────────────────────── Browser (Next.js) ─────────────────────────┐
│  既有：Sidebar + Header + Content · 看板 dnd · SWR · AuthContext         │
│  ＋ TicketDrawer（右侧抽屉：详情 + 协作 feed + 评论框 + 让Agent处理）      │  ← 新增
│  ＋ Skeleton / EmptyState / error.tsx 错误边界                           │  ← 新增
│  ＋ 看板同列可排序（@dnd-kit/sortable）                                   │  ← 增强
└───────────────▲─────────────────────────────────────────────────────────┘
                │  HTTP/JSON, Bearer JWT
┌───────────────┴──────────────── Flask (create_app) ────────────────────┐
│  既有 Blueprints: auth users agents projects requirements bugs board stats│
│  ＋ comments 蓝图（GET/POST 评论、GET feed 合并流）                        │  ← 新增
│  ＋ routes 内挂载 agent-advance（复用 requirements/bugs 蓝图）             │  ← 新增
│  Services: workflow（不变，仍是迁移唯一裁决）                              │
│  ＋ agent_runner.py（Agent 单步推进的确定性模拟）                          │  ← 新增
│  ＋ pagination.py（limit/offset 解析 + X-Total-Count）                    │  ← 新增
│  ＋ observability：结构化日志 + request-id + after_request 访问日志        │  ← 新增
│  ＋ ratelimit：登录滑动窗口限流（内存版）                                  │  ← 新增
│  ORM → SQLite: users agents projects requirements bugs activities        │
│  ＋ comments 表（新增，additive，db.create_all 自动建）                    │  ← 新增
└───────────────▲─────────────────────────────────────────────────────────┘
                │  pytest（内存 SQLite，独立 TestConfig，不 seed）
        ┌───────┴────────┐
        │ backend/tests/ │  auth / requirements / bugs / workflow /
        │  （新增）       │  agent_runner / comments / rbac / health
        └────────────────┘
```

**关键不变量（下游必须保持）**：迁移合法性**仍且只由 `services/workflow.py` 邻接表裁决**——Agent 推进工单也**必须**走 `can_transition`，绝不能因为「是 Agent 在推进」就绕过状态机。这保证了「人推」和「机推」共用同一套合法性真理，是本产品可信度的地基。

### 2.2 支柱 A：Agent 协作运行时（核心）

#### 2.2.1 设计原则

- **不依赖外部 LLM**：Phase‑2 的 Agent「工作」是**确定性模拟**——按预置的「Agent 前进路径」推进一步 + 生成模板化工作说明。理由：(1) 可被单测断言、(2) 无网络/密钥依赖、无抖动，契合「稳健可靠」、(3) 接口与数据模型即为未来接真实 Agent 预留的插槽，替换点单一（`agent_runner._perform`）。
- **绝不绕过状态机**：推进的每一步都调用 `workflow.can_transition`；若「Agent 前进路径」给出的下一步恰好非法（理论不应发生，但需防御），返回 409，不改库。
- **每一步都留痕**：一次成功推进产生「**1 条状态迁移 + 1 条 Agent 评论 + 1 条 activity（actor=agent）**」，三者在同一事务内提交，保证时间线与看板一致。

#### 2.2.2 「Agent 前进路径」映射（AGENT_FORWARD）

在 `agent_runner.py` 内定义按 `(entity, agent.kind, current_status)` 查「下一步目标态」的表。语义：**该 Agent 在此状态下会把工单推进到哪一步**（均为 workflow 邻接表内的合法前进边）：

需求（requirement）：

| agent.kind | 当前态 | Agent 推进到 | 工作说明（评论模板，示意）|
|---|---|---|---|
| `dev` | `assigned` | `in_development` | 「dev‑agent 已认领需求，拆解任务、拉起开发分支。」|
| `dev` | `in_development` | `testing` | 「dev‑agent 完成实现与自测，提交变更，转入测试。」|
| `dev` | `bug_fixing` | `testing` | 「dev‑agent 已定位并修复缺陷，回归自测通过，转回测试。」|
| `qa` | `testing` | `reviewing` | 「qa‑agent 执行测试用例通过，转入审批。」|
| `generic` | `assigned` | `in_development` | 「agent 已认领需求并开始处理。」|

BUG（bug）：

| agent.kind | 当前态 | Agent 推进到 | 工作说明 |
|---|---|---|---|
| `dev` | `assigned` | `fixing` | 「dev‑agent 已认领缺陷，开始定位根因。」|
| `dev` | `fixing` | `verifying` | 「dev‑agent 提交修复，转入验证。」|
| `qa` | `verifying` | `closed` | 「qa‑agent 验证修复通过，关闭缺陷。」|
| `generic` | `assigned` | `fixing` | 「agent 已认领缺陷并开始处理。」|

> 未命中表（该 kind 在该状态下无预置动作）→ 返回 `409 {error:"agent has no action for this state", detail:{kind, status}}`，不改库。这让「dev‑agent 处理审批中的需求」这类越界请求被明确拒绝，而非乱推。

#### 2.2.3 关键代码路径：`POST /api/requirements/:id/agent-advance`

1. `@jwt_required()`；取 `req`，404 保护。
2. **前置校验**：`req.assignee_type == "agent"` 且 `req.assignee_id` 指向存在的 Agent，否则 `409 {error:"ticket is not assigned to an agent"}`。
3. 查 `AGENT_FORWARD[("requirement", agent.kind, req.status)]` → 得目标态 `to`；未命中 → 409（见上）。
4. **防御性复核**：`workflow.can_transition("requirement", req.status, to)` 必须为真，否则 `500`（表配置错误，记日志）。
5. 事务内：更新 `req.status=to`、`req.position=_next_position(...)` → 写 `Comment(author_type="agent", author_id=agent.id, body=模板)` → `Activity.log(action="agent_advanced", actor=("agent", agent.id), from_status, to_status=to, message=...)`。**〔R‑04 修订〕单步不切 `busy`**：`busy→idle` 若同处一次 commit 则对外不可见（纯死写），故**单步推进 Agent 终态即 `idle`，不写 `busy`**；进度反馈交给前端按钮 loading 态。
6. `db.session.commit()`；返回 `200 {ticket: req.to_dict(), comment: comment.to_dict(), agent: agent.to_dict()}`（`agent.status=="idle"`）。
7. BUG 侧 `POST /api/bugs/:id/agent-advance` 逻辑同构（entity="bug"）。

> **run‑to‑completion（P1 增强）**：`POST /api/requirements/:id/agent-advance?run=all` 时，服务端**先把 `agent.status="busy"` 并 commit**，再在一个循环里连续 `advance`——**每步各自 commit**（评论+activity+状态各持久化一次），直到：命中「无预置动作」（如 dev 推到 `testing` 后需 qa 接手）、或到达终态、或达 `MAX_AGENT_STEPS=6` 上限（防死循环）；循环结束（含异常路径）在 `finally` 中把 `agent.status="idle"` 并 commit。**〔R‑04〕唯有 `run=all` 因逐步 commit 才让 `busy` 成为可观测窗口**——这也是 §2.2/P‑U3 里 `busy` 语义的唯一落点。核心版先实现单步（终态 `idle`）；`run=all` 作为 P1。

#### 2.2.4 前端呈现

- 卡片 `KanbanCard` 的 `assignee` 为 Agent 时，卡片右下角显示一枚小机器人标识（已有 `AssigneeAvatar` 支持）。
- **TicketDrawer**（见 §2.4）在「协作」区顶部，当 `ticket.assignee_type==="agent"` 时渲染一个 primary 按钮 **`▶ 让 {agentName} 处理下一步`**：点击 → `POST .../agent-advance` → 成功后 `mutate` 抽屉内的 ticket + feed（新评论/新状态立刻出现），并 `mutate` 看板数据（卡片自动移列）。处理中按钮 `loading`。若返回 409（无预置动作/未指派 Agent）→ toast 说明。

### 2.3 支柱 B（数据侧）：评论模型与合并 feed

#### 2.3.1 `comments` 表

见 §5。要点：多态作者 `author_type ∈ {user, agent, system}` + `author_id`（system 可空）；`entity_type ∈ {requirement, bug}` + `entity_id`；`body` 文本；`created_at` 索引。`to_dict()` 按 `author_type` join 出作者概要（复用 `User.summary()` / `Agent.summary()`；system 返回固定 `{type:"system", name:"系统"}`）。

#### 2.3.2 合并 feed 的构造

`GET /api/{requirements|bugs}/:id/feed` 返回**按 `created_at` 升序合并**的混合流，每个元素带 `kind` 判别字段：

```jsonc
{ "items": [
  { "kind": "activity", "id": 1, "action": "created", "from_status": null,
    "to_status": "new", "actor": {"type":"user","id":2,"name":"Peter"},
    "message": "创建需求「…」", "created_at": "…Z" },
  { "kind": "comment", "id": 5, "author": {"type":"agent","id":1,"name":"dev-agent","kind":"dev"},
    "body": "dev-agent 已认领需求…", "created_at": "…Z" }
] }
```

后端实现：分别查 activities 与 comments，规整为统一 dict（activity 的 `actor` / comment 的 `author` 都解析成概要对象），合并后 `sorted(key=created_at, then kind priority)`。前端只需渲染 `items`，无需二次拉取与合并——把复杂度收在后端，前端更薄、更稳。

> 兼容性：Phase‑1 的 `GET /requirements/:id/activities` **保留不动**（仪表盘不受影响）；`feed` 为新增聚合视图。

### 2.4 支柱 B（前端）：TicketDrawer 工单详情抽屉

统一组件 `frontend/components/TicketDrawer.tsx`，需求/BUG 共用（以 `entity` 区分）。

- **触发**：`KanbanCard` 与列表行新增 `onClick` → 打开抽屉（拖拽与点击互斥：拖拽用 `onPointerDown` 阈值/`isDragging` 守卫，点击仅在未拖动时触发；沿用 Phase‑1 卡内「转 BUG」按钮已验证的 `stopPropagation` 手法）。
- **结构**：右侧 slide‑over 面板（`fixed inset-y-0 right-0 w-[480px]`，半透明遮罩，Anthropic 暖色、`shadow-lift`、进出用 `transition-transform`）。
  - **Header**：`REQ/BUG-id` · 标题 · 状态徽章 · 优先级/严重度徽章 · 关闭按钮。
  - **详情区**：可编辑标题/描述/优先级（`PATCH /:id`）、`AssigneePicker`（复用，指派人或 Agent，`PATCH .../assign`）、reporter、创建/更新时间；需求在 `testing/reviewing` 显示「转 BUG」（复用既有逻辑）。
  - **协作区**：顶部条件渲染「让 Agent 处理下一步」（§2.2.4）；中部为 §2.3.2 的混合 feed（activity 与 comment 分别用不同视觉：activity 为细线时间轴小点 + 灰字，comment 为带作者头像的气泡，Agent 作者用机器人图标与 clay 描边区分于人类）；底部为评论输入框 `Textarea` + 发送（`POST .../comments`，成功后 `mutate` feed）。
- **数据**：抽屉内用 SWR 拉 `GET /:entity/:id` 与 `GET /:entity/:id/feed`；所有写操作成功后 `mutate` 这两者 + 外层看板/列表数据（保证抽屉与看板同步）。
- **可访问性**：`role="dialog" aria-modal="true"`，打开时焦点移入、`Esc` 关闭、关闭后焦点归还触发元素；遮罩点击关闭。

### 2.5 支柱 C：可靠性加固（后端）

1. **结构化日志 + 请求 ID**（`backend/observability.py`，在 `create_app` 内 `init_observability(app)`）：
   - 配置根/应用 logger：`logging.basicConfig` 或自定义 handler，格式含 `时间 级别 logger [request_id] message`。
   - `@app.before_request`：生成 `g.request_id = uuid4().hex[:12]`（若入参带 `X-Request-Id` 则透传）。
   - `@app.after_request`：记 `method path status 耗时ms request_id`；并回写响应头 `X-Request-Id`。
   - 500 分支记 `logger.exception`（含堆栈，仅入日志，不入响应体——沿用 §Phase‑1 2.6「不泄露堆栈」）。
2. **全局 500 回滚**（改 `errors.py`）：`@app.errorhandler(Exception)` 内**先 `db.session.rollback()`** 再返回 `{"error":"internal server error"}`,500，避免半提交事务污染后续请求。
3. **列表分页（非破坏性）**（`backend/services/pagination.py`）：新增 `paginate(query) -> (rows, total)`，读 `?limit=`（默认 50，上限 200）与 `?offset=`（默认 0）；在 `list_requirements`/`list_bugs`/`list_users`/`list_agents`/`GET comments` 等列表接口应用，响应体**仍是裸数组**（保持 Phase‑1 契约），仅**新增响应头 `X-Total-Count`**。前端渐进采用。**〔R‑01 修订〕** 该头是**跨域自定义响应头**，浏览器 JS 默认读不到，**必须**在 §7 的 CORS 配置里 `expose_headers` 放行（见下方新增第 7 条），否则前端 `fetch` 侧拿不到该值——`pytest` test client 同源可读，故此坑仅在浏览器暴露。
4. **登录限流**（`backend/services/ratelimit.py`）：内存滑动窗口，键为 `ip + ":" + username`，窗口 5 分钟内失败 ≥ `LOGIN_MAX_ATTEMPTS`（默认 10）→ `429 {error:"too many attempts, try later"}`。仅拦**失败**尝试；成功清零。明确标注为 MVP 单机版（重启即清空、多副本不共享），生产改 Redis（`# TODO(ratelimit-distributed)`）。**〔R‑03 修订，测试隔离〕** 限流计数**不得**用裸模块级全局字典——那样跨用例不复位、`test_auth` 的失败登录会互相污染、P‑T2 的 429 断言变得顺序敏感。落法二选一：(a) 把存储挂在 `app.extensions["ratelimit"]` 上，随每个测试的独立 `app` 实例自然重建；或 (b) 提供 `ratelimit.reset()` 并由 conftest `autouse` fixture 每用例前调用。`LOGIN_MAX_ATTEMPTS` 在 `TestConfig` 里调小（如 3）以便快测。
5. **配置按环境变量**（改 `config.py`）：`SECRET_KEY`/`JWT_SECRET_KEY`/`CORS_ORIGINS`/`JWT_ACCESS_TOKEN_EXPIRES`/`LOGIN_MAX_ATTEMPTS` 全部 `os.environ.get(..., 默认值)`。**〔R‑07 修订〕库 URI 沿用既有 `DATABASE_URL` 环境变量名**（`config.py` 现状即读 `DATABASE_URL` 落到 `SQLALCHEMY_DATABASE_URI`），**不要**另引 `SQLALCHEMY_DATABASE_URI` 环境变量以免出现两个冲突开关；README 环境变量表以 `DATABASE_URL` 为准。新增 `SEED_ON_STARTUP`（默认 True）控制 `app.py` 是否在启动时 seed——测试据此关闭并自建 fixture。
   - **新增 `TestConfig`（〔R‑02 修订，务必固定连接池〕）**：`SQLALCHEMY_DATABASE_URI="sqlite:///:memory:"`、`SEED_ON_STARTUP=False`、短 JWT 过期、`LOGIN_MAX_ATTEMPTS` 调小。**关键**：内存库**必须**显式固定连接池，否则依赖 SQLAlchemy 对 `:memory:` 的默认 `SingletonThreadPool`+同线程假设，跨线程/`pytest-xdist` 会 `no such table`。写法：
     ```python
     from sqlalchemy.pool import StaticPool
     SQLALCHEMY_ENGINE_OPTIONS = {
         "connect_args": {"check_same_thread": False},
         "poolclass": StaticPool,
     }
     ```
     `StaticPool` 让整个进程共用**同一条**内存连接，`conftest` 在同一 app fixture 的 app_context 内 `db.create_all()`，请求与建表遂共享该连接、表恒可见。注意这会**覆盖** base `Config` 的 `connect_args={"timeout":15}`（内存库无需 busy‑timeout，无副作用）。
6. **健康检查**：`GET /api/health` 已存在（`app.py`），Phase‑2 扩展返回 `{status, service, db: "ok"|"error"}`（做一次 `SELECT 1` 探活），供部署探针。DB 探活失败返回 `503`。
7. **CORS 暴露自定义响应头（〔R‑01 新增，P1〕）**：Phase‑2 新增 `X-Total-Count`（§2.5‑3）与 `X-Request-Id`（§2.5‑1）两个响应头，跨域下浏览器默认不可读。**必须**在 `create_app` 的 `CORS(...)` 里增配 `expose_headers=["X-Total-Count", "X-Request-Id"]`（Flask‑CORS `resources` 内或全局 `expose_headers`）。此为**新增配置项、非破坏**（既有响应体契约不变）。同时前端 `lib/api.ts` 需提供一个**返回 headers 的读取路径**（现有 `request()` 只回 body、丢弃 `res.headers`，无法取用；见 §3.3）。

### 2.6 支柱 C：看板同列拖拽重排（收口 board‑reorder TODO）

把 Phase‑1「落列尾、不重排」升级为**真正的同列/跨列精确插入**：

- **接口**：`PATCH /:id/move { status, position? }` 中 `position` 语义由「忽略」改为「**目标列内的目标插入索引**（0‑based）」。缺省仍追加列尾（向后兼容）。
- **后端**：在一个事务内对**目标列**做「取出该列有序卡 → 在 `position` 处插入本卡 → 从 0 连续重编号该列所有卡的 `position`」（`_reindex_column`）。跨列移动时源列可不重编号（其空洞不影响 `ORDER BY position, id`）或顺带压缩（择一，推荐目标列重编号即可，`# NOTE`）。仍先 `can_transition` 裁决跨列合法性；同列（`frm==to`）仅重排、不校验迁移。
- **前端**：`KanbanColumn` 改用 `@dnd-kit/sortable` 的 `SortableContext`（垂直列表），`onDragEnd` 依落点计算目标列 + 插入索引，`useBoard.move(cardId, toStatus, toIndex)` 携带 `position`。乐观更新按索引插入。**该依赖（`@dnd-kit/sortable`、`@dnd-kit/utilities`）Phase‑1 已在 `package.json` 声明**，无需新增。
- 优先级 **P2**：核心价值不依赖它；作为「顶级手感」增强，排在 A/B 与可靠性之后。

### 2.7 支柱 C：前端打磨（顶级 / HCI 最佳实践）

- **骨架屏** `components/ui/Skeleton.tsx`：看板列骨架、列表行骨架、抽屉骨架，替换现有「加载看板中…」纯文字。
- **空状态** `components/ui/EmptyState.tsx`：图标 + 标题 + 提示 + 可选 CTA；用于空列表、空看板列、无活动。
- **错误边界**：`app/(app)/error.tsx`（段级）、`app/global-error.tsx`（根级兜底）、`app/(app)/not-found.tsx`；统一 Anthropic 风格的「出错了/重试」界面，避免白屏。
- **仪表盘可视化升级** `dashboard/page.tsx`：把「需求分布/BUG 分布」从纯数字升级为**纯 CSS 水平占比条**（各态一行，条宽 = 占比%，配色取 `constants` 状态色）；新增「Agent 利用率」（busy/total 占比条）与「本周活动数」小计。**不引入图表库**（稳健，零新依赖）。
- **Agents 页增强** `agents/page.tsx`：每个 Agent 卡展示 `kind/status` 徽章、**当前指派工单数**（查 requirements/bugs where assignee=agent）与最近若干条该 Agent 的 activity；点工单跳看板。
- **无障碍拖拽（P2）**：`KanbanBoard` 挂 `@dnd-kit` 的 `KeyboardSensor`，卡片/列补 `aria-label`/`aria-roledescription`，支持键盘移动。
- **既有 Modal / Toast 可达性补强（P1）**：`components/ui/Modal.tsx` 补 `role="dialog"`/`aria-modal`/焦点陷阱；`lib/toast.tsx` 容器补 `role="status" aria-live="polite"`，让屏幕阅读器播报——与新增抽屉的 a11y 标准一致。

### 2.8 轻量加固清单（cheap hardening，逐条 P1，均为小改动）

审计确认的低成本、高性价比修补，实现时顺手完成、并各自补一条断言/说明：

1. **`project_id` 存在性校验**：`create_requirement`/`create_bug` 当前接受任意 `project_id` 不校验（`routes/requirements.py:90`）。改为：传了 `project_id` 时先 `db.session.get(Project, id)`，不存在返回 `400 {error:"project not found"}`。
2. **SQLite 外键 PRAGMA**：`extensions.py` 或 `app.py` 内注册 `@event.listens_for(Engine,"connect")` 执行 `PRAGMA foreign_keys=ON`，让既有真实外键（`reporter_id`/`owner_id`/`related_requirement_id`/`project_id`）在 DB 层生效（多态 assignee 仍靠应用层校验，语义不变）。**〔R‑05 修订，P2〕** 监听回调**须限 SQLite 方言**——`if dbapi_conn` 来自 sqlite 时才发 PRAGMA（对非 SQLite 连接发 `PRAGMA foreign_keys` 会报错，为未来接 Postgres 留后路）；实践上判 `dbapi_connection.__class__.__module__.startswith("sqlite3")` 或据 `engine.dialect.name == "sqlite"`。**并须验证**：开启强制后既有删除/seed 路径仍全绿。**已核**：无 user/project 删除端点；`delete_requirement` 已先把关联 BUG 的 `related_requirement_id` 置空再删；`delete_bug` 删的是子行；seed 按 users→agents→project→requirements→bugs→activities 顺序 flush，均 FK 安全——故本改动低风险，仅需守卫方言 + 一条回归断言。
3. **审计完整性**：`Activity.log` 目前只在 create/assign/move/convert 触发；补 `patch_requirement`/`patch_bug`（记 `action="updated"`）与 `delete`（记 `action="deleted"`），让时间线覆盖全生命周期（feed 因此更完整）。
4. **`assignee_id` 类型防御**：`_validate_assignee` 内对 `assignee_id` 先 `int()` 兜底，避免非法类型直接进 `db.session.get`。
5. **前端质量脚本**：`frontend/package.json` 补 `"typecheck": "tsc --noEmit"`（**唯一硬门禁**，与 `next build` 一起把关，见 §6.3）。**〔R‑06 修订，P2〕** 关于 ESLint：仅新增 `.eslintrc.json` 而不装 `eslint`/`eslint-config-next`，`next lint` 首跑仍会**交互式**索求安装（与「避免交互式默认」矛盾）。二选一：(a) 同时把 `eslint` 与 `eslint-config-next` 加入 `devDependencies` 再补 `.eslintrc.json`（`extends: next/core-web-vitals`）；或 (b) 本期**不引 ESLint**，`lint` 不作门禁，仅以 `typecheck`+`next build` 兜底。推荐 (b)（零新增依赖、更契合本 Phase「零新增运行时依赖」的稳健取向），ESLint/CI 归入 `# TODO(phase3-ci)`。

### 2.9 明确的范围边界（Out of Scope，本 Phase 刻意不做，诚实标注）

为保证 Phase‑2 聚焦且可交付，以下项**明确延期**，各留 `# TODO`，不得在实现中声称已做：

- **通知系统 / WebSocket 实时推送**：`# TODO(phase3-notifications)`。价值高但独立成一大块（模型+推送通道+已读态），另立一期；本期用「协作 feed + 抽屉刷新」覆盖「看得到 Agent/他人动作」的最小诉求。
- **Alembic/Flask‑Migrate 列级迁移**：`# TODO(migrations-alembic)`。本期仅新增 `comments` 表（`create_all` 安全），无既有列变更，暂不引迁移工具。
- **真实商用字体（Tiempos/Styrene）**：涉及授权，`# TODO(webfonts-licensing)`。本期继续用 `Georgia`/`system-ui` 回退并**通过 `next/font` 强化排版一致性与微交互动效**（可选），不擅自引入需授权字体。
- **前端单测 / CI 流水线**：`# TODO(phase3-ci)`。本期以**后端 pytest 套件**兑现「可靠」，前端以 `tsc --noEmit` + `next build` 把关；CI 与前端测试留待后续。
- **Agent 对外身份与自主认证**（Agent 用自己的凭证调 API 主动认领）：本期由人类在 UI 触发 `agent-advance`（人机协同），`agent_runner` 已把「Agent 作为 actor」的数据面建好；Agent 自主轮询/回调 `# TODO(phase3-agent-autonomy)`。
- **行级 RBAC**：延续 Phase‑1 的 `# TODO(rbac-row-level)`，本期可起步（如「仅 assignee/pm/admin 可 `agent-advance`」）但不作为 DoD。

---

## 3. File / Module Change Plan（文件变更计划）

> 图例：**［新］**=新建，**［改］**=修改既有文件（增量，不破坏既有契约）。优先级 **P0**=核心必做，**P1**=强烈建议，**P2**=增强/时间允许则做。

### 3.1 Backend（`backend/`）

| 文件 | 变更 | 优先级 | 意图（一句话）|
|---|---|---|---|
| `models/comment.py` | ［新］ | P0 | `Comment` 模型：多态作者 + 多态实体 + body + `to_dict`（解析作者概要）|
| `models/__init__.py` | ［改］ | P0 | 汇总导入新增 `Comment`，保证 `create_all` 建表 |
| `services/agent_runner.py` | ［新］ | P0 | `AGENT_FORWARD` 映射 + `advance(entity, ticket, actor)`：单步推进+评论+审计（确定性）|
| `routes/comments.py` | ［新］ | P0 | 评论蓝图：`GET/POST /:entity/:id/comments`、`GET /:entity/:id/feed`（合并流）|
| `routes/requirements.py` | ［改］ | P0 | 挂 `POST /:id/agent-advance`；`move` 支持 `position` 插入索引（P2 部分）；list 应用分页 |
| `routes/bugs.py` | ［改］ | P0 | 挂 `POST /:id/agent-advance`；`move` 支持 `position`；list 应用分页 |
| `routes/__init__.py` | ［改］ | P0 | 注册 `comments` 蓝图 |
| `services/pagination.py` | ［新］ | P1 | `paginate(query)`：解析 `limit/offset`，返回 `(rows,total)`；调用方写 `X-Total-Count` |
| `observability.py` | ［新］ | P1 | `init_observability(app)`：结构化日志 + request-id + after_request 访问日志 |
| `services/ratelimit.py` | ［新］ | P1 | 内存滑动窗口登录限流 `check_and_record(key)` |
| `routes/auth.py` | ［改］ | P1 | 登录接入限流；失败/成功计数 |
| `errors.py` | ［改］ | P1 | 500 handler 内 `db.session.rollback()` 后再返回 JSON |
| `app.py` | ［改］ | P1 | 调 `init_observability`；`SEED_ON_STARTUP` 控制 seed；health 加 DB 探活 |
| `config.py` | ［改］ | P1 | 全字段改 `os.environ.get`；新增 `TestConfig`、`SEED_ON_STARTUP`、`LOGIN_MAX_ATTEMPTS` |
| `routes/stats.py` | ［改］ | P1 | 新增「本周活动数」「Agent 利用率」字段供仪表盘 |
| `seed.py` | ［改］ | P1 | 追加若干 seed 评论（人+Agent）与一条 `agent_advanced` 活动，让 feed 一启动就有内容 |
| `extensions.py` | ［改］ | P1 | 注册 `PRAGMA foreign_keys=ON` 连接事件（§2.8‑2）|
| `models/project.py` · `routes/requirements.py` · `routes/bugs.py` | ［改］ | P1 | §2.8 轻量加固：`project_id` 存在性校验、`assignee_id` 类型防御、patch/delete 补审计 |

### 3.2 Backend 测试（`backend/tests/`，全部 ［新］）

| 文件 | 优先级 | 意图 |
|---|---|---|
| `tests/conftest.py` | P0 | `app`（`TestConfig` 内存库）/`client`/`auth_header(role)` fixtures；建表 + 最小 fixture 数据 |
| `tests/test_health.py` | P0 | `GET /api/health` 200 且含 `db:"ok"` |
| `tests/test_auth.py` | P0 | 登录成功/密码错 401/`me`/register admin-only/限流 429 |
| `tests/test_workflow.py` | P0 | 纯单元：`can_transition` 全矩阵、`next_states`、`is_terminal`、终态回退 |
| `tests/test_requirements.py` | P0 | CRUD、assign 自动 new→assigned、合法 move 200、非法 move 409+allowed、convert-to-bug、`X-Total-Count` |
| `tests/test_bugs.py` | P0 | CRUD、move、分页头 |
| `tests/test_agent_runner.py` | P0 | agent-advance 推进+评论+activity(actor=agent)、agent 未指派→409、无预置动作→409、绝不绕过状态机 |
| `tests/test_comments.py` | P0 | 发/列评论、feed 合并顺序正确、system/agent/user 三种作者概要解析 |
| `tests/test_rbac.py` | P0 | member 调 admin 接口 403、pm 建单 200、member 建单 403 |
| `backend/requirements-dev.txt` | P0 | `pytest`（锁版本）|
| `backend/pytest.ini` | P0 | `testpaths=tests`、`pythonpath=.` |

### 3.3 Frontend（`frontend/`）

| 文件 | 变更 | 优先级 | 意图 |
|---|---|---|---|
| `components/TicketDrawer.tsx` | ［新］ | P0 | 工单详情右侧抽屉：详情 + 协作 feed + 评论框 + 让 Agent 处理 |
| `components/collab/FeedTimeline.tsx` | ［新］ | P0 | 渲染合并 feed（activity 时间轴点 / comment 作者气泡，人/Agent/系统区分）|
| `components/collab/CommentComposer.tsx` | ［新］ | P0 | 评论输入框 + 发送（`POST .../comments`）|
| `hooks/useTicket.ts` | ［新］ | P0 | 拉 `GET /:entity/:id` + `GET /:entity/:id/feed`；封装评论、agent-advance、指派、编辑并 `mutate` |
| `lib/types.ts` | ［改］ | P0 | 新增 `Comment`/`FeedItem`/`AgentAdvanceResult` 等类型 |
| `lib/api.ts` | ［改］ | P0 | 无破坏；沿用既有 ApiError。**〔R‑01〕** 若要读 `X-Total-Count`，须新增一个**返回 `{data, headers}` 的读取路径**（现有 `request()` 丢弃 `res.headers`，取不到），并依赖后端 CORS `expose_headers`（§2.5‑7）；否则该分页头仅后端/测试可见 |
| `components/kanban/KanbanCard.tsx` | ［改］ | P0 | 卡片 `onClick` 打开抽屉（与拖拽互斥）|
| `components/kanban/KanbanBoard.tsx` | ［改］ | P0 | 承接抽屉打开态；P2：`SortableContext` + KeyboardSensor |
| `app/(app)/requirements/board/page.tsx` | ［改］ | P0 | 挂 TicketDrawer；打开/关闭态管理；成功后 `mutate` |
| `app/(app)/bugs/board/page.tsx` | ［改］ | P0 | 同上（BUG 侧）|
| `app/(app)/requirements/page.tsx` | ［改］ | P1 | 列表行可点开抽屉；空/加载态换骨架/EmptyState |
| `app/(app)/bugs/page.tsx` | ［改］ | P1 | 同上 |
| `components/ui/Skeleton.tsx` | ［新］ | P1 | 骨架屏原语（列/行/块）|
| `components/ui/EmptyState.tsx` | ［新］ | P1 | 空状态原语 |
| `app/(app)/error.tsx` | ［新］ | P1 | 段级错误边界 |
| `app/global-error.tsx` | ［新］ | P1 | 根级错误兜底 |
| `app/(app)/not-found.tsx` | ［新］ | P1 | 404 页 |
| `app/(app)/dashboard/page.tsx` | ［改］ | P1 | 分布可视化（CSS 占比条）+ Agent 利用率 + 本周活动 |
| `app/(app)/agents/page.tsx` | ［改］ | P1 | Agent 当前工单数 + 最近活动 |
| `lib/constants.ts` | ［改］ | P1 | 补 `actionLabel`（含 `agent_advanced`/`updated`/`deleted`）、作者类型样式映射 |
| `components/ui/Modal.tsx` | ［改］ | P1 | 补 `role="dialog"`/`aria-modal`/焦点陷阱（§2.7）|
| `lib/toast.tsx` | ［改］ | P1 | 容器补 `role="status" aria-live="polite"`（§2.7）|
| `package.json` | ［改］ | P1 | 补 `"typecheck": "tsc --noEmit"` 脚本（§2.8‑5）|
| `.eslintrc.json` | ［新］ | P1 | 固化 `next/core-web-vitals` lint 规则（§2.8‑5）|

### 3.4 顶层 / 文档

| 文件 | 变更 | 优先级 | 意图 |
|---|---|---|---|
| `docs/plans/aragonteam-phase2/spec.md` | ［新］ | — | 本文档 |
| `README.md` | ［改］ | P1 | 追加 Phase‑2 能力说明、`pytest` 运行方式、新增环境变量表 |

---

## 4. Interface Design（接口设计，REST）

> 统一约定沿用 Phase‑1：JSON in/out；错误体恒为 `{error, detail?}`（+ 迁移类附 `allowed`）；写接口需 `Authorization: Bearer`。以下**仅列新增/变更**，未列者不变。

### 4.1 Agent 协作运行时（新增）
```
POST /api/requirements/:id/agent-advance            (JWT)  → 200 {ticket, comment, agent}
                                                            | 409 未指派Agent / 该状态无预置动作
POST /api/bugs/:id/agent-advance                    (JWT)  → 200 {ticket, comment, agent} | 409
   （P1）?run=all  连续推进至无动作/终态/上限(6步)，返回最后一步 {ticket, steps:[...]}
```

### 4.2 评论与合并流（新增）
```
GET  /api/requirements/:id/comments    (JWT)              → 200 [Comment]      （支持 limit/offset）
POST /api/requirements/:id/comments    (JWT) {body}       → 201 Comment        （author = 当前用户）
GET  /api/requirements/:id/feed        (JWT)              → 200 {items:[FeedItem]}  （activity+comment 合并升序）
GET  /api/bugs/:id/comments  · POST /api/bugs/:id/comments · GET /api/bugs/:id/feed   同构
```
`Comment`：`{id, entity_type, entity_id, author_type, author_id, author:{type,id,name,...}|{type:"system",name:"系统"}, body, created_at}`
`FeedItem`：`{kind:"activity"|"comment", ...}`（activity 字段见 §2.3.2；comment 同 Comment）

### 4.3 看板移动（变更 · P2）
```
PATCH /api/requirements/:id/move  {status, position?}   → 200 Requirement | 409
   position 语义：目标列内 0-based 插入索引；缺省=追加列尾（向后兼容）。后端对目标列重编号。
PATCH /api/bugs/:id/move          {status, position?}   → 同上
```

### 4.4 列表分页（变更 · P1，非破坏）
```
GET /api/requirements?...&limit=&offset=   → 200 [Requirement]  + Header: X-Total-Count
GET /api/bugs?...&limit=&offset=           → 200 [Bug]          + Header: X-Total-Count
GET /api/users · /api/agents · /comments   → 同上
   limit 默认 50、上限 200；offset 默认 0。响应体仍为裸数组（Phase-1 契约不变）。
   〔R‑01〕`X-Total-Count` 须经后端 CORS `expose_headers` 放行，浏览器 JS 方可读取（§2.5‑7）。
```

### 4.5 健康检查（变更 · P1）
```
GET /api/health   (public)  → 200 {status:"ok", service:"aragonteam-backend", db:"ok"} | 503 {db:"error"}
```

---

## 5. Data Model（数据模型）

**新增 `comments` 表**（additive，`db.create_all()` 自动创建，SQLite 对新增表无迁移风险；`aragon.db` 已 gitignore，dev 首启即建全）：

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | INTEGER | PK | |
| `entity_type` | VARCHAR(16) | not null | `requirement` \| `bug` |
| `entity_id` | INTEGER | not null | 关联工单 id |
| `author_type` | VARCHAR(16) | not null | `user` \| `agent` \| `system` |
| `author_id` | INTEGER | nullable | user/agent 主键；system 为 NULL |
| `body` | TEXT | not null | 评论正文（发送前 `strip()`，空则 400）|
| `created_at` | DATETIME | not null, index | UTC naive（复用 `utcnow`），`to_dict` 补 `Z` |

索引：`ix_comments_entity (entity_type, entity_id)` 支撑「某工单的评论/feed」查询。`to_dict()` 依 `author_type` join 概要：`user`→`User.summary()`，`agent`→`Agent.summary()`，`system`→`{"type":"system","name":"系统"}`；作者已被删除时降级为 `{"type":..., "name":"(已删除)"}`，不抛异常。

**既有表变更**：无 schema 变更。`agents.status` 语义扩展为「Agent 忙闲」的**运行态**（`agent-advance` 期间 `busy`，完成回 `idle`）——沿用既有列，不加列。需求/BUG 表不变。`Activity.action` 取值集合扩充一个 `agent_advanced`（列为自由 String，无需迁移）。

**关系与一致性**：评论与工单为逻辑关联（多态，无 DB 级外键，与既有 assignee 多态一致）；删除工单时**一并删除其评论**（`delete_requirement`/`delete_bug` 内 `Comment.query.filter_by(entity_type,..).delete()`，与「删需求前置空关联 BUG」同处理，避免悬挂）。

---

## 6. Testing & Acceptance Criteria（测试与验收标准）

### 6.1 后端自动化测试（pytest，本 Phase 的可靠性硬指标）
运行：`cd backend && pip install -r requirements-dev.txt && pytest -q`。用 `TestConfig`（`sqlite:///:memory:`，`SEED_ON_STARTUP=False`），`conftest` 建表并注入最小 fixture（admin/pm/member 各一、dev/qa Agent 各一、覆盖关键状态的需求/BUG 各若干）。**验收：`pytest` 全绿。** **〔R‑02/R‑03 测试确定性硬约束〕**：(1) 内存库**必须**按 §2.5‑5 固定 `StaticPool`+`check_same_thread=False`，否则跨线程 `no such table`；(2) 登录限流存储**必须**随 app 实例重建或由 `autouse` fixture 每用例复位（§2.5‑4），否则失败计数跨用例污染、429 断言非确定。二者是本套件「全绿且可重复」的前提，实现时先落地。

- **P‑T1 workflow 单元**：邻接表全矩阵合法/非法、`next_states` 有序、终态仅回退。
- **P‑T2 auth**：`admin/admin123` 200 带 token；错密码 401；`me` 复原；`register` 非 admin 403；同一 key 连续失败超阈 429。
- **P‑T3 requirements**：创建 `status=new`；assign→Agent 后 `assignee_type=agent` 且 `new→assigned`；`in_development→testing` 200 且写 activity；`new→done` 409 含 `allowed`；`convert-to-bug` 后 Bug.`related_requirement_id` 指向源需求且源需求转 `bug_fixing`；列表返回头含 `X-Total-Count`。
- **P‑T4 bugs**：CRUD + 合法/非法 move + 分页头。
- **P‑T5 agent_runner（核心）**：对指派给 dev‑agent 的 `assigned` 需求调 `agent-advance` → 需求转 `in_development`、新增一条 `author_type=agent` 评论、新增一条 `action=agent_advanced` 且 `actor_type=agent` 的 activity、Agent 最终 `status=idle`；对未指派 Agent 的单 → 409；对「无预置动作」的态（如 qa‑agent 处理 `new`）→ 409；断言**推进目标永远 ∈ `can_transition` 允许集**（绝不绕过状态机）。
- **P‑T6 comments/feed**：POST 评论作者为当前用户；GET feed 按 `created_at` 升序合并 activity 与 comment；system/agent/user 三类作者概要均正确解析。
- **P‑T7 rbac**：member `POST /users` 403、member `POST /requirements` 403、pm `POST /requirements` 201。
- **P‑T8 health**：`GET /api/health` 200 且 `db:"ok"`。

### 6.2 前端验收（手动 / 可选 Playwright 冒烟）
- **P‑U1 工单抽屉**：点击任意看板卡片 → 右侧抽屉展开，显示详情 + 协作 feed；`Esc`/遮罩关闭；焦点管理正确。
- **P‑U2 人机混合讨论**：在抽屉发一条评论 → 立即出现在 feed（作者=当前用户头像）；feed 中人/Agent/系统三类视觉可区分。
- **P‑U3 Agent 处理（核心演示）**：打开一张指派给 `dev-agent` 的 `assigned` 需求 → 点「让 dev‑agent 处理下一步」→ **按钮进入 loading 态**（可观测的进度信号）→ 卡片自动移到「开发中」，feed 立刻出现 Agent 的工作说明评论与流转记录；单步同步完成后 **Agent 终态为 `idle`**（〔R‑04〕单步不产生可观测的 `busy` 窗口，`busy` 仅见于 `run=all`）。**这是 Phase‑2 的标志性验收。**
- **P‑U4 骨架/空/错误态**：首屏加载显示骨架屏而非纯文字；空看板列显示空状态；人为制造错误（关后端）时错误边界兜底不白屏。
- **P‑U5 仪表盘可视化**：需求/BUG 分布以占比条呈现；Agent 利用率可见。
- **P‑U6（P2）同列重排**：同列内拖动卡片可精确插入到目标位置，刷新后顺序保持。

### 6.3 Definition of Done（Phase‑2）
1. 后端 `pytest -q` 全绿（P‑T1…P‑T8）；前端 `tsc --noEmit` 0 error、`next build` 成功。
2. P0 项（支柱 A：agent‑advance + 评论/feed + TicketDrawer；后端测试套件）**全部落地并演示 P‑U3**。
3. P1 项尽量完成；未完成项以 `# TODO(phase2-...)` 明确标注，不得声称已做。
4. 不破坏 Phase‑1 任何契约与既有验收（T1–T8 / U1–U6 仍通过）。
5. 前后端可启动无报错，数据落 SQLite 且重启不丢。

---

## 7. Risks & Mitigations（风险与缓解）

| 风险 | 影响 | 缓解 |
|---|---|---|
| **Agent 推进绕过状态机**导致非法态 | 数据不可信、看板错乱 | `agent_runner` 每步强制走 `can_transition`；单测 P‑T5 断言目标 ∈ 允许集；`AGENT_FORWARD` 的每条边均为邻接表内的合法前进边 |
| **卡片点击与拖拽冲突**（点开抽屉误触拖拽）| 交互挫败 | 沿用卡内已验证的 `isDragging`/`stopPropagation` 守卫；点击仅在拖拽阈值内未移动时触发 |
| **抽屉与看板数据不同步**（移动/评论后看板不更新）| 状态错位 | 所有写操作成功后同时 `mutate` 抽屉 SWR key 与看板 key；后端返回权威数据 |
| **多态作者/实体无 DB 外键** | 脏数据 | 与既有 assignee 多态同策略：写前校验目标存在；`to_dict` join 失败降级为占位而非抛错；删单级联删评论 |
| **内存限流重启失效 / 多副本不共享** | 防护弱（MVP 可接受）| 明确 MVP 边界 + `# TODO(ratelimit-distributed)`；不作为唯一安全边界 |
| **`db.create_all` 不做列级迁移** | 若未来改既有表列会漏迁移 | 本 Phase 仅**新增表**（comments），无既有列变更，`create_all` 安全；列级演进未来引 Alembic（`# TODO(migrations-alembic)`）|
| **pytest 与启动期 seed 冲突**（重复/污染）| 测试不稳定 | `SEED_ON_STARTUP=False` + 内存库 + `conftest` 自建 fixture，测试与运行期数据完全隔离 |
| **run=all 死循环** | 服务端挂起 | `MAX_AGENT_STEPS=6` 硬上限 + 命中「无动作」即停 |
| **同列重排并发写竞态** | position 错乱 | 目标列重编号在单事务内完成；MVP 单机足够；高并发迁 Postgres 行锁（记 TODO）|
| **feed 合并性能**（大量活动/评论）| 详情慢 | 索引 `ix_comments_entity` + `ix_activities_entity`；feed 支持 `limit`；MVP 单工单量级无压力 |
| **前端新增运行时依赖引入不稳定** | 构建/体积风险 | Phase‑2 前端**零新增运行时依赖**（sortable/utilities 已在 package.json）；可视化用纯 CSS |

---

## 8. 交付顺序与实施建议（供下游「代码开发」节点参考）

建议实现顺序（先立地基，再铺价值，最后打磨）：

1. **数据与服务地基（P0）**：`models/comment.py` → `models/__init__.py` → `services/agent_runner.py` → `routes/comments.py`（含 feed）→ requirements/bugs 挂 `agent-advance` → 注册蓝图。此时后端核心能力齐备。
2. **后端测试（P0）**：`config.py` 加 `TestConfig`/`SEED_ON_STARTUP` → `conftest.py` → 各 `test_*.py`。**先让 `pytest` 全绿**，为后续所有改动兜底。
3. **前端协作层（P0）**：`lib/types.ts` → `hooks/useTicket.ts` → `FeedTimeline`/`CommentComposer` → `TicketDrawer` → 两个看板页挂抽屉、`KanbanCard` 可点开。演示 **P‑U3**。
4. **可靠性加固（P1）**：`observability.py`、`errors.py` 回滚、`pagination.py`、`ratelimit.py`、`config.py` 环境变量、health DB 探活、stats 扩字段。
5. **前端打磨（P1）**：Skeleton/EmptyState/error 边界、dashboard 可视化、agents 页增强、列表页接抽屉。
6. **增强（P2）**：同列拖拽重排、run=all、键盘可达拖拽、行级 RBAC 起步。

> **契约铁律（延续 Phase‑1）**：status key 集合、错误响应 shape、JWT identity=str、看板/列表既有返回 shape **一律不变**；Phase‑2 所有接口均为**新增或向后兼容变更**。任何对既有契约的改动都必须回到本 spec 与 Phase‑1 spec 同步评审。

---

## 9. 交付清单摘要（给下游的最小实现集）

1. **后端**：`comments` 表 + 评论/feed 接口 + `agent_runner` 单步推进接口（req/bug）+ 分页头 + 结构化日志/request‑id + 登录限流 + 500 回滚 + `TestConfig`。
2. **后端测试**：`backend/tests/` 8 个测试文件 + `conftest` + `pytest.ini` + `requirements-dev.txt`，`pytest -q` 全绿。
3. **前端**：`TicketDrawer` + 合并 feed 时间线 + 评论框 + `useTicket` + 卡片可点开 + 「让 Agent 处理」；骨架屏/空状态/错误边界；仪表盘可视化；Agents 页增强。
4. **文档**：本 spec + README 追加 Phase‑2 能力与运行方式。
5. **端到端**：P‑U1…P‑U5 通过（P‑U3 为标志性演示），T1–T8 / U1–U6 回归不破。

---

*本文档为 Phase‑2 **v2**（v1 由 Iteration 2/3 的 Solution Architect 产出，经 Senior Reviewer 评审并就地修复 P0/P1），建立在 Phase‑1 MVP（`docs/plans/aragonteam-mvp/spec.md` v2，commit 91507c2）之上，仅做向后兼容的增量演进与加固。供下游「代码开发」节点逐行实现。核心主张：让「Agent 参与协作」成为可交互、可追溯、可测试的真实机制，并以自动化测试与可靠性护栏兑现「稳健、可靠、顶级」。*

---

## 评审结论（Review Verdict）

**结论：有条件通过（Approved with Conditions）。**

本方案建立在已合入的 Phase‑1 MVP 之上，**逐文件核对既有代码后确认其对既有契约的引用全部属实**，架构方向（三支柱：Agent 协作运行时 / 讨论与工单详情 / 可靠性加固）**紧扣全局目标「稳健、可靠、顶级」与产品立身之本「AI 时代可协作平台」**，范围为「MVP 深化」而非重写，右尺寸得当、无过度设计，且严守「不破坏 Phase‑1 对外契约」的铁律。其**最大亮点**是把「Agent 参与协作」从静态字段落成「会推进工单、会留言、会进时间线」的可测机制，并坚持 Agent 推进**绝不绕过 `workflow.can_transition`**——这是可信度的地基，评审予以肯定。

评审共提出 **4×P1 + 3×P2**：

- **P1（4 项）已在本 v2 正文就地修复**：
  - **R‑01** CORS `expose_headers`（`X-Total-Count`/`X-Request-Id` 跨域可读）+ 前端 `api.ts` 返回 headers 的读取路径 —— 见 §2.5‑3/§2.5‑7、§3.3、§4.4。
  - **R‑02** `TestConfig` 内存库固定 `StaticPool`+`check_same_thread=False` —— 见 §2.5‑5、§6.1。
  - **R‑03** 登录限流存储随 app 重建 / conftest `autouse` 复位（测试隔离）—— 见 §2.5‑4、§6.1。
  - **R‑04** 单步 `agent-advance` 终态即 `idle`、不写不可观测的 `busy`；进度信号改前端按钮 loading；`busy` 仅归 `run=all` —— 见 §2.2、§2.2.3、§6.2 P‑U3。

- **放行条件（P2，实现期须遵守，正文已给方案，不作 DoD 阻塞）**：
  1. **R‑05** `PRAGMA foreign_keys=ON` 监听须**限 SQLite 方言**并补一条删除/seed 回归断言（§2.8‑2）。
  2. **R‑06** ESLint 二选一：补齐 `eslint`+`eslint-config-next` devDependencies，或本期不引 ESLint、以 `typecheck`+`next build` 为唯一门禁（推荐后者）（§2.8‑5）。
  3. **R‑07** 库 URI 环境变量统一沿用既有 `DATABASE_URL`，勿另引 `SQLALCHEMY_DATABASE_URI`（§2.5‑5）。

**DoD 校验**：`spec.md` 已含 §评审记录 与 §评审结论；文档版本已标 **v2**；4 项 P0/P1 均已在正文闭环，无未决 P0/P1。据此**准予进入「代码开发」节点实现**，实现完成后按 §6 的 P‑T1…P‑T8 / P‑U1…P‑U5 验收，并回归 Phase‑1 T1–T8 / U1–U6 不破。

> 评审仅修改 `spec.md`，未触碰任何源代码，未执行 `git commit`（遵守本节点约束）。

---

## 实施过程发现的方案缺陷（Issues Found During Implementation）

> 由下游「代码开发」节点在逐项落地时记录。整体方案**高度可实现**，仅两处**变更计划表的表述精度**问题，均按 spec 正文既有结论采取「更正后的做法」，不影响任何契约与验收。

- **I-01（对齐 R-06 推荐 b）｜`.eslintrc.json` 未创建**：§3.3 变更计划表把 `.eslintrc.json` 列为 ［新］P1，但 §2.8-5 / R-06 的**评审推荐是方案 (b)——本期不引 ESLint**（避免 `next lint` 首跑交互式索求安装、坚持「零新增依赖」）。实现遵循 R-06 推荐 (b)：**未创建 `.eslintrc.json`、未加 eslint 依赖**，硬门禁为 `typecheck`(`tsc --noEmit`) + `next build`（二者均已通过）；ESLint/CI 归入 `# TODO(phase3-ci)`。此非静默偏离——是执行 spec 自身评审已拍板的更正做法。

- **I-02（表述精度）｜`models/project.py` 无需改动**：§3.1 末行把 `models/project.py · routes/requirements.py · routes/bugs.py` 并列为 §2.8 轻量加固的 ［改］项，但 §2.8-1 的 `project_id` 存在性校验、§2.8-4 的 `assignee_id` 类型防御、§2.8-3 的 patch/delete 补审计**全部落在两个 routes 文件**，`Project` 模型本身无字段/方法变更。故 `models/project.py` **保持不变**，加固项已在 `routes/requirements.py`（`_validate_project`/`_validate_assignee` int 兜底/patch·delete `Activity.log`）与 `routes/bugs.py` 就地完成。

- **补充实现说明（非缺陷，留痕）**：为落地 §2.6 同列拖拽重排（P2），除计划表列出的 `KanbanCard`/`KanbanBoard` 外，一并把 `components/kanban/KanbanColumn.tsx` 接入 `@dnd-kit/sortable` 的 `SortableContext`——§2.6 正文已明确「`KanbanColumn` 改用 `SortableContext`」，属方案内既定改动，依赖（`@dnd-kit/sortable`/`utilities`）Phase-1 已声明，**零新增依赖**。

**实现期验收结果**：后端 `pytest -q` **47 用例全绿**（P-T1…P-T8 全覆盖）；前端 `tsc --noEmit` **0 error**、`next build` **成功**（13 路由）；生产配置路径（真实 seed + PRAGMA 外键 + 环境变量）端到端冒烟通过——P-U3 标志性演示（agent-advance 单步 assigned→in_development + Agent 评论 + `agent_advanced` 审计 + 终态 idle）、`run=all` 连续推进、合并 feed 升序、分页头、健康探活均符合预期。R-05 守卫（PRAGMA 限 SQLite 方言）经 seed/删除路径回归无破。
