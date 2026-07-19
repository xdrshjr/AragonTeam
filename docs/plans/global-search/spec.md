# 全局统一搜索（Global Search）开发方案

> 版本：**v2**（Subtask #1 逐节评审通过、就地修复全部 P1 后升版；P0=0）
> 迭代：Loop Iteration 3/5 · 阶段目标「对项目中的所有 mock / 占位逻辑真实化，完善接口与功能，稳健可靠好用，主流程无大报错」
> 前置：
> - Iteration 1 已把**唯一的业务 Mock**（Agent 执行引擎罐头文案）真实化（`docs/plans/real-agent-execution/spec.md`，commit `12c5a4c`）。
> - Iteration 2 已把**最后一处显式用户占位**（设置页）真实化为账号自助中心（`docs/plans/account-settings/spec.md`，commit `1373e94`），并在其 §11「后续迭代路线」把本轮选题**明确交棒**：第 1 项即「统一全局搜索（B5/B6）」。

## 评审记录（Review Notes）

> Subtask #1（Anthropic Eng · 资深评审）逐节复核。每条问题均**对照真实代码取证**（文件:行号），并按 P0/P1/P2 定级；P0/P1 已就地修复并升 v2，P2 记录备查、不阻断落地。评审维度：可行性 / 完备性 / 一致性 / 合理规模。

**取证结论（可行性 & 一致性总览）**：方案依赖的所有接缝均经代码核实存在且形状匹配——`updated_at` 列（`models/requirement.py:33`、`models/bug.py:34`）、`to_dict()`、`swrFetcher`（`lib/api.ts:102`，`API_BASE=".../api"` 故 SWR key 用 `/search` 正确）、`statusStyle`（`lib/constants.ts:88`）、`aragon:open-ticket`/`aragon:search`/`?ticket=`/`?q=` 契约、`conftest` 的 `client/auth/make_requirement/make_bug/data` fixture、后端 `or_` 与既有裸 `ilike`（`routes/bugs.py:56-58`、`routes/requirements.py:154-157`）、全仓无 `/api/search`（R8 成立）。检索排序键分叉（search 用 `updated_at desc`，list 用 `position asc`）为 §2.3 显式论证的**有意设计**，非缺陷。规模合理：2 新后端文件 + 1 注册 + 1 测试；1 新组件 + 3 处改动；零 DB / 零既有 shape 变更——不过度设计、不欠规格。

| 级别 | 编号 | 维度 | 问题 | 处置 |
|------|------|------|------|------|
| **P0** | — | — | 无。 | — |
| **P1** | P1-1 | 一致性 / 正确性 | **实体命名单复数不一致**：§2.2-B 用**单数** `kind:'requirement'` + 隐式 `seg` 单→复映射，而 §6.4 实现指引、既有 board 页监听（`d.entity === "requirements"` @ `requirements/board/page.tsx:31`、`=== "bugs"` @ `bugs/board/page.tsx:24`）、路由段（`/requirements/board`、`/bugs/board`、列表 `/requirements`、`/bugs`）均要求**复数「路由段」形式**。若按 §2.2 落地：`router.push('/requirement/board')` → **404**；`dispatch {entity:'requirement'}` 永不等于 board 的 `=== "requirements"` 判定 → **同页直达/打开双双失效**（正是本特性核心交互）。 | **已修复**：§2.2-A/B/D 与架构图统一为复数路由段 `kind`，删除 `seg` 映射，并新增「命名不变量」注（`kind` == 路由段 == `aragon:open-ticket` 的 `detail.entity` == board 比较值，四处逐字一致，权威定义见 §4.2）。 |
| **P1** | P1-2 | 完备性 / 测试严谨 | **`test_search_escapes_like_wildcards` 无法真正验证转义**：原诱饵「abcdef」既不含 `100` 也不含 `100%`，无论转义与否（`%100%%` vs `%100\%%`）都只命中「100% 完成」；测试对「删除 `escape="\\"`/漏转义」**不敏感**，会给出假绿——恰恰放过本特性头号稳健点（R2 通配泄漏防护，也是新建 `services/search.py` 而非复用裸 list 逻辑的**唯一技术理由**）。 | **已修复**：§7.1 重设计为「诱饵含前缀但无字面元字符」——`q=%` + 无 `%` 诱饵（未转义 `%%%` 命中全部、转义 `%\%%` 仅命中含字面 `%` 者），成为真正区分「有无转义」的回归护栏。 |
| **P2** | P2-1 | 完备性 / 可落地 | §7.1 称「复用 `make_requirement`/`make_bug`」，但两 fixture 仅接受 `(title, priority\|severity, assignee)`，**无 `description` 形参**（见 `conftest.py:104-137`）；description 命中用例与转义用例需按具体 `title`/`description` 直建。 | **已就地补注**（§7.1）：这些用例改用 `client.post(json={"title":..,"description":..}, headers=auth("pm"))` 直建；不阻断。 |
| **P2** | P2-2 | 完备性 / UX 降级 | 后端不可用时 `swrFetcher` 抛 `ApiError`，`useSWR` 将其入 `error` 态、`data` 恒 `undefined`，下拉停在「搜索中…」而非错误提示。§7.3-4「无红屏、静默降级」**成立**（不崩溃），但永久 loading 略误导。 | **建议（非阻断）**：§6.4 可读 `useSWR` 的 `error` 渲染「搜索服务暂不可用」行；本轮不强制，交 Subtask #2 酌情。 |
| **P2** | P2-3 | 一致性 | 检索排序键（`updated_at desc`）与既有 list（`position asc`）分叉。 | **保留**：§2.3 已显式论证（预览取「最近在动的单」更贴合相关度），属有意设计、非缺陷。 |

---

## 0. 剩余占位 / 半成品盘点（本轮选题依据）

承接 `account-settings/spec.md §0` 的全仓审计结论——**业务路由中已无任何伪造 / 硬编码的 API 响应**，Agent 执行引擎与设置页两处显式占位已分别在 Iter1/Iter2 真实化。本轮从其 §11 路线图**按价值/风险排序取第 1 项**，对应审计项 B5/B6：

| # | 位置 | 现状（本轮复核确认仍存在） | 类型 | 本轮 |
|---|------|------|------|------|
| B5 | `frontend/components/layout/Header.tsx:48-55` | 全局搜索框 `runSearch()` 恒 `router.push('/requirements?q=')` 并派发 `aragon:search`；占位文案 `placeholder="搜索需求 / BUG…"` 宣称可搜 BUG，但 **BUG 永不可达**——只跳需求列表。 | 前端半成品（承诺 > 实现） | **✅ 纳入** |
| B6 | `frontend/app/(app)/bugs/page.tsx:39-45` | BUG 列表页 mount 时读 `?q=`，但**未监听 `aragon:search` 事件**（需求页 `requirements/page.tsx:46-53` 有监听）；后端 `bugs.py:56-58` 的 `q` ilike 检索能力**闲置**，无任何 UI 入口把关键词送达。 | 缺集成（后端能力无前端） | **✅ 纳入** |
| B7 | 全仓无「跨实体聚合搜索」端点 | 需求 / BUG 各有独立 list `q` 过滤，但无 `GET /api/search`，用户无法一次看到「需求 + BUG」的综合命中，只能逐列表切换。 | 后端缺端点 | **✅ 纳入**（B5 的真实后端支点） |

其余审计项（C7 @提及自动补全、D8–D11 管理台 UI、A4 LLM 运行时配置）继续按 §10 路线图交棒 Iteration 4–5，本轮不贪多。

**选题结论**：本轮把 Header 全局搜索框从「假搜索（只跳需求）」真实化为**端到端可用的统一搜索**：新增后端聚合端点 `GET /api/search`（跨需求 + BUG 命中，反查现成、闲置的 BUG 检索能力），前端把 Header 搜索框升级为**实时下拉预览**（分组展示需求 / BUG 命中、点击直达工单抽屉、「查看全部」跳对应过滤列表），并顺手补齐 BUG 列表页缺失的 `aragon:search` 监听，让"搜索需求 / BUG"的界面承诺**首次真正兑现**。

---

## 1. 概述（Overview）

AragonTeam 是「AI 时代（Agent 可参与协作）的研发协作管理平台」。经前两轮真实化，平台业务主链路（鉴权、需求/BUG 看板、指派、状态机流转、评论/时间线、通知扇出、Agent 自主执行、账号自助中心）均已由真实数据驱动。全仓复核显示，唯一仍**言行不一**的用户界面是 Header 顶部的**全局搜索框**——它的 `placeholder` 白纸黑字写着「搜索需求 / BUG」，但 `runSearch()` 无论输入什么都只 `push('/requirements?q=')`，BUG 永远搜不到；后端虽在 `bugs.py` 早已支持 `q` 关键词 ilike，却因**没有任何前端入口把关键词送达 BUG 侧**而长期闲置。这是继 Agent 引擎、设置页之后，最后一处「界面承诺 > 实际能力」的缺口，直接影响「这平台是否做完」的观感。

本方案把全局搜索真实化为**跨实体的统一搜索**，落地三块高内聚能力：**（1）后端聚合端点** `GET /api/search?q=&limit=`——一次查询同时返回需求命中与 BUG 命中的前若干条（`limit` 可控）及各自总命中数，复用既有 `title/description` ilike 语义，并**转义 LIKE 元字符**（`% _ \`）以规避通配泄漏，比现有裸 ilike 更稳健；**（2）Header 实时下拉预览**——把搜索框从 Header 抽为独立组件 `GlobalSearch`，输入防抖 300ms 后拉取 `/api/search`，下拉框按「需求 / BUG」分组展示编号+标题+状态徽章，支持键盘上下选择、Enter 直达、Esc 关闭；点击某条命中即**复用既有「直达工单」契约**（`router.push('/<seg>/board?ticket=<id>')` + 派发 `aragon:open-ticket`）打开工单抽屉；分组底部「查看全部 N 条需求 / BUG」跳转到对应**过滤列表**；**（3）补齐 BUG 列表联动**——给 `bugs/page.tsx` 加上与需求页对称的 `aragon:search` 监听，让「查看全部 BUG」及 Header 直搜都能即时刷新 BUG 列表。

设计的第一性原则依旧是**稳健与向后兼容**：**零新增数据表、零既有表列变更、零既有接口 shape 变更、零状态机改动**。新端点只读、只挂新蓝图 `/api/search`，检索逻辑收敛进新服务 `services/search.py`；前端复用早在 `NotificationBell` 落地并被其注释显式称作「与全局搜索同策略」的 `aragon:open-ticket` 直达契约与 `aragon:search` 刷新契约——即本特性所需的所有接缝均已存在、经上一阶段验证，本轮只是把它们接线成一条完整链路。因此既有 **150** 个 pytest 用例、前端既有类型与页面均无需改动即可继续通过，新增能力是**纯加性**的。

---

## 2. 技术设计（Technical Design）

### 2.1 架构总览

```
┌──────────────────────────── 前端（Next.js App Router）────────────────────────────┐
│  Header.tsx ──renders──> GlobalSearch.tsx (新)                                      │
│      · query 状态 + 300ms 防抖                                                       │
│      · useSWR(q ? `/search?q=..&limit=5` : null, swrFetcher<SearchResults>)         │
│      · 下拉分组渲染（需求 / BUG）+ 键盘导航 + 点击外部/Esc 关闭                        │
│      · 命中点击 → router.push('/<seg>/board?ticket=<id>') + dispatch aragon:open-ticket│
│      · 「查看全部」→ router.push('/<seg>?q=<q>') + dispatch aragon:search             │
│                                                                                     │
│  requirements/page.tsx（已监听 aragon:search，无改）                                  │
│  bugs/page.tsx（本轮新增 aragon:search 监听 —— B6）                                   │
│  {requirements,bugs}/board/page.tsx（已支持 ?ticket= + aragon:open-ticket，无改）     │
└─────────────────────────────────────────────────────────────────────────────────┘
              │ GET /api/search?q=&limit=（Bearer JWT）
              ▼
┌──────────────────────────── 后端（Flask）────────────────────────────┐
│  routes/search.py (新)  ── bp: /api/search, @jwt_required            │
│      · 解析 q（strip）、limit（clamp [1,20]，缺省 5）                  │
│      · q 空 → 200 空信封（下拉无输入时的稳健降级）                      │
│      · 调 services.search.search_all(q, limit)                        │
│                        │                                             │
│  services/search.py (新)                                             │
│      · _like_clause(model, kw)：转义 % _ \，构造 title/description ilike │
│      · search_entity(model, kw, limit) → (rows[:limit], total)        │
│      · search_all(kw, limit) → {requirements, bugs, counts}          │
│                        │ 只读                                         │
│  models.Requirement / models.Bug（既有 to_dict，无改）                 │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 关键代码路径与时序

**A. 用户在 Header 输入「登录」的实时预览：**

1. `GlobalSearch` 的 `onChange` 更新 `query`；`useEffect` 300ms 后写入 `debounced`。
2. `debounced` 非空 → SWR key 变为 `/search?q=登录&limit=5` → `swrFetcher` → `api.get` 带 JWT 请求后端。
3. 后端 `global_search`：`q="登录"`、`limit=5`；调 `search_all("登录", 5)`。
4. `search_all` 对 `Requirement`、`Bug` 各跑 `search_entity`：先 `count()` 得总数，再 `order_by(updated_at desc, id desc).limit(5).all()` 取前 5，`to_dict()` 序列化。
5. 返回 `{query, requirements:[...], bugs:[...], counts:{requirements:N1, bugs:N2}}`；SWR 缓存并回填组件。
6. 组件渲染下拉：需求组 min(5,N1) 行 + BUG 组 min(5,N2) 行；若 `N1>5` 显示「查看全部 N1 条需求 →」。

**B. 点击某条需求命中「REQ-42」：**

1. `onSelect('requirements', 42)`——`kind` 恒取**复数「路由段」形式**（`'requirements'` / `'bugs'`），无单→复映射。
2. `router.push('/requirements/board?ticket=42')`——若当前不在该看板则导航、mount 读 `?ticket=42` 打开抽屉。
3. 同时 `window.dispatchEvent(new CustomEvent('aragon:open-ticket', {detail:{entity:'requirements', id:42}}))`——若已在该看板（同路由 push 不重挂载），事件即时打开抽屉。二者互补，覆盖「跨页 / 同页」两种落点（与 `NotificationBell.onOpenItem` 逐字同构）。
4. `setDropdownOpen(false)`、`setQuery("")` 收起下拉。

> **【命名不变量 · P1-1】** 命中项的 `kind` 只有一种取值域：**复数路由段** `'requirements'` / `'bugs'`。它必须同时满足四处**逐字相等**——① 路由段 `/${kind}/board`、`/${kind}`（既有路由 `/requirements`、`/bugs`）；② `aragon:open-ticket` 的 `detail.entity`（board 页监听 `d.entity === "requirements"` @ `requirements/board/page.tsx:31`、`=== "bugs"` @ `bugs/board/page.tsx:24`）；③ `aragon:search` 的消费页；④ §4.2 事件契约表的权威定义。**切勿使用单数 `'requirement'`/`'bug'`**——那会让 `push` 落到不存在的 `/requirement/board`（404）、且 `detail.entity` 永不匹配 board 的复数比较值（同页抽屉打不开）。

**C. 点击分组底部「查看全部 12 条需求」：**

1. `router.push('/requirements?q=登录')`——跨页时列表页 mount 读 `?q=` 初始化过滤。
2. `window.dispatchEvent(new CustomEvent('aragon:search', {detail:'登录'}))`——已在列表页时即时刷新过滤条（沿用需求页既有监听；BUG 页本轮新增对称监听）。

**D. 键盘可达（a11y）：**`/` 聚焦搜索（非输入态时，从 Header 迁入 `GlobalSearch`）；`↑/↓` 在扁平化命中列表（需求在前、BUG 在后）间移动高亮；`Enter` 打开高亮项，无高亮项且 `q` 非空则回退到「查看全部需求」；`Esc` 关闭下拉（再按清空并失焦）。

### 2.3 检索语义与排序

- **匹配字段**：`title` OR `description`，大小写不敏感（`ilike`），与既有 list `q` 一致。
- **LIKE 转义**（稳健性增强）：对用户输入先转义 `\`→`\\`、`%`→`\%`、`_`→`\_`，再包 `%kw%`，并显式 `escape="\\"`。避免用户输入 `100%` 被当成「匹配任意」的通配泄漏——这是对既有裸 ilike 的**严格增强**，只在含元字符的边缘输入上产生更正确的结果。
- **排序**：`updated_at DESC, id DESC`（最近活跃者优先，作为相关度近似；预览场景比 `position` 更贴合"我最近在动的单"）。
- **可见性**：与既有 list 读接口一致——**任何已登录用户可读全部命中**（读放开、写才 RBAC）；搜索不做行级读过滤，保持与 `list_requirements/list_bugs` 同一读模型。

---

## 3. 文件 / 模块变更计划（File / Module Change Plan）

### 后端（backend/）

| 文件 | 动作 | 一句话意图 |
|------|------|-----------|
| `backend/services/search.py` | **新增** | 跨需求+BUG 聚合检索服务：`_like_clause`（转义元字符）/`search_entity`（rows+total）/`search_all`（信封），`DEFAULT_LIMIT=5`、`MAX_LIMIT=20`。 |
| `backend/routes/search.py` | **新增** | `/api/search` 蓝图 + `@jwt_required` 的 `global_search`：解析 q/limit、空 q 降级、调 `search_all`。 |
| `backend/routes/__init__.py` | 修改 | `register_blueprints` 追加导入并注册 `search_bp`。 |
| `backend/tests/test_global_search.py` | **新增** | 端点行为回归：双实体命中、描述命中、空 q 降级、limit 上/下限、鉴权 401、**LIKE 元字符转义**、无命中空组。 |

### 前端（frontend/）

| 文件 | 动作 | 一句话意图 |
|------|------|-----------|
| `frontend/components/layout/GlobalSearch.tsx` | **新增** | 独立搜索组件：防抖查询、SWR 拉 `/search`、分组下拉预览、键盘导航、命中直达/查看全部、点击外部/Esc 关闭。 |
| `frontend/components/layout/Header.tsx` | 修改 | 移除内联搜索 state/effect/`runSearch`/input，替换为 `<GlobalSearch />`；保留用户菜单与铃铛。 |
| `frontend/app/(app)/bugs/page.tsx` | 修改 | **B6 修复**：mount effect 内新增 `aragon:search` 监听（与 `requirements/page.tsx:46-53` 对称），使「查看全部 BUG」与 Header 直搜即时刷新本页。 |
| `frontend/lib/types.ts` | 修改 | 新增 `SearchResults` interface（`/api/search` 响应形状）。 |

> **不新增数据库表、不改任何既有表列、不改既有接口 shape、不动 `workflow.py`。** 前端 `api.ts`/`constants.ts`/看板页/需求列表页均无需改动（复用既有 `swrFetcher`、`statusStyle`、`aragon:open-ticket`、`aragon:search`、`?ticket=`/`?q=` 契约）。

---

## 4. 接口设计（Interface Design）

### 4.1 REST：`GET /api/search`

- **鉴权**：`@jwt_required()`（无 token → 401，走全局错误信封）。
- **查询参数**：
  - `q`（string，必填但空/空白宽容）：关键词；服务端 `strip()`。空或纯空白 → 返回空信封（200），不 400（下拉每键触发时更稳健）。
  - `limit`（int，可选，缺省 `5`）：**每类**预览条数；`clamp` 到 `[1, 20]`（`<1`→1，`>20`→20，非法/缺省→5）。
- **成功响应 `200`**（对象信封，非裸数组，故不设 `X-Total-Count`）：

```json
{
  "query": "登录",
  "requirements": [ { /* Requirement.to_dict()，最多 limit 条 */ } ],
  "bugs": [ { /* Bug.to_dict()，最多 limit 条 */ } ],
  "counts": { "requirements": 12, "bugs": 3 }
}
```

- `requirements`/`bugs`：命中前 `limit` 条（`updated_at` 倒序）。
- `counts.*`：**总**命中数（供「查看全部 N 条」文案与 `N>limit` 判定）。
- **空 q 响应 `200`**：`{"query":"","requirements":[],"bugs":[],"counts":{"requirements":0,"bugs":0}}`。
- **错误**：仅 `401`（未授权）。参数不触发 400（宽容降级）。

### 4.2 前端事件契约（复用既有，无新增自定义事件）

| 事件 | detail 形状 | 触发方 | 消费方 |
|------|------------|--------|--------|
| `aragon:open-ticket` | `{ entity: "requirements"\|"bugs"; id: number }` | `GlobalSearch`（命中点击） | `{requirements,bugs}/board/page.tsx`（既有监听） |
| `aragon:search` | `string`（关键词） | `GlobalSearch`（查看全部） | `requirements/page.tsx`（既有）、`bugs/page.tsx`（**本轮新增**） |

### 4.3 前端 TS 类型（`lib/types.ts` 新增）

```ts
// —— global-search：统一搜索（GET /api/search 响应）——
export interface SearchResults {
  query: string;
  requirements: Requirement[];
  bugs: Bug[];
  counts: { requirements: number; bugs: number };
}
```

---

## 5. 数据模型（Data Model）

**本特性零数据库变更。** 纯只读复用既有 `requirements` / `bugs` 两表与既有 `Requirement.to_dict()` / `Bug.to_dict()` 序列化，无新表、无新列、无索引变更、无迁移。检索字段 `title`（`String(255)`）、`description`（`Text`）均为现有列；`status` 已有索引，排序键 `updated_at` 为普通列（MVP 单机量级无需额外索引）。

内存态新增的仅是一个响应信封（§4.1）与其 TS 镜像 `SearchResults`（§4.3）。

---

## 6. 落地细节（逐文件实现指引）

> 目标：下游 Subtask #2 可据此逐行落地，无需再决策。

### 6.1 `backend/services/search.py`（新增）

```python
"""全局统一搜索（跨需求 + BUG 的关键词命中聚合）。

只读服务：复用 Requirement / Bug 既有 to_dict；对用户关键词转义 LIKE 元字符
（% _ \），避免通配泄漏（比 routes 内既有裸 ilike 更稳健）。排序按 updated_at
倒序（最近活跃优先，作为预览相关度近似）。空关键词由调用方处理，此处假定已 strip 非空。
"""
from sqlalchemy import or_

from models.requirement import Requirement
from models.bug import Bug

DEFAULT_LIMIT = 5
MAX_LIMIT = 20


def _like_clause(model, keyword: str):
    """构造 title/description 的大小写不敏感 LIKE 子句，转义 LIKE 元字符。"""
    escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like = f"%{escaped}%"
    return or_(model.title.ilike(like, escape="\\"),
               model.description.ilike(like, escape="\\"))


def search_entity(model, keyword: str, limit: int):
    """单实体检索：返回 (前 limit 条命中, 总命中数)，按 updated_at 倒序。"""
    q = model.query.filter(_like_clause(model, keyword))
    total = q.count()
    rows = q.order_by(model.updated_at.desc(), model.id.desc()).limit(limit).all()
    return rows, total


def search_all(keyword: str, limit: int = DEFAULT_LIMIT) -> dict:
    """跨需求 + BUG 聚合。keyword 须为已 strip 的非空串；limit 须已 clamp。"""
    reqs, req_total = search_entity(Requirement, keyword, limit)
    bugs, bug_total = search_entity(Bug, keyword, limit)
    return {
        "requirements": [r.to_dict() for r in reqs],
        "bugs": [b.to_dict() for b in bugs],
        "counts": {"requirements": req_total, "bugs": bug_total},
    }
```

要点：`ilike(..., escape="\\")` 让 `\%`/`\_` 被当字面量；`or_` 覆盖标题或描述任一命中；两次 `count()`+`limit()` 对 SQLite MVP 量级足够，无 N+1（`to_dict` 内的 assignee 解析为逐条 `session.get`，与既有 list 行为一致、量级受 `limit` 上限 20 约束）。

### 6.2 `backend/routes/search.py`（新增）

```python
"""全局搜索路由（global-search §4.1）。GET /api/search —— 跨需求+BUG 聚合命中。

只读、jwt_required；q 空/空白宽容降级为空信封（下拉每键触发场景更稳健），
limit 缺省 5、clamp 到 [1, 20]。
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from services import search

bp = Blueprint("search", __name__, url_prefix="/api/search")


def _coerce_limit(value):
    """把 limit 参数安全 clamp 到 [1, MAX_LIMIT]；缺省/非法 → DEFAULT_LIMIT。"""
    if value is None:
        return search.DEFAULT_LIMIT
    return max(1, min(value, search.MAX_LIMIT))


@bp.get("")
@jwt_required()
def global_search():
    keyword = (request.args.get("q") or "").strip()
    limit = _coerce_limit(request.args.get("limit", type=int))
    if not keyword:
        return jsonify({
            "query": "", "requirements": [], "bugs": [],
            "counts": {"requirements": 0, "bugs": 0},
        }), 200
    result = search.search_all(keyword, limit)
    result["query"] = keyword
    return jsonify(result), 200
```

### 6.3 `backend/routes/__init__.py`（修改）

在导入区加 `from routes.search import bp as search_bp`；在 `register_blueprints` 内（`bugs_bp` 之后、`board_bp` 附近或末尾）加 `app.register_blueprint(search_bp)`。

### 6.4 `frontend/components/layout/GlobalSearch.tsx`（新增）

职责：独立搜索框 + 下拉预览。结构（伪码，实现须 <200 行、方法 <50 行、嵌套 ≤4）：

- **state**：`query`、`debounced`、`open`（下拉）、`active`（高亮索引，-1 表示无）。`wrapRef`、`inputRef`。
- **防抖**：`useEffect([query])` 300ms 写 `debounced`；`query` 变则 `setActive(-1)`、`setOpen(true)`。
- **SWR**：`const key = debounced ? \`/search?q=${encodeURIComponent(debounced)}&limit=5\` : null; const { data } = useSWR<SearchResults>(key, swrFetcher);`
- **扁平命中列表**：`const flat = [...(data?.requirements||[]).map(r=>({kind:'requirements',...})), ...(data?.bugs||[]).map(b=>({kind:'bugs',...}))]`（用于 ↑/↓ 与 Enter）。`kind` 恒为**复数路由段**，遵守 §2.2【命名不变量 · P1-1】。
- **`/` 全局聚焦**：`useEffect` 监听 `keydown`，非输入态按 `/` → `preventDefault` + `inputRef.focus()`（从 Header 迁入）。
- **点击外部 / Esc**：`useEffect([open])` 监听 `mousedown`/`keydown`，落外或 Esc → `setOpen(false)`。
- **选择命中** `onSelect(kind, id)`：`router.push(\`/${kind}/board?ticket=${id}\`)` + `dispatch aragon:open-ticket {entity:kind,id}` + `setOpen(false)` + `setQuery("")`。（`kind` 直接作路由段与 `detail.entity`，见【命名不变量 · P1-1】；**不得**在此做单/复数转换。）
- **查看全部** `onSeeAll(kind)`：`router.push(\`/${kind}?q=${encodeURIComponent(debounced)}\`)` + `dispatch aragon:search debounced` + `setOpen(false)`。（`kind` 已是路由段 `'requirements'`/`'bugs'`，直接拼列表路由，无需三元判定。）
- **输入框 `onKeyDown`**：`ArrowDown`/`ArrowUp` 移 `active`（clamp 到 `flat` 边界）；`Enter` → 有 `active` 则 `onSelect(flat[active])`，否则 `debounced` 非空 → `onSeeAll('requirements')`；`Escape` → 若 `open` 关闭，否则清空并 `blur`。
- **渲染**：input（沿用 Header 现有放大镜 svg + 配色类名，`placeholder="搜索需求 / BUG…（/）"`）；`open && debounced` 时下拉面板（`absolute right-0 mt-2 w-96 …`，复用 `NotificationBell` 面板类名风格）：
  - 加载中（`!data`）：「搜索中…」。
  - 无命中（`counts.requirements===0 && counts.bugs===0`）：「未找到匹配的需求或 BUG」。
  - 需求组：标题「需求」+ 行 `REQ-{id} · {title}` + `<Badge style={statusStyle(r.status)} />`；`counts.requirements > items.length` 时底部「查看全部 {counts.requirements} 条需求 →」。
  - BUG 组：同构，`BUG-{id}` + `statusStyle(b.status)`。
  - 行高亮：`idx === active` 加底色类。

### 6.5 `frontend/components/layout/Header.tsx`（修改）

- 删除 `query` state、两个搜索相关 `useEffect`（`/` 聚焦、`runSearch`）、`searchRef`、以及 `{/* 全局搜索框 */}` 整块 input JSX。
- 顶部 `import GlobalSearch from "@/components/layout/GlobalSearch";`。
- 在原搜索框位置渲染 `<GlobalSearch />`（保持 `hidden md:block` 由组件内自持或包一层 wrapper——建议组件内根节点带 `hidden md:block`，Header 只 `<GlobalSearch />`）。
- `useRouter` 若仅剩登出使用则保留；`useState/useRef/useEffect` 若用户菜单仍用则保留（用户菜单逻辑不动）。

### 6.6 `frontend/app/(app)/bugs/page.tsx`（修改，B6）

把现有 mount effect（lines 39-45）扩成与需求页对称：

```ts
useEffect(() => {
  const q = new URLSearchParams(window.location.search).get("q") || "";
  if (q) { setKeyword(q); setDebounced(q); }
  function onSearch(e: Event) {
    const term = (e as CustomEvent<string>).detail?.trim();
    if (!term) return;
    setKeyword(term); setDebounced(term);
  }
  window.addEventListener("aragon:search", onSearch);
  return () => window.removeEventListener("aragon:search", onSearch);
}, []);
```

### 6.7 `frontend/lib/types.ts`（修改）

在文件末尾（`ProfileUpdate` 之后）追加 §4.3 的 `SearchResults` interface。

---

## 7. 测试与验收标准（Testing & Acceptance）

### 7.1 后端 pytest（新增 `tests/test_global_search.py`，约 8 例）

| 用例 | 断言 |
|------|------|
| `test_search_returns_both_entities` | 建需求「登录页面」+ BUG「登录失败」，`GET /api/search?q=登录` → 200；`requirements`、`bugs` 各含对应单；`counts` 正确。 |
| `test_search_matches_description` | 关键词只在 description 命中也返回（该单须**直建**带 `description`，见下方 fixture 注）。 |
| `test_search_blank_query_returns_empty` | `GET /api/search`（无 q）→ 200，两组空、counts 全 0。 |
| `test_search_limit_caps_preview_but_counts_total` | 建 7 条命中需求，`limit=3` → `requirements` 长度 3，`counts.requirements == 7`。 |
| `test_search_limit_clamped_to_min` | `limit=0` → 至少返回 1 条（clamp 下限）。 |
| `test_search_limit_clamped_to_max` | `limit=999` 不报错、行为等价上限 20（可用少量数据 + 断言 200 + 结构完整）。 |
| `test_search_escapes_like_wildcards` | **须真正区分「有无转义」**（原「100% vs abcdef / q=100%」设计无效——诱饵不含 `100`，转义与否都只命中前者，见 P1-2）。改为：直建两需求「80% 覆盖率」与「进度良好」（诱饵**不含字面 `%`**），`q=%` → **仅**命中「80% 覆盖率」、`counts.requirements==1`。判据：未转义时模式退化为 `%%%` 命中全部（诱饵也中）→ 断言 `==1` 会失败；转义后 `%\%%` 仅命中含字面 `%` 者 → 通过。这样测试对「漏写 `escape="\\"` / 漏转义」敏感，成为 R2 的真回归护栏。 |
| `test_search_requires_auth` | 无 Authorization 头 → 401。 |

复用 `conftest.py` 既有 fixture（`client`/`auth`/`make_requirement`/`make_bug`/`data`）；账号映射沿用 `admin/pm/member/member2`。**注（P2-1）**：`make_requirement`/`make_bug` 仅接受 `(title, priority|severity, assignee)`，**无 `description` 形参**（`conftest.py:104-137`）。凡需指定 `description` 或用作转义诱饵的用例（`test_search_matches_description`、`test_search_escapes_like_wildcards`），须以 `client.post("/api/requirements"|"/api/bugs", json={"title":.., "description":..}, headers=auth("pm"))` 直建，而非依赖便捷 fixture。

### 7.2 前端

- `npm run typecheck`（`tsc --noEmit`）零错误（`SearchResults` 类型闭合、`GlobalSearch` 泛型正确）。
- `npm run build` 成功（`GlobalSearch` 为 `"use client"`，无 SSR/Suspense 违规）。

### 7.3 手动冒烟（主流程无大报错）

1. 登录 → Header 输入「登录」→ 下拉出现需求 + BUG 两组命中，状态徽章正确。
2. 点击某需求命中 → 跳需求看板并打开该单抽屉；点击某 BUG 命中 → 跳 BUG 看板并打开。
3. 「查看全部 N 条 BUG」→ 跳 `/bugs?q=登录`，BUG 列表按关键词过滤；此时再从 Header 直搜别的词，BUG 列表**即时刷新**（验证 B6 监听）。
4. 空输入 / 无命中 / 后端未启动（`ApiError`）均无红屏，SWR 静默降级。
5. 键盘：`/` 聚焦、`↑/↓` 选择、`Enter` 直达、`Esc` 关闭。

### 7.4 质量门（Definition of Done）

- `pytest -q` 全绿（既有 **150** + 新增 ≈8）。
- 前端 `npm run typecheck` + `npm run build` 零错误。
- 既有 150 例、既有前端类型/页面**零改动即通过**（纯加性验证）。

---

## 8. 风险与缓解（Risks & Mitigations）

| # | 风险 | 影响 | 缓解 |
|---|------|------|------|
| R1 | 下拉每键触发请求，高频输入压后端 | 性能/抖动 | 300ms 防抖 + SWR 去重缓存 + `limit` 上限 20；空 q 不发请求（SWR key=null）。 |
| R2 | LIKE 元字符（`% _`）通配泄漏，`100%` 匹配全部 | 结果错误 | `services/search.py` 显式转义 + `escape="\\"`；`test_search_escapes_like_wildcards` 回归。 |
| R3 | 新端点与既有 list `q` 检索语义分叉（后者未转义） | 一致性存疑 | **有意保留**：list 端点维持既有裸 ilike（严格向后兼容既有 125+ 用例的通配行为），新端点更严格；差异记入本表与 §10（list 采用共享 helper 为**可选**后续清理，不在本轮）。 |
| R4 | Header 抽出组件后 `/` 快捷键 / 布局回归 | 交互回归 | `/` 聚焦逻辑随组件迁移并保留；`hidden md:block` 响应式类名保持；手动冒烟 §7.3-5 覆盖。 |
| R5 | 同路由 `router.push` 不重挂载，直达/查看全部失效 | 功能失效 | 与 `NotificationBell` 同策略：`push` + 派发事件双管，覆盖跨页/同页；board 页 `?ticket=` 与 `aragon:open-ticket` 均已就绪。 |
| R6 | `to_dict` 内 assignee 逐条 `session.get` 造成额外查询 | 轻微性能 | 受 `limit≤20` 约束、与既有 list 同行为，MVP 量级可忽略；如需再优化留待后续。 |
| R7 | BUG 页新增监听与既有 mount 读 `?q=` 冲突/重复刷新 | 轻微重渲染 | 与需求页对称实现（已生产验证）；`onSearch` 内 `trim` 空值早退，幂等安全。 |
| R8 | 新蓝图前缀 `/api/search` 与既有路由冲突 | 路由错误 | 全仓 grep 确认无 `/api/search`；蓝图独立 `url_prefix`，注册顺序无副作用。 |

---

## 9. 与既有架构约定的一致性核对

- **状态机神圣**：本特性**纯只读**，零触碰任何工单状态迁移，`workflow.can_transition` 零改动。
- **通知收口唯一**：不涉及 `notify()`，不新增通知类型。
- **向后兼容**：零新表、零既有列/接口 shape 变更、零 seed 依赖；既有 150 例零改动即绿。
- **RBAC 一致**：读放开（任何已登录用户可搜全部命中，与既有 list 读同模型），写才 RBAC——本特性无写路径。
- **风格一致**：Python PEP8 + Google docstring；TS 公共类型用 `interface`；文件 <800 行、方法 <50 行、参数 ≤5、嵌套 ≤4（服务/路由/组件三处拆分即满足）。
- **平台约定**：Windows / PowerShell 5.1 命令分开执行、勿用 `&&`；后端测试禁 mock 鉴权（用例走真实 `auth` fixture 取 JWT）。
- **接缝复用**：`aragon:open-ticket` / `aragon:search` / `?ticket=` / `?q=` / `swrFetcher` / `statusStyle` 均为既有、经上一阶段验证的接缝，本轮零新增自定义事件。

---

## 10. 后续迭代路线（本轮 Out of Scope，交棒 Iteration 4–5）

承接 `account-settings/spec.md §11` 未尽项，按价值/风险续排：

1. **@提及自动补全**（C7）：`CommentComposer` 加 `@` 触发的用户下拉（拉 `GET /api/users`），补全后端已支持的 `notify_mentions` 链路。
2. **管理台 UI**（D8–D11）：Team 页「新增成员 / 改姓名邮箱 / 重置密码」（接 `POST /api/users`、全量 `PATCH /api/users/<id>`）、Agents 页「建/改 Agent」（接 `POST/PATCH /api/agents`）、项目管理页（接 `projects.py`）。
3. **LLM 运行时配置**（A4，谨慎）：坚持「仅存 provider/model/base_url + 密钥走 env/密钥库引用」，admin-only，明文密钥不落库。
4. **搜索增强（可选）**：list 端点采用 `services/search._like_clause` 统一转义（消除 R3 分叉）；`GET /api/search` 增分页 / 高亮片段 / 全文索引；`Header` 搜索纳入 Agent 命中（当前只搜工单）。

---

## 评审结论（Review Verdict）

**结论：✅ 通过（P0=0；P1 全部就地修复，升 v2）。**

方案在**可行性、一致性、合理规模**三维上表现扎实：所有依赖接缝（`updated_at` 列、`to_dict`、`swrFetcher`+`API_BASE`、`statusStyle`、`aragon:open-ticket`/`aragon:search`/`?ticket=`/`?q=` 四契约、`conftest` fixture、后端 `or_`/`ilike`）均经**代码逐一取证**存在且形状匹配；零新表 / 零既有 shape 变更 / 零状态机改动，与 CLAUDE.md「状态机神圣、向后兼容、通知收口唯一」诸约定一致；规模贴合本轮「把最后一处言行不一的 UI 真实化」的目标，不过度设计。

本轮修复的两个 P1 均属**会真实致故障 / 假绿**的隐患，已就地闭合：

1. **P1-1 命名不变量**——消除单/复数分叉，避免直达功能整体失效（`/requirement/board` 404、同页抽屉打不开）。已统一为复数路由段并加不变量注。
2. **P1-2 转义回归护栏**——重设计 `test_search_escapes_like_wildcards`，令其真正对「漏转义」敏感，守住新服务相对裸 list 的**唯一技术卖点**（R2）。

**放行附带的非阻断优化建议（P2，交 Subtask #2 酌情，或延后 Iter4-5）：**

- **P2-1**（已就地补注）：description / 转义诱饵用例改用 `client.post(json={...,"description":..})` 直建，勿依赖无 `description` 形参的便捷 fixture。
- **P2-2**（建议）：`GlobalSearch` 读 `useSWR` 的 `error` 渲染「搜索服务暂不可用」行，替代后端不可用时的永久「搜索中…」——纯 UX 细化，不影响主流程。
- **P2-3**（保留）：搜索排序键与 list 分叉系 §2.3 有意设计，无需改动。

**Definition of Done 核对**：`spec.md` 已含「评审记录」（顶部）与「评审结论」（本节）；版本已标 **v2**；**无 P0 / P1 遗留**。准予进入 Subtask #2 代码开发。

---

*—— 方案设计：资深工程师（Anthropic Eng）· Subtask #0 · Loop Iteration 3/5 · 特性 `global-search`*
*—— 方案评审：资深评审（Anthropic Eng）· Subtask #1 · 升 v2 · 通过（P0=0 / P1 已闭合）*
