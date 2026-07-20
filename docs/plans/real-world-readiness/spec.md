# AragonTeam 真实世界就绪（Real-World Readiness）Spec

> 第 5 轮。前四轮闭合的分别是「点了会报错」（reliability-hardening）、「功能跑不通 / 页面在异常下不可用」
> （feature-completeness）、「数据一多就够不着 + 项目维度没贯通」（scale-and-project-scope）、
> 「做错了没有回头路」（lifecycle-and-governance）。
> **本轮闭合的是：在真实规模、真实设备、真实安全预期下，这套系统还成不成立。**
>
> 版本：**v2（已评审）** ｜ 作者：Subtask #0（Solution Architect）｜ 评审：Subtask #1（Design Review）
> ｜ 面向读者：Subtask #2（实施）
> 基线（本轮开工前实测，非引用文档）：`pytest -q` → **342 passed, exit 0**；
> `tsc --noEmit` → **0 error**；`next build` → **16/16 页成功**。
> 评审复核：`pytest -q` **342 passed / exit 0 已由评审独立重跑确认**（不是引用 v1 的数字）。
> 工作树状态：第 4 轮（lifecycle-and-governance）代码**已实现但尚未提交**，本轮在其之上继续。

---

## 评审记录（Design Review · v1 → v2）

**评审方法**：不采信文档自述。评审对 v1 引用的每一个源码锚点做了一手核验
（`routes/requirements.py` 的 5 个公共辅助签名、`errors.py:75` 的 blocklist 钩子实体、
`services/lifecycle.py` 的实际导出、`seed.py` 的幂等分支、`tests/conftest.py` 的既有 fixture、
`frontend/lib/swr-keys.ts` 的函数签名、`lib/api.ts` 的 fetch 实现、`app/(app)/layout.tsx`、
`services/workflow.py` 的看板列数），并独立重跑了 `pytest -q`（342 passed / exit 0）。
随后把评审重心放在**「如果有人逐字实现这份文档，会发生什么」**——v1 的缺陷诊断经核验基本属实，
问题几乎全部出在**修复方案本身**上。

**v1 诊断的准确性**：抽查的每一条都成立。特别确认了两条 v1 自我否决 / 自我提示的判断是对的，
实施时不要再翻案：① `seed.py::seed_if_empty` 第一行就是 `if User.query.count() > 0: return False`，
所以 `set_password` 只在空库首启时跑，§2.3 「seed 无副作用」的结论**成立**；
② 全仓 `grep project_id` 确认前端只有 `RequirementForm` / `BugForm` 的**创建**路径传该字段，
`PATCH /:id` 收紧对现有客户端**确实零影响**。

| # | 维度 | 严重度 | 问题 | 处理 |
|---|---|---|---|---|
| R1 | 完备性 | **P0** | **本轮的核心护栏是空的**：§2.4-C3 的查询预算用例在**未修复的代码上也会通过**。`tests/conftest.py::bulk_tickets` 造出的单 `assignee_type=None`，而 `_resolve_assignee` 对未指派**第一行就 `return None`、零查询**——120 张无 assignee 的卡在今天的 N+1 代码上也只有十几条查询。v1 声称的「今日 115」只在**带 assignee** 的数据集上成立。护栏必须先在旧代码上红 | 已修：§2.4-C3 / §6.1 明确要求预算用例的数据**必须带互不相同的 assignee**，`bulk_tickets` 追加 additive 的 `assignees` 参数；新增 **T-C0「护栏自证」**：实施者必须在打补丁前跑一次并记录红值 |
| R2 | 可行性 | **P1** | §2.2 的 `assert_project_writable` 调用了 `_iso(project.archived_at)`，但 `services/lifecycle.py` **根本没有 `_iso`**（全仓 8 份 `_iso` 都在 `models/*` 与 `routes/comments.py` 里）。逐字实现 = `NameError`，且 v1 的补救建议「用 models 里同名实现」会诱导第 9 份副本或跨模块 import 私有名 | 已修：改用 `project.to_dict()["archived_at"]`——复用模型自己的公开序列化器，零新助手、零私有导入 |
| R3 | 可行性 | **P1** | §2.2-A4 与 §4.4 都写成 `invalidateTicketViews()`，但 `lib/swr-keys.ts:33` 的签名是 `invalidateTicketViews(mutate: ScopedMutator)`——**逐字实现 `tsc --noEmit` 必红**，直接打掉 §6.2 门禁。同时 v1 把失效放进 `useTicket`，与该文件既定分工相反（`remove` 的注释逐字写着「由调用方失效外层列表 / 看板」）；且 v1 的 URL 模板 `` `/${entity}s/${id}/project` `` 多了一个 `s`——`entity` 本就是复数（`"requirements" \| "bugs"`），逐字实现会请求 `/requirementss/3/project` 并 404；且改派写审计却没刷 feed，抽屉时间线看不到刚发生的事 | 已修：§4.4 整段重写——`moveProject` 与既有 `patch()` 同形（只落工单 + feed 两个 key），跨视图失效由 `TicketDrawer`（已持有 `useSWRConfig`，第 60 / 182 行）在成功回调里做 |
| R4 | 完备性 | **P1** | 承 R3：改派会改变项目的工单计数，而本轮 P2-4 刚给项目页加上计数列——`TICKET_VIEW_PREFIXES` **不含 `/projects`**，于是「移动完，项目页计数还是旧的」。这正是本轮要消灭的「页面说假话」，却由本轮自己新造一处 | 已修：成功回调追加 `invalidateAdminViews(mutate)`（其前缀含 `/projects`），并加验收 A-10 |
| R5 | 可行性 | **P1** | §2.4-C3 的看板阈值 **25 算错了**：`services/workflow.py:23` 的需求看板是 **7 列**（不是 6，含 `bug_fixing`），且 `board_page.column_page` 在**循环内**就 `to_dict()`，预热只能逐列做 → 最坏 7×(1 页查询+1 计数+2 身份)=28，加鉴权钩子 ≈ 30 > 25。**正确实现也会红**，而实施者最省事的反应是去放宽护栏——护栏就此报废 | 已修：§2.4 改为「先收全列的行 → `prime()` 一次 → 再序列化」，身份查询降到全看板 ≤2；阈值 25 的推导重算（7+7+2+鉴权≈17）并逐项写出 |
| R6 | 可行性 | **P1** | §2.4-C3 的 `count_queries` 里 `event.remove(db.engine, "before_cursor_execute", ...)` 的 `...` 是**字面省略号**，且 lambda 无法被 `remove` 引用——逐字实现直接 `SyntaxError`/监听器泄漏到后续用例 | 已修：给出可直接粘贴的实现（具名 `_on_exec` + `try/finally` 移除） |
| R7 | 一致性 | **P1** | §3.2 要求新建 fixture `many_tickets`，§2.4 的示例用例签名是 `(client, auth_pm, many_tickets)`——**这三个名字在仓库里都不存在**：既有的是 `bulk_tickets(n, status, project_id)`、`auth(role)` 与 `archived_project`（均在 `tests/conftest.py`；**按名字找，别按行号**——见 R14，并行工作流已经把这个文件的行号推移过一次）。逐字实现要么报 fixture 未找到，要么造出第二份批量造单器——正是本文件 §3.1 自己引用的「`_next_position` 双份副本」教训 | 已修：§3.2 / §6.1 全部改为**复用**既有 fixture，`bulk_tickets` 只做 additive 扩展 |
| R8 | 完备性 · 安全 | **P1** | 吊销文案说假话：§4.2 有意复用 `account is disabled or removed`。用户在手机上改完密码，笔记本上弹出「账号已被停用或删除」——**一句关于自己账号的假话**，而这轮的主题就是消灭假话。更实际的是：admin 走 `PATCH /api/users/<自己>` 重置自己的密码（团队页现成入口，`routes/users.py:103` 无自我豁免）会**当场把自己登出**并看到同一句假话 | 已修：`_revoked_token` 按原因分流文案（停用/删除 vs 改密）；§2.3 补 admin 自重置的显式说明与前端确认文案；新增 T-B7 |
| R9 | 完备性 | P2 | §2.2 的幂等短路排在归档守卫**之后**：把归档项目里的单「移动到它自己所在的项目」会得到 409，与 T-A4「归档只拦放进去」的口径轻微打架 | 已修：幂等判定前置到守卫之前 |
| R10 | 完备性 | P2 | `PATCH /:id` 上两条新 400（`project_id` 指路 / 无可识别字段）的**判定顺序**未定义，而 `{"project_id":2}` 同时命中两者；顺序反了 T-A13 的指路断言就会挂 | 已修：§2.2 / §4.2 写死「先判 `project_id` 指路，再判无可识别字段」 |
| R11 | 完备性 | P2 | P2-1 的超时落点不够精确：`lib/api.ts` 现有 `catch` 把**一切** fetch 异常映射成「无法连接服务器」，`AbortError` 会被吞掉；且 `getWithHeaders` 是**第二个** fetch 点；且必须 `clearTimeout` | 已修：§2.6 给出三条落地约束 |
| R12 | 一致性 | P2 | `identity.summary()` 把缓存里的**同一个 dict 实例**发给同一请求内的 N 行；今天全仓无人就地改这个 dict（评审已 grep 确认 `["assignee"]` / `["author"]` / `["actor"]` 均无写入），但一旦有人改就是**跨行静默污染** | 已修：`summary()` 返回浅拷贝，并在 docstring 写明理由 |
| R13 | 右尺寸 | P2 | 需求被改派后，它转出的 BUG（`related_requirement_id`）仍留在原项目，形成跨项目关联 | 已记入 §9 为**明确取舍**（不做），避免实施者顺手「修」出一个未经设计的级联 |
| R14 | 一致性 | **P1** | **v1 的 R-15 风险在评审期间就兑现了**：并行工作流（`data-persistence-and-seed-slimming`）已经把代码**落进同一个工作树**，`git status` 现显示它改了 `backend/tests/conftest.py`、`models/user.py`、`models/requirement.py`、`routes/requirements.py`、`errors.py`、`app.py`——全部是本轮的落点；且它已经把 `CLAUDE.md` 的质量门禁改成**「相对判据：记录基线，要求零失败且用例数不下降」**并显式写明「93 是陈旧的、现已 380+」。于是 v1 的 P2-3（把 CLAUDE.md 改成写死的实测值）会**回退**别人刚落地的约定，而 §6.4 的「≥370 例」这个绝对数字既与新约定冲突、也已被现实超过 | 已修：P2-3 缩到只剩 `.claude-index/index.md`；§6.4 改为相对门禁（开工前自测基线，要求零失败且用例数不下降）；§7 R-15 升级为**已发生**并给出具体冲突文件清单 |

**未采纳的候选（评审自我否决，记录以免下游重复劳动）**：
① 「`set_password` 收敛会让每次重启 seed 都踢人下线」——查 `seed.py:26` 的幂等前置，**不成立**；
② 「`Agent.summary()` 含 `status`，`autorun-all` 单请求内改状态会读到缓存陈旧值」——查
`models/agent.py:35`，`summary()` 只有 `type/id/name/kind`，**不成立**；
③ 「`models` → `services.identity` 会成环」——`services/__init__.py` 只有一行包标记（63 字节），
不 import 任何子模块，**不成立**；
④ 「`_validate_project` 换成 `assert_project_writable` 会破坏调用方」——两者都是
「可用返回 `None`，否则返回 `(响应, 码)`」，`routes/requirements.py:213` 的
`perr = ...; if perr: return perr` 逐字兼容，**不成立**。

---

## 0. 摘要：本轮为什么是这五类缺陷

前四轮把「用户点得到的东西」修得相当干净：坏输入不再 500、每页都有错误态、列表翻得到、
项目维度贯通，删除 / 停用 / 归档都有回头路。于是我在本轮开工时先问了一个不同的问题——
**「把这套东西真的拿去用，会在哪里散架？」**——然后逐条上机复现，而不是读文档推测。
答案落在五个前四轮从未触及的方向上，每一条都在一个真实运行的 Flask 应用
（`TestConfig` 内存库 + 真实 JWT + `app.test_client()`）或真实源码行上复现过：

| # | 类别 | 一句话 | 严重度 | 一手证据 |
|---|---|---|---|---|
| A | 功能断链 | 工单**不能**在项目之间移动，而 `PATCH /:id` 收下 `project_id` 后**静默忽略并返回 200**；产品自己的文案却在教用户「把工单移到别的项目」 | **P0** | `PATCH /api/requirements/3 {"project_id":2}` → `200`，响应体 `project_id` 仍为 `1`；`frontend/app/(app)/projects/page.tsx:209` |
| B | 安全 | 改密码 / 管理员重置密码**不吊销**任何既有会话，被盗的 token 继续可用（默认 24h） | **P1** | 改密成功后旧 token `GET /api/auth/me` → `200`（期望 `401`） |
| C | 性能 | 多态 `assignee` / `author` 解析是**每行一次 SELECT** 的 N+1：一次看板请求 = 615 次查询 | **P1** | 2000 单库：`GET /api/board/requirements` → 615 queries / 195 KB / 135 ms |
| D | 可用性 | 全站**零响应式**：固定 `w-56` 侧栏 + `h-screen` 三段式，窄屏（手机 / 分屏 / 投屏）下每一页都不可用 | **P1** | `Sidebar.tsx:82` `w-56 shrink-0`；全仓 35 个 `.tsx` 中只有 7 个文件、共 12 处断点类 |
| E | 一致性 | 归档只在 UI 生效（API 仍收单）、抽屉把归档项目显示成裸 `#3`、`npm run lint` 声明了却跑不起来、`CLAUDE.md` 的质量门禁数字停在 93（实测 342）、前端请求无超时 | P2 | 见 §2.6 |

这五条有一条共同的形状，也正是本轮的判据：
**「在演示数据、宽屏浏览器、一个人用」的条件下它们全都看不出来；一旦换成真实数据量、真实设备、
真实的多人与安全预期，它们同时成立。」** 前四轮修的是「功能对不对」，本轮修的是
**「功能在真实条件下还对不对」**。

本轮同样遵守项目已确立的三条硬不变量：

1. **状态机是圣域**——`services/workflow.py` 的两张邻接表一字不动；本轮新增的「改项目」
   与删除 / 停用一样，**完全不触碰 `status`**。
2. **成功路径 shape 只增不改**——唯一的行为收紧是 `PATCH /:id` 收到 `project_id` 时
   由「静默 200」改为 **400 并指路**（§4.2 已登记；今日无任何前端调用点会命中）。
3. **零新表、零新运行时依赖**——新增的唯一一列 `users.password_changed_at` 走第 4 轮建立的
   `schema_sync.ADDITIVE_COLUMNS`（CLAUDE.md 的硬约束）；性能修复不引入缓存中间件，
   只用 `flask.g` 的请求内存化。

---

## 1. Overview（概述）

AragonTeam 已经是一个功能完备的 AI 协作研发平台：需求 / BUG 的全生命周期、看板、
Agent 自主认领与推进、通知、评论与 @提及、项目维度、成员与项目的生命周期治理，都已闭合。
**它现在缺的不是功能，而是「真实条件下的正确性」**——这正是从「能演示」到「能用」的最后一段距离，
也是本轮的全部内容。

本轮做五件事，且只做这五件事。

**第一件是把「项目」这个维度从只写不改变成可再组织。** 第 3 轮把项目维度端到端贯通、
第 4 轮给项目加上归档与删除之后，产品已经在多个地方向用户承诺「把工单移到别的项目」
（`projects/page.tsx:209` 的删除确认框逐字写着这句话），但**后端从来没有实现过这个能力**：
`PATCH /api/{requirements|bugs}/:id` 只识别 `title` / `description` / `priority|severity`
三个字段，传进来的 `project_id` 被无声丢弃，然后照样返回 `200` 和一个「看起来成功了」的完整工单体。
于是「归档项目 → 清空它 → 删除它」这条第 4 轮刚建立的治理链路，**断在最后一跳**：
项目里的单出不去，项目就永远删不掉；而归档本身又只在前端生效——直接调 API 仍然能往归档项目里
塞新单（实测 `201`）。本轮新增 `PATCH /api/{entity}/:id/project` 端点（pm/admin），
带上看板 `position` 的正确搬迁与审计，并把归档约束**下沉到后端**。

**第二件是把「改密码」变成真正的安全动作。** 第 4 轮为了让停用成员的既有 token 立即失效，
已经注册了 `jwt.token_in_blocklist_loader`（`errors.py:75`）——这个钩子把「按用户状态吊销 token」
的成本降到了几行。今天改密码（自助或管理员重置）**不吊销任何东西**：一个刚刚意识到密码泄露的用户，
改完密码之后攻击者手里的 token 依然能用满 24 小时，而产品什么都没告诉他。本轮加一列
`users.password_changed_at`，在 blocklist 钩子里与 token 的 `iat` 比对（实测 JWT 载荷含 `iat`），
并让改密接口**返回一枚新 token**，使「改密踢掉所有其它会话、但不踢掉自己」成为默认行为。

**第三件是把每行一次 SELECT 的 N+1 收口。** `_resolve_assignee`（`models/requirement.py:57`）
与 `_resolve_author`（`models/comment.py:50`）在序列化每一条记录时各做一次 `db.session.get()`。
实测（2000 需求 / 500 BUG / 60 评论）：一次 `GET /api/board/requirements` 触发
**615 次查询、195 KB、135 ms**；`GET /api/requirements?limit=200` 触发 **203 次**；
一条 60 评论工单的 `/feed` 触发 **124 次**。更关键的是，同一个请求内对同一个 id 的重复
`db.session.get()` **并不会被复用**（实测：连续三次 `db.session.get(User, 2)` = 3 次查询），
所以哪怕整块看板只指派给 2 个人，也照样发 600 次查询。第 3 / 4 轮的分页与列上限压的是
**页大小**，压不到**每行一次**这个系数。本轮新增 `services/identity.py`：请求内多态身份缓存
（`flask.g`）+ 批量预热，把上面三个数字压到常数级，并**用一条会数查询次数的测试把它焊死**。

**第四件是让每一页在窄屏下真的能用。** 应用外壳是 `flex h-screen overflow-hidden` +
一个 `w-56 shrink-0` 的固定侧栏（`layout.tsx` / `Sidebar.tsx:82`），全仓 35 个 `.tsx`
里只有 7 个文件、总共 12 处响应式断点类。在 390 px 宽的手机上，侧栏独占 224 px，
正文只剩 166 px——**每一页都不可用**，包括登录后的第一屏。本轮不做移动端重设计，
只做「窄屏可用性」：断点以下侧栏收进抽屉式导航、Header 折叠、所有表格进横向滚动容器、
看板列给出最小宽度并保持横滑。

**第五件是把一批「说了假话」的小事收干净**（§2.6）：归档提示与实际约束不一致、抽屉里
把归档项目显示成裸 `#3`、`package.json` 声明了一个跑不起来的 `lint` 脚本、
`CLAUDE.md` 与索引里的质量门禁数字停留在 93（实测 342）、前端请求没有超时因而后端假死时
UI 永远转圈。

做完这五件事之后，这句话应该成立：**把 aragon.db 换成一个装着几千张单的真实库、
把浏览器换成一台手机、把使用者换成一个刚刚改完密码的人——每一个功能仍然不报错，
每一个页面仍然能正确使用。**

---

## 2. Technical Design（技术设计）

### 2.1 架构 Delta（本轮新增的接缝）

```
backend/
  services/
    identity.py            ← 【新】请求内多态身份缓存（assignee / author 的唯一解析入口）
    schema_sync.py         ← 改：ADDITIVE_COLUMNS 登记 users.password_changed_at
    lifecycle.py           ← 改：新增 assert_project_writable（归档项目写守卫，单一真相）
  models/
    user.py                ← 改：+password_changed_at 列
    requirement.py         ← 改：_resolve_assignee 改走 identity.py（bug.py 共用此函数）
    comment.py             ← 改：_resolve_author 改走 identity.py
  routes/
    requirements.py        ← 改：+PATCH /:id/project；PATCH /:id 拒收 project_id；创建走归档守卫；列表预热
    bugs.py                ← 改：同构
    board.py               ← 改：序列化前预热身份
    comments.py            ← 改：feed 序列化前预热身份
    me.py / users.py       ← 改：改密 / 重置密码时打 password_changed_at 并签发新 token
    projects.py            ← 改：GET 支持 ?with_counts=1（additive）
  errors.py                ← 改：blocklist 钩子加 iat < password_changed_at 判据

frontend/
  components/
    TicketDrawer.tsx       ← 改：项目行可改派（pm/admin）+ 归档项目正确显示名字
    layout/Sidebar.tsx     ← 改：受控开合 + 窄屏抽屉
    layout/Header.tsx      ← 改：汉堡按钮 + 窄屏折叠
    ui/MoveProjectDialog.tsx ← 【新】改派项目对话框（复用 ConfirmDialog 的交互约定）
  app/(app)/layout.tsx     ← 改：持有窄屏导航开合状态
  lib/api.ts               ← 改：请求超时（AbortController，零依赖）
  lib/swr-keys.ts          ← 改：改派项目后的失效集合
```

**一条贯穿全轮的设计原则**：本轮四个修复各自都有「可以就地打补丁」的诱惑写法
（在 `PATCH` 里加个 `if "project_id" in data`、在每个路由里手写 `IN` 查询、
在每个页面加 `md:` 类、在两个改密路径各写一遍 `password_changed_at = utcnow()`）。
**全部拒绝**：每一条都收敛到一个单一真相点（`assert_project_writable` / `identity.py` /
外壳布局 / `set_password` 本身），因为这四条修复的共同教训正是
**「同一个语义散落在多处 → 漏一处就是一个静默错」**。

---

### 2.2 缺陷 A（P0）：项目归属不可再组织 + 归档只在 UI 生效

#### A1 复现（真实应用 + 真实 JWT）

```
POST  /api/requirements {"title":"A2","project_id":1}      → 201  project_id=1
PATCH /api/projects/1   {"archived":true}                   → 200  archived=true
POST  /api/requirements {"title":"R2","project_id":1}      → 201  ← 归档项目仍然收单
PATCH /api/requirements/3 {"project_id":2}                 → 200  project_id 仍为 1  ← 静默忽略
PATCH /api/requirements/1 {"project_id":999999}            → 200  project_id 仍为 1  ← 连不存在都不报
POST  /api/requirements {"title":"x","project_id":999}     → 400 {"error":"project not found"}
```

最后两行放在一起看最刺眼：**同一个 `project_id`，创建时校验存在性并 400，更新时连看都不看。**

#### A2 为什么这是 P0 而不是「缺个功能」

1. **产品文案已经承诺了它。** `frontend/app/(app)/projects/page.tsx:209` 的删除确认框写着
   「若它名下仍有需求或 BUG，删除会被拒绝——请先归档，**或把工单移到别的项目**」。
   用户按这句话去做，会发现产品里没有任何地方能做到这件事。
2. **它让第 4 轮的治理链路断在最后一跳。** 第 4 轮建立的是「归档优于删除、删除前置引用检查」，
   删除被 409 拒绝时给出「还有 12 个需求、3 个 BUG」的可操作计数——**可操作性依赖于
   「能把这 12 个需求挪走」**。挪不走，那个 409 就只是一句无解的拒绝。
3. **它是一次静默说谎的写操作。** 前四轮反复收口的正是这一类（`PATCH /users/:id` 无有效字段
   由 200 改 400、「未指派」死控件、看板谎报回滚）。同类问题在工单主体 `PATCH` 上仍然存在。
4. **归档的约束只在前端。** 第 4 轮的实现把「归档项目不出现在切换器与建单表单」做在 UI 层，
   后端 `_validate_project`（`routes/requirements.py:132`）只校验存在、不校验归档。
   一个开着旧页面的浏览器、一条深链、一次 API 直调，都能继续往归档项目里塞新单——
   **归档因此不是一个约束，只是一个视觉过滤器。**

#### A3 设计：新增子资源端点，而不是往 `PATCH /:id` 里塞字段

```
PATCH /api/requirements/<int:req_id>/project      @require_role("admin","pm")
PATCH /api/bugs/<int:bug_id>/project              @require_role("admin","pm")
body: {"project_id": <int> | null, "expected_updated_at": <iso, 可选>}
```

**为什么是独立端点**：`PATCH /:id` 的门禁是行级 `can_manage_ticket`（reporter / 人类 assignee /
pm / admin 都能改标题），而「把单挪到别的项目」是**组织性动作**，与 `assign` / `move` 同级，
必须是 pm/admin。把一个 pm/admin 字段混进 can_manage 门禁的路由里，等于给这条路由造了两套权限，
是下一轮的 bug 温床。项目里已有的 `/assign`、`/move`、`/convert-to-bug` 都是这个形状，
新端点与之一致，不引入新范式。

**实现（`routes/requirements.py`，bugs 侧同构且复用同一批辅助函数）：**

```python
@bp.patch("/<int:req_id>/project")
@require_role("admin", "pm")          # 组织性动作，与 assign / move 同级
def move_requirement_project(req_id):
    """把需求改派到另一个项目（或置为未归属）。

    绝不触碰 status：本操作只改变归属与看板列内序号，状态机不参与
    （CLAUDE.md「状态机是圣域」）。

    Returns:
        200 + 工单体；404 单不存在；400 project 不存在；409 目标项目已归档 / 并发冲突。
    """
    req = db.session.get(Requirement, req_id)
    if req is None:
        return jsonify({"error": "requirement not found"}), 404
    data = json_body()
    conflict = check_concurrency(req, data)      # 与 patch/move 同一并发语义
    if conflict:
        return conflict
    if "project_id" not in data:
        return jsonify({"error": "project_id is required",
                        "detail": {"field": "project_id",
                                   "expected": "integer or null"}}), 400
    target = _wanted_project_id(data)            # None = 未归属；见下
    # 【评审 R9】幂等短路必须排在归档守卫**之前**：把一张归档项目里的单「移动到它现在
    # 所在的项目」是一次空操作，不是「往归档项目里放新东西」。排在守卫之后会返回 409，
    # 与 T-A4 确立的口径（归档只拦「放进去」）自相矛盾。
    if target == req.project_id:                 # 幂等：同项目直接返回，不写审计
        return jsonify(req.to_dict()), 200
    guard = lifecycle.assert_project_writable(target)   # 归档 → 409；不存在 → 400
    if guard:
        return guard
    _rehome_ticket(Requirement, "requirement", req, target)   # position 搬迁 + 审计，见下
    db.session.commit()
    return jsonify(req.to_dict()), 200
```

**`_wanted_project_id(data)`（放在 `requirements.py` 的公共辅助区，bugs 侧 import）：**

```python
def _wanted_project_id(data):
    """从请求体取目标项目 id：显式 JSON null → None（未归属），否则走 want_int。

    判据必须是 `is None` 而不是 falsy——`0` 与 `""` 是**非法输入**（want_int 负责 400），
    与「显式置空」语义不同。这与第 4 轮 assign 的取消指派判据逐字一致，
    刻意保持同形，避免读者在两个地方推两套规则。
    """
    if data.get("project_id") is None:
        return None
    return want_int(data, "project_id", minimum=1)
```

**`_rehome_ticket(model, entity, ticket, target_pid)`（公共辅助，需求 / BUG 共用；
`bugs.py` 已有 `from routes.requirements import (_next_position, _validate_project,
_reindex_column, check_concurrency, ...)` 的先例，新辅助追加进同一个 import 即可）：**

```python
def _rehome_ticket(model, entity: str, ticket, target_pid) -> None:
    """把工单搬到另一个项目，并维护两端看板列的 position 连续性。

    position 的语义是「同项目同状态列内的相对次序」（scale-and-project-scope §2.5），
    所以搬家必须两端都动：目标列取新号、源列重编号补洞。少做任何一边，
    看板都会出现重复序号或空洞——那是「拖了、成功了、顺序却错了」的老问题。

    Args:
        model: Requirement / Bug 模型类。
        entity: "requirement" | "bug"，只用于审计行的 entity_type。**显式传入**而不是
            从 model 反查——审计的实体名是对外契约的一部分，让它依赖一张私有映射表
            是下一个「改了模型名就悄悄写错审计」的入口。
        ticket: 已从 session 取出的工单实例。
        target_pid: 目标项目 id，None 表示未归属。
    """
    old_pid, status = ticket.project_id, ticket.status
    ticket.project_id = target_pid
    ticket.position = _next_position(model, status, target_pid)
    db.session.flush()                       # 先让源列查询看不到这张单
    _reindex_column(model, status, old_pid)  # 源列补洞，连续重编号
    Activity.log(entity, ticket.id, "moved_project", actor=_actor(),
                 to_status=status,
                 message=f"将工单移动到项目「{_project_label(target_pid)}」"
                         f"（原：{_project_label(old_pid)}）")
```

`_project_label(pid)` 返回项目 `name`，`None` 时返回「未归属」，项目已被删时返回 `#<id>`
——审计文本必须能独立于当前数据被读懂（这是第 3 轮「删单串档」的同一条教训）。

**`services/lifecycle.py` 新增（归档写守卫的单一真相）：**

```python
# 依赖：from flask import jsonify；from extensions import db；from models.project import Project
# 【评审 R2】v1 在这里写了 `_iso(project.archived_at)`——但 `services/lifecycle.py` 里
# **没有** `_iso`（全仓 8 份 `_iso` 全在 models/* 与 routes/comments.py），逐字实现即 NameError。
# 也**不要**从 models 里 import 那个下划线私有名，更不要写第 9 份副本：
# 直接用 `Project.to_dict()` 这个公开序列化器取已经格式化好的 `archived_at`。
ARCHIVED_PROJECT_ERROR = "project is archived"

def assert_project_writable(project_id):
    """校验「可以把新东西放进这个项目」。可写返回 None，否则返回 (响应, 状态码)。

    归档的产品语义是「只切断把新东西放进去」（第 4 轮 §2.6 逐字如此），
    因此本守卫只用于**写入方向**：建单、改派进来。把单**挪出**归档项目、
    以及归档项目里既有单的流转 / 评论 / Agent 推进，一律不受影响。

    Returns:
        None | tuple[flask.Response, int]：400 不存在 / 409 已归档。
    """
    if project_id is None:                    # 未归属是合法目标，永远可写
        return None
    project = db.session.get(Project, project_id)
    if project is None:
        return jsonify({"error": "project not found"}), 400   # 与创建路径逐字一致
    if project.archived_at is not None:
        return jsonify({
            "error": ARCHIVED_PROJECT_ERROR,
            "detail": {"project_id": project.id, "key": project.key,
                       # 【评审 R2】复用模型公开序列化器，不引私有 _iso、不写第 9 份。
                       "archived_at": project.to_dict()["archived_at"]},
        }), 409
    return None
```

**接入点（三处，必须全接，漏一处归档就还是假的）：**

| 位置 | 现状 | 改为 |
|---|---|---|
| `routes/requirements.py:132 _validate_project` | 只校存在 → 400 | 整体替换为 `lifecycle.assert_project_writable`（创建路径由此同时获得归档守卫） |
| `routes/bugs.py` 建 BUG | 调用同一个 `_validate_project` | 无需改（共用） |
| 新 `/:id/project` 端点 | —— | 直接调用 |

> **有意不接的地方**：`POST /:id/convert-to-bug` 继承源需求的 `project_id`。转 BUG 是既有单的
> **流转**而非「放新东西进去」，若源需求所在项目已归档，硬拦会把一条正常的质量流程堵死。
> 这一条必须写进测试（§6.1 T-A7），否则下一个读代码的人会「顺手补上」这个守卫。

#### A4 前端：抽屉里可改派 + 归档项目正确显示

1. **`TicketDrawer.tsx:376-384` 的项目名解析改用含归档的项目源。**
   现状用 `useProjectScope().projects`（= `PROJECTS_KEY`，后端默认**不返回归档项目**），
   于是归档项目的单在抽屉里显示成裸 `#3`。改为读 `PROJECTS_ALL_KEY`
   （`/projects?limit=200&include_archived=1`，实测 member 角色也可读 → 200），
   命中归档项目时显示「Alpha（已归档）」。
   **不复用 `PROJECTS_KEY`**：一个 key 一种形状是第 1 轮确立的不变量，两个 key 的语义差异
   （看不看得见归档）恰恰是这里要区分的东西。
2. **新增 `components/ui/MoveProjectDialog.tsx`**（pm/admin 可见，入口在抽屉项目行右侧的
   「移动」文字按钮）：
   - 选项 = 未归属 + 全部**未归档**项目；当前项目若已归档，额外置顶一条 `disabled` 的
     「Alpha（已归档，不能移回）」——让用户看懂自己现在在哪，而不是显示成「未归属」。
   - 提交期间按钮禁用（防重复提交，与 `ConfirmDialog` 同约定）；
   - 失败**不关闭对话框**，就地显示后端 `detail`（409 的归档提示正是要被读到的地方）；
   - 成功后的刷新分工见 §4.4（**评审 R3/R4 已重写，勿按 v1 的写法实现**）：
     `useTicket.moveProject` 只负责工单与 feed 两个 key，跨视图失效由 `TicketDrawer`
     在成功回调里做，且**必须同时**调 `invalidateTicketViews(mutate)` 与
     `invalidateAdminViews(mutate)`——后者才含 `/projects`，否则 P2-4 新加的项目工单计数
     会停在旧值（本轮自己新造一处「页面说假话」）。
3. **`projects/page.tsx:209` 的文案在能力落地后保持不变**——它终于说了真话。

---

### 2.3 缺陷 B（P1 · 安全）：改密码不吊销既有会话

#### B1 复现

```
alice 登录 → token_old                              GET /api/auth/me (token_old) → 200
POST /api/me/password {current, new}                → 200 {"ok":true}
GET  /api/auth/me (token_old)                       → 200      ← 期望 401
POST /api/auth/login (旧密码)                        → 401      ← 密码本身确实改了

admin PATCH /api/users/<bob> {"password": "..."}     → 200
GET  /api/auth/me (bob 的旧 token)                   → 200      ← 期望 401
```

`routes/me.py:141` 有一句坦率的注释：「JWT 无状态不吊销（§10 R4）：旧 token 在过期前仍有效，
属 MVP 可接受权衡」。**这句注释在第 4 轮之后已经过期**——第 4 轮为停用成员注册了
`jwt.token_in_blocklist_loader`（`errors.py:75`），吊销通道已经存在且已在生产路径上跑着。
第 4 轮的 spec §8-4 也明确写了：「已具备落地前置，**建议列为下一轮首选项**」。本轮兑现它。

#### B2 设计

**数据（唯一新增列，走 `schema_sync`）：**

```python
# backend/models/user.py
# 【real-world-readiness §2.3】改密 / 重置密码的时刻；blocklist 钩子据此吊销更早签发的 token。
# 可空：存量行为 NULL，语义是「从未改过密码」→ 不吊销任何东西（升级无感）。
# 必须同时登记进 services/schema_sync.py::ADDITIVE_COLUMNS，否则存量库全线 no such column → 500。
password_changed_at = db.Column(db.DateTime, nullable=True)
```

```python
# backend/services/schema_sync.py::ADDITIVE_COLUMNS 追加一行
("users", "password_changed_at", "DATETIME"),
```

> 注意：**不设 NOT NULL、不设 server_default**。若给它 `DEFAULT CURRENT_TIMESTAMP`，
> 存量库执行 `ALTER` 的瞬间所有人的既有 token 会一起失效（全员被登出）——一次迁移把全公司踢下线，
> 是本轮最容易踩且最贵的坑。`NULL = 从未改过 = 不吊销` 是唯一安全的默认。

**写入点收敛到 `set_password` 自身**（而不是在两个路由里各写一遍）：

```python
# backend/models/user.py
def set_password(self, password: str) -> None:
    """设置密码，并记录改密时刻（用于吊销更早签发的 token）。

    刻意写在这里而不是各调用点：`set_password` 是全仓设置密码的唯一入口
    （auth.register / users.create / users.patch / me.change_password 四处都调它），
    收敛在此可保证「任何一条改密路径都会吊销旧会话」，漏一条即是一个后门。
    """
    self.password_hash = generate_password_hash(password, method="pbkdf2:sha256")
    self.password_changed_at = utcnow()
```

> 副作用（**有意且正确**）：`POST /api/users` 与 `POST /api/auth/register` 创建新用户时也会
> 写上该字段。新用户此前没有任何 token，因此零影响；语义上「账号创建即密码设定时刻」也成立。
> 唯一需要小心的是 `seed.py`：它在启动时创建 seed 用户，同样只是写一个时间戳，无副作用。

**吊销判据（`errors.py:75` 的钩子内追加，与停用判据并列）：**

```python
# 文件顶部需 `from datetime import timezone`（errors.py 目前未导入）。
@jwt.token_in_blocklist_loader
def _is_revoked(jwt_header, jwt_payload):
    from models.user import User

    sub = jwt_payload.get("sub")
    try:
        uid = int(sub)
    except (TypeError, ValueError):
        return True
    user = db.session.get(User, uid)
    if user is None or not user.is_active:
        return True                       # 【第 4 轮 §2.5】停用 / 已删
    # 【本轮 §2.3】改密时刻之前签发的 token 立即失效。
    # 判据用 `<` 而非 `<=`：改密接口会在同一秒签发新 token，用 `<=` 会把它一起杀掉，
    # 造成「改完密码立刻被登出、再登录又被登出」的死循环。代价是同一秒内签发的旧 token
    # 会存活至多 1 秒——这是刻意接受的窗口，已在 §7 R-2 登记。
    changed = user.password_changed_at
    if changed is not None:
        iat = jwt_payload.get("iat")
        if isinstance(iat, (int, float)) and iat < int(changed.replace(
                tzinfo=timezone.utc).timestamp()):
            return True
    return False
```

**吊销文案必须分流（评审 R8）——不要复用「账号已被停用或删除」。**
`errors.py` 的 `@jwt.revoked_token_loader` 今天只有一句 `account is disabled or removed`。
本轮之后它会覆盖两种完全不同的原因，而对改密场景那句话**是假的**：用户在手机上改完密码，
笔记本上弹出「账号已被停用或删除」——一句关于他自己账号的假话，是这一轮最不该自己制造的东西。
钩子拿得到 `jwt_payload`，分流的成本只有一次查询，而且只发生在**已经被吊销**的罕见路径上：

```python
    @jwt.revoked_token_loader
    def _revoked_token(jwt_header, jwt_payload):
        """【评审 R8】按吊销原因分流文案：停用/删除 与 改密是两件事，不能共用一句话。

        前端只按 401 自动登出（lib/api.ts::signalUnauthorizedIfNeeded），
        因此两种文案对流程零影响，纯粹是「别对用户说假话」。
        """
        from models.user import User

        try:
            user = db.session.get(User, int(jwt_payload.get("sub")))
        except (TypeError, ValueError):
            user = None
        if user is not None and user.is_active:
            # 账号好好的却被吊销 → 只可能是改密（§2.3 的唯一另一种来源）。
            return jsonify({"error": "password changed, please sign in again"}), 401
        return jsonify({"error": "account is disabled or removed"}), 401
```

> `iat` 的存在性已实测确认：本项目签发的 token 载荷为
> `['csrf','exp','fresh','iat','jti','nbf','role','sub','type']`。
> `password_changed_at` 由 `utcnow()` 写入（`extensions.py`，tz-aware UTC），
> 但 SQLite 取回时可能是 naive datetime——**必须显式补 `tzinfo=utc` 再取时间戳**，
> 否则在非 UTC 时区的机器上会算出几小时的偏差，把有效 token 误杀（或把该杀的放过）。

**不把自己踢下线（`routes/me.py::change_password`）：**

```python
    user.set_password(new_password)
    db.session.commit()
    # 需 `from flask_jwt_extended import create_access_token`，并与 routes/auth.py::login
    # 的签发方式**逐字一致**（identity=str(user.id) + additional_claims={"role": ...}）
    # ——两处签发不一致会让新 token 少一个 role claim，表现为「改完密码就没权限了」。
    # 【§2.3】改密后本人不应被自己踢下线：立刻签发一枚新 token 一并返回。
    # additive：既有 {"ok": true} 字段不变，老客户端读不到 token 也只是需要重新登录一次。
    return jsonify({"ok": True, "token": create_access_token(
        identity=str(user.id), additional_claims={"role": user.role})}), 200
```

前端 `settings` 页改密成功后 `setToken(res.token)`（若存在），其余会话在下一次请求即 401 →
既有的 `signalUnauthorizedIfNeeded` 自动登出（第 2 轮已建成的通道，无需新代码）。

**管理员重置他人密码（`routes/users.py:103`）**：不签发新 token（那是别人的会话），
被重置者的所有会话下一次请求即 401——**这正是重置密码这个动作的目的**。
响应体需补一句可读提示进 `detail`？不——`PATCH /users/:id` 的成功 shape 不改（§4.2），
提示放在前端确认文案里（「重置后该成员的所有登录会话将立即失效」）。

> **【评审 R8】admin 重置的是「自己」的时候会当场把自己登出。**
> `routes/users.py:103` 的 `if data.get("password"): user.set_password(...)` **没有自我豁免**，
> 而团队页的重置入口对 admin 自己那一行同样可点。收敛到 `set_password` 之后，
> admin 给自己重置密码 → `password_changed_at` 前移 → 他手里那枚 token 的 `iat` 立刻过期 →
> 下一次请求 401 自动登出。**这个行为本身是正确的**（密码变了，旧会话就该失效），
> 不要为它加特例；但必须让用户**事先知道**：
> - 前端 `team/page.tsx` 的重置确认框在目标是当前登录者时，文案改为
>   「这会立即结束**包括你自己在内**的所有登录会话，你需要用新密码重新登录」；
> - 不在此处签发新 token——`PATCH /users/:id` 是管理接口，它的成功 shape 不改（§4.2），
>   而「自助改密不踢自己」已经由 `POST /api/me/password` 覆盖（那才是给自己改密的正路）。
> 用例 T-B7 守这条。

---

### 2.4 缺陷 C（P1 · 性能）：多态身份解析的 N+1

#### C1 实测数据（2000 需求 + 500 BUG + 60 评论 + 60 活动 + 300 通知，SQLAlchemy 事件计数）

| 端点 | 状态 | 耗时 | 响应体 | **查询次数** |
|---|---|---|---|---|
| `GET /api/requirements`（默认 50） | 200 | 21.7 ms | 16.4 KB | **53** |
| `GET /api/requirements?limit=200` | 200 | 48.7 ms | 65.5 KB | **203** |
| `GET /api/board/requirements`（默认每列 100） | 200 | 135.0 ms | 195.1 KB | **615** |
| `GET /api/requirements/1/feed`（60 评论 + 60 活动） | 200 | 32.1 ms | 27.8 KB | **124** |
| `GET /api/stats` | 200 | 11.0 ms | 2.3 KB | 9 |
| `GET /api/me/work` | 200 | 5.3 ms | 0.1 KB | 6 |

查询构成（按语句归并，300 单库的看板请求）：`51 × SELECT users` + `50 × SELECT agents` +
`14 × SELECT requirements` = 115。**即每张卡一次。**

关键诊断：这不是「同一个 id 查了很多次但被 ORM 身份映射挡住了」——实测
**同一个 app context 内连续三次 `db.session.get(User, 2)` = 3 次查询**。
所以哪怕整块看板只涉及 2 个 assignee，也照样发 600 次。

为什么前四轮没碰到：第 3 轮加的是**分页**（限制返回条数），第 4 轮加的是**每列上限**
（限制卡片数）——两者都在压 `N`，而这里的问题是**系数 1（每行一次）**。
在 SQLite 进程内一次查询是微秒级，所以 135 ms 还能忍；换成任何一个走 TCP 的数据库
（每次往返 ~0.5-1 ms），同一个看板请求就是 **0.6-1.5 秒**，而看板与铃铛都在轮询。

#### C2 设计：`backend/services/identity.py`（请求内多态身份缓存）

```python
"""多态身份（user / agent）的请求内解析缓存（real-world-readiness §2.4）。

问题：`Requirement._resolve_assignee` 与 `Comment._resolve_author` 在序列化**每一行**时
各做一次 `db.session.get()`，而 SQLAlchemy 不会跨调用复用（实测同 id 连查三次 = 三条 SQL）。
一次看板请求因此产生 615 条查询。

对策：把「(kind, id) → summary dict」的解析收敛到本模块，并在**请求生命周期内**记忆化。
一次请求内同一个人只查一次；配合 `prime()` 的批量预热，N 张卡最多 2 条查询。

边界（刻意）：
  * 缓存挂在 `flask.g` 上，**随请求结束自然消亡**——不是进程级缓存，不需要失效策略，
    也就不可能出现「改了名字但页面还显示旧名」这类缓存陈旧问题。
  * 无请求上下文时（Agent 运行时、脚本、单测直调模型）**退化为直接查询**，
    行为与今天逐字一致——本模块只做加速，不改语义。
"""
from flask import g, has_request_context

from extensions import db          # 注意：本模块被模型层 import，故对 models 一律**局部 import**
                                   # （与 models/requirement.py 既有的循环依赖规避手法一致）

_CACHE_KEY = "_identity_cache"


def _cache():
    """取本请求的身份缓存；无请求上下文时返回 None（调用方退化为直查）。"""
    if not has_request_context():
        return None
    cache = getattr(g, _CACHE_KEY, None)
    if cache is None:
        cache = {}
        setattr(g, _CACHE_KEY, cache)
    return cache


def prime(pairs) -> None:
    """批量预热一批 (kind, id)，把 N 次点查压成每类一次 IN 查询。

    Args:
        pairs: 可迭代的 (kind, id) 二元组，kind ∈ {"user","agent"}；None id 自动跳过。
            **内部会先物化为 list**——调用方常传生成器，而本函数要遍历两次（user / agent 各一次），
            不物化会让第二次遍历拿到空序列，表现为「agent 头像全部变成已删除占位」。
    """
    cache = _cache()
    if cache is None:
        return
    from models.agent import Agent
    from models.user import User

    pairs = list(pairs)
    for kind, model in (("user", User), ("agent", Agent)):
        missing = {i for k, i in pairs if k == kind and i is not None
                   and (kind, i) not in cache}
        if not missing:
            continue
        for batch in _chunked(sorted(missing), 500):     # R-5：SQLite IN 参数上限
            for row in model.query.filter(model.id.in_(batch)).all():
                cache[(kind, row.id)] = row.summary()
        for ident in missing:                       # 查不到的记为已删占位，避免二次点查
            cache.setdefault((kind, ident), None)


def _chunked(items, size):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def summary(kind, ident):
    """返回 (kind, ident) 的概要 dict；目标不存在返回 None（调用方负责占位文案）。

    【评审 R12】返回的是缓存值的**浅拷贝**。今天全仓没有任何地方就地修改
    `to_dict()["assignee"] / ["author"] / ["actor"]`（评审已 grep 确认），
    但缓存一旦命中，同一请求内 N 行拿到的就是**同一个 dict 实例**——将来任何一处
    「顺手给 assignee 补个字段」都会静默污染整页所有行，而且极难定位。
    一次浅拷贝的成本远低于这个风险，且不改变任何查询次数。
    """
    if ident is None:
        return None
    cache = _cache()
    if cache is not None and (kind, ident) in cache:
        hit = cache[(kind, ident)]
        return dict(hit) if hit is not None else None
    from models.agent import Agent
    from models.user import User

    model = {"user": User, "agent": Agent}.get(kind)
    row = db.session.get(model, ident) if model is not None else None
    result = row.summary() if row is not None else None
    if cache is not None:
        cache[(kind, ident)] = result
    return dict(result) if result is not None else None
```

**模型侧改写（语义逐字不变，只换解析来源）：**

```python
# models/requirement.py::_resolve_assignee
def _resolve_assignee(assignee_type, assignee_id):
    if not assignee_type or assignee_id is None:
        return None                                  # 真·未指派：不变
    if assignee_type in ("user", "agent"):
        found = identity.summary(assignee_type, assignee_id)
        return found if found is not None else _deleted_summary(assignee_type, assignee_id)
    return _deleted_summary(assignee_type, assignee_id)
```

`models/comment.py::_resolve_author` 同构改写（`system` 分支与未知类型兜底原样保留）。

**预热点（四处，每处一行）：**

| 位置 | 预热内容 |
|---|---|
| `routes/requirements.py::list_requirements` / `bugs.py::list_bugs` | 本页行的 `(assignee_type, assignee_id)` |
| `services/board_page.py::column_page` | **全部列**的行合起来预热**一次**（见下方 R5 说明），再统一 `to_dict()` |
| `routes/comments.py::feed` / `list_comments` | 评论的 `(author_type, author_id)` + 活动的 `(actor_type, actor_id)` |
| `routes/me.py::my_work` | 两个列表的 assignee |
| `routes/notifications.py::list_notifications` | 每条通知的 `(actor_type, actor_id)`——`Notification.to_dict` 经 `resolve_actor()` → `_resolve_author`（`models/notification.py:44-51`）同样是每行一次；铃铛按 20 s 轮询，**这是全站频率最高的一个 N+1** |
| `routes/{requirements,bugs}.py::activities` | 活动行的 `(actor_type, actor_id)` |

即便**一处都不预热**，仅靠记忆化就能把「600 张卡 2 个 assignee」压到 2 条查询；
预热解决的是「600 张卡 600 个不同 assignee」的最坏情况。两者都要，因为最坏情况在真实团队里
不罕见（一个上百人的项目）。

**【评审 R5】`column_page` 必须「先收行、再预热、后序列化」，不能逐列预热。**
`services/board_page.py:27` 今天是在 `for key, title in workflow.columns(entity)` 的循环体内
直接 `"items": [r.to_dict() for r in rows]`。若把 `prime()` 放进循环，每列最坏各发 2 条
（user / agent 各一），而需求看板是 **7 列**（`services/workflow.py:23`，含 `bug_fixing`），
最坏就是 14 条身份查询——正好把下面那个常数阈值顶穿（见 C3 的推导）。改成两趟：

```python
    columns, staged = [], []
    for key, title in workflow.columns(entity):
        q = apply_project_filter(model.query.filter(model.status == key), model, scope)
        total = q.order_by(None).count()
        rows = q.order_by(model.position.asc(), model.id.asc()).limit(column_limit).all()
        staged.append((key, title, rows, total))
    # 【§2.4 / 评审 R5】全看板只预热一次：身份查询从「每列 2 条」降到「整块 ≤2 条」。
    identity.prime((r.assignee_type, r.assignee_id) for _, _, rows, _ in staged for r in rows)
    for key, title, rows, total in staged:
        columns.append({"key": key, "title": title,
                        "items": [r.to_dict() for r in rows],
                        "total": total, "truncated": total > len(rows)})
```

这一步同时解释了 `prime()` 为什么必须**在内部把入参物化成 list**（§2.4-C2 的 docstring
已写死）：这里传进去的正是一个生成器。

#### C3 把它焊死：查询次数回归测试

CLAUDE.md 要求「任何被发现的回归 bug 都要补上对应的测试，把过去的坑变成未来的护栏」。
性能缺陷的护栏就是**数查询**：

> **【评审 R1 · P0】这条护栏在 v1 的写法下是空的，实施时必须按下面的版本写。**
> v1 打算用一个新 fixture 批量造单，但仓库既有的 `tests/conftest.py:147::bulk_tickets`
> 造出来的单 **`assignee_type` / `assignee_id` 全是 `None`**，而
> `models/requirement.py::_resolve_assignee` 对未指派**第一行就 `return None`、一条查询都不发**。
> 于是「120 张无 assignee 的卡」在**今天这份没修过的 N+1 代码上**也只有十几条查询——
> 断言 `<= 25` 会**直接通过**，护栏什么都没护住，而 §6.4 的 DoD 会据此宣布达标。
> v1 报的「今日 115」是在**带 assignee** 的数据集上测的，两者不是同一个场景。
> 因此：**预算用例的数据必须带 assignee，且 assignee 要互不相同**（这才同时压住
> 「记忆化」与「预热」两条路径），并且实施者必须先在未打补丁的代码上跑一次、看到它红。

**fixture：扩展既有的，不新建（评审 R7）。** 仓库已有 `bulk_tickets` / `auth` /
`archived_project`，v1 引用的 `many_tickets` / `auth_pm` **都不存在**。
`bulk_tickets` 做一次 additive 扩展即可，既有调用点（看板分页用例）零影响：

```python
# tests/conftest.py：在既有 _bulk 签名尾部追加一个可选参数，默认 None = 今天的行为
def _bulk(n, status="new", project_id=None, assignees=None):
    """assignees: [(type, id), ...]，按下标取模轮流指派。

    【spec §2.4 / 评审 R1】查询预算用例必须传它：不传时所有单都是「未指派」，
    而未指派在 _resolve_assignee 里是零查询的早返回——护栏会在**未修复的代码上**
    也变绿，等于没写。
    """
    with app.app_context():
        for i in range(n):
            atype, aid = assignees[i % len(assignees)] if assignees else (None, None)
            db.session.add(Requirement(
                title=f"批量需求 {i}", status=status, project_id=project_id,
                position=i, assignee_type=atype, assignee_id=aid,
            ))
        db.session.commit()
```

```python
# backend/tests/test_query_budget.py（新建）
@contextmanager
def count_queries(app):
    """统计 with 块内实际发往数据库的语句条数。

    【评审 R6】监听器必须是**具名函数**：v1 写成 lambda 再 `event.remove(..., ...)`
    （字面省略号），既跑不起来，也无法解除注册——监听器会泄漏到后续用例里。
    """
    seen = []

    def _on_exec(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    with app.app_context():
        engine = db.engine
    event.listen(engine, "before_cursor_execute", _on_exec)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", _on_exec)


def test_board_query_count_is_constant(app, client, auth, data, bulk_tickets):
    """120 张卡的看板请求必须在常数级查询内完成（回归护栏，见 spec §2.4）。

    修复前实测 ~115 条（本用例的 assignee 分布下），修复后 ≤ 25。
    """
    bulk_tickets(120, assignees=[("user", data["member_id"]),
                                 ("user", data["pm_id"]),
                                 ("agent", data["dev_agent_id"])])
    with count_queries(app) as seen:
        res = client.get("/api/board/requirements", headers=auth("pm"))
    assert res.status_code == 200
    assert len(seen) <= 25, f"board N+1 regression: {len(seen)} queries"
```

**阈值 25 的推导（评审 R5 已重算，v1 的「6 列」是错的）**：需求看板 **7 列**
（`services/workflow.py:23`：new / assigned / in_development / testing / reviewing /
bug_fixing / done）→ 7 条分页查询 + 7 条 `COUNT` + 全看板 **≤2** 条身份预热
+ blocklist 钩子的 1 条 user 查询 ≈ **17**，留 8 条余量取整到 **25**。
若照 v1 那样逐列预热，最坏是 7+7+14+1 = **29 > 25**，正确实现也会红——
而实施者最省事的反应是去放宽阈值，护栏就此报废。**阈值必须写死为常数、不得随卡片数缩放**
——那正是要防的东西。同一套护栏覆盖列表页（`≤ 12`）与 feed（`≤ 12`）。

---

### 2.5 缺陷 D（P1 · 可用性）：窄屏下全站不可用

#### D1 现状（源码级证据）

- `frontend/app/(app)/layout.tsx`：`<div className="flex h-screen overflow-hidden">` +
  `<Sidebar />` + `<div className="flex min-w-0 flex-1 flex-col">`——**没有任何断点**。
- `frontend/components/layout/Sidebar.tsx:82`：`flex w-56 shrink-0 flex-col`——
  固定 224 px，且 `shrink-0` 明确禁止压缩。
- 全仓 35 个 `.tsx` 中只有 7 个文件出现过响应式断点类，合计 **12 处**（`lg` 7 / `md` 3 / `sm` 2）。

结论：在 390 px 宽（iPhone 竖屏）下，正文区宽度 = 390 − 224 = **166 px**；
列表页的表格、看板的列、抽屉的表单在这个宽度下全部不可读。
在 768 px（平板竖屏 / 桌面分屏）下勉强能看但表格必然溢出——
`overflow-x` 在全仓只出现在 `KanbanBoard.tsx:121` 一处。

#### D2 设计：窄屏可用性（不是移动端重设计）

断点统一取 Tailwind 默认 `md`（768 px）。**`md` 及以上的视觉与行为一字不改**
——这是本条改动的验收基线，也是它敢在一轮内做完的原因。

| 元素 | `< md`（窄屏） | `≥ md` |
|---|---|---|
| 应用外壳 `layout.tsx` | 单列；侧栏脱离文档流 | 现状（左右两栏） |
| `Sidebar` | `fixed inset-y-0 left-0 z-40 -translate-x-full` + 打开时 `translate-x-0`；配一层 `bg-ink/30` 遮罩，点击 / `Esc` 关闭 | 现状（`w-56` 静态列） |
| `Header` | 最左新增汉堡按钮（`md:hidden`，`aria-label="打开导航"`、`aria-expanded`）；全局搜索折叠为图标；项目切换器只显示 key | 现状 |
| 列表页表格 | 外层包 `overflow-x-auto`，表格 `min-w-[640px]` | 无变化（父容器更宽，不触发滚动） |
| 看板 | 列 `min-w-[260px]`，容器保持横滑（现状已有 `overflow-x-auto`） | 无变化 |
| `TicketDrawer` | 已是 `w-full max-w-[480px]`，窄屏自然全宽——**无需改动**（自我否决的候选） | 无变化 |

**开合状态的落点**：`app/(app)/layout.tsx` 已是 `"use client"`，直接在其中 `useState`，
把 `open` / `onClose` 传给 `Sidebar`，把 `onOpen` 通过 context 或 props 交给各页的 `Header`。
本项目的 Header 由**每个页面各自渲染**（不是外壳统一渲染），逐页传 props 会改 12 个文件且极易漏
——因此新增一个极薄的 `lib/nav-drawer.tsx`（`NavDrawerProvider` + `useNavDrawer()`），
外壳提供，Header 消费，**其余页面一行不改**。这是本条改动能收敛在 5 个文件内的关键。

**必须同时满足的可访问性下限**（否则「能显示」不等于「能用」）：
抽屉打开时锁 `body` 滚动、焦点移入抽屉、`Esc` 关闭、遮罩 `aria-hidden`、
汉堡按钮有 `aria-controls` / `aria-expanded`。项目里已有 `Modal` 与
第 4 轮的 `ConfirmDialog` 两套现成实现可以照抄，**不要发明第三套**。

---

### 2.6 P2 收口清单（低风险、随手补齐，但每一条都是一次「说假话」）

| # | 位置 | 问题 | 处理 |
|---|---|---|---|
| P2-1 | `frontend/lib/api.ts:91` / `:159` | `fetch` 无超时：后端假死（不是断连）时 UI 永久转圈，且所有页面的错误态都等不到 | 加 `AbortController`：GET 15 s / 写 30 s，超时抛 `ApiError(0, "请求超时，请重试")`。零依赖。**落地三条约束见下（评审 R11）** |
| P2-2 | `frontend/package.json:9` | 声明了 `lint` 脚本，但仓库既无 eslint 依赖也无配置——跑它会进入交互式安装提示（在 CI / Agent 环境里就是挂起） | 删除该脚本，并在 README 明确门禁 = `typecheck` + `build`。**不引入 eslint**（新依赖，且与本轮主题无关） |
| P2-3 | ~~`CLAUDE.md:116`~~、`.claude-index/index.md:13`、`:198` | 质量门禁写着「93 cases」，实测 342——下游 Agent 会按 93 验收 | **【评审 R14 已缩范围】`CLAUDE.md` 那一处已由并行工作流修好，并且改成了「相对判据：记录基线 + 零失败 + 用例数不下降」——本轮**不要再动它**，写死一个新数字就是把别人刚落地的改进又退回去。本轮只改 `.claude-index/index.md` 的两处，且**同样写成相对形式**，不写死数字 |
| P2-4 | `frontend/app/(app)/projects/page.tsx` | 项目列表不显示每个项目有多少张单，用户只有点了删除、吃到 409 才知道 | `GET /api/projects?with_counts=1`（additive，两条 `GROUP BY`）→ 表格新增「需求 / BUG」两列 |
| P2-5 | `routes/requirements.py::patch_requirement` / `bugs.py::patch_bug` | 无任何可识别字段时仍返 200 + 完整体（用户以为改了）；第 4 轮已把 `patch_user` 收成 400，两边不一致 | 对齐为 400 `{"error":"no updatable field"}`；`project_id` 在此路由上单独给出**指路型** 400（见 §4.2） |
| P2-6 | `frontend/lib/constants.ts::actionLabel` | 新审计动作 `moved_project` 无中文映射（会显示成裸英文 key） | 补映射，并复核 `unassigned` 等既有值 |

**【评审 R11】P2-1 的三条落地约束**（少任何一条，超时都会变成一个更难查的 bug）：

1. **必须识别 `AbortError`**。`lib/api.ts` 现有的 `catch (e)` 把**一切** fetch 异常都规整成
   「无法连接服务器，请确认后端已启动」。超时抛出的 `AbortError` 会被这一句吞掉，
   用户看到一句与事实无关的提示。判据写 `e instanceof DOMException && e.name === "AbortError"`
   （或 `(e as Error)?.name === "AbortError"`），命中时抛
   `new ApiError(0, "请求超时，请重试")`。
2. **两个 fetch 点都要接**。`request()` 之外，`getWithHeaders()` 是**第二个**独立的 `fetch`
   调用点（分页读 `X-Total-Count` 走它）。只接第一个，列表页照样会永久转圈。
3. **必须 `clearTimeout`**。在 `finally` 里清掉定时器，否则每个请求都留一个待触发的
   `setTimeout`，长时间停留的页面会攒下大量无用定时器。

P2-1 与 P2-5 分别是「前端等一个永远不来的答案」和「后端给一个假的答案」——
和 §2.2 的静默忽略是同一族问题，一并收口才算干净。

**【评审 R10】P2-5 的两条 400 必须写死判定顺序。** `PATCH /:id {"project_id": 2}`
同时命中「含 `project_id`」与「无任何可识别字段」两条规则。顺序必须是：
**先判 `project_id` 并返回指路型 400**，再判「无可识别字段」。反过来的话用户会收到
一句 `no updatable field`，既没指出 `/:id/project`，也让 T-A13 的指路断言直接挂掉。
另：`expected_updated_at` **不计入**「可识别字段」（§7 R-6 已定），只传它 → `no updatable field`。

---

## 3. File / Module Change Plan（文件与模块变更计划）

### 3.1 Backend —— 新建 1 个 / 修改 13 个

| 文件 | 新建/修改 | 一句话意图 |
|---|---|---|
| `backend/services/identity.py` | **新建** | 请求内多态身份缓存：`prime()` / `summary()`，N+1 的唯一收口点（§2.4） |
| `backend/services/lifecycle.py` | 修改 | 新增 `assert_project_writable()`：归档 → 409 / 不存在 → 400，写入方向的单一真相（§2.2） |
| `backend/services/schema_sync.py` | 修改 | `ADDITIVE_COLUMNS` 追加 `("users","password_changed_at","DATETIME")`（§2.3） |
| `backend/models/user.py` | 修改 | `+password_changed_at` 列；`set_password()` 内写入该时刻（唯一写入点）（§2.3） |
| `backend/models/requirement.py` | 修改 | `_resolve_assignee` 改走 `identity.summary`（`bug.py` 共用此函数，无需改）（§2.4） |
| `backend/models/comment.py` | 修改 | `_resolve_author` 改走 `identity.summary`；`system` 与未知类型分支原样保留（§2.4） |
| `backend/errors.py` | 修改 | blocklist 钩子追加 `iat < password_changed_at` 判据（含 tz 补正）；**`revoked_token_loader` 按原因分流文案**（评审 R8）（§2.3） |
| `backend/routes/requirements.py` | 修改 | `+PATCH /:id/project`；`_validate_project` 换成 `assert_project_writable`；`PATCH /:id` 对 `project_id` 指路 400、无有效字段 400；列表预热（§2.2/§2.4/P2-5） |
| `backend/routes/bugs.py` | 修改 | 上述四项的 BUG 侧同构改动（复用 `requirements.py` 的公共辅助，**不复制第二份**） |
| `backend/services/board_page.py` | 修改 | **评审 R5 补漏**：v1 的 §2.4 预热表点名了本文件，§3.1 的清单却漏了它。改为「先收全列的行 → `prime()` 一次 → 再统一 `to_dict()`」，身份查询从「每列 2 条 × 7 列」降到「整块 ≤2 条」（§2.4） |
| `backend/routes/comments.py` | 修改 | `feed` / `comments` 序列化前预热身份（§2.4） |
| `backend/routes/notifications.py` | 修改 | 列表序列化前预热 actor 身份——铃铛 20 s 轮询，是频率最高的 N+1（§2.4） |
| `backend/routes/me.py` | 修改 | `change_password` 成功后签发并返回新 token；删除已过期的「不吊销」注释（§2.3）；`my_work` 序列化前预热身份（§2.4） |
| `backend/routes/users.py` | 修改 | 管理员重置密码：无需新增代码（`set_password` 已收敛），仅补 docstring 说明会踢掉对方会话（§2.3） |
| `backend/routes/projects.py` | 修改 | `GET /api/projects` 支持 `?with_counts=1`（additive）（P2-4） |

> **实施提示（防重复代码）**：`_wanted_project_id` / `_rehome_ticket` / `_project_label`
> 三个辅助放在 `routes/requirements.py` 的「公共辅助」区，`bugs.py` 以
> `from routes.requirements import _rehome_ticket, ...` 复用——项目里
> `check_concurrency` / `_validate_project` 已是这个模式，照做即可，
> **不要在 bugs.py 里写第二份**（第 3 轮 `_next_position` 双份副本的教训已写在注释里）。

### 3.2 Backend 测试 —— 新建 2 个 / 修改 2 个

| 文件 | 新建/修改 | 覆盖 |
|---|---|---|
| `backend/tests/test_ticket_project.py` | **新建** | 改派项目：成功 / 幂等 / 未归属 / 归档目标 409 / 不存在 400 / member 403 / 并发 409 / position 两端正确 / 审计文本 / 转 BUG 不受归档守卫影响 |
| `backend/tests/test_query_budget.py` | **新建** | 看板 / 列表 / feed / 通知的查询次数上界（常数阈值，N+1 回归护栏）+ 无上下文回退 + 跨请求不串缓存 |
| `backend/tests/test_auth.py` | 修改 | 改密后旧 token 401、新 token 200、管理员重置后对方旧 token 401、admin 自重置会登出自己且文案分流、`password_changed_at` 为 NULL 的存量用户不受影响 |
| `backend/tests/conftest.py` | 修改 | **只给既有 `bulk_tickets` 追加一个可选 `assignees` 参数**（评审 R1/R7）——**不要**新建 `many_tickets`：`bulk_tickets`、`auth(role)`、`archived_project` 都已存在（按符号名定位，别按行号——并行工作流已推移过一次），v1 引用的 `many_tickets` / `auth_pm` 是不存在的名字。`count_queries()` 是 `test_query_budget.py` 的模块内助手，不进 conftest（只有一个文件用） |

### 3.3 Frontend —— 新建 2 个 / 修改 12 个（外加各列表页的纯 className 调整）

| 文件 | 新建/修改 | 一句话意图 |
|---|---|---|
| `frontend/components/ui/MoveProjectDialog.tsx` | **新建** | 改派项目对话框：未归档项目 + 未归属；pending 禁用、失败不关窗、就地显示 409（§2.2） |
| `frontend/lib/nav-drawer.tsx` | **新建** | `NavDrawerProvider` / `useNavDrawer()`——窄屏导航开合的唯一状态源（§2.5） |
| `frontend/app/(app)/layout.tsx` | 修改 | 包 `NavDrawerProvider`；窄屏下侧栏脱流 + 遮罩（§2.5） |
| `frontend/components/layout/Sidebar.tsx` | 修改 | 受控开合 + `md` 断点；焦点与 `Esc` 处理（§2.5） |
| `frontend/components/layout/Header.tsx` | 修改 | 汉堡按钮（`md:hidden`）+ 窄屏折叠搜索 / 切换器（§2.5） |
| `frontend/components/TicketDrawer.tsx` | 修改 | 项目行显示归档标注（读 `PROJECTS_ALL_KEY`）+ pm/admin 的「移动」入口（§2.2） |
| `frontend/hooks/useTicket.ts` | 修改 | `moveProject(projectId: number | null)`；成功后 `mutate` + 失效列表/看板（§2.2） |
| `frontend/lib/swr-keys.ts` | 修改 | 改派项目后的失效集合（列表 / 看板 / 统计 / 我的工作）（§2.2） |
| `frontend/lib/api.ts` | 修改 | 请求超时（`AbortController`）（P2-1） |
| `frontend/lib/constants.ts` | 修改 | `actionLabel` 补 `moved_project`（P2-6） |
| `frontend/app/(app)/projects/page.tsx` | 修改 | 表格新增「需求 / BUG」计数列（`?with_counts=1`）（P2-4） |
| `frontend/app/(app)/settings/page.tsx` | 修改 | 改密成功后写入返回的新 token；文案说明「其它设备将被登出」（§2.3） |
| `frontend/app/(app)/team/page.tsx` | 修改 | **评审 R8 补漏**：重置密码确认框补一句「该成员所有登录会话将立即失效」；目标是**当前登录者本人**时改为「包括你自己在内，你需要用新密码重新登录」（§2.3） |
| `frontend/package.json` | 修改 | 删除跑不起来的 `lint` 脚本（P2-2） |
| 各列表页（requirements / bugs / team / projects / notifications / my-work） | 修改 | 表格外层 `overflow-x-auto` + `min-w`（§2.5，纯 className） |

### 3.4 文档

| 文件 | 变更 |
|---|---|
| `README.md` | 新增「真实世界就绪」章节：接口语义变更一览 + 质量门禁（数字用实测值） |
| `CLAUDE.md` | 质量门禁数字修正；新增一条硬约束：**「多态身份解析必须走 `services/identity.py`，禁止在序列化路径上直接 `db.session.get`」** |
| `.claude-index/index.md` | 成熟度与用例数修正；新增 `identity.py` / 新端点 / 新测试文件条目 |

---

## 4. Interface Design（接口设计）

### 4.1 新增端点

| 端点 | 权限 | 请求体 | 成功 | 失败 |
|---|---|---|---|---|
| `PATCH /api/requirements/<int:id>/project` | pm / admin | `{"project_id": int \| null, "expected_updated_at"?: iso}` | `200` + 工单体（shape 与 `PATCH /:id` 完全一致） | `404` 单不存在；`400` 缺字段 / 非整数 / 项目不存在；`409` 目标项目已归档；`409` 并发冲突（带 `detail.current_updated_at`）；`403` 非 pm/admin |
| `PATCH /api/bugs/<int:id>/project` | pm / admin | 同上 | 同上 | 同上 |

**归档 409 的响应体**（`detail` 必须可操作，否则前端只能弹一句废话）：

```json
{"error": "project is archived",
 "detail": {"project_id": 3, "key": "LEGACY", "archived_at": "2026-07-19T12:00:00Z"}}
```

### 4.2 既有端点的语义变更（**成功路径 shape 只增不改**）

| 端点 | 变更 | 破坏性？ |
|---|---|---|
| `PATCH /api/{requirements\|bugs}/:id` | 请求体含 `project_id` → **400** `{"error":"use PATCH /:id/project to move a ticket between projects"}`（此前静默忽略 + 200） | 行为收紧。**全仓 grep 确认今日无任何前端调用点传这个字段**，故对现有客户端零影响；且被收紧的是一个「本来就没生效」的用法 |
| `PATCH /api/{requirements\|bugs}/:id` | 无任何可识别字段 → **400** `{"error":"no updatable field"}`（此前 200 + 完整体） | 与第 4 轮 `PATCH /users/:id` 对齐；需检查既有测试里是否有裸 PATCH（§7 R-6） |
| `POST /api/requirements`、`POST /api/bugs` | `project_id` 指向**已归档**项目 → **409**（此前 201） | 语义收紧。这正是「归档」二字的含义；前端建单表单本就不列出归档项目，故正常路径零影响 |
| `POST /api/me/password` | 响应体 additive 增加 `token`（新签发）；旧 token 立即失效 | additive；老客户端读不到 `token` 只会多登录一次 |
| 全部 `@jwt_required()` 端点 | `iat` 早于该用户 `password_changed_at` 的 token → **401**，`error` 为 **`password changed, please sign in again`**（评审 R8：**不复用** `account is disabled or removed`——对改密场景那句话是假的） | 有意的安全收紧；存量用户 `password_changed_at IS NULL` → 零影响 |
| 既有的吊销 401（停用 / 删除） | 文案不变，仍为 `account is disabled or removed` | 无（分流只新增一条分支，旧分支逐字不动） |
| `GET /api/projects` | 新增可选 `?with_counts=1`：每项 additive 增加 `counts: {requirements, bugs}` | additive，缺省不返回该字段（不给不需要的调用方增加两次聚合查询） |
| 全部返回工单 / 评论 / feed 的端点 | 响应体**逐字节不变**；只是内部查询次数从 O(N) 降到 O(1) | 无 |

### 4.3 错误契约（沿用全局约定）

所有非 2xx 恒为 `{error: string, detail?: object}`；本轮不新增任何错误码族。
`409` 在本项目已有两种来源（状态机非法迁移带 `allowed`；乐观并发带 `detail.current_updated_at`），
本轮新增第三种（归档项目带 `detail.project_id/key/archived_at`）——**三者靠 `detail` 的键区分**，
前端 `MoveProjectDialog` 只需读 `error` 与 `detail`，无需分支判断来源。

### 4.4 前端调用约定

> 【评审 R3/R4：v1 的原始写法有三个会当场翻车的地方，已在此重写】
> ① `invalidateTicketViews` 的真实签名是 `(mutate: ScopedMutator) => Promise<...>`
> （`lib/swr-keys.ts:33`），v1 的无参调用会让 `tsc --noEmit` 直接红，打掉 §6.2 门禁；
> ② `useTicket` 的既定分工是「hook 只 mutate 自己的两个 key，跨视图失效由调用方做」
> ——`remove` 的注释逐字写着这一条，把失效塞进 hook 会造出第二套约定；
> ③ 改派会写 `moved_project` 审计，**必须同时刷 feed**，否则抽屉时间线里看不到刚刚发生的事；
> ④ 项目工单计数（P2-4）在 `/projects` 上，只有 `invalidateAdminViews` 的前缀覆盖它。

```ts
// hooks/useTicket.ts —— 与既有 patch() 完全同形：只落自己的两个 key
const moveProject = useCallback(
  async (projectId: number | null) => {
    if (!id) return;
    const updated = await api.patch<Ticket>(`/${entity}/${id}/project`, {
      project_id: projectId,
      expected_updated_at: ticket?.updated_at,   // 与 patch/move 同一并发语义
    });
    mutateTicket(updated, { revalidate: false });
    mutateFeed();                                // 改派写审计 → 时间线必须跟着变
    return updated;
  },
  [entity, id, ticket, mutateTicket, mutateFeed]
);
```

```tsx
// components/TicketDrawer.tsx —— 跨视图失效在调用方，与既有 remove() 的处理逐字同形
// （该文件第 60 行已有 `const { mutate } = useSWRConfig()`，第 182 行已有一次 invalidateTicketViews(mutate)）
async function handleMoved() {
  invalidateTicketViews(mutate);   // 列表 / 看板 / 统计 / 我的工作 / 通知 / 搜索
  invalidateAdminViews(mutate);    // 【R4】/projects：项目页的工单计数随改派变化
}
```

> `entity` 在 `useTicket` 里已经是复数形式（`"requirements" | "bugs"`），所以路径是
> `/${entity}/${id}/project` 而**不是** v1 写的 `/${entity}s/...`——后者会请求
> `/requirementss/3/project` 并 404。

---

## 5. Data Model（数据模型）

### 5.1 新增列（零新表）

| 表 | 列 | 类型 | 可空 | 语义 |
|---|---|---|---|---|
| `users` | `password_changed_at` | `DATETIME` | **是**（`NULL` = 从未改过密码） | 早于该时刻签发的 token 一律失效 |

**迁移**：在 `services/schema_sync.py::ADDITIVE_COLUMNS` 追加
`("users", "password_changed_at", "DATETIME")`。启动时由第 4 轮的加列迁移器幂等补齐。
**严禁**给它 `NOT NULL` 或 `DEFAULT CURRENT_TIMESTAMP`——那会让存量库在迁移的一瞬间
把所有人的 token 一起作废（见 §2.3 的警告与 §7 R-1）。

### 5.2 不新增的东西（明确记录，避免实施时擅自扩张）

- **不新增 `sessions` / `token_blocklist` 表**：吊销判据是「用户状态 + 时间戳比对」，
  是无状态的；引入表意味着写路径、清理任务与一致性问题，收益为零。
- **不新增 `activities.action` 枚举约束**：`action` 至今是自由字符串 + 前端 label 映射，
  本轮新增 `moved_project` 沿用该模式（第 4 轮 F4 已就此做过同样判断）。
- **不新增第 7 种通知类型**：`NOTIFICATION_TYPES` 是 6 元组且与用户偏好一一对应，
  为「改派项目」加第七类会连带偏好表、设置页与迁移。改派项目只写审计不发通知，
  理由与「改标题不发通知」一致（§9）。
- **不给 `identity.py` 加进程级缓存**：`flask.g` 随请求消亡，因此**不存在失效问题**；
  跨请求缓存会立刻引入「改了名字页面还显示旧名」，用一个更难的问题换一个更小的收益。

---

## 6. Testing & Acceptance（测试与验收标准）

### 6.1 后端 pytest 新增用例（按文件，名字即断言）

**`test_ticket_project.py`（新建，约 16 例）**

| # | 用例 | 断言 |
|---|---|---|
| T-A1 | `moves_ticket_to_another_project` | 200；`project_id` 变更；两端 board 各自可见 |
| T-A2 | `moves_ticket_to_unassigned_with_explicit_null` | `{"project_id": null}` → 200，`project_id is None` |
| T-A3 | `rejects_move_into_archived_project` | 409，`detail.key` 存在 |
| T-A4 | `allows_move_out_of_archived_project` | 200（归档只拦「放进去」） |
| T-A5 | `rejects_unknown_project` | 400 `project not found` |
| T-A6 | `rejects_member_moving_project` | member → 403 |
| T-A7 | `convert_to_bug_ignores_archive_guard` | 源需求在归档项目里，转 BUG 仍 201 |
| T-A8 | `source_column_is_reindexed_after_move` | 源列 position 连续 `0..n-1`，无洞 |
| T-A9 | `target_column_appends_at_tail` | 新 position = 目标列原最大值 + 1 |
| T-A10 | `same_project_move_is_idempotent_and_writes_no_activity` | 200，活动数不变 |
| T-A11 | `honours_expected_updated_at_conflict` | 陈旧时间戳 → 409 |
| T-A12 | `writes_moved_project_activity_with_both_names` | 审计文本含新旧项目名 |
| T-A13 | `rejects_project_id_on_plain_patch` | `PATCH /:id {"project_id":2}` → 400 且指路 |
| T-A14 | `rejects_patch_without_updatable_field` | `PATCH /:id {}` → 400 |
| T-A15 | `rejects_creating_ticket_in_archived_project` | POST → 409 |
| T-A16 | `bug_side_is_symmetric` | 上述关键路径在 `/api/bugs` 上同样成立 |

**`test_query_budget.py`（新建，约 7 例）**

> **所有预算用例的数据必须带互不相同的 assignee**（评审 R1）：`bulk_tickets` 不传
> `assignees` 时造出的全是「未指派」，而未指派在 `_resolve_assignee` 里是**零查询的早返回**
> ——护栏会在未修复的代码上也变绿。同理，feed 用例的评论必须来自**多个不同作者**。

| # | 用例 | 断言 |
|---|---|---|
| T-C0 | `budget_guard_is_red_before_the_fix` | **护栏自证**（新增）：实施者在**打补丁之前**先跑一次 T-C1/T-C2/T-C3 并把红值记进 PR 说明。若三条在未修复的代码上就是绿的，说明数据造错了（多半是没带 assignee），护栏无效，必须先修用例再修代码 |
| T-C1 | `board_query_count_is_constant` | 120 卡 + ≥3 个不同 assignee 的看板 ≤ **25** 条查询（未修复时约 115） |
| T-C2 | `list_query_count_is_constant` | `?limit=200` ≤ **12** 条（未修复时约 203） |
| T-C3 | `feed_query_count_is_constant` | 60 评论（多作者）+ 60 活动 ≤ **12** 条（未修复时约 124） |
| T-C4 | `identity_cache_falls_back_without_request_context` | 无请求上下文时 `to_dict()` 仍返回正确 assignee（Agent 运行时路径） |
| T-C5 | `notifications_query_count_is_constant` | 50 条通知 ≤ **10** 条查询（铃铛 20 s 轮询，频率最高） |
| T-C6 | `identity_cache_never_leaks_across_requests` | 用两个不同用户连续请求，第二次不得读到第一次缓存的身份（R-4 的护栏） |

**`test_auth.py`（修改，新增约 6 例）**

| # | 用例 | 断言 |
|---|---|---|
| T-B1 | `old_token_is_rejected_after_password_change` | 旧 token → 401 |
| T-B2 | `returned_token_works_after_password_change` | 响应里的新 token → 200 |
| T-B3 | `admin_reset_revokes_target_user_tokens` | 被重置者旧 token → 401；管理员自己不受影响 |
| T-B4 | `legacy_user_without_password_changed_at_is_unaffected` | 手动置 `NULL` 后旧 token 仍 200 |
| T-B5 | `health_and_login_are_never_blocked_by_revocation` | `/api/health`、`/api/auth/login` 不受影响 |
| T-B6 | `password_change_still_rejects_wrong_current_password` | 既有 400 行为不回归 |
| T-B7 | `admin_resetting_own_password_revokes_own_token_with_distinct_message` | 评审 R8：admin `PATCH /api/users/<自己> {"password":...}` → 200；其旧 token 下一次请求 **401**，且 `error == "password changed, please sign in again"`（**不是** `account is disabled or removed`）；停用用户的 401 文案保持旧值不变 |

**回归基线**：评审当日实测 **342 passed / exit 0**（评审已独立重跑确认）。但**必须以你开工当天
自测的数字为准**——同一个工作树里有并行工作流在持续增加用例（评审 R14 / §7 R-15）。
判据是**零失败 + 用例数不下降**，不是某个写死的绝对值。任一既有用例需要修改，都要在 PR 说明里
逐条给出理由（本轮预期只有 §7 R-6 提到的裸 `PATCH` 用例可能需要调整）。

### 6.2 前端质量门禁

```
cd frontend
npm run typecheck    # tsc --noEmit → 0 error
npm run build        # next build → 16/16 页成功
```

### 6.3 手工验收冒烟（逐条可勾）

**A 组 —— 项目改派与归档**

| # | 步骤 | 期望 |
|---|---|---|
| A-1 | pm 打开任一工单抽屉 → 项目行点「移动」→ 选另一个项目 | 抽屉项目名即时更新；列表 / 看板 / 仪表盘随之刷新 |
| A-2 | 在目标项目的看板里查看该卡 | 出现在正确的列**尾部**，序号连续 |
| A-3 | 回到源项目看板 | 其余卡序号连续无洞 |
| A-4 | 归档一个项目 → 建单表单 / 切换器 | 看不到它（现状保持） |
| A-5 | 用 curl 往归档项目建单 | **409**，`detail` 带项目 key |
| A-6 | 打开归档项目里某张单的抽屉 | 显示「Alpha（已归档）」，不是裸 `#3` |
| A-7 | 把该单移出到未归档项目，然后在项目页删除原项目 | 移出 200；原项目已空 → 删除 204（第 4 轮的 409 死胡同就此打通）|
| A-8 | 项目页 | 每行显示「需求 12 / BUG 3」，与删除 409 的计数一致 |
| A-9 | member 打开抽屉 | 看不到「移动」按钮；直调 API → 403 |
| A-10 | 改派成功后**不刷新页面**，直接看抽屉时间线与项目页 | 时间线立刻出现「移动到项目…」（`mutateFeed`）；项目页两个计数列同步变化（`invalidateAdminViews`）——评审 R3/R4 |

**B 组 —— 改密与会话**

| # | 步骤 | 期望 |
|---|---|---|
| B-1 | 浏览器 A 与 B 同时登录 alice → 在 A 改密码 | A 仍然可用（拿到新 token）；B 的下一次操作被自动登出并跳登录 |
| B-2 | 用旧密码登录 | 401 |
| B-3 | admin 在成员页重置 bob 密码 | bob 的会话下一次请求即登出；admin 自己不受影响 |
| B-5 | admin 在成员页重置**自己**的密码（评审 R8） | 确认框事先说明「包括你自己在内的所有会话都会结束」；确认后下一次请求即登出，且提示是「密码已修改，请重新登录」而**不是**「账号已被停用或删除」 |
| B-4 | 一份**第 4 轮之前**的 `aragon.db` 副本启动 | 日志出现 `schema_sync applied`；所有人可正常登录（`password_changed_at` 为 NULL） |

**C 组 —— 性能**

| # | 步骤 | 期望 |
|---|---|---|
| C-1 | 造 2000 单后打开看板 | 后端日志中该请求耗时显著下降；`test_query_budget` 全绿 |
| C-2 | 打开一条 60 评论的工单 | feed 秒开，查询数 ≤ 12 |

**D 组 —— 窄屏**

| # | 步骤 | 期望 |
|---|---|---|
| D-1 | 浏览器窗口拖到 390 px（或 DevTools iPhone 预设）逐页浏览 | 无横向溢出；正文可读；侧栏收起 |
| D-2 | 点汉堡按钮 | 抽屉滑出 + 遮罩；点遮罩 / `Esc` 关闭；焦点回到按钮 |
| D-3 | 窄屏打开工单抽屉 | 全宽显示，所有按钮可点 |
| D-4 | 窄屏看板 | 列可横滑，卡片不被压扁 |
| D-5 | 窗口 ≥ 768 px | **与本轮改动前逐像素一致**（这是硬验收） |

**Z 组 —— 无回归**

| # | 步骤 | 期望 |
|---|---|---|
| Z-1 | 「▶ 运行 AI 团队一轮」 | 与第 3 / 4 轮一致：需求到 `reviewing`、BUG 到 `closed` |
| Z-2 | 看板拖拽（含跨列） | 状态机裁决不变；非法迁移 409 + 回滚 |
| Z-3 | 停用成员 / 删 Agent / 删项目 | 第 4 轮行为一字不变 |

### 6.4 Definition of Done

1. `pytest -q` **零失败、exit 0，且用例总数不低于开工当天自测的基线 + 28**。
   **用相对判据，不写死绝对数**（评审 R14）：`CLAUDE.md` 已被并行工作流改成这个约定，
   而且同一个工作树里还有别人的用例在增加——把「≥370」当硬门禁，要么误判通过、
   要么误判失败。**实施第一步就是先跑一次 `pytest -q` 记下你自己的基线数**，
   本文件写的 342 是评审当日的实测值，不保证你开工时还是它。
2. `tsc --noEmit` 0 error；`next build` 16/16 页成功。
3. §6.3 的 A/B/C/D/Z 五组冒烟全部 PASS，其中 **D-5（≥768 px 零变化）** 与
   **Z-1/Z-2/Z-3（前四轮功能零回归）** 是一票否决项。
4. 用一份**第 4 轮之前**的 `aragon.db` 副本启动一次，登录正常（B-4）。
5. `README.md` / `CLAUDE.md` / `.claude-index/index.md` 的数字与实测一致。
6. 全仓 `grep` 确认：序列化路径上没有残留的 `db.session.get(User` / `db.session.get(Agent`；
   `bugs.py` 里没有 `_rehome_ticket` 的第二份实现。

---

## 7. Risks & Mitigations（风险与缓解）

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R-1 | `password_changed_at` 若写成 `NOT NULL DEFAULT CURRENT_TIMESTAMP`，存量库迁移瞬间全员登出 | **灾难级**（一次升级把所有人踢下线） | 列必须可空、无 server_default；`test_auth.py::T-B4` 专门守卫；§2.3 与 §5.1 双处红字警告 |
| R-2 | `iat` 与 `password_changed_at` 同秒时的 1 秒窗口内，旧 token 仍有效 | 极低（需要攻击者恰好在同一秒发请求） | 判据用 `<` 是为了避免「改密即死循环」；窗口显式登记在此，不假装不存在 |
| R-3 | SQLite 取回的 `DateTime` 是 naive，时区处理错误会误杀或漏杀 token | 高（在非 UTC 机器上表现为「改密后随机被登出」或「吊销不生效」） | 统一 `replace(tzinfo=timezone.utc).timestamp()`；测试在断言前显式构造 naive/aware 两种值 |
| R-4 | `identity.py` 的缓存若挂在模块级或 `app` 上而非 `flask.g`，会跨请求串数据（A 用户看到 B 的名字） | **严重**（信息泄露） | 缓存键固定为 `flask.g`；`test_query_budget::T-C4` 覆盖无上下文回退；评审必须逐行确认没有模块级 dict |
| R-5 | `prime()` 的 `IN` 子句在极端页大小下参数过多（SQLite 上限 999） | 中 | 页大小上限已由 `MAX_LIMIT=200` 与 `MAX_COLUMN_LIMIT=500` 钳住；`prime` 内部按 500 分批 |
| R-6 | `PATCH /:id` 无有效字段改 400，可能打到既有测试或某个只传 `expected_updated_at` 的调用 | 中 | 实施前先 `grep` 全仓 PATCH 调用点；`expected_updated_at` **不计入**「可识别字段」判定，但只传它时应返回 400（语义即「你什么都没改」） |
| R-7 | `_rehome_ticket` 的 `flush()` 顺序写反（先 reindex 后改 project）会把这张单也算进源列 | 中（序号错乱） | §2.2 给出的代码模板已定序；T-A8/T-A9 双向断言 |
| R-8 | 响应式改造是纯视觉大面积 diff，无自动化测试，容易在宽屏引入回归 | 中 | 全部改动限定在 `< md` 分支（新增类一律带 `md:` 复原）；D-5 为一票否决冒烟项 |
| R-9 | 归档守卫接到 `_validate_project` 上，可能误伤「归档项目内部」的既有流程 | 中 | 守卫只在**创建**与**改派进来**两个方向生效；转 BUG 显式豁免并有 T-A7 守卫 |
| R-10 | 前端超时（P2-1）设得过短，会让本来能成功的慢请求变成假失败 | 低 | GET 15 s / 写 30 s；`autorun-all` 等长跑接口走写超时；超时文案区别于网络错误 |
| R-11 | 新端点 `/:id/project` 与既有 `?project_id=` 查询参数在命名上易混 | 低 | 端点是**路径**、过滤是**查询串**，README 的接口表并列写出以消歧 |
| R-12 | 本轮四条改动分属四个领域，实施时若并行推进会难以定位回归 | 中 | §10 强制四阶段串行，每阶段独立门禁 |
| R-13 | 同一请求内先改了某人的 `display_name`（`PATCH /users/:id`）再序列化含该人的列表，缓存会返回改前的值 | 低 | 今日没有任何一个端点在同一请求里既改身份又列工单；若将来出现，在写入后 `g.pop(_CACHE_KEY, None)` 即可。**在 `identity.py` 的模块 docstring 里写明这一条**，比事后调试便宜得多 |
| R-14 | `prime()` 只在部分路由接入，未接入的路由静默退回逐行查询（性能回归无人察觉） | 中 | `test_query_budget.py` 覆盖看板 / 列表 / feed / 通知四条主路径；新增序列化路径时，评审清单要求同步加一条查询预算断言 |
| R-15 | **已发生，不再是风险预警**（评审 R14）：并行工作流 `data-persistence-and-seed-slimming` 的代码**已经落进同一个工作树**。评审当日 `git status` 显示它改动的文件里，与本轮**直接重叠**的有：`backend/tests/conftest.py`（本轮要扩 `bulk_tickets`）、`backend/models/user.py`（本轮加列）、`backend/models/requirement.py`（本轮改 `_resolve_assignee`）、`backend/routes/requirements.py`（本轮加端点）、`backend/errors.py`（本轮改吊销钩子）、`backend/app.py`；它还新增了 `models/seed_record.py` / `tools/purge_demo_data.py` 并改写了 `seed.py` 与 `CLAUDE.md` | **高** | ① 实施前**先跑一次 `pytest -q` 记录你自己的基线**，别用本文件的 342；② 本文件所有 `文件:行号` 引用都可能已经偏移——**一律按符号名定位**（评审已把测试 fixture 的引用改成按名）；③ 严格限定在本文件 §3 的清单内，绝不顺手改另一份方案的落点；④ **`CLAUDE.md` 的质量门禁段落已被对方改成相对判据，本轮不得改回写死的数字**；⑤ `models/user.py` 加列前先确认对方是否也动了该模型与 `ADDITIVE_COLUMNS`，两边都加列时**登记顺序无关但不能重名** |

---

## 8. Out of Scope（本轮明确不做，及理由）

1. **移动端重设计**（触屏拖拽看板、底部导航、手势）——本轮只做「窄屏不再不可用」，
   真正的移动端体验需要独立的信息架构决策，且 `@dnd-kit` 的触屏拖拽与「转 BUG」这类
   不可逆操作的误触防护（第 3 轮已用 `pointer-events` 处理过一次）需要单独一轮。
2. **引入 eslint / 前端单测框架**——都是新依赖。前端质量门禁本轮仍是 `typecheck` + `build`；
   P2-2 的做法是**删掉那个跑不起来的脚本**而不是补上依赖，因为「声明了但用不了」比「没有」更坏。
3. **Redis / 进程外缓存 / 连接池调优**——§2.4 的 N+1 是算法级问题，修好之后单机 SQLite
   完全够用；引入外部依赖属于部署形态演进，与本轮主题正交。
4. **WebSocket / SSE 实时化**——与前四轮结论一致，通知与看板继续走 SWR 轮询。
5. **`agent_runs` 运行历史表 / Agent 可观测面板**——新表 + 新功能，第 4 轮已列为 out of scope，
   本轮不推翻。
6. **工单软删 / 回收站**——第 3 轮已定型硬删 + 级联，README 已写；不在一轮里推翻两轮结论。
7. **评论的编辑 / 删除**——第 4 轮的理由继续成立（收益小、牵动 feed 与通知收件人集合）。
8. **批量操作**（批量改派项目 / 批量指派）——本轮先把**单条**改派做对；批量需要选择态、
   部分失败语义与撤销，是一个独立特性而非缺陷修复。
9. **引入 Alembic**——本轮唯一的 schema 变更是一次纯 ADD COLUMN，正落在
   `schema_sync` 的能力边界内（CLAUDE.md 已写死判据：出现改类型 / 改约束 / 数据回填才换）。

---

## 9. 设计取舍说明（含被排除的候选缺陷）

以下候选我在排查中列过，**经复现后主动排除**，记录在此以免下游重复劳动：

- **「看板每列上限 100 × 6 列 = 600 张卡仍然太大」**——排除为本轮范围。默认值是第 4 轮
  刚定的产品取舍，且真正的成本是 §2.4 的 615 次查询而非 600 个对象；N+1 修好后
  195 KB 的序列化成本可接受。**连续两轮改同一个默认值不明智。**
- **「看板列被截断时拖拽会排错序」**——**实测排除（这是一个假设的缺陷，实际是对的）**：
  `?column_limit=2` 截断后把第 2 张卡拖到首位，`move` 走的是全列 `_reindex_column`，
  返回的整列顺序为 `[5,4,6,7,8,9,10]`，position 连续无重复。第 4 轮 §8-7 的「接受偏差」
  在这个场景下并没有产生偏差。
- **「`PATCH /:id` 应该直接支持 `project_id`（少一个端点）」**——排除。见 §2.2-A3：
  它会让一条路由同时承载 `can_manage_ticket` 与 `pm/admin` 两套门禁。
- **「改派项目应该发通知」**——排除。`NOTIFICATION_TYPES` 是与用户偏好一一对应的 6 元组，
  加第七类会连带偏好表、设置页与迁移；而「工单换了个文件夹」对 assignee 的实际影响
  小于「换了负责人」。审计时间线仍然完整记录。
- **「`db.session.get` 在 `_resolve_assignee` 里可以用 `joinedload` 替代」**——排除。
  assignee 是**多态**的（`assignee_type` + `assignee_id`，无外键关系），ORM 关系加载不适用；
  为它建两条真外键关系是模型层的破坏性改动。请求内缓存是成本最低且零契约变更的解。
- **「`GET /api/users` 会把已停用成员也返回给所有人」**——排除。第 4 轮有意为之
  （团队页要显示「已停用」标记），`AssigneePicker` 已在前端过滤。
- **「`POST /api/auth/register` 是冗余端点」**——排除（第 4 轮已判过一次，结论不变）。
- **「登录限流是进程内的」**——排除（同上，属部署形态演进）。
- **「`/api/board/*` 的 `setdefault` 容错分桶会隐藏非法状态」**——排除（第 4 轮已判过）。
- **「改派需求时应把它转出的 BUG 一起搬过去」**——排除（评审 R13）。`Bug.related_requirement_id`
  是一条**弱关联**（删需求时也只是置空，不级联删，见 `routes/requirements.py::delete_requirement`），
  把它升级成「跟着搬」等于凭空发明一条未经设计的级联规则：BUG 有自己的
  reporter / assignee / 看板列，它归谁管是一个产品判断，不该由「需求换了个文件夹」代答。
  **实施时不要顺手补这个级联**——本条明确记录，就是为了让下一个读代码的人知道这是取舍不是遗漏。
- **「`identity.py` 应该同时缓存 `Project`，把 `_project_label` 也压掉」**——排除。
  `_project_label` 只在**改派这一条写路径**上一请求调用两次，不是 N+1；
  把无关实体塞进身份缓存会让这个模块的职责从「多态身份」漂成「什么都缓存」。

---

## 10. 实施顺序建议（给 Subtask #2 · 严格四阶段，每阶段独立门禁）

**阶段 1 —— 性能收口（先做，因为它改的是所有序列化路径的公共底座）**
`services/identity.py` + `models/requirement.py` + `models/comment.py` + 四处 `prime()` +
`tests/test_query_budget.py` + `conftest.py` 的 fixture。
门禁：`pytest -q` 全绿（342 + 4）；T-C1/T-C2/T-C3 的查询数达标；
**响应体与改动前逐字节一致**（用同一组请求 diff JSON，这是本阶段的核心断言）。

**阶段 2 —— P0 项目改派 + 归档守卫**
`services/lifecycle.py::assert_project_writable` + `routes/requirements.py`（新端点 + 辅助 +
`_validate_project` 替换 + `PATCH` 两处 400）+ `routes/bugs.py` 复用 +
`tests/test_ticket_project.py` + 前端 `MoveProjectDialog` / `TicketDrawer` / `useTicket` /
`swr-keys` / `constants`。
门禁：`pytest -q` 全绿；冒烟 A-1…A-9 全 PASS。

**阶段 3 —— 会话安全**
`models/user.py` 加列 + `schema_sync` 登记 + `errors.py` 判据 + `routes/me.py` 新 token +
`settings` 页 + `tests/test_auth.py`。
门禁：`pytest -q` 全绿；冒烟 B-1…B-4 全 PASS；**其中 B-4（存量库启动 + 登录）不通过则立即回退**。

**阶段 4 —— 窄屏可用性 + P2 收口 + 文档**
`lib/nav-drawer.tsx` + 外壳 / `Sidebar` / `Header` + 各列表页 `overflow-x-auto` +
P2-1…P2-6 + `README` / `CLAUDE.md` / 索引。
门禁：`tsc --noEmit` 0 error；`next build` 16/16；冒烟 D-1…D-5 与 Z-1…Z-3 全 PASS。

每个阶段结束都要能回答一句话：**「这一阶段之后，用户多了哪一种以前做不到的事？」**
- 阶段 1：数据变多之后，页面仍然是秒开的。
- 阶段 2：把工单挪到别的项目——以及因此真正能清空并删除一个项目。
- 阶段 3：改密码这个动作，第一次真的把别人踢了出去。
- 阶段 4：在手机上打开这个平台，并且每一页都能用。

答不上来，说明阶段划分错了。

**【评审补充】阶段 0（开工前 15 分钟，不可跳过）**：并行工作流已经把代码落进同一个工作树
（§7 R-15 / 评审 R14）。开工第一件事是 `git status` + `pytest -q`，**记下你自己的基线用例数**，
并确认本文件引用的符号（`bulk_tickets` / `_validate_project` / `_next_position` /
`invalidateTicketViews`）在当前工作树里的实际形态——**按名字找，不要按行号**。

---

## 评审结论（Review Verdict）

### 结论：**有条件通过（Approved with conditions）**

v1 的**缺陷诊断**质量很高：评审逐条核验了它引用的源码锚点，没有发现一条捏造或推测的证据，
连它自我否决的候选（`seed.py` 幂等、看板截断拖拽）也复核为正确。方向判断也站得住：
这五类确实是「演示能过、真用就散架」的同一族问题，与前四轮正交。

但**修复方案本身**问题集中：v1 有 6 处代码块 / 接口引用与仓库现状对不上，
其中 4 处逐字实现会当场失败（`_iso` NameError、`invalidateTicketViews()` 类型错、
URL 多一个 `s`、`event.remove(..., ...)` 字面省略号），
1 处会让本轮**最重要的那条护栏在未修复的代码上也变绿**（P0-R1），
1 处会让正确实现反而顶穿阈值、诱导实施者去放宽护栏（R5）。
这些已在 v2 中**全部就地修复**，P0 / P1 均已清零。

### 放行条件（每条都绑定一个可勾的验收项，缺一不可）

| # | 条件 | 绑定验收 |
|---|---|---|
| C1 | **先证明护栏是红的**：打补丁前跑一次查询预算用例并把红值记进 PR；数据必须带互不相同的 assignee | T-C0 / T-C1-C3 |
| C2 | **不新建重复 fixture**：只给既有 `bulk_tickets` 追加 additive 的 `assignees`，复用 `auth(role)` / `archived_project` | §3.2 / §6.4-6 |
| C3 | **看板预热一次、不逐列**：`column_page` 改成「先收行 → prime → 再序列化」，并核对 7 列的推导 | T-C1 ≤ 25 |
| C4 | **吊销文案分流**：改密的 401 不得复用「账号已被停用或删除」；admin 自重置要事先告知 | T-B7 / B-5 |
| C5 | **改派的刷新分工照 §4.4 实现**：hook 只落两个 key（含 feed），跨视图失效在调用方且**必须含 `invalidateAdminViews`** | A-10 |
| C6 | **`PATCH /:id` 两条 400 的顺序**：先 `project_id` 指路，再「无可识别字段」 | T-A13 / T-A14 |
| C7 | **阶段 1 的响应体逐字节 diff 必须做**：这是「只加速、不改语义」的唯一证据，`summary()` 的浅拷贝改动尤其需要它 | §10 阶段 1 门禁 |
| C8 | **先跑阶段 0**：记录你自己的基线用例数，按符号名而非行号定位；不得把 `CLAUDE.md` 的相对门禁改回写死数字 | §6.4-1 / §7 R-15 |

### 评审对「右尺寸」的判断

四个领域（性能 / 功能 / 安全 / 可用性）放在一轮里偏大，但**可以放行**，理由是
§10 的四阶段划分是真串行、每阶段有独立门禁、且阶段间没有共享的半成品状态。
若实施中时间不够，**允许把阶段 4（窄屏 + P2）单独顺延**——它是唯一没有自动化门禁的部分，
顺延不会让前三阶段处于「改了一半」的状态。**不允许**顺延的是阶段 1：
它是所有序列化路径的公共底座，后面三个阶段都在它之上改。

### 遗留的 P2（不阻塞放行，实施时顺手带上即可）

R9（幂等前置）、R10（400 判定顺序）、R11（超时三约束）、R12（`summary()` 浅拷贝）、
R13（转出 BUG 不跟着搬，已记入 §9）——五条都已在 v2 正文里给出确切写法，
不需要实施者再做设计决策。


