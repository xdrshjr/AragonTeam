# AragonTeam 规模化可用与项目维度贯通 —「数据一多就翻不到、项目建了却用不上、工单页推不动 Agent」的收官（Spec）

- **文档版本**: **v2**（v1 由 Subtask #0 · Solution Architect 产出；v2 由 Subtask #1 · Design Reviewer 评审并就地修复 P0/P1）
- **Feature slug**: `scale-and-project-scope`
- **作者角色**: Solution Architect（Anthropic Engineering）
- **本轮需求（第 3 轮）**: 「继续完善所有主要功能，确保每个功能都不报错，客户端页面都能够正确使用。」
- **全局目标**: 「完成对应的开发，确保稳健可靠好用，顶级。」
- **基线**: 建立在已合入的 11 个里程碑之上（MVP → Phase-2 → Phase-3 → 真实 Agent 执行 → 账号自助中心 → 全局搜索 → @提及自动补全 → 管理台建改闭环 → `reliability-hardening`（第 1 轮）→ `feature-completeness`（第 2 轮）），最新 commit **`de5bd0a`**。
- **技术栈（沿用，零新增运行时依赖）**: Next.js 14 App Router + React 18 + TypeScript + Tailwind + @dnd-kit + SWR ｜ Flask 3 + SQLAlchemy 2 + SQLite + flask-jwt-extended + Flask-CORS。
- **目标读者**: 下游开发工程师（须可据此逐行实现，无需再做架构决策）。
- **审计方法**: **Solution Architect 一手逐文件核验** + **两支只读缺陷审计（后端一支、前端一支）**，全部基于现网 `de5bd0a`。后端审计**实际启动 Flask 应用（`TestConfig` 内存库）逐条复现**了每个 500 / 409 / 数据串档；前端审计逐条给出 `file:line` 与操作步骤，并**主动剔除了 10 条经核验的假阳性**（记于 §9）。第 1、2 轮已修复项已明确排除。
- **评审方法（v2 新增）**: 评审员**独立复跑**了 v1 声称的核心复现（启动 `TestConfig` 应用），确认 P0 断点与 offline `claim-next` 陷阱态属实；并对 v1 的**修复方案本身**做了对抗性核验（「照这份文档实现会发生什么」），发现 1 条 P0 + 5 条 P1。全部证据与修复见下节。

---

## 评审记录（Review Notes）

> 评审人：Subtask #1 · Design Reviewer（Anthropic Engineering）｜ 评审基线：spec v1 + 现网 `de5bd0a`
> 四维：**可行性 / 完备性 / 一致性 / 尺度**。P0/P1 **已在正文就地修复**（下表「已修复」列给出落点）；P2 记录备查。

**总体判断**：v1 的**问题诊断**质量很高——评审员独立复跑确认了 §2.2 的 P0 断点（`assigned→in_development→testing` 后**永久 409**）与 §2.2⑤ 的 offline `claim-next` 陷阱态（**200 认领成功**），二者与文档描述逐字符一致；§9 的假阳性自剔除也经抽样复核属实。问题出在**修复方案的收口完整性**上：v1 把「剩余 500 清零」定义为「URL 路径 + 请求体」两点式，**漏掉了第三条同样会走进 SQLite 绑定的路径——查询串**，而 §2.4 新写的 `project_scope()` 恰好用裸 `int()` 把其中一个 500 **原样带进了新代码**。这一条使本轮自设的硬门槛 D1 不可达，定级 P0。

| # | 维度 | 严重度 | 问题 | 已修复（落点） |
|---|---|---|---|---|
| **R1** | **完备性 / 可行性** | **P0** | **§2.6 的「两点式」收口漏掉查询串整型，§6.3-D1「没有任何一个返回 500」按 v1 设计不可达；且 §2.4 的 `project_scope()` 用裸 `int(raw)`，落地后 `?project_id=<超界>` 仍 500 —— 新代码亲手带进一个 500。** 评审员实机复现（`TestConfig` 内存库 + 有效 JWT）：`?assignee_id=<huge>` → **500**、`?reporter_id=<huge>` → **500**、`?offset=<huge>` → **500**、`GET /api/board/requirements?project_id=<huge>` → **500**、`GET /api/requirements?project_id=<huge>` → **500**（`?limit=<huge>` 安全，已被 `paginate` 钳到 200）。根因：`request.args.get(..., type=int)` 与 `paginate()` 既不经 URL 转换器、也不经 `want_int`，是**第三条独立路径** | §2.6① 升级为**三点式**（新增「修复 C · 查询串侧」）；§2.4① `scope.py` 改为提供通用 `want_query_int()` 并被 `project_scope` / G2 / `paginate` 共用；§4 新增第 ⑫ 行；§6.3 新增 **D3**；§3.2 `test_hardening_r3.py` 新增覆盖点 ⑧ |
| **R2** | **一致性（文档自相矛盾）** | **P1** | §2.2② 的 `maybe_handoff` **代码块本身是错的**——`assignee_type == "user"` 时会直接落进「找对口 Agent 并抢走」的分支；守卫只以散文形式写在代码块**下方**。本文档自述「目标读者须可据此**逐行实现**」，照抄代码块即打破 §6.3-**A3**（「交接不抢人类的单」）这一验收项 | 守卫已**内联进 §2.2② 的代码块本体**，散文降级为强调说明 |
| **R3** | **一致性（CLAUDE.md）/ 完备性** | **P1** | §2.5 把 `project_id` 设计成**默认参数 `=None`**：8 处调用点 + `agent_runner.py` 一份内联副本，**漏传任何一处都不会报错**，而是把该单编进「未归属项目」的号段 → 看板次序静默错乱。唯一护栏是 §6.4 的人工 grep。违反 CLAUDE.md「错误显式传播，不要默默吞异常或返回 `null` 假装一切正常」 | §2.5 改为**必填位置参数**，漏传即 `TypeError`（测试立即变红）；`_reindex_column` 同理（经核验现网两处调用点均以关键字传 `insert_*`，插在第三位安全） |
| **R4** | **一致性（内部冲突）** | **P1** | `/projects` 的 SWR key 在三处相互冲突：§2.4④ 写 `useSWR("/projects", …)`、§7-R7 承诺「与 `projects/page.tsx` 同 key → 零额外请求 + 新建项目后切换器立刻出现新项」、§7-R8/§2.9-G1 又要求消费方**显式传 `?limit=200`**。任何一处改而另一处没改，就同时打破 R7 的两条承诺（变成两次请求 + 新建项目在下拉里看不见） | §2.4④、§2.4⑤、§7-R7、§7-R8 统一改为引用**单一导出常量 `PROJECTS_KEY`**（`lib/api.ts`），并写明「G1 若延后则该常量值不变」的兼容规则 |
| **R5** | **完备性 / 尺度** | **P1** | 本轮的核心主张是「消灭静默说谎的 UI」，但 §2.4 引入的**全局**项目切换器只作用于一部分视图：`/me/work`、`/search`、通知、`recent_activities` / `activities_this_week`、Agents 页均**有意不受控**（§8-4、§8-5、§2.3④）。后端只要求在 docstring 写理由，**前端没有任何可见提示** —— 用户看到 Header 写着「项目 A」，却在同一屏读到全局的活动流与通知。这等于本轮**亲手造出第五处「静默说谎」** | §2.4⑦ 新增「不受作用域约束的视图必须显式标注」一节（仪表盘最近活动卡 / 通知页 / 全局搜索下拉 / Agents 页各加「（全部项目）」小字）；§6.3 新增验收 **C8**；§8-4、§8-5 补「须显式标注」的前提 |
| **R6** | **可行性（欠精确）** | **P1** | §2.6①-B 说「`want_int` **增加** 64 位上下界」，但 `want_int` **现网已有** `minimum` / `maximum` 形参且已被多个调用方传参（`services/validation.py:78-95`）。若下游把 64 位界实现成这两个形参的 **default**，则任何显式传 `maximum=` 的调用方都会**把硬界覆盖掉**，超界 500 依旧存在于那些路径 | §2.6①-B 改写为「硬界与调用方界**并存取交集**、且不经形参暴露」，并钉死 `expected` 串 |
| R7 | 一致性（Windows 约定） | P2 | §6.4 的 grep 复核清单含 **bash-only** 语法：`{requirements,bugs,notifications}` 花括号展开、`\(app\)` 反斜杠转义。CLAUDE.md 明确本项目在 **Windows / PowerShell 5.1** 下工作，这些命令在 PS 下不可执行 → 一份「要求逐条执行并留痕」的 DoD 清单等于没有护栏 | §6.4 已改为逐文件、跨 shell 可执行的形式 |
| R8 | 一致性（文案） | P2 | §2.6①-A 的超界 id → 404 由 Werkzeug 通用 `HTTPException` handler 渲染（`errors.py:20-22`），体为 `{"error":"Not Found"}` —— **英文、非领域文案**，与 §2.8「消灭生硬英文 toast」的取向不完全一致。因该路径不可能由正常 UI 产生（前端只会用列表里回来的真实 id），**接受此取舍**，仅记录 | §2.6①-A 补一句说明，不改设计 |
| R9 | 健壮性（细节） | P2 | §2.8② 的 `key.startsWith("/notifications?limit=50")` 把 `PAGE_SIZE` 常量硬编码进了字符串匹配（改一处则静默失效）；且现网 `hooks/useNotifications.ts` **未 import `globalMutate`**，文档未提 | §2.8② 已改为 `startsWith("/notifications?")` 并补 import 说明 |
| R10 | 完备性 | P2 | §2.2④ 把 `AGENT_CLAIMABLE["generic"]` 清空后，`claim-next` 对 generic Agent 的**返回语义未定义**（`claim_next` 返 `(None, None)` 走哪个分支、前端提示什么），§6.3 也无对应验收 | §2.2④ 已补语义说明与一条验收指引 |
| R11 | 尺度（范围声明） | P2 | 本轮主题是「规模化」，但 `/api/board/*` **无分页、无上限**（`board.py:20` 一次取全表），数据一多看板同样会退化。这属合理取舍（看板语义就是看全列），但 v1 的 §8「有意不做」**没有声明**，会被误读为漏审 | §8 已补第 9 项 |

**未采纳的疑似问题（评审员核验后判为非问题，记录以免下游重复调查）**：

- 「`routes/requirements.py` 顶部 `from services import agent_autopilot` 会循环导入」—— 经核验 `agent_autopilot` 只依赖 `extensions` / `models` / `services`，**无循环**，v1 的判断正确。
- 「`_derive_kind_for_status` 的多解归并逻辑有洞」—— 逐分支推演过：`table[key]` 一旦被置 `None`，后续任何 kind 都会重新命中 `table[key] != kind` 分支并保持 `None`，**收敛正确**；且经现网 `AGENT_FORWARD`（`agent_runner.py:30-51`）核对，§2.2① 给出的 7 行派生表**逐行准确**。
- 「SWR 的 `keepPreviousData` / 函数式 key 过滤需要 SWR 2.x」—— 已核 `frontend/package.json` 为 `swr: ^2.2.5`，**两项均可用**。
- 「`_reindex_column` 插入 `project_id` 作第三位形参会破坏现网调用点」—— 已核现网两处调用均为 `_reindex_column(Model, to, insert_id=…, insert_index=…)`（关键字），**安全**。
- 「§2.7 的 `Activity.query…delete()` 会把同一批 `Activity.log('deleted')` 冲掉」—— v1 已识别并给出「直接删掉该条写入」的推荐解，**无需再改**。

---

## 0. 背景：为什么还需要这一轮

三轮的问题层次是严格递进的：

| 轮次 | slug | 解决 | 本轮是否重复 |
|---|---|---|---|
| 第 1 轮 | `reliability-hardening` | **不崩**：坏输入 500→400、SWR 形状崩溃、永久卡骨架、无效 JWT 422→401 | 否 —— 本轮不改 `validation.py` 的既有行为，只**复用**其 400 契约形状 |
| 第 2 轮 | `feature-completeness` | **跑得通**：dev→qa 交接、默认列表序、401 自动登出、权限门禁 | 否 —— 但发现第 2 轮的交接**只接到了自主编排层，漏了工单级路由**（§2.2），本轮补完 |
| **第 3 轮** | **`scale-and-project-scope`** | **用得上**：数据一多翻得到、项目建了用得上、工单页也推得动 Agent、剩余的真 500 清零 | — |

两轮之后，**单张单、少量数据、单个项目、从 Agents 页发起**的场景确实已经「不报错、跑得通」。第三轮审计（含实机复现）暴露出四类此前**从未被触及**的缺陷：

**① 主流程仍有一处 P0 断点：从工单抽屉推不动 Agent。** 第 2 轮把 dev→qa 交接接在了 `services/agent_autopilot.py:41 _maybe_handoff_to_qa`，调用点只有 `autorun`（`agent_autopilot.py:157,178`）。而**工单级**路由 `routes/requirements.py:421-495 do_agent_advance`（BUG 蓝图经 `bugs.py:27-28` 复用同一函数）**从未调用它**。实机复现：需求指派给 `dev-agent`，反复点抽屉里的「▶ 让 dev-agent 处理下一步」→ `assigned → in_development → testing`，第三次起**永久 409** `{"error":"agent has no action for this state","detail":{"kind":"dev","status":"testing"}}`，抽屉弹红色 toast（`TicketDrawer.tsx:151`），单永远停在 `testing` 且仍挂在 dev-agent 名下。`?run=all` 同病。**净效果：README 宣称的自主闭环只在 Agents 页成立，用户最自然的入口（点开工单、按按钮）是死路。**

同源的还有两个「泊车」缺陷：(a) `AGENT_CLAIMABLE["generic"]` 允许 generic Agent 认领新单（`agent_autopilot.py:33`），但 `AGENT_FORWARD` 里 generic 只有 `assigned` 一条边（`agent_runner.py:40-41,49-50`），推到 `in_development` / `fixing` 后无人接手，而 `assignee_id` 已非空 → **其他 Agent 也不会再认领**，单永久泊死；(b) seed 数据自带一例镜像症状——BUG「看板列计数未实时刷新」是 `fixing` 且挂在 **qa-agent** 名下（`seed.py:92`），qa 在 `fixing` 无动作，而交接只有 dev→qa 单向，**这张演示单从产品出厂第一天起就永远不动**。

**② 列表页在第 51 条之后「看得见、数得到、翻不到」（两支审计独立命中同一处）。** 需求页 `useSWR(listKey, listFetcher)` 请求 `/requirements` **不带任何 `limit`/`offset`**（`requirements/page.tsx:72-73`），后端 `paginate()` 默认 `DEFAULT_LIMIT = 50`（`services/pagination.py:9,22-24`）只返 50 行，而 `X-Total-Count` 返的是**未分页前的真实总数**（`pagination.py:29`）。页面标题因此渲染成「**共 137 条**」（`requirements/page.tsx:109`），表格里却只有 50 行，**且全页没有任何分页控件**。第 51 条起的需求在列表视图**永远无法到达**——而筛选条只存在于列表页、不存在于看板页，所以「筛出来的第 51 条」是彻底不可达的。BUG 页完全同构（`bugs/page.tsx:72-73,109`）；通知页硬编码 `limit=100` 同病（`notifications/page.tsx:27,72`）。

**③ 「项目」整条维度是死的——建了项目，却没有任何地方能用它。** 后端把项目支持做全了：`Requirement.project_id` / `Bug.project_id` 外键（`models/requirement.py:18`）、创建时校验存在性（`requirements.py:186-189`）、列表按 `project_id` 过滤（`requirements.py:145-146`）、看板按 `project_id` 分组（`board.py:18-19,35`）、`useBoard(entity, projectId?)` 连 hook 签名都留好了（`useBoard.ts:12-14`）。**但前端没有任何一处传过它**——`grep -n "project" frontend/components/requirements/RequirementForm.tsx frontend/components/bugs/BugForm.tsx frontend/components/TicketDrawer.tsx "frontend/app/(app)/requirements/board/page.tsx"` **零命中**。后果连锁：(a) 建单表单不含项目字段（`RequirementForm.tsx:48-52` 的 payload 只有 `title/description/priority`），**所有用户新建的单 `project_id` 恒为 `NULL`**；(b) 项目页 `projects/page.tsx:69-80` 的表格行**不可点击、无链接**，是个纯装饰的死胡同，侧边栏却把它作为一级导航（`Sidebar.tsx:66-68`）；(c) 抽屉不显示工单所属项目（`TicketDrawer.tsx:357-365`）。**一个自称「组织团队协作、进行项目开发」的平台，项目是它唯一不能用的一等概念。**

**④ 剩余的真 500、数据串档、以及一批「静默说谎」的页面。** 实机复现的 500：`GET /api/requirements/99999999999999999999` → **500**（`OverflowError: Python int too large to convert to SQLite INTEGER`，六个 `<int:id>` 路由 + 三个请求体 id 字段全中）；`POST /api/projects {"description":{"a":1}}` → **500**（四处漏掉 `want_str` 的 `description`）。数据串档：删除工单只删评论与通知、**不删审计**（`requirements.py:255-262`），而 SQLite 复用主键，于是新建的下一张单**继承了上一张被删单的完整时间线**——`GET /api/requirements/1/feed` 会把已删单的标题原样吐给另一个用户看，既是错数据也是信息泄露。前端侧四处「静默说谎」：看板拖拽**未做 RBAC 门禁**，member 拖别人的卡会看到一句生硬的英文 toast `forbidden`（`useBoard.ts:85`）；铃铛「全部已读」不失效通知页的 SWR key，页面上每一行仍显示未读（`useNotifications.ts:29-42` vs `notifications/page.tsx:27`）；铃铛下拉在请求失败时**永久转圈**（`useNotifications.ts:47` 从不返回 `error`）；通知偏好卡在 GET 失败时把六个开关**全画成「开」并全部锁死**，用户会确信通知都开着（`NotificationPrefsCard.tsx:40,51`）。

四类缺陷共享一个根因：**平台的功能面是按「演示数据量、单项目、从 Agents 页发起、后端永远正常」造的，从未按「真实规模、多项目、从工单页发起、后端会出错」验收过。** 本轮就做这一件事。范围克制、**零新表、零新运行时依赖、成功路径响应 shape 不变**。

---

## 1. Overview（概述）

**本轮主题是「规模、维度、入口、诚实」：让列表在数据变多时仍然可达，让项目这一维度从数据库一路贯通到每一个页面，让工单页和 Agents 页拥有同样完整的 Agent 闭环，让剩下的每一个 500 与每一处「静默说谎」的 UI 归零。**

它不发明新业务概念——分页能力后端早已具备（`paginate` + `X-Total-Count` + CORS `expose_headers`，`app.py:30`），项目外键与过滤后端也早已具备，dev→qa 交接第 2 轮已经写好；本轮做的是把这些**只差最后一公里**的能力接完，并把审计实机复现出的 500 与数据串档收口。

五条主线：

- **后端 A · 补完 Agent 交接，并把它从「dev→qa 单向」泛化为「按状态找对的 kind」**（§2.2）。把 `_maybe_handoff_to_qa` 升为公开的 `maybe_handoff`，其目标 kind **不再硬编码，而是从 `agent_runner.AGENT_FORWARD` 的键集派生**（单一真相，零漂移）；然后接进工单级 `do_agent_advance` 与 `_agent_run_all`。一处泛化同时解决 P0 断点、generic 泊车、seed 卡死三个症状，且**对第 2 轮已有的 dev→qa 行为逐字节等价**。
- **前端 B · 分页可用性**（§2.3）。新增一个**无状态、纯展示**的 `Pagination` 原语，接到需求页、BUG 页、通知页。列表 SWR key 显式带上 `limit`/`offset`，筛选变化时归零 offset，配合 `keepPreviousData` 消除翻页闪烁。**后端一行不改**。
- **前后端 C · 项目维度贯通**（§2.4 + §2.5）。新增全局 `ProjectScopeProvider`（`localStorage` 持久化，`null`=全部、`"none"`=未归属）与 Header 项目切换器，接到列表 / 看板 / 仪表盘 / 建单表单 / 抽屉 / 项目页；后端抽出共享 `services/scope.py` 统一 `?project_id=` 语义，`/stats` 支持项目过滤且 `_by_status` 改 SQL `GROUP BY`。**并必须同时修复 `_next_position` / `_reindex_column` 不含项目导致的看板重排失效**（§2.5）——这是引入项目过滤后**当场就会触发**的缺陷，不是可选项。
- **后端 D · 剩余 500 与数据串档清零**（§2.6 + §2.7）。超界整型**三点式**收口（URL 转换器上界 → 404；`want_int` 硬界 → 400；**查询串 `want_query_int` → 400**——第三点为**评审 R1 补入**，v1 遗漏且新代码会把该 500 带进来）；四处 `description` 补 `want_str`；删单一并删审计，堵住 SQLite 主键复用导致的时间线串档。
- **前端 E · 消灭「静默说谎」的 UI**（§2.8 + §2.9）。看板拖拽 RBAC 门禁（并抽出与后端同判据的 `canManageTicket`）、铃铛与通知页双向同步、铃铛与偏好卡的错误态、以及一批低风险机械加固。

**关键不变量（下游必须保持，任何实现都不得违反）**：

1. **状态机仍是圣域**（`CLAUDE.md`「State machine is sacred」）。本轮**不新增、不修改任何迁移边**。`maybe_handoff` 与第 2 轮的 `_maybe_handoff_to_qa` 一样**只改多态 assignee（`assignee_type`/`assignee_id`），绝不触碰 `status`**；所有推进仍经 `agent_runner.advance_one → workflow.can_transition`。项目过滤只加 `WHERE`，分页只加 `LIMIT/OFFSET`。
2. **向后兼容**。不新增数据库表（延续「唯一新表是 Phase-3 `notifications`」）、不新增前后端运行时依赖、**不改动任何成功路径的响应 shape**（§2.2 的交接刻意设计成「重试一次后返回与今天完全相同的 200 体」，正是为了守住这条）。
3. **不过度设计**。只补审计实机复现的真实缺口。新增文件 5 个（2 个后端、3 个前端），其余全是就地增量。**明确不做**的 8 项及理由见 §8。

---

## 2. Technical Design（技术设计）

### 2.1 架构增量（Delta）

```
后端
  services/agent_autopilot.py
    _maybe_handoff_to_qa  ──►  maybe_handoff(entity, ticket)        【公开 + 泛化】
                                 └─ 目标 kind 由 AGENT_FORWARD 键集派生（_KIND_FOR_STATUS）
                                    ▲ 调用方：autorun ×2（既有）+ do_agent_advance ×2（新增）
  services/scope.py  【新增】 want_query_int() ★ / project_scope() / apply_project_filter()
                                    ▲ 调用方：requirements / bugs / board / stats / pagination ★
  errors.py          注册 QueryParamError → 400 全局处理器 ★（与既有 ValidationError 同构）
  app.py             BoundedIntConverter 覆盖 url_map.converters["int"]  → 超界 id 走 404 而非 500
  services/validation.py   want_int 加**无条件** 64 位硬界 → 超界走 400 而非 500

  ★ = 评审 R1（P0）新增：「超界整型 → 500」的第三条路径（查询串）收口，
      v1 的两点式漏掉了它，且 v1 版 project_scope() 会把该 500 带进新代码。

前端
  lib/project-scope.tsx     【新增】ProjectScopeProvider / useProjectScope()
  lib/permissions.ts        【新增】canManageTicket(user, ticket)  ← 与后端 can_manage_ticket 同判据
  components/ui/Pagination.tsx        【新增】受控分页条
  components/layout/ProjectSwitcher.tsx【新增】Header 项目下拉
        │
        ├─► 需求/BUG 列表页：+ limit/offset + project_id + <Pagination>
        ├─► 两个看板页：useBoard(entity, scope)；KanbanCard 按 canManageTicket 禁用拖拽
        ├─► 仪表盘：/stats?project_id=
        ├─► 两个建单表单：项目 Select（默认继承 scope）
        ├─► 工单抽屉：显示所属项目；canManage 改用 lib/permissions
        └─► 项目页：行可点击 → 切 scope + 跳转
```

新增 5 个文件、修改 ~24 个文件（评审后 `errors.py`、`pagination.py` 加入修改集），**无新表、无新依赖、无状态机改动**。

---

### 2.2 后端 A【P0】：补完工单级 Agent 交接，并把交接泛化为「按状态找对的 kind」

**缺陷复现（实机验证）**：`pm` 登录 → 把一条需求指派给 `dev-agent` → 打开抽屉，连点「▶ 让 dev-agent 处理下一步」。**预期**：一路推到 `reviewing`（待人工审批）。**实际**：`assigned → in_development → testing` 之后**每次都 409**，红色 toast，单永久挂在 dev-agent 的 `testing`。

**根因**：第 2 轮的交接 helper 只接进了 `agent_autopilot.autorun`，工单级 `do_agent_advance` / `_agent_run_all` 从未调用。同时该 helper 硬编码了 `_QA_HANDOFF_STATUS = {"requirement":"testing","bug":"verifying"}`，是**单向的 dev→qa**，因此 generic Agent 泊在 `in_development`、seed 的 qa-agent 泊在 `fixing`，都无解。

#### ① 泛化：目标 kind 从 `AGENT_FORWARD` 派生（`services/agent_autopilot.py`）

删除 `_QA_HANDOFF_STATUS`（行 37-38），改为在模块顶部由 `agent_runner.AGENT_FORWARD` 的**键集**派生：

```python
def _derive_kind_for_status() -> dict[tuple[str, str], str | None]:
    """由 AGENT_FORWARD 键集派生「(entity, status) → 唯一能处理它的 agent kind」。

    单一真相：交接目标不另立一张会漂移的表，直接从推进表反推。
    某状态若有 **多种** kind 都能处理（如 assigned 兼容 dev / generic），映射为 None
    ——多解即不自动交接，避免抢走 generic 自己能干的活。
    """
    table: dict[tuple[str, str], str | None] = {}
    for entity, kind, status in agent_runner.AGENT_FORWARD:
        key = (entity, status)
        if key in table and table[key] != kind:
            table[key] = None          # 多解 → 不交接
        else:
            table.setdefault(key, kind)
    return table


_KIND_FOR_STATUS = _derive_kind_for_status()
```

以现网 `AGENT_FORWARD`（`agent_runner.py:30-51`）派生出的表**必须**是（实现者可据此写断言）：

| (entity, status) | 派生 kind | 说明 |
|---|---|---|
| `("requirement","assigned")` | `None` | dev / generic 皆可 → 不交接 |
| `("requirement","in_development")` | `dev` | **新增能力**：修 generic 泊车 |
| `("requirement","bug_fixing")` | `dev` | 新增能力 |
| `("requirement","testing")` | `qa` | **与第 2 轮完全一致** |
| `("bug","assigned")` | `None` | dev / generic 皆可 |
| `("bug","fixing")` | `dev` | **新增能力**：修 seed 卡死单 |
| `("bug","verifying")` | `qa` | **与第 2 轮完全一致** |

#### ② `_maybe_handoff_to_qa` → `maybe_handoff`（公开、语义为严格超集）

保留原函数体的全部安全性质，只替换「目标 kind」的来源：

```python
def maybe_handoff(entity, ticket):
    """当前 assignee 的 kind 与该状态所需 kind 不符时，重指派给一个可用的对口 Agent。

    **不 commit、不改状态**——只改多态 assignee（assignee_type='agent' + assignee_id）。
    状态迁移已由 advance_one 合法完成，本函数绝不触碰 status/position（不绕过状态机）。
    无对口 / 无可用 Agent / 已是对口 kind / 该状态多解 / **单在人类手里** → 一律 no-op 返回 None。
    返回被交接到的 Agent 或 None。
    """
    need = _KIND_FOR_STATUS.get((entity, ticket.status))
    if need is None:
        return None
    # 【评审 R2 · 必须在最前】交接只在 Agent 之间发生，绝不从人手里抢单。
    # 现网 _maybe_handoff_to_qa 因只在 Agent 推进后调用而侥幸不暴露此问题；泛化后
    # 调用点增多（工单级路由、run=all 的 NoAgentAction 分支），此守卫为**必须**。
    # 缺了它，§6.3-A3「把 testing 需求指派给人类 alice → autorun-all 后仍在 alice 名下」
    # 这条验收会直接失败。
    if ticket.assignee_type != "agent" or ticket.assignee_id is None:
        return None
    cur = db.session.get(Agent, ticket.assignee_id)
    if cur is not None and cur.kind == need:
        return None
    target = Agent.query.filter_by(kind=need).filter(Agent.status != "offline")\
        .order_by(Agent.id.asc()).first()
    if target is None:
        return None
    ticket.assignee_type = "agent"
    ticket.assignee_id = target.id
    Activity.log(
        entity, ticket.id, "assigned", actor=("agent", target.id),
        from_status=ticket.status, to_status=ticket.status,
        message=f"{target.name} 接手{_label(entity)}「{ticket.title}」继续处理",
    )
    # 【第 2 轮评审 R1，务必保留】通知源单 reporter（人类）：必须用 notify_claim
    # （收件人=reporter、type="assigned"）。**绝不**用 notify_assignment——它仅通知人类
    # assignee，而此刻 assignee 已是 Agent，会被 notifications.py 静默丢弃。
    notifications.notify_claim(ticket, entity, target)
    return target
```

**关键约束（实现者必须逐条守住）**：
- **不得**交接给 `offline` Agent（`.filter(Agent.status != "offline")` 原样保留）。
- **不得**在 assignee 是**人类**时交接 —— 见上方代码块开头的守卫（**评审 R2 已内联，不得删除或下移**）。守卫必须在 `db.session.get(Agent, …)` **之前**：assignee 是人类时 `assignee_id` 指向的是 `users.id`，若先去 `Agent` 表取，会取到一个**同 id 的不相干 Agent**，判据随即失真。
- 同步更新 `agent_autopilot.py:157` 与 `:178` 两处调用点为 `maybe_handoff`。
- 语义为现网 `_maybe_handoff_to_qa` 的**严格超集**：dev→qa 的既有行为逐字节不变（`_KIND_FOR_STATUS` 在 `testing`/`verifying` 上的取值与旧硬编码表一致，且旧函数在人类持单时同样走不到抢单分支——它的 `status` 前置判据加上「只在 Agent 推进后调用」共同挡住了）。

#### ③ 接进工单级路由（`routes/requirements.py::do_agent_advance` / `_agent_run_all`）

`requirements.py` 顶部补 `from services import agent_autopilot`（`agent_autopilot` 只依赖 services/models，**不依赖 routes，无循环导入**）。

**单步分支**（`do_agent_advance`，约行 441-460）——两处接线，**响应 shape 保持不变**：

```python
    frm = ticket.status
    try:
        to, comment, activity = agent_runner.advance_one(entity, ticket, agent)
    except agent_runner.NoAgentAction as e:
        # 【§2.2】本 Agent 无动作时，先尝试交接给对口 Agent 再重试一次；
        # 这样存量卡死单（generic@in_development、seed 的 qa@fixing）一次点击即可复活。
        handed = agent_autopilot.maybe_handoff(entity, ticket)
        if handed is None:
            return jsonify({"error": "agent has no action for this state",
                            "detail": {"kind": e.kind, "status": e.status}}), 409
        db.session.commit()          # 交接本身即为可持久化的进展
        agent = handed
        try:
            to, comment, activity = agent_runner.advance_one(entity, ticket, agent)
        except agent_runner.NoAgentAction as e2:
            # 交接已落库（净进展），但新 Agent 仍无动作 → 仍返 409，契约不变。
            return jsonify({"error": "agent has no action for this state",
                            "detail": {"kind": e2.kind, "status": e2.status}}), 409
    db.session.commit()
    notifications.notify_advance(ticket, entity, actor=("agent", agent.id),
                                 from_status=frm, to_status=to)
    db.session.commit()
    # —— 推进成功后即时交接，使下一次点击由对口 Agent 接力（与 autopilot 同策略）——
    if agent_autopilot.maybe_handoff(entity, ticket) is not None:
        db.session.commit()
    return jsonify({
        "ticket": ticket.to_dict(),
        "comment": comment.to_dict(),
        "agent": agent.to_dict(),
    }), 200
```

> **重试至多一次**（无循环）。`agent` 变量被重绑定后，响应里的 `agent` 字段即执行本步的那个 Agent —— 语义正确且 shape 不变。

**`run=all` 分支**（`_agent_run_all`）——在 `except NoAgentAction: break` 之前与每步成功之后各插一次交接，且**交接后 `break`**：

```python
            except agent_runner.NoAgentAction:
                if agent_autopilot.maybe_handoff(entity, ticket) is not None:
                    db.session.commit()
                break
            ...
            if workflow.is_terminal(entity, ticket.status):
                break
            if agent_autopilot.maybe_handoff(entity, ticket) is not None:
                db.session.commit()
                break      # 已易主：本次 run 的 busy 软锁只覆盖原 agent，不越界替新 agent 跑
```

> **为什么交接后必须 `break` 而不是继续循环**：`_agent_run_all` 的 busy 软锁 `prev = agent.status` 只锁住**原** Agent，`finally` 也只恢复它。若换人后继续跑，新 Agent 未被加锁，会与 `/autorun` 并发撞车。**保持与 `agent_autopilot.autorun`（行 160、181）完全一致的「交接即 break」策略**，由下一次调用接力。

#### ④ generic Agent 不再主动认领（`agent_autopilot.py:31-35`）

把 `AGENT_CLAIMABLE["generic"]` 改为 `[]`（与 `"qa": []` 同理）。**理由**：`generic` 在 `AGENT_FORWARD` 里只有 `assigned` 一条边，认领后必然在下一状态无动作。泛化交接虽已能把它救出来，但让一个「没有完整泳道」的 Agent 去抢分诊阶段的新单本身就是错的编排——generic Agent 仍可被 pm **显式指派**并推进一步，能力不减。

> 该改动会影响既有断言，实现者**必须**先 `grep -n "generic" backend/tests/` 核对 `test_agent_autopilot.py`，按新语义更新（而非删除）相关用例。

> **【评审 R10 · P2】须同时钉死 `claim-next` 对 generic Agent 的返回语义**（v1 未定义）：`claim_next` 返 `(None, None)` 时走的是 `routes/agents.py` 既有的「无可认领」分支，**响应码与体保持现网不变**（本轮不改）。实现者须在 `claim_next` 的 docstring 里写明「`generic` 自 §2.2④ 起不参与自主认领，故对 generic Agent 恒走该分支」，并在 `test_agent_autopilot.py` 补一条断言锁死此语义。产品侧影响：generic Agent 仍可被 pm **显式指派**、推进一步，随后由 §2.2① 的泛化交接转给对口 kind —— 即 generic 的定位从「自主劳力」收窄为「人工分诊后的通用起手」，须在 `README.md` 的 Agent 说明里同步一句。

#### ⑤ `claim-next` 补 busy/offline 门禁（`routes/agents.py:134-144`）

实机复现：`PATCH /api/agents/1 {"status":"offline"}` → `POST /api/agents/1/claim-next {}` → **200，offline Agent 认领成功**；紧接着 `POST /api/agents/1/autorun` → 409「agent is busy or offline」。**离线 Agent 把单吞了又拒绝干活**，是个纯陷阱态。按 `autorun-all`（`agents.py:119`）同款门禁补上：

```python
    if agent.status in ("busy", "offline"):
        return jsonify({"error": "agent is busy or offline"}), 409
```

> **有意不改**：单步 `agent-advance`（非 `run=all`）**仍不设 offline 门禁**——这是第 2 轮评审 R5 的显式裁定（pm/admin 的手动单步操作，人已经知道自己在做什么）。`claim-next` 之所以要门禁，是因为它是**自主认领**语义且会产生「吞了又不干」的陷阱态，二者不矛盾。此裁定须原样写进 `claim_next` 的 docstring。

---

### 2.3 前端 B【P0】：列表分页可用性

**缺陷复现**：`pm` 登录 → 造 ≥ 60 条需求 → 打开 `/requirements`。**预期**：能浏览到全部 60 条。**实际**：标题「共 60 条」，表格 50 行，页面底部空无一物，第 51–60 条不可达。BUG 页、通知页同构。

#### ① 新增纯展示原语 `frontend/components/ui/Pagination.tsx`

```tsx
interface Props {
  offset: number;                 // 当前页首条下标（0 基）
  limit: number;                  // 每页条数
  total: number;                  // 后端 X-Total-Count（未分页前总数）
  onOffset: (next: number) => void;
  disabled?: boolean;             // 取数中禁用，防连点越界
}
```

- **`total <= limit` 时 `return null`**（不渲染）——保证小数据量下页面观感与今天**完全一致**，这是「零视觉回归」的硬约束。
- 文案：`第 {offset + 1}–{Math.min(offset + limit, total)} 条 / 共 {total} 条`。
- 两个 `<Button variant="ghost" size="sm">`：`上一页`（`offset <= 0` 时 `disabled`；点击 `onOffset(Math.max(0, offset - limit))`）、`下一页`（`offset + limit >= total` 时 `disabled`；点击 `onOffset(offset + limit)`）。
- 容器 `flex items-center justify-between border-t border-border px-4 py-3 text-sm text-ink-muted`，置于表格容器**内部底端**。
- 受控、无 state、无副作用，行数 < 50、圈复杂度 < 5（符合 `CLAUDE.md` 阈值）。

#### ② 需求页 / BUG 页接线（`requirements/page.tsx`、`bugs/page.tsx`，两文件同构）

```tsx
const PAGE_SIZE = 50;              // 与后端 pagination.DEFAULT_LIMIT 对齐，便于对照排查
const [offset, setOffset] = useState(0);

// …既有 params 构造之后、组 key 之前追加：
if (scopeParam) params.set("project_id", scopeParam);   // §2.4
params.set("limit", String(PAGE_SIZE));
params.set("offset", String(offset));

const listKey = `/requirements?${params.toString()}`;
const { data, error, mutate } = useSWR(listKey, listFetcher<Requirement>, {
  keepPreviousData: true,          // 翻页保留上一页数据，消除骨架闪烁
});
```

三条**必须实现**的守卫：

```tsx
// (a) 任一筛选条件（含项目作用域）变化 → 回第一页。否则「筛出 3 条却停在 offset=50」→ 空表误读。
const filterSignature =
  `${debounced}|${status}|${priority}|${assignee.assignee_type}|${assignee.assignee_id}|${scopeParam}`;
useEffect(() => { setOffset(0); }, [filterSignature]);

// (b) 越界自愈：他人删单致 total 缩小、或刷新到深页。
useEffect(() => {
  if (data && offset > 0 && offset >= data.total) setOffset(0);
}, [data, offset]);
```

- (c) **空态判据保持原样**（`reqs.length === 0`）。守卫 (b) 会把越界 offset 拉回 0 并重取；实现者**不得**把 `EmptyState` 的判据改成含 offset 的复合条件（会引入闪烁）。
- `<Pagination>` 渲染在 `</table>` 之后、包裹表格的 `div.overflow-hidden` 之内，仅在 `reqs && reqs.length > 0` 分支渲染，`disabled={!data}`。
- `Header` 的 `subtitle`（`共 ${data.total} 条`）**不改**——它此前是谎言，接上分页后成为事实。

#### ③ 通知页接线（`notifications/page.tsx`）

同构，`PAGE_SIZE = 50`，key 变为 `/notifications?limit=50&offset=${offset}`。

> **必须注意**：`syncBell()`（`notifications/page.tsx:31-36`）里的 `globalMutate("/notifications?limit=15")` 是**铃铛的字面 key**（`useNotifications.ts:20`），与本页 key 无关，**原样保留不得改动**。反向同步见 §2.8-②。

#### ④ Agents 页（有意不改，须记录）

`agents/page.tsx:42-44` 以 `limit=200`（= 后端 `MAX_LIMIT`）拉「指派给 Agent 的在制单」，只为算负载计数 `load.total`，不是可浏览列表。本轮**有意不改**：为一个计数引入分页 UI 属过度设计。风险与正解见 §7-R4。

---

### 2.4 前后端 C【P1】：项目维度端到端贯通

**缺陷复现**：`pm` 登录 → 侧边栏点「项目」→ 看到 seed 项目 `ARA / AragonTeam Platform` → **点击任意一行，什么也不会发生** → 回需求页新建一条需求 → 该需求 `project_id` 为 `NULL` → 打开抽屉，**看不到任何项目信息**。

#### ① 新增 `backend/services/scope.py`

> **【评审 R1 · P0】本模块的职责比 v1 大一档**：它同时是**查询串整型的唯一入口**。原因见 §2.6①-C —— 查询串是除「URL 路径」「请求体」之外的**第三条**会把 Python 大整数直接绑进 SQLite 的路径，v1 的两点式没有覆盖它，而 v1 版 `project_scope()` 的裸 `int(raw)` 会把 `?project_id=<超界>` 的 500 **原样带进新代码**。因此 `want_query_int` 必须先落地，`project_scope` 建在它之上，§2.9-G2 的 `assignee_id`/`reporter_id` 与 `pagination.paginate` 的 `limit`/`offset` 也全部改走它（这同时兑现了 G2「不得写三份」的要求）。

```python
"""查询串整型边界 + 项目作用域过滤（scale-and-project-scope §2.4 / §2.6①-C）。

【为什么在这里】`services/validation.py` 管的是**请求体**（已归一为 dict 的字段），
`app.py::BoundedIntConverter` 管的是**URL 路径**。查询串是第三条独立路径：
`request.args.get(k, type=int)` 会把任意长度的十进制串解析成 Python 大整数，随后
`filter_by(...)` / `.offset(...)` 把它绑进 SQLite，触
`OverflowError: Python int too large to convert to SQLite INTEGER` → 500（实机复现见 §2.6①-C）。
本模块把「取一个查询串整数」收敛为一处带 64 位钳制的边界函数。

契约：`?project_id=` 缺省 / 空串 = 不过滤；整数 = 该项目；字面量 `none` = 未归属
（`project_id IS NULL`）；其余取值（含超界整数）= 400（沿用前两轮「坏输入一律 400」的既定契约）。
"""
from flask import request, jsonify

UNASSIGNED = "none"

# SQLite / 多数 RDBMS 的 INTEGER 值域（64 位有符号）。与 app.py::MAX_DB_INT 同一常量语义，
# 但**有意各自定义**：app.py 属应用装配层，services 不反向依赖它（避免 service→app 依赖倒置）。
MIN_DB_INT = -(2 ** 63)
MAX_DB_INT = 2 ** 63 - 1


class QueryParamError(Exception):
    """查询串参数取值非法（类型错 / 超界）；由调用方转成 400 响应。

    稳定异常类，勿更名（对外错误契约，CLAUDE.md §五）。
    """

    def __init__(self, field: str, got, expected: str):
        super().__init__(f"invalid {field}")
        self.field = field
        self.got = got
        self.expected = expected


# 【向后兼容别名】v1 文档与早期草稿用的名字；保留以免下游按旧名 import。
ProjectScopeError = QueryParamError


def want_query_int(field: str, *, default=None, minimum=None, maximum=None):
    """从查询串取一个整数，缺省返回 default；非法 / 超 64 位一律抛 QueryParamError（→ 400）。

    Args:
        field: 查询串参数名（同时用作错误体的 detail.field）。
        default: 参数缺省 / 空串时的返回值。
        minimum / maximum: 调用方附加界；**与 64 位硬界取交集**，不得放宽它。

    Raises:
        QueryParamError: 非十进制整数、或落在 [MIN_DB_INT, MAX_DB_INT] 之外、或越调用方界。
    """
    raw = request.args.get(field)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise QueryParamError(field, raw, "integer")
    # 硬界优先：超出 64 位的值不可能命中任何主键，也不能被绑进 SQLite。
    if value < MIN_DB_INT or value > MAX_DB_INT:
        raise QueryParamError(field, raw, "integer within 64-bit range")
    lo = MIN_DB_INT if minimum is None else max(minimum, MIN_DB_INT)
    hi = MAX_DB_INT if maximum is None else min(maximum, MAX_DB_INT)
    if value < lo or value > hi:
        raise QueryParamError(field, raw, f"integer in [{lo}, {hi}]")
    return value


def project_scope():
    """解析 `?project_id=`。返回 None（不过滤）/ UNASSIGNED / int。非法值抛 QueryParamError。"""
    if request.args.get("project_id") == UNASSIGNED:
        return UNASSIGNED
    return want_query_int("project_id")


def apply_project_filter(query, model, scope):
    """把 project_scope() 的结果套到 query 上；scope 为 None 时原样返回。"""
    if scope is None:
        return query
    if scope == UNASSIGNED:
        return query.filter(model.project_id.is_(None))
    return query.filter(model.project_id == scope)


def query_error_response(exc: QueryParamError):
    """统一 400 响应体，与既有 validation 错误契约（{error, detail:{field, expected}}）同形。"""
    return jsonify({
        "error": f"invalid {exc.field}",
        "detail": {"field": exc.field, "expected": exc.expected, "got": str(exc.got)},
    }), 400


# 【向后兼容别名】同上。
scope_error_response = query_error_response
```

> **稳定错误串**：`project_id` 非法时的 `"invalid project_id"` 与 §4-③ 承诺的体**逐字段一致**（`expected` 在「非整数」时为 `"integer"`、在「超界」时为 `"integer within 64-bit range"`；`none` 是合法值，故 `expected` 不再写 `"integer or 'none'"` —— 只有走到 `want_query_int` 的值才会报错，而 `none` 在此之前已被拦下）。按 `CLAUDE.md`「对外暴露的错误码必须稳定」，这些串一经落地不得更名。
>
> **`paginate` 接线（R1 收口的一部分）**：`services/pagination.py:19-20` 的两行 `request.args.get(…, type=int)` 改为 `want_query_int("limit")` / `want_query_int("offset", minimum=0)`。**既有钳制语义不变**（`limit` 仍钳到 `[1,200]`）；`offset` 为负此前被静默归零、现在改为 400，属与 §4-③ 同批的行为收紧，须一并写进 §4-⑫。

#### ①' 全局错误处理器接线（**评审 R1 要求，取代 v1 的逐路由 `try/except`**）

`QueryParamError` **必须**在 `backend/errors.py::register_error_handlers` 内注册全局处理器，与既有 `ValidationError` 的处理**逐行同构**（`errors.py:24-30`）：

```python
    from services.scope import QueryParamError

    # 【§2.4 / 评审 R1】查询串边界失败统一 400，与 ValidationError 同一档次的边界契约。
    @app.errorhandler(QueryParamError)
    def handle_query_param_error(e: QueryParamError):
        return jsonify({
            "error": f"invalid {e.field}",
            "detail": {"field": e.field, "expected": e.expected, "got": str(e.got)},
        }), 400
```

**为什么必须走全局处理器，而不是 v1 设计的「四个端点各加 `try/except`」**：`paginate()` 被**每一个**列表端点调用（需求 / BUG / 通知 / 搜索 / 评论 / 用户 / Agent / 项目…），逐路由 `try/except` 一旦漏掉一处，该处的超界 `?offset=` 就**仍然 500** —— 那正是本轮要清零的东西，却把「是否清零」寄托在人工穷举上。全局处理器把这一整类失败模式一次性消灭，且与仓库既有约定一致。`query_error_response()` 仍保留，供确实需要在路由内提前返回的场景使用（本轮无）。

#### ② 四个端点接线

> **【评审 R1】以下接线一律**不写** `try/except` —— `QueryParamError` 由 §2.4①' 的全局处理器统一转 400。这既少写四份重复代码，也杜绝「漏写一处 → 该处仍 500」。

- `routes/requirements.py::list_requirements`（行 136-146）：删掉 `project_id = request.args.get("project_id", type=int)` 与其 `filter_by`，改为
  ```python
  q = apply_project_filter(Requirement.query, Requirement, project_scope())
  ```
  其余过滤（`status`/`assignee_*`/`priority`/`reporter_id`/`q`）、排序、`paginate` **一字不动**（`assignee_id` / `reporter_id` 的整数解析按 §2.9-G2 改走 `want_query_int`）。
- `routes/bugs.py::list_bugs`：同构（`severity` 替 `priority`）。
- `routes/board.py`：`_grouped(model, entity, scope)` 第三参改名，内部 `q = apply_project_filter(model.query, model, scope)`；两个视图函数把 `request.args.get("project_id", type=int)` 换成 `project_scope()`。
- `routes/stats.py`：见 ③。

#### ③ `/stats` 项目过滤 + `_by_status` 改 GROUP BY

现网 `stats.py:22-26` 把**每一行的状态**取回 Python 再逐条累加（`db.session.query(model.status).all()`），单量上万即 O(N) 内存与传输。改为一次聚合：

```python
def _by_status(model, entity, scope):
    """按状态计数。以 SQL GROUP BY 聚合（此前逐行取回 Python 累加，单量上万即 O(N) 内存）。"""
    counts = {key: 0 for key in workflow.column_keys(entity)}
    q = apply_project_filter(
        db.session.query(model.status, func.count(model.id)), model, scope
    ).group_by(model.status)
    for status, n in q.all():
        # 列集合外的历史状态容错入表（与 board.py:25 的 setdefault 同策略）。
        counts[status] = counts.get(status, 0) + n
    return counts
```

`stats()` 开头解析 scope（`try/except` → 400），传给两个 `_by_status`，并把 `requirements.total` / `bugs.total` 由 `Model.query.count()` 改为 `apply_project_filter(Model.query, Model, scope).count()`。

**有意保持全局、不随项目过滤的字段**（须在 docstring 写明理由）：`agents.*`（Agent 是**全局共享的执行者**，不隶属项目）、`members`（全局账号）、`activities_this_week` 与 `recent_activities`（`Activity` 表**没有 `project_id` 列**，按项目过滤需连表回查且要分别处理两种 `entity_type`，属过度设计 → §8）。**响应体键集完全不变**，前端 `lib/types.ts:172-179` 的 `Stats` 类型无需改动。

#### ④ 新增 `frontend/lib/project-scope.tsx`

```tsx
export type ProjectScope = number | "none" | null;   // 具体项目 | 未归属 | 全部项目

interface ProjectScopeValue {
  scope: ProjectScope;
  setScope: (next: ProjectScope) => void;
  scopeParam: string;              // 可直接拼进 query；scope 为 null 时返回 ""
  projects: Project[] | undefined;
  isLoading: boolean;
  error: unknown;
}
```

- Provider 内 `useSWR<Project[]>(PROJECTS_KEY, swrFetcher)`，与 `projects/page.tsx:20` **同 key 同 fetcher** → SWR 自动共享缓存，**零额外请求**。

  > **【评审 R4 · P1】`/projects` 的 key 必须是唯一的导出常量，不得在任何一处写字面量。**
  > v1 在三处给出了**互相冲突**的写法：§2.4④ 写 `"/projects"`、§7-R7 承诺「与 `projects/page.tsx` 同 key」、§7-R8 / §2.9-G1 又要求消费方显式传 `?limit=200`。三处只要有一处改了另一处没改，就会**同时**打破 R7 的两条承诺——变成两次请求，且**新建项目后切换器下拉里看不到它**（两份缓存互不失效）。
  > 落地方式：在 `frontend/lib/api.ts` 导出
  > ```ts
  > /** `/projects` 的唯一 SWR key。ProjectScopeProvider 与 projects 页必须共用它，
  >  *  否则两份缓存互不失效：新建项目后切换器下拉里看不到它（评审 R4）。 */
  > export const PROJECTS_KEY = "/projects";
  > ```
  > 并让 `lib/project-scope.tsx`、`app/(app)/projects/page.tsx` **一律 import 它**。
  > **与 §2.9-G1 的兼容规则**：G1 若落地（给 `/projects` 加 `paginate`），只需把该常量改成 `"/projects?limit=200"` **一处**，两个消费方自动同步；G1 若按 §7-R8 建议延后，常量值保持 `"/projects"` 不变。**两种情况下都不需要改任何消费点**——这正是引入常量的目的。
- 持久化：`localStorage` key **`aragon.project`**。**读取必须在 `useEffect` 内**（在 `useState` 初始化函数里读会造成 SSR/首屏 hydration mismatch，见 §7-R3）；初值恒为 `null`。写入在 `setScope` 内同步进行。
- **失效自愈**：`projects` 到达后，若 `scope` 是数字且不在 `projects` 中（项目被删 / 换库 / 换环境），**静默回落 `null` 并清除 localStorage**。这是防「选了个不存在的项目 → 每页都空」的关键守卫。
- `scopeParam = scope === null ? "" : String(scope)`。

#### ⑤ 新增 `frontend/components/layout/ProjectSwitcher.tsx`

- 原生 `<select>`，复用 `FilterBar.tsx:42-43` 的 `selectCls` 样式（零新依赖），`aria-label="切换项目"`。
- 选项：`全部项目`（value `""`）· `未归属项目`（value `none`）· 每个项目 `{key} · {name}`（value = id）。
- `projects` 未到达或 `error` 时渲染 `disabled` 占位 `<select>`，**不渲染 skeleton**（Header 高度固定 `h-16`，避免布局跳动）；项目列表拉不到不得阻断整个 Header。

#### ⑥ 挂载点

- `frontend/app/(app)/layout.tsx`：在**鉴权守卫之后**（`if (loading || !user) return …` 之后）用 `<ProjectScopeProvider>` 包住返回的 `<div className="flex h-screen …">` —— 放在守卫之后可保证 `/projects` 请求必然携带有效 JWT。
- `frontend/components/layout/Header.tsx`：在 `<GlobalSearch />` **之前**（行 46 前）插入 `<ProjectSwitcher />`，阅读顺序为「项目 → 搜索 → 页面动作 → 通知 → 头像」。

#### ⑦ 各消费点接线

| 页面 / 组件 | 接线 |
|---|---|
| `requirements/page.tsx` · `bugs/page.tsx` | `if (scopeParam) params.set("project_id", scopeParam)`，并计入 §2.3 的 `filterSignature` |
| `requirements/board/page.tsx` · `bugs/board/page.tsx` | `useBoard("requirements", scope)` |
| `hooks/useBoard.ts` | 第二参由 `projectId?: number` 放宽为 `scope?: ProjectScope`；key 拼装由 `projectId ? …` 改为 `scope == null ? "" : \`?project_id=${scope}\`` （**必须改**：现写法无法表达 `"none"`） |
| `dashboard/page.tsx` | `/stats` key 改为 `` `/stats${scopeParam ? `?project_id=${scopeParam}` : ""}` ``；subtitle 追加当前项目名 |
| `requirements/RequirementForm.tsx` · `bugs/BugForm.tsx` | 新增「项目」`<Select>`（`不归属项目`(值 `""`) + 各项目）；初值 = 当前 scope 为数字时取之，否则 `""`；payload 追加 `project_id: projectId ? Number(projectId) : undefined`（`undefined` 经 `JSON.stringify` 自动省略 → 后端 `want_int` 得 `None`，语义与今天一致） |
| `TicketDrawer.tsx` | 元信息行（行 357-365）追加 `<span>项目：{projectName}</span>`；由 `useProjectScope().projects?.find(p => p.id === ticket.project_id)` 解析，未命中或 `project_id == null` 显示「未归属」 |
| `projects/page.tsx` | `<tr>` 加 `onClick={() => { setScope(p.id); router.push("/requirements"); }}` + `cursor-pointer`；当前 scope 命中行加 `bg-clay-soft/30` 与「当前」徽标 |

#### ⑦' 不受作用域约束的视图**必须显式标注**（【评审 R5 · P1】）

**问题**：项目切换器挂在 Header 上，是一个**全局**的作用域指示器；但按 §8-4、§8-5、§2.3④ 的裁定，下列视图**有意不受它约束**：

| 视图 | 为什么不受控 |
|---|---|
| 仪表盘「最近活动」卡 + 「本周活动数」 | `activities` 表无 `project_id`（§5、§8-5） |
| 通知页 / 铃铛下拉 | 通知是「与我相关」的个人维度，非项目维度 |
| 全局搜索下拉 | 语义即「全局」（§8-4） |
| 「我的工作」`/me/work` | 语义即「与我相关的一切」（§8-4） |
| Agents 页的负载计数 | Agent 是全局共享执行者，不隶属项目（§2.4③） |

用户看到 Header 明晃晃写着「ARA · AragonTeam Platform」，却在**同一屏**读到跨项目的活动流、通知与搜索结果——**这恰恰是本轮立誓要消灭的那类「静默说谎 UI」，只不过是本轮亲手造出来的第五处。** v1 只要求在后端 docstring 写理由，而 docstring 用户看不见。

**修复（必须实现，成本极低）**：在上述每个视图上加一处**可见**的作用域标注，仅在 `scope !== null`（即用户确实选了具体项目 / 未归属）时渲染：

- 仪表盘「最近活动」卡片标题右侧、「本周活动」小计旁：`<span className="text-xs text-ink-muted">（全部项目）</span>`。
- 通知页 `Header` 的 `subtitle`、全局搜索下拉的页脚、Agents 页 `Header` 的 `subtitle`：同款「（不随项目筛选）」小字。
- 反向地，**受控**视图（需求 / BUG 列表与看板、仪表盘的需求 / BUG 统计）在 `scope !== null` 时，其 `Header.subtitle` 追加当前项目名（§2.4⑦ 的仪表盘一行已含此要求，此处推广到列表与看板两页）。

> **判据**：任何一屏上，用户都能一眼分辨「这块数据服从我选的项目」还是「这块不服从」。这条与 §2.8 是同一原则的两面——**UI 不得在用户不知情时说与事实不符的话**。

#### ⑧ 关键可用性守卫（必须实现，否则本改动会制造新坑）

选中具体项目后，**存量的 `project_id IS NULL` 工单会全部消失**——现网所有用户新建的单都属此类。三重缓解，缺一不可：

1. **默认作用域是「全部项目」**（`scope` 初值 `null`），不做任何自动选中；
2. **切换器提供「未归属项目」**，配合后端 `?project_id=none`，让存量单**始终可达**；
3. **建单表单默认继承当前 scope**，使「选了项目之后新建的单」自然落进该项目。

---

### 2.5 后端 C'【P1】：看板 `position` 的项目隔离（§2.4 的**必要伴随修复**，不是可选项）

**这是审计发现的、由 §2.4 直接引爆的缺陷。** `_next_position`（`requirements.py:46-49`）与 `_reindex_column`（`requirements.py:57-74`）只按 `status` 分组、**不含 `project_id`**，而 `useBoard.ts:59-63` 发送的是**项目过滤后**看板里的插入索引。

**实机复现**：项目 A 在 `new` 列有 A1,A2（position 0,1）；项目 B 有 B1,B2,B3（position 2,3,4）。`GET /api/board/requirements?project_id=<B>` 显示 `[B1,B2,B3]`；在该看板把 B1 拖到第 3 位 → `PATCH /requirements/<B1>/move {"status":"new","position":2}` → **200**，但 B 的看板**仍是 `[B1,B2,B3]`**（预期 `[B2,B3,B1]`）——因为后端把索引 2 套在了**含 A 卡的全列** `[A1,A2,B1,B2,B3]` 上。**用户拖了、成功了、什么都没变，且没有任何错误提示。**

**修复**：把两个函数改为**项目内编号**，签名增加 `project_id`。

> **【评审 R3 · P1】`project_id` 必须是「无默认值的必填位置参数」，不得写成 `project_id=None`。**
> 理由：本项改动有 **8 处路由调用点 + `agent_runner.py` 一份内联副本**。若给默认值，漏传的调用点**不会报错**，而是把该单编进「未归属项目（`project_id IS NULL`）」的号段 —— 结果是看板次序静默错乱、且只能靠 §6.4 的人工 grep 发现。改成必填后，漏传即 `TypeError`，现网 244 个 pytest 用例里任何一条覆盖到该路径的都会**立刻变红**。这符合 `CLAUDE.md`「错误显式传播，不要默默吞异常或返回 `null` 假装一切正常」——**把静默错数据换成响铃失败**。

```python
def _next_position(model, status: str, project_id) -> int:
    """返回「同项目同状态」列的下一个 position（最大值 + 1；空列为 0）。

    position 的语义是**看板某一列内的相对次序**，而看板已按项目过滤（board.py），
    因此编号必须与看板可见集合同域，否则跨项目卡片会污染插入索引（§2.5）。

    Args:
        project_id: 工单所属项目 id，未归属传 None。**必填**（评审 R3：给默认值会让
            漏传的调用点静默把单编进「未归属」号段，错得无声无息）。
    """
    rows = model.query.filter_by(status=status, project_id=project_id).all()
    return max((r.position for r in rows), default=-1) + 1


def _reindex_column(model, status: str, project_id, insert_id=None, insert_index=None):
    """把「同项目同状态」列内的卡按 (position,id) 排序后连续重编号 0..n-1。

    project_id 同为**必填位置参数**（评审 R3）。经核验，现网两处调用点均以关键字传
    `insert_id=` / `insert_index=`（`requirements.py:333,350`），因此把 project_id
    插在第三位**不会**产生位置参数错位。
    """
    rows = model.query.filter_by(status=status, project_id=project_id)\
        .order_by(model.position.asc(), model.id.asc()).all()
    # …以下与现网逐行一致…
```

**调用点全部须传 `ticket.project_id`**（实现者以 `grep -n "_next_position\|_reindex_column" backend/` 逐一核对，现知 8 处）：
`requirements.py` 的 create / assign / move（2 处）、`bugs.py:100,173,208-229`（经 `from .requirements import` 复用）、以及 `services/agent_runner.py:68-74` 的**同名内联副本**（`advance_one` 在 `:105` 调用）与 `services/agent_autopilot.py:94`。

> **`agent_runner._next_position` 是一份独立副本**（其 docstring 明说「此处内联以避免 service→routes 依赖」）。**两处必须同步修改**，否则 Agent 推进产生的 position 与路由产生的不同域，看板次序会错乱。这是本轮最容易漏的一处，务必在验收清单里单列（§6.4）。
>
> **既有数据的编号空洞**（同列跨项目原本连号，改后各项目各自 0..n-1）**无需迁移**：`position` 只要求**列内单调**，`_reindex_column` 会在下一次 move 时把该项目该列重排连续。已知无害，记于 §7-R9。

---

### 2.6 后端 D【P1】：剩余的真 500 清零

#### ① 超界整型 → `OverflowError` → 500（**三点式**收口）

> **【评审 R1 · P0】v1 写的是「两点式」，漏掉了第三条路径——查询串。** 评审员在 `TestConfig` 内存库上带有效 JWT 复现，`?assignee_id` / `?reporter_id` / `?offset` / `?project_id` 四个查询串参数**今天就在返 500**，且 v1 版 `project_scope()` 的裸 `int(raw)` 会把其中一个原样带进新代码。若不补齐第三点，§6.3-**D1**（硬门槛，「没有任何一个返回 500」）**不可能通过**。

三条路径互相独立，必须各自收口：

| 路径 | 入口 | 收口点 | 结果 |
|---|---|---|---|
| A · URL 路径 | `<int:id>` 转换器 | `app.py::BoundedIntConverter` | **404** |
| B · 请求体 | `want_int(data, …)` | `services/validation.py` | **400** |
| **C · 查询串** | `request.args.get(k, type=int)` / `paginate()` | **`services/scope.py::want_query_int`（§2.4①）+ §2.4①' 全局处理器** | **400** |

实机复现（全部返 500，根因均为 Python 大整数被绑进 SQLite → `OverflowError: Python int too large to convert to SQLite INTEGER`）：

- **A · URL 路径**（六处，根因 `db.session.get(Model, huge)`）：`GET /api/requirements/99999999999999999999`、`/api/bugs/<huge>`（`bugs.py:113`）、`/api/users/<huge>`（`users.py:49`）、`/api/agents/<huge>`（`agents.py:65`）、`/api/projects/<huge>`（`projects.py:45`）、`POST /api/notifications/<huge>/read`（`notifications.py:52`）。
- **B · 请求体**（三处）：`PATCH /requirements/1/assign {"assignee_id": 100000000000000000000}`（`requirements.py:91`）、`POST /requirements {"project_id": <huge>}`（`requirements.py:105`）、`POST /bugs {"related_requirement_id": <huge>}`（`bugs.py:88`）。
- **C · 查询串**（评审员实机复现，v1 遗漏）：

  | 请求 | 现网 | 根因 |
  |---|---|---|
  | `GET /api/requirements?assignee_id=99999999999999999999` | **500** | `filter_by(assignee_id=huge)`（`requirements.py:151`） |
  | `GET /api/requirements?reporter_id=<huge>` | **500** | `filter_by(reporter_id=huge)`（`requirements.py:155`） |
  | `GET /api/requirements?offset=<huge>` | **500** | `query.offset(huge)`（`pagination.py:30`）——**波及每一个列表端点** |
  | `GET /api/requirements?project_id=<huge>` | **500** | `filter_by(project_id=huge)`（`requirements.py:145`） |
  | `GET /api/board/requirements?project_id=<huge>` | **500** | `_grouped` 的 `filter_by`（`board.py:19`） |
  | `GET /api/requirements?limit=<huge>` | 200 | 已被 `paginate` 钳到 `[1,200]`，**安全**，无需处理 |

  BUG 侧、通知侧、搜索侧的同名参数同构（同一段 `paginate` / `filter_by` 代码）。

**修复 A —— URL 侧一处解决（`backend/app.py`）**：Werkzeug 的 `int` 转换器无上界。在 `create_app` 内覆盖全局转换器，超界即**规则不匹配 → 404**（语义正确：这样的 id 本就不存在）：

```python
from werkzeug.routing import IntegerConverter

# SQLite / 多数 RDBMS 的 INTEGER 上限（64 位有符号）。超出即不可能命中任何主键。
MAX_DB_INT = 2 ** 63 - 1


class BoundedIntConverter(IntegerConverter):
    """给 `<int:…>` 加 64 位上界：超界值不匹配路由 → 404，
    而非进 db.session.get 触 OverflowError → 500。

    仅通过构造参数固定 max，无需覆写任何方法——越界判定由父类 NumberConverter 完成。
    """

    def __init__(self, url_map, *args, **kwargs):
        kwargs.setdefault("max", MAX_DB_INT)
        super().__init__(url_map, *args, **kwargs)


# 在 create_app 内、注册蓝图**之前**执行；所有既有 `<int:xxx>` 规则自动生效，无需逐条改路由。
app.url_map.converters["int"] = BoundedIntConverter
```

> `IntegerConverter` 继承自 `NumberConverter`，其 `to_python` 在越界时抛 `werkzeug.routing.ValidationError`，Werkzeug 据此判定「规则不匹配」并最终 404 —— 正是我们要的。
> **三点必须注意**：① 覆写 `url_map.converters` 必须发生在 `register_blueprints(app)` **之前**（现网该调用在 `app.py:41`，覆写插在 `app.py:39` 的「—— 蓝图 ——」注释之前即可），否则已编译的规则不会采用新转换器；② 实现者须断言返回 **404**（不是 400），并额外断言**正常 id 行为完全不变**；③ **【评审 R8 · P2 已知取舍】** 该 404 由 `errors.py:20-22` 的通用 `HTTPException` 处理器渲染，体是 `{"error":"Not Found","detail":…}` —— **英文、非领域文案**，与 §2.8「消灭生硬英文 toast」的取向不完全一致。因该路径不可能由正常 UI 产生（前端只会使用列表返回的真实 id），**接受此取舍，不为其定制文案**；记录于此以免下游误判为漏项。

**修复 B —— 请求体侧（`backend/services/validation.py`）**：给 `want_int` 加 64 位硬界，越界抛既有 `ValidationError` → 400，`detail` 沿用现有 `{field, expected}` 形状，`expected` 固定写 `"integer within 64-bit range"`。`want_int` 已被 `requirements.py` / `bugs.py` / `agents.py` 等广泛使用，**一处改动覆盖全部请求体 id 字段**。

> **【评审 R6 · P1】实现方式必须精确，否则这条修复会被调用方悄悄绕过。** `want_int` **现网已有** `minimum` / `maximum` 两个形参（`services/validation.py:78-95`），且已有调用方在传参。因此：
> - **不得**把 64 位界实现成 `minimum` / `maximum` 的**默认值** —— 任何显式传 `maximum=` 的调用方都会把硬界覆盖掉，那些路径的超界 500 依然存在。
> - 正确写法：在既有 `minimum` / `maximum` 判定**之前**插一段**无条件**的硬界检查，两者**并存取交集**，硬界不经形参暴露：
>   ```python
>   _MIN_DB_INT = -(2 ** 63)
>   _MAX_DB_INT = 2 ** 63 - 1
>   ...
>       # 【§2.6①-B】64 位硬界：超出即不可能是任何主键，且绑进 SQLite 会 OverflowError → 500。
>       # 无条件生效，调用方的 minimum/maximum 只能在其内部再收窄，不能放宽。
>       if v < _MIN_DB_INT or v > _MAX_DB_INT:
>           raise ValidationError(f"{key} is out of range", field=key,
>                                 expected="integer within 64-bit range")
>   ```
> - 与 §2.4① 的 `scope.MIN_DB_INT` / `MAX_DB_INT` **有意各自定义**（`validation` 与 `scope` 互不依赖，都是叶子边界模块）；两者数值必须一致，`test_hardening_r3.py` 须断言 `validation._MAX_DB_INT == scope.MAX_DB_INT`，防未来漂移。

**修复 C —— 查询串侧（`backend/services/scope.py` + `backend/errors.py`）**：见 §2.4① 的 `want_query_int()` 与 §2.4①' 的全局 `QueryParamError` 处理器。接线点：`pagination.paginate` 的 `limit`/`offset`、`requirements.py` / `bugs.py` 列表的 `assignee_id`/`reporter_id`（§2.9-G2）、`project_id`（§2.4②）。**这三处接完，A/B/C 三条路径才算全部收口，D1 才可验收。**

#### ② 四处未校验的 `description` → 500

实机复现（全部 500，`sqlite3.ProgrammingError: Error binding parameter … type 'dict' is not supported`）：

| 位置 | 复现请求 |
|---|---|
| `routes/projects.py:27`（commit 于 `:38`） | `POST /api/projects {"name":"n","key":"K1","description":{"a":1}}` |
| `routes/agents.py:49`（commit 于 `:58`） | `POST /api/agents {"name":"z","description":{"a":1}}` |
| `routes/agents.py:97`（commit 于 `:99`） | `PATCH /api/agents/1 {"description":[1,2]}` |
| `routes/requirements.py:387`（autoflush 于 `:399`） | `POST /api/requirements/<id>/convert-to-bug {"description":{"a":1}}` |

四处都还在用裸 `data.get("description")`。**全仓其余位置早已统一为 `want_str(data, "description", required=False, strip=False) or None`**（见 `requirements.py:180-182`），照抄即可。**不得**为此新增任何 helper。

#### ③ 关键字符串字段补 `max_len`

实机复现：`POST /api/projects {"key":"K"*100}` → **201**，把 100 字符写进 `String(16)` 列（`models/project.py:10`）；`POST /api/agents {"name":"N"*300}` → 201 写进 `String(64)`。SQLite 不强制长度所以不炸，**换 Postgres/MySQL 即硬 500**，且列表 UI 会被撑变形。逐处补 `want_str(..., max_len=N)`，N 取模型列宽：

| 位置 | 字段 | max_len |
|---|---|---|
| `routes/projects.py:26` | `key` | 16 |
| `routes/projects.py`（同处） | `name` | 128 |
| `routes/agents.py:47` · `:96` | `name` | 64 |
| `routes/auth.py:59` · `routes/users.py:26` | `username` | **64**（评审核对 `models/user.py`：`String(64)`；v1 写「按列宽」未给数字，此处钉死） |
| `routes/users.py`（同处） | `display_name` | **128**（`String(128)`；v1 遗漏，一并补齐） |
| `routes/users.py:31` | `email` | 255 |

> `me.py:106` 的自助改邮箱已有 `len(email) > 255` 与 `_EMAIL_RE` 双校验；`users.py:31` 的管理员改邮箱路径**两者都没有**，须补齐到同一水位（复用 `me.py:39` 的 `_EMAIL_RE`，通过 `import` 而非复制正则）。

---

### 2.7 后端 E【P1】：删单后审计残留 + SQLite 主键复用导致的时间线串档

**实机复现**：`POST /api/requirements {"title":"OLD-SECRET"}` → id=1 → 评论、指派 → `DELETE /api/requirements/1` → 204 → `POST /api/requirements {"title":"BRAND-NEW"}` → **id 又是 1** → `GET /api/requirements/1/feed` 返回 **4 条**，含 `created 创建需求「OLD-SECRET」`、`assigned 指派给 Agent「dev-agent」`、`deleted 删除需求「OLD-SECRET」`。

**性质**：既是**错数据**（新单继承别人的时间线），也是**信息泄露**（已删单的标题原样吐给另一个用户）。评论与通知已被删（`requirements.py:258,260`），唯独审计被有意保留，而 SQLite 不带 `AUTOINCREMENT` 时会复用最大 rowid。

**修复**：在两个 delete 路由的级联里**一并删除该实体的审计行**，与评论 / 通知同批：

```python
    # 【§2.7】删单一并删审计：SQLite 复用主键，残留审计会被下一张同 id 的单继承，
    # 造成时间线串档 + 已删单标题泄露。审计的价值绑定在「单还在」这一前提上。
    Activity.query.filter_by(entity_type="requirement", entity_id=req_id).delete()
```

位置：`routes/requirements.py:262` 与 `routes/bugs.py:256` 的 `db.session.delete(...)` **之前**。注意**顺序**：现网在删除前还会 `Activity.log(... "deleted" ...)` 写一条删除审计（`requirements.py:261-262`），该行必须**移到 `.delete()` 之后**或直接删除——否则刚写的那条会被同一批清掉（等价于删掉，但让代码说谎）。**推荐直接删掉这条 `deleted` 审计的写入**，并在注释里说明理由（该单已不存在，其审计无查看入口）。

**副作用（须写进 §4 与验收）**：`/stats` 的 `activities_this_week` 会在删单时相应下降。这是**更正确**的行为（统计不该包含已不存在实体的活动）。

> **已评估并否决的替代方案**：(a) 给 `requirements.id` 加 `AUTOINCREMENT` 杜绝主键复用 —— 需 schema 变更 + 数据迁移，越过「零 schema 变更」红线；(b) 在 feed 查询里按 `created_at > ticket.created_at` 过滤 —— 治标，且对同秒创建不可靠。

---

### 2.8 前端 E【P1】：消灭四处「静默说谎」的 UI

#### ① 看板拖拽补 RBAC 门禁（并抽出与后端同判据的 `canManageTicket`）

**复现**：`alice`（member）登录 → `/requirements/board` → 拖一张别人的卡 → 卡片动画飞过去又弹回，toast 显示**生硬英文** `forbidden`。链路：后端 `/move` 要求 `can_manage_ticket`（`requirements.py:312-314`），`auth_helpers.py:75-77` 返 `{"error":"forbidden"}`，`api.ts:95-97` 把它塞进 `ApiError.message`，`useBoard.ts:85` 原样 toast。而 `useSortable` 对每张卡无条件启用——**与 TicketDrawer 早已按 `canManage` 门禁的做法不一致**。

**修复（两步）**：

1. **新增 `frontend/lib/permissions.ts`**，把 `TicketDrawer.tsx:130-137` 的内联判据抽出来（**判据与后端 `can_manage_ticket` 逐条对齐**，任何一侧变更须同步）：
   ```ts
   /** 与后端 services/auth_helpers.py::can_manage_ticket 同判据：pm/admin ｜ reporter ｜ 人类 assignee。 */
   export function canManageTicket(user: User | null, ticket: Card | null): boolean {
     if (!user) return false;
     if (user.role === "admin" || user.role === "pm") return true;
     if (!ticket) return false;
     return ticket.reporter_id === user.id
       || (ticket.assignee_type === "user" && ticket.assignee_id === user.id);
   }
   ```
   `TicketDrawer.tsx` 改为调用它（**删除内联判据，避免两份判据漂移**）。
2. `KanbanCard.tsx` 接收 `canDrag: boolean`（由 `KanbanBoard` 依 `canManageTicket(user, card)` 逐卡计算），传给 `useSortable({ ..., disabled: !canDrag })`，并给不可拖卡去掉 `cursor-grab`。
3. **兜底**：`useBoard.ts` 的错误分支追加 `else if (err instanceof ApiError && err.status === 403) toast.error("你没有权限移动这张工单")`，杜绝任何路径下再冒出英文 `forbidden`。

#### ② 铃铛 → 通知页的反向同步（`hooks/useNotifications.ts:29-42`）

**复现**：停在 `/notifications` 页 → 点该页 Header 里的铃铛 → 「全部已读」→ 角标归零，但**页面每一行仍高亮为未读**，「全部已读」按钮还在，直到刷新。原因：`markRead`/`markAllRead` 只 mutate `/notifications/unread-count` 与 `/notifications?limit=15`，而通知页用的是另一个 key。页面侧的 `syncBell()` 做了正向同步，**缺的是反向**。

**修复**：在 `useNotifications` 的 `markRead`/`markAllRead` 成功后，追加对**通知页 key 前缀**的失效。因 §2.3-③ 后该 key 含变动的 `offset`，须用 SWR 的**函数式 key 匹配**：

```ts
import { mutate as globalMutate } from "swr";   // 【评审 R9】现网 useNotifications.ts 未 import，须补

// 铃铛与通知整页是两个独立 key；读单后必须双向同步，否则另一侧滞留旧状态。
// 【评审 R9】只匹配到 "?" 为止：不把 PAGE_SIZE(=50) 硬编码进匹配串——否则日后调页长，
// 这行会静默失效（匹配不到任何 key，且不报错）。多失效一个铃铛自己的 key 无害。
globalMutate((key) => typeof key === "string" && key.startsWith("/notifications?"));
```

> 保留既有的两条精确 mutate 不动（角标 + 铃铛下拉），只**追加**这一条。SWR 2.x 支持函数式 key 过滤（已核 `package.json` 为 `swr: ^2.2.5`）。

#### ③ 铃铛下拉的错误态（`useNotifications.ts:47` + `NotificationBell.tsx:121-122`）

**复现**：停掉后端 → 点铃铛 → **永久「加载中…」**，无重试、无 toast。原因：`loading: listEnabled && !listSWR.data`，而 `listSWR.error` **从未被返回**，下拉也没有 error 分支。

**修复**：`useNotifications` 返回值增加 `error: listSWR.error`；`NotificationBell` 下拉在 `loading` 分支**之前**插入 error 分支，复用全站 `ErrorState` 原语（`components/ui/ErrorState.tsx`）并接 `onRetry={() => mutate()}`。与第 1 轮给各主页面加 ErrorState 的做法完全一致——**这是那一轮漏掉的最后一个消费点**。

#### ④ 通知偏好卡的错误态（`NotificationPrefsCard.tsx:40,51` + `useNotificationPreferences.ts:48-50`）

**复现**：让 `GET /api/me/notification-preferences` 失败 → 打开 `/settings` → **六个开关全部画成「开」且全部锁死，没有任何提示**。用户会确信通知都开着。原因：`preferences: data?.preferences ?? null`，卡片渲染 `preferences?.[type] ?? true` 且 `disabled={loading || !preferences}`，`preferences` 永远是 `null`。

**修复**：hook 返回 `error`；卡片在 `error && !preferences` 时渲染 `<ErrorState message="无法加载通知偏好" onRetry={...} />` **替代整组开关**——**绝不允许**在数据未知时把开关画成任何一个具体状态。

---

### 2.9 一批低风险机械加固（P2，各自独立、可按序落地）

**后端**

| # | 位置 | 缺陷 | 修复 |
|---|---|---|---|
| G1 | `routes/users.py:16-18` · `agents.py:37-39` · `projects.py:15-17` | 三个 list 端点无 `paginate()`、无 `X-Total-Count`（实测响应头缺失），破坏 `listFetcher` 契约（`api.ts:161` 只能回落 `items.length`）且无上界 | 照 `requirements.py:165-167` 套 `paginate` + `with_total_count`。**响应体仍是裸数组，契约不变** |
| G2 | `requirements.py:136-155` · `bugs.py:38-57` | 畸形过滤值被静默丢弃：`?assignee_id=abc` → 200 且返**全部**行（`type=int` → `None` → 跳过过滤）。`reporter_id`、`limit` 同 | 与 §2.4 的 `project_id` 同策略：非法整数 → 400，`detail.field` 指明字段。**须与 §2.4 共用一个 helper**，不得写三份 |
| G3 | `routes/agents.py:19-32` `_run_with_lock` · `requirements.py:488-490` `_agent_run_all` 的 `finally` | busy 软锁可**永久泄漏**：`busy` 先行持久化提交，若 `fn()` 抛 DB 级异常，`finally` 里的 `db.session.commit()` 自身抛 `PendingRollbackError`，恢复丢失 → Agent 永久 busy → 之后每次 `/autorun`、`/tick`、`?run=all` 都 409，只能靠管理员手动 `PATCH` 复位 | `finally` 内在恢复前先 `db.session.rollback()`，再 `agent.status = prev; db.session.commit()`。**两处都改** |
| G4 | `routes/bugs.py` | 缺 `GET /api/bugs/<id>/activities`（需求侧 `requirements.py:498` 有），纯路由不对称 | 补上，复用同一实现 |

**前端**

| # | 位置 | 缺陷 | 修复 |
|---|---|---|---|
| H1 | `hooks/useTicket.ts:20-21` vs `TicketDrawer.tsx:115` | id 守卫不一致：抽屉判 `id == null`，hook 判 falsy。`/bugs/board?ticket=0` → 全屏遮罩 + **永不结束的骨架**，看板不可用（须 Esc） | 两侧统一为「正整数才有效」：`Number.isInteger(id) && id > 0`，其余按 `null` 处理（看板的 `?ticket=` 解析同步收紧） |
| H2 | `components/layout/GlobalSearch.tsx:54-59,97-98,153` | 选中结果后下拉**闪回**：`onSelect` 置 `open=false`，但 `[query]` effect 无条件 `setOpen(true)`，而 `debounced` 300ms 后才清空 | `onSelect` 里同步清 `debounced`；或给 effect 加「query 非空才 open」守卫。**同路由跳转不重挂载，此路径必现** |
| H3 | `hooks/useBoard.ts:57-73` | **写成功但重取失败**被报成「移动失败，已回滚」：thunk 是 `patch` 然后 `get`，只有第二步失败时 `rollbackOnError` 仍回滚，行 89 还把陈旧快照钉死（`revalidate:false`） | 区分两段：`patch` 成功后即视为写入成功；重取失败时**不回滚**，改为 `mutate()` 触发一次重新验证并提示「已提交，正在刷新」 |
| H4 | `hooks/useBoard.ts:36` | 同列拖到列**空白处**是静默 no-op（`KanbanBoard.tsx:84-87` 在 `over.id` 为字符串时置 `toIndex = undefined`），用户拖了没反应也没提示 | 同列且 `toIndex === undefined` 时按「移到列尾」处理（`toIndex = 该列长度 - 1`），语义符合直觉 |
| H5 | `app/(app)/agents/page.tsx:174-175` | 无 loading 态：`{agents?.map(...)}` + `{agents && agents.length === 0 && <empty/>}`，取数期间**整页空白**，与「没有 Agent」无法区分 | 补 `SkeletonRows`/骨架卡片分支，与其余列表页一致 |
| H6 | `components/kanban/KanbanCard.tsx:58-60,88` | 「转 BUG」按钮 `opacity-0 group-hover:opacity-100` —— **opacity 不移除命中区**：触屏点卡片右下角可能**误触发不可逆的转 BUG**；且它嵌在被 `useSortable` 置为 `role="button" tabIndex=0` 的 div 内，`KeyboardSensor` 又抢走 Enter/Space，键盘用户既打不开抽屉也够不到该按钮 | 改用 `pointer-events-none opacity-0 group-hover:pointer-events-auto group-hover:opacity-100 focus-visible:pointer-events-auto focus-visible:opacity-100`，并给按钮 `aria-label`。**转 BUG 是不可逆操作，此项须优先于其他 P2** |
| H7 | `components/ui/Input.tsx:11` · `Select.tsx:18` | `id` 回退到 `rest.name`，而多数调用方两者都不传 → `<label>` 与控件**未关联**：点标签不聚焦，读屏播报「未命名输入框」。受影响：`PasswordCard.tsx:47-67`（三个密码框）、`ProfileCard.tsx:83-96`、`MemberFormModal.tsx:104-111,161-166`、`AgentFormModal.tsx:120-123`、`ProjectFormModal.tsx:57-62` | 在 `Input`/`Select` 内用 `useId()` 生成稳定回退 id（React 18 内置，SSR 安全），`id ?? rest.name ?? useId()` |

---

## 3. File / Module Change Plan（文件变更计划）

### 3.1 Backend（新增 1 · 修改 11）

| 文件 | 动作 | 一句话意图 |
|---|---|---|
| `backend/services/scope.py` | **新增** | **查询串整型边界 `want_query_int`（评审 R1 · 三点式的第三点）** + 统一 `?project_id=` 解析与过滤（`int` / `none` / 非法或超界→400）；被 G2 的整数过滤参数与 `pagination` 共用 |
| `backend/errors.py` | 修改 | **【评审 R1】注册 `QueryParamError` → 400 全局处理器**（与既有 `ValidationError` 同构），取代 v1 的逐路由 `try/except`（§2.4①'） |
| `backend/services/pagination.py` | 修改 | **【评审 R1】`limit`/`offset` 改走 `want_query_int`**，堵住 `?offset=<超界>` 这条波及**每一个**列表端点的 500 |
| `backend/services/agent_autopilot.py` | 修改 | `_QA_HANDOFF_STATUS` → `_KIND_FOR_STATUS`（由 `AGENT_FORWARD` 派生）；`_maybe_handoff_to_qa` → 公开 `maybe_handoff` + 人类持单守卫；`AGENT_CLAIMABLE["generic"] = []` |
| `backend/routes/requirements.py` | 修改 | 交接接进 `do_agent_advance` / `_agent_run_all`（§2.2③）；`project_id` 过滤改走 `scope.py`；`_next_position`/`_reindex_column` 加 `project_id`（§2.5）；删单级联删审计（§2.7）；G2 过滤严格化 |
| `backend/routes/bugs.py` | 修改 | 同构：列表 scope、position 项目隔离调用点、删单级联删审计、G2；补 `GET /<id>/activities`（G4） |
| `backend/routes/board.py` | 修改 | `_grouped` 改用 `scope.py`；两个视图加 400 分支 |
| `backend/routes/stats.py` | 修改 | `/stats` 接受 `?project_id=`；`_by_status` 改 `GROUP BY`；全局字段保持不过滤并在 docstring 写明理由 |
| `backend/routes/agents.py` | 修改 | `claim-next` 补 busy/offline 门禁（§2.2⑤）；`description` 两处补 `want_str`、`name` 补 `max_len`；`_run_with_lock` 的 `finally` 补 `rollback`（G3）；列表补分页（G1） |
| `backend/routes/projects.py` | 修改 | `description` 补 `want_str`；`key`/`name` 补 `max_len`；列表补分页（G1） |
| `backend/routes/users.py` · `auth.py` | 修改 | `username`/`email` 补 `max_len` 与 `_EMAIL_RE`；`users` 列表补分页（G1） |
| `backend/services/validation.py` | 修改 | `want_int` 增加**无条件**的 64 位硬界（与调用方 `minimum`/`maximum` 取交集，不经形参暴露）→ 越界 400（§2.6①-B，评审 R6） |
| `backend/services/agent_runner.py` | 修改 | `_next_position` 内联副本同步加 `project_id`（§2.5，**最易漏**） |
| `backend/app.py` | 修改 | 注册 `BoundedIntConverter` 覆盖 `url_map.converters["int"]`（§2.6①-A） |

### 3.2 Backend 测试（新增 3 · 修改 1）

| 文件 | 动作 | 覆盖点 |
|---|---|---|
| `backend/tests/test_project_scope.py` | **新增** | ① `?project_id=<id>` 只返该项目；② `?project_id=none` 只返 `IS NULL`；③ `?project_id=abc` → 400 且 `detail.field=="project_id"`（需求 / BUG / board / stats 各断一次）；④ **向后兼容**：缺省时结果集与改造前逐项一致；⑤ 看板列结构（列数、列 key 顺序）不变；⑥ `project_id=99999` → 200 空结果（**不 404**）；⑦ **§2.5 回归**：两项目同列时，在项目内看板按索引 move 后，该项目看板次序确实改变 |
| `backend/tests/test_stats.py` | **新增** | ① `/stats` 顶层键集与现网一致（**契约回归**）；② `?project_id=` 下 `total`/`by_status` 只计该项目；③ `agents`/`members`/`activities_this_week` **不随** `project_id` 变化；④ `by_status` 覆盖全部 `column_keys` 且缺省 0；⑤ `?project_id=abc` → 400 |
| `backend/tests/test_hardening_r3.py` | **新增** | ① 六个 `<int:id>` 路由的超界 id → **404**；② 三个请求体 id 字段超界 → **400**；③ 四处 `description` 非串 → 400；④ `key`/`name`/`username` 超长 → 400；⑤ 删单后新建同 id 单的 `feed` **为空**（§2.7 串档回归）；⑥ offline Agent `claim-next` → 409；⑦ `_run_with_lock` 异常路径后 Agent 状态回到 `idle`（§2.9-G3）；**⑧【评审 R1】查询串超界 → 400**：`?assignee_id=` / `?reporter_id=` / `?offset=` / `?project_id=`（需求 / BUG / board 各断一次）**全部 400 且无一 500**，并断言 `?limit=<超界>` 仍 200（钳制语义未被破坏）、`?offset=-1` → 400；**⑨** 断言 `validation` 与 `scope` 两处 64 位常量相等（防漂移，§2.6①-B） |
| `backend/tests/test_agent_autopilot.py` | 修改 | 按 §2.2④ 更新 generic 认领相关断言；**新增**：`_KIND_FOR_STATUS` 派生表逐项断言；generic 泊在 `in_development` 经一次 `agent-advance` 交接给 dev 并推进；seed 式「qa-agent 持 `fixing` BUG」经一次推进交接给 dev；**dev→qa 既有行为逐项不变** |

> 现网 **244 个 pytest 用例必须继续全绿**（除 §2.2④ 明确须按新语义更新的 generic 认领断言）。本轮**只增不减**。

### 3.3 Frontend（新增 4 · 修改 18）

| 文件 | 动作 | 一句话意图 |
|---|---|---|
| `frontend/components/ui/Pagination.tsx` | **新增** | 受控分页条；`total <= limit` 时渲染 `null` |
| `frontend/lib/project-scope.tsx` | **新增** | `ProjectScopeProvider` / `useProjectScope()`；localStorage 持久化 + 失效自愈 |
| `frontend/components/layout/ProjectSwitcher.tsx` | **新增** | Header 项目下拉（全部 / 未归属 / 各项目） |
| `frontend/lib/permissions.ts` | **新增** | `canManageTicket(user, ticket)`，与后端 `can_manage_ticket` 同判据 |
| `frontend/app/(app)/layout.tsx` | 修改 | 鉴权守卫**之后**包 `ProjectScopeProvider` |
| `frontend/components/layout/Header.tsx` | 修改 | `<GlobalSearch />` 前挂 `<ProjectSwitcher />` |
| `frontend/app/(app)/requirements/page.tsx` · `bugs/page.tsx` | 修改 | 分页（key + `<Pagination>` + 筛选归零 + 越界自愈 + `keepPreviousData`）+ 项目 scope |
| `frontend/app/(app)/notifications/page.tsx` | 修改 | 去掉硬编码 `limit=100`，接分页；`syncBell()` 的铃铛 key 保持不动 |
| `frontend/app/(app)/requirements/board/page.tsx` · `bugs/board/page.tsx` | 修改 | `useBoard(entity, scope)`；`?ticket=` 解析收紧为正整数（H1） |
| `frontend/app/(app)/dashboard/page.tsx` | 修改 | `/stats` key 带 `project_id`；subtitle 显示当前项目 |
| `frontend/app/(app)/projects/page.tsx` | 修改 | 行可点击 → 切 scope + 跳转；当前项目高亮 + 「当前」徽标 |
| `frontend/app/(app)/agents/page.tsx` | 修改 | 补 loading 骨架（H5） |
| `frontend/hooks/useBoard.ts` | 修改 | 第二参放宽为 `ProjectScope`；403 中文文案；写成功/重取失败区分（H3）；同列空白落点（H4） |
| `frontend/hooks/useTicket.ts` | 修改 | id 守卫统一为正整数（H1） |
| `frontend/hooks/useNotifications.ts` | 修改 | 返回 `error`；读单后反向失效通知页 key（§2.8②③） |
| `frontend/hooks/useNotificationPreferences.ts` | 修改 | 返回 `error`（§2.8④） |
| `frontend/components/notifications/NotificationBell.tsx` | 修改 | 下拉补 ErrorState 分支 |
| `frontend/components/settings/NotificationPrefsCard.tsx` | 修改 | 错误时以 ErrorState 替代整组开关 |
| `frontend/components/kanban/KanbanBoard.tsx` · `KanbanCard.tsx` | 修改 | 逐卡 `canDrag` 门禁；转 BUG 按钮 `pointer-events` + `focus-visible` + `aria-label`（H6） |
| `frontend/components/TicketDrawer.tsx` | 修改 | 显示所属项目；`canManage` 改用 `lib/permissions`（删除内联判据） |
| `frontend/components/requirements/RequirementForm.tsx` · `bugs/BugForm.tsx` | 修改 | 新增「项目」Select，默认继承 scope，payload 带 `project_id` |
| `frontend/components/layout/GlobalSearch.tsx` | 修改 | 选中后不再闪回（H2） |
| `frontend/components/ui/Input.tsx` · `Select.tsx` | 修改 | `useId()` 兜底 id，恢复 label 关联（H7） |

### 3.4 文档

| 文件 | 动作 | 意图 |
|---|---|---|
| `docs/plans/scale-and-project-scope/spec.md` | **新增（本文件）** | 本轮设计与验收依据 |
| `README.md` | 修改 | 补项目切换、分页、`?project_id=`（含 `none`）、`/stats?project_id=`、超界 id → 404 |
| `.claude-index/index.md` | 修改 | 补 `services/scope.py`、`lib/project-scope.tsx`、`lib/permissions.ts`、`ui/Pagination.tsx`、`layout/ProjectSwitcher.tsx` |

---

## 4. Interface Design（接口设计 · 仅列语义变更，成功响应 shape 全部不变）

| # | 端点 | 变更 | 说明 |
|---|---|---|---|
| ① | `GET /api/requirements`、`/api/bugs`、`/api/board/*` | **`?project_id=` 语义扩展** | 新增 `none` = 仅未归属（`IS NULL`）。整数与缺省行为**与今天完全一致**。响应仍为裸数组 + `X-Total-Count` / 分组结构不变。 |
| ② | `GET /api/stats` | **新增可选 `?project_id=`** | 过滤 `requirements.*` 与 `bugs.*`；`agents.*` / `members` / `activities_this_week` / `recent_activities` **有意保持全局**。响应键集不变。 |
| ③ | 上述端点 | **`?project_id=<非整数且非 none>` → `400`** | 此前静默忽略。体为 `{"error":"invalid project_id","detail":{"field":"project_id","expected":"integer or 'none'","got":"…"}}`。同策略适用于 `assignee_id` / `reporter_id` / `limit`（§2.9-G2）。**本轮主要的行为收紧**，风险评估见 §7-R1。 |
| ④ | 全部 `<int:id>` 路由（6 处） | **超界 id 由 `500` 改为 `404`** | 纯修复。`< 2^63` 的 id 行为完全不变。 |
| ⑤ | `POST /api/requirements` 等携 id 字段的写端点 | **超界 id 由 `500` 改为 `400`** | 纯修复，`detail` 沿用既有 `{field, expected}`。 |
| ⑥ | `POST /api/projects`、`POST/PATCH /api/agents`、`POST /api/requirements/<id>/convert-to-bug` | **非串 `description` 由 `500` 改为 `400`**；超长 `key`/`name`/`username`/`email` 由 `201` 改为 `400` | 纯修复 + 收紧。合法输入行为不变。 |
| ⑦ | `POST /api/agents/<id>/claim-next` | **offline / busy Agent 由 `200` 改为 `409`** | 与 `/autorun`、`/tick`、`?run=all` 对齐，消除「吞了又不干」的陷阱态。 |
| ⑧ | `POST /api/requirements/<id>/agent-advance`（BUG 同构） | **无签名 / 无 shape 变更**；行为上「本 Agent 无动作」时先交接再重试一次 | 成功仍返 `{ticket, comment, agent}`；仍无对口 Agent 时仍返同样的 409。**这是刻意设计的「零契约变更修复」**。 |
| ⑨ | `GET /api/users`、`/api/agents`、`/api/projects` | **新增 `X-Total-Count` 响应头 + `limit`/`offset` 支持** | 响应体仍是裸数组，**契约不变**；`limit` 缺省 50 / 上限 200 —— 实现者须核对现有前端消费方（`AssigneePicker`、`team`、`projects`、`agents` 页）在超过 50 条成员/Agent 时是否需要显式传 `limit`。见 §7-R8。 |
| ⑩ | `GET /api/bugs/<id>/activities` | **新增端点** | 与 `requirements` 侧对称，同 shape。 |
| ⑪ | `DELETE /api/requirements/<id>`、`/api/bugs/<id>` | 级联**新增删除审计行** | 响应仍 204。副作用：`/stats.activities_this_week` 会相应下降（更正确）。 |
| **⑫** | **全部列表端点的查询串整型参数**（`limit` / `offset` / `assignee_id` / `reporter_id` / `project_id`） | **【评审 R1 新增】超界（>64 位）由 `500` 改为 `400`**；`offset` 为负由「静默归零」改为 `400` | 体为 `{"error":"invalid <field>","detail":{"field","expected","got"}}`，与 ③ 同形、由 §2.4①' 的全局 `QueryParamError` 处理器统一渲染。**合法范围内的取值行为完全不变**（`limit` 仍钳到 `[1,200]`）。这是 D1「零 500」得以成立的关键一条。 |

**无新增鉴权要求、无请求体结构变更。** 所有端点的 `@jwt_required()` / `@require_role` 装饰器一律原样。

---

## 5. Data Model（数据模型）

**本轮不新增表、不新增列、不改列类型、不做 schema 迁移。** 延续「自 MVP 以来唯一新增表是 Phase-3 `notifications`」的记录。

| 表 / 列 | 类型 | 本轮用法 |
|---|---|---|
| `projects.id` / `.key` / `.name` / `.owner_id` | `Integer` / `String(16) unique` / `String(128)` / FK→`users.id` | 项目切换器选项来源（`GET /api/projects`，已存在）；`key`/`name` 本轮补 `max_len` 对齐列宽 |
| `requirements.project_id` · `bugs.project_id` | `Integer`，**`nullable=True`**，FK→`projects.id`（`models/requirement.py:18`） | 过滤键；`NULL` = 未归属，经 `?project_id=none` 可达 |
| `requirements.position` · `bugs.position` | `Integer` | 语义**收窄**为「**同项目**同状态列内的相对次序」（§2.5）。无需数据迁移：只要求列内单调，`_reindex_column` 会在下次 move 时重排连续 |
| `requirements.status` · `bugs.status` | `String` | `_by_status` 的 `GROUP BY` 键 |
| `activities` | — | 无 `project_id` 列 ⇒ 不按项目过滤（§8）；**行的生命周期本轮绑定到工单**（删单即删审计，§2.7） |
| `agents.kind` | `String`（`dev`/`qa`/`generic`） | `_KIND_FOR_STATUS` 的取值域；交接目标筛选键 |

前端新增的**内存形状**（非持久化）：

```ts
type ProjectScope = number | "none" | null;          // 具体项目 | 未归属 | 全部
// localStorage["aragon.project"]: "" | "none" | "<id>" —— 读取时非法值一律回落 null
```

**SQLite 索引说明**：`project_id` 上目前无显式索引。单机 MVP 量级（万级以内）全表扫描可接受；本轮**有意不加**（加索引需 `ALTER`/迁移，越过零 schema 变更红线）。见 §7-R5。

---

## 6. Testing & Acceptance（测试与验收标准）

### 6.1 后端 pytest

```powershell
cd M:/takoAI/AragonTeam/backend
python -m pytest -q
```

**通过判据**：exit code 0，用例数 ≥ 244 + 新增（约 `test_project_scope.py` 12 例 + `test_stats.py` 6 例 + `test_hardening_r3.py` **17** 例（评审 R1 增补覆盖点 ⑧⑨）+ `test_agent_autopilot.py` 增补 5 例 ≈ **282+**），**零失败、零 error**。

三条**回归护栏**必须存在：

- **向后兼容**：`GET /api/requirements`（不带 `project_id`）结果集与改造前逐项一致（用 seed 数据断言 id 列表与顺序）。
- **契约稳定**：`GET /api/stats` 顶层键集 == `{requirements, bugs, agents, members, activities_this_week, recent_activities}`。
- **第 2 轮零回归**：dev→qa 交接的既有断言**逐条不变**；`POST /api/agents/autorun-all` 仍能把需求带到 `reviewing`、BUG 带到 `closed`。

### 6.2 前端质量门禁

```powershell
cd M:/takoAI/AragonTeam/frontend
npm run typecheck      # tsc --noEmit → 0 error
npm run build          # next build  → 页面数不减少（现网 16/16）
```

**通过判据**：`tsc --noEmit` **0 error**（`ProjectScope` 联合类型经 `useBoard` 到 key 拼装必须类型自洽，**不得用 `as any` 绕过**——现网全仓零 `as any`，此纪录须保持）；`next build` 成功且页面数不减。

### 6.3 手工验收（P0/P1 路径冒烟）

| # | 场景 | 步骤 | 期望 |
|---|---|---|---|
| **A1** | **工单页 Agent 闭环（本轮头号 P0）** | 需求指派 `dev-agent` → 抽屉连点「▶ 让 … 处理下一步」 | `assigned→in_development→testing`，**第三次点击不再 409**，负责人自动变为 `qa-agent` 并推进到 `reviewing`；全程无红色 toast |
| A2 | 存量卡死单复活 | 打开 seed BUG「看板列计数未实时刷新」（`fixing` @ `qa-agent`）→ 点推进一次 | 交接给 `dev-agent` 并推进到 `verifying`；时间线出现「接手…继续处理」 |
| A3 | 交接不抢人类的单 | 把一条 `testing` 需求指派给**人类** alice → `POST /autorun-all` | 该单**仍在 alice 名下**，不被 qa-agent 抢走 |
| A4 | offline 不接单 | `PATCH /agents/<qa> {"status":"offline"}` → 推进一条到 `testing` 的需求 | **不交接给 offline 的 qa**；`claim-next` 对 offline Agent 返 **409** |
| **B1** | **分页可达性** | 造 ≥ 60 条需求 → `/requirements` | 标题「共 60 条」；50 行；底部「第 1–50 条 / 共 60 条」+「下一页」；点击后显示 51–60，「下一页」置灰 |
| B2 | 分页 × 筛选 | 在第 2 页把状态筛成只有 3 条的状态 | **立刻回第 1 页**显示 3 条；分页条消失；**不得**出现空表 |
| B3 | 小数据量零视觉回归 | 在 seed 库（< 50 条）打开 `/requirements`、`/bugs` | 与改造前**完全一致**，底部无分页条 |
| B4 | 通知分页 + 双向同步 | 造 ≥ 60 条通知 → `/notifications` → 翻到第 2 页 → 点该页 Header 的铃铛「全部已读」 | 可达 51+ 条；**页面每一行立即变为已读**（不需刷新）；角标归零 |
| **C1** | **项目切换贯通** | Header 下拉选 `ARA · AragonTeam Platform` | 需求页 / BUG 页 / 两个看板 / 仪表盘**同时**只显示该项目；刷新浏览器后选择保持 |
| C2 | 未归属可达 | 下拉选「未归属项目」 | 显示全部 `project_id IS NULL` 的存量单——**验证「切项目后老数据不会消失」守卫生效** |
| C3 | 建单落项目 | scope=`ARA` 时新建需求（表单「项目」默认已选中 `ARA`）→ 提交 | 新单出现在 `ARA` 作用域下；抽屉显示「项目：AragonTeam Platform」 |
| C4 | 项目页不再是死胡同 | `/projects` 点任意一行 | 切 scope 并跳 `/requirements`；返回后该行有「当前」徽标与高亮 |
| C5 | 失效自愈 | `localStorage.setItem("aragon.project","99999")` → 刷新 | 静默回落「全部项目」，**不空页、不报错** |
| **C6** | **看板项目内重排（§2.5 回归）** | 造两个项目，同在 `new` 列各 2–3 张卡 → 切到项目 B 的看板 → 把 B1 拖到末位 | 松手后 B 的看板**确实变成** `[B2,B3,B1]`；刷新后仍然如此；项目 A 的看板次序**不受影响** |
| C7 | 统计按项目 | 仪表盘在 `ARA` 与「全部项目」之间切换 | 需求 / BUG 总数与分布条随之变化；**Agent 利用率、成员数、本周活动数不变** |
| **C8** | **作用域标注不说谎（【评审 R5】）** | 切到具体项目 `ARA` → 依次看仪表盘、通知页、全局搜索下拉、Agents 页 | 需求 / BUG 统计与列表 / 看板的标题**带项目名**；而「最近活动」「本周活动数」「通知」「搜索结果」「Agent 负载」**各自带可见的「（全部项目）/（不随项目筛选）」标注**；切回「全部项目」时这些标注消失。**判据：用户一眼能分清哪块数据服从作用域** |
| **D1** | **剩余 500 清零 · 路径与请求体** | `curl "…/api/requirements/99999999999999999999"` → 404；`POST /api/projects {"name":"n","key":"K1","description":{"a":1}}` → 400；`POST /api/projects {"key":"K"*100}` → 400；`?project_id=abc` → 400；`?project_id=none` → 200 | 全部如期；**没有任何一个返回 500** |
| D2 | 时间线不串档 | 建单 → 评论 → 删单 → 再建一张（同 id）→ 看抽屉时间线 | **时间线为空**，不含任何已删单的标题 |
| **D3** | **剩余 500 清零 · 查询串（【评审 R1】硬门槛）** | 以 `H='99999999999999999999'` 依次请求：`/api/requirements?assignee_id=$H`、`?reporter_id=$H`、`?offset=$H`、`?project_id=$H`、`/api/board/requirements?project_id=$H`、`/api/bugs?offset=$H`、`/api/notifications?offset=$H` | **七条全部 400**（体为 `{"error":"invalid <field>", detail:{field,expected,got}}`），**无一 500**；对照组 `?limit=$H` 仍 **200**（钳到 200 条），`?offset=0` 行为完全不变 |
| **E1** | **看板拖拽权限** | `alice`（member）登录 → 看板拖别人的卡 | 卡片**不可拖动**（无抓手光标）；若经其他路径触发 403，toast 为**中文**「你没有权限移动这张工单」，绝不出现 `forbidden` |
| E2 | 错误态不说谎 | 停掉后端 → 点铃铛；再让 `/me/notification-preferences` 失败 → 开 `/settings` | 铃铛下拉显示错误 + 可重试（**不再永久转圈**）；偏好卡显示错误 + 可重试（**不再把六个开关画成「开」并锁死**） |
| E3 | 触屏不误触 | 平板上点 `testing` 需求卡右下角 | 打开抽屉，**不会**触发不可逆的「转 BUG」 |

### 6.4 Definition of Done 汇总

- [ ] 后端 `python -m pytest -q` exit 0，用例数 ≥ 282，零失败。
- [ ] 前端 `npm run typecheck` 0 error；`npm run build` 成功且页面数不减；全仓仍**零 `as any`**。
- [ ] §6.3 全部 **22** 项手工验收通过（**A1 / B1 / C1 / C2 / C6 / C8 / D1 / D3 / E1 为硬门槛**）。
- [ ] **全仓复核清单**（逐条执行并留痕）。**【评审 R7】以下命令已改写为跨 shell 可执行形式** —— v1 版含 bash 专属的 `{a,b,c}` 花括号展开与 `\(app\)` 转义，在本项目约定的 **Windows / PowerShell 5.1**（见 `CLAUDE.md`）下会直接报错，等于没有护栏。推荐直接用 Claude Code 的 Grep 工具，或按下列**逐项**命令执行：
  - `rg -n "_next_position|_reindex_column" backend` —— **每一处调用都传了 `project_id`**（评审 R3 后为必填位置参数，漏传会 `TypeError`），且 `services/agent_runner.py` 的内联副本已同步（§2.5 最易漏项）。
  - `rg -n "_maybe_handoff_to_qa|_QA_HANDOFF_STATUS" backend` —— **零命中**（已全部替换）。
  - `rg -n "data\.get\(.description.\)" backend/routes` —— **零命中**。
  - `rg -n "args\.get\(.*type=int" backend` —— **零命中**（评审 R1：查询串整型必须全部走 `want_query_int`；这是 D3 能否通过的静态判据）。
  - 逐个文件确认分页已接：`rg -n "offset" "frontend/app/(app)/requirements/page.tsx"`、`… "frontend/app/(app)/bugs/page.tsx"`、`… "frontend/app/(app)/notifications/page.tsx"` —— 三处全部命中。
  - `rg -n "\"/projects\"" frontend` —— **零命中**（评审 R4：只允许经 `PROJECTS_KEY` 常量引用）。
  - `rg -n "as any" frontend` —— 零命中。
- [ ] `README.md` 与 `.claude-index/index.md` 已同步新符号与新参数。
- [ ] 以 `feat:` 前缀**精确 `git add`** 提交（**禁止 `git add -A`** —— 工作区含 `.claude-index/`、`CLAUDE.md` 等非本轮工具文件）。

---

## 7. Risks & Mitigations（风险与缓解）

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R1 | **`?project_id=abc` 等畸形过滤值由静默忽略改为 400**，属对外收紧 | 依赖旧宽松行为的调用方会 400 | 已核验：`grep -n "project_id" backend/tests/*.py` 仅 4 处命中（`conftest.py:52,72` 造数、`test_requirements.py:16` 断言不存在项目→400、`test_validation.py:55` 断言 `[1]`→400），**无一处依赖宽松过滤**；前端改造后只传合法值。实现者落地前**必须**重跑该 grep。与前两轮「坏输入一律 400」契约一致。 |
| R2 | 选中具体项目后存量 `NULL` 单不可见，用户误判「数据丢了」 | 高频误解，直伤「页面能正确使用」 | §2.4⑧ 三重守卫（默认全部 + 显式「未归属」+ 建单继承 scope）。**C2 为硬性验收项**。 |
| R3 | `localStorage` 在 SSR 阶段不存在，误在 `useState` 初始化中读取会 hydration mismatch | 首屏 React 水合错误 | §2.4④ 明确要求在 `useEffect` 内读取，初值恒 `null`。实现者不得走捷径。 |
| R4 | Agents 页仍以 `limit=200` 估负载，Agent 在制单 > 200 时计数偏低 | 仅影响一个展示计数 | 本轮有意不改（§2.3④）。正解是后端加计数端点而非前端分页，留待未来。 |
| R5 | `project_id` 无索引，大库下按项目过滤走全表扫描 | 单机 SQLite 万级以内无感 | 零 schema 变更红线内不加索引，记录为已知取舍。 |
| R6 | `keepPreviousData` 让翻页瞬间显示上一页数据 | 观感上「按了没反应」 | `<Pagination disabled={!data}>` 在取数期间禁用按钮。**不得**因此退回骨架闪烁方案。 |
| R7 | 项目切换器与 `projects/page.tsx` 共用同一 SWR key，互相影响 | 新建项目后切换器立即出现新项 —— **实为期望行为** | 明确写入设计：`projects/page.tsx` 的 `mutate()` 天然刷新切换器。实现者**不得**为切换器另起 key（否则新建项目后下拉里看不到它）。**【评审 R4】机制上锁死**：两处一律 import `lib/api.ts` 的 `PROJECTS_KEY` 常量，任何一处写字面量都在 §6.4 的 `rg -n "\"/projects\"" frontend` 复核里被抓出。 |
| R8 | **G1 给 `/users`、`/agents`、`/projects` 加分页会引入默认 50 条上限** | 团队 > 50 人时 `AssigneePicker`、团队页会静默截断 —— **这是把一个缺陷换成另一个** | **必须同时**核对全部消费方（`AssigneePicker.tsx`、`team/page.tsx`、`projects/page.tsx`、`agents/page.tsx`、`lib/project-scope.tsx`）并显式传 `?limit=200`，或**将 G1 整项延后**。若时间紧张，**优先延后 G1**——它是 P2，而截断是 P1 级别的伤害。**【评审 R4】`/projects` 一侧的改法唯一**：只改 `PROJECTS_KEY` 常量的值为 `"/projects?limit=200"`，**不得**逐消费点各自拼串（否则 R7 立即失效）。 |
| **R13** | **【评审 R1 新增】`want_query_int` 落地不全** —— 只改了 `project_id` 而没改 `paginate` / G2 的整数过滤参数 | `?offset=<超界>` 这条**波及每一个列表端点**的 500 依然存在，D3 不通过，本轮「零 500」的核心主张落空 | ① 收口点集中在 `services/scope.py` 一处，接线点仅 3 个（`pagination.py`、两个列表路由）；② §6.4 增加静态判据 `rg -n "args\.get\(.*type=int" backend` 必须零命中；③ D3 是硬门槛验收，7 条请求逐条断言。 |
| **R14** | **【评审 R1 新增】`QueryParamError` 全局处理器未注册 / 注册晚于蓝图** | 异常直冒到 `errors.py` 的兜底 `Exception` handler → **仍是 500**，且日志里看起来像未知崩溃 | `register_error_handlers(app, jwt)` 现网在 `app.py:37`、蓝图注册在 `:41`，**顺序天然正确**，只需在该函数内追加一个 handler（与 `ValidationError` 紧邻）。`test_hardening_r3.py` 覆盖点 ⑧ 即为其回归护栏。 |
| R9 | §2.5 改 position 分组后，既有数据同列出现编号空洞 | 无可见影响（只要求列内单调） | `_reindex_column` 在下一次 move 时自动重排连续。已在 §5 记录，不做迁移。 |
| R10 | §2.7 删单删审计会让 `activities_this_week` 下降 | 仪表盘数字变化 | 这是**更正确**的语义（统计不应包含已不存在实体的活动）。须写进 §4-⑪ 与 README，并在 `test_stats.py` 断言其行为明确。 |
| R11 | §2.2 的交接泛化改变了「哪些状态会自动换人」 | 若某状态被误判为单解，会出现非预期换人 | 派生表**必须**在 `test_agent_autopilot.py` 中逐项断言（§3.2），锁死为 7 条；未来给 `AGENT_FORWARD` 加边时该断言会立刻失败，形成护栏。 |
| R12 | 本轮变更面较大（22+ 文件） | 一次性落地风险高 | §9 给出**严格按 P0→P1→P2 的分段实施序**，每段独立可门禁、可提交；P2 段（§2.9）整段延后不影响前面任何验收项。 |

---

## 8. 有意不做（Out of Scope）与理由

1. **项目成员制 / 项目级 RBAC**：需新表 `project_members` 与全面授权改造，越过零新表红线；本轮需求是完善现有功能而非新增权限模型。
2. **项目编辑 / 删除 / 归档**：后端只有 `list`/`create`/`get`，前端**不放假按钮**，延续 `projects/page.tsx:4` 既定原则。
3. **工单跨项目搬迁**：`PATCH /<id>` 目前不接受 `project_id`；改动会牵动 §2.5 刚收窄的 position 语义（需在两个项目列间各重排一次），风险与收益不匹配。
4. **`/search` 与 `/me/work` 的项目过滤**：全局搜索的语义就是「全局」，「我的工作」的语义是「与我相关的一切」，按项目切片与其命名相悖。
5. **`recent_activities` / `activities_this_week` 按项目过滤**：`activities` 无 `project_id`（§5），需 `JOIN` 回两张工单表并分别处理 `entity_type`，属过度设计。
6. **`assign` / `convert-to-bug` 的乐观并发守卫**：`check_concurrency` 目前只接在 `patch` / `move`，两个 PM 同时改派会静默后写胜出。是真实缺口但属**并发正确性**主题，与本轮「规模与维度」不同轴，且需要前端同步传 `expected_updated_at`。**建议列为下一轮首选项。**
7. **`new → assigned` 允许无 assignee 造成的孤儿单**：`PATCH /move {"status":"assigned"}` 对未指派单返 200，而 `_claim_from_lane` 只扫 `new`/`open`，该单不会被任何 Agent 认领。修复须动 `workflow` 邻接表或给 move 加前置校验，**触碰「状态机是圣域」**，须单独设计与评审，不在本轮夹带。
8. **`notify_comment` 的 N+1 扇出**：每条新评论都会加载该单**全部**历史评论并按参与者逐个插通知（`services/notifications.py:100-115`）。长讨论串下每条评论写入数十行。属性能主题，非正确性缺陷，留待专门一轮。
9. **【评审 R11 补充】看板端点的分页 / 上限**：`GET /api/board/*` 一次取全表分组返回（`board.py:20`），**本轮不加分页也不加上限**。理由：看板的语义就是「看见该列的全部卡」，分页看板反而破坏拖拽重排的正确性（跨页拖拽无定义）；且 §2.4 的项目过滤已经把单看板的数据量按项目切小。**这是有意取舍而非漏审** —— 若未来单项目单列超过千张卡，正解是列内虚拟滚动 + 列级懒加载，属独立主题。

---

## 9. 审计核验说明与假阳性剔除

**核验强度**：后端每一条缺陷均在**实际启动的 Flask 应用**（`TestConfig` 内存 SQLite，未写任何文件）上复现，记录了真实的状态码与异常类型；前端每一条均给出 `file:line` 与可执行的操作步骤。

**经核验后剔除的假阳性**（记录于此，避免下游重复调查）：

- `paginate()` 的 `limit=0 / -5 / abc`、`offset=-5` —— 已正确钳制到 `[1,200]` / `0`。
- 对不存在工单的评论 / feed —— `_get_entity_or_404` 干净返 404。
- `POST /api/bugs` 带不存在的 `related_requirement_id` —— 已在 `bugs.py:88` 校验返 404。
- 删除有转出 BUG 的需求 —— `related_requirement_id` 先置空（`requirements.py:255`），`PRAGMA foreign_keys=ON`（`extensions.py:29`）确实生效，无 FK 违规。
- `move` 传非串 / 列表 `status`、`position` 为 `"2"` / `null` —— 均已被 `want_str` + `_coerce_index` 兜住。
- 通知 RBAC —— 他人通知正确 403；`read-all` 已按 `user_id` 收敛。
- `board.py:25` `setdefault` 与 `stats.py:25` `counts.get` —— 对列集合外状态均 KeyError-safe。
- `services/llm/providers.py` 全部网络 / HTTP / 解码 / 解析路径已归一为 `LLMError`，无 5xx 泄漏路径。
- `me.py::_apply_profile` 在 400 前的部分改写 —— 未持久化（Flask-SQLAlchemy teardown 回滚）。
- `errors.py:41` 的 500 回滚存在，故 §2.6 的那些 500 不会污染下一个请求。
- 前端：`FeedTimeline` 的 `item.author.name`（后端 `_resolve_author` 恒返 dict）、`PRIORITY_STYLES[...]` 越界（`Badge.tsx:10` 有 `FALLBACK_STYLE`）、Modal 未重置表单（`Modal.tsx:72` 关闭即 unmount）、`toLocaleString` 水合失配（均在 SWR 数据后渲染）、SWR 同 key 异 fetcher 形状冲突（已复核 `/users` `/agents` `/stats` `/board/*` `/me/work` `/search` 全部一致）、`MENTION_RE` 的 `lastIndex` 泄漏（仅经无状态的 `matchAll` 消费）、`lib/toast.tsx` 每次渲染重建 `api` 对象（无 `useEffect` 依赖它）—— **均为假阳性，不予处理**。

---

## 10. 实施顺序建议（供 Subtask #2 · 严格按 P0→P1→P2，每段独立可门禁）

**第 1 段 · P0 主流程（最高优先，独立可提交）**
1. §2.2①②：`_KIND_FOR_STATUS` 派生 + `maybe_handoff`（含**人类持单守卫**）+ 两处调用点改名 → `pytest -q`（既有 244 例应仍全绿，**这是最强的回归信号**）。
2. §2.2③④⑤：接进 `do_agent_advance` / `_agent_run_all`、generic 不再认领、`claim-next` 门禁 → 更新 `test_agent_autopilot.py` → `pytest -q`。**此时 A1–A4 即可验收。**
3. §2.3：`ui/Pagination.tsx` → 接需求页 → `typecheck` → 接 BUG 页、通知页。**此时 B1–B4 即可验收，本轮两个 P0 已清零。**

**第 2 段 · P1 项目维度（依赖第 1 段无，可并行开发但建议串行落地）**
4. §2.5：`_next_position` / `_reindex_column` 加**必填** `project_id`（**含 `agent_runner.py` 内联副本**）→ `pytest -q`。**必须先于 §2.4 落地**——否则接上项目过滤的看板会立刻出现「拖了没反应」。评审 R3 后漏传即 `TypeError`，`pytest` 是此步的完整护栏。
5. §2.4①①'②③：`services/scope.py`（**含 `want_query_int`**）+ `errors.py` 全局处理器 + `pagination.py` 接线 + 四端点 + `_by_status` → 写 `test_project_scope.py` / `test_stats.py` → `pytest -q`。
   > **【评审 R1】`want_query_int` 与全局处理器必须在这一步一次落地**，不得拆到第 3 段 —— §2.4 的 `project_scope()` 一旦上线而边界没跟上，`?project_id=<超界>` 的 500 就从「历史遗留」变成「本轮新引入」。
6. §2.4④⑤⑥⑦⑦'⑧：前端 scope + 切换器 + 逐个消费点 + **不受控视图的作用域标注（评审 R5）**，每接 1–2 处跑一次 `typecheck`。**此时 C1–C8 可验收。**

**第 3 段 · P1 稳健性与诚实 UI**
7. §2.6（超界 id 三点式中的 A/B 两点——C 已在第 5 步落地、四处 `description`、`max_len`）+ §2.7（删单级联删审计）→ 写 `test_hardening_r3.py` → `pytest -q`。**D1、D2、D3 可验收。**
8. §2.8（看板 RBAC + `lib/permissions.ts`、铃铛双向同步、铃铛与偏好卡错误态）→ `typecheck`。**E1、E2 可验收。**

**第 4 段 · P2（整段可延后，各项彼此独立）**
9. §2.9 前端 H6（**触屏误触不可逆操作，此项应提到 P1 优先级之后立即做**）→ H1 → H3 → H4 → H2 → H5 → H7。
10. §2.9 后端 G3（软锁泄漏，收益/成本比最高）→ G2 → G4 → **G1 最后，且须先落实 R8 的消费方核对，否则宁可不做**。

**收尾**
11. `npm run build` + §6.3 全量手工冒烟（**A1、C6、C8、D1、D3 与第 2 轮的 `autorun-all` 闭环最后再各跑一遍**）。
12. 更新 `README.md` 与 `.claude-index/index.md` → 执行 §6.4 的复核清单 → 精确 `git add` → `feat:` 提交。

---

## 评审结论（Review Verdict）

### 结论：**有条件通过**（Approved with Conditions）

评审员按**可行性 / 完备性 / 一致性 / 尺度**四维逐节复核了 v1，并独立复跑了其核心复现。结论是：**这份设计的问题诊断是可信的、方案主干是正确的、尺度是克制的，可以进入实施**——但必须带着下列条件。

**四维评价**

| 维度 | 评价 |
|---|---|
| **可行性** | **好。** 全部改动都在现有技术栈内：`BoundedIntConverter` 的父类越界语义、SWR 2.x 的 `keepPreviousData` 与函数式 key 过滤、`AGENT_FORWARD` 的键集派生，评审员逐项核对了现网源码与 `package.json`，**无一处基于错误假设**。唯一的可行性缺陷是 R6（`want_int` 已有同名形参，实现方式若不精确会被调用方覆盖），已就地写死。 |
| **完备性** | **v1 有一处硬伤，已修复。** R1：「超界整型 → 500」有**三条**独立路径，v1 只收了两条，遗漏的第三条（查询串）经实机复现有 **5 个端点今天在返 500**，且 v1 版 `project_scope()` 会把其中一个**带进新代码**——这使本轮自设的硬门槛 D1 不可达。R5 是另一类完备性缺口：全局作用域指示器只治理部分视图却不作提示，等于本轮亲手造出第五处「静默说谎 UI」。两者均已在正文补齐并加了对应验收项（D3、C8）。 |
| **一致性** | **好，两处已修正。** 与 `CLAUDE.md` 的三条硬约定（状态机是圣域、向后兼容、Windows/PowerShell）中，前两条 v1 守得很严（交接只动多态 assignee、零新表、成功路径 shape 不变）；第三条在 §6.4 的 grep 清单上破了（bash 专属语法，R7）。另有 R2（代码块与其下方散文自相矛盾）与 R4（`/projects` key 在三处互相冲突）两处**文档内部**不一致，均已消除。 |
| **尺度** | **恰当。** 5 个新文件、~24 个改动文件、3 个新测试文件，对应四类实机复现的缺陷，没有发明新业务概念、没有新表、没有新依赖。§8 的 8 项「有意不做」理由充分（评审补入第 9 项）；§7-R12 的 P0→P1→P2 四段实施序让每段独立可门禁，是本文档最有价值的风险控制设计。**未发现过度设计。** 唯一需要警惕的是 §2.9-G1，v1 自己已给出「宁可延后」的判断，评审同意。 |

**放行条件（下游 Subtask #2 必须逐条满足，缺一即视为未完成）**

1. **【R1 · P0】三点式必须全部落地。** `services/scope.py::want_query_int` + `errors.py` 的 `QueryParamError` 全局处理器 + `pagination.py` 接线，三者**在第 2 段第 5 步一次落地**，不得拆散、不得延后。验收以 §6.3-**D3** 的 7 条请求为准，并以 §6.4 的 `rg -n "args\.get\(.*type=int" backend` **零命中**为静态判据。
2. **【R2 · P1】`maybe_handoff` 的人类持单守卫必须在函数最前、在 `db.session.get(Agent, …)` 之前。** 以 §6.3-**A3** 验收。
3. **【R3 · P1】`_next_position` / `_reindex_column` 的 `project_id` 必须是无默认值的必填位置参数**，§2.5 列出的 8 处调用点（**含 `agent_runner.py` 的同名内联副本**）全部显式传参。以 `pytest` 全绿 + §6.3-**C6** 验收。
4. **【R4 · P1】`/projects` 的 SWR key 只能经 `lib/api.ts::PROJECTS_KEY` 引用**，前端不得出现 `"/projects"` 字面量。以 §6.4 的 `rg -n "\"/projects\"" frontend` 零命中验收。
5. **【R5 · P1】不受项目作用域约束的五类视图必须带可见标注。** 以 §6.3-**C8** 验收。
6. **【R6 · P1】`want_int` 的 64 位硬界必须无条件生效**，不得实现为 `minimum`/`maximum` 的默认值；并断言 `validation` 与 `scope` 两处常量相等。
7. **既有 244 个 pytest 用例除 §2.2④ 明确须按新语义更新的 generic 认领断言外，必须逐条保持全绿**——这是第 2 轮零回归的最强信号，任何一条变红都必须先解释再继续。
8. **若时间不足，允许整段砍掉第 4 段（§2.9 全部 P2）**，但 **H6（触屏误触不可逆的「转 BUG」）除外**——它是安全性问题，须随第 3 段一并落地。**G1 按 §7-R8 默认延后**，除非其 5 个消费方全部核对完毕。

**不阻塞放行、但须在实施中留痕的观察**

- R8（超界 id 的 404 体是英文 `{"error":"Not Found"}`）为**已接受的取舍**，不要求处理，但不得被后续轮次误判为新缺陷。
- R9 / R10 / R11 三条 P2 已在正文就地写清，实施时顺手带上即可，不单独设门禁。
- §8-6（`assign` / `convert-to-bug` 缺乏乐观并发守卫）是评审员认同的**真实缺口**，v1 建议「列为下一轮首选项」——评审确认这个判断，建议下一轮以「并发正确性」为主题独立成轮。

**P0 / P1 残留**：**0 条**。R1–R6 全部已在本文档正文就地修复，修复点在「评审记录」表的「已修复」列逐条给出。

---

*—— 评审于 v2 完成。本文档现为下游实施的唯一依据；实施过程中若发现与本文档冲突的现网事实，以现网为准并回写本文档，不得静默偏离。*

---

## 实施过程发现的方案缺陷（Issues Found During Implementation）

> 记录人：Subtask #2 · Implementation Engineer ｜ 基线：spec v2 + 现网 `de5bd0a`
> 按 §「Constraints」的要求：发现设计有误 / 不完整时不静默偏离，在此登记并说明**已采用的修正方案**。
> 全部 4 条均已在本轮代码中落地并有测试覆盖。

| # | 严重度 | 缺陷 | 采用的修正 |
|---|---|---|---|
| **F1** | **P1（文档内部自相矛盾，会让 D3 与 §2.4 二选一）** | §2.4① 的 `paginate` 接线要求 `limit` 改走 `want_query_int("limit")`，而 `want_query_int` 对超 64 位值**抛错 → 400**；但 §2.6①-C 的表格与 §6.3-**D3** 的对照组同时钉死「`?limit=<超界>` 仍 **200**（已被钳到 200 条），安全，无需处理」。照 §2.4 逐行实现会让 D3 的对照组断言失败；照 D3 实现又留下 `type=int`，破坏 §6.4 的静态判据（`args.get(.*type=int)` 零命中）。 | 给 `want_query_int` 增加 `clamp: bool = False` 形参：**`clamp=True` 时越界钳到界内而非报错，非整数仍恒 400**。`paginate` 以 `want_query_int("limit", default=50, minimum=1, maximum=200, clamp=True)` 接线 —— 既保住 `limit` 的既有钳制语义（D3 对照组 200）、又兑现 G2（`?limit=abc` → 400）、还让静态判据零命中。判据依据：`limit` 语义是**上限**而非取值，它从不作为主键绑进 SQL，因此不需要「拒绝」而只需要「钳制」；`offset` / `assignee_id` / `reporter_id` / `project_id` 会真正进 SQL，仍走默认的 `clamp=False`（400）。同一处理另行覆盖了 §6.4 漏列的 `routes/search.py:25`（`?limit=` 的第 6 处 `type=int`）。覆盖测试：`test_hardening_r3.py::test_limit_clamping_semantics_preserved`。 |
| **F2** | **P1（收口不完整，D1/D3「零 500」不可达）** | §2.6①-B 把 `PATCH /requirements/<id>/assign {"assignee_id": <超界>}` 归为「请求体路径，由 `want_int` 一处覆盖」。**但该路径根本不经 `want_int`**：第 2 轮评审 R4 明确裁定 `assign` 保留 `_validate_assignee`（有意容忍数字串 `"5"`），其内部是裸 `int(assignee_id)` + `db.session.get`（`requirements.py:88-91`）。实机复现：落地 `want_int` 硬界后该请求**仍然 500**（`OverflowError`）。 | 在 `_validate_assignee` 内独立复述一次 64 位硬界（`from services.scope import MIN_DB_INT, MAX_DB_INT`），越界返 400 且 `detail` 与既有契约同形。**有意不改回 `want_int`** —— 那会打破第 2 轮 R4 的裁定（数字串容忍）。docstring 已注明这是「三点式之外的第四个入口」，改动任一侧须同步。覆盖测试：`test_hardening_r3.py::test_oversized_body_ids_return_400`。 |
| F3 | P2（DoD 判据过宽，会误报） | §6.4 的复核项 `rg -n "\"/projects\"" frontend` 要求**零命中**，但该字面量还有两类**与 SWR key 无关**的合法用途：`api.post("/projects", …)` 的**请求路径**（`ProjectFormModal.tsx:45`）与 `Sidebar.tsx` 的**导航 href**。按字面执行会把这三处误判为违规并被改坏。 | 判据收窄为「**`useSWR(...)` 的第一参不得出现 `/projects` 字面量**」。落地上：`lib/api.ts` 导出 `PROJECTS_KEY`（并同理新增 `USERS_KEY` / `AGENTS_KEY`，因为 G1 给这三个列表都加了分页），全部 SWR 读取点一律 import 常量；请求路径与 href 保持原样。复核命令改为 `rg -n "useSWR<[^>]*>\(\"/" frontend` 零命中。 |
| F4 | P2（G1 的连锁影响未在文档中收敛） | §7-R8 只讨论了「G1 会给 `/users`、`/agents`、`/projects` 引入默认 50 条上限」，但**没有提到 `agents/page.tsx::revalidateAll()` 用的是一张写死的字面量 key 清单**（`"/agents"`、`"/stats"`、`"/board/requirements"` …）。§2.4 让这些 key 全部可能带 `?project_id=` / `?limit=` 后缀后，该清单会在切换项目后**静默漏刷**——运行完 AI 团队一轮，看板与统计不更新。 | `revalidateAll()` 改为**前缀函数式 key 匹配**（SWR 2.x），覆盖 `/agents`、`/requirements`、`/bugs`、`/stats`、`/board/`、`/notifications` 六个前缀。同款问题在 §2.8② 已被评审 R9 识别过（不把常量硬编码进匹配串），此处是同一原则的第二个落点。 |

**未构成缺陷、但实施时做了收敛的两处**（记录以免下游误判为偏离）：

- §2.9-**G1 未按 §7-R8 延后，而是完整落地**。理由：R8 要求「先核对全部消费方」，而消费方仅 5 个且全部可静态定位（`AssigneePicker` / `team` / `projects` / `agents` / `lib/project-scope`）。落地方式是统一改走 `USERS_KEY` / `AGENTS_KEY` / `PROJECTS_KEY` 三个常量（值均为 `?limit=200` = 后端 `MAX_LIMIT`），因此不存在「漏改一处 → 静默截断 50 条」的风险面。收益是三个列表终于有 `X-Total-Count`（`listFetcher` 契约成立）与上界。
- §2.9-**G3 的 `rollback` 补在了两处**：`routes/agents.py::_run_with_lock` 与 `routes/requirements.py::_agent_run_all`（§2.9-G3 原文即要求「两处都改」，此处仅确认已执行）。
