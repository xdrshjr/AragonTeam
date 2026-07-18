# AragonTeam MVP — 开发方案设计（Spec）

- **文档版本**: v2（经 Subtask #1 设计评审，P0/P1 已就地修复）
- **Feature slug**: `aragonteam-mvp`
- **作者角色**: Solution Architect（Anthropic Engineering）｜ **评审角色**: Senior Reviewer（Anthropic Engineering）
- **状态**: Reviewed —— 有条件通过（详见文末「评审结论」）
- **目标读者**: 下游开发工程师（需可据此逐行实现，无需再做架构决策）
- **技术栈**: Next.js (App Router) + React + TypeScript + Tailwind CSS ｜ Python Flask + SQLAlchemy + SQLite ｜ @dnd-kit 拖拽 ｜ JWT 鉴权

---

## 评审记录（Review Notes｜Subtask #1）

> 评审维度：**可行性 Feasibility / 完备性 Completeness / 一致性 Consistency / 规模合理性 Right-sizing**。
> 评审对象：本文档 v1。下表列出全部问题与严重级；**P0 与全部 P1 已在 v2 正文就地修复**（见「修复」列），P2 记录在案，其中低成本项亦已顺手修复，其余留作实施期注意点。
> 说明：本项目为全新目录，无 `CLAUDE.md` 与既有源码，因此「一致性」以**文档内部自洽**与**对既定技术栈的正确用法**为准绳。

| # | 级别 | 维度 | 位置 | 问题描述 | 修复 |
|---|---|---|---|---|---|
| **R-01** | **P0** | 可行性 | §2.2 A · §4.1 | `create_access_token(identity=user.id, …)` 传入 **int**。flask-jwt-extended 4.x 会将 `identity` 写入 JWT 的 `sub` 声明，并在解码时要求 `sub` 为**字符串**，否则 `@jwt_required()` 抛错、**所有受保护接口返回 422**（登录后一切操作失效，直接击穿 T2/T5/T6/T8 与全部看板操作）。 | ✅ v2 §2.2 A 改为 `identity=str(user.id)`，并规定读取侧 `int(get_jwt_identity())`；`auth_helpers.current_user()` 统一封装类型转换。 |
| **R-02** | **P1** | 一致性 | §2.3 | 迁移合法性存在**两个互相矛盾的权威**：邻接表（如允许 `testing→bug_fixing`，跨列）与散文规则「默认放行**相邻+回退**、跨多列判非法」。二者对 `testing→bug_fixing`、`reviewing→bug_fixing` 等给出相反结论，实施者无从取舍，且 U4/T6 行为不可预测。 | ✅ v2 明确**邻接表为唯一事实来源（SSOT）**，看板拖拽一律调用 `can_transition(entity, frm, to)` 查表判定；删除「相邻+回退」启发式；并把终态 `done`/`closed` 的可回退目标写进机器可读集合。 |
| **R-03** | **P1** | 完备性 | §2.1 · §4 · §3.2 | 未定义**全局 JSON 错误处理器**。Flask 对未捕获的 400/404/405/415/422/500 默认返回 **HTML 错误页**，而前端 `lib/api.ts` 的 `ApiError` 假定错误体恒为 `{error, detail?}` JSON —— 任一错误路径都会让前端解析崩溃（尤其 JWT 缺失/过期的 422、非法路由 404）。 | ✅ v2 新增 §2.6「错误处理与响应契约」，规定注册统一 `errorhandler`（含 JWT 回调）把所有错误规整为 `{error, detail?}`；`app.py` 文件意图同步补充。 |
| **R-04** | **P1** | 完备性 | §2.2 C · §3.2 | 依赖**未锁版本**（`requirements.txt` 与 `package.json` 仅列包名）。`pip install` 会拉取 flask-jwt-extended / SQLAlchemy 2.x / werkzeug 3.x 最新版，正是触发 R-01、以及 SQLAlchemy 2.0 破坏性变更的根因；不利于「稳健、可靠」的可复现构建。 | ✅ v2 §8 给出**锁定版本**的 `requirements.txt` 全文，并对前端关键依赖锁定主版本（`^`）；§3.2 对应行注明「带版本锁」。 |
| **R-05** | **P1** | 一致性/规模 | §2.2 C | 「需求转 BUG」后源需求置为 `bug_fixing` **或保留 `testing`「视配置」** —— 把架构决策下放给了下游，违反本文「无需再做架构决策」的定位，且与 §2.3 状态机需要确定入边相冲突。 | ✅ v2 定死：转 BUG 后源需求**统一迁移到 `bug_fixing`**（该操作为业务动作，经 `can_transition` 校验当前态∈{`testing`,`reviewing`} 后置位），删除「视配置」选项。 |
| **R-06** | P2 | 可行性 | §2.2 D · seed | werkzeug 3.x `generate_password_hash` 默认算法为 `scrypt`，在部分未启用 scrypt 的 OpenSSL 构建上会抛 `ValueError`。 | ✅ 已顺手修复：v2 规定统一 `method="pbkdf2:sha256"`，跨平台确定可用。 |
| **R-07** | P2 | 一致性 | §5 requirements | `requirements.related_bug_id` 为单值列，但一个需求可转出**多个** BUG（一对多），单列只能存「最近一个」，语义含糊。 | ✅ 已修复：v2 删除该列，需求→BUG 的反查一律走 `bugs.related_requirement_id`（并建索引）。 |
| **R-08** | P2 | 完备性 | §2.4 · §4 | `assign` / `move` 接口未声明角色守卫，MVP 实为**任意登录用户可操作任意单**（行级「仅限本人相关」明确延期）。需显式写明以免被误读为已做权限收敛。 | ✅ 已在 v2 §2.4 显式声明：MVP 下 `assign`/`move` 仅需 `@jwt_required()`，行级校验以 TODO 标注。 |
| **R-09** | P2 | 完备性 | §2.2 B · §5 | 列内 `position` 的重排语义未定义（拖到中间是否需要为同列其它卡重算 position）。 | ✅ v2 §2.2 B 给出 MVP 简化方案：落入目标列时 `position = 目标列现有最大值 + 1`（追加到末尾），不做整列重排；同列内相对排序为增强项、留 TODO。 |
| **R-10** | P2 | 一致性 | §5 requirements | `assignee_type` 枚举写作 `user\|agent\|null`，把「可空」混入枚举值，易被实现为字面量 `'null'`。 | ✅ v2 澄清：列可空（`nullable=True`），枚举取值集合为 `{user, agent}`，未指派时该列为 SQL `NULL`。 |
| **R-11** | P2 | 完备性 | §2.3 · §2.4 | 通过看板把需求拖入 `assigned` 列不会自动写入 `assignee`，可能出现「已指派」态但 `assignee_id=NULL`。 | v2 §2.3 增注：`assigned` 列语义为「待人/Agent 认领」，拖入不强制 assignee；正式指派通过 `assign` 接口完成。作为已知取舍保留，实施期注意。 |

**结论摘要**：无致命的架构方向性错误；核心闭环（鉴权 / CRUD / 状态机 / 拖拽持久化 / 转 BUG / 审计）设计成立、规模对 MVP 合理。上述 P0/P1 均为「按当前依赖版本落地时确定会踩」的工程性缺陷，已在 v2 正文修复。

---

## 0. 背景与既有约定说明

当前工作目录 `M:\takoAI\AragonTeam` 为全新目录，仅含运行时 `.agentmesh/`，**不存在** `README.md` / `CLAUDE.md` / 既有源码。因此本项目从零搭建，没有需要遵循的历史约定，所有目录结构与编码规范由本方案确立，作为后续所有子任务的唯一事实来源（single source of truth）。参考只读根目录 `.../resources/server` 为 AgentMesh 运行时自身（Node/Next/drizzle），与本项目业务无关，不作为约定来源。

本文所有路径均使用正斜杠 `/`；命令均给出跨平台（Windows PowerShell / cmd 兼容）写法；代码标识符使用英文，散文使用中文。

---

## 1. Overview（概述）

**AragonTeam** 是一个面向「AI 时代」的团队协作与研发管理平台。与传统研发管理工具（Jira / 禅道）最本质的区别是：**Agent 是一等公民的执行者**——需求单与 BUG 单不仅可以指派给人类成员，也可以指派给 AI Agent（如 dev-agent、qa-agent）。平台记录人类与 Agent 混合协作的完整流转轨迹，为后续「Agent 自动认领需求、自动开发、自动修 BUG」的能力预留数据结构与接口位。本阶段（MVP）目标是搭建**可运行的完整骨架**：前后端可启动、可登录、可创建/指派/流转需求与 BUG、看板可拖拽、数据可持久化。

系统由三层组成：(1) **Next.js 前端**——左侧竖向功能导航、顶部 Header、右侧主内容区的经典三段式布局，采用 Anthropic 风格的暖色浅色设计（ivory 背景 + clay/coral 强调色 + 衬线标题），仅浅色模式；(2) **Flask REST 后端**——提供鉴权、用户/Agent/项目/需求/BUG/看板/统计等 JSON API，内含需求与 BUG 的**状态机（workflow）**服务以保证流转合法；(3) **SQLite 持久化**——通过 SQLAlchemy ORM 落库，首次启动自动建表并 seed 一批 mock 数据（管理员、若干成员、2 个 Agent、示例需求与 BUG），保证前端「开箱即用」。

核心业务闭环为需求生命周期：**新建 → 指派（人 / Agent）→ 开发中 → 测试中 → 审批中 → 完成**，其中审批不通过或发现缺陷可**一键转 BUG**；BUG 生命周期为：**新建 → 指派 → 修复中 → 验证中 → 关闭**。两条流转都通过看板列（column）可视化，拖拽卡片即触发状态迁移；后端状态机会校验迁移是否合法，非法迁移返回 409 并回滚前端乐观更新。MVP 阶段允许部分数据 mock，但鉴权、CRUD、状态流转、拖拽持久化必须是真实可用的端到端链路。

---

## 2. Technical Design（技术设计）

### 2.1 总体架构

```
┌──────────────────────────── Browser ────────────────────────────┐
│  Next.js (App Router, TS)                                        │
│  ├─ Shell: Sidebar(左) + Header(上) + Content(右)                 │
│  ├─ Pages: /login /dashboard /requirements(+board) /bugs(+board) │
│  │         /agents /team /settings                               │
│  ├─ State: AuthContext(JWT in localStorage) + SWR/fetch          │
│  └─ DnD: @dnd-kit (看板拖拽 → PATCH /move, 乐观更新+回滚)          │
└───────────────▲──────────────────────────────────────────────────┘
                │  HTTP/JSON, Authorization: Bearer <JWT>
┌───────────────┴──────────── Flask (create_app 工厂) ─────────────┐
│  Blueprints: auth / users / agents / projects / requirements /   │
│              bugs / board / stats                                │
│  Services: workflow.py (需求&BUG 状态机, 合法迁移校验)            │
│  Auth: flask-jwt-extended (HS256), werkzeug password hash        │
│  CORS: flask-cors (允许 http://localhost:3000)                   │
│  ORM: Flask-SQLAlchemy → SQLite (aragon.db)                      │
└───────────────▲──────────────────────────────────────────────────┘
                │  SQLAlchemy
        ┌───────┴────────┐
        │  SQLite 文件   │  users / agents / projects /
        │  aragon.db     │  requirements / bugs / activities
        └────────────────┘
```

前后端**分离部署**：前端 dev 跑在 `http://localhost:3000`，后端跑在 `http://localhost:5000`。前端通过环境变量 `NEXT_PUBLIC_API_BASE`（默认 `http://localhost:5000/api`）访问后端。CORS 在后端放行前端 origin。

### 2.2 关键代码路径（Key code paths）

**A. 登录鉴权链路**
1. 用户在 `/login` 提交用户名密码 → 前端 `lib/api.ts` `POST /api/auth/login`。
2. 后端 `routes/auth.py::login` 查 `User`，`werkzeug.security.check_password_hash` 校验，`create_access_token(identity=str(user.id), additional_claims={"role": user.role})` 签发 JWT。
   > **【R-01 修复｜必须遵守】** `identity` **必须传字符串**（`str(user.id)`）：flask-jwt-extended 4.x 要求 JWT 的 `sub` 声明为字符串，传 int 会导致解码期 `@jwt_required()` 报错、所有受保护接口返回 422。相应地，读取侧统一 `int(get_jwt_identity())` 转回整型主键；该转换封装在 `services/auth_helpers.py::current_user()` 内，业务代码不得直接把 `get_jwt_identity()` 当作 int 使用。`role` 从 `additional_claims` 读取仅用于**粗粒度装饰器校验**，敏感操作仍以库内 `User.role` 为准（见 §7 安全项）。
3. 前端把 `token` 存 `localStorage["aragon_token"]`，`user` 存内存 `AuthContext`，后续所有请求带 `Authorization: Bearer`。
4. 受保护页面在 `(app)/layout.tsx` 检查 `AuthContext`，未登录重定向 `/login`；刷新时用 `GET /api/auth/me` 复原会话。

**B. 需求状态流转链路（核心）**
1. 前端看板拖拽卡片从「开发中」列拖到「测试中」列 → `onDragEnd` 计算目标 `status` 与 `position`。
2. **乐观更新**：立即更新本地列数据；同时 `PATCH /api/requirements/:id/move { status, position }`。
3. 后端 `routes/requirements.py::move` 调 `services/workflow.py::can_transition(entity="requirement", frm, to)` 校验；合法则更新 `status`+`position` 并写 `Activity` 审计记录；非法返回 `409 {error, allowed:[...]}`。
4. 前端若收到非 2xx → **回滚**本地状态并 toast 错误提示。
> **【R-09 修复｜position 语义】** MVP 简化排序方案：卡片落入目标列时后端令 `position = 该列现有最大 position + 1`（追加到列尾），**不做整列重排**，避免一次拖拽触发多行 UPDATE 的复杂度与竞态。看板查询按 `ORDER BY position ASC, id ASC` 取卡。「同列内任意位置精确插入 + 重排」列为后续增强项（`# TODO(board-reorder)`），不在本期实现。前端 `move` 请求可不传 `position`（由后端计算），传入亦以后端为准。

**C. 需求转 BUG 链路**
1. 需求详情页/审批列点击「转 BUG 修复」→ `POST /api/requirements/:id/convert-to-bug { title?, severity? }`。
2. 后端事务内：**先校验** `can_transition("requirement", 需求.status, "bug_fixing")`（要求当前态 ∈ `{testing, reviewing}`，否则返回 `409 {error, allowed}`）；随后创建 `Bug`（`related_requirement_id` 指向源需求，status=`open`），将源需求**统一置为 `bug_fixing`**，并写两条 `Activity`（需求 `converted` + BUG `created`）；返回新建 BUG。
   > **【R-05 修复】** 取消 v1 的「或保留 `testing` 视配置」二义写法：转 BUG 后源需求**恒迁移到 `bug_fixing`**，作为唯一确定行为，下游无需再做选择。反查该需求转出的全部 BUG 一律通过 `bugs.related_requirement_id`（一对多）。
3. 前端跳转到 BUG 看板并高亮新卡片。

**D. 首次启动 seed**
`backend/seed.py::seed_if_empty()` 在 `create_app` 后、`db.create_all()` 之后调用：若 `User` 表为空，则插入 admin/pm/两名 member、两个 Agent、一个默认 project、若干示例 requirement 与 bug（覆盖各状态列，便于看板一启动就有内容）。
> **【R-06 修复】** 所有口令统一以 `generate_password_hash(pw, method="pbkdf2:sha256")` 生成——werkzeug 3.x 默认算法 `scrypt` 在部分 OpenSSL 构建上不可用会抛错，`pbkdf2:sha256` 跨平台确定可用，符合「稳健、可靠」要求。`db.create_all()` 前必须已 `import` 全部模型（经 `models/__init__.py` 汇总），否则表不会注册。

### 2.3 需求状态机（Workflow State Machine）

需求 `RequirementStatus`（即看板列，从左到右）：

| key | 中文列名 | 允许迁移到 |
|---|---|---|
| `new` | 新建 | `assigned` |
| `assigned` | 已指派 | `in_development`, `new` |
| `in_development` | 开发中 | `testing`, `assigned` |
| `testing` | 测试中 | `reviewing`, `bug_fixing`, `in_development` |
| `reviewing` | 审批中 | `done`, `bug_fixing`, `testing` |
| `bug_fixing` | 修复中 | `testing`, `in_development` |
| `done` | 已完成 | `reviewing`（准终态：默认不再流出，仅允许回退到 `reviewing` 以纠错）|

BUG 状态 `BugStatus`（看板列）：

| key | 中文列名 | 允许迁移到 |
|---|---|---|
| `open` | 新建 | `assigned` |
| `assigned` | 已指派 | `fixing`, `open` |
| `fixing` | 修复中 | `verifying`, `assigned` |
| `verifying` | 验证中 | `closed`, `fixing` |
| `closed` | 已关闭 | `verifying`（准终态：默认不再流出，仅允许回退到 `verifying` 以纠错）|

`workflow.py` 用两张 `dict[str, set[str]]` 邻接表（内容**逐字**等于上两张表的「允许迁移到」列，含终态的回退目标 `done→{reviewing}`、`closed→{verifying}`）实现 `can_transition(entity, frm, to)`，并暴露 `next_states(entity, frm)` 供前端渲染「下一步」按钮、`is_terminal(entity, s)`。

> **【R-02 修复｜迁移合法性的唯一事实来源】** 迁移是否合法**只由上述邻接表判定**，不存在第二套规则。v1 中「默认放行相邻 + 回退、跨多列判非法」的启发式描述**已删除**——它与邻接表冲突（例如邻接表允许 `testing→bug_fixing`、`reviewing→bug_fixing` 这类非相邻迁移，而「仅相邻」会误判其非法）。看板 `onDragEnd` 计算出目标 `status` 后，一律以 `PATCH …/move` 交后端 `can_transition` 查表裁决：命中返回 200，未命中返回 `409 {error, allowed:list}`，前端据此回滚。因此 T6 的 `new→done` 判非法、U4 的跨列非法拖拽回滚，均由「目标态不在源态邻接集合内」这一条规则统一解释。
>
> **【R-11 说明】** `assigned` 列语义为「已进入指派环节 / 待认领」，通过看板将卡片拖入 `assigned` 列**不强制**写入 `assignee`（允许出现 `assigned` 态而 `assignee_id=NULL` 的过渡态）；正式指派人/Agent 通过 `assign` 接口完成。此为 MVP 已知取舍。

### 2.4 权限模型（RBAC，MVP 简化）

三角色：`admin`（全权：管理用户/Agent/项目）、`pm`（项目经理：建/指派/流转需求与 BUG、审批）、`member`（普通成员：认领与流转自己相关的单）。MVP 采用**装饰器级粗粒度校验**：`@require_role("admin")` / `@require_role("admin","pm")`，行级（只能改自己的单）留 TODO 注释，不在本期强制。所有写接口需登录（`@jwt_required()`）。

> **【R-08 修复｜权限守卫的明确边界】** 为避免被误读为「已做权限收敛」，此处显式声明各写接口的 MVP 守卫级别：
> - `@require_role("admin")`：`POST/PATCH /api/users`。
> - `@require_role("admin","pm")`：创建/删除需求与 BUG（`POST /requirements`、`DELETE /requirements/:id`、`POST /bugs`、`DELETE /bugs/:id`）、创建 Agent/项目。
> - **仅 `@jwt_required()`（任意登录用户可操作任意单）**：`assign`、`move`、`convert-to-bug`、`PATCH` 详情、`convert`。即 MVP 阶段成员可流转/认领**任意**单——「仅限本人相关」的行级校验统一以 `# TODO(rbac-row-level)` 标注，明确延期到后续迭代，本期不实现，也不得声称已实现。

### 2.5 Anthropic 设计系统（Design tokens，落到 `tailwind.config.ts`）

仅浅色。核心令牌：

| token | 值 | 用途 |
|---|---|---|
| `bg` (ivory) | `#F7F4EE` | 页面背景 |
| `surface` | `#FFFFFF` | 卡片/面板 |
| `border` | `#E7E1D6` | 分隔线/描边 |
| `ink` | `#1A1A17` | 主文本 |
| `ink-muted` | `#6E6A62` | 次文本 |
| `clay` (primary) | `#C15F3C` | 主强调/按钮 |
| `clay-soft` | `#E8C9BC` | 强调浅底 |
| `accent-blue` | `#3B6EA5` | 信息态 |
| 字体 | serif: `Georgia, "Tiempos", serif`（标题）；sans: `system-ui, Inter, sans-serif`（正文）| 排版 |
| 圆角 | `rounded-xl`(12px) 卡片，`rounded-lg`(8px) 控件 | 形状 |
| 阴影 | `shadow-[0_1px_2px_rgba(0,0,0,0.04)]` 轻投影 | 层次 |

状态徽章（badge）配色：`new/open`=灰、`assigned`=蓝、`in_development/fixing`=clay、`testing/verifying`=琥珀、`reviewing`=紫、`done/closed`=绿。集中定义在 `frontend/lib/constants.ts`，前后端 status key 必须一致。

### 2.6 错误处理与响应契约（R-03 新增）

前端 `lib/api.ts` 的 `ApiError` 假定**所有**非 2xx 响应体均为 `{ "error": string, "detail"?: any }` JSON。而 Flask 默认对未捕获异常/路由错误返回 **HTML 错误页**，会让前端 `res.json()` 解析失败并连锁崩溃。为此后端**必须**在 `create_app()` 内注册统一错误处理，把全部错误规整成契约 JSON：

- **HTTP 异常**：`@app.errorhandler(HTTPException)` → 返回 `{"error": e.name, "detail": e.description}`，`status = e.code`（覆盖 400/401/403/404/405/415/409）。
- **JWT 相关**（flask-jwt-extended 回调，统一 401/422 均走 JSON）：`@jwt.unauthorized_loader`（缺 token）、`@jwt.invalid_token_loader`（token 非法/`sub` 类型错，见 R-01）、`@jwt.expired_token_loader`（过期）、`@jwt.revoked_token_loader`，一律返回 `{"error": ...}` + 对应状态码。
- **业务 409（非法状态迁移）**：由路由主动 `return {"error": "illegal transition", "detail": {"from":…, "to":…}, "allowed": [...]}, 409`。
- **兜底 500**：`@app.errorhandler(Exception)` → 记录日志后返回 `{"error": "internal server error"}`, 500，**不泄露堆栈**。
- **请求体解析**：读 body 统一用 `request.get_json(silent=True)` 并显式判空返回 400，避免 415/内部异常穿透。

契约 JSON 的 `error` 为面向用户可读的短语，`detail` 为可选调试信息；前端只依赖 `error` 字段渲染 toast，因此该字段在任何错误路径下都必须存在。

---

## 3. File / Module Change Plan（文件变更计划）

> 全部为**新建**。根目录 `M:/takoAI/AragonTeam` 下分 `frontend/`（Next.js）与 `backend/`（Flask）两个子项目 + 顶层文档/脚本。

### 3.1 顶层

| 文件 | 意图（一句话）|
|---|---|
| `README.md` | 项目简介 + 前后端启动步骤 + 默认账号 |
| `.gitignore` | 忽略 `node_modules/`、`.next/`、`__pycache__/`、`*.db`、`.venv/`、`.env*` |
| `docs/plans/aragonteam-mvp/spec.md` | 本设计文档（已存在）|

### 3.2 Backend（`backend/`）

| 文件 | 意图 |
|---|---|
| `backend/requirements.txt` | 依赖（**必须锁版本**，见 §8 全文）：flask, flask-cors, flask-sqlalchemy, flask-jwt-extended, werkzeug |
| `backend/config.py` | 配置类：`SECRET_KEY`、`JWT_SECRET_KEY`、`SQLALCHEMY_DATABASE_URI=sqlite:///aragon.db`、`SQLALCHEMY_ENGINE_OPTIONS={"connect_args":{"timeout":15}}`、CORS origin |
| `backend/extensions.py` | 实例化 `db = SQLAlchemy()`、`jwt = JWTManager()`（延迟 init）|
| `backend/app.py` | `create_app()` 工厂：注册扩展/蓝图/CORS、**注册 §2.6 全局错误处理器与 JWT 回调**、`import` 全部模型后 `db.create_all()`、`seed_if_empty()`；`__main__` 起 5000 |
| `backend/errors.py` | §2.6 错误契约：`register_error_handlers(app, jwt)`（HTTPException / 兜底 500 / JWT loaders 统一 JSON）|
| `backend/seed.py` | 幂等 seed：mock 用户/Agent/项目/需求/BUG |
| `backend/models/__init__.py` | 汇总导出所有模型 |
| `backend/models/user.py` | `User`（含 `set_password`/`check_password`/`to_dict`）|
| `backend/models/agent.py` | `Agent`（AI 执行者：name/kind/status/description）|
| `backend/models/project.py` | `Project`（name/key/description/owner_id）|
| `backend/models/requirement.py` | `Requirement`（含 assignee 多态、status、position、时间戳、`to_dict`）|
| `backend/models/bug.py` | `Bug`（severity、status、position、related_requirement_id、`to_dict`）|
| `backend/models/activity.py` | `Activity`（审计：entity_type/entity_id/action/from/to/actor/created_at）|
| `backend/services/workflow.py` | 状态机邻接表 + `can_transition` / `next_states` / `is_terminal` |
| `backend/services/auth_helpers.py` | `require_role(*roles)` 装饰器、`current_user()` 取当前用户 |
| `backend/routes/__init__.py` | `register_blueprints(app)` |
| `backend/routes/auth.py` | `login` / `me` / `register`(admin) |
| `backend/routes/users.py` | 用户 CRUD（list/create/get/patch）|
| `backend/routes/agents.py` | Agent CRUD |
| `backend/routes/projects.py` | 项目 list/create/get |
| `backend/routes/requirements.py` | 需求 CRUD + `assign` + `move` + `convert-to-bug` + `activities` |
| `backend/routes/bugs.py` | BUG CRUD + `assign` + `move` |
| `backend/routes/board.py` | `GET /board/requirements`、`GET /board/bugs`（按列分组）|
| `backend/routes/stats.py` | `GET /stats` 仪表盘计数 |

### 3.3 Frontend（`frontend/`）

| 文件 | 意图 |
|---|---|
| `frontend/package.json` | next/react/typescript/tailwind/@dnd-kit/swr 依赖与脚本（**锁定主版本**，见 §8）|
| `frontend/next.config.mjs` | 基础配置（reactStrictMode）|
| `frontend/tsconfig.json` | TS 配置（`@/*` 路径别名）|
| `frontend/tailwind.config.ts` | 注入 §2.5 设计令牌 |
| `frontend/postcss.config.js` | tailwind + autoprefixer |
| `frontend/.env.local.example` | `NEXT_PUBLIC_API_BASE=http://localhost:5000/api` |
| `frontend/app/globals.css` | Tailwind 指令 + 基础排版（衬线标题、暖底）|
| `frontend/app/layout.tsx` | 根布局：字体、`<AuthProvider>` |
| `frontend/app/page.tsx` | 重定向到 `/dashboard`（未登录→`/login`）|
| `frontend/app/login/page.tsx` | 登录页（含默认账号提示）|
| `frontend/app/(app)/layout.tsx` | 应用外壳：Sidebar+Header+Content，鉴权守卫 |
| `frontend/app/(app)/dashboard/page.tsx` | 仪表盘：统计卡 + 最近活动 |
| `frontend/app/(app)/requirements/page.tsx` | 需求列表（表格 + 新建/指派）|
| `frontend/app/(app)/requirements/board/page.tsx` | 需求看板（可拖拽）|
| `frontend/app/(app)/bugs/page.tsx` | BUG 列表 |
| `frontend/app/(app)/bugs/board/page.tsx` | BUG 看板（可拖拽）|
| `frontend/app/(app)/agents/page.tsx` | Agent 列表与状态 |
| `frontend/app/(app)/team/page.tsx` | 成员列表（admin 可增改角色）|
| `frontend/app/(app)/settings/page.tsx` | 占位：当前用户信息/退出登录 |
| `frontend/components/layout/Sidebar.tsx` | 左侧竖向导航（图标+文字，active 高亮）|
| `frontend/components/layout/Header.tsx` | 顶部栏：标题、用户头像菜单、退出 |
| `frontend/components/kanban/KanbanBoard.tsx` | @dnd-kit 容器，列布局，拖拽落列回调 |
| `frontend/components/kanban/KanbanColumn.tsx` | 单列（droppable）+ 列头计数 |
| `frontend/components/kanban/KanbanCard.tsx` | 卡片（draggable）：标题/负责人/优先级徽章 |
| `frontend/components/ui/Button.tsx` | 按钮（primary/ghost/danger）|
| `frontend/components/ui/Badge.tsx` | 状态/优先级徽章（读 constants 配色）|
| `frontend/components/ui/Avatar.tsx` | 头像（人=首字母彩底，Agent=机器人图标）|
| `frontend/components/ui/Modal.tsx` | 通用弹窗 |
| `frontend/components/ui/Select.tsx` `Input.tsx` `Textarea.tsx` | 表单控件 |
| `frontend/components/requirements/RequirementForm.tsx` | 新建/编辑需求表单（含指派人/Agent 选择）|
| `frontend/components/bugs/BugForm.tsx` | 新建/编辑 BUG 表单 |
| `frontend/components/AssigneePicker.tsx` | 统一「指派给 人 or Agent」选择器 |
| `frontend/lib/types.ts` | 全量 TS 类型（User/Agent/Requirement/Bug/...）|
| `frontend/lib/constants.ts` | status/priority/severity 的 key→中文名→配色映射 |
| `frontend/lib/api.ts` | fetch 封装（自动带 token、统一错误、`ApiError`）|
| `frontend/lib/auth.tsx` | `AuthProvider` + `useAuth`（登录态、token 存取）|
| `frontend/hooks/useBoard.ts` | 看板数据拉取 + 乐观移动 + 回滚 |

---

## 4. Interface Design（接口设计，REST）

统一约定：JSON in/out；成功 `2xx`；错误体**恒为** `{ "error": string, "detail"?: any }`（含 404/422/500 等框架级错误，由 §2.6 全局处理器保证，前端可无条件 `res.json()`）；写接口需 `Authorization: Bearer <JWT>`。Base path：`/api`。角色守卫级别见 §2.4（R-08）。

### 4.1 Auth
```
POST /api/auth/login       body {username, password}      → 200 {token, user}
GET  /api/auth/me          (JWT)                           → 200 {user}
POST /api/auth/register    (admin) {username,password,role,display_name,email?} → 201 {user}
```

### 4.2 Users / Agents / Projects
```
GET   /api/users                                → 200 [User]
POST  /api/users        (admin) {…}             → 201 User
PATCH /api/users/:id    (admin) {role?,display_name?} → 200 User

GET   /api/agents                               → 200 [Agent]
POST  /api/agents       (admin|pm) {name,kind,description?} → 201 Agent
PATCH /api/agents/:id    {status?,description?} → 200 Agent

GET   /api/projects                             → 200 [Project]
POST  /api/projects     (admin|pm) {name,key,description?} → 201 Project
GET   /api/projects/:id                         → 200 Project
```

### 4.3 Requirements
```
GET   /api/requirements?project_id=&status=&assignee_type=&assignee_id=  → 200 [Requirement]
POST  /api/requirements   {title,description?,priority?,project_id?}       → 201 Requirement (status=new)
GET   /api/requirements/:id                                                → 200 Requirement
PATCH /api/requirements/:id  {title?,description?,priority?}               → 200 Requirement
DELETE/api/requirements/:id  (admin|pm)                                    → 204
PATCH /api/requirements/:id/assign  {assignee_type:'user'|'agent', assignee_id} → 200 Requirement (若为 new→assigned；仅 @jwt_required)
PATCH /api/requirements/:id/move    {status, position?}                    → 200 Requirement | 409 {error,detail,allowed}  (position 可省略，缺省追加列尾；仅 @jwt_required)
POST  /api/requirements/:id/convert-to-bug {title?,severity?}              → 201 Bug | 409 (源需求须∈{testing,reviewing}；仅 @jwt_required)
GET   /api/requirements/:id/activities                                     → 200 [Activity]
```

### 4.4 Bugs
```
GET   /api/bugs?project_id=&status=&assignee_id=      → 200 [Bug]
POST  /api/bugs   {title,description?,severity?,project_id?,related_requirement_id?} → 201 Bug (status=open)
GET   /api/bugs/:id                                   → 200 Bug
PATCH /api/bugs/:id  {title?,description?,severity?}   → 200 Bug
PATCH /api/bugs/:id/assign {assignee_type,assignee_id}→ 200 Bug (仅 @jwt_required)
PATCH /api/bugs/:id/move   {status, position?}        → 200 Bug | 409 {error,detail,allowed} (position 可省略，缺省追加列尾；仅 @jwt_required)
DELETE/api/bugs/:id  (admin|pm)                        → 204
```

### 4.5 Board / Stats
```
GET /api/board/requirements?project_id=  → 200 {columns:[{key,title,items:[Requirement]}]}
GET /api/board/bugs?project_id=          → 200 {columns:[{key,title,items:[Bug]}]}
GET /api/stats                           → 200 {requirements:{by_status}, bugs:{by_status}, agents:{idle,busy}, members}
```

---

## 5. Data Model（数据模型，SQLite via SQLAlchemy）

所有表含 `id INTEGER PK AUTOINCREMENT`，时间戳 `created_at`/`updated_at`（UTC，`server_default`/`onupdate`）。

**users**：`username`(unique, not null)、`email`(nullable)、`password_hash`、`role`(enum `admin|pm|member`)、`display_name`、`avatar_color`(hex, seed 时分配)。

**agents**：`name`(unique)、`kind`(enum `dev|qa|generic`)、`status`(enum `idle|busy|offline`, default `idle`)、`description`。表示可被指派工作的 AI 执行者。

**projects**：`name`、`key`(short unique, 如 `ARA`)、`description`、`owner_id`→users.id。

**requirements**：
`project_id`→projects.id(nullable)、`title`(not null)、`description`(text)、`priority`(enum `low|medium|high|urgent`, default `medium`)、`status`(enum RequirementStatus, default `new`)、`assignee_type`(**nullable**，枚举取值集合 `{user, agent}`；未指派时为 SQL `NULL`)、`assignee_id`(int, nullable, 语义随 `assignee_type`)、`reporter_id`→users.id、`position`(int, 列内排序，default 0)。
> **【R-07 修复】** v1 的 `related_bug_id` 单值列已删除：一个需求可转出多个 BUG（一对多），单列会语义含糊。需求→其转出 BUG 的关系**统一由 `bugs.related_requirement_id` 反查**（该列建索引）。
> **【R-10 修复】** assignee 采用**多态外键**（`assignee_type` + `assignee_id`），避免为「人/Agent」建两列；`assignee_type` 是**可空列**而非把 `null` 当枚举字面量，取值只有 `user` / `agent`。`to_dict` 时后端按 `assignee_type` join 出 `assignee` 概要对象（`{type,id,name,avatar_color/kind}`）返给前端渲染；未指派时返回 `assignee: null`。

**bugs**：字段同需求，差异：`severity`(enum `trivial|minor|major|critical`, default `major`)、`status`(enum BugStatus, default `open`)、`related_requirement_id`→requirements.id(nullable, 由「转 BUG」写入)。

**activities**（审计/时间线）：`entity_type`(enum `requirement|bug`)、`entity_id`、`action`(如 `created|assigned|moved|converted`)、`from_status`、`to_status`、`actor_type`(user|agent|system)、`actor_id`、`created_at`。看板/详情页时间线读此表。

关系与索引：`requirements(status)`、`bugs(status)`、`bugs(related_requirement_id)`、`activities(entity_type,entity_id)` 建索引以支撑看板分组、需求→BUG 反查与时间线查询。删除策略：MVP 采用硬删除；删除需求前先把其转出 BUG 的 `related_requirement_id` 置空（`NULL`），避免悬挂外键与级联误删。`position` 语义见 §2.2 B（R-09）。

---

## 6. Testing & Acceptance Criteria（测试与验收标准）

### 6.1 后端（`backend/tests/` 或手动 curl 脚本）
- **T1 建表 & seed**：全新运行后 `aragon.db` 生成，`users` ≥ 4、`agents` = 2、`requirements`/`bugs` 覆盖各状态列。
- **T2 登录**：默认 `admin/admin123` 登录返回 `token`+`user`；错误密码返回 401。
- **T3 需求 CRUD**：创建返回 `status=new`；`GET` 列表含新单。
- **T4 指派**：`assign` 到某 Agent 后 `assignee_type=agent`，且 `new→assigned` 自动迁移。
- **T5 合法迁移**：`in_development→testing` 返回 200 并写 Activity。
- **T6 非法迁移**：`new→done` 返回 409 且含 `allowed` 列表。
- **T7 转 BUG**：`convert-to-bug` 后新 Bug 的 `related_requirement_id` 指向源需求。
- **T8 权限**：`member` 调 `POST /api/users` 返回 403。

### 6.2 前端（手动验收 / 可选 Playwright 冒烟）
- **U1 布局**：左侧竖向导航 + 顶部 Header + 右侧内容三段式；仅浅色、暖色 Anthropic 风格；导航 active 高亮。
- **U2 登录守卫**：未登录访问 `/dashboard` 重定向 `/login`；登录后可进入。
- **U3 看板拖拽**：把需求卡从「开发中」拖到「测试中」，卡片停留新列，刷新后仍在新列（持久化生效）。
- **U4 非法拖拽回滚**：跨多列非法拖拽后卡片弹回原列并出现错误提示。
- **U5 指派 Agent**：新建需求并指派给 `dev-agent`，卡片显示机器人头像与 Agent 名。
- **U6 转 BUG**：审批列需求点「转 BUG」后 BUG 看板出现关联 BUG。

### 6.3 Definition of Done（MVP）
前端 `npm run dev` 与后端 `python app.py` 均可启动无报错；U1–U6 全通过；数据落 SQLite 且重启不丢；`spec.md v2` 中规划文件全部就位。

---

## 7. Risks & Mitigations（风险与缓解）

| 风险 | 影响 | 缓解 |
|---|---|---|
| **CORS/端口不一致**导致前端请求被拦 | 登录即失败 | 后端 `flask-cors` 明确放行 `http://localhost:3000`；前端 `NEXT_PUBLIC_API_BASE` 可配 |
| **@dnd-kit 与 Next SSR**冲突（`window` 未定义）| 看板白屏 | 看板页 `"use client"`；DnD 组件仅客户端渲染，必要时 `dynamic(..., {ssr:false})` |
| **乐观更新与后端 409 不一致** | 卡片错位 | `useBoard` 保存 move 前快照，失败回滚 + toast |
| **多态 assignee 无法 DB 级外键约束** | 脏数据风险 | `to_dict` 时校验 join；写接口先校验 `assignee_id` 存在再落库 |
| **JWT 存 localStorage 的 XSS 面** | 安全（MVP 可接受）| MVP 记 TODO；生产改 httpOnly cookie；后端不信任 role claim，敏感操作二次查库 |
| **SQLite 并发写锁** | 高并发下 500 | MVP 单机足够；`SQLALCHEMY_ENGINE_OPTIONS` 设 `timeout`；未来迁 Postgres |
| **status key 前后端漂移** | 看板列错乱 | key 常量在 `backend/services/workflow.py` 与 `frontend/lib/constants.ts` 双写并在评审核对，作为契约 |
| **seed 非幂等重复插入** | 重复数据 | `seed_if_empty` 先判 `User.query.count()==0` 再插 |
| **Windows 命令兼容** | 启动脚本报错 | README 提供 PowerShell/cmd 双写，不用 `&&` 链式 |
| **JWT `sub` 非字符串**（R-01/P0）| 登录后全接口 422 | `identity=str(user.id)`，读取 `int(get_jwt_identity())`，统一封装于 `auth_helpers.current_user()` |
| **框架级错误返回 HTML**（R-03/P1）| 前端错误路径解析崩溃 | §2.6 全局 `errorhandler` + JWT loaders，错误体恒为 `{error,detail?}` JSON |
| **依赖未锁版本**（R-04/P1）| 拉到不兼容新版、构建不可复现 | §8.1 锁定 `requirements.txt` 全文与前端主版本 |
| **werkzeug 默认 scrypt 不可用**（R-06）| seed/建账户抛错 | 口令统一 `method="pbkdf2:sha256"` |

---

## 8. 运行与交付（供 Subtask #2 实施参考）

**后端**：
```
cd backend
python -m venv .venv
.venv\Scripts\activate            # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py                     # http://localhost:5000
```
**前端**：
```
cd frontend
npm install
copy .env.local.example .env.local
npm run dev                       # http://localhost:3000
```
**默认账号（seed）**：`admin/admin123`（admin）、`pm/pm123`（pm）、`alice/alice123`、`bob/bob123`（member）。Agent：`dev-agent`(kind=dev)、`qa-agent`(kind=qa)。

### 8.1 锁定依赖清单（R-04 新增，务必逐字采用）

未锁版本会让 `pip install` 拉取最新 flask-jwt-extended / SQLAlchemy 2.x / werkzeug 3.x，正是 R-01 与 SQLAlchemy 2.0 破坏性变更的根因。下游**必须**采用以下经过相互兼容验证的锁定版本，保证可复现、稳健：

`backend/requirements.txt`：
```
Flask==3.0.3
Flask-Cors==4.0.1
Flask-SQLAlchemy==3.1.1
Flask-JWT-Extended==4.6.0
SQLAlchemy==2.0.31
Werkzeug==3.0.3
```

`frontend/package.json`（`dependencies` 关键项锁定主版本）：
```
"next": "14.2.5", "react": "18.3.1", "react-dom": "18.3.1",
"@dnd-kit/core": "^6.1.0", "@dnd-kit/sortable": "^8.0.0", "swr": "^2.2.5"
```
`devDependencies` 关键项：`typescript ^5.5`、`tailwindcss ^3.4`、`postcss ^8.4`、`autoprefixer ^10.4`、`@types/react ^18.3`、`@types/node ^20`。

> 说明：Next.js 固定 `14.2.5`（App Router 稳定线，规避 15.x 的 async request API / React 19 迁移波动，契合「稳健、可靠」定位）；React 保持 18.3.1 与之匹配。

---

## 9. 交付清单摘要（给下游的最小实现集）

1. 后端 8 个 blueprint + 6 张表 + workflow 状态机 + seed。
2. 前端三段式外壳 + 8 个页面 + 看板(可拖拽) + 表单 + UI 基础组件 + api/auth/types/constants。
3. README + .gitignore。
4. 端到端可跑通 U1–U6、T1–T8。

> **契约铁律**：status key 集合（需求 7 态 / BUG 5 态）、优先级/严重度枚举、API 路径与返回 shape，前后端必须逐字一致，任何改动需回到本 spec 同步。

---

## 评审结论（Review Verdict｜Subtask #1）

**结论：有条件通过（Approved with Conditions）。**

方案在四个维度上整体成立：
- **可行性**：所选技术栈（Next.js App Router + Flask + SQLAlchemy 2.x + SQLite + @dnd-kit + flask-jwt-extended）能够端到端支撑全部 MVP 目标；原 v1 中唯一会「必然击穿」的可行性缺陷（JWT `sub` 类型，R-01/P0）已修复。
- **完备性**：补齐了此前缺失的**全局错误响应契约**（R-03）、**依赖版本锁定**（R-04）、**position 排序语义**（R-09）与**权限守卫边界**（R-08），错误路径、边界与可复现构建已闭合。
- **一致性**：消除了状态迁移「邻接表 vs 相邻+回退」的**双权威矛盾**（R-02），确立邻接表为唯一事实来源；转 BUG 目标态、多态 assignee、需求↔BUG 关系的语义歧义（R-05/R-07/R-10）均已统一。作为全新项目，无 `CLAUDE.md`/既有源码约束，文档现已内部自洽。
- **规模合理性**：约 60 文件的全栈骨架与 MVP「可运行骨架」定位匹配，未见过度设计；审计表 `activities` 服务于「人/Agent 混合协作轨迹」这一核心价值主张，予以保留。

**修复情况**：1 个 P0（R-01）、4 个 P1（R-02/R-03/R-04/R-05）**已全部在 v2 正文就地修复**；6 个 P2 中 R-06/R-07/R-08/R-09/R-10 亦已顺手修复，R-11 作为明确的 MVP 取舍在正文注明。**当前无遗留 P0/P1。**

**放行条件（下游 Subtask #2 实施时必须遵守，均已写入正文，此处为验收核对项）**：
1. **C-1**：JWT `identity` 必须 `str(user.id)`，读取侧 `int(get_jwt_identity())`（§2.2 A / R-01）。
2. **C-2**：迁移合法性只认 §2.3 邻接表，`move`/`convert-to-bug` 一律经 `can_transition` 裁决，不得另立启发式（R-02/R-05）。
3. **C-3**：`create_app()` 必须注册 §2.6 全局错误处理器与 JWT loaders，保证错误体恒为 `{error, detail?}` JSON（R-03）。
4. **C-4**：依赖严格采用 §8.1 锁定版本，口令统一 `pbkdf2:sha256`（R-04/R-06）。
5. **C-5**：`assign`/`move`/`convert-to-bug` 的行级权限本期不实现，须以 `# TODO(rbac-row-level)` 标注，不得声称已收敛（R-08）。

满足以上 5 项条件即视为方案落地合规。

**评审人**：Senior Reviewer, Anthropic Engineering ｜ **评审轮次**：Subtask #1（Iteration 1/3）

---

*本文档现为 **v2**：已由 Subtask #1（方案评审与修复）逐节评审，P0/P1 全部就地修复，供 Subtask #2 逐行实现。*

---

## 实施过程发现的方案缺陷（Issues Found During Implementation｜Subtask #2）

> 实施结论：v2 方案整体可逐行落地，**无架构性缺陷**，全部 T1–T8 后端验收在 Flask test client 上通过。以下为实施期发现的**次要不完备项**，均已按「不静默偏离」原则记录，并以最小改动就地补齐（新增的两个支撑文件不改变既有契约与文件语义）。

| # | 类型 | 位置 | 发现 | 处理 |
|---|---|---|---|---|
| **I-01** | 完备性（次要） | §3.3 前端文件清单 | 清单在 U4/U6 与 `hooks/useBoard.ts` 多处要求「toast 错误提示」，但**未单列 toast 原语文件**，导致无处承载全局提示。 | 新增最小实现 `frontend/lib/toast.tsx`（`ToastProvider` + `useToast`），在 `app/layout.tsx` 挂载。仅补齐既定诉求，不新增第三方依赖。 |
| **I-02** | 完备性（技术支撑） | §3.2 后端文件清单 | 清单列出 `routes/__init__.py` 但**未列 `services/__init__.py`**；虽 Python 3.3+ 命名空间包可免 `__init__.py`，为保证跨环境 `from services.x import ...` 稳定导入，显式补包标记更稳健。 | 新增空的 `backend/services/__init__.py` 包标记。不含逻辑，纯稳健性补强。 |
| **I-03** | 一致性（澄清） | §8.1 前端依赖 | 锁定清单列了 `@dnd-kit/core`、`@dnd-kit/sortable`，未列同族的 `@dnd-kit/utilities`（`core`/`sortable` 的传递依赖）。 | `package.json` 显式列出 `@dnd-kit/utilities`（同族包，随 core 自动安装），避免 phantom dependency。看板实现采用 `useDraggable`+`useDroppable`+`DragOverlay`（`@dnd-kit/core`），未强依赖 `sortable` 的整列重排（与 R-09「不整列重排」一致）。 |
| **I-04** | 澄清（非缺陷） | §2.2 C / U6 | 「转 BUG 后跳转 BUG 看板并高亮新卡片」——MVP 已实现跳转与关联展示（BUG 卡显示「源需求 #」），`?highlight=` 参数已在 URL 预留但暂未做视觉高亮动画。 | 记为已知取舍，`# TODO(board-highlight)`；不影响 U6 核心验收（BUG 看板出现关联 BUG）。 |

**说明**：以上 I-01/I-02/I-03 为「实现既定诉求所必需的最小支撑」，未扩大功能范围；I-04 为对既有取舍的透明记录。除此之外，方案的鉴权链路、状态机（邻接表 SSOT）、错误契约、多态 assignee、转 BUG、审计时间线、看板拖拽持久化均按 v2 正文逐字实现，未做任何未记录的偏离。

**实施人**：Senior Implementation Engineer, Anthropic Engineering ｜ **实施轮次**：Subtask #2（Iteration 1/3）
