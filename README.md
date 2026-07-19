# AragonTeam

**AI 时代的团队协作与研发管理平台** —— 与传统研发管理工具（Jira / 禅道）最本质的区别是：
**Agent 是一等公民的执行者**。需求单与 BUG 单不仅可以指派给人类成员，也可以指派给 AI Agent
（dev-agent / qa-agent 等）。平台记录人类与 Agent 混合协作的完整流转轨迹，为「Agent 自动认领需求、
自动开发、自动修 BUG」预留数据结构与接口位。

本仓库为 **MVP 骨架**：前后端可启动、可登录、可创建 / 指派 / 流转需求与 BUG、看板可拖拽、数据可持久化。

---

## 技术栈

- **前端**：Next.js 14（App Router）+ React 18 + TypeScript + Tailwind CSS + @dnd-kit（拖拽）+ SWR
- **后端**：Python Flask + SQLAlchemy 2 + Flask-JWT-Extended（JWT 鉴权）+ Flask-CORS
- **持久化**：SQLite（`backend/aragon.db`，首次启动自动建表并 seed mock 数据）
- **设计**：Anthropic 暖色浅色风（ivory 背景 + clay/coral 强调 + 衬线标题），仅浅色模式

三段式布局：**左侧竖向功能导航 + 顶部 Header + 右侧主内容区**。

---

## 目录结构

```
AragonTeam/
├─ backend/            Flask REST 后端
│  ├─ app.py           create_app 工厂 + 启动入口（:5000）
│  ├─ config.py        配置（密钥 / SQLite / CORS）
│  ├─ extensions.py    db / jwt 实例
│  ├─ errors.py        全局 JSON 错误契约 + JWT loaders
│  ├─ seed.py          幂等 mock 数据
│  ├─ models/          User / Agent / Project / Requirement / Bug / Activity
│  ├─ services/        workflow（状态机）/ auth_helpers（鉴权）
│  └─ routes/          auth / users / agents / projects / requirements / bugs / board / stats
└─ frontend/           Next.js 前端
   ├─ app/             login / (app){dashboard,requirements(+board),bugs(+board),agents,team,settings}
   ├─ components/      layout / kanban / ui / requirements / bugs / AssigneePicker
   ├─ lib/             types / constants / api / auth / toast
   └─ hooks/           useBoard（看板拉取 + 乐观移动 + 回滚）
```

---

## 启动步骤

> Windows 下命令分开执行，**不要**用 `&&` 链式（PowerShell 5.1 不支持）。

### 1. 后端（端口 5000）

PowerShell：
```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

cmd：
```bat
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

首次启动会自动创建 `aragon.db` 并写入 mock 数据。后端地址：`http://localhost:5000`
（健康检查：`GET /api/health`）。

### 2. 前端（端口 3000）

PowerShell / cmd：
```
cd frontend
npm install
copy .env.local.example .env.local
npm run dev
```

打开 `http://localhost:3000`。前端通过 `NEXT_PUBLIC_API_BASE`（默认 `http://localhost:5000/api`）
访问后端。

---

## 默认账号（seed）

| 用户名 | 密码 | 角色 |
|---|---|---|
| `admin` | `admin123` | 管理员 |
| `pm` | `pm123` | 项目经理 |
| `alice` | `alice123` | 成员 |
| `bob` | `bob123` | 成员 |

内置 Agent：`dev-agent`（开发）、`qa-agent`（测试）。

---

## 核心业务闭环

- **需求生命周期**：新建 → 指派（人 / Agent）→ 开发中 → 测试中 → 审批中 → 完成；
  审批不通过或发现缺陷可**一键转 BUG**（源需求转入「修复中」）。
- **BUG 生命周期**：新建 → 指派 → 修复中 → 验证中 → 关闭。
- **看板拖拽**：拖动卡片触发状态迁移，合法性由后端状态机（邻接表）裁决；
  非法迁移返回 409，前端乐观更新回滚并提示。
- **审计时间线**：每次创建 / 指派 / 流转 / 转 BUG 都写入 `activities`，记录人 / Agent 混合协作轨迹。

设计与验收细节见 [`docs/plans/aragonteam-mvp/spec.md`](docs/plans/aragonteam-mvp/spec.md)。

---

## Phase-2 能力（从「可运行骨架」到「可信的 Agent 协作平台」）

在 Phase-1 MVP 之上做**向后兼容的增量演进与加固**（不改任何既有对外契约）：

- **Agent 协作运行时**：`POST /api/{requirements|bugs}/:id/agent-advance` 让指派给 Agent 的工单
  真正**推进一步**——按状态机（邻接表，绝不绕过）流转 + 以 Agent 身份留一条工作说明评论 +
  写 `actor_type=agent` 的审计。确定性离线模拟，未来替换 `agent_runner._perform` 即可接真实 Agent。
  另有 `?run=all` 连续推进至无动作 / 终态 / 6 步上限。
- **讨论与工单详情**：新增 `comments` 表 + 评论/合并 `feed` 接口；前端 **TicketDrawer** 右侧抽屉
  （点击任意看板卡片或列表行打开），内含详情编辑、指派、转 BUG、**人/Agent/系统混合时间流**、
  评论输入框与「让 Agent 处理下一步」。
- **可靠性加固**：结构化日志 + 请求 ID（`X-Request-Id`）、列表分页（`?limit/offset` + `X-Total-Count`，
  非破坏）、登录限流（滑动窗口，MVP 单机版）、全局 500 事务回滚、SQLite 外键约束（限方言）、
  健康检查加 DB 探活（`GET /api/health` → `{db:"ok"|"error"}`）。
- **顶级打磨**：骨架屏 / 空状态 / 错误边界（段级 + 根级 + 404）、看板同列拖拽精确重排、
  仪表盘分布可视化（纯 CSS 占比条）+ Agent 利用率 + 本周活动、Agents 页工单负载与最近活动、
  Modal/Toast/抽屉可访问性补强。

### 后端测试（Phase-2 可靠性硬指标）

```powershell
cd backend
pip install -r requirements.txt -r requirements-dev.txt
pytest -q
```

内存 SQLite + 独立 `TestConfig`（`StaticPool` 固定连接、关闭启动 seed、限流阈调小），
覆盖鉴权 / CRUD / 状态机 / Agent 运行时 / 评论合并流 / RBAC / 健康检查（P-T1…P-T8）。

### 前端质量门禁

```
cd frontend
npm run typecheck   # tsc --noEmit
npm run build       # next build
```

### 环境变量

后端全部配置项可用环境变量覆盖（均有开发默认值，开箱即用）：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SECRET_KEY` | `aragon-dev-secret-change-me` | Flask 密钥（生产务必覆盖）|
| `JWT_SECRET_KEY` | `aragon-dev-jwt-secret-change-me` | JWT 签名密钥（生产务必覆盖）|
| `JWT_ACCESS_TOKEN_EXPIRES` | `86400`（秒）| 访问令牌有效期 |
| `DATABASE_URL` | `sqlite:///backend/aragon.db` | 数据库 URI（沿用既有名）|
| `CORS_ORIGINS` | `http://localhost:3000` | 允许的前端 origin（逗号分隔）|
| `LOGIN_MAX_ATTEMPTS` | `10` | 登录限流阈值（5 分钟窗口内失败上限）|
| `SEED_ON_STARTUP` | `true` | 启动时是否幂等 seed（测试关闭）|

前端：`NEXT_PUBLIC_API_BASE`（默认 `http://localhost:5000/api`）。

Phase-2 设计与验收细节见 [`docs/plans/aragonteam-phase2/spec.md`](docs/plans/aragonteam-phase2/spec.md)。

---

## Phase-3 能力（从「可信的 Agent 协作平台」到「自主协作的研发中枢」）

在 Phase-2 之上继续做**向后兼容的增量演进与收官**（唯一 schema 变更是新增 `notifications` 表，
`create_all` 自动建；不改任何既有对外契约）。三根支柱：

- **支柱 A — Agent 自主协作闭环**：`services/agent_autopilot.py` + 一组编排接口，让 Agent
  **自己认领并推进**一批工作（全程仍走状态机 `can_transition`，复用 Phase-2 `agent_runner`）：
  - `POST /api/agents/:id/claim-next`——Agent 自动认领其泳道内最久未指派的工单；
  - `POST /api/agents/:id/autorun[?run=all]`——扫描并连续推进该 Agent 名下所有可推进工单；
  - `POST /api/agents/:id/tick`——「认领 + 推进」一次自主循环（**旗舰演示**）；
  - `POST /api/agents/autorun-all`——一键运行整支 AI 团队一轮。
  运行期间 `agent.status=busy` 作为**软锁**（并发触发 → 409），`finally` 必归 `idle`。
  前端 Agents 页每张卡新增「自动一轮 / 认领下一个 / 运行队列」，pm/admin 顶部「▶ 运行 AI 团队一轮」。
- **支柱 B — 通知中心与协作感知**：新增 `notifications` 表 + 通知接口
  （`GET /api/notifications`、`/unread-count`、`POST /:id/read`、`/read-all`），在
  **指派 / 评论 / @提及 / 状态推进（含 Agent 自主推进）/ 转 BUG** 等事件上向相关人类用户扇出通知
  （不给自己 / Agent 发、去重）。前端 Header 新增**通知铃铛**（未读红点 + 下拉 + 点击直达工单 + 一键已读），
  实时性用 **SWR 轮询**（默认 20s）达成，**零新依赖**（WebSocket/SSE 延期）。
- **支柱 C — 权限 / 并发 / 检索收官**：
  - **行级 RBAC**（收口 `# TODO(rbac-row-level)`）：patch/move 需 `can_manage_ticket`（reporter /
    人类 assignee / pm / admin）；assign / 转 BUG / 删除 / autopilot 需 pm/admin；
    `agent-advance` 需 pm/admin 或 `can_manage_ticket`（**有意收紧**，防旁路 move/patch 门禁）。
  - **乐观并发守卫**：`PATCH /:id` 与 `/:id/move` 接受可选 `expected_updated_at`，冲突返回 409
    （体含 `detail.current_updated_at`、**无** `allowed`，与状态机 409 区分），前端提示刷新，杜绝拖拽丢更新。
  - **过滤 / 检索**：列表接口加 `q/status/priority/severity/assignee_*/reporter_id`（全部可选、向后兼容）；
    新增 **`GET /api/me/work`「我的工作」聚合**（指派给我 / 我提交的）与 **Header 全局搜索**、
    列表页过滤条、侧边栏「我的工作」入口、通知点击 `?ticket=<id>` 直达工单抽屉。

Phase-3 后端 pytest 在 Phase-2 基础上扩充至 **93 用例全绿**（新增 agent_autopilot / notifications /
concurrency / search，并扩充 rbac）。前端 `tsc --noEmit` 0 error、`next build` 通过。

> **契约变更提示（诚实标注）**：`agent-advance` 在 Phase-2 为「仅需登录即可推进任意工单」，Phase-3
> **有意收紧**为「pm/admin 或 `can_manage_ticket`」以防 RBAC 旁路——Phase-2 的
> `test_member_can_comment_and_advance` 已按新契约改写（member 评论仍 201；member 对非归属单
> `agent-advance` 现为 403）。这是**明示的契约变更**，非「零变更」。

Phase-3 设计与验收细节见 [`docs/plans/aragonteam-phase3/spec.md`](docs/plans/aragonteam-phase3/spec.md)。

---

## 真实 Agent 执行引擎（Real Agent Execution）—— 去 Mock

在 Phase-3 之上把平台**唯一**的业务 Mock（Agent 执行引擎）真实化：此前指派给 Agent 的工单
被推进时只写一句**固定罐头文案**，Agent 并未真正「读需求、想实现、写测试」。本迭代在
`agent_runner.advance_one` 这一**唯一接缝**处接入**真实 LLM 执行层**——dev-agent / qa-agent
推进每一步时会真正调用大模型，读取工单标题 / 描述 / 最近讨论，产出**该步骤的真实工作产物**
（需求拆解与实现要点、测试计划与用例、缺陷根因与修复摘要等），写入协作时间线。

- **状态机仍是圣域**：迁移目标**完全**由 `AGENT_FORWARD` + `workflow.can_transition` 裁决，
  LLM 只产「内容」、绝不决定「流转到哪」。
- **有凭据则真、无凭据则稳（双模）**：未配置凭据 / 测试环境 / 调用失败 / 返回空 / 响应异形——
  **任一情况都优雅降级**回既有确定性模板，工单照常推进、流程绝不中断、**绝不冒泡成 5xx**。
  默认（不设任何 `AGENT_LLM_*`）即今日行为，**开箱即用、升级无感**。
- **零新依赖、零 schema 变更**：LLM 调用仅用标准库 `urllib`；产物写入既有 `Comment.body`，
  溯源信息（provider / model / latency / 降级因）进结构化日志，不落库。
- **可观测**：`GET /api/health` 新增只读 `llm` 块（`{enabled, provider, model}`，**从不回传密钥**）。

### 环境变量（`AGENT_LLM_*`，全部有默认值 → 未设即离线模式）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `AGENT_LLM_PROVIDER` | `none` | `anthropic` / `openai` / `none`；`none` = 离线（用确定性文案）|
| `AGENT_LLM_API_KEY` | 空（回落 `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`）| 模型凭据；为空即离线 |
| `AGENT_LLM_MODEL` | `claude-opus-4-8`（anthropic）/ `gpt-4o-mini`（openai）| 模型 ID |
| `AGENT_LLM_BASE_URL` | 各 provider 官方端点 | 自建 / 兼容网关覆盖点（openai 须含 `/v1`）|
| `AGENT_LLM_MAX_TOKENS` | `700` | 单步产物上限（控延迟 / 成本）|
| `AGENT_LLM_TEMPERATURE` | `0.4` | 采样温度 |
| `AGENT_LLM_TIMEOUT` | `30` | 单次调用超时（秒）|
| `AGENT_LLM_MAX_RETRIES` | `2` | 超时 / 5xx / 网络错误的重试次数 |
| `AGENT_LLM_WALL_BUDGET` | `120` | 单次 autopilot 调用的 LLM 墙钟预算（秒）；超则其余单 `skipped(reason="budget")`；`0` = 不限 |

> **提示**：`AGENT_LLM_MODEL` 默认 `claude-opus-4-8` 追求质量；**autopilot 密集 / 整队场景**
> 建议改用更快更省的模型（如 Haiku 级）以压低串行时延与成本。**一键回滚**：置
> `AGENT_LLM_PROVIDER=none`（或清空 `AGENT_LLM_API_KEY`）即回退确定性文案，无需改码。

启用示例（PowerShell，仅当前会话有效；不设即离线）：

```powershell
$env:AGENT_LLM_PROVIDER = 'anthropic'
$env:AGENT_LLM_API_KEY  = '<your-key>'
python app.py
```

设计与验收细节见 [`docs/plans/real-agent-execution/spec.md`](docs/plans/real-agent-execution/spec.md)。

---

## 稳健化收官（Reliability Hardening）—— 每个功能都不报错、每个页面都能正确使用

在既有 8 个里程碑之上做一次**面向缺陷的收敛式加固**：不新增任何业务功能、不新增数据库表、
不新增前后端运行时依赖，只把「点了会 500 / 换页会崩 / 后端抖动就卡骨架 / 无权却给按钮」这些
真实缺口逐一堵住。

- **后端输入边界校验（坏输入 400 不 500）**：新增 `services/validation.py`
  （`json_body()` + `want_str/want_int/want_bool` + `ValidationError`），把 12 个写路由里
  重复且脆弱的 `request.get_json(silent=True) or {}` + `(x or "").strip()` 收敛为一处可复用、
  可单测的边界模块。非对象 JSON 体（`5`/`[1]`/`"x"`）、非字符串字段（`username=123`）、
  非法主键（`project_id=[1]`）等**坏输入统一走 400 JSON 契约** `{error, detail:{field,expected}}`，
  **绝不冒泡成 5xx**（含公开 `POST /api/auth/login`）。看板 `move` 的 `status` 也先归一为字符串，
  杜绝 `["assigned"]` 触发的 `unhashable` 500。
- **SWR key/fetcher 形状一致性（消灭崩溃与卡死）**：确立不变量——**一个 SWR key 在全应用只对应
  一种 fetcher 返回形状**；据此拆开 Agents 页与列表页对 `/requirements`、`/bugs` 的 key 冲突
  （裸数组 vs `{items,total}`），根治「先开列表再开 Agents 页整页崩」「反向导航显示共 undefined 条」。
  新增 `components/ui/ErrorState.tsx`（内联错误 + 重试），列表/详情/仪表盘/我的工作/通知等页面
  读 `error` 渲染错误态，后端抖动不再永久卡骨架。
- **权限门禁与交互正确性**：TicketDrawer 的「保存详情 / 改派 / 让 Agent 处理」按 `can_manage`/`pm-admin`
  门禁隐藏（后端仍是权威，前端只收敛「可见即可用」）；转 BUG 后用 `?ticket=` 直达新卡；
  Agent 禁止被手动置 `busy`（防 autopilot 软锁死锁）；徽章枚举越界中性兜底；通知偏好切换失败提示。
- **错误码修正（更对，不破坏任何正常用法）**：坏输入 **500→400**；无效/伪造 JWT **422→401**
  （前端据 401 自动登出重定向，杜绝会话卡死）。**成功路径契约零变更**。

### 质量门禁

```powershell
cd backend
pytest -q            # 222 用例全绿（含新增 test_validation.py 等）
```
```
cd frontend
npm run typecheck    # tsc --noEmit → 0 error
npm run build        # next build → 成功
```

设计与验收细节见 [`docs/plans/reliability-hardening/spec.md`](docs/plans/reliability-hardening/spec.md)。
