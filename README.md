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

内置 Agent：`dev-agent`（开发）。

首启的示例数据**每类只有一条**（1 账号 / 1 Agent / 1 项目 / 1 需求 / 1 BUG /
1 评论 / 1 审计 / 1 通知，共 8 行）。其余成员请登录后在「团队」页创建；需要演示
dev→qa 交接时，在「Agents」页一键新建一个 `qa` Agent 即可。示例工单一律是
未指派的初始状态（`new` / `open`），不会一启动就卡在中间列。

详见下文「示例数据与清理」。

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
| `DATABASE_URL` | `sqlite:///<repo>/backend/aragon.db` | 数据库 URI（沿用既有名）。默认值由 `backend/config.py` **所在目录**解析为绝对路径，从任何工作目录启动都命中同一个文件；若自行覆盖，**请也写绝对路径**，相对路径会随工作目录漂移出第二个库，表现就是「数据莫名消失了」|
| `CORS_ORIGINS` | `http://localhost:3000` | 允许的前端 origin（逗号分隔）|
| `LOGIN_MAX_ATTEMPTS` | `10` | 登录限流阈值（5 分钟窗口内失败上限）|
| `SEED_ON_STARTUP` | `true` | 启动时是否幂等 seed（测试关闭）|
| `RELEASE_STALE_LOCKS_ON_STARTUP` | `true` | 启动时解开崩溃残留的 Agent `busy` 软锁；多 worker 部署必须置 `false` |
| `SQLITE_SYNCHRONOUS` | `NORMAL` | SQLite 落盘同步级别（`OFF`/`NORMAL`/`FULL`/`EXTRA`）；对掉电零容忍时设 `FULL` |

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

---

## 主流程完备化与页面可用性收官（Feature Completeness）—— 每个主要功能都能端到端跑通、每个页面在异常与权限下都能正确使用

在「稳健化收官」之后，本轮做一次**收敛式功能完备化 + 页面可用性收口**：让每一个已存在的主要功能都能端到端跑通并给出正确数据，让每一个客户端页面在后端异常、会话过期、权限不足三类边界下都优雅可用。零新表、零新依赖、不破坏成功路径契约。

- **自主 AI 团队闭环真正闭合（dev→qa 交接）**：在自主编排层（`agent_autopilot.autorun`）为 dev→qa 增加一处**确定性交接**——把被推进到 qa 泳道状态（需求 `testing` / BUG `verifying`）的单重指派给一个可用 qa-agent（**只改多态 assignee，绝不碰状态机**）。于是 `/autorun`、`/tick`、`/autorun-all` 都能把需求带到 `reviewing`（待人工审批）、把 BUG 带到 `closed`；存量已停在测试/验证却指派给非-qa 的单（含 seed 演示单）经 `except NoAgentAction` 分支同一交接被解救，不再永久卡死。至此「一键运行整支 AI 团队一轮」终于能产出端到端完成的单。
- **默认列表视图给对顺序**：需求 / BUG 扁平列表默认按「最近更新」（`updated_at desc, id desc`）全局排序，与「我的工作」一致；`position` 仅继续服务看板列内排序（此前用列内序号排跨状态的扁平列表会交错各列、顺序无意义）。看板接口不受影响。
- **残余坏输入 500→400 收口**：`claim_count`（`want_int`）、`email`（`want_str`）、`description`（`want_str(strip=False)`）三处仍会 500 的字段全部收敛为 400；`want_str` 枚举字段空串回退 `default`（不再落库非法 `""`）。
- **Agent offline 语义收口**：自主编排（`/autorun`、`/tick`、`/autorun-all`）与 `agent-advance?run=all` 尊重 `offline`（拒 409 / 计入 `skipped`），软锁 `finally` 恢复原状态（不再把 offline 清成 idle）。
- **页面错误态完备化**：补齐上一轮漏掉的**看板页、工单抽屉、团队页**的 `error`/加载分支——后端出错不再永久卡骨架，深链 / 过期通知点开已删工单时抽屉显示可关闭的错误态，团队页失败不再误读为「无成员」。
- **会话过期全局自动登出**：`api.ts` 在 401（非 `/auth/` 路径）时清 token 并广播 `aragon:unauthorized`，`AuthProvider` 订阅后清态 → 外壳自动跳登录，不再全站「重试也失败」。
- **列表 / 看板写按钮按角色门禁**：列表页内联「指派」与需求看板「转 BUG」仅对 pm/admin 可见（与后端权威一致），无权成员不再看到点了必 403 的按钮。
- **一批交互正确性加固**：铃铛角标读后即时同步、指派弹窗防重复提交、建单带指派部分失败精确反馈（仍刷新、不留孤单）、抽屉连改级别不再触发假并发冲突、仪表盘「本周活动数」去死链。

### 质量门禁

```powershell
cd backend
pytest -q            # ≥222 用例全绿（新增自主闭环 / offline / 残余坏输入 / 枚举回退用例）
```
```
cd frontend
npm run typecheck    # tsc --noEmit → 0 error
npm run build        # next build → 成功
```

更多设计细节见 [`docs/plans/feature-completeness/spec.md`](docs/plans/feature-completeness/spec.md)。

---

## 规模化可用与项目维度贯通（Scale & Project Scope）—— 数据一多翻得到、项目建了用得上、工单页也推得动 Agent

第 3 轮做四件事：让列表在**数据变多**时仍然可达，让**项目**这一维度从数据库一路贯通到每一个页面，让**工单页**和 Agents 页拥有同样完整的 Agent 闭环，让剩下的每一个 500 与每一处「静默说谎」的 UI 归零。零新表、零新运行时依赖、成功路径响应 shape 全部不变。

- **工单级 Agent 闭环补完 + 交接泛化**：`agent_autopilot.maybe_handoff` 从「dev→qa 单向硬编码」升级为**由 `agent_runner.AGENT_FORWARD` 键集派生**的「按状态找对口 kind」（单一真相、零漂移；多解状态不交接），并接进工单级 `POST /:entity/:id/agent-advance` 与 `?run=all`。抽屉里连点「▶ 让 … 处理下一步」不再在 `testing` 永久 409，而是自动交接给 qa 并推到 `reviewing`；存量卡死单（generic 泊在 `in_development`、seed 的 qa-agent 持 `fixing`）一次点击即复活。**交接绝不从人类手里抢单，也绝不交给 offline Agent。**
- **generic Agent 定位收窄**：`generic` 不再参与自主认领（它在 `AGENT_FORWARD` 里只有 `assigned` 一条边，认领后必然泊死）；仍可被 pm **显式指派**、推进一步，随后由泛化交接转给对口 kind。`claim-next` 对 generic 恒返回 `{"claimed": null}` + 200（契约不变），并补上 busy/offline 门禁（此前离线 Agent「吞了单又拒绝干活」）。
- **列表分页可用**：需求 / BUG / 通知三页接上受控分页条（`?limit/offset` + `X-Total-Count`，`keepPreviousData` 消除翻页闪烁）。此前标题写着「共 137 条」表格却只有 50 行且没有任何翻页控件，第 51 条起在列表视图**永远不可达**。数据量 ≤ 一页时分页条不渲染，小库观感零变化。
- **项目维度端到端贯通**：Header 新增**全局项目切换器**（`localStorage` 持久化 + 失效自愈），贯通需求 / BUG 列表与看板、仪表盘、建单表单（默认继承当前作用域）、工单抽屉（显示所属项目）、项目页（行可点击 → 切作用域并跳转）。后端新增共享 `services/scope.py` 统一 `?project_id=` 语义：**缺省 = 不过滤、整数 = 该项目、字面量 `none` = 未归属（`IS NULL`）**，`/api/stats` 亦支持之（`_by_status` 改 SQL `GROUP BY`）。**不受作用域约束的视图（通知、全局搜索、我的工作、Agent 负载、最近活动）一律带可见标注**，绝不让 UI 在用户不知情时说与事实不符的话。
- **看板 `position` 的项目隔离**：`_next_position` / `_reindex_column`（含 `agent_runner` 的内联副本）改为**按「同项目同状态」编号**，`project_id` 为无默认值的必填参数（漏传即 `TypeError`，不容许静默错数据）。此前在项目 B 的看板里拖卡会把索引套在含项目 A 卡片的全列上——拖了、成功了、什么都没变。
- **剩余的真 500 清零（三点式收口）**：超界整型有三条互相独立的路径，各自收口——**URL 路径**经 `app.py::BoundedIntConverter` → **404**；**请求体**经 `want_int` 的无条件 64 位硬界 → **400**；**查询串**（`?limit/offset/assignee_id/reporter_id/project_id`）经 `services/scope.py::want_query_int` + `errors.py` 的 `QueryParamError` 全局处理器 → **400**。另补四处未校验的 `description`、`key`/`name`/`username`/`email` 的 `max_len` 与邮箱格式，并给 `/users`、`/agents`、`/projects` 三个列表补上分页与 `X-Total-Count`（响应体仍是裸数组，契约不变）。
- **删单不再串档**：删除工单时**一并删除其审计行**。SQLite 复用主键，残留审计会被下一张同 id 的单继承——既是错数据，也是已删单标题的信息泄露。副作用：`/stats.activities_this_week` 相应下降（更正确的语义）。
- **消灭「静默说谎」的 UI**：看板拖拽按后端同判据（新增 `lib/permissions.ts::canManageTicket`）逐卡门禁，403 文案中文化；铃铛与通知页**双向**同步已读；铃铛下拉与通知偏好卡补错误态（此前分别是「永久转圈」与「六个开关全画成开并锁死」）；看板「写成功但重取失败」不再谎报「已回滚」；触屏误触不可逆的「转 BUG」由 `pointer-events` 真正屏蔽。

### 接口语义变更一览（成功路径 shape 全部不变）

| 端点 | 变更 |
|---|---|
| `GET /api/requirements`、`/api/bugs`、`/api/board/*` | `?project_id=` 新增 `none` = 仅未归属；整数与缺省行为不变 |
| `GET /api/stats` | 新增可选 `?project_id=`；`agents.*` / `members` / `activities_this_week` / `recent_activities` **有意保持全局** |
| 全部 `<int:id>` 路由 | 超界 id 由 `500` 改为 **404** |
| 全部列表端点的查询串整型参数 | 超界由 `500` 改为 **400**；`offset` 为负由静默归零改为 **400**；`limit` 的钳制语义（`[1,200]`）不变 |
| `POST /api/projects`、`POST/PATCH /api/agents`、`convert-to-bug` | 非串 `description` 由 `500` 改为 **400**；超长 `key`/`name`/`username`/`email` 由 `201` 改为 **400** |
| `POST /api/agents/:id/claim-next` | busy / offline Agent 由 `200` 改为 **409** |
| `GET /api/users`、`/api/agents`、`/api/projects` | 新增 `X-Total-Count` + `limit`/`offset`（响应体仍是裸数组） |
| `GET /api/bugs/:id/activities` | **新增**（与需求侧对称） |
| `DELETE /api/requirements/:id`、`/api/bugs/:id` | 级联新增删除审计行；仍返 204 |

### 质量门禁

```powershell
cd backend
pytest -q            # ≥275 用例全绿（新增项目作用域 / 统计契约 / 三点式 500 清零 / 交接泛化用例）
```
```
cd frontend
npm run typecheck    # tsc --noEmit → 0 error
npm run build        # next build → 16/16 页成功
```

更多设计细节见 [`docs/plans/scale-and-project-scope/spec.md`](docs/plans/scale-and-project-scope/spec.md)。


## 生命周期闭环与治理安全（Lifecycle & Governance）—— 改得动、撤得回、删得掉、停得住

第 4 轮换一个观察角度：前三轮闭合的是「点了会报错」，本轮闭合的是**「做错了没有回头路」**与
**「后端有能力、客户端够不着」**。零新表、零新运行时依赖、成功路径响应 shape 只增不改，
状态机（`services/workflow.py` 的两张邻接表）一字未动——删除 / 停用 / 归档全都**不触碰 `status`**。

- **启动期 additive 加列迁移器（本轮的硬前置）**：`db.create_all()` 只建**不存在的表**，对已存在的表
  一列都不会加。项目至今没加过列，因此本轮新增 `users.is_active` / `projects.archived_at` 会让存量
  `aragon.db` 的每一次查询都 `no such column` → 500，连登录都进不去。新增
  `backend/services/schema_sync.py`：启动时对照 `inspect(engine)` 的实际列集合补齐差额，幂等、可日志、
  零新依赖。**能力边界写死在模块 docstring 里：只支持 ADD COLUMN。**
- **末任管理员不变量**：唯一的管理员此前可以把自己降级成普通成员，此后 `POST /api/users`、
  `POST /api/auth/register`、`PATCH /api/users/:id` 三个 `@require_role("admin")` 端点同时且永久地
  失去唯一的合法调用者——产品内没有任何恢复路径。现在降级 / 停用最后一位**有效**管理员一律 **409**
  （停用的 admin 不计入有效数，二者是同一个死锁的两张脸，由同一个守卫拦下）。
- **成员停用 / 启用（不做删除）**：`users.id` 被 `requirements/bugs.reporter_id` 与 `projects.owner_id`
  真外键引用且 `PRAGMA foreign_keys=ON`，硬删必 `IntegrityError`；删干净就得销毁审计轨迹，与本平台
  「人 / Agent 混合协作可追溯」的核心价值直接冲突。**停用是唯一正确的产品答案**：不能登录（403）、
  既有 token 下一次请求即失效（`jwt.token_in_blocklist_loader` → 401 → 前端自动登出）、不接收通知、
  不出现在指派选择器里；已有工单**一律不动**，只是在头像旁灰显「已停用」，由 pm 自己决定是否改派。
- **工单可撤销**：`DELETE /api/{requirements|bugs}/:id` 早就实现（含评论 / 通知 / 审计的级联清理），
  但**整个前端没有任何一处调用过 `api.del`**。现在工单抽屉底部有「危险区」删除入口（仅 pm/admin 可见，
  确认框写明将连带删除多少条评论）。同时 `PATCH /:id/assign` 支持 `assignee_type: null` **显式取消指派**
  ——此前 `AssigneePicker` 渲染的「未指派」选项是个点了必然无效的死控件。
- **项目改名 / 归档 / 删除**：新增 `PATCH /api/projects/:id`（pm/admin）与 `DELETE /api/projects/:id`（admin）。
  **归档优于删除**：`GET /api/projects` 默认只返回未归档（`?include_archived=1` 全返），归档项目不再出现在
  全局切换器与建单表单里，**它已有的工单完全不受影响**；删除则前置检查引用，仍有工单时返 **409** 并带上
  「还有 12 个需求、3 个 BUG」的可操作计数——绝不依赖外键异常兜底（那会变成一句「internal server error」）。
- **Agent 删除 + 悬挂 assignee 的诚实降级**：新增 `DELETE /api/agents/:id`，名下仍有**未终态**工单时 409
  （判据复用 `workflow.is_terminal`，不内联第二份状态清单）。删除后，指向它的工单 `assignee` 返回
  `{"name":"(已删除)","deleted":true}` 占位而非 `null`——返回 `null` 会让 UI 把一张明明还挂着
  `assignee_id` 的单显示成「未指派」。
- **看板分页**：`GET /api/board/*` 此前没有任何上限（300 张单就返 300 张卡 / 82 KB）。现在每列最多
  `?column_limit=`（默认 100，钳制 `[1,500]`）张卡，并给出该列**真实总数**；被截断时列头诚实写出
  「显示 100 / 共 342」+「查看全部」出口（跳列表页并预置 `?status=`）。未截断时不渲染任何额外元素。
- **统一破坏性确认原语**：新增 `components/ui/ConfirmDialog.tsx`——确认按钮 pending 期间禁用（杜绝双击
  重复 DELETE）、`onConfirm` 抛错时**不关闭对话框**而是就地显示错误（409 的计数正是要被读到的地方）、
  删项目需键入项目 `key` 解锁。四个破坏性动作共用它，不各页手搓。

### 接口语义变更一览（成功路径 shape 只增不改）

| 端点 | 变更 |
|---|---|
| `PATCH /api/projects/:id` | **新增**（admin/pm）：`name`/`key`/`description`/`owner_id`/`archived` |
| `DELETE /api/projects/:id` | **新增**（admin）：204；仍有工单 → 409（detail 带计数） |
| `DELETE /api/agents/:id` | **新增**（admin/pm）：204；仍有未终态工单 → 409（detail 带计数） |
| `PATCH /api/users/:id` | 接受 `is_active`；降级 / 停用最后一位有效管理员 → **409**；无任何可更新字段 → **400**（此前 200） |
| `PATCH /api/{requirements\|bugs}/:id/assign` | `assignee_type: null` = 显式取消指派（此前 400）；`""` 等坏输入仍 400 |
| `POST /api/auth/login` | 已停用账号 → **403**（不计入限流） |
| 全部 `@jwt_required()` 端点 | 已停用 / 已不存在用户的 token → **401** `account is disabled or removed` |
| `GET /api/projects` | **默认只返回未归档**；`?include_archived=1` 全返；每项 additive 增加 `archived` / `archived_at` |
| `GET /api/board/*` | 每列上限 `?column_limit=`（默认 100，钳制 `[1,500]`）；每列 additive 增加 `total` / `truncated` |
| `GET /api/{requirements\|bugs}/:id/activities` | 接 `?limit/offset` + `X-Total-Count`（默认上限 200，响应体仍是裸数组） |
| 全部返回工单的端点 | `assignee` 指向已删除目标时返回占位对象（含 `deleted: true`）而非 `null` |
| `GET /api/users` 各响应 | additive 增加 `is_active`（`to_dict` 与 `summary` 均有） |

### `schema_sync` 的能力边界与升级判据

`backend/services/schema_sync.py` **只做 ADD COLUMN**。改类型 / 改约束 / 删列 / 改表名 / 数据回填
一律不在其内——它们需要真正的迁移工具与人工审阅，擅自扩展本模块会制造「看起来有迁移、其实静默错数据」
的更坏局面。

- **加列的正确姿势**：在 `models/` 里加列的同时，**必须**在 `ADDITIVE_COLUMNS` 里登记一条
  `(表名, 列名, DDL)`，否则存量库全线 500。
- **何时必须换成 Alembic**：出现第一个「改类型 / 改约束 / 需要数据回填」的需求时。
- **失败即启动失败**（刻意）：任一 `ALTER` 抛错则异常向上传播、应用起不来——模型与库不一致地跑起来，
  比起不来危险得多。手工回退命令：
  `sqlite3 backend/aragon.db "ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1;"`。

### 质量门禁

```powershell
cd backend
pytest -q            # 零失败且用例总数不减（新增迁移器 / 治理不变量 / 生命周期 / 看板分页用例）
```
```
cd frontend
npm run typecheck    # tsc --noEmit → 0 error
npm run build        # next build → 16/16 页成功
```

更多设计细节见 [`docs/plans/lifecycle-and-governance/spec.md`](docs/plans/lifecycle-and-governance/spec.md)。

---

## 数据持久化与示例数据清理（Data Persistence & Seed Slimming）

### 数据存在哪、存不存得住

- **单一库文件**：`DATABASE_URL` 默认由 `backend/config.py` 所在目录解析为**绝对路径**，
  从仓库根还是 `backend/` 启动都命中同一个 `backend/aragon.db`。启动日志会打印
  `storage: sqlite file=<绝对路径> exists=… size=…`——「数据去哪了」先看这一行。
- **WAL + busy_timeout**：文件库连接上自动设 `journal_mode=WAL`、`synchronous=NORMAL`、
  `busy_timeout=15000`。WAL 让读不阻塞写、崩溃窗口更小；`SQLITE_SYNCHRONOUS=FULL`
  可回到「每次提交 fsync」的语义。网络盘 / 只读挂载上 WAL 会静默失败——此时**只记
  warning 并继续启动**，`GET /api/health` 如实报告真实生效值，不粉饰。
- **健康检查自省**（additive，既有字段字面不变）：

  ```jsonc
  "storage": { "persistent": true, "journal_mode": "wal",
               "foreign_keys": true, "synchronous": "NORMAL" }
  ```

  `persistent: false` 就意味着当前跑在内存库上、重启即失忆。**有意不含路径**——
  该端点无需鉴权。自省失败只会把这几个字段降级为 `unknown`，**绝不改变 200/503 判据**。
- **崩溃残留软锁自愈**：`agents.status='busy'` 是一把落库的软锁，进程被 `Ctrl+C` 杀死时
  `finally` 不执行，锁会永久留在库里、该 Agent 此后每次调用都 409。现在启动时自动解回
  `idle`。**多 worker 部署必须把 `RELEASE_STALE_LOCKS_ON_STARTUP` 置 `false`**
  （否则第二个 worker 会误解锁第一个正在跑的 Agent），并改用带心跳的租约锁。

### 示例数据与清理

首启的示例数据是**每类恰好一条**（共 8 行），且每一行都在 `seed_records` 表里登记了出身。
存量库里的旧演示数据（v1 的 31 行）没有登记，用一次性维护工具清理：

```powershell
cd backend
python tools/purge_demo_data.py                 # 默认 dry-run：只报告，不写库
python tools/purge_demo_data.py --apply         # 备份后真正执行
python tools/purge_demo_data.py --apply --json  # 机器可读报告
```

| 退出码 | 含义 |
|---|---|
| `0` | 正常结束，且没有任何守卫跳过 |
| `1` | 参数错误 / 库不存在 / 前置校验失败（未执行任何删除）|
| `2` | 正常结束，但存在守卫跳过（末任管理员 / Agent 仍有在手工单）|

四重保险：**默认 dry-run**（只有显式 `--apply` 才写库，不可配置）、指纹**精确相等**匹配
（不用 `LIKE`，避免误伤标题里含「拖拽」的真单）、`--apply` 前自动用 SQLite 在线备份 API
生成 `aragon.db.bak-<时间戳>`、报告先列出「清理后剩余」供人核对。

**最重要的一条规则**：`comments` / `activities` / `notifications` **永不按计数裁剪**。
这三张表里绝大多数行是用户真实产生的审计与讨论，且没有出身标记；工具只删「已登记 ∪
被删工单级联带走 ∪ 指向不存在实体的孤儿」三类。**没有出身证明的行，一律推定为真实数据。**

其他须知：

- 被其他行引用的 seed 用户会被**停用**（`is_active=False`）而不是删除——删干净就等于
  销毁审计轨迹。报告里会写明「停用（仍被 N 行引用）」。
- 删除 Agent / 用户会在存活工单上留下悬空 `assignee_id`（多态软引用，无外键，UI 显示
  「(已删除)」），与既有 `DELETE /api/agents` 行为一致；报告里的
  `dangling assignments` 一行会在 `--apply` 之前把它告诉你。
- **想反悔**：`copy aragon.db.bak-<时间戳> aragon.db`。
- **兜底路径**：如果你确信库里本来就没有真数据，直接删掉 `backend/aragon.db` 再启动即可，
  新 seed 会重建那 8 行——零风险、一条命令。这个工具服务的是另一类人：库里真假混杂，
  且真的那部分丢不起。

更多设计细节见
[`docs/plans/data-persistence-and-seed-slimming/spec.md`](docs/plans/data-persistence-and-seed-slimming/spec.md)。

---

## 全流程文档管理（Ticket Document Management）—— 交付物和状态一起流转

前十轮把**状态**流转得很好，但真实团队跑一张需求单时，流转的从来不只是状态，还有
**交付物**：需求说明书、技术方案、测试计划、复现录屏、验收报告。此前它们在系统里没有
任何落点——用户只能硬塞进 `description`（无版本、无格式、无法下载），或贴一个会失效的
外部网盘链接。本轮把「上传 / 查看 / 编辑 / 绑定」四条能力一次补齐，并**贯穿全流程**。

### 一句话立场

**需求和 BUG 从新建到关闭的每一个环节，都要能上传、查看、编辑、绑定它的文档；
文档是可复用的一等资源，不是某张单的私有附件；每一次文档动作都进时间线。**

### 三张表，不是一张附件表

| 表 | 职责 |
|---|---|
| `documents` | 文档的**逻辑实体**：标题、类型、描述、归属项目、上传者、当前版本指针 |
| `document_versions` | 每一次落盘就是一个**版本**：原始文件名、MIME、大小、SHA-256、备注 |
| `document_links` | 文档 ↔ 工单的**多对多绑定**，附 `stage`（绑定当时的工单状态**快照**，永不回写）|

一张 `attachments` 表意味着「同一份 PRD 服务 5 张单」要存 5 行、5 份磁盘副本，改名要改
5 处——那正是本轮要消灭的问题本身。而「编辑」若不产生新版本行，就只能覆盖原文件，历史
直接消失，而研发文档的价值有一半在版本对比上。

### 存储：内容寻址 + 去重

文件按 SHA-256 摘要落盘到 `UPLOAD_DIR/<ab>/<cd>/<digest>`，元数据全部进数据库。
一刀切在这里同时拿下三件事：**去重**（同一份文件传 10 次只占一份磁盘）、
**防路径穿越**（落盘路径由摘要推导，与用户提供的文件名**结构性无关**，而不是靠某个
清洗函数守住）、**可校验**（摘要即完整性签名）。**零新增依赖**——不上 boto3、
不上 python-magic、不上 Alembic。

上传边界五道闸，任一不过即 **400**（绝不 500）：引用前置校验（`project_id` /
`document_id` 存在性）→ 存在性 → 文件名清洗 → 扩展名白名单 → 魔数嗅探。
超大请求体由 Flask 的 `MAX_CONTENT_LENGTH` 在**进入路由之前**拦下，返 **413**。

### ⚠️ 多机部署：`UPLOAD_DIR` 必须共享

内容寻址天然幂等，多进程同时写同一摘要靠 `os.replace` 原子收敛，**单机多 worker 无需
任何额外配置**。但**多机部署必须把 `UPLOAD_DIR` 指向共享存储**（NFS / 对象存储挂载），
否则一台机上传的文件另一台读不到，用户会随机地拿到 410。切换到对象存储时唯一需要替换的
模块是 `backend/services/documents/storage.py`——它的六函数窄接口就是为此预留的。

### 阶段文档门禁（默认关闭）

`services/doc_policy.py` 为每个（实体, 状态）声明「这一步通常应该有哪几类文档」，
前端在抽屉里渲染为**建议性清单**（缺失项本身就是一个上传按钮）。默认**绝不阻断**任何流转。

把 `DOC_STAGE_GATE=true` 打开后，人类推进在材料不齐时会收到 409。四条铁律：

1. **状态机仍是唯一的迁移仲裁者**——门禁插在 `can_transition` 判 True 之后、写入之前，
   只能否决一次合法迁移，永远无法放行一次非法迁移；`services/workflow.py` 一行未改。
2. **Agent 路径永久豁免**——`agent-advance` / `autorun` / `tick` / `claim-next` 一律不受
   门禁约束。Agent 是后台循环，被挡住会表现为「自动流水线莫名其妙不动了」，而没有任何
   一个人会收到那个 409。改为在时间线上写一条**去重后的**建议性提示。
3. **只作用于「前进」迁移**。用户按下回退键的原因恰恰是材料不合格；门禁若在回退时也生效，
   就会出现「因为缺测试报告，所以你不能把这张误标为已完成的单退回去补测试报告」的死结。
4. 该 409 **不带 `allowed` 键**——前端看板拖拽以它是否存在区分「状态机非法」与「其他冲突」。

### 删除语义：对用户真实数据的推定必须是保留

- **删工单** → 只删它的**绑定关系**，**文档本体绝不删除**。它可能绑在别的单上；即使没有，
  它也是用户真实上传的数据。抽屉里的删除确认文案会如实说明这一点。
- **删文档** → 仍有绑定时返 **409** 并给出计数；pm/admin 可 `?force=1` 强删，此时为每张
  受影响的单写一条 `doc_detached` 审计。
  **从 `document-lifecycle-depth` 起，删除是「移入回收站」而不是物理删除**：外部契约
  （204 / 409 / 403 / 404）一字未变，内部由删行改为置位 `deleted_at`。文档随后可经
  `POST /api/documents/:id/restore` 恢复；真正不可逆的只有 admin 专属的 `?purge=1`。
  软删**不解除**已有绑定（走 `?force=1` 的那些除外——它按老规矩先解绑），因此恢复之后
  工单抽屉里的位置与 `link.stage` 快照原样回来。
  软删期间 **blob 绝不会被 GC 回收**：`document_versions` 行还在，摘要仍被引用，
  `test_gc_keeps_blobs_of_soft_deleted_documents` 钉死这一点——否则恢复出来的是一个空壳。
- **物理 blob 的回收恒在 commit 之后**，且在线路径**只做判定不硬删**：删除最后一个引用后、
  unlink 之前，另一个请求可能**去重命中**同一摘要（命中时不写盘），此时删下去就会让别人
  刚上传的文件永久指向空气。故引入 `BLOB_GRACE_SECONDS` 宽限窗口 + 去重命中时 `os.utime`
  触碰 mtime，把这个窗口从毫秒级不可控变成小时级且可配。

### 孤儿 blob 回收 CLI

```
python backend/tools/gc_orphan_blobs.py                 # 默认 dry-run，只报告
python backend/tools/gc_orphan_blobs.py --apply         # 真删
python backend/tools/gc_orphan_blobs.py --apply --json  # 机器可读报告
```

回收判据**不是**「磁盘上有、`document_versions` 里无人引用」这一条——`UPLOAD_DIR/.tmp/*.part`
恰好满足它，而那是**其他进程正在写入**的临时文件。三条判据缺一不可（与在线删除**共用同一个
`storage.is_reapable`**）：不在 `.tmp/` 下、路径符合 `<2hex>/<2hex>/<64hex>` 的内容寻址形状、
mtime 早于 `now - BLOB_GRACE_SECONDS`。报告会**分别**列出「本轮实际回收」与「无人引用但仍在
宽限期内（跳过）」——一个只说自己删了多少、不说自己跳过了多少的清理工具，会让人误以为已经
清干净了。退出码沿用 `purge_demo_data` 约定（`0` / `1` / `2`）。

### 回收站过期清理 CLI

```
python backend/tools/purge_trash.py                 # 默认 dry-run：只列出超期文档，不改任何东西
python backend/tools/purge_trash.py --days 7        # 覆盖 DOC_TRASH_RETENTION_DAYS
python backend/tools/purge_trash.py --apply         # 真删（行 + 释放的 blob）
python backend/tools/purge_trash.py --apply --json  # 机器可读报告
```

彻底删除走 `services/documents/trash.py::purge`，与 HTTP 的 `?purge=1` **完全同一个入口**：
它**自包含**地先解绑（逐单写 `doc_detached`，受 `DOC_FANOUT_MAX_LINKS` 约束）再删行。
这一点不是洁癖——`document_links.document_id` 是真外键且 `PRAGMA foreign_keys=ON` 每连接
生效，把解绑留在调用方，CLI 就会在第一份带绑定的过期文档上撞外键并崩掉整批。
**逐个文档各自 try/except**：一份失败只记进 `skipped` 并继续。

**有意不自动调度**：本项目没有调度器；引入定时任务意味着引入一个能在无人值守时
**不可逆删除用户数据**的组件，那需要单独讨论它的可观测性与熔断。与 `gc_orphan_blobs.py` /
`purge_demo_data.py` 一致：不可逆操作由人按下。退出码 `0` 正常 / `2` 前置条件失败。

### 新增环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `UPLOAD_DIR` | `<repo>/backend/var/uploads` | blob 根目录。**多机部署必须共享**（见上）；已随 `.gitignore` 排除 |
| `MAX_UPLOAD_MB` | `20` | 单请求体上限；超限返 413 且响应体是 JSON 契约 |
| `DOC_ALLOWED_EXTENSIONS` | `md,txt,log,csv,json,yaml,yml,pdf,png,jpg,jpeg,gif,webp,doc,docx,xls,xlsx,ppt,pptx,zip` | 扩展名白名单（逗号分隔）。**有意不含 `html/htm/svg/js`**——它们能在同源下执行脚本，而这是文档预览路径上真正生效的第一道防线，任何放宽都必须重做安全评估 |
| `DOC_STAGE_GATE` | `false` | 阶段文档门禁总开关。默认关闭，行为与本轮之前逐字节相同 |
| `BLOB_GRACE_SECONDS` | `3600` | blob 回收宽限窗口，关闭「删除↔去重」竞态 |
| `DOC_TEXT_PREVIEW_MAX_BYTES` | `1048576`（1 MB）| `/content` 文本预览上限；超出则 `truncated=true` |
| `DOC_TEXT_EDIT_MAX_BYTES` | `524288`（512 KB）| 在线编辑上限。**启动期断言必须严格小于预览上限**，否则可编辑大小的文件会被截断后保存，截断即成为新版本的全部内容 |
| `DOC_FANOUT_MAX_LINKS` | `20` | 单次改版最多向多少张单扇出时间线 + 通知；超出只写一条汇总，并在响应体如实回传 `fanout_truncated` |
| `DOC_AGENT_ARCHIVE` | `true` | Agent 交付物归档总开关（`document-lifecycle-depth`）。关掉即完全回到上一轮行为。**运维注记：它是唯一一个「升级即生效、且会自动产生用户可见数据」的开关**——首次上线建议先以 `DOC_AGENT_ARCHIVE=false` 跑一轮，确认 LLM 产物质量与 `ARCHIVE_KIND` 的归类符合预期后再打开。归档只在**真实 LLM 产物**上触发（测试与离线环境恒不触发），且**只写 Activity、不发通知** |
| `DOC_AGENT_ARCHIVE_MIN_CHARS` | `200` | 短于此长度的 Agent 产物不建成文档——两句话的产出不值得成为一份「交付物」 |
| `DOC_TRASH_RETENTION_DAYS` | `30` | 回收站保留期（天）。**运行时不据此自动删任何东西**，只有 `tools/purge_trash.py` 在人按下 `--apply` 时读它；前端的「剩余 N 天」也由 `GET /api/documents/meta` 下发此值，**不得硬编码** |

### 安全取向

- **Markdown 渲染成 React 元素树，不是 HTML 字符串**（`document-lifecycle-depth` 起）。
  上一轮的取向是「不引入 Markdown 渲染库」，理由是「渲染 Markdown 意味着 HTML 输出，
  意味着必须再配一套消毒库」——本轮换了一条**结构性**的路：`frontend/lib/markdown.ts`
  零依赖、返回 `ReactNode[]`，实现中**不存在** `dangerouslySetInnerHTML` / `innerHTML` /
  字符串拼 HTML 的任何路径。于是用户正文里的 `<img src=x onerror=alert(1)>` 只能作为
  **文本节点**出现：XSS 不是「被过滤掉了」，而是**没有可以注入的位置**。
  链接只放行 `http:` / `https:` / `mailto:`（`javascript:` / `data:` 降级为纯文本字面），
  图片**不外链**（渲染为 `[图片: alt]`，避免向第三方泄漏内网访问行为），裸 HTML 逐字显示。
  `.md` / `.markdown` 之外的文本类型行为**逐字节不变**，仍是 `<pre>`。
- **前端预览的 `objectURL` 硬规则**：`blob:` URL 的 MIME 完全取自前端 `new Blob(..., {type})`
  的入参、与任何响应头无关，且 `blob:` 文档运行在**前端源**（JWT 就在这个源的 localStorage
  里）。因此 Blob 的 `type` 只能来自后端 `mime_type` 且必须先过 `INLINE_SAFE_MIMES` 白名单；
  PDF 只在 `<iframe sandbox>` 内渲染；文本只进 `<pre>` 的文本节点；**禁止**把 `objectURL`
  交给 `window.open` 或任何顶层导航。
- **`TEXT_EXTENSIONS` 与 `INLINE_SAFE_MIMES` 回答的是两个不同的问题，不可互换**：前者是
  「这份东西的正文能不能当纯文本读」（正文经 `/content` 这个 JSON 端点取回，全程不产生
  `blob:`，故它**没有任何安全职责**）；后者是「哪些 MIME 允许被浏览器当作文档直接渲染」
  （`text/html` 与 `image/svg+xml` 被刻意排除）。`.csv` / `.json` / `.yaml` 此前因为
  用错了判据而被推去下载——本轮改的是**判据**，`INLINE_SAFE_MIMES` 一个字节都没动。
  把它们加进那张白名单是一个看起来更短、实则把仅存的防线撬松的改法（`text/html` 只隔一行）。
- **不做病毒 / 恶意内容扫描**（显式的 Non-Goal）。本轮的取向是「不执行、不渲染、不解压」——
  文件只被摘要、存盘、原样回吐，服务端从不解析其内容。真正的查杀属于部署侧议题。

### 质量门禁

- 后端：`cd backend` → `python -m pytest -q`。**597 passed**（`document-lifecycle-depth` 开工基线 506，本轮新增 5 个测试文件共 91 条）。
  判据是**相对的**：零失败 + 总数不低于基线 + 本轮新增；README 里的绝对数字只是留痕，以实测输出为准。
- 前端：`npm run typecheck` + `npm run build`，均零错误。

更多设计与评审细节见
[`docs/plans/ticket-document-management/spec.md`](docs/plans/ticket-document-management/spec.md)。
