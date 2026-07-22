# 版本 / 计划：把工单层级补完为「版本 → 计划 → 需求/BUG」（version-plan-hierarchy）

> **文档版本：v2**（2026-07-21 设计评审升版；下述 P1 问题已在正文逐条修复，见「评审记录」，评审结论见文末）。
>
> 角色：本文件为**设计节点**产物（Anthropic 工程团队解决方案架构师），只产出设计文档，
> **不写实现代码**、不改 `docs/plans/version-plan-hierarchy/` 之外的任何源文件、不 `git commit`。
> 下游工程师应能据本文档逐行实现，无需再做设计决策。
>
> 采集基线（**实测**，`cd backend && ./.venv/Scripts/python.exe -m pytest -q --collect-only`）：
> **808 用例 / 46 文件**，收集零错误。验收判据以**开工当日**重跑的 `--collect-only` 为准
> （CLAUDE.md「质量门禁」：零失败 + 用例总数不低于基线），不采信任何写死的数字。
>
> 本文档中所有涉及既有代码的断言均带 `文件:行号`，写作时逐条对照过真实源码
> （backend：`models/{requirement,bug,project,activity,__init__}.py`、
> `services/{scope,validation,schema_sync,lifecycle,workflow,positions}.py`、
> `routes/{requirements,bugs,projects}.py`、`seed.py`、`errors.py`；
> frontend：`components/layout/Sidebar.tsx`、`app/(app)/{requirements,projects}/page.tsx`、
> `components/FilterBar.tsx`、`lib/{project-scope.tsx,api.ts,swr-keys.ts,types.ts,constants.ts}`、
> `components/admin/ProjectFormModal.tsx`、`components/ui/*`、`hooks/useBoard.ts`）。

---

## 评审记录（Review Notes · v2）

> 评审人：Anthropic 工程团队资深评审。评审维度：**可行性 / 完整性 / 一致性 / 规模适配**。
> 方法：逐节对照真实源码复核了 v1 的每一条 `文件:行号` 断言——**绝大多数精确命中**
> （`schema_sync.ADDITIVE_COLUMNS` 10 条、`workflow._TERMINAL:51`、`activity.TICKET_ENTITY_TYPES:11`、
> `requirements.py` 的 `:123/:152/:189/:205/:246/:249/:410/:439`、`swr-keys` 的 `:13/:27`、
> `ProjectFormModal:17`、`constants.BadgeStyle:18/PRIORITY_STYLES:62`、`ui/ProgressBar` 存在等均属实），
> 整体架构（四层树、全程 additive、真 FK 仅在新表、`plan_id` 无 FK、不接状态机、不写 activities）
> **可行且正确**。下表列出复核中发现的每一条问题；**所有 P1 已在 v2 正文修复**。
>
> **无 P0**——设计不含破坏既有契约或无法在当前栈实现的项。

| # | 严重度 | 维度 | 问题 | 处置（v2） |
|---|---|---|---|---|
| **P1-A** | P1 | 可行性/完整性 | §4.7 把 `purge_demo_data.py` 描述为「依 `seed_records` 的**删除顺序**插入 plan/version」。**实测该工具不是线性删除序列，而是按类别硬编码的管线**（`PROVENANCE_CATEGORIES:45`、`_candidates:172`、`_entity_models:154`、`_summarise_principals:496`）。更危险的是：`_prune_orphan_seed_records:135` 对每条登记用 `_entity_models().get(type)` 找模型，**找不到即当孤儿删掉该登记**——若不同步 `_entity_models`，版本/计划的 `SeedRecord` 会在首次 purge（含 dry-run 计算阶段）被误删，自毁出身证明，且工单表行永远清不掉。 | **已修**：§4.7 重写为**四处**具体改动（`_entity_models` 登记＝最低必须项、`PROVENANCE_CATEGORIES`+`_candidates` 加两类且 legacy 指纹为空、新增 `_purge_versions`/`_purge_plans` 守卫、`_summarise_principals` 按 FK 顺序接线）；§5.1 与 §8.1 同步。 |
| **P1-B** | P1 | 完整性 | §7.1 与 §8.3#3 要求「版本卡聚合进度条」（该版本所有工单 done/total），但 §6.1 只富化 `plan_count`——**没有任何数据路径产出版本级 done/total**。靠前端把整张 plans 表拉下来客户端求和，在 plans 分页（`limit=200`）时会漏算。 | **已修**：§3.4/§3.6 新增 `hierarchy.version_ticket_counts(ids)->{vid:{total,done}}`（工单→计划→版本两跳、一次 GROUP BY、零 N+1）；§6.1 `/api/versions` 每项富化 `total_count`/`done_count`；§7.1 明确进度由服务端聚合而非客户端求和。 |
| **P1-C** | P1 | 完整性/一致性 | §4.1/§6.1 声明 `released_at`（DATETIME）**由前端写值**且列入 PATCH 可改字段，但 §6.4 只新增 `want_date`（DATE，非 datetime）——**没有任何请求体原语能解析 `released_at`**；且「让客户端写时间戳」与既有 `projects.py:89`「`archived` 只暴露 bool、不让客户端写时间戳」的约定相悖。 | **已修**：`released_at` 改为**服务端托管**——`status` 转入 `released` 时后端 stamp `utcnow()`、转出时清空，客户端不可写。§4.1/§6.1/§6.4 同步；无需新增 datetime 请求体原语。 |
| **P2-A** | P2 | 一致性（论据错误） | §4.6 称必须扩 `SEED_ENTITY_TYPES`「否则 `SeedRecord.mark` 会因不在白名单而拒绝」。**实测 `mark` 不做任何白名单校验**（`seed_record.py:43`），该论据是假的。 | **已修论据**：§4.6 改为真实理由（白名单是「可登记类别」的单一真相，且须与 §4.7 purge 的 `_entity_models` 一一对应）；追加动作仍保留（正确）。 |
| **P2-B** | P2 | 一致性 | 新增版本/计划改变了 seed 写入内容，但 v1 未提递增 `SEED_VERSION`（现 `"2"`，其 docstring 要求「每次改写入内容都应递增」），且 `seed.py` docstring「每类 1 条，共 8 行」将过时。 | **已修**：并入 §4.6——`SEED_VERSION`→`"3"`，`seed.py` docstring 同步为 10 行。 |
| **P2-E** | P2 | 可行性 | §3.6 `next_sort_position` 用 `func.max(position)+1`，**空父（首个子）时 `func.max` 返 NULL**，未 COALESCE 会把首行 `position` 置 `None`，违反 `NOT NULL`。 | **已修**：§3.6 注明须 `COALESCE`/`(m or -1)+1` 归 0。 |
| **P2-F** | P2 | 一致性（有意分歧） | `DELETE /api/versions`、`DELETE /api/plans` 用 `admin\|pm`，而既有 `DELETE /api/projects` 是 `admin` 独占（`projects.py:133`，「删项目远比建项目危险」）。 | **保留设计**：版本/计划是更轻的规划物、且删除前有 409 空引用守卫，`pm` 作为规划负责人可删空版本/计划属合理右尺寸；此分歧为**有意**，在此登记，不改。 |
| **P2-G** | P2 | 一致性（论据） | §5.1 列 `services/__init__.py` 为 ✏️「若聚合导出则登记」。**实测它是纯包标记、不聚合导出**（各 service 直接 `from services import x`）。 | **已修**：§5.1 该行改为「无需改动」，`hierarchy` 同样直接 import。 |
| **P2-H** | P2 | 完整性 | §8.2 要 `Record<...Status,BadgeStyle>` 的编译期穷尽，但既有 `STATUS_STYLES` 是 `Record<string,BadgeStyle>`（**不**穷尽）。若 version/plan 样式照抄 `STATUS_STYLES` 形状则丢失该保障。 | **已修**：§5.2 明确 `VERSION_STATUS_STYLES`/`PLAN_STATUS_STYLES` 用 `Record<VersionStatus,BadgeStyle>`（漏键即编译错）。 |

> 另注（非缺陷）：§3.4 的 `?version_id=` 子查询用 `select(Plan.id)`，与仓库现有 `db.session.get`（SQLAlchemy ≥1.4 API）兼容，`col.in_(select(...))` 合法，无需改写；`ui/ProgressBar` 默认 `aria-label` 为「上传进度」，规划场景**必须显式传 `label`**，已在 §7.1 提示。

---

## 1. 概述（Overview）

本平台今天的工单只有**两层结构**：`Project`（项目，全局作用域）直接挂 `Requirement` /
`Bug`（需求 / BUG）。项目是唯一的组织维度，靠 `project_id` 列 + 全局项目切换器
（`frontend/lib/project-scope.tsx`）把工单分组。这在「一个项目一直往前推」的场景够用，
但一旦项目进入**多版本、多轮迭代**的真实研发节奏，就缺了两个中间层：没有「这批需求属于
哪个发布版本」，也没有「这个版本下这一轮迭代计划要做哪些单」。用户只能把版本号写进标题、
或另开一个项目来假装版本——前者不可筛选，后者污染了「项目」这个维度的语义。

本轮补上这两层，把工单层级补完为 **版本（Version）→ 计划（Plan）→ 需求 / BUG**，并让
它们坐落在既有的 `Project` 之下，形成完整的 **项目 → 版本 → 计划 → 需求/BUG** 四层树：
一个项目下有多个**版本**（如 `v2.0`、`2026 Q3 发布`），一个版本下有多轮**计划**（迭代 /
Sprint），每个计划下挂多个需求与 BUG 的具体实例。版本与计划都是**人工管理**的一等资源
（CRUD + 生命周期状态），需求 / BUG 通过一个可空的 `plan_id` 归属到某个计划；列表、看板、
抽屉三处都能按**版本**或**计划**正确分类与筛选，计划卡与版本卡以进度条呈现「这一批做完了
多少」。

设计上刻意**全程 additive、严格向后兼容**：不新建会破坏既有契约的东西，只加两张新表
（`versions` / `plans`）、给 `requirements` / `bugs` 各加一个可空列 `plan_id`、在工单序列化
站点富化一个只读的 `plan` 概要对象。既有工单 `plan_id` 恒为 `NULL`（= 未归属计划），照常
显示与流转，零回填、零行为漂移。版本 / 计划**不接入工单状态机**（`services/workflow.py`）——
它们是被管理的规划物，其 `status` 是自由枚举、可任意人工切换，与需求 / BUG 的邻接表状态机
是两套互不干涉的机制，本文档 §3.4 明确划清这条边界。

---

## 2. 目标与非目标

### 2.1 目标（本轮交付）

- **G1｜版本 CRUD + 生命周期**：`versions` 表 + `/api/versions` 路由；版本挂在项目下，
  支持新建 / 改名改描述 / 改状态（`planning|active|released|archived`）/ 归档 / 删除
  （删除前置引用检查，非空 → 409）。
- **G2｜计划 CRUD + 生命周期**：`plans` 表 + `/api/plans` 路由；计划挂在版本下，状态
  `planning|active|completed|archived`；同款前置引用检查。
- **G3｜工单归属计划**：`requirements.plan_id` / `bugs.plan_id`（可空、无 DB 外键、应用层校验）；
  建单 / 编辑 / 转 BUG 三条写路径可设置 / 变更 / 继承 `plan_id`，并强制「计划与工单同项目」不变量。
- **G4｜分类与筛选**：需求 / BUG 列表与看板新增 `?version_id=` / `?plan_id=` 过滤
  （含 `none` 哨兵 = 未归属）；工单序列化站点富化只读 `plan` 概要（含所属版本名），供前端展示徽章。
- **G5｜前端「版本 / 计划」管理界面**：新增侧栏「版本」入口 + `/versions` 页——版本卡可展开
  内联其计划列表，计划卡带**进度条**（已完成 / 总数）与需求 / BUG 计数；版本 / 计划表单弹窗
  复用 `ProjectFormModal` 的 `state|null` + `onSaved` 模式；需求 / BUG 页新增版本 / 计划级联
  筛选与行内徽章；工单抽屉新增计划选择器。界面「美观优雅、符合人机交互最佳实践」（§7）。
- **G6｜示例种子**：seed 追加**恰好一个版本 + 一个计划**（守住「每类一条」），把既有示例
  需求 / BUG 归属到该计划，全部登记 `SeedRecord`，并让 `purge_demo_data` 能正确清理。

### 2.2 非目标（本轮明确不做，避免范围蔓延）

- **版本 / 计划不写 `activities` 审计表**。`activities.ENTITY_TYPES`（`models/activity.py:12`）
  是受控集合，其中 `TICKET_ENTITY_TYPES`（`:11`）被 `GET /api/stats` 与全员时间线专门隔离，
  以防治理事件泄漏进仪表盘。给它加 `version`/`plan` 维度会撕开这条隔离。版本 / 计划的变更
  改走**结构化日志**（`log.info(...)`），与 `routes/projects.py:152`（删项目）、Agent 删除
  的既有先例一致。若日后确需版本 / 计划时间线，另起一轮并配套评估 `stats` 泄漏面。
- **不新增通知类型**。`NOTIFICATION_TYPES`（`models/notification.py`）保持 9 种不变。
- **不接入工单状态机**。版本 / 计划的 `status` 是自由枚举，无 `can_transition` 裁决。
- **`me/work` 聚合、全局搜索、仪表盘 stats 暂不按版本 / 计划分组**。列出为 §9 的后续项。
- **不引入 Alembic**。新列继续走 `schema_sync.ADDITIVE_COLUMNS`（本轮只加两列，见 §4.4）。
- **版本 / 计划不做拖拽排序的跨列迁移**；`position` 仅用于同层手动排序（append 落尾），
  不复用工单看板的 `_reindex_column` 复杂度。

---

## 3. 技术设计（Technical design）

### 3.1 层级与归属的落点

四层树的父子关系全部用**外键 / 归属列**表达，读取方向永远「子指父」：

```
Project (existing)
  └─ Version   versions.project_id  → projects.id   （DB 外键，新表建表期可加）
       └─ Plan      plans.version_id → versions.id  （DB 外键）
       │            plans.project_id → projects.id  （反范式冗余，= version.project_id，见 §3.3）
            └─ Requirement/Bug   requirements.plan_id / bugs.plan_id （可空，**无 DB 外键**，应用层校验）
```

**为什么工单侧 `plan_id` 不建 DB 外键**：它是通过 `schema_sync` 给**存量表**追加的列
（`schema_sync.py:8` 能力边界：只支持 `ADD COLUMN`，SQLite 的 `ALTER TABLE ADD COLUMN`
无法可靠加带 FK 的列）。若在模型里声明 `db.ForeignKey`，则**全新库**（`create_all`）建出带 FK
的列、**存量库**（`ALTER`）建出不带 FK 的列——两条建表路径产出不同 schema，正是
`schema_sync.py:23-25` 处理 `documents.deleted_by_id` 时刻意规避的漂移。故 `plan_id` 与既有的
多态 `assignee_id`（`models/requirement.py:26` 注释「无法建 DB 级外键」）、`deleted_by_id`
同策略：**列上不建 FK，引用完整性在应用写入边界一次性校验**，删除侧用 `lifecycle` 前置守卫
防悬挂（§3.5）。

**为什么新表 `versions`/`plans` 可以建真 FK**：它们由 `create_all` 一次性建出，`version.project_id
→ projects.id`、`plan.version_id → versions.id`、`plan.project_id → projects.id` 都是建表期
就能落的 FK（对既有 `projects` 表建 FK 在 `CREATE TABLE` 时合法）。真 FK 给了版本 / 计划之间
的强完整性；对 `projects` 的 FK 则要求删项目前先清空其版本（§3.5 扩 `project_references`）。

### 3.2 关键代码路径（写路径）

**建版本** `POST /api/versions`（`require_role("admin","pm")`，仿 `routes/projects.py:49`）：
1. `json_body()` → `want_str("name", required, max_len=128)`、`want_str("description", strip=False)`、
   `want_str("status", default="planning", choices=VERSION_STATUSES)`、`want_int("project_id", required)`、
   可选 `want_int("owner_id")`、日期 `want_date("target_date")`（新原语，§6.4）。
2. 校验 `project_id` 存在（复用 `_validate_project` 同型，见 `routes/requirements.py:123`）、
   `owner_id` 存在（仿 `projects._want_owner_id`，`routes/projects.py:25`）。
3. `position = positions.next_position` **不适用**（那是「按 status 列分组」的分配器，
   `services/positions.py`）；版本 / 计划的排序是「按父分组落尾」，用一句
   `func.max(Version.position).filter_by(project_id=…)+1` 计算（§3.6 新增 `hierarchy.next_sort_position`）。
4. `db.session.add` → `commit` → `201 + to_dict()`。结构化日志记一行 `log.info("version created ...")`。

**建计划** `POST /api/plans`：同上，但父是 `version_id`；校验版本存在后，**把 `plan.project_id
设为 `version.project_id`**（反范式落定，此后不因任何操作漂移，见 §3.3）。

**建 / 改需求携带计划**（`routes/requirements.py:205 create_requirement` / `:249 patch_requirement`，
`bugs.py` 同构复用）：请求体可带 `plan_id`（`int` | `null`）。经**共享校验** `hierarchy.resolve_plan_for_ticket`：
- `plan_id` 缺省 → 不改（patch）/ 置 `NULL`（create）。
- `plan_id` 为 `null`（键存在且值为 `None`）→ **解除归属**（`plan_id=NULL`），不校验。
- `plan_id` 为整数 → `want_int` 归一（64 位硬界）→ 查 `Plan` 存在，否则 `ValidationError`（→400）；
  再校验**同项目不变量**：若工单已有 `project_id` 且 `!= plan.project_id` → `ValidationError`（→400）；
  若工单 `project_id` 为 `NULL` → **采纳**计划的项目（`ticket.project_id = plan.project_id`），
  使其自然落入正确的项目作用域。

**转 BUG**（`routes/requirements.py:410 convert_to_bug`）：新建的 Bug **继承源需求的 `plan_id`**
（与既有「继承 `project_id`」`:439` 同行补一句 `plan_id=req.plan_id`），保持层级不断链。

所有写路径的错误统一走 `errors.py:29`（`ValidationError`→400）与 `:39`（`QueryParamError`→400），
路由内**不写 `try/except`**（CLAUDE.md 五：错误显式传播 + 边界一次性校验）。

### 3.3 反范式 `plans.project_id` 的正确性论证

`plans.project_id` 冗余存储 `version.project_id`，目的是让**计划列表**直接复用既有的
`apply_project_filter(query, Plan, project_scope())`（`services/scope.py:176`）按项目作用域过滤，
而不必每次 join `versions`。冗余的代价是「可能漂移」，本设计用两条不变量消灭漂移：

- **不变量 A｜版本的 `project_id` 不可变**：`PATCH /api/versions/<id>` **拒绝** `project_id` 变更
  （请求体带 `project_id` 时忽略或 400）。版本一旦创建就锚定在一个项目里。
- **不变量 B｜计划改挂版本必须同项目**：`PATCH /api/plans/<id>` 允许改 `version_id`，但新版本
  必须与当前 `plan.project_id` 同项目，否则 400；改挂后 `project_id` 不变（因为同项目）。

有 A、B 之后，`plan.project_id` 永远等于 `plan.version.project_id`，冗余安全。工单侧不冗余
`version_id`（只存 `plan_id`），按版本过滤走子查询（§3.4），避免「计划改挂版本时要 fan-out
更新它名下所有工单的 version_id」这类漂移——单一真相是 `plan → version` 这一跳。

### 3.4 读路径：分类与筛选

**需求 / BUG 列表**（`routes/requirements.py:152 list_requirements`）在既有过滤链末尾追加两个可选参数，
经**共享辅助** `hierarchy.apply_ticket_hierarchy_filter(query, model)`（requirement / bug 复用，
仿 `bugs.py` 复用 `_next_position` / `check_concurrency` / `do_agent_advance` 的既有做法）：

- `?plan_id=<int>` → `query.filter(model.plan_id == n)`；`?plan_id=none` → `model.plan_id.is_(None)`。
- `?version_id=<int>` → `query.filter(model.plan_id.in_(select(Plan.id).where(Plan.version_id == n)))`
  （子查询，plan→version 单跳）；`?version_id=none` → `model.plan_id.is_(None)`（无计划 ⟺ 无版本）。
- 两者同传则 AND 叠加（若不一致则自然空集，语义正确）。
- 参数解析复用 `want_query_int`（`services/scope.py:42`，畸形 / 超界 → 400）+ `none` 哨兵
  （复用 `UNASSIGNED = "none"`，`scope.py:17`）；封装为 `hierarchy.version_scope()` / `plan_scope()`，
  形状与 `project_scope()`（`scope.py:169`）一致：`None`（不过滤）/ `"none"` / `int`。

**工单序列化富化**：在**序列化站点**（非 `to_dict` 内，避免 N+1，与 `document_counts` 同策略，
`routes/requirements.py:189` 已有先例）批量补一个只读 `plan` 概要：

```json
"plan_id": 7,
"plan": { "id": 7, "name": "迭代 1", "version_id": 3, "version_name": "v2.0" }
```

由 `hierarchy.with_plan_context(rows)` 实现：收集所有非空 `plan_id` → 一次 `Plan.id.in_(...)` →
一次 `Version.id.in_(...)` → 组装映射回填。`plan_id` 指向已删除计划时（理论上被 §3.5 守卫拦住，
但仍防御）→ `plan` 置 `null`，前端渲染为「未归属」，与 `_deleted_summary`
（`models/requirement.py:80`）「宁可显式占位也不说谎」的价值观一致（此处选 `null`，因为
删除已被守卫拦住，正常数据零命中）。富化应用于：`GET /api/requirements`、`GET /api/requirements/<id>`、
`GET /api/bugs`、`GET /api/bugs/<id>`、看板 `board_page.column_page`。

**版本 / 计划列表的计数富化**（供进度条）：
- 版本卡计划数：`hierarchy.version_plan_counts([vid...]) -> {vid: plan_count}`（一次 `GROUP BY version_id`）。
- **版本卡聚合进度**（评审 P1-B）：版本聚合进度条需要「该版本名下**所有工单**的 done/total」，
  而 `plan_count` 给不出这个数。新增 `hierarchy.version_ticket_counts([vid...]) -> {vid: {total, done}}`：
  以工单 `plan_id ∈ (该版本的计划 id 集合)` 做**工单→计划→版本两跳**的一次 `GROUP BY versions.id` 聚合
  （子查询，零 N+1）。`/api/versions` 每项据此富化 `total_count`/`done_count`，前端直接画聚合进度条，
  **不依赖把整张 plans 表拉到前端再客户端求和**——plans 分页（`limit=200`）下客户端求和会漏算，
  故版本聚合进度**必须服务端算**。
- 计划卡：`hierarchy.plan_ticket_counts([pid...]) -> {pid: {requirements, bugs, done}}`，其中 `done`
  统计终态工单（需求 `done` + BUG `closed`）。终态集合**不内联**，新增
  `workflow.terminal_statuses(entity) -> set[str]`（`services/workflow.py:51 _TERMINAL` 的公开只读访问器），
  count 查询用 `status.in_(workflow.terminal_statuses(entity))`——避免第二份会随邻接表漂移的终态清单。

### 3.5 删除与生命周期守卫（`services/lifecycle.py`）

沿用本仓库「引用完整性一律前置检查、冲突一律 409（不带 `allowed` 键）、绝不靠 DB 外键异常
兜底」的三条统一契约（`lifecycle.py:6-14`）：

- **扩 `project_references`（`lifecycle.py:101`）**：现返回 `{requirements, bugs}`；**追加 `versions`
  计数**。删项目时 `versions` 计数非零即 409——否则删项目会因 `versions.project_id` 的真 FK
  触 `IntegrityError` → `errors.py:72` 兜底 500（用户看到「internal server error」而非「还有 3 个版本」）。
  计划被版本传递覆盖（有计划必有版本），故只需数版本。`conflict_project_has_tickets`
  （`:109`）的 detail 相应带上 `versions` 计数与「先归档 / 清空版本」的 hint。
- **新增 `version_references(version_id) -> {plans}`** + `conflict_version_has_plans(refs)`（409，无 `allowed`）。
  删版本前若有计划 → 409，提示「先删除 / 归档其计划」。
- **新增 `plan_references(plan_id) -> {requirements, bugs}`** + `conflict_plan_has_tickets(refs)`（409，无 `allowed`）。
  删计划前若有工单 → 409，提示「先把工单移出该计划或删除」。计划与工单**无 DB 外键**，
  不会触 IntegrityError，但仍前置守卫：避免留下指向已删计划的悬挂 `plan_id`（保持数据自洽）。
- **软路径**：版本 / 计划都提供 `status='archived'`（PATCH 即可），归档即从默认列表 / 选择器隐藏
  （`?include_archived=1` 才返回，仿 `routes/projects.py:41`），是比删除更常用的「收起」动作。
- **工单删除级联**（`lifecycle.py:141 delete_ticket_cascade`）**无需改动**：`plan_id` 只是工单自身
  的一列，随工单行一并删除，不涉及跨表清理。

### 3.6 新增服务模块 `services/hierarchy.py`（叶子）

把「版本 / 计划的读写辅助」收敛到一个可单测的叶子模块，避免让已 611 行的 `routes/requirements.py`
逼近 800 行硬顶（CLAUDE.md 二）。它**不碰 Flask 响应**（除少数返回既有 409 构造器的守卫留在
`lifecycle.py`），只提供纯函数：

- `next_sort_position(model, **filter_by) -> int`——按父分组取 `max(position)+1`；**空父（首个子）时
  `func.max` 返回 `NULL`，须 `COALESCE`/`(m or -1)+1` 归 0**（评审 P2-E），否则首行 `position` 被置 `None`
  违反 `NOT NULL`。
- `version_scope()` / `plan_scope()`——查询串边界，返回 `None|"none"|int`（复用 `scope.want_query_int`）。
- `apply_ticket_hierarchy_filter(query, model)`——把 version/plan 过滤套到工单查询。
- `resolve_plan_for_ticket(ticket, data) -> None`——校验并就地应用 `plan_id`（含同项目不变量与项目采纳），
  非法抛 `ValidationError`（→400）。
- `with_plan_context(rows) -> list[dict]` / `with_plan_context_one(row) -> dict`——工单序列化富化。
- `version_plan_counts(ids)` / `version_ticket_counts(ids)` / `plan_ticket_counts(ids)`——批量计数
  （版本的计划数 / 版本聚合的工单 `total·done` / 计划的工单 `requirements·bugs·done`，各一次 `GROUP BY`、零 N+1；`version_ticket_counts` 为评审 P1-B 新增）。

依赖方向：`services/hierarchy` → `models/{version,plan,requirement,bug}` + `services/{scope,validation,workflow}`；
`routes/{versions,plans,requirements,bugs}` → `services/hierarchy`。无环。

---

## 4. 数据模型（Data model）

### 4.1 新表 `versions`（`backend/models/version.py`）

| 列 | 类型 | 约束 / 默认 | 说明 |
|---|---|---|---|
| `id` | INTEGER | PK | |
| `project_id` | INTEGER | FK `projects.id`, NOT NULL, index | 所属项目；创建后不可变（§3.3 不变量 A） |
| `name` | VARCHAR(128) | NOT NULL | 版本名，如 `v2.0`、`2026 Q3 发布` |
| `description` | TEXT | NULL | |
| `status` | VARCHAR(16) | NOT NULL, default `'planning'` | `VERSION_STATUSES` 枚举 |
| `target_date` | DATE | NULL | 计划发布日期 |
| `released_at` | DATETIME | NULL | 实际发布时间；**服务端托管**（`status` 转入 `released` 时后端 stamp `utcnow()`、转出时清空），客户端不可写（评审 P1-C，仿 `projects.py:89` 的 `archived` 只暴露语义、不暴露时间戳） |
| `owner_id` | INTEGER | FK `users.id`, NULL | 版本负责人（仿 `projects.owner_id`） |
| `position` | INTEGER | NOT NULL, default 0 | 项目内手动排序（append 落尾） |
| `created_at` / `updated_at` | DATETIME | NOT NULL, `utcnow` / `onupdate=utcnow` | 与全表一致 |

`VERSION_STATUSES = ("planning", "active", "released", "archived")`
（规划中 / 进行中 / 已发布 / 已归档）。`to_dict()` 输出全部列 + `_iso` / `_iso_date` 序列化时间字段。

### 4.2 新表 `plans`（`backend/models/plan.py`）

| 列 | 类型 | 约束 / 默认 | 说明 |
|---|---|---|---|
| `id` | INTEGER | PK | |
| `version_id` | INTEGER | FK `versions.id`, NOT NULL, index | 所属版本 |
| `project_id` | INTEGER | FK `projects.id`, NOT NULL, index | 反范式 = `version.project_id`（§3.3） |
| `name` | VARCHAR(128) | NOT NULL | 计划名，如 `迭代 1`、`Sprint 3` |
| `description` | TEXT | NULL | |
| `status` | VARCHAR(16) | NOT NULL, default `'planning'` | `PLAN_STATUSES` 枚举 |
| `start_date` / `end_date` | DATE | NULL | 计划周期 |
| `position` | INTEGER | NOT NULL, default 0 | 版本内手动排序 |
| `created_at` / `updated_at` | DATETIME | NOT NULL | |

`PLAN_STATUSES = ("planning", "active", "completed", "archived")`
（规划中 / 进行中 / 已完成 / 已归档）。

### 4.3 既有表新增列

| 表 | 列 | 类型 | 说明 |
|---|---|---|---|
| `requirements` | `plan_id` | INTEGER, NULL, index, **无 DB 外键** | 归属计划；`NULL` = 未归属（§3.1） |
| `bugs` | `plan_id` | INTEGER, NULL, index, **无 DB 外键** | 同上 |

模型侧写法（`models/requirement.py` / `bug.py`）：
`plan_id = db.Column(db.Integer, nullable=True, index=True)`（**不写 `db.ForeignKey`**，理由见 §3.1），
并在 `to_dict()`（`requirement.py:39` / `bug.py:39`）的返回 dict 里追加 `"plan_id": self.plan_id`
（人类可读的 `plan` 概要不进 `to_dict`，在序列化站点富化，§3.4）。

### 4.4 迁移登记（**硬约束，漏登记 = 存量库全线 500**）

`db.create_all()` 只建**新表**（`versions` / `plans` 自动建出），但对**已存在**的 `requirements` /
`bugs` 表不会加列。故 `requirements.plan_id` / `bugs.plan_id` **必须**登记进
`services/schema_sync.py:19 ADDITIVE_COLUMNS`，**追加在列表末尾**（`schema_sync.py:36-37`：
`sync_additive_columns` 按列表顺序返回 `applied`，`tests/test_schema_sync.py` 断言该精确顺序）：

```python
# version-plan-hierarchy §4.4：工单归属计划的两列。默认 NULL，存量行零回填即语义正确
# （存量工单确实「未归属任何计划」）。无 DB 外键 → DDL 为裸 INTEGER，与模型侧「不建 FK」
# 的两条建表路径产出同一 schema（schema_sync.py:23-25 的同款考量）。
("requirements", "plan_id", "INTEGER"),
("bugs", "plan_id", "INTEGER"),
```

登记后 `ADDITIVE_COLUMNS` 从 10 条变 12 条。`versions` / `plans` **是新表、不进 `ADDITIVE_COLUMNS`**
（那只管「给已存在的表加列」）。

### 4.5 模型注册（**两处都要登记**）

`backend/models/__init__.py` 的 **import 行（`:6-22`）与 `__all__` 列表（`:24-44`）两处都要加**
（漏 import → 表不进 metadata、`create_all` 建不出来；漏 `__all__` → 符号导不出，
`models/__init__.py:40-43` 的教训原文）：

```python
from .version import Version, VERSION_STATUSES
from .plan import Plan, PLAN_STATUSES
# __all__ 追加： "Version", "VERSION_STATUSES", "Plan", "PLAN_STATUSES"
```

### 4.6 种子数据（`backend/seed.py`，守住「每类一条」）

`seed.py:130` 现登记 8 类实体。追加**恰好一个版本 + 一个计划**（仍是「每类一条」，
CLAUDE.md「Seed data is one row per category」）：

- 版本 `v1.0 首个可用版本`（`project_id=project.id`, `status="active"`）。
- 计划 `迭代 1：打通主流程`（`version_id=version.id`, `project_id=project.id`, `status="active"`）。
- 把既有示例需求（`seed.py:77`）与示例 BUG（`:87`）的 `plan_id` 设为该计划 id。
- 在 `seed.py:130` 的登记循环追加 `("version", version)` 与 `("plan", plan)`，各 `SeedRecord.mark(...)`。
- `backend/models/seed_record.py::SEED_ENTITY_TYPES` **必须**追加 `"version"` / `"plan"`（评审 P2-A 更正：
  `SeedRecord.mark`（`seed_record.py:43`）实测**不做**白名单校验，故并非「会被拒绝」；追加的真实理由是让该白名单
  保持「可登记类别」的单一真相，并与 §4.7 中 purge 的 `_entity_models` 登记**一一对应**——两处任缺其一，
  版本 / 计划要么变新孤岛，要么被 purge 误判为孤儿删掉登记）。
- **递增 `SEED_VERSION`** 由 `"2"` 到 `"3"`（评审 P2-B：seed 写入内容已变，`seed_record.py:19` docstring
  明示「每次改写入内容都应递增」），并把 `seed.py` 的「每类 1 条，共 8 行」docstring 同步为 **10 行**。

seed 行数从 8 → 10；DoD 里的 `test_seed_minimal.py`（`tests/`）断言需同步（§8）。

### 4.7 示例数据清理（`backend/tools/purge_demo_data.py`）

新增两类 seed 行必须能被 purge 精确识别与清理（CLAUDE.md「Any new seed row must be registered
too, otherwise it becomes demo data that purge can never clean up」）。

**⚠️ 评审 P1-A 更正**：该工具**不是**一条「按 `seed_records` 顺序删行」的线性序列，而是一套
**按类别硬编码的管线**（`PROVENANCE_CATEGORIES:45`、`_candidates:172`、`_entity_models:154`、
`_summarise_principals:496`）。仅「把 plan/version 插入删除顺序」既无处可插，还会触发一个**静默损坏**：
`_prune_orphan_seed_records:135` 对每条 `seed_records` 用 `_entity_models().get(entity_type)` 找模型，
**找不到即当孤儿删掉那条登记**——若不同步 `_entity_models`，版本 / 计划的 `SeedRecord` 会在首次 purge
（含 dry-run 的计算阶段）被判为孤儿删除，等于自己抹掉出身证明，且工单表行永远清不掉。故本轮 purge
的改动必须是下面这**四处**（缺一即上述损坏或「清不掉」）：

1. **`_entity_models():154` 追加** `"version": Version, "plan": Plan`——**最低限度的必须项**：让
   `_prune_orphan_seed_records` 认得这两类登记，不再误判为孤儿。
2. **`PROVENANCE_CATEGORIES:45` 追加** `"versions"`, `"plans"`；**`_candidates():172` 的 `specs` 追加两条**：
   `("versions", Version, Version.name, (), "version")`、`("plans", Plan, Plan.name, (), "plan")`——**legacy
   指纹为空元组 `()`**（版本 / 计划是全新实体，存量库里根本不存在，无历史指纹可言；`column.in_(())` 恒假，
   候选集因此只来自 `seed_records` 登记，语义正确）。
3. **新增 `_purge_versions(rows)` / `_purge_plans(rows)`**：两个带前置引用守卫的删除函数（仿 `_purge_projects:329`）——
   删版本前若名下有计划则跳过并说明；删计划前若名下有工单则跳过并说明。
4. **`_summarise_principals():496` 按 FK 安全顺序接线**：工单（已在 `_run` 先删）→ **计划**（其父版本 / 项目
   仍在，删子无碍）→ **版本**（其名下计划已在上一步处理，父项目仍在）→ 项目 → Agent → 用户。

「每类留一」（`_split_keep_delete`）对版本 / 计划同样生效：seed 只写 1 版本 + 1 计划，候选集恒为 1 条，
必被保留、`removals` 恒空——因此**正常单 seed 场景下版本 / 计划永远不会被删**；只有当库里被人为塞进多条
**带 `SeedRecord` 登记**的演示版本 / 计划时，多余的才按上述顺序清理。该工具 **dry-run 默认、SQLite 先备份**
的既有铁律不变。

---

## 5. 文件 / 模块变更计划（File / module change plan）

> 图例：🆕 新建 · ✏️ 修改。所有「新增列 / 新符号 / 新 seed 行」的登记点已在 §4 展开。

### 5.1 后端

| 文件 | 动作 | 一句话意图 |
|---|---|---|
| `backend/models/version.py` | 🆕 | `Version` 模型 + `VERSION_STATUSES` + `to_dict`。 |
| `backend/models/plan.py` | 🆕 | `Plan` 模型 + `PLAN_STATUSES` + `to_dict`。 |
| `backend/models/__init__.py` | ✏️ | import 行与 `__all__` **两处**登记 `Version`/`Plan` 及其常量（`:6-22`/`:24`）。 |
| `backend/models/requirement.py` | ✏️ | 加 `plan_id` 列（无 FK，`:26` 之后）；`to_dict` 追加 `plan_id`（`:39`）。 |
| `backend/models/bug.py` | ✏️ | 同上（`:23`/`:39`）。 |
| `backend/models/seed_record.py` | ✏️ | `SEED_ENTITY_TYPES` 追加 `"version"`/`"plan"`。 |
| `backend/services/schema_sync.py` | ✏️ | `ADDITIVE_COLUMNS` **末尾**追加 `requirements.plan_id`/`bugs.plan_id`（`:19`）。 |
| `backend/services/hierarchy.py` | 🆕 | 版本 / 计划读写辅助叶子模块（§3.6 全部纯函数）。 |
| `backend/services/workflow.py` | ✏️ | 新增只读访问器 `terminal_statuses(entity)`（暴露 `:51 _TERMINAL`，供进度计数）。 |
| `backend/services/lifecycle.py` | ✏️ | 扩 `project_references` 计版本（`:101`）；新增 `version_references`/`plan_references` 与两个 `conflict_*`（409，无 `allowed`）。 |
| `backend/services/__init__.py` | —— | 评审 P2-G：实测为纯包标记、不聚合导出（各 service 直接 `from services import x`），**无需改动**；`hierarchy` 同样直接 import。 |
| `backend/routes/versions.py` | 🆕 | `versions_bp`：list/create/get/patch/delete + `?status=`/`?include_archived=`/project 作用域 + 计划计数富化。 |
| `backend/routes/plans.py` | 🆕 | `plans_bp`：同型，按 `?version_id=`/project 作用域过滤 + 工单计数富化。 |
| `backend/routes/__init__.py` | ✏️ | `register_blueprints` 挂载 `versions_bp`/`plans_bp`（15 → 17 蓝图）。 |
| `backend/routes/requirements.py` | ✏️ | list 接 `?version_id=`/`?plan_id=`（`:152`）；create/patch 接 `plan_id`（`:205`/`:249`）；convert 继承 `plan_id`（`:439`）；序列化站点富化 `plan`（`:189`/`:246`）。 |
| `backend/routes/bugs.py` | ✏️ | 复用上述共享辅助（同 `bugs.py` 复用需求 helper 的既有方式）：list 过滤 + create/patch 的 `plan_id` + 序列化富化。 |
| `backend/routes/board.py` / `services/board_page.py` | ✏️ | 看板列查询接 `?version_id=`/`?plan_id=` 过滤 + 卡片 `plan` 富化。 |
| `backend/seed.py` | ✏️ | 追加 1 版本 + 1 计划，示例需求 / BUG 归属该计划，登记 2 条 `SeedRecord`（`:77`/`:87`/`:130`）。 |
| `backend/tools/purge_demo_data.py` | ✏️ | **四处**（评审 P1-A）：`_entity_models` 加 version/plan（防误判孤儿）、`PROVENANCE_CATEGORIES`+`_candidates` 加两类（空 legacy 指纹）、新增 `_purge_versions`/`_purge_plans` 守卫、`_summarise_principals` 按 FK 顺序接线（计划→版本→项目）。 |

### 5.2 前端

| 文件 | 动作 | 一句话意图 |
|---|---|---|
| `frontend/lib/types.ts` | ✏️ | 加 `Version`/`Plan`/`PlanContext` 与 `VersionCreate`/`VersionUpdate`/`PlanCreate`/`PlanUpdate`；`Requirement`(`:139`)/`Bug`(`:158`) 加 `plan_id?: number\|null`、`plan?: PlanContext\|null`。 |
| `frontend/lib/constants.ts` | ✏️ | 加 `VERSION_STATUS_STYLES: Record<VersionStatus, BadgeStyle>`/`PLAN_STATUS_STYLES: Record<PlanStatus, BadgeStyle>`（**用穷尽 `Record<Status,…>` 而非 `STATUS_STYLES:46` 的 `Record<string,…>`，漏键即编译错**，评审 P2-H；仿 `PRIORITY_STYLES:62`）+ 选项列表 + `versionStatusStyle()`/`planStatusStyle()` 访问器。 |
| `frontend/lib/api.ts` | ✏️ | 加前缀常量 `VERSIONS_KEY = "/versions?limit=200"`、`PLANS_KEY = "/plans?limit=200"`（供整表下拉；分页 / 带筛选视图仍内联拼 key，遵 `api.ts:16` 的一 key 一形状铁律）。 |
| `frontend/lib/swr-keys.ts` | ✏️ | `TICKET_VIEW_PREFIXES`(`:13`) 与 `ADMIN_VIEW_PREFIXES`(`:27`) 补 `/versions`/`/plans`（改单一真相处，令跨视图 mutate 失效正确）。 |
| `frontend/components/layout/Sidebar.tsx` | ✏️ | `NAV`(`:34`) 在「需求」前插入「版本」项（`href:/versions`, `match:/versions`, 内联 SVG 图标）。 |
| `frontend/app/(app)/versions/page.tsx` | 🆕 | 「版本 / 计划」主管理页：版本卡（进度 + 计划计数）可展开内联其计划列表；计划卡带进度条 + 需求/BUG 计数 + 「查看工单」跳转；顶栏 + `FilterBar`(状态) + `Pagination`，仿 `requirements/page.tsx`。 |
| `frontend/components/planning/VersionFormModal.tsx` | 🆕 | 版本增改弹窗，`state\|null`+`onSaved` 模式（仿 `ProjectFormModal.tsx:17`）。 |
| `frontend/components/planning/PlanFormModal.tsx` | 🆕 | 计划增改弹窗（父版本预填 / 可选），同款模式。 |
| `frontend/components/planning/VersionCard.tsx` / `PlanRow.tsx` | 🆕 | 版本卡（可折叠）+ 计划行（进度条用 `ui/ProgressBar`），承载「顶级设计」的视觉（§7）。 |
| `frontend/components/planning/PlanPicker.tsx` | 🆕 | 级联选择器：版本 select → 计划 select，输出 `plan_id\|null`，供建单 / 抽屉复用。 |
| `frontend/hooks/useVersions.ts` / `usePlans.ts` | 🆕 | SWR 列表 hook（filter + paginate + CRUD 回调，仿 `useDocumentLibrary`），mutate 后调 `invalidateTicketViews`/`invalidateAdminViews`。 |
| `frontend/components/FilterBar.tsx` | ✏️ | 增加可选 `version`/`plan` 级联筛选槽（`Props`(`:10`) 加可选字段，缺省不渲染，既有调用点零改动）。 |
| `frontend/app/(app)/requirements/page.tsx` / `bugs/page.tsx` | ✏️ | listKey 拼入 `version_id`/`plan_id`（`:80-91`）；`FilterBar` 接版本 / 计划筛选；表格行加「计划 / 版本」徽章列。 |
| `frontend/components/TicketDrawer.tsx`（及其 `collab/` 拆分） | ✏️ | 详情区加「计划」`PlanPicker`，PATCH `plan_id`；时间线 / 概要显示所属版本 · 计划。 |
| `frontend/app/(app)/requirements/board/page.tsx` / `bugs/board/page.tsx` | ✏️ | 看板顶部接版本 / 计划筛选（透传给 `useBoard` 的 key）。 |
| `frontend/hooks/useBoard.ts` | ✏️ | key 构造（`:19` 一带）接受可选 `version_id`/`plan_id`，透传后端。 |

---

## 6. 接口设计（Interface design）

所有响应体沿用既有契约：列表返回**裸数组** + `X-Total-Count` 头（`services/pagination.py`），
错误体恒 `{error, detail?}`（`errors.py`）。金额 / 计数类富化字段挂在列表项对象上。

### 6.1 版本 `/api/versions`

| 方法 / 路径 | 鉴权 | 语义 |
|---|---|---|
| `GET /api/versions` | `jwt_required` | 列版本。查询串：`?project_id=`（作用域，复用 `project_scope`）、`?status=`（∈`VERSION_STATUSES`）、`?include_archived=1`（默认隐藏 `archived`）、`?limit=&offset=`。每项富化 `plan_count` 与聚合 `total_count`/`done_count`（供版本卡聚合进度条，评审 P1-B）。裸数组 + `X-Total-Count`。 |
| `POST /api/versions` | `admin\|pm` | 建版本。体：`{name, description?, status?, project_id, owner_id?, target_date?}`。校验 project/owner 存在。→ `201 + to_dict`。 |
| `GET /api/versions/<int:id>` | `jwt_required` | 取单个（含 `plan_count`/`total_count`/`done_count`）。404 若不存在。 |
| `PATCH /api/versions/<int:id>` | `admin\|pm` | 改 `name/description/status/target_date/owner_id/position`。`released_at` **服务端托管**：随 `status` 转入 / 转出 `released` 由后端 stamp / 清空，**不接受客户端传值**（评审 P1-C，仿 `projects.py:89`）。**拒绝改 `project_id`**（§3.3 A）。无可改字段 → 400（仿 `projects.py:125`）。 |
| `DELETE /api/versions/<int:id>` | `admin\|pm` | 删空版本；有计划 → `409 conflict_version_has_plans`（detail 带 `plans` 计数 + hint，无 `allowed`）。 |

### 6.2 计划 `/api/plans`

| 方法 / 路径 | 鉴权 | 语义 |
|---|---|---|
| `GET /api/plans` | `jwt_required` | 列计划。查询串：`?version_id=`（过滤到某版本）、`?project_id=`（作用域）、`?status=`、`?include_archived=1`、`?limit=&offset=`。每项富化 `{requirement_count, bug_count, done_count}`。 |
| `POST /api/plans` | `admin\|pm` | 建计划。体：`{name, description?, status?, version_id, start_date?, end_date?}`。校验版本存在；`project_id` 由版本推导写入。→ `201`。 |
| `GET /api/plans/<int:id>` | `jwt_required` | 取单个（含计数）。 |
| `PATCH /api/plans/<int:id>` | `admin\|pm` | 改 `name/description/status/start_date/end_date/position/version_id`；改 `version_id` 须同项目否则 400（§3.3 B）。 |
| `DELETE /api/plans/<int:id>` | `admin\|pm` | 删空计划；有工单 → `409 conflict_plan_has_tickets`（detail 带 `requirements`/`bugs` 计数 + hint）。 |

### 6.3 需求 / BUG 的增量（向后兼容）

- `GET /api/requirements` / `GET /api/bugs`：**新增可选** `?version_id=<int|none>`、`?plan_id=<int|none>`
  （与既有 `q/status/priority/assignee_*/reporter_id` AND 叠加）；响应项**新增** `plan_id` 与只读
  `plan:{id,name,version_id,version_name}`（`plan_id=NULL` 时 `plan=null`）。既有字段与形状不变。
- `POST /api/requirements` / `POST /api/bugs`：体**可选** `plan_id`；缺省 = 不归属。
- `PATCH /api/requirements/<id>` / `PATCH /api/bugs/<id>`：体**可选** `plan_id`（`int` 改归属，`null` 解除）。
- `POST /api/requirements/<id>/convert-to-bug`：新 Bug 继承源需求 `plan_id`（无新参数）。
- `GET /api/board/<entity>`：新增可选 `?version_id=`/`?plan_id=`；卡片新增 `plan` 富化。

**错误契约**：非法 `plan_id`（非整数 / 超界）→ 400（`want_int`/`want_query_int`）；`plan` 不存在
→ 400（`ValidationError`，`{error:"plan_id is invalid", detail:{field:"plan_id"}}`）；计划与工单
跨项目 → 400（`{error:"plan and ticket must be in the same project", detail:{field:"plan_id"}}`）。

### 6.4 新增边界原语 `want_date`

版本 / 计划有 `target_date`/`start_date`/`end_date` 三个**日期**字段（DATE，非 datetime）。
`services/validation.py` 今天只有 `want_str/int/bool/email`（`:47/:94/:121/:146`），无日期原语。
新增 `want_date(data, key) -> date|None`：接受 `YYYY-MM-DD`，非法 → `ValidationError`（→400）；
缺省 / 空串 → `None`。查询串侧已有 `want_query_datetime`（`scope.py:138`），本处是**请求体**侧的
对偶，住在 `validation.py`（边界模块归位，同 `want_email` 的理由，`validation.py:14-17`）。

**评审 P1-C**：`released_at` 是 DATETIME 且**服务端托管**（§4.1 / §6.1：随 `status` 进出 `released` 由后端
stamp / 清空），**不经请求体传入**，故本轮**无需**新增 datetime 请求体原语——`want_date` 只服务上述三个
DATE 字段。这样既补齐了「谁来解析 `released_at`」的缺口，又与 `projects.py:89`「时间戳由服务端写、
对外只暴露语义动作」的既定约定一致。

---

## 7. 前端设计（界面与人机交互）

设计基调延续仓库既有的**暖色浅色风**（ivory 底 + clay/coral 点缀 + 衬线标题，README §技术栈），
所有色值走 `constants.ts` 的 `BadgeStyle`（内联 hex，非 Tailwind class，`constants.ts:18`）。

### 7.1 「版本」主页 `/versions`（层级一屏可览）

- **顶栏**：标题「版本 / 计划」+ 当前项目作用域标签（`useProjectScope().scopeLabel`，`project-scope.tsx`）
  + 「新建版本」主按钮（`admin|pm` 可见，仿 `requirements/page.tsx:37` 的 `canCreate` 门禁）。
- **版本卡（可折叠 accordion）**：每张卡显示版本名、状态徽章（`VERSION_STATUS_STYLES`）、
  `target_date`、负责人头像（`ui/Avatar` 的 `AssigneeAvatar`）、`plan_count` 与一条**聚合进度条**
  （评审 P1-B：**直接读 `/api/versions` 富化的 `done_count`/`total_count`**，`ui/ProgressBar` 的
  `value = total_count ? done_count/total_count*100 : 0`；**并显式传 `label`**——`ProgressBar` 默认
  `aria-label` 是「上传进度」，规划场景须覆盖为如「版本进度 done/total」。**不在前端对 plans 列表求和**，
  避免分页漏算）。卡右侧 `⋯` 菜单：编辑 / 归档 / 删除
  （删除走 `ConfirmDialog`，命中 409 时把后端 detail 的「还有 N 个计划」原样呈现，`ui/ConfirmDialog`
  保持打开并内联报错，`ConfirmDialog.tsx` 既有能力）。
- **展开后**：内联渲染该版本的**计划行**（`PlanRow`）——计划名、状态徽章、周期
  （`start_date~end_date`）、`{requirement_count+bug_count}` 计数、**进度条**（`done_count/总数`），
  行内「查看工单」链接跳 `/requirements?plan_id=<id>`（预置筛选）。版本卡底部「+ 新建计划」
  （父版本预填）。
- **加载 / 空 / 错误**：`SkeletonRows`/`EmptyState`/`ErrorState`（`ui/`），空态文案引导「先建一个版本」。
- **分页**：`Pagination`（`total<=limit` 时自渲染为空，`Pagination.tsx`）。
- 数据经 `useVersions()`/`usePlans()`（SWR + `listFetcher`，key 内联拼 `project_id`/`status`/`include_archived`/
  `limit`/`offset`，遵 `api.ts` 一 key 一形状铁律）；CRUD 后 `invalidateAdminViews(mutate)` +
  `invalidateTicketViews(mutate)`（计划进度依赖工单，`swr-keys.ts`）。

### 7.2 需求 / BUG 列表与看板的分类筛选

- `FilterBar` 增加**级联筛选**：先选版本（`Select`，选项来自 `useVersions` 的当前项目集合），
  选定版本后计划 `Select` 才启用（选项来自该版本的计划）；两者皆有「全部」项，且支持「未归属」
  （映射 `?version_id=none` / `?plan_id=none`）。清空按钮（`FilterBar` 既有 `hasFilter` 逻辑）一并复位。
- 表格新增「计划」列：`Badge` 显示 `plan.name`，`title` 悬浮显示 `版本 · 计划`；未归属显示浅灰「—」。
- 看板页顶部同一套版本 / 计划筛选，透传给 `useBoard` 的 key（`useBoard.ts:19` 的 `scopeParam` 旁边
  再拼 `version_id`/`plan_id`）；看板卡角落加一枚小计划徽章。

### 7.3 工单抽屉的计划归属

`TicketDrawer` 详情区新增「计划」字段，用 `PlanPicker`（版本→计划级联）读当前 `plan_id`，
变更即 `PATCH {plan_id}`（`null` = 解除）。命中「跨项目」400 时把后端文案 toast 出来。
抽屉里同时以只读方式展示「所属：项目 · 版本 · 计划」的面包屑，让层级一眼可见。

### 7.4 可访问性与一致性

- 所有 `Select`/`Input` 走 `ui/` 组件（自带 `useId` 关联 label）；进度条 `ProgressBar` 的可见百分比
  用 `aria-label`（`ProgressBar` 既有 `aria-*`）。
- 状态徽章颜色语义统一：`planning` 中性灰、`active` 蓝、`released`/`completed` 绿、`archived` 淡灰
  （与 `PRIORITY_STYLES` 同一套明度基线）。
- 侧栏「版本」图标用一个「层叠 / 分支」意象的内联 SVG（与既有 `Icon({path})` 同风格，`Sidebar.tsx:17`）。

---

## 8. 测试与验收标准（Testing & acceptance criteria）

### 8.1 后端（`backend/tests/`，pytest；判据见文首基线）

新增测试文件（真实集成测试，走 `conftest.py` 的 app/client/auth fixture，禁止 mock DB / 鉴权）：

- `test_versions.py`：CRUD；`project_id` 存在性 400；`PATCH` 拒改 `project_id`；`?status=`/
  `?include_archived=` 过滤；删非空版本 → 409（detail 带 `plans` 计数、无 `allowed`）；分页 `X-Total-Count`；
  **富化 `plan_count`/`total_count`/`done_count` 正确**（评审 P1-B：建版本→建两计划→各挂工单并推一张进终态，
  断言版本聚合 done/total）；**`released_at` 服务端托管**（评审 P1-C：`status` 转 `released` 后 `released_at`
  非空、转出后清空；请求体传 `released_at` 不生效）。
- `test_plans.py`：CRUD；建计划自动写 `project_id=version.project_id`；`PATCH version_id` 跨项目 → 400；
  `?version_id=` 过滤；删非空计划 → 409；计数富化 `{requirement_count,bug_count,done_count}` 正确
  （含 done 用 `workflow.terminal_statuses` 判定）。
- `test_hierarchy.py`：`resolve_plan_for_ticket` 的同项目不变量与「无项目工单采纳计划项目」；
  `apply_ticket_hierarchy_filter` 的 `version_id`/`plan_id`/`none` 各分支；`with_plan_context`
  批量富化零 N+1（可用查询计数断言）。
- `test_requirements.py` / `test_bugs.py`（✏️ 既有，追加）：建单带 `plan_id`；`PATCH plan_id`
  设置 / 解除；`?plan_id=`/`?version_id=`/`=none` 过滤；convert-to-bug 继承 `plan_id`；
  非法 `plan_id` 400、不存在 400、跨项目 400；响应含 `plan_id` 与 `plan` 富化。
- `test_lifecycle.py`（✏️）：`project_references` 计入版本；删有版本的项目 → 409；
  新增 `version_references`/`plan_references` 与两个 `conflict_*`（409 无 `allowed`）。
- `test_schema_sync.py`（✏️）：`ADDITIVE_COLUMNS` 末尾新增两列的**精确顺序**断言；存量库 backfill 幂等。
- `test_seed_minimal.py`（✏️）：seed 现为 **10** 行（8 + 版本 + 计划），各有 `SeedRecord`；
  示例需求 / BUG 的 `plan_id` 指向示例计划。
- `test_purge_demo_data.py`（✏️）：干跑不写；**版本 / 计划的 `SeedRecord` 不被 `_prune_orphan_seed_records`
  误判为孤儿删除**（评审 P1-A：`_entity_models` 已登记两类——这是最易漏且后果最隐蔽的一条）；单 seed 场景
  版本 / 计划被「每类留一」保留；人为塞入多条带登记的演示版本 / 计划时，正式跑能按 **计划→版本→项目** 的
  FK 安全顺序清掉而不违反 FK；且**不误删**真实用户建的版本 / 计划（无 `SeedRecord` 的行不动）。
- `test_workflow.py`（✏️）：`terminal_statuses("requirement") == {"done"}`、
  `terminal_statuses("bug") == {"closed"}`（守住终态单一真相）。
- `test_validation.py`（✏️）：`want_date` 合法 / 非法 / 空。

### 8.2 前端

- `npm run typecheck`（`tsc --noEmit` 0 error）+ `npm run build` 成功（CLAUDE.md 质量门禁）。
- `types.ts` 新增类型被 `constants.ts` 的 `Record<...Status, BadgeStyle>` 全覆盖（漏键即编译错误，
  与 `login-hardening` 评审记录里 `Record<UserActivityAction,…>` 同款保障）。

### 8.3 验收清单（Definition of Done，功能维度）

1. 能在 UI 建版本、建计划、把需求 / BUG 归属到计划；层级 项目→版本→计划→工单 端到端可见。
2. 需求 / BUG 列表与看板能按版本、按计划筛选，「未归属」可单独筛出。
3. 计划卡进度条随其工单进入终态而增长；版本卡聚合进度正确。
4. 删除非空版本 / 计划被 409 拦截并给出可操作计数；归档可把它们从选择器隐藏。
5. 后端 `pytest -q` 零失败且用例总数 ≥ 开工基线（808）；前端 typecheck + build 通过。
6. 存量 `aragon.db` 启动零报错（`schema_sync` 幂等补列），既有工单 `plan_id=NULL` 照常工作。

---

## 9. 风险与缓解（Risks & mitigations）

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R-1 | **漏登记 `schema_sync.ADDITIVE_COLUMNS`** | 存量库对 `requirements`/`bugs` 的每次查询 `no such column: plan_id` → 全线 500 | §4.4 明确「末尾追加两列」为硬约束；`test_schema_sync.py` 顺序断言 + 一条「存量库启动零报错」集成测试兜底。 |
| R-2 | **`plan_id` 误建 DB 外键** | `create_all` 与 `ALTER` 两条建表路径 schema 漂移；且删计划触 IntegrityError → 500 | §3.1 定死「列上不建 FK」，DDL 为裸 INTEGER，与 `assignee_id`/`deleted_by_id` 同策略；引用完整性走应用层校验 + `lifecycle` 前置守卫。 |
| R-3 | **删项目触版本 FK 的 500** | `versions.project_id` 真 FK，删有版本的项目会 IntegrityError → 兜底 500 | §3.5 扩 `project_references` 计版本，前置 409；`test_lifecycle.py` 覆盖。 |
| R-4 | **`plans.project_id` 反范式漂移** | 冗余列与 `version.project_id` 不一致 → 项目作用域筛选错乱 | §3.3 两条不变量（版本 project 不可变 + 计划改版本须同项目）从写路径消灭漂移来源；`test_plans.py` 断言。 |
| R-5 | **富化 `plan` 概要 N+1** | 列表 50 行触发 50+ 次子查询，拖慢列表 | §3.4 在序列化站点批量富化（`Plan.id.in_`+`Version.id.in_` 各一次），复刻 `document_counts` 既有零 N+1 做法；`test_hierarchy.py` 查询计数断言。 |
| R-6 | **seed 破坏「每类一条」/ purge 清不掉 / 误删登记** | 违反 CLAUDE.md 硬约束，示例数据变「无出身」的永久残留；或 purge 把版本 / 计划登记误当孤儿删掉（评审 P1-A） | §4.6 只加 1 版本 + 1 计划、各登记 `SeedRecord`、扩 `SEED_ENTITY_TYPES`、递增 `SEED_VERSION`；§4.7 修正 purge 为**四处**改动（`_entity_models` 登记＝防误判孤儿、`PROVENANCE_CATEGORIES`+`_candidates`、`_purge_versions`/`_purge_plans`、`_summarise_principals` FK 顺序接线）；`test_seed_minimal.py`/`test_purge_demo_data.py` 覆盖。 |
| R-7 | **`activities` 被拉进版本 / 计划维度** | 撕开 `TICKET_ENTITY_TYPES` 隔离，治理 / 工单事件互相泄漏进仪表盘 | §2.2 明确非目标：版本 / 计划变更走结构化日志，不进 `activities`；与 `projects` 删除的既有先例一致。 |
| R-8 | **跨项目挂计划造成层级错乱** | 工单显示在 A 项目，其计划却属 B 项目 | §3.2「同项目不变量」在建 / 改工单写路径强制；无项目工单采纳计划项目；三条错误路径均 400 且文案可操作。 |
| R-9 | **`routes/requirements.py` 逼近 800 行硬顶** | 继续堆逻辑触 CLAUDE.md 二的文件尺寸红线 | §3.6 把版本 / 计划逻辑收敛进新叶子 `services/hierarchy.py`，路由只做「取参→调服务→渲染」。 |
| R-10 | **前端 `FilterBar` 破坏既有调用点** | 需求 / BUG 现有筛选回归 | §5.2 把版本 / 计划筛选做成 `FilterBar` 的**可选**槽，缺省不渲染，既有调用点零改动；typecheck 兜底。 |
| R-11 | **计划删除策略之争（409 守卫 vs 解绑工单）** | 用户期望「删计划顺带把工单变未归属」而被 409 挡住 | 本轮取 409 守卫（与 `projects` 删除先例一致、最不易误删）；若产品反馈更需「解绑式删除」，另加 `?detach=1` 选项，届时把工单 `plan_id` 批量置 NULL 后再删——列为后续项，不在本轮默认行为里。 |

---

## 10. 落地顺序（实施 checklist，建议）

1. **模型层**：`version.py`/`plan.py` + `requirement/bug` 加 `plan_id` + `__init__.py` 两处登记 +
   `schema_sync` 末尾两列 + `seed_record.SEED_ENTITY_TYPES`。跑 `test_schema_sync.py`。
2. **服务层**：`workflow.terminal_statuses` + `hierarchy.py` 全部纯函数 + `lifecycle` 三个守卫 /
   扩 `project_references` + `validation.want_date`。补 `test_hierarchy.py`/`test_lifecycle.py`。
3. **路由层**：`versions.py`/`plans.py` + `routes/__init__` 挂载 + `requirements/bugs/board` 的过滤与
   `plan_id` 写入与序列化富化。补 `test_versions.py`/`test_plans.py`，追加既有工单测试。
4. **seed / tools**：`seed.py` 加两行 + `purge_demo_data.py` 删除顺序。跑 `test_seed_minimal.py`/
   `test_purge_demo_data.py`。此时后端 `pytest -q` 应零失败、用例数 ≥ 基线。
5. **前端数据层**：`types.ts`/`constants.ts`/`api.ts`/`swr-keys.ts` + `useVersions`/`usePlans`/`PlanPicker`。
6. **前端界面层**：`Sidebar` 入口 + `/versions` 页 + 两个 FormModal + `VersionCard`/`PlanRow` +
   需求 / BUG 页与看板与抽屉的筛选 / 徽章 / 选择器。跑 `npm run typecheck`+`npm run build`。
7. 端到端手测 §8.3 验收清单 6 条。

---

## 附：为什么把版本 / 计划**放在项目之下**而非取代项目

需求描述只写了「版本 → 计划 → 需求/BUG」，未提项目。但本仓库的作用域、切换器、`project_id`
列、`project_scope()`（`scope.py:169`）、末任管理员 / 归档等治理都深度绑定 `Project` 这一维度，
且 CLAUDE.md 与 README 反复强调**向后兼容 / additive**。把版本做成项目的**平级或上级**都需要
迁移海量既有语义、破坏契约；而把版本 / 计划**嵌入项目之下**，让四层树 `项目→版本→计划→工单`
自然成立，既满足需求描述的三层关系，又零破坏既有一切。这是唯一与仓库现有架构自洽、且能在
一轮内稳健交付的落点。若未来需要「跨项目共享的版本」，那是一个独立的、更大的建模决策，
应另起一轮评估，不在本轮范围。

---

## 评审结论（Review Verdict · v2）

**结论：有条件通过（Approved with conditions）。**

本设计的**架构判断是对的**：四层树坐落在既有 `Project` 之下、全程 additive、真 FK 只在新表、
工单侧 `plan_id` 不建 FK 走应用层校验、版本 / 计划不接工单状态机、不写 `activities`（避免 stats 泄漏）——
每一条都与仓库现有约定自洽，且逐条 `文件:行号` 断言在复核中**绝大多数精确命中**。可行性、一致性、
规模适配三个维度均达标；**无 P0**。

评审发现 **3 个 P1**（`purge` 机制描述错误且会静默误删登记、版本聚合进度缺数据路径、`released_at`
缺解析原语）与若干 P2，**全部 P1 已在 v2 正文修复**（详见「评审记录」表与 §3.4 / §3.6 / §4.1 / §4.6 /
§4.7 / §5.1 / §5.2 / §6.1 / §6.4 / §7.1 / §8.1 / §9-R6 的 `评审 P*` 标注）。故本设计满足「无 P0 / P1
遗留」的放行门槛，**准予进入实现**。

放行所附**条件**（实现期必须落实，多为 P2 与 P1 修复的落地校验）：

1. **purge 四处改动缺一不可**（P1-A）：尤其 `_entity_models` 登记 version/plan 是最易漏、后果最隐蔽
   的一条——`test_purge_demo_data.py` 必须有一条「版本 / 计划登记不被误判为孤儿」的断言把它钉死。
2. **版本聚合进度走服务端** `version_ticket_counts` 富化（P1-B），前端不得对分页 plans 列表求和；
   `test_versions.py` 覆盖聚合 `done/total` 正确。
3. **`released_at` 服务端托管**（P1-C）：随 `status` 进出 `released` 由后端 stamp / 清空，不接受客户端传值；
   本轮不新增 datetime 请求体原语，`want_date` 仅服务三个 DATE 字段。
4. **登记面全部对齐**（P2-A/B）：`SEED_ENTITY_TYPES` 与 purge `_entity_models` 一一对应；`SEED_VERSION`→`"3"`；
   `seed.py` docstring 同步「10 行」。（注意 `SeedRecord.mark` 并不校验白名单，勿以「会被拒绝」为由自证。）
5. **`next_sort_position` 处理空父 NULL**（P2-E），`VERSION_STATUS_STYLES`/`PLAN_STATUS_STYLES` 用穷尽
   `Record<Status,BadgeStyle>`（P2-H），`services/__init__.py` 无需改动（P2-G）。
6. **`DELETE` 版本 / 计划用 `admin|pm`** 是与 `DELETE /api/projects`（`admin` 独占）的**有意分歧**（P2-F），
   已登记；若实现期认为应对齐为 `admin` 独占，属可接受的收紧，但需在实现说明中标注。
7. 交付前按 CLAUDE.md「质量门禁」以**开工当日** `pytest -q --collect-only` 为基线（文首实测 808/46），
   要求零失败且用例总数不低于基线；前端 `npm run typecheck` + `npm run build` 通过。

以上条件均为**实现细节层面的收口**，不改变本设计的技术路线与范围。满足即视为达成 DoD。
