# AragonTeam 迭代记录（详细版）

> 本文是 README 的详细归档：逐轮记录每次迭代的设计取舍、接口语义变更与验收结论。
> 只想快速跑起来，请看仓库根目录的 [`README.md`](../README.md)。
> 每轮的完整 spec 在 [`docs/plans/`](plans/) 下。

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

---

## 自助注册与根管理员治理（Self-Service Registration）—— 谁能进这个系统，由配置和邀请码一起决定

设计与评审全文见
[`docs/plans/self-service-registration/spec.md`](plans/self-service-registration/spec.md)（v2，含 §0 评审记录）。

### 一句话立场

用户来源此前只有一条路径：管理员在「团队」页代建账号、把明文密码经 IM 发给本人。
本轮把它拆成三根支柱——**邀请码门禁的自助注册**（谁都能自己进来，但得先有码）、
**配置文件定义的根管理员**（永远有一个人进得来，且这条恢复路径不在库里）、
**管理员的治理面**（人一多之后仍然看得清「这批人是谁、从哪来、还该不该留着」）。

### 根管理员：配置文件是唯一真相

`ROOT_ADMIN_USERNAME` / `ROOT_ADMIN_PASSWORD` 写在后端配置里，
`services/bootstrap.py::ensure_root_admin` 每次启动幂等地保证这个账号存在、是 admin、
是启用状态、带 `users.is_root` 标，并保证全库**至多一行**为真。它不可被降级 / 停用 /
被他人重置密码（409，且响应体**不带 `allowed` 键**，不误伤看板拖拽的错误分流）。

- **调用顺序不可换**：必须排在 `seed_if_empty()` **之后**。seed 的幂等判据是
  `User.query.count() == 0`，先建根管理员会让全新库上 users 恒非空，示例项目 / 需求 /
  BUG / 评论一行都不写入。默认配置下的时序是「seed 建出 `admin` → bootstrap 认领同一行 →
  只打 `is_root` 标」，因此**全新库的开箱体验与本轮之前逐字相同**（users 仍然只有 1 行）。
- **`ROOT_ADMIN_BOOTSTRAP` 有五个必须关闭的入口**：`TestConfig`、`tests/conftest.py::file_app`、
  以及三个运维 CLI。`file_app` 的基类是 `Config` 而**不是** `TestConfig`——只关前者，
  `test_purge_demo_data.py` 的空库上会先被建出一个 `admin`，随后撞上同名插入 →
  唯一索引冲突 → 该文件 15 条用例集体炸；三个 CLI 还会往目标库里凭空写一个用户行，
  直接违背 `purge_demo_data` 开篇「dry-run 绝不写库」的第一原则。
- **忘密码只有一条恢复路径，四步顺序不可换**（README 有完整说明）：
  设 `ROOT_ADMIN_SYNC_PASSWORD=true` → 重启 → 登录 → **先把 flag 设回 false 并再重启一次**，
  之后才去改密码。颠倒最后两步，新密码会在下一次重启时被静默改回配置里的旧值。
  该 flag 为真时**每次启动都打 warning**，就是为了让「登录完忘了关」在下一次重启就被发现。
- **`ROOT_ADMIN_USERNAME` 是保留用户名**。`POST /auth/signup` 与 `POST /api/users`
  共用 `app_settings.is_reserved_username`，响应体与普通重名 409 **逐字节相同**——
  既堵住「抢注那个名字、等下次重启把自己变成不可降级的根管理员」，又不额外泄露
  「这个名字是根管理员用户名」。提权既有账号时必打含 user id 的 warning。

### 邀请码与自助注册

- **一张键值表而不是逐个加列**：`app_settings` 是本轮唯一新增的表（`create_all` 自动建）。
  本轮只需要三个设置项，但未来一定还有第四第五个；逐个加列意味着每次都要动 `schema_sync`。
  代价是失去列级类型约束，故类型与业务约束全部收敛在 `services/app_settings.py`，
  **路由层永远不直接读表**。
- **不缓存**。每次注册请求打一次唯一索引查询。进程内缓存在多 worker 下必然失效不同步
  （改了邀请码只有一个 worker 生效），是典型的「优化制造出的 bug」。
- **邀请码明文存储**，这是有意识的取舍：根管理员必须能读回来才能发给同事，哈希存储会让
  「查看当前邀请码」不可能实现。缓解是可随时一键 rotate（旧码**立即失效、无宽限期**）、
  可关总开关、只有根管理员能读。
- **`default_role` 无条件过 `SIGNUP_ROLES`（member/pm）白名单**，库内脏值与**配置兜底值**
  一视同仁。`PATCH` 端点上的白名单只管住了「改设置」这条路径，管不住「全新库上
  `app_settings` 为空、直接走配置兜底」——而后者恰恰是每次全新部署的常态。
  少了这一步，`REGISTRATION_DEFAULT_ROLE=admin` 一个环境变量就能让任何拿到邀请码的人
  注册即为管理员。
- **口令强度只作用于 `/auth/signup`**。有意不套用到 `POST /api/users` 与
  `POST /api/me/password`：那两条路径今天没有任何长度约束，存量测试里存在 6 位口令的用例，
  收紧它们是一次破坏性变更。统一全站口令策略是明确的后续项。
- **`/signup` 的 409 可用于枚举用户名**，有意接受：攻击者要先拿到邀请码，而把 409 换成
  模糊错误会让真实用户在「换个名字重试」时完全失去反馈。

### ⚠️ 反代部署必须设 `TRUST_PROXY_COUNT=1`

本仓库自带 nginx 反代模板，而后端**没有** `ProxyFix`。那种部署下每个请求的
`remote_addr` 恒为 `127.0.0.1`，注册限流会退化成**全站单桶**：一个人手滑几次就把全公司
挡在注册门外，对真攻击者反而毫无作用（他就是那唯一的桶）。

选「显式配置 + 从右往左取第 N 跳」而不是无脑接 `ProxyFix`：后者是全局中间件，一旦装上，
**所有**读 `remote_addr` 的地方都无条件相信客户端可写的 `X-Forwarded-For`——直连部署下
装它，等于把限流键的取值权交给攻击者。默认 0 = 一个转发头都不信，与本轮之前的行为逐字节相同。

### 前端：让「漏改一处」变成编译错误

新增通知类型 `user_registered` 时发现，前端的通知类型有**三处**镜像，其中两处漏改
**不会**被 `npm run typecheck` 拦住：`NOTIFICATION_LABELS` / `NOTIFICATION_ICONS` 是
`Record<string, string>`，取值函数还带 `|| type` 兜底，铃铛里只会显示英文原文 `user_registered`；
`NotificationPrefsCard` 的 `TYPES` 是手写数组，漏加只会让用户永远关不掉这类通知。
本轮把两个 map 收紧为 `Record<NotificationType, string>`、把 `TYPES` 改为从
`lib/types.ts::NOTIFICATION_TYPE_LIST` 派生——这道门禁在通知链路上才第一次真正成立。
收紧**有意不外扩**到 `STATUS_STYLES` / `ROLE_LABELS` / `ACTION_LABELS`，那是另一轮的清理。

其余前端要点：登录页的 `DEMO_ACCOUNTS` 一键填充块（`admin` / `admin123`）**已删除**——
它在任何真实部署里都是一个公开页面上的管理员后门；信息本身没丢，README 快速开始写明了
默认账号来自 `ROOT_ADMIN_*`。团队页的数据层由 `swrFetcher` 整体换成 `listFetcher`
（此前完全没有分页接线，靠 `limit=200` 硬扛），并**自建 SWR key**——绝不复用
`USERS_KEY`，否则指派选择器会被筛选结果污染、突然只剩几个人。

### 反向 schema 漂移守卫（本轮补上的一个假护栏）

`test_schema_sync.py` 原有的守卫是**单向**的：它只遍历 `ADDITIVE_COLUMNS` 去查模型，
所以「给模型加了列却忘了登记」**不会让任何用例变红**，直到存量库上线全线 `no such column`。
本轮补上 `test_every_model_column_is_creatable_or_registered`：模型列 ⊆ 冻结的 create_all
基线列 ∪ `ADDITIVE_COLUMNS`。CLAUDE.md 里那条硬约束第一次有了机器执行者。

### 新增环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ROOT_ADMIN_USERNAME` / `ROOT_ADMIN_PASSWORD` | `admin` / `admin123` | 根管理员账号，**生产必须覆盖密码** |
| `ROOT_ADMIN_EMAIL` / `ROOT_ADMIN_DISPLAY_NAME` | `admin@aragon.dev` / `Ada（管理员）` | 展示信息 |
| `ROOT_ADMIN_BOOTSTRAP` | `true` | 启动期保障开关；测试与三个运维 CLI 必须关 |
| `ROOT_ADMIN_SYNC_PASSWORD` | `false` | 忘密码恢复开关，平时必须 false |
| `REGISTRATION_ENABLED` / `REGISTRATION_INVITE_CODE` / `REGISTRATION_DEFAULT_ROLE` | `true` / `aragon` / `member` | 自助注册的**兜底默认值**，库内有行时以库为准 |
| `SIGNUP_MAX_ATTEMPTS` | `10` | 单客户端 5 分钟内注册尝试上限（成功也计数） |
| `TRUST_PROXY_COUNT` | `0` | 信任几层反代的 `X-Forwarded-For`；**反代部署必须置 1** |

### 明确不做

邮箱验证 / 找回密码（需要 SMTP）、注册审批队列（用「邀请码 + 可事后停用」达到同等治理
效果，复杂度低一个数量级）、统一全站口令策略、多根管理员 / 组织级 RBAC 重构、
SSO / OAuth / LDAP、分布式限流（`client_ip()` 只解决「反代下 IP 全都一样」，
**不**解决「多 worker 各算各的」——那与既有 `/login` 限流是完全相同的已知缺口）。

### 质量门禁

- 后端：开工基线 `pytest -q --collect-only` = **597 条 / 39 个文件**；收工实测见下方提交说明。
  判据是**相对的**：零失败 + 总数不低于基线。
- 前端：`npm run typecheck` + `npm run build`，均零错误。

---

## 第 9 轮：账号安全与治理收口（account-security-and-governance）

完整设计见 [`docs/plans/account-security-and-governance/spec.md`](plans/account-security-and-governance/spec.md)。

上一轮把「谁能进这个系统」治理住了，却**没有治理「进来之后，口令这件事由谁负责」**。
实际状态是：自助注册的人被要求 8 位两类字符的口令，而管理员代建的同事可以拿到一个 `p`
作为长期口令——管理员知道它、浏览器保存它，没有任何机制促使它被换掉。同一个产品里，
安全水位由**「你是怎么进来的」**决定，这本身就是缺陷。本轮收口四件事。

### ⚠️ 破坏性变更告示（本轮唯一一次，有意为之）

| 端点 | 此前 | 现在 |
|---|---|---|
| `POST /api/users` | 弱口令 201（一个字符也行） | 弱口令 **400** |
| `POST /api/auth/register` | 同上 | 同上；另：命中保留用户名由 201 变 **409**（这不是破坏，是补一个真实存在的缺口——合并前 `users.py` 有这道守卫、`auth.py` 没有） |
| `PATCH /api/users/:id` 带 password | 无约束 | 过策略；且**他人**重置会置 `must_change_password` |
| `POST /api/me/password` | 下限 6 位 | 下限 = 策略值（默认 8）；错误串由 `new password must be 6..128 chars` 变为 `password must be 8..128 chars`（`current password is incorrect` 与 `new password must differ from current` **逐字保留**） |

**登录路径永不重新校验口令**：存量的弱口令用户不会被锁在门外。
`POST /api/users` 的 password 同时**变为可选**（缺省 → 服务端生成一次性口令），那是放宽，
不破坏任何调用方；`POST /api/auth/register` **有意不获得**这个新能力——它是给存量管理台
与脚本用的兼容端点，扩它的能力面等于制造第二个主入口。

### 一、一份口令策略，四条写入路径共用

`services/passwords.py` 从「只服务 `/auth/signup`」改写为**全站唯一真相源**。配置只提供
两个阈值旋钮，它们的合法区间、脏值回落与钳位全部收敛在 `policy()` 里：钳到 `[6,128]` /
`[1,4]`。**钳位不是防御性编程，是给一个人类可写的旋钮加物理止挡**——`=0` 会让策略静默
变成「没有策略」，`=999` 会让所有人（包括根管理员）都改不了密码，那是一个手滑造成的、
产品内无恢复路径的死锁。

一次性口令生成器的长度区间由策略**派生**（`lower = min_length + 4`，再被 `max_length`
上钳），而不是与它并列取 `max`：写成 `[max(min_length, 8), 32]` 会在 `min_length > 32`
的**合法配置**下变成空区间，生成出一个违反自己策略的口令。生成后不写
`assert count_char_classes(...) >= 3` 这种与策略脱钩的常数断言，而是**把成品喂给策略本身**
（`validate_password(result)`）——策略以后怎么改，这一行都不会说谎。

策略经 `GET /api/auth/registration-meta` 下发（additive 两键），前端**不再硬编码** 8/2。
关键在于它穿进的是 `passwordRules` / `isPasswordAcceptable` 两个**模块级纯函数**，不是
组件 props：真正拦住提交的是 `RegisterForm` 在组件**之外**调用的 `isPasswordAcceptable()`，
只给组件加 props 的话，根管理员把下限调到 12 之后注册页仍按 8 放行、点提交才 400。

### 二、一次性口令 + 强制改密（管理员不该替别人想密码）

新增列 `users.must_change_password`（已登记 `ADDITIVE_COLUMNS`，存量行零回填即语义正确）。
置位判据**不是「走了哪条路径」，是「谁改了谁的口令」**（`actor.id != target.id`）——
无条件置位会让任何用管理台给自己改密的人（含根管理员）当场被闸门自锁。

服务端闸门 `install_password_gate(app)` 是一条 `before_request`，而不是逐路由装饰器：
路由有 40+ 个，漏挂一个就是一个后门。四条不可动摇的约束：**`OPTIONS` 第一顺位放行**
（CORS 预检被拦 = 全站跨域瘫痪，而日志里只有一串 403，是最难定位的一类故障）；
只捕获 JWT 族异常并**放行**（闸门在语义上不负责鉴权，令牌问题交给端点的 `@jwt_required()`
产出既有 401）；闸门内**不做第二次查库**（依赖 SQLAlchemy identity map 同会话命中）；
`FORCE_PASSWORD_CHANGE=false` **只关硬拦、不关标记**。

`ensure_root_admin` **恒不置位**，且 `services/bootstrap.py` **不得 import** 策略模块：
让破窗路径也过一遍口令策略，意味着存量部署里一个 7 位的 `ROOT_ADMIN_PASSWORD` 会让
**应用起不来**——把一次配置瑕疵升级成一次完全无法自愈的全站宕机。告警，不阻断。

### 三、根管理员保护：新端点不得复用为另一种形状写的守卫

新增 `POST /api/users/:id/reset-password`。设计评审在这里拦下了一个**完整的权限提升路径**：
初版说「复用 `_reject_root_mutation` 判据」，但那个函数的口令分支挂在 `data.get("password")`
上，而新端点的**主用法恰恰是空 body**（服务端生成口令）→ 判据恒假 → **任意 admin 都能
把根管理员的口令重置成一个自己看得见的一次性口令，然后完全接管破窗账号**。

实现节点先写了复现用例再改代码，并**实测确认了它在旧写法下返回 200**（而不是 409）。
现在的判据与请求体无关，判定顺序被钉死为：`404` → `409 根管理员保护` → 读 body →
`400 口令策略`；`_reject_root_mutation` 的 docstring 上加了「任何 body 可空的端点都不得
复用它」这条前提，让下一个想复用它的人**在复用之前**就看见。

### 四、账号治理审计（复用 activities，不建第二张表）

`activities` 的实体维度扩到 `user` / `app_setting`（**零 DDL 变更**，只扩 Python 侧枚举）。
不建新表的理由：那张表已具备全部所需字段，且 CLAUDE.md 已把「activities 永不按数量清理」
写成仓库级不变量——审计数据落在这里天然继承那条保护。

扩表**必须同时修两处外溢**，漏掉任何一处都是缺陷：

1. `GET /api/stats` 的两处 `Activity.query` 钉死在 `TICKET_ENTITY_TYPES` 上。否则
   「停用了张三」会出现在**所有成员**都能打开的仪表盘「最近动态」里——一次实打实的信息
   泄露，而且前端按 `entity_type` 渲染跳转链接，`user` 类型会渲染成指向不存在工单的死链。
2. `purge_demo_data::_user_references` 追加「被治理」计数。该函数原先只统计「这个人**做过**
   治理动作」，漏掉「这个人**被**治理过」的那一半：一个从没做过管理动作、但被停用过一次的
   普通成员会被判为可硬删，而 SQLite 复用主键后，下一个同 id 的用户会继承他的治理时间线。

审计写入口收敛在 `services/audit.py`（路由层**不直接调** `Activity.log`），它**绝不**把
口令、哈希、邀请码明文写进 message——审计要能被广泛阅读，凭据不能。注册配置变更的 message
**只列被改动的键名，不带值**。

### 五、建号路径合并 + 保留名表

`POST /api/users` 与 `POST /api/auth/register` 合并到 `services/accounts.py::create_user_by_admin`，
两条契约的差异全部落在 `allow_generated` 一个参数上，不允许再有第二处分叉。
用例 `both_create_paths_produce_identical_user_rows` 是「同一件事只有一份实现」的机器执行者：
两条路由哪天再漂移，它先红。保留用户名从「只有根管理员一个」扩成一张可配置的表
（内置 11 个 ∪ `RESERVED_USERNAMES` ∪ `ROOT_ADMIN_USERNAME`），**只在建号那一刻判定**。

### 新增环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `PASSWORD_MIN_LENGTH` / `PASSWORD_MIN_CHAR_CLASSES` | `8` / `2` | 全站策略旋钮，钳到 `[6,128]` / `[1,4]` |
| `TEMP_PASSWORD_LENGTH` | `16` | 一次性口令长度，仍被策略上下界二次钳位 |
| `RESERVED_USERNAMES` | 空 | 追加保留名（逗号分隔），不追溯存量账号 |
| `FORCE_PASSWORD_CHANGE` | `true` | 强制改密闸门；`false` 只关硬拦、不关标记 |

### 明确不做

注册审批队列（会与 `must_change_password` 形成两个正交的「半激活」状态，产品语义变浑浊）、
口令历史 / 禁止复用最近 N 次、**口令过期（90 天强制轮换）**——现代口令指南（NIST SP 800-63B）
明确反对无理由的定期轮换，它把用户推向 `Password1` → `Password2`；二次验证 / TOTP、
邮件找回密码（管理员重置 + 一次性口令已经把「忘记密码」的恢复路径从「改配置重启」降到了
「找管理员点一下」）、全局审计检索页、项目 / Agent 删除也塞进 `activities`（那会让
`entity_type` 从「有语义的实体维度」退化成什么都装的垃圾桶）。

### 质量门禁

- 后端：开工基线 `pytest -q --collect-only` = **674 条 / 42 个文件**；本轮新增 2 个测试
  文件、**+68 条**用例（含参数化展开）。判据是**相对的**：零失败 + 总数不低于基线。
- 前端：`npm run typecheck` + `npm run build`，均零错误；产物含 `/force-password` 路由。
- 释放条件（设计评审要求，逐条已验证）：P0-1 的复现用例**先红后绿**（旧写法实测返回 200）；
  一次性口令在 `PASSWORD_MIN_LENGTH=40/128` + `MIN_CHAR_CLASSES=4` 下仍过策略；
  闸门落地后整跑全量 pytest；`fixture_users_are_not_flagged` 已入库。

## 第 10 轮：登录纵深与治理审计出口（login-hardening-and-audit-console）

完整设计见 [`docs/plans/login-hardening-and-audit-console/spec.md`](plans/login-hardening-and-audit-console/spec.md)。

前两轮把「谁能进来」修好了，但入口没有仪表盘。本轮把整条链路补完为「谁进来过、
进来多少次、还能进来多久」，收口三件事——每一件都对应一个**已被证实存在**的缺陷。

### 一、邀请码从一份没有额度的凭据，变成有额度、有期限、有用量的真凭据

`verify_invite_code` 此前只做定长比较：码一旦被贴进任何一个群就永久有效、可被无限次使用，
根管理员在产品内看不到它被用过几次。本轮给它加了三个设置键（`invite_expires_at` /
`invite_max_uses` / `invite_issued_at`，仍走键值表、**零结构变更**），`check_invite_code`
取代 `verify_invite_code` 成为判据，判定顺序 **mismatch → expired → exhausted** 是契约的一部分
——`expired`/`exhausted` 只在候选码与真码一致后才可能返回，否则任何人都能探测出「这个站点的
邀请码已过期」。用量是**派生值**（数「拿这个码建出来、现在还在库里」的账号）而非计数器：
规避了读-改-写竞态与「purge 删了账号计数器不降」两个失败模式。`rotate` 自动归零用量、
保留期限与额度。**值判等即整条短路**：原样再保存一次邀请码不弄脏行、不移动 `updated_at`——
少了这一步，「只设过额度、从没改过码」的库会在另一个管理员点一下保存时静默把额度归零。

### 二、登录第一次留下痕迹，并长出一道落库的刹车

`login` 此前全程不写库：成功不记时间、失败不计次数，唯一的刹车是**纯内存、按 `ip:username`**
的限流——换个 IP 就是一个全新的桶。本轮加了三列（`last_login_at` / `failed_login_count` /
`locked_until`）：连续失败达阈值即**按账号**临时锁定（落库、跨重启有效，拦得住换 IP 的慢速撞库）。
两个决定写进了契约：**锁定检查排在口令校验之后**（否则 403 会成为用户枚举预言机——攻击者看到
403 就知道「这个用户名存在且我把它打锁了」）；**根管理员永不被锁**（它是破窗入口，锁上等于拆掉
唯一的恢复路径）。绝不为每次失败写 Activity；锁定通知有 24h 冷却而审计没有——审计那一条就是
本功能的产出，压掉它等于让控制台显示一个比真相温和的攻击画像。

### 三、已经写进库里的治理审计，第一次有了出口

`app_setting` 事件此前**只写不可读**（`user_timeline` 写死 `entity_type=user`，
`stats` 已被收紧到工单实体）——「谁改了邀请码」写进去就再也拿不出来。本轮加了
`GET /api/settings/audit`（`@require_root()`，因为它会返回站点设置事件），支持按
实体 / 动作 / 施动者 / 起始时间筛选 + 分页，`actor`/`target` 一次 `IN` 查询批量解析、不做 N+1。
查询串侧补了第四个原语 `want_query_datetime`（容忍尾部 `Z`），`?since=乱码` 现在是 **400 而非 500**。

### 前端

侧栏为根管理员多出「审计」页；团队页多了「已锁定」徽章、「解锁」行操作与「最后登录」列；
注册配置卡内联了期限 / 额度 / 用量进度条。`relTime()` 的两份副本收口到新建的 `lib/format.ts`。
审计页的「非根管理员无权限态」是本仓库**第一例页面级 EmptyState**（不 redirect），
本轮把它连同分工判据写成一条新惯例。

### 新增环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LOGIN_LOCK_THRESHOLD` | `8` | 账号连续失败达此数即临时锁定；钳到 `[3,100]`。**必须 < `LOGIN_MAX_ATTEMPTS`**，否则 IP 限流先挡光、账号锁定永不触发 |
| `LOGIN_LOCK_MINUTES` | `15` | 锁定时长（分钟），自然到期无需后台任务；钳到 `[1,1440]` |
| `LOGIN_LOCK_NOTIFY_COOLDOWN_MINUTES` | `1440` | 同一账号在此窗口内已通知过就只写审计、不再扇出通知；钳到 `[0,10080]`，`0` = 每次都通知 |

### 明确不做

邮件（找回 / 邀请 / 告警）、TOTP / 二次验证、注册审批队列、分布式限流、口令历史 /
口令过期、会话/令牌管理面、审计导出（CSV/JSON）。真正还敞着的是 `ratelimit` 仍是单进程
内存实现——本轮的账号锁定补上了它在多 worker 下最要命的缺口，但没有替代它，那应是下一轮首位。

### 质量门禁

- 后端：开工基线 `pytest -q --collect-only` = **742 条 / 44 个文件**；本轮新增 2 个测试
  文件、修改 2 处既有断言，**+71 条**用例，DoD 下限 **813**。判据是**相对的**：零失败 + 总数不低于基线。
- 前端：`npm run typecheck` + `npm run build`，均零错误；产物含 `/audit` 路由。
- 释放条件（设计评审要求，逐条已验证）：用例 11′（原样再保存不归零）与用例 60（`?since=乱码`
  返回 400 而非 500）先红后绿；`test_auth.py` 在 `LOGIN_LOCK_THRESHOLD=2` 时红、`=3` 时绿；
  两条既有断言（`test_schema_sync.py:57`、`test_app_settings.py:26`）已显式改过；
  锁定用例跨过第 3 次请求前显式 `ratelimit.reset()`；通知冷却用例证明二次锁定
  `activities +1`、`notifications +0`；`relTime` 只在 `lib/format.ts` 有定义。
