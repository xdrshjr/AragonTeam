# 开发方案：管理台 UI（`admin-console`）——团队 / Agent / 项目的建改闭环

> **文档版本**：**v2**（Subtask #1 · 设计评审后修订；v1 由 Subtask #0 方案设计产出）
> **Loop 迭代**：Iteration 5/5 · 特性 `admin-console`
> **作者**：资深工程师（Anthropic Eng）
> **评审人**：资深评审（Anthropic Eng）——已按可行性 / 完备性 / 一致性 / 合理规模逐节比对代码核实（见 §评审记录 / §评审结论）。
>
> 前置脉络（本 Loop 已交付、均已 commit）：
> - Iteration 1（`real-agent-execution`，`12c5a4c`）：把**唯一的业务 Mock**（Agent 执行引擎罐头文案）真实化，接入真实 LLM 与全链路优雅降级。
> - Iteration 2（`account-settings`，`1373e94`）：把设置页占位真实化为账号自助中心（资料 / 改密 / 通知偏好）。
> - Iteration 3（`global-search`，`9396400`）：把 Header「假搜索」真实化为跨需求 / BUG 的统一全局搜索。
> - Iteration 4（`mention-autocomplete`，`e5f7b9f`）：把评论框「@提及」占位真实化为成员下拉自动补全 + 后端正则加固。
>
> **交棒依据**：`mention-autocomplete/spec.md §9`「后续迭代路线」把本轮选题**显式交棒**：**第 1 项即「管理台 UI（D8–D11）」**——Team 页「新增成员 / 改姓名邮箱 / 重置密码」、Agents 页「建 / 改 Agent」、项目管理页。本轮即落地这三块**管理写操作在前端的缺口**，把「只读花名册」升级为「可管可控的管理台」。

---

## 评审记录（Review Notes · v1 → v2）

> **评审人**：资深评审（Anthropic Eng）· Subtask #1 · 维度：**可行性 / 完备性 / 一致性 / 合理规模**
>
> **核实过程（逐一比对代码，非纸面复述）**：设计的每一处关键技术断言均已落到源码核实为真——
> ① 六个后端写接口存在且权限 / 载荷形状与 §4.1 一致（`POST/PATCH /api/users` admin；`POST /api/agents` pm/admin；`GET/POST /api/projects`；`GET /api/users`）；
> ② `backend/routes/agents.py:67-84` `patch_agent` 现为裸 `@jwt_required()`、仅受理 `status`/`description`（与「需收紧 + 扩 name/kind」的判断一致）；
> ③ `require_role` / `AGENT_KINDS` / `AGENT_STATUSES` 已在 `agents.py` import（`patch_agent` 改造无需新增 import）；
> ④ **全仓 `grep .patch(` 确认：无任何既有测试直调 `PATCH /api/agents/<id>`**（仅 `/claim-next`·`/autorun`·`/tick`，均已 pm/admin）——门禁收紧零回归；
> ⑤ `Project.key` = `String(16) unique`、`Agent.name` = `String(64) unique`、`User.email` = `String(255) nullable 非唯一`（故无邮箱唯一性冲突）；
> ⑥ UI Kit（`Modal`/`Input`/`Select`(含 `options`)/`Textarea`/`Button`(变体 `subtle`/`ghost`)）契约与弹窗设想相容；`ProfileCard` 的「diff + 空 diff 提示」既有习惯确存在；
> ⑦ `conftest` fixtures 齐备（`client`/`auth`/`data`；角色 admin/pm/member/member2；`dev_agent_id`/`qa_agent_id`/`project_id`；seed agent 名 `dev-agent`/`qa-agent`；项目 key `TST`）。
>
> **总评**：方案可落地、零新表、零状态机改动，与 CLAUDE.md「状态机神圣 / 向后兼容 / 通知收口唯一」三约定一致，选题与规模均恰当。下表列出全部发现项与处置。

| # | 严重度 | 维度 | 位置 | 问题 | 处置 |
|---|--------|------|------|------|------|
| C1 | **P1** | 完备性 / 正确性 | §2.3 编辑态 `status` | 编辑弹窗把 `busy` 作为**人工可选**状态暴露。`busy` 是自主编排的**运行时软锁**（`tick`/`autorun`/`claim` 见 busy 即 409），仅由 `_run_with_lock` 的 `finally` 归位。人工设成 `busy` 后**无任何流程会归它 idle**，该 Agent 将被永久锁出全部编排，直到有人再手动改回——一次普通管理操作即可**静默瘫痪核心能力**。 | **v2 已修**：编辑态 `status` 仅提供「空闲 / 离线」（`idle`/`offline`）；`busy` 系统托管、不可人工设置；当前恰为 busy（编排中）时只读展示且仅允许改为 idle/offline。见 §2.3、§4.1 表注、R9。 |
| C2 | P2 | 一致性 | §2.2 `MemberFormModal` | 管理台 `POST/PATCH /api/users` **不校验邮箱格式**，而自助路径 `/me/profile` 会（`test_settings.py:47` 拒收 `not-an-email`）。同为写邮箱，两路径行为不一致。 | **v2 已加**前端软校验（邮箱非空时基本格式检查，与 R6 密码软约束同策略），后端契约不变。见 §2.2、R10。 |
| C3 | P2 | 一致性 | §2.3 `AgentFormModal` edit | 编辑态无「空 diff」保护，而 `MemberFormModal` edit 有（「没有需要保存的改动」）。同类弹窗行为不一致。 | **v2 已补**：edit 空 diff → toast「没有需要保存的改动」，不发请求。见 §2.3。 |
| C4 | P2 | 一致性 / 可维护 | §2.2 `MemberFormModal` | 三态合一（create/edit/reset + 共享 state + 提交分支 + diff 构造）易超 CLAUDE.md §二 / §六阈值（单方法 ≤50 行、圈复杂度 ≤10）。 | **条件（实现时）**：按模式拆分渲染 / 提交（每态子函数或策略表），单函数守住阈值。列入 §评审结论。 |
| C5 | P2 | 一致性（体验） | §2.2 / §2.4 / §6.3 | 后端错误文案为英文（`username already exists` 等），前端 `err.message` 直显 → 中文界面弹英文 toast（既有全仓惯例）。§6.3 冒烟所述中文 toast（如「已存在」）不会字面命中。 | **条件**：或在弹窗层把关键 409/400 映射为中文，或把冒烟判定改为「命中 409 且给出错误 toast」。见 §6.3 注、§评审结论。 |
| C6 | P2 | 完备性（纵深） | §2.5 / R1 | 后端 `patch_user` 无「最后一名 admin 不可降级」不变量；靠前端禁用自我降级使**经 UI** 不可达零 admin（已论证），但 admin 直调 API 仍可自降。 | 依 R5「后端为权威」当前可接受；如需纵深防御可加后端守护，已列 §8 交棒。 |
| C7 | P2 | 一致性（文档） | §6 验收 / CLAUDE.md | CLAUDE.md 记「pytest（93 cases）」，实测当前基线为 **154** 个 `def test_`（Iter2–4 已增补）。本 spec 未硬编码数字（仅「既有全部用例须仍绿」），**无缺陷**；但验收基线宜以真实 154 为准。 | 记录事实基线；建议下次「regenerate index」刷新该数字。见 §6.4 注。 |

> **处置口径**：C1（唯一 P0/P1 级）已在正文修复并 bump **v2**；C2、C3 亦顺手在正文加固（成本极低、增强一致性）；C4–C7 为 P2，作为 §评审结论的落地条件 / 未来项，不阻塞通过。

---

## 0. 剩余占位 / 半成品盘点（本轮选题依据）

承接 `global-search/spec.md §10`、`account-settings/spec.md §0` 与 `mention-autocomplete/spec.md §9` 的全仓审计结论——**业务路由中已无任何伪造 / 硬编码的 API 响应**。本轮从 §9 路线图**按价值 / 风险排序取第 1 项**，对应审计项 **D8–D11**：后端写接口**已存在且已被 RBAC 测试覆盖**，唯独**前端没有触达它们的界面**，导致这些能力「有后端、无入口」，长期闲置。

| # | 位置 | 现状（本轮复核确认仍存在） | 类型 | 本轮 |
|---|------|------|------|------|
| D8 | `frontend/app/(app)/team/page.tsx` | 花名册表格 + **仅**行内「改角色」下拉。后端 `POST /api/users`（admin）已具备，但**无「新增成员」入口**——管理员无法在 UI 里加人，只能靠 seed 或直接打 API。 | 前端缺口（有后端、无入口） | **✅ 纳入** |
| D9 | `frontend/app/(app)/team/page.tsx` | 后端 `PATCH /api/users/<id>` 支持改 `display_name`/`email`/`role`/`password`，但前端**仅**发 `{role}`，`display_name`/`email` **无编辑 UI**。 | 前端缺口 | **✅ 纳入** |
| D10 | `frontend/app/(app)/team/page.tsx` | 后端 `PATCH /api/users/<id>` 接受 `{password}` 即可重置密码（真实改哈希），但前端**无「重置密码」入口**——管理员无法帮成员找回。 | 前端缺口 | **✅ 纳入** |
| D11 | `frontend/app/(app)/agents/page.tsx` | Agent 卡片 + 自主编排按钮（Iter1/Phase-3）。后端 `POST /api/agents`（pm/admin）与 `PATCH /api/agents/<id>` 已具备，但前端**无「新建 / 编辑 Agent」入口**——AI 团队成员只能靠 seed 固定两只（dev/qa）。 | 前端缺口 | **✅ 纳入** |
| D11-proj | 全仓无 `projects` 页 / 无侧栏入口 | 后端 `GET /api/projects` + `POST /api/projects`（pm/admin）已具备，前端**从未消费**——无法在 UI 查看 / 新建项目。 | 前端缺口 | **✅ 纳入（列表 + 新建）** |
| D11-back | `backend/routes/agents.py:67-84` | `PATCH /api/agents/<id>` **只**接受 `status`/`description`，**不支持改 `name`/`kind`**（编辑 Agent 无法改名 / 改类型）；且门禁为裸 `@jwt_required()`——**任意登录成员都能改共享 Agent** 的状态 / 描述，与 `POST`（`admin|pm`）不一致，是 RBAC 缺口。 | 后端健壮性 / RBAC 缺口 | **✅ 一并加固** |

其余审计项（A4 LLM 运行时配置的管理台化、提及纳入 Agent、跨类型通知去重合并）继续按 §后续迭代路线交棒未来，本轮**不贪多**——聚焦把「管理写操作」这条链路在前端**端到端补齐、做稳**。

### 选题理由

D8–D11 是本 Loop 反复出现的同一模式的**最后一处集中体现**：**后端能力齐备、被测试守护，却缺前端入口**。把它补上，管理员 / PM 才能在界面里**完成一支混合团队（人 + Agent）的组建与维护**——加人、改人、重置密码、扩充 AI 团队、开项目——这正是「组织团队协作」产品主线的**地基**。方案自洽、低风险、**零新表、零状态机改动**，与 Iter1–4「把一处言行不一 / 有能力无入口的 UI 真实化、由现成后端能力兜底」的模式完全一致；仅有的后端改动（Agent 改名 / 改类型 + 门禁收紧）是**加固**而非新造，向后兼容。作为 Loop 收官轮，它让「稳健可靠好用，顶级」的目标在**管理面**闭环。

---

## 1. 概述（Overview）

本方案把管理相关的三个页面从**只读 / 半可写**升级为**完整的建改闭环**，交付一个轻量「管理台」：**团队管理**、**Agent 管理**、**项目管理**。核心是三个共享的表单弹窗组件（`MemberFormModal` / `AgentFormModal` / `ProjectFormModal`），复用既有 `Modal` + UI Kit（`Input`/`Select`/`Textarea`/`Button`）与既有 `api`/`useToast`/`useSWR` 基础设施，把早已存在、却无 UI 触达的后端写接口接通。**团队页**新增「+ 新增成员」，并把行内「改角色」升级为一个覆盖「显示名 / 邮箱 / 角色 / 重置密码」的编辑弹窗；**Agent 页**在既有「运行 AI 团队一轮」旁新增「+ 新建 Agent」，并为每张卡片加「编辑」；**项目页**是一个新路由（含侧栏入口），提供项目列表与「+ 新建项目」。

与前端补齐对称，本方案对后端做**一处有界的健壮性加固**：把 `PATCH /api/agents/<id>` 扩展为可改 `name`（非空 + 唯一性校验，冲突 409）与 `kind`（枚举校验，非法 400），使「编辑 Agent」能真正改名 / 改类型；同时把该路由门禁从裸 `@jwt_required()` **收紧**为 `@require_role("admin", "pm")`，与 `POST /api/agents` 的门禁一致——避免任意成员擅改共享 Agent。此收紧属**有意的契约变更**（先例：Phase-3 已把 `agent-advance` 收紧为 `pm/admin 或 can_manage_ticket`，见 CLAUDE.md），且经全仓核验**无任何既有测试直接调用该 PATCH 接口**，故不破坏现有回归。

范围严格自洽：**零新表、零既有 API shape 变更（仅 Agent PATCH 增可选入参）、零状态机改动、零新依赖**，恪守 CLAUDE.md「状态机神圣 / 向后兼容 / 通知收口唯一」三约定。所有前端写操作在提交前按角色**隐藏入口**（member 看不到新增 / 编辑按钮），与后端权威门禁**双保险对齐**，避免「点了才 403」的体验落差。项目页本轮只做**列表 + 新建**（后端仅提供 list/create，无 `PATCH`/`DELETE`），项目的编辑 / 删除按 §后续迭代路线明确交棒，方案不隐瞒此边界。

---

## 2. 技术设计（Technical Design）

### 2.1 架构与接缝

```
┌──────────────────────────────── 前端（frontend/） ────────────────────────────────┐
│  app/(app)/team/page.tsx      ← 改：Header 加「+新增成员」；表格加「操作」列（编辑/重置密码）│
│      └─ components/admin/MemberFormModal.tsx   ← 新增：建/改成员 + 重置密码（一个弹窗两模式）│
│  app/(app)/agents/page.tsx    ← 改：Header 加「+新建 Agent」；卡片加「编辑」                 │
│      └─ components/admin/AgentFormModal.tsx    ← 新增：建/改 Agent（name/kind/desc[/status]）│
│  app/(app)/projects/page.tsx  ← 新增：项目列表 + 「+新建项目」                               │
│      └─ components/admin/ProjectFormModal.tsx  ← 新增：新建项目（name/key/desc）             │
│  components/layout/Sidebar.tsx ← 改：NAV 增「项目」入口（团队与设置之间）                    │
│  lib/types.ts                  ← 改：加 UserCreate/UserUpdate/AgentInput/ProjectCreate 载荷型 │
└────────────────────────────────────────────────────────────────────────────────────┘
        │ POST /api/users · PATCH /api/users/:id            （既有，admin）
        │ POST /api/agents · PATCH /api/agents/:id          （既有[+扩展]，pm/admin）
        │ POST /api/projects · GET /api/projects            （既有，pm/admin/列表全员）
        ▼
┌──────────────────────────────── 后端（backend/） ────────────────────────────────┐
│  routes/agents.py:patch_agent   ← 改：@require_role("admin","pm")；受理 name/kind（校验+唯一）│
│  （users.py / projects.py / auth.py 无改动——写接口已完备）                                  │
└────────────────────────────────────────────────────────────────────────────────────┘
```

**关键设计原则**：前端**只暴露后端支持的字段**，绝不给出「填了也无法保存」的控件——`MemberFormModal` 编辑态不含 `username`（后端不可改）；`ProjectFormModal` 无「编辑」态（后端无 `PATCH /projects`）；`AgentFormModal` 编辑态含 `status`（后端支持），创建态不含（新建恒为 `idle`）。前端角色门禁与后端 `require_role` **镜像**：member 不渲染任何写入口。

### 2.2 前端：团队管理（`team/page.tsx` + `MemberFormModal`）

**页面改动**（`team/page.tsx`）：

1. `Header` 增 `action`：`isAdmin` 时渲染 `<Button size="sm" onClick={()=>setEditing({mode:"create"})}>+ 新增成员</Button>`。
2. 表格保留「成员 / 用户名 / 邮箱 / 角色」四列，**移除**行内 `role` `<select>`（其能力并入编辑弹窗），角色改为纯文本 `ROLE_LABELS[u.role]`；新增第五列「操作」（仅 `isAdmin` 渲染），每行两个 `variant="ghost" size="sm"` 按钮：`编辑`（`setEditing({mode:"edit", user:u})`）、`重置密码`（`setEditing({mode:"reset", user:u})`）。
3. 底部挂载 `<MemberFormModal state={editing} onClose={...} onSaved={()=>{setEditing(null); mutate();}} />`；`editing` 为 `null | {mode:"create"} | {mode:"edit"|"reset", user:User}`。

**组件 `MemberFormModal`**（一个组件三态，减少重复）：

- **create**：字段 `username`（必填）、`password`（必填）、`display_name`（选填，占位提示「留空则同用户名」）、`email`（选填）、`role`（Select，默认 `member`）。提交 → `api.post<User>("/users", {username, password, role, display_name||undefined, email||undefined})` → 成功 toast「已创建成员 X」→ `onSaved()`。
- **edit**：`username` 只读展示（灰字，不可编辑，注明「用户名不可修改」）；可改 `display_name`、`email`、`role`。**自我保护**：当 `user.id === me.id` 时禁用 `role` Select 并注「不能修改自己的角色」（防管理员误把自己降级 / 自锁）。提交按 diff 只发变化字段 → `api.patch<User>("/users/"+user.id, diff)`。若 `diff` 为空 → toast「没有需要保存的改动」（对齐 `ProfileCard` 既有习惯）。
- **reset**：仅一个 `password`（新密码，必填）+ 确认框；提交 → `api.patch("/users/"+user.id, {password})` → toast「已重置 X 的密码」。**不**在此暴露其它字段，避免误改。

三态共用一套 state 与 `submitting` 锁；错误统一 `toast.error(err instanceof ApiError ? err.message : "操作失败")`（承接 `409 username already exists` / `400 invalid role` 的后端文案直显）。**【v2·C2】** create/edit 的 `email` 加**前端软校验**：非空时做基本格式检查（如 `/^[^\s@]+@[^\s@]+\.[^\s@]+$/`），不合格则即时提示且拦截提交——与自助路径 `/me/profile` 的邮箱校验（`test_settings.py:47` 拒 `not-an-email`）行为对齐；后端 `users.py` 契约**不改**（软约束仅在前端，避免破坏既有 seed / 测试），与 R6 密码软约束同策略。

### 2.3 前端：Agent 管理（`agents/page.tsx` + `AgentFormModal`）

**页面改动**（`agents/page.tsx`）：

1. `Header` 的 `action` 由单按钮改为 `<div className="flex items-center gap-2">`：`canOrchestrate` 时先渲染 `+ 新建 Agent`（`setForm({mode:"create"})`），再渲染既有「▶ 运行 AI 团队一轮」。
2. 每张 Agent 卡片：在 `canOrchestrate` 的自主编排按钮行（`onTick`/`onClaim`/`onAutorun` 那一排）**追加**一个 `variant="ghost" size="sm"` 的「编辑」按钮 → `setForm({mode:"edit", agent:a})`。
3. 底部挂载 `<AgentFormModal state={form} onClose={...} onSaved={()=>{setForm(null); mutate("/agents");}} />`。

**组件 `AgentFormModal`**：

- **create**：`name`（必填、唯一由后端保证）、`kind`（Select：开发 / 测试 / 通用 → `dev`/`qa`/`generic`，默认 `generic`）、`description`（Textarea 选填）。提交 → `api.post<Agent>("/agents", {name, kind, description||undefined})`。
- **edit**：可改 `name`、`kind`、`description`、`status`。**【v2·C1 修正】** `status` Select **仅提供「空闲 / 离线」（`idle`/`offline`）——不暴露 `busy`**：`busy` 是自主编排的**运行时软锁**（`tick`/`autorun`/`claim` 见 busy 即 409），由 `_run_with_lock` 的 `finally` 独家归位；若允许人工设 `busy`，将无任何流程把它归 idle，Agent 会被永久锁出全部编排，故 `busy` 定为**系统托管、不可人工设置**。若打开编辑弹窗时该 Agent 恰为 `busy`（编排进行中），`status` 字段**只读展示当前「忙碌」**并仅允许切到 idle/offline（提交 idle 即等于安全解锁）。按 diff 只发变化字段 → `api.patch<Agent>("/agents/"+agent.id, diff)`。**【v2·C3】** 若 diff 为空 → toast「没有需要保存的改动」、不发请求（与 `MemberFormModal` edit 一致）。
- 成功 toast「Agent 已保存」→ `onSaved()`；错误同 §2.2。

`kind`/`status` 的中文标签复用 `AGENT_KIND_LABELS` / `AGENT_STATUS_LABELS`（`constants.ts` 既有），Select options 由其 `Object.entries` 生成。

### 2.4 前端：项目管理（新 `projects/page.tsx` + `ProjectFormModal` + 侧栏）

**新路由 `app/(app)/projects/page.tsx`**（`"use client"`）：

- `useSWR<Project[]>("/projects", swrFetcher)` 拉列表；`canCreate = role ∈ {admin, pm}`。
- `Header title="项目" subtitle="研发项目容器"`，`action` 为 `canCreate` 时的 `+ 新建项目`。
- 表格列：「标识（key，等宽字体徽章）/ 名称 / 描述 / 负责人」。负责人由 `owner_id` 关联 `useSWR<User[]>("/users")` 就地解析显示名（找不到显示「—」）。空态用 `EmptyState`。
- 底部挂 `<ProjectFormModal open={creating} .../>`。

**组件 `ProjectFormModal`**（仅创建态）：

- 字段 `name`（必填）、`key`（必填，`onChange` 即 `toUpperCase()`，占位「如 ARA」，`maxLength` 16）、`description`（Textarea 选填）。
- 提交 → `api.post<Project>("/projects", {name, key, description||undefined})` → 承接后端 `409 project key already exists` / `400 name and key are required` 文案 → 成功 toast「项目已创建」。

**侧栏**（`Sidebar.tsx`）：`NAV` 数组在「团队」与「设置」之间插入一项 `{ href:"/projects", label:"项目", icon:<Icon path="…文件夹图标 d…" /> }`。选一个与既有风格一致的单 path 文件夹图标（如 `M3 7a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z`）。

### 2.5 后端：Agent PATCH 扩展 + 门禁收紧（唯一后端改动）

`backend/routes/agents.py` 的 `patch_agent`（第 67–84 行）改为：

```python
@bp.patch("/<int:agent_id>")
@require_role("admin", "pm")        # 【收紧·有意契约变更】原 @jwt_required()：任意成员可改共享 Agent → 与 POST 对齐
def patch_agent(agent_id):
    agent = db.session.get(Agent, agent_id)
    if agent is None:
        return jsonify({"error": "agent not found"}), 404
    data = request.get_json(silent=True) or {}

    if "name" in data:                                   # 【新增】支持改名（编辑 Agent 的核心）
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400
        exists = Agent.query.filter(Agent.name == name, Agent.id != agent.id).first()
        if exists:
            return jsonify({"error": "agent name already exists"}), 409
        agent.name = name
    if "kind" in data:                                   # 【新增】支持改类型
        if data["kind"] not in AGENT_KINDS:
            return jsonify({"error": "invalid kind", "detail": {"allowed": list(AGENT_KINDS)}}), 400
        agent.kind = data["kind"]
    if "status" in data:                                 # 既有，保持不变
        if data["status"] not in AGENT_STATUSES:
            return jsonify({"error": "invalid status", "detail": {"allowed": list(AGENT_STATUSES)}}), 400
        agent.status = data["status"]
    if "description" in data:                            # 既有，保持不变
        agent.description = data["description"]

    db.session.commit()
    return jsonify(agent.to_dict()), 200
```

要点：`require_role` 已从 `services.auth_helpers` 导入吗？——当前文件已 `from services.auth_helpers import require_role`（用于 `create_agent`），无需新增 import。改名唯一性用 `Agent.id != agent.id` 排除自身，避免「改成自己现名」误报 409。其余字段处理逐字保持既有语义，**新增仅为可选入参**（不传即旧行为），对既有唯一调用方（前端 Agent 卡片改状态）无回归。

`users.py`、`projects.py`、`auth.py` **不改**——`POST /api/users`（admin）、`PATCH /api/users/<id>`（admin，含 password）、`POST /api/projects`（pm/admin）、`GET /api/projects` 均已满足前端所需，本轮仅**消费**它们。

---

## 3. 文件 / 模块变更计划（File / Module Change Plan）

| # | 文件 | 动作 | 一句话意图 |
|---|------|------|-----------|
| 1 | `frontend/components/admin/MemberFormModal.tsx` | **新增** | 建 / 改成员 + 重置密码的三态弹窗（复用 `Modal`+UI Kit；含自我降级保护）。 |
| 2 | `frontend/components/admin/AgentFormModal.tsx` | **新增** | 建 / 改 Agent 弹窗（name/kind/description[/status]；diff 提交）。 |
| 3 | `frontend/components/admin/ProjectFormModal.tsx` | **新增** | 新建项目弹窗（name/key 大写化/description）。 |
| 4 | `frontend/app/(app)/projects/page.tsx` | **新增** | 项目列表页 + 「+新建项目」入口 + owner 解析。 |
| 5 | `frontend/app/(app)/team/page.tsx` | 修改 | Header 加「+新增成员」；表格加「操作」列（编辑 / 重置密码）；行内 role 下拉并入弹窗。 |
| 6 | `frontend/app/(app)/agents/page.tsx` | 修改 | Header 加「+新建 Agent」；卡片操作行加「编辑」。 |
| 7 | `frontend/components/layout/Sidebar.tsx` | 修改 | `NAV` 增「项目」入口（团队与设置之间）。 |
| 8 | `frontend/lib/types.ts` | 修改 | 新增 `UserCreate`/`UserUpdate`/`AgentInput`/`ProjectCreate` 载荷型（薄类型，供弹窗 props 与 api 调用）。 |
| 9 | `backend/routes/agents.py` | 修改 | `patch_agent` 门禁收紧 `admin/pm`；受理 `name`（唯一）/`kind`（枚举）。 |
| 10 | `backend/tests/test_admin_console.py` | **新增** | ≥12 条集成回归：用户建改 / 改密真实校验、Agent 建改 / 改名唯一 / 门禁、项目建 / key 唯一 / 门禁。 |

**不改动**：`models/*`（零 schema 变更）、`workflow.py`（零状态机改动）、`services/notifications.py`（零通知改动）、`routes/users.py`/`projects.py`/`auth.py`（写接口已完备）、`lib/api.ts`（`api.post`/`patch` 已够用）、`lib/constants.ts`（`ROLE_LABELS`/`AGENT_*_LABELS` 已存在）。

---

## 4. 接口设计（Interface Design）

### 4.1 复用的 REST 接口（无新增端点、仅 Agent PATCH 增可选入参）

| 方法 · 路径 | 权限 | 请求体 | 成功 | 关键错误 |
|---|---|---|---|---|
| `POST /api/users` | admin | `{username*, password*, role?, display_name?, email?}` | `201 User` | 400 缺字段 / 非法 role；409 username 已存在 |
| `PATCH /api/users/<id>` | admin | 任意子集 `{display_name?, email?, role?, password?}` | `200 User` | 404；400 非法 role |
| `POST /api/agents` | admin/pm | `{name*, kind?, description?}` | `201 Agent` | 400 缺 name / 非法 kind；409 name 已存在 |
| `PATCH /api/agents/<id>` | **admin/pm**〔收紧〕 | 任意子集 `{name?, kind?, status?, description?}`〔name/kind 本轮新增〕 | `200 Agent` | 404；400 缺 name / 非法 kind / 非法 status；409 name 已存在 |
| `POST /api/projects` | admin/pm | `{name*, key*, description?}` | `201 Project` | 400 缺字段；409 key 已存在 |
| `GET /api/projects` · `GET /api/users` | 任意登录 | — | `200 T[]` | — |

（`*` 为必填。`?` 为可选。）

> **表注【v2·C1】**：`PATCH /api/agents/<id>` 的 REST 契约仍接受完整 `status` 枚举（含 `busy`，后端 `agents.py` 对 status 的处理**逐字不变**）——**限制只在 UI 层**：`AgentFormModal` 编辑态只提供 `idle`/`offline` 供人工选择，`busy` 由自主编排软锁独家托管，避免人工把 Agent 永久锁出编排（详见 §2.3）。

### 4.2 组件契约

```ts
// MemberFormModal：三态合一（create / edit / reset）
type MemberFormState =
  | { mode: "create" }
  | { mode: "edit"; user: User }
  | { mode: "reset"; user: User };
interface MemberFormModalProps {
  state: MemberFormState | null;   // null → 关闭
  onClose: () => void;
  onSaved: () => void;             // 成功后：关闭 + mutate("/users")
}

// AgentFormModal：create / edit
type AgentFormState = { mode: "create" } | { mode: "edit"; agent: Agent };
interface AgentFormModalProps {
  state: AgentFormState | null;
  onClose: () => void;
  onSaved: () => void;             // 成功后：关闭 + mutate("/agents")
}

// ProjectFormModal：仅 create
interface ProjectFormModalProps {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;             // 成功后：关闭 + mutate("/projects")
}
```

### 4.3 新增 TS 载荷型（`lib/types.ts`）

```ts
export interface UserCreate { username: string; password: string; role: Role; display_name?: string; email?: string; }
export interface UserUpdate { display_name?: string; email?: string; role?: Role; password?: string; }
export interface AgentInput { name?: string; kind?: AgentKind; status?: AgentStatus; description?: string; }
export interface ProjectCreate { name: string; key: string; description?: string; }
```

---

## 5. 数据模型（Data Model）

**无变更。** 复用现有三表，均已建模且已有 `to_dict()`：

- `User`（`username`/`email`/`role`/`display_name`/`avatar_color`）——成员管理源。新成员由后端 `_pick_color(username)` 分配头像底色；`set_password` 走既有 `pbkdf2:sha256`（R-06），改密即真实换哈希。
- `Agent`（`name`/`kind`/`status`/`description`）——AI 团队成员源；本轮新增前端建改入口，`name` 唯一约束由 DB `unique=True` + 路由 409 双重保证。
- `Project`（`name`/`key`(unique)/`description`/`owner_id`）——项目容器；新建时后端以 `current_user()` 填 `owner_id`。

**零新表 / 零列变更 / 零索引变更**，符合 CLAUDE.md「Phases 2 & 3 只新增 `notifications` 一张表」的向后兼容基线。

---

## 6. 测试与验收标准（Testing & Acceptance）

### 6.1 后端 pytest（新增 `backend/tests/test_admin_console.py`）

沿用 `conftest` 既有 fixtures（`client`/`auth`/`data`；角色 `admin`/`pm`/`member`/`member2`，`data` 提供 `dev_agent_id`/`qa_agent_id`/`project_id` 等 id）。覆盖正常路径 + 至少一条异常路径（CLAUDE.md §7）：

**用户（Team）**
1. `test_admin_creates_member`：admin `POST /api/users {username:"carol", password:"pw123456", role:"member"}` → 201；随后 `GET /api/users` 含 carol。
2. `test_create_member_duplicate_username_conflicts`：以既有 `member` 用户名再建 → 409。
3. `test_admin_patches_member_profile_and_role`：`PATCH /api/users/<member_id> {display_name:"Mia2", email:"mia@x.io", role:"pm"}` → 200，返回体三字段同步。
4. `test_admin_resets_member_password`（**真实改密集成，禁 mock**）：`PATCH /api/users/<member_id> {password:"newpw123"}` → 200；旧密登录 401、新密登录 200。守护「改密真实生效」。
5. `test_member_cannot_create_or_patch_user`：member `POST /api/users` 与 `PATCH /api/users/<id>` 均 403（后者补齐既有 `test_member_cannot_create_user` 未覆盖的 patch 门禁）。

**Agent**
6. `test_pm_creates_agent`：pm `POST /api/agents {name:"sec-agent", kind:"generic"}` → 201。
7. `test_create_agent_duplicate_name_conflicts`：以 `dev-agent` 再建 → 409。
8. `test_patch_agent_name_kind_description`（**本轮新增后端能力**）：`PATCH /api/agents/<qa_agent_id> {name:"qa-agent-2", kind:"generic", description:"x"}` → 200，三字段同步。
9. `test_patch_agent_rename_to_existing_conflicts`：把 `qa-agent` 改名为 `dev-agent` → 409；改回自己现名（`{name:"qa-agent"}`）→ 200（`id != self` 排除，不误报）。
10. `test_patch_agent_invalid_kind_rejected`：`{kind:"bogus"}` → 400。
11. `test_member_cannot_edit_agent`（**本轮 RBAC 收紧**）：member `PATCH /api/agents/<dev_agent_id> {description:"x"}` → 403。

**项目**
12. `test_pm_creates_project` / `test_create_project_duplicate_key_conflicts` / `test_member_cannot_create_project`：201 / 409（用 `data["project_id"]` 对应项目的 key `TST`）/ 403。

**回归**：既有全部用例（含 `test_rbac.py`、`test_agent_autopilot.py`）须**仍绿**——门禁收紧仅影响 `PATCH /agents/<id>`（无既有测试直接调用），扩参为纯可选。

### 6.2 前端质量门（无前端单测框架，走 typecheck + build）

- `cd frontend && npm run typecheck` → 0 error（三弹窗 props、`MemberFormState`/`AgentFormState` 判别联合、diff 构造、新载荷型均需类型正确）。
- `cd frontend && npm run build` → 成功（含新 `projects` 路由与受影响的 `team`/`agents` 页）。

### 6.3 手动冒烟（Definition of Done 级）

1. **建成员**：admin 登录 → 团队页「+新增成员」→ 填 `carol/pw123456/成员` → 提交 → 列表出现 carol；退出以 carol 登录成功。
2. **改资料 + 改角色**：admin 编辑某成员改显示名 / 邮箱 / 角色 → 保存 → 列表即时反映；编辑**自己**时角色 Select 禁用且有提示。
3. **重置密码**：admin 对某成员「重置密码」→ 该成员旧密登录失败、新密成功。
4. **建 / 改 Agent**：pm 登录 → Agent 页「+新建 Agent」建 `sec-agent` → 卡片出现；对其「编辑」改名 / 改类型 / 改描述 → 卡片即时反映。**【v2·C1】** 编辑态 status 下拉**只含「空闲 / 离线」、不含「忙碌」**。
5. **项目**：pm 打开「项目」页 → 「+新建项目」建 `key=DEMO` → 列表出现，负责人为当前 pm；再建同 key → 弹出错误 toast（承接后端 `409 project key already exists`）。**【v2·C5】** 判定口径为「出现 409 错误 toast」而非字面中文串——现阶段前端直显后端英文文案（全仓既有惯例）；若实现时选择在弹窗层把关键 409/400 映射为中文，则改判「toast 含『已存在』」。
6. **权限门禁**：以 member 登录 → 团队页无「+新增成员 / 操作列」、Agent 页无「+新建 / 编辑」、项目页无「+新建项目」（仅可看列表）。

### 6.4 验收判定

- 后端 `pytest -q` 全绿（既有基线全部通过 + 本轮 ≥12 新增，**无既有断言改动**）；**【v2·C7】** 既有基线以**实测真实数**为准——当前仓库共 **154** 个 `def test_`（CLAUDE.md 记载的「93 cases」系 Phase-3 旧值、已过时，Iter2–4 增补后为 154），本 spec 不硬编码该数字，仅要求「既有全部用例仍绿 + 新增 ≥12」。
- 前端 `npm run typecheck` 0 error 且 `npm run build` 成功；
- §6.3 六项冒烟全过。

---

## 7. 风险与缓解（Risks & Mitigations）

| # | 风险 | 类型 | 缓解 |
|---|------|------|------|
| R1 | 管理员编辑自己时把 `role` 降为 member → 自锁（失去管理权） | 越权 / 自锁 | `MemberFormModal` edit 态在 `user.id === me.id` 时**禁用** role Select + 提示；后端无 user DELETE 接口，故无自删风险。§6.3-2 冒烟覆盖。 |
| R2 | Agent PATCH 门禁收紧破坏既有回归 | 回归 | 全仓核验：**无**测试直接调 `PATCH /agents/<id>`（仅 claim-next/autorun/tick，均已 pm/admin）；新增 `test_member_cannot_edit_agent` 锁定新契约；CLAUDE.md 已有 `agent-advance` 收紧先例，属**有意契约变更**并记于本文与提交信息。 |
| R3 | 改名唯一性把「改成自己现名」误判 409 | 结果错误 | 唯一性查询带 `Agent.id != agent.id` 排除自身；§6.1-9 专项断言「改回现名 → 200」。 |
| R4 | 新增成员 / 项目后 SWR 列表缓存陈旧、不刷新 | 数据新鲜度 | 每个 `onSaved` 显式 `mutate(key)`（`/users`/`/agents`/`/projects`）；SWR 默认 `revalidateOnFocus` 兜底。 |
| R5 | 前端隐藏了入口但 API 仍可被越权直调 | 安全 | 前端隐藏仅为体验；**后端 `require_role` 才是权威**（admin 建 / 改用户、pm/admin 建 / 改 Agent 与项目），§6.1 门禁用例守护。 |
| R6 | 密码强度无策略（后端接受任意非空） | 健壮性（有限） | 本轮前端加**软约束**（新密最短 6 位、创建密码必填的即时校验 + 提示），不改后端契约；正式密码策略按 §后续路线交棒，避免破坏既有 seed 弱口令与测试。 |
| R7 | 项目页只做「列表 + 新建」，用户期望能编辑 / 删除 | 范围落差 | 后端仅提供 list/create，本文**显式声明**项目编辑 / 删除 out-of-scope 并交棒（§8）；UI 不放置「编辑 / 删除」假按钮，避免言行不一。 |
| R8 | `key` 未大写 / 超长导致 409 或截断困惑 | 输入体验 | `ProjectFormModal` `onChange` 即 `toUpperCase()` + `maxLength=16`（对齐 `Project.key` VARCHAR(16) 与后端 `.upper()`）；重复 key 直显后端 409 文案。 |
| R9 | **【v2·C1】** 人工把 Agent 状态设成 `busy` → 永久锁出自主编排（软锁无归位者） | 正确性 / 可用性 | `AgentFormModal` 编辑态**不暴露 `busy`**，仅 `idle`/`offline` 可人工选；`busy` 系统托管；当前 busy 时只读展示且仅允许改 idle/offline。§4.1 表注 + §2.3 明述；建议新增冒烟：编辑态 status 选项不含「忙碌」。 |
| R10 | **【v2·C2】** 管理台写入非法邮箱（后端 `users.py` 不校验格式），与 `/me/profile` 校验不一致 | 一致性 | `MemberFormModal` 前端软校验邮箱格式（非空时），后端契约不变；与 R6 密码软约束同策略。 |

---

## 8. 后续迭代路线（本轮 Out of Scope，交棒未来）

承接 `mention-autocomplete/spec.md §9` 未尽项，按价值 / 风险续排：

1. **项目管理深化**：`PATCH /api/projects/<id>`（改名 / 换 owner / 描述）与归档 / 删除；需求 / BUG 创建表单接入项目选择（当前 `project_id` 恒为 seed 项目）；看板 / 列表按项目过滤。
2. **LLM 运行时配置管理台**（A4，谨慎）：把 Iter1 的 LLM 接入做成 admin-only 配置页——**仅存** provider / model / base_url + 密钥走 env / 密钥库**引用**，明文密钥不落库。
3. **成员生命周期**：停用 / 归档用户（软删）、密码策略（最短长度 / 复杂度）、批量邀请；`@提及` 补全纳入 Agent。**【v2·C6】** 纵深防御：为 `PATCH /api/users/<id>` 增后端不变量守护「拒绝把最后一名 admin 降级 / 拒绝把自己降级」——当前经 UI 已不可达零 admin（前端 R1 禁用自我降级），此项仅为把该不变量下沉到权威层、覆盖 API 直调场景。
4. **审计增强**：管理写操作（建 / 改用户 / Agent / 项目）纳入 `Activity` 审计流，与既有工单审计一致可追溯。

---

## 9. 实施顺序与回滚（Implementation Order & Rollback）

**建议落地顺序**（每步可独立编译 / 测试，便于回滚）：

1. 后端 §2.5：改 `patch_agent`（门禁 + name/kind）→ 跑既有 `pytest -q` 确认全绿。
2. 后端 §6.1：新增 `test_admin_console.py` ≥12 用例 → `pytest -q` 全绿。
3. 前端 §4.3：`lib/types.ts` 加 4 个载荷型 → `typecheck`。
4. 前端 §2.2：`MemberFormModal` + `team/page.tsx` 接入 → `typecheck`。
5. 前端 §2.3：`AgentFormModal` + `agents/page.tsx` 接入 → `typecheck`。
6. 前端 §2.4：`ProjectFormModal` + `projects/page.tsx` + `Sidebar` 入口 → `typecheck` + `build` + §6.3 冒烟。

**回滚边界**：前端 6 处改动互不耦合、可独立回退；后端单点改动是**纯增量 + 门禁收紧**（新可选入参 + 更严 role），`git revert` 即可干净回退；全程零 schema 迁移。

---

## 评审结论（Review Verdict）

**结论：有条件通过（Approved with Conditions）。**

**通过依据**：方案的每一处关键技术断言均已逐一比对源码核实为真（详见 §评审记录 核实过程 ①–⑦）；可行性、完备性、一致性、合理规模四维均达标；恪守 CLAUDE.md「状态机神圣 / 向后兼容（零新表）/ 通知收口唯一」三约定；唯一后端改动（`patch_agent` 门禁收紧 + 扩 `name`/`kind`）经全仓核验对既有 154 用例**零回归**，且有 Phase-3 `agent-advance` 收紧先例，属**有意契约变更**。**唯一 P1（C1：编辑弹窗暴露 `busy` 软锁 → 可永久锁死 Agent 编排）已在 v2 正文修复**（§2.3 / §4.1 表注 / R9）；C2、C3 两项 P2 亦顺手在正文加固。**当前无任何未解决的 P0 / P1。**

**落地条件（P2，实现与验收时须遵守，不阻塞设计通过）**：

1. **（C4）** `MemberFormModal` 三态实现须按模式拆分渲染 / 提交逻辑（每态子函数或策略表），单函数守住 CLAUDE.md 阈值（≤50 行 / 圈复杂度 ≤10 / 嵌套 ≤4）。
2. **（C5）** 错误 toast 语言口径二选一并在实现中固定：直显后端英文文案（则冒烟按「出现 409 错误 toast」判定），或在弹窗层将关键 409/400 映射为中文（则可按中文串判定）；§6.3-5 已给出双口径。
3. **（C1 验收）** 新增一条冒烟 / 组件断言：`AgentFormModal` 编辑态 status 选项**不含「忙碌」**，防止回归重新暴露软锁。
4. **（C2）** `MemberFormModal` create/edit 落地邮箱前端软校验（非空时格式检查），保持与 `/me/profile` 一致。
5. **（C7）** 验收以真实 154 用例基线为准；建议一并在下次「regenerate index」时把 CLAUDE.md 的「93 cases」刷新为当前值。

**未来项（非本轮，已入 §8 交棒）**：C6 后端「最后一名 admin 不可降级」不变量下沉。

满足以上条件即视为完整达成本 Loop「稳健可靠好用，顶级」在管理面的闭环。

---

*—— 方案设计：资深工程师（Anthropic Eng）· Subtask #0；设计评审与 v2 修订：资深评审（Anthropic Eng）· Subtask #1 · Loop Iteration 5/5 · 特性 `admin-console`*
