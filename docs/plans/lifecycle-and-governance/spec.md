# AragonTeam 生命周期闭环与治理安全（Lifecycle & Governance）Spec

> 第 4 轮迭代设计文档 · 版本 v1 · 作者：Solution Architect（Subtask #0）
> 主题一句话：**「建得出来的，也要改得动、撤得回、删得掉、停得住；后端已经有的能力，
> 客户端必须够得着；做错一步，不能没有回头路。」**

---

## 0. 立场：为什么本轮是这一组缺陷

前三轮已经把「点了会报错」这一类问题基本清零：

| 轮次 | 主题 | 已闭合的问题类 |
|---|---|---|
| 1 | reliability-hardening | 坏输入 500→400、SWR 形状不变量、全页错误态、无效 JWT 422→401 |
| 2 | feature-completeness | dev→qa 交接闭环、默认列表序、残余坏输入、offline 语义、全局自动登出 |
| 3 | scale-and-project-scope | 列表分页可达、项目维度端到端、工单页 Agent 闭环、三点式 500 清零、删单串档 |

于是本轮**必须换一个观察角度**才有价值。我以「一个真实团队用这套系统跑一个月」为剧本，
逐条走一遍**资源的完整生命周期**（创建 → 使用 → 修改 → 停用 → 销毁），发现剩下的缺口
根本不是「点了报错」，而是两类**更难受、也更致命**的问题：

1. **做错了没有回头路**——误建的需求删不掉、误指派的 Agent 撤不回、打错字的项目永远
   挂在全局切换器上、离职的成员永远出现在指派下拉里而且还能登录；最极端的一例：
   **系统里唯一的管理员可以把自己降级成普通成员，此后全站再也没有人能创建 / 修改任何账号**，
   只能改数据库救场。
2. **后端有能力，客户端够不着**——`DELETE /api/requirements/:id` 与 `DELETE /api/bugs/:id`
   在后端完整实现（含评论 / 通知 / 审计的级联清理，第 3 轮刚加固过），但
   **整个前端没有任何一个文件调用过 `api.del`**，这两个端点从任何页面都触达不到。

以及一个**元缺陷**：项目至今没有任何迁移机制（`db.create_all()` 对已存在的表**不会**加列），
所以「给 users 加一个 `is_active` 列」这种最普通的演进，在存量 `aragon.db` 上会变成
`OperationalError: no such column`——**每一个请求都 500**。这条不修，上面所有生命周期
能力都不能安全落地。它必须是本轮的第一块砖。

本轮的四个缺陷类（全部经我在真实 Flask 应用上首手复现，证据见 §2 各节）：

| 类 | 级别 | 一句话 |
|---|---|---|
| **A** | P0 | 唯一管理员可自我降级 → 全站账号治理永久失能，产品内无恢复路径 |
| **B** | P0 | 工单不可撤销：删除端点客户端零调用；取消指派**无路径**且 `PATCH` 静默返回 200 |
| **C** | P1 | 项目 / Agent / 成员：建得出来、改不动、删不掉、停不住；且外键约束下裸删必 500 |
| **D** | P1 | 看板端点无任何上限：300 单返 300 张卡，数据一多必然拖垮页面 |
| **E** | P0（前置） | 无迁移：`create_all` 不 ALTER 已有表，本轮任何加列在存量库上必炸 |

---

## 1. Overview（概述）

AragonTeam 是一个「Agent 是一等公民」的研发协作平台。经过三轮加固，它的**正向流程**
已经足够可靠：建单、指派（人或 Agent）、看板流转、Agent 自主认领与推进、通知扇出、
项目作用域、分页检索，都能端到端跑通且不报错。但一个真实可用的协作平台，可靠性只是
及格线；**可维护性**——也就是「用错了能不能改回来」——才是团队敢不敢把真实工作放进来的
分水岭。本轮就补齐这条分水岭：把每一种资源（工单 / 项目 / Agent / 成员 / 指派关系）的
生命周期从「只有创建」补成「创建 → 修改 → 停用 / 归档 → 删除」的完整闭环，并且给每一个
破坏性动作配上**统一的二次确认**、**引用完整性守卫**与**可回溯的审计**。

本轮同时补上一块基础设施：**幂等的启动期加列迁移器**（`services/schema_sync.py`）。
项目今天靠 `db.create_all()` 建表，它只会创建**不存在的表**，对已存在的表**一列都不会加**。
这意味着任何模型演进（本轮要加的 `users.is_active`、`projects.archived_at`）在开发者
本地的存量 `aragon.db` 上都会变成「模型以为有、数据库其实没有」的幽灵列——每一次
`SELECT users.*` 都 500。这不是理论风险：它是本轮工作的**硬前置**，也是本项目未来每一次
schema 演进的硬前置。我们用最保守的方式解决它：只支持 **additive（加列）**，启动时对照
`inspect(engine)` 的实际列集合补齐差额，幂等、可日志、非 SQLite 方言同样安全；改类型 /
删列 / 加约束一律**不**在此机制内，需要时必须显式引入真正的迁移工具（写入 §7 风险表）。

最后是规模化的最后一块拼图：**看板分页**。第 3 轮把需求 / BUG / 通知三个**列表**页接上了
分页条，却把**看板**留在了原地——`GET /api/board/*` 至今没有任何上限。我在真实应用里灌入
300 张需求单，看板一次性返回了全部 300 张卡、82 KB 响应体（对照组：列表端点同样数据只返
200 条并给出 `X-Total-Count: 300`）。一个团队跑三个月就是几千张卡，届时看板页会一次性
渲染几千个可拖拽 DOM 节点。本轮给看板加上**每列上限 + 每列真实总数**，并在列头诚实地写出
「显示 100 / 共 342」以及「在列表中查看全部」的出口——**绝不让 UI 在用户不知情时少给数据**，
这与前三轮确立的「不说谎的 UI」原则一脉相承。

三条**硬不变量**贯穿全文，任何实现都不得违反：

- **G1｜状态机仍是圣域**：本轮不新增任何状态、不改 `services/workflow.py` 的两张邻接表、
  不新增绕过 `can_transition` 的写状态路径。删除 / 停用 / 归档都**不触碰 `status`**。
- **G2｜成功路径响应 shape 只增不改**：既有字段名 / 类型 / 语义一律不动，新增字段一律
  additive。唯一的例外是 §2.7 的「悬挂 assignee 降级」——它只在本轮**新引入**的
  「Agent 被删除」状态下才可能出现，对既有数据零影响，但仍在 §4 显式标注为契约变更。
- **G3｜破坏性动作必须满足三件事**：① 前置引用完整性检查（不靠数据库异常兜底）；
  ② 前端二次确认（统一原语，不各页手搓）；③ 写审计或结构化日志（谁、何时、删了什么）。

---

## 2. Technical Design（技术设计）

### 2.1 架构 Delta（本轮新增的接缝）

```
backend/
  app.py                     ← 建表后调用 schema_sync（新接缝①）
  errors.py                  ← 注册 jwt.token_in_blocklist_loader（新接缝②）
  services/
    schema_sync.py   【新】  加列迁移器（additive-only，幂等）
    lifecycle.py     【新】  删除 / 停用的引用守卫 + 统一 409 契约
    board_page.py    【新】  看板每列分页（列上限 + 列总数）
  routes/
    users.py                 ← 末任管理员不变量 + 停用 / 启用
    projects.py              ← PATCH / DELETE / 归档
    agents.py                ← DELETE
    requirements.py|bugs.py  ← assign 支持显式取消指派
    board.py                 ← 接 board_page
  models/
    user.py                  ← +is_active
    project.py               ← +archived_at
    requirement.py           ← _resolve_assignee 悬挂降级（bug.py 共用）

frontend/
  components/ui/ConfirmDialog.tsx  【新】 全站统一破坏性二次确认
  components/admin/ProjectFormModal.tsx ← 建 / 改两态
  components/TicketDrawer.tsx      ← 危险区「删除工单」+ 取消指派真正生效
  components/kanban/KanbanColumn.tsx ← 列头「显示 x / 共 y」+ 查看全部
  app/(app)/projects/page.tsx      ← 行操作：编辑 / 归档 / 删除
  app/(app)/team/page.tsx          ← 行操作：停用 / 启用 + 已停用标注
  app/(app)/agents/page.tsx        ← 卡片操作：删除
```

**接缝原则**：所有新逻辑都收敛到 `services/` 下的三个新模块，路由层只做「取参 → 调服务 →
渲染契约」。禁止在路由里内联第二份引用检查或第二份分页算法（第 3 轮 `_next_position` 被
内联成两份、必须「两处同步修改」的教训，见 `agent_runner.py:68` 的注释）。

---

### 2.2 缺陷 A（P0）：唯一管理员可自我降级 → 全站治理永久失能

#### 复现（首手，真实应用 + 真实 JWT）

```text
POST /api/auth/login   (admin)                        -> 200
PATCH /api/users/1  {"role": "member"}                -> 200   ← 唯一管理员把自己降级
POST  /api/users    {"username":"z","password":"y"}   -> 403   ← 从此谁都建不了账号
```

`backend/routes/users.py:77-79` 无条件接受任何合法角色值：

```python
if "role" in data:
    user.role = want_str(data, "role", required=True, choices=ROLES)
```

`POST /api/users`、`POST /api/auth/register`、`PATCH /api/users/:id` 全部是
`@require_role("admin")`（`routes/users.py:35,70`、`routes/auth.py:55`）。一旦库里
admin 数归零，**这三个端点同时且永久地失去唯一的合法调用者**——产品内没有任何恢复路径，
只能进 SQLite 手改。这是一次点击造成的不可逆治理死锁，定级 P0。

#### 设计

在 `routes/users.py` 引入**末任管理员不变量**，并把它做成一个**可复用的守卫函数**——
因为本轮还要加「停用成员」，停用最后一个管理员是同一个死锁的另一张脸：

```python
# backend/services/lifecycle.py
def would_orphan_admins(target_user, *, new_role=None, new_active=None) -> bool:
    """本次变更是否会让系统里**有效管理员**（role=admin 且 is_active）数量归零。

    有效管理员 = 能真正调用 @require_role("admin") 端点的人。停用的 admin 不算数
    （其 token 已被 blocklist 拒绝，见 §2.5），故停用最后一个 admin 与降级最后一个
    admin 是同一个死锁，必须由同一个判据拦住。

    Args:
        target_user: 被改动的用户。
        new_role: 变更后的角色；None 表示本次不改角色。
        new_active: 变更后的启用状态；None 表示本次不改。

    Returns:
        True 表示该变更会造成治理死锁，调用方应返回 409。
    """
```

判定逻辑（不做「统计后减一」的近似，直接算变更后的集合基数，避免边界错算）：

```python
still_admin = (new_role or target_user.role) == "admin"
still_active = target_user.is_active if new_active is None else new_active
if still_admin and still_active:
    return False                      # 目标本人变更后仍是有效管理员 → 不可能归零
others = User.query.filter(
    User.role == "admin", User.is_active.is_(True), User.id != target_user.id
).count()
return others == 0
```

命中后返回稳定的 409 契约（**不是 400**：请求本身合法，是系统状态不允许）：

```json
{
  "error": "cannot remove the last administrator",
  "detail": {
    "reason": "at least one active admin must remain",
    "active_admins": 1
  }
}
```

接入点（两处，共用同一守卫）：

- `routes/users.py::patch_user`——处理 `role` 与 `is_active` **之前**统一判定一次。
- 未来任何「删除用户」的实现同理（本轮不做删除，见 §2.5 的取舍）。

**同时收紧一处更隐蔽的自伤**：允许 admin 停用**自己**（`target_user.id == current_user().id`）
在判据上是合法的（只要还有别的 admin），但会立刻把自己登出。这属于「用户明确表达的意图」，
不禁止，但前端必须在确认框里明说「你将立即退出登录」（§2.9）。

---

### 2.3 缺陷 E（P0 · 前置）：`create_all` 不加列 —— `schema_sync` 加列迁移器

#### 问题

`backend/app.py:86` 是全部的「建表」逻辑：

```python
db.create_all()
```

`create_all()` 的语义是「**创建不存在的表**」；对已存在的表，即使模型新增了列，它
**一列都不会加，也不会报错**。本项目没有 Alembic、没有任何 migration 目录
（`git ls-files` 下无 `migrations/`），`README.md` 也只写「首次启动自动建表」。
后果：开发者本地 / 任何已运行过的部署上，`backend/aragon.db` 的 `users` 表永远是
旧列集合，而模型层新增的 `is_active` 会出现在**每一条** `SELECT users.*` 的列清单里 →
`sqlite3.OperationalError: no such column: users.is_active` → 经 `errors.py:46` 的兜底
处理器变成 500。**登录都进不去。**

这不是「本轮引入的新风险」，而是**本轮才第一次撞上的既有地雷**——项目至今没加过列。
它必须先修，否则 §2.5 / §2.6 的列一加，存量库全线报废。

#### 设计：`backend/services/schema_sync.py`

```python
"""启动期 additive schema 同步（本轮新增）。

`db.create_all()` 只建**不存在的表**，对已存在的表不加任何列。项目无 Alembic，
因此模型每新增一列，存量 aragon.db 上的每一次查询都会 `no such column` → 500。
本模块以最保守的方式补上这条缝：**只做加列**，幂等，可重复执行，且不依赖
任何新第三方依赖（inspect 来自 SQLAlchemy 本体）。

**能力边界（务必遵守）**：只支持 ADD COLUMN。改类型 / 改约束 / 删列 / 改表名 /
数据回填一律**不在**本机制内——它们需要真正的迁移工具（Alembic）与人工审阅，
擅自扩展本模块会制造「看起来有迁移、其实静默错数据」的更坏局面（见 spec §7 R-3）。
"""
from sqlalchemy import inspect, text

# (表名, 列名, DDL 片段)。DDL 只允许使用 SQLite 与 PostgreSQL 双方言都接受的
# 保守类型 + 常量默认值：SQLite 的 ADD COLUMN 要求默认值是常量（非表达式）。
ADDITIVE_COLUMNS: list[tuple[str, str, str]] = [
    ("users", "is_active", "BOOLEAN NOT NULL DEFAULT 1"),
    ("projects", "archived_at", "DATETIME"),
]


def sync_additive_columns(engine) -> list[str]:
    """补齐 ADDITIVE_COLUMNS 中缺失的列，返回实际执行的 "表.列" 列表（供日志）。

    - 表不存在 → 跳过（create_all 会建全新表，无需补列）。
    - 列已存在 → 跳过（幂等：正常启动恒返回 []）。
    - 每条 ALTER 各自执行；任一条失败**向上抛出**，绝不吞掉——一个补不上的列
      会让整个应用处于「模型与库不一致」的状态，宁可启动失败也不能带病运行
      （CLAUDE.md 五：错误显式传播）。
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    # 【实现要点】先把每张表的现有列集合一次性快照下来，循环里只读快照、改快照。
    # SQLAlchemy 的 Inspector 带 info_cache，DDL 之后同一实例的 get_columns 可能返回
    # 陈旧结果；且同一张表若在清单里有两列待补，第二次读也不该再打一次库。
    snapshot: dict[str, set[str]] = {
        t: {c["name"] for c in inspector.get_columns(t)} for t in existing_tables
    }
    applied: list[str] = []
    with engine.begin() as conn:
        for table, column, ddl in ADDITIVE_COLUMNS:
            if table not in snapshot or column in snapshot[table]:
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            snapshot[table].add(column)
            applied.append(f"{table}.{column}")
    return applied
```

**已首手验证**（SQLAlchemy 2.0.31 / SQLite）：`ALTER TABLE users ADD COLUMN is_active
BOOLEAN NOT NULL DEFAULT 1` 与 `ADD COLUMN archived_at DATETIME` 均成功；执行后
`inspect(engine).get_columns('users')` 可见新列，且**存量行的 `is_active` 自动为 1**
（不会有人被静默锁在门外，与 §5.2 的承诺一致）。

接入 `backend/app.py`（**必须在 `db.create_all()` 之后**——新库由 `create_all` 一次建全，
`sync` 随即变成零 DDL 的 no-op；存量库则由 `sync` 补差额）：

```python
        db.create_all()
        # 【lifecycle-and-governance §2.3】create_all 不给已存在的表加列；存量
        # aragon.db 缺少本轮新增的列时，每一次查询都会 no such column → 500。
        applied = schema_sync.sync_additive_columns(db.engine)
        if applied:
            app.logger.info("schema_sync applied: %s", ", ".join(applied))
        if app.config.get("SEED_ON_STARTUP", True):
            seed_if_empty()
```

#### 为什么不引 Alembic

引 Alembic 会新增运行时依赖 + `migrations/` 目录 + 「谁来跑 `upgrade head`」的运维流程，
对一个「首次启动自动建表、开箱即用」的单机 MVP 是明显的过度设计，且与前三轮
「零新依赖」的一贯取舍冲突。本模块 40 行、零依赖、能力边界写死在 docstring 里，
是当前阶段的正确刻度。**何时必须换成 Alembic**：出现第一个「改类型 / 改约束 / 需要数据
回填」的需求时——这条判据写进 §7 风险表，避免本模块被后人无声地扩权。

---

### 2.4 缺陷 B（P0）：工单不可撤销

#### B1 复现：删除端点存在，但客户端零调用

后端两个端点完整存在且已被加固（`routes/requirements.py:275-294`，bugs 同构）：
删除工单时级联清理其评论、通知、审计，并解除转出 BUG 的 `related_requirement_id`。

前端：

```text
$ grep -rn "api\.del|method:\s*\"DELETE\"" frontend/   （排除 node_modules/.next）
frontend/lib/api.ts:121:  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
```

**只有定义，没有任何一处调用。** 需求列表页、BUG 列表页、两个看板页、工单抽屉——
没有任何一个界面提供删除入口。用户误建一张单（或 Agent 自主认领后发现是重复单），
它就永久留在列表、看板、`/stats` 计数与「我的工作」里。

#### B2 复现：取消指派**无路径**，且 `PATCH` 静默说谎

```text
PATCH /api/requirements/1/assign  {"assignee_type": null, "assignee_id": null}
  -> 400 {"error":"invalid assignee_type","detail":{"allowed":["user","agent"]}}

PATCH /api/requirements/1         {"assignee_type": null, "assignee_id": null}
  -> 200  且 assignee 仍是 {"type":"agent","id":1,"name":"dev-agent"}   ← 静默无效
```

`routes/requirements.py::_validate_assignee`（第 103 行）对 `None` 一律 400；
`patch_requirement`（第 256-266 行）的白名单里**根本没有** assignee 字段，
于是传了也不生效，却照样返回 200 + 完整工单体——用户看到「保存成功」，数据纹丝不动。

更糟的是 UI 层：`components/AssigneePicker.tsx:47` 渲染了一个 `<option value="">未指派</option>`，
但它的两个消费者都拒绝执行——`TicketDrawer.tsx:161-164` 弹一句「暂不支持在此取消指派」，
`hooks/useTicket.ts:63` 直接 `return` 静默吞掉。**一个被渲染出来、点了必然无效的死控件**，
正是前三轮反复清理的「会说谎的 UI」的又一例。

#### 设计 B2：`assign` 支持显式取消指派

对 `PATCH /api/{requirements|bugs}/:id/assign` 做**严格向后兼容**的扩展：

```python
# routes/requirements.py::assign_requirement（bugs 同构，_validate_assignee 共用）
data = json_body()
assignee_type = data.get("assignee_type")
assignee_id = data.get("assignee_id")

# 【§2.4-B2】显式取消指派：assignee_type 为 JSON null 即「置为未指派」。
# 判据必须是 `is None`，不能用 falsy——空串 "" 是**非法类型**，仍应 400，
# 二者语义不同（前者是用户明确的「清空」，后者是坏输入）。
if assignee_type is None and "assignee_type" in data:
    return _unassign(req, "requirement")
```

`_unassign` 的语义（收敛到 `services/lifecycle.py::unassign_ticket`，两个蓝图共用）：

- 置 `assignee_type = None`、`assignee_id = None`（与 `models/requirement.py:10` 的
  「未指派以列为 NULL 表达」注释一致，**不引入 `'null'` 字面量**）。
- **绝不触碰 `status` 与 `position`**（G1）。工单停在 `assigned` 而无 assignee 是合法的
  中间态——它正是「等待重新分诊」，且 `agent_autopilot.AGENT_CLAIMABLE` 只认领
  `new`/`open`，不会误抢（`agent_autopilot.py:34-38`），故不制造新的认领竞争。
- 写审计：`Activity.log(entity, id, "unassigned", actor=_actor(), from_status=s,
  to_status=s, message="取消了指派")`。`unassigned` 是**新的 action 值**，
  前端 `lib/constants.ts::actionLabel` 必须同步补一条中文映射，否则时间线显示英文原文。
- 通知：向**原人类 assignee**（若是人）发一条 `assigned` 类型通知，文案
  「你不再负责{需求|BUG}「…」」。原 assignee 是 Agent → 不发（与
  `services/notifications.py:82` 的既有策略一致）。
- 权限：与 assign 同为 `@require_role("admin", "pm")`，**不放宽**。
- 幂等：本就未指派时同样返 200，但不写审计、不发通知（避免时间线被无意义事件刷屏）。

前端随之收口：`useTicket.ts::assign` 去掉 `if (!value.assignee_type ... ) return` 的静默
吞噬，改为把 `{assignee_type: null, assignee_id: null}` 原样发出；`TicketDrawer.tsx`
删掉「暂不支持」的 toast 分支。**「未指派」这个选项从此真的能用。**

#### 设计 B1：前端接上删除

后端**零改动**（端点与级联已就绪，权限为 `@require_role("admin","pm")`）。

前端新增两处入口，两处都走 §2.9 的统一确认原语：

1. **工单抽屉底部危险区**（主入口，`components/TicketDrawer.tsx`）：仅 `canAssign`
   （= pm/admin，与后端 `@require_role("admin","pm")` 同判据）可见的一行
   「删除此{需求|BUG}」文字按钮，点击弹 `ConfirmDialog`，确认文案必须写清**级联范围**：
   「将同时删除它的 N 条评论与全部协作时间线，且不可恢复」。
2. **看板卡片 / 列表行不提供删除**——刻意为之。破坏性操作放在「已经打开、已经读过内容」
   的抽屉里，比放在一列卡片上安全得多；列表行上的删除按钮与「指派」按钮相邻，误触代价
   不对等（第 3 轮已经因为触屏误触把「转 BUG」用 `pointer-events` 屏蔽过一次）。

删除成功后的收尾（三件事缺一不可，否则页面会「删了还在」）：

```ts
await api.del(`/${entity}/${id}`);
toast.success("已删除");
onClose();                 // 抽屉必须关闭：其 SWR key 已 404
onChanged?.();             // 外层列表 / 看板 mutate
```

另外 `TicketDrawer` 的 `onChanged` 在各调用点只做了 `mutate()` 单个 key。删除会同时影响
仪表盘统计与「我的工作」，因此本轮把删除后的失效改为**前缀函数式失效**（复用
`app/(app)/agents/page.tsx:60-70` 已验证的 `revalidateAll` 写法，提取到
`lib/swr-keys.ts::invalidateTicketViews()` 供三处共用，**不再各页手抄一份**）。

---

### 2.5 缺陷 C1（P1）：成员停用 / 启用 + 令牌即时失效

#### 现状

`GET /api/users` 只有 list / create / get / patch（`routes/users.py`），**没有删除，
也没有任何「离职 / 停用」概念**。后果：

- 离职成员永远出现在 `AssigneePicker` 的「团队成员」分组里，随时可能被误指派；
- 他的账号**永远可以登录**——密码没换过，JWT 默认 24h 有效期（`config.py:34`），
  但他随时可以再登一次拿新 token；
- `/stats.members` 永远把他计入团队规模。

为什么**不做「删除用户」**：`users.id` 被 `requirements.reporter_id`、`bugs.reporter_id`、
`projects.owner_id` 三处真外键引用，且 `extensions.py:17-30` 已开启
`PRAGMA foreign_keys=ON`。我首手验证过裸删的下场：

```text
db.session.delete(user); db.session.commit()
-> IntegrityError: (sqlite3.IntegrityError) FOREIGN KEY constraint failed
   [SQL: DELETE FROM users WHERE users.id = ?]
```

要「删干净」就必须把该用户提过的所有单的 `reporter_id` 置 NULL——那等于**销毁审计**，
与本平台「记录人 / Agent 混合协作完整轨迹」的核心价值主张（`README.md:5`）直接冲突。
**停用是唯一正确的产品答案**，删除刻意不做（写入 §8）。

#### 设计

**数据模型**：`users` 加一列（经 §2.3 的 `schema_sync` 落地）

```python
# backend/models/user.py
# 停用而非删除：users.id 被 requirements/bugs.reporter_id 与 projects.owner_id
# 真外键引用，硬删会 IntegrityError；且删除等于销毁审计轨迹。停用保留全部历史，
# 只切断「能登录」与「能被指派」两种**面向未来**的能力。
is_active = db.Column(db.Boolean, nullable=False, default=True, server_default="1")
```

`to_dict()` **additive** 增加 `"is_active": self.is_active`；`summary()` 也加，
因为指派头像与时间线需要据此打「已停用」标记（`summary()` 是 shape 变更，见 §4 契约表）。

**接口**：不新增端点，扩展既有 `PATCH /api/users/:id`（admin）：

```python
if "is_active" in data:
    active = want_bool(data, "is_active", required=True)     # 非 bool / null → 400
    if lifecycle.would_orphan_admins(user, new_active=active):
        return lifecycle.conflict_last_admin()
    user.is_active = active
```

`want_bool` 已存在于 `services/validation.py:111`，但**当前签名是
`want_bool(data, key, *, default=False)`，没有 `required` 形参**——直接按上面的写法调用会
`TypeError`。因此本轮需要给它补一个 `required` 形参（**additive、默认 `False`、
既有两个调用点行为逐字节不变**），与同模块 `want_str` / `want_int` 的约定对齐：

```python
def want_bool(data: dict, key: str, *, required: bool = False,
              default: bool = False) -> bool:
    v = data.get(key, None)
    if v is None:
        if required:
            # 【lifecycle-and-governance §2.5】显式传 null 时必须 400 而非静默取 default：
            # `{"is_active": null}` 若回落成 False，会**把一个用户悄悄停用**。
            raise ValidationError(f"{key} is required", field=key, expected="boolean")
        return default
    ...
```

这是**唯一**需要改动 `validation.py` 的地方，且必须补一条针对性用例
（`want_bool_required_rejects_null`），否则「传 null 静默停用」就是本轮自己制造的新缺陷。

**令牌即时失效**（关键——只改数据库标志而不管已签发 token，等于停用形同虚设）：
利用 `flask_jwt_extended` 为吊销场景准备的钩子，在 `errors.py::register_error_handlers`
里注册（该文件已经注册了 `revoked_token_loader`，第 75-77 行，无需新增错误契约）：

```python
    @jwt.token_in_blocklist_loader
    def _is_revoked(jwt_header, jwt_payload):
        """已停用 / 已不存在的用户，其既有 token 立即失效（§2.5）。

        选这个钩子而不是 before_request：它由 jwt_required() 内部调用，天然只作用于
        受保护端点，不会误伤 /api/health 与 /api/auth/login；也不必在 53 个路由上
        各加一次守卫（漏一个就是一个后门）。
        """
        sub = jwt_payload.get("sub")
        try:
            uid = int(sub)
        except (TypeError, ValueError):
            return True
        user = db.session.get(User, uid)
        return user is None or not user.is_active
```

**已首手验证**（flask-jwt-extended 4.6.0，在真实应用上跑通）：把某 uid 加入拒绝集合后，
`GET /api/auth/me` 与 `GET /api/requirements` 立即返回 **401 `{"error":"token revoked"}`**，
而 `GET /api/health` 仍 200、`POST /api/auth/login` 仍可达——**受保护端点全覆盖、公开端点零误伤**，
且**一行路由代码都不用改**。这正是选它而不是 `before_request` 或逐路由守卫的原因。

并把既有 `_revoked_token` 的文案改为对用户有意义的一句：
`{"error": "account is disabled or removed"}`，仍是 **401**——前端 `lib/api.ts:55`
的 `signalUnauthorizedIfNeeded` 会据 401 清 token 并广播 `aragon:unauthorized`，
被停用的用户**下一次任何请求就会被自动登出**，无需额外前端改动。

**登录侧**：`routes/auth.py::login` 在密码校验通过后加一道门：

```python
    if not user.is_active:
        # 与「密码错误」区分：这是明确的管理动作，用户需要知道去找谁。
        # 不计入限流失败（不是猜密码），也不泄露更多信息。
        return jsonify({"error": "account is disabled, contact an administrator"}), 403
```

选 **403 而非 401**：401 会触发前端的自动登出流程（此时用户本就未登录，行为无意义），
403 会被登录页当作普通错误直接展示文案。**注意**：`lib/api.ts:56` 的自动登出对
`/auth/` 路径本就豁免，两种码都不会误触发，选 403 纯粹是语义更准。

**被停用者的既有工单**：**一律不动**。不自动改派、不清空 assignee——那是静默篡改数据。
产品答案是「看得见」：`_resolve_assignee` 返回的 `summary()` 带上 `is_active`，前端在
头像旁渲染灰色「已停用」小字，pm 自己决定是否改派。

**通知**：`services/notifications.py::notify()` 增加一条跳过条件——收件人已停用则不落库
（与既有的「不给自己发」「偏好静音」并列，第 46-54 行同一处），避免给一个再也不会登录的
账号堆积通知。

**指派选择器**：`AssigneePicker` 过滤掉 `is_active === false` 的成员；但**若当前工单的
assignee 正是一个已停用成员，仍需把他保留在选项里**，否则 `<select>` 的 value 匹配不到
任何 option，浏览器会静默显示成第一项——UI 会显示成「未指派」，又是一次说谎。

---

### 2.6 缺陷 C2（P1）：项目改名 / 归档 / 删除

#### 现状

`routes/projects.py` 只有 list / create / get（`app.url_map` 首手枚举确认，无 PATCH / DELETE）。
`app/(app)/projects/page.tsx:4` 的注释坦承：「后端仅提供 list/create，本页只做列表 + 新建；
编辑 / 删除按 §8 交棒未来，不放假按钮」——是当时正确的克制，本轮就是那个「未来」。

代价是具体的：项目 `key` 打错一个字母（`ARGA` 而非 `ARAG`）就**永久**印在每一张卡片旁；
一个试建的项目会永远占据 Header 全局切换器的一个位置；`owner` 离职也换不掉。

#### 设计

**归档优于删除**（与 §2.5 同一取舍逻辑）：项目一旦有工单挂靠，删除就意味着要么违反外键、
要么把工单的 `project_id` 悄悄置 NULL（错数据 + 丢归属）。所以：

- **`PATCH /api/projects/:id`**（`@require_role("admin","pm")`）：`name` / `key` /
  `description` / `owner_id` / `archived`。
  - `key` 改动须做**唯一性检查**（排除自身），冲突 409，与 `create_project` 的
    `routes/projects.py:38-39` 同契约；`key` 统一 `.upper()`，与创建路径一致。
  - `owner_id` 传 `null` 即清空；传整数须经 `want_int` + 存在性校验（复用
    `_validate_project` 的同款写法，避免第四份手搓校验）。
  - `archived` 是 **bool 语义参数**，映射到 `archived_at`（`True` → `utcnow()`，
    `False` → `None`）。对外只暴露 bool，不让客户端写时间戳。
- **`DELETE /api/projects/:id`**（`@require_role("admin")`——比 PATCH 更严，删项目是
  比建项目危险得多的动作）：**先查引用，再删**：

```python
refs = lifecycle.project_references(project_id)   # {"requirements": n, "bugs": m}
if refs["requirements"] or refs["bugs"]:
    return jsonify({
        "error": "project still has tickets",
        "detail": {**refs, "hint": "archive the project instead, or move its tickets"},
    }), 409
```

**绝不依赖外键异常兜底**：`IntegrityError` 会被 `errors.py:46` 的兜底处理器变成 500，
用户看到「internal server error」而不是「这个项目还有 12 张单」。前置检查是唯一
能给出可操作信息的做法（CLAUDE.md 五：错误信息必须包含定位线索）。

**归档语义**（三条，必须逐条实现，否则归档只是个装饰性标志）：

| 面 | 归档后的行为 |
|---|---|
| `GET /api/projects` | **默认只返回未归档**；`?include_archived=1` 才全返（**这是既有默认响应的语义变更**，见 §4） |
| 建单表单 / 全局切换器 | 归档项目不出现在可选项里（自然由上一条达成，零前端特判） |
| 既有工单 / `?project_id=<归档id>` | **完全不受影响**——仍可查询、仍可流转。归档只切断「未来把新东西放进去」 |

**边界自愈**：`lib/project-scope.tsx` 已有「作用域失效自愈」逻辑（第 3 轮引入）。当前
作用域项目被归档 / 删除后，切换器读不到它 → 必须回落到「全部项目」并给一次 toast
提示，而不是把 UI 卡在一个不存在的作用域上。这条要在实现时对照现有自愈代码确认覆盖。

---

### 2.7 缺陷 C3（P1）：Agent 删除 + 悬挂 assignee 的诚实降级

#### 现状

`routes/agents.py` 有 create / patch，**没有 delete**。一个试建的 Agent 会：
永远出现在 `AssigneePicker` 的「Agent」分组、永远出现在 Agents 页、并且
**每一次「▶ 运行 AI 团队一轮」都会对它跑一遍 tick**（`routes/agents.py:130` 遍历全部
Agent）——在配了真实 LLM 的部署上，这是实打实的 token 与墙钟成本。

#### 设计

**`DELETE /api/agents/:id`**（`@require_role("admin","pm")`，与 create/patch 同级）：

```python
load = lifecycle.agent_open_workload(agent_id)   # 未终态工单计数
if load["requirements"] or load["bugs"]:
    return jsonify({
        "error": "agent still holds open tickets",
        "detail": {**load, "hint": "reassign or unassign them first"},
    }), 409
```

「未终态」判据必须复用 `workflow.is_terminal`，**不得内联一份状态清单**——那正是会
随邻接表漂移的第二真相。实现为：

```python
def agent_open_workload(agent_id: int) -> dict:
    """该 Agent 名下**未终态**的在手工单计数（terminal 单不阻止删除）。"""
    out = {}
    for entity, model in (("requirements", Requirement), ("bugs", Bug)):
        rows = model.query.filter_by(assignee_type="agent", assignee_id=agent_id).all()
        key = "requirement" if entity == "requirements" else "bug"
        out[entity] = sum(1 for r in rows if not workflow.is_terminal(key, r.status))
    return out
```

**删除后的悬挂引用**——这是本节真正值得设计的部分。Agent 被删后：

- **评论 / 时间线**：`models/comment.py::_resolve_author`（第 59-63 行）**已经**优雅降级为
  `{"type":"agent","id":…,"name":"(已删除)"}`。零改动，历史可读性保住。
- **工单 assignee**：`models/requirement.py::_resolve_assignee`（第 57-72 行）对找不到的
  目标返回 **`None`**。于是 `to_dict()` 会给出 `assignee_type: "agent"`、`assignee_id: 7`、
  **`assignee: null`**——前端 `TicketDrawer.tsx:360` 与列表页 `r.assignee ? … : "未指派"`
  会把它显示成**「未指派」**。一张明明还挂着 `assignee_id=7` 的单，UI 说它没人负责。
  这正是本轮要消灭的那类谎话。

  **修复**：让 `_resolve_assignee` 与 `_resolve_author` 对齐——目标不存在时返回占位而非
  `None`（**只有「从未指派」才返回 `None`**）：

```python
def _resolve_assignee(assignee_type, assignee_id):
    if not assignee_type or assignee_id is None:
        return None                      # 真·未指派：语义不变
    if assignee_type == "user":
        u = db.session.get(User, assignee_id)
        return u.summary() if u else _deleted_summary("user", assignee_id)
    if assignee_type == "agent":
        a = db.session.get(Agent, assignee_id)
        return a.summary() if a else _deleted_summary("agent", assignee_id)
    return _deleted_summary(assignee_type, assignee_id)


def _deleted_summary(kind, ident) -> dict:
    """指向已删除目标的多态 assignee 占位（与 comment._resolve_author 同策略）。

    返回占位而非 None 是**有意的契约变更**：None 会被前端渲染成「未指派」，
    而这张单其实**有** assignee_id——UI 会说谎（spec §2.7）。
    """
    return {"type": kind, "id": ident, "name": "(已删除)", "deleted": True}
```

  这是本轮**唯一**的成功路径 shape 变更，且只在「目标已删除」这一本轮新引入的状态下
  才会出现（今天 `_validate_assignee` 保证指派时目标必存在，且用户 / Agent 都删不掉，
  故存量数据零命中）。§4 显式标注。

**前端**：Agents 页每张卡在 pm/admin 的操作行末尾加「删除」（`variant="danger"`），
走 §2.9 的 `ConfirmDialog`；409 的 `detail` 里的计数要**渲染进提示文案**
（「dev-agent 还有 3 个需求、1 个 BUG 在手，请先改派」），而不是把后端英文原样 toast。

---

### 2.8 缺陷 D（P1）：看板端点无上限

#### 复现（首手）

```text
灌入 300 张 status=new 的需求单：
GET /api/board/requirements  -> 200，返回 300 张卡，响应体 82 291 字节（无任何上限）
GET /api/requirements?limit=200 -> 200，返回 200 条，X-Total-Count: 300（有上限）
```

`routes/board.py::_grouped`（第 17-29 行）是 `.all()` 后在 Python 里分桶，**没有 limit**。
第 3 轮给三个列表页接上了分页条，看板被完整地留在了原地。

#### 设计

新增 `backend/services/board_page.py`，把「每列取前 N + 该列真实总数」收敛为一个函数：

```python
DEFAULT_COLUMN_LIMIT = 100
MAX_COLUMN_LIMIT = 500


def column_page(model, entity, scope, column_limit: int):
    """按 workflow 列分组，每列最多取 column_limit 张卡，并给出该列真实总数。

    以「每列一次带 LIMIT 的查询 + 一次 COUNT」实现（列数固定为 5~7，查询次数有界），
    而不是取回全表再切片——后者的内存与序列化成本正是本节要消灭的问题。
    """
```

响应 shape **additive**（既有 `key/title/items` 一字不改，新增两个字段）：

```json
{"columns": [
  {"key": "new", "title": "新建", "items": [...], "total": 342, "truncated": true}
]}
```

`?column_limit=` 走 `services/scope.py::want_query_int`（`minimum=1, maximum=500,
clamp=True`），与第 3 轮确立的三点式查询串收口一致——**不新写第四份整型解析**。

**前端**：`components/kanban/KanbanColumn.tsx` 的列头在 `truncated` 为真时渲染
「显示 100 / 共 342」+ 一个「查看全部」链接，跳到对应列表页并预置 `?status=<key>`
筛选（列表页已有 status 过滤条与分页条，天然承接）。`truncated` 为假时**不渲染任何
额外元素**——小库观感零变化，与第 3 轮分页条的处理方式一致。

**与拖拽的相互作用**（必须写清，否则实现者会踩）：拖拽落点索引由
`_reindex_column` 基于**数据库里该列的全部卡**重编号（`routes/requirements.py:71-92`），
与前端只看到前 100 张**并不冲突**——前端传的 `position` 是它可见范围内的索引，落到
被截断的列时可能与用户直觉略有偏差。本轮**接受**这一偏差并在列头标注「仅显示前 100 张，
排序以完整列为准」，**不**改动 `_reindex_column`（它是 G1 之外的第二条高风险区域，
第 3 轮刚为它做过项目隔离的修正，不宜连续两轮改写）。

---

### 2.9 前端：统一破坏性确认原语 `ConfirmDialog`

本轮一次性引入 4 个破坏性动作（删工单 / 删项目 / 删 Agent / 停用成员），而全站**至今
没有任何二次确认原语**——`components/ui/Modal.tsx` 是通用容器，没有「危险确认」语义。
如果四处各写一遍，必然出现文案风格、按钮顺序、加载态、错误处理各不相同的四份实现。

`components/ui/ConfirmDialog.tsx`（基于既有 `Modal` 组合，不重造遮罩 / 焦点管理）：

```tsx
interface ConfirmDialogProps {
  open: boolean;
  title: string;
  /** 必须说清后果与范围，例如「将同时删除 12 条评论与全部协作时间线」。 */
  description: React.ReactNode;
  confirmLabel?: string;      // 默认「确认删除」
  danger?: boolean;           // 默认 true → 红色确认按钮
  /** 高危动作要求用户键入该文本才解锁确认按钮（删项目用项目 key）。 */
  requireTypedConfirmation?: string;
  onConfirm: () => Promise<void>;
  onClose: () => void;
}
```

约定（四处调用点一律遵守）：

- 确认按钮在**右**、取消在左；确认按钮在 `onConfirm` pending 期间禁用并显示「处理中…」，
  杜绝双击造成的重复 DELETE（第二次必然 404，用户会看到一个莫名其妙的错误）。
- `onConfirm` 抛错时**不关闭对话框**，在对话框内就地显示错误文案——这正是 409
  （「还有 12 张单」）需要被读到的地方，弹一个转瞬即逝的 toast 然后关窗是最差解。
- Esc / 遮罩点击在 pending 期间**不生效**。
- `requireTypedConfirmation` 只用于「删项目」（键入项目 `key`）——删单 / 删 Agent /
  停用成员都是可挽回或影响有限的动作，强制键入是过度摩擦。

---

### 2.10 P2 收口（低风险、随手补齐）

| # | 位置 | 问题 | 处理 |
|---|---|---|---|
| P2-1 | `routes/requirements.py:581`（bugs 同构） | `/activities` 端点无分页，单工单活动多时全量返回 | 接 `paginate()` + `X-Total-Count`（响应体仍是裸数组，契约不变） |
| P2-2 | `services/notifications.py:103` | `notify_comment` 每次评论都全量取回该单历史评论以求收件人集合 | 改为只 `SELECT DISTINCT author_id`（去掉 body 的搬运），单查询同语义 |
| P2-3 | `routes/requirements.py:44` / `agent_runner.py:68` | `_next_position` 取回整列行再 Python 求 max | 改为 `func.max(model.position)` 单聚合查询；**两处必须同改**（既有注释已警示） |
| P2-4 | `lib/constants.ts::actionLabel` | 新 action `unassigned` 无中文映射 | 补映射；顺带补 `deleted` 等未来值的中性兜底 |
| P2-5 | `routes/users.py::patch_user` | 无字段被识别时仍返 200 + 完整用户体，用户以为改了 | 与 `patch_requirement` 的 `changed` 模式对齐：无有效字段 → 400 `{"error":"no updatable field"}` |

P2-5 与 §2.4-B2 是同一类问题的两个实例（「静默成功」），一并收口才算干净。

---

## 3. File / Module Change Plan（文件与模块变更计划）

### 3.1 Backend —— 新建 3 个 / 修改 15 个

| 文件 | 新建/修改 | 一句话意图 |
|---|---|---|
| `backend/services/schema_sync.py` | **新建** | additive-only 幂等加列迁移器 + `ADDITIVE_COLUMNS` 清单（§2.3） |
| `backend/services/lifecycle.py` | **新建** | `would_orphan_admins` / `project_references` / `agent_open_workload` / `unassign_ticket` / 统一 409 构造器（§2.2/2.4/2.6/2.7） |
| `backend/services/board_page.py` | **新建** | 看板每列分页：`column_page()` + 列上限常量（§2.8） |
| `backend/app.py` | 修改 | `create_all()` 之后调用 `schema_sync.sync_additive_columns` 并记日志（§2.3） |
| `backend/errors.py` | 修改 | 注册 `jwt.token_in_blocklist_loader`；`revoked_token_loader` 文案改为账号停用语义（§2.5） |
| `backend/models/user.py` | 修改 | `+is_active` 列；`to_dict()` / `summary()` additive 暴露之（§2.5） |
| `backend/models/project.py` | 修改 | `+archived_at` 列；`to_dict()` additive 暴露 `archived`（bool）（§2.6） |
| `backend/models/requirement.py` | 修改 | `_resolve_assignee` 悬挂降级为占位 + `_deleted_summary`（bug.py 共用此函数，无需改）（§2.7） |
| `backend/routes/users.py` | 修改 | 末任管理员不变量；`is_active` 停用/启用；无有效字段 → 400（§2.2/2.5/P2-5） |
| `backend/routes/auth.py` | 修改 | 登录时拒绝已停用账号（403，不计入限流）（§2.5） |
| `backend/routes/projects.py` | 修改 | 新增 `PATCH` / `DELETE`；`GET` 默认过滤归档 + `?include_archived=1`（§2.6） |
| `backend/routes/agents.py` | 修改 | 新增 `DELETE`（在手未终态工单 → 409）（§2.7） |
| `backend/routes/requirements.py` | 修改 | `assign` 支持显式取消指派；`/activities` 接分页；`_next_position` 改聚合（§2.4/P2-1/P2-3） |
| `backend/routes/bugs.py` | 修改 | 同上三项的 BUG 侧同构改动 |
| `backend/routes/board.py` | 修改 | 改调 `board_page.column_page`，透传 `?column_limit=`（§2.8） |
| `backend/services/notifications.py` | 修改 | `notify()` 跳过已停用收件人；`notify_comment` 收件人查询改 DISTINCT（§2.5/P2-2） |
| `backend/services/agent_runner.py` | 修改 | `_next_position` 内联副本同步改为聚合查询（P2-3，与路由侧必须同改） |
| `backend/services/validation.py` | 修改 | `want_bool` 补 `required` 形参（additive，默认 False；显式 `null` → 400）（§2.5） |

### 3.2 Backend 测试 —— 新建 3 个 / 修改 1 个

| 文件 | 新建/修改 | 覆盖 |
|---|---|---|
| `backend/tests/test_schema_sync.py` | **新建** | 缺列的存量库被补齐、重复执行零 DDL、表不存在时跳过、补列后模型查询正常 |
| `backend/tests/test_lifecycle.py` | **新建** | 末任管理员降级/停用 409、还有别的 admin 时放行、取消指派（含幂等与审计）、项目/Agent 引用守卫 409 与放行、停用后登录 403 与既有 token 401 |
| `backend/tests/test_board_page.py` | **新建** | 每列上限生效、`total` 为真实总数、`truncated` 标志正确、`?column_limit` 钳制与非法值 400、小库时 `truncated=false` |
| `backend/tests/conftest.py` | 修改 | 新增 `disabled_user` / `archived_project` / `bulk_tickets(n)` fixture |

### 3.3 Frontend —— 新建 2 个 / 修改 14 个

| 文件 | 新建/修改 | 一句话意图 |
|---|---|---|
| `frontend/components/ui/ConfirmDialog.tsx` | **新建** | 全站统一破坏性二次确认（§2.9） |
| `frontend/lib/swr-keys.ts` | **新建** | `invalidateTicketViews()` / `invalidateAdminViews()` 前缀失效工具，三处共用（§2.4） |
| `frontend/lib/types.ts` | 修改 | `User.is_active`、`Project.archived`、`Assignee.deleted?`、`BoardColumn.total/truncated` |
| `frontend/lib/api.ts` | 修改 | 无（`api.del` 已存在）；仅在需要时补 `PROJECTS_KEY` 的归档参数注释 |
| `frontend/lib/constants.ts` | 修改 | `actionLabel` 补 `unassigned`（P2-4） |
| `frontend/components/TicketDrawer.tsx` | 修改 | 危险区「删除工单」；「未指派」真正生效（去掉「暂不支持」分支）（§2.4） |
| `frontend/hooks/useTicket.ts` | 修改 | `assign` 允许 null 载荷；新增 `remove()`（§2.4） |
| `frontend/components/AssigneePicker.tsx` | 修改 | 过滤已停用成员，但保留「当前 assignee 恰为停用成员」的选项（§2.5） |
| `frontend/components/ui/Avatar.tsx` | 修改 | `AssigneeAvatar` 对 `deleted`/停用目标渲染灰态与角标（§2.5/2.7） |
| `frontend/app/(app)/team/page.tsx` | 修改 | 行操作「停用 / 启用」+ 已停用行灰显与徽章（§2.5） |
| `frontend/app/(app)/projects/page.tsx` | 修改 | 行操作「编辑 / 归档 / 删除」+ 归档项目分区或标注（§2.6） |
| `frontend/components/admin/ProjectFormModal.tsx` | 修改 | 由「仅新建」扩展为「新建 / 编辑」两态（§2.6） |
| `frontend/app/(app)/agents/page.tsx` | 修改 | 卡片操作「删除」+ 409 计数渲染进文案（§2.7） |
| `frontend/components/kanban/KanbanColumn.tsx` | 修改 | 列头「显示 x / 共 y」+「查看全部」出口（§2.8） |
| `frontend/hooks/useBoard.ts` | 修改 | key 透传 `column_limit`；类型接住 `total`/`truncated`（§2.8） |
| `frontend/lib/project-scope.tsx` | 修改 | 作用域项目被归档 / 删除时的自愈与提示（§2.6） |

### 3.4 文档

| 文件 | 意图 |
|---|---|
| `docs/plans/lifecycle-and-governance/spec.md` | 本文件 |
| `README.md` | 新增本轮小节：能力清单、接口语义变更一览、`schema_sync` 的能力边界与「何时必须换 Alembic」 |
| `CLAUDE.md` | 在「Project-Specific Notes」补一条硬约束：**加列必须同时登记进 `ADDITIVE_COLUMNS`**，否则存量库必炸 |

---

## 4. Interface Design（接口设计）

### 4.1 新增端点

| 方法 | 路径 | 权限 | 请求体 | 成功 | 失败 |
|---|---|---|---|---|---|
| `PATCH` | `/api/projects/:id` | admin, pm | `{name?, key?, description?, owner_id?, archived?}` | `200` 项目体 | `400` 坏输入 / `404` / `409` key 冲突 |
| `DELETE` | `/api/projects/:id` | admin | — | `204` | `404` / `409` 仍有工单（detail 带计数） |
| `DELETE` | `/api/agents/:id` | admin, pm | — | `204` | `404` / `409` 仍有在手工单（detail 带计数） |

### 4.2 变更的既有端点（**成功路径 shape 只增不改**）

| 端点 | 变更 | 兼容性 |
|---|---|---|
| `PATCH /api/users/:id` | 接受 `is_active`（bool）；降级 / 停用最后一位有效管理员 → **409**；无任何可更新字段 → **400**（此前 200） | 既有合法调用零影响；两个新错误码是**有意收紧** |
| `PATCH /api/{requirements\|bugs}/:id/assign` | `assignee_type: null` 显式取消指派（此前 400） | 纯扩展；`""` 等坏输入仍 400 |
| `POST /api/auth/login` | 已停用账号 → **403** `account is disabled…`（此前 200 + token） | 有意收紧 |
| 全部 `@jwt_required()` 端点 | 已停用 / 已不存在用户的 token → **401** `account is disabled or removed`（此前照常放行；`/api/auth/me` 此前对已删用户返 404） | 有意收紧；前端 401 自动登出天然承接 |
| `GET /api/projects` | **默认只返回未归档**；`?include_archived=1` 返回全部；响应体每项 additive 增加 `"archived": bool` | **默认结果集语义变更**（唯一一处），无归档数据时逐字节不变 |
| `GET /api/board/{requirements\|bugs}` | 每列最多 `?column_limit=`（默认 100，钳制 [1,500]）张卡；每列 additive 增加 `"total"` 与 `"truncated"` | `items` 语义不变；≤100 张的列逐字节不变 |
| `GET /api/{requirements\|bugs}/:id/activities` | 接 `?limit/offset` + `X-Total-Count`（响应体仍是裸数组） | 默认 50 条——**注意这是截断语义变更**，见 §7 R-5 |
| 全部返回工单的端点 | `assignee` 指向已删除目标时返回占位对象而非 `null`（新增 `deleted: true`） | 仅在本轮新引入的「Agent 已删除」状态下可能出现，存量零命中 |

### 4.3 错误契约（全部沿用既有 `{error, detail?}` 形状）

```json
// 末任管理员（409）
{"error":"cannot remove the last administrator",
 "detail":{"reason":"at least one active admin must remain","active_admins":1}}

// 项目仍有工单（409）
{"error":"project still has tickets",
 "detail":{"requirements":12,"bugs":3,"hint":"archive the project instead, or move its tickets"}}

// Agent 仍有在手工单（409）
{"error":"agent still holds open tickets",
 "detail":{"requirements":3,"bugs":1,"hint":"reassign or unassign them first"}}

// 账号停用（登录 403 / 受保护端点 401）
{"error":"account is disabled, contact an administrator"}
{"error":"account is disabled or removed"}
```

**注意**：`409` 在本项目已有两种含义（状态机非法迁移带 `allowed`；乐观并发冲突带
`detail.current_updated_at`）。本轮新增的三种 409 **都不带 `allowed`**，前端
`useBoard.ts:80-88` 的分流判据（`err.allowed` 是否存在）因此仍然成立，无需改动。
新的 409 由各自的调用点就地处理，不进入看板拖拽的错误分流路径。

---

## 5. Data Model（数据模型）

### 5.1 新增列（零新表；经 `schema_sync` 在存量库上补齐）

| 表 | 列 | 类型 | 默认 | 语义 |
|---|---|---|---|---|
| `users` | `is_active` | BOOLEAN NOT NULL | `1` | false = 已停用：不能登录、既有 token 立即失效、不接收通知、不出现在指派选择器 |
| `projects` | `archived_at` | DATETIME NULL | `NULL` | 非空 = 已归档：不出现在项目列表默认结果与全局切换器；既有工单完全不受影响 |

### 5.2 迁移语义

- **新库**：`db.create_all()` 一次建全，`sync_additive_columns` 返回 `[]`。
- **存量库**：`sync` 检出缺列并 `ALTER TABLE … ADD COLUMN`；`is_active` 的
  `NOT NULL DEFAULT 1` 让**全部存量用户默认启用**（不会有人被静默锁在门外）；
  `archived_at` 可空，存量项目默认未归档。
- **幂等**：重复启动零 DDL，日志无输出。
- **失败即启动失败**：任一 ALTER 抛错则异常向上传播、应用起不来。这是**刻意**的——
  模型与库不一致地跑起来，比起不来危险得多。

### 5.3 不新增的东西（明确记录，避免实现时擅自扩张）

- **不加 `deleted_at` 软删列**：工单的硬删 + 级联清理已在第 3 轮定型并写进 README 的
  接口变更表，本轮改成软删会推翻上一轮的结论，且 `_reindex_column` / `_next_position` /
  统计 / 看板全都要加「排除软删」的条件——四处漏一处就是错数据。
- **不加 `agent_runs` 运行历史表**：Agent 可观测性是有价值的方向，但它是「新功能」而非
  「生命周期缺口」，与本轮主题不同，写入 §8。
- **不加 `users.password_changed_at`**：改密码不吊销旧 token 是 `routes/me.py:141` 已
  显式记录的 MVP 权衡；本轮新建的 blocklist 钩子让它变得很便宜，但它属于**认证策略**
  而非生命周期，混进来会让本轮的验收边界模糊。写入 §8 并标注「已具备落地前置」。

---

## 6. Testing & Acceptance（测试与验收标准）

基线：`cd backend; python -m pytest -q` 当前 **281 passed, exit 0**（本轮开工前实测）。
本轮目标 **≥ 315 passed, exit 0**，且**不修改任何既有用例的断言**（若某个既有用例因
本轮的有意收紧而失败，必须在 spec 的接口变更表里能找到对应行，并在 commit message 中
显式标注——不允许「改测试让它绿」）。

### 6.1 后端 pytest 新增用例（按文件）

**`test_schema_sync.py`**
1. `adds_missing_column_to_existing_table`——手工建一张缺列的 `users` 表，跑 sync，列出现。
2. `is_idempotent_on_second_run`——第二次执行返回 `[]` 且不抛。
3. `skips_unknown_table`——清单里的表不存在时静默跳过（新库场景）。
4. `queries_work_after_sync`——补列后 `User.query.all()` 正常，不再 `no such column`。

**`test_lifecycle.py`**
5. `rejects_demoting_the_last_admin` → 409，且库内角色未变。
6. `rejects_deactivating_the_last_admin` → 409。
7. `allows_demoting_when_another_active_admin_exists` → 200。
8. `a_deactivated_admin_does_not_count_as_active` → 有 2 个 admin 但其一已停用时，
   降级另一个仍 409（这是最容易实现错的一条）。
9. `disabled_user_cannot_login` → 403，且**不增加限流计数**。
10. `existing_token_of_disabled_user_is_rejected` → 停用后用旧 token 请求 → 401。
11. `unassign_clears_polymorphic_assignee` → `assignee_type/id` 均为 NULL，`status` **未变**。
12. `unassign_writes_activity_and_notifies_previous_human_assignee`。
13. `unassign_is_idempotent_without_extra_activity`。
14. `assign_with_empty_string_type_still_400`（防把「取消」判据写成 falsy）。
15. `delete_project_with_tickets_conflicts` → 409 且 detail 计数正确。
16. `delete_empty_project_succeeds` → 204，且 `/api/projects` 不再包含它。
17. `archived_project_hidden_by_default_and_visible_with_flag`。
18. `patch_project_key_conflict_409` / `patch_project_updates_fields`。
19. `delete_agent_with_open_tickets_conflicts` → 409 且计数正确。
20. `delete_agent_with_only_terminal_tickets_succeeds` → 204。
21. `deleted_agent_assignee_degrades_to_placeholder` → 工单 `assignee.deleted === True`，
    **不是** `null`（这条直接对应 §2.7 的「不说谎」目标）。
22. `notifications_skip_disabled_recipient`。

**`test_board_page.py`**
23. `column_is_capped_at_limit` / `column_total_is_true_total` / `truncated_flag_is_accurate`。
24. `small_board_reports_truncated_false`。
25. `column_limit_query_param_is_clamped` + 非法值 → 400（走既有 `QueryParamError`）。
26. `board_shape_is_backward_compatible`——`columns[].key/title/items` 依旧存在且有序。

**回归（在既有文件里补，不改既有断言）**
27. `test_rbac.py`：member 对新增的 `DELETE /projects/:id`、`DELETE /agents/:id` → 403。
28. `test_validation.py`：`is_active` 传非 bool → 400；`archived` 传非 bool → 400；
    `column_limit` 超界 → 400。
29. `test_admin_console.py`：`patch_user` 无可更新字段 → 400。
30. `test_validation.py`：`want_bool_required_rejects_null`——`{"is_active": null}` → 400
    （**不是**静默取 default False 把人停用）；且既有两个 `want_bool` 调用点行为不变。

### 6.2 前端质量门禁

```powershell
cd frontend
npm run typecheck   # tsc --noEmit → 0 error，且全轮不得新增任何 `as any`
npm run build       # next build → 全部页面成功（当前基线 16/16）
```

### 6.3 手工验收冒烟（P0/P1 路径，逐条可勾）

| # | 步骤 | 期望 |
|---|---|---|
| A1 | 用唯一 admin 尝试把自己改成 member | 弹出可读的中文错误「系统至少需要保留一位管理员」，角色未变 |
| A2 | 新建第二个 admin 后再降级自己 | 成功 |
| B1 | 抽屉里删除一张需求 → 返回列表 / 看板 / 仪表盘 | 三处都不再有它；再刷新仍然没有 |
| B2 | 删除时确认框 | 写明将连带删除的评论条数；处理中按钮禁用；双击不产生第二次请求 |
| B3 | 抽屉里把 assignee 选成「未指派」 | 保存成功，负责人显示「未指派」，时间线出现「取消了指派」中文条目 |
| B4 | 原 assignee（人类）登录看铃铛 | 收到「你不再负责…」通知 |
| C1 | admin 在团队页停用 alice | 行灰显 + 「已停用」徽章；指派下拉里不再有 alice |
| C2 | alice 用旧 token 刷新任意页面 | 自动跳登录页（401 自动登出链路） |
| C3 | alice 重新登录 | 403 + 中文提示「账号已停用，请联系管理员」 |
| C4 | 停用一张工单当前 assignee 后打开该单 | 负责人仍显示其名字 + 灰色「已停用」，**不是**「未指派」 |
| C5 | 项目页编辑项目名 / key | 立即生效；Header 切换器与工单抽屉的项目名同步更新 |
| C6 | 归档当前作用域所在项目 | 切换器回落「全部项目」并有一次提示；该项目的工单仍能正常打开与流转 |
| C7 | 删除仍有工单的项目 | 确认框内**就地**显示「还有 12 个需求、3 个 BUG」，对话框不关闭 |
| C8 | 删除一个空项目（键入 key 解锁） | 204，列表与切换器同步消失 |
| C9 | 删除仍有在手单的 Agent | 409 + 中文计数提示 |
| C10 | 删除一个空闲无单的 Agent | 成功；其历史评论仍在时间线上，作者显示「(已删除)」 |
| D1 | 灌 300 张需求后打开看板 | 每列最多 100 张；列头显示「显示 100 / 共 300」；点「查看全部」到达列表页且已按该状态筛选 |
| D2 | 小库（每列 < 100）打开看板 | 列头**无**任何额外文案（观感与今天完全一致） |
| E1 | 用**上一轮的存量 `aragon.db`** 启动后端 | 启动日志出现 `schema_sync applied: users.is_active, projects.archived_at`；登录与所有页面正常 |
| E2 | 再启动一次 | 无 `schema_sync applied` 日志（幂等），一切正常 |
| Z1 | 全站回归：建单 → 指派 Agent → 「运行 AI 团队一轮」 | 与本轮之前行为一致，需求推进到 `reviewing`、BUG 到 `closed` |

### 6.4 Definition of Done

1. `pytest -q` ≥ 315 passed，exit 0，**无既有用例的断言被改写**。
2. `tsc --noEmit` 0 error；`next build` 全页成功；本轮不新增 `as any`。
3. §6.3 的 24 条冒烟**全部 PASS**，其中 E1 必须在**真实的存量 `aragon.db`** 上验证
   （不是新建的空库——那验证不到本轮最关键的迁移路径）。
4. 全站 `grep` 确认：`api.del` 至少有 3 处调用；`ADDITIVE_COLUMNS` 与 `models/` 里
   本轮新增的列一一对应；`_next_position` 的两处副本改动一致。
5. `README.md` 与 `CLAUDE.md` 已更新（含 `schema_sync` 的能力边界与升级 Alembic 的判据）。

---

## 7. Risks & Mitigations（风险与缓解）

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R-1 | `schema_sync` 在存量库上执行失败（磁盘只读 / 表被锁） | 应用起不来 | **刻意**让异常向上抛（起不来 > 带病跑）；日志给出确切的表.列；README 写明手工 `ALTER` 的回退命令 |
| R-2 | `ADDITIVE_COLUMNS` 与模型漂移（有人加列忘了登记） | 存量库全线 500 | 写进 `CLAUDE.md` 硬约束；`test_schema_sync.py` 增加一条「模型列集合 ⊆ (create_all 建出的列 ∪ 清单)」的守卫断言 |
| R-3 | 后人给 `schema_sync` 扩权（改类型 / 删列 / 回填） | 静默错数据，比没有迁移更危险 | 能力边界写死在模块 docstring + §2.3；给出「出现第一个非 additive 需求即引 Alembic」的明确判据 |
| R-4 | `token_in_blocklist_loader` 给每个受保护请求加一次 `users` 查询 | 潜在性能回归 | `current_user()` 本就查同一行，SQLAlchemy identity map 在同一 session 内命中缓存；实测以 `/api/stats` 为基准对比前后 P95，回归 > 10% 则改为在 JWT claim 里带 `is_active` 并只在写路径回查 |
| R-5 | `/activities` 加分页后**默认只返 50 条**，是截断语义变更 | 前端若有消费者会静默少数据 | 已确认前端**无任何调用点**（只用 `/feed`）；仍在 §4 显式标注，并在实现时把默认上限设为 `MAX_LIMIT=200` 而非 50，把风险降到最低 |
| R-6 | 删除工单的级联依赖第 3 轮的实现，本轮只接前端 | 若级联有洞，本轮把它暴露给了所有用户 | 冒烟 B1 必须验证「评论 / 通知 / 审计 / 转出 BUG 的反向引用」四项都干净；`test_lifecycle.py` 补一条删除后 `/notifications` 不再含指向该单的条目 |
| R-7 | 「未指派」态的工单在看板上无人认领，可能被遗忘 | 流程停滞 | 取消指派会给原 assignee 发通知，且工单停留在原状态列可见；**不**自动改派（静默改派更坏） |
| R-8 | 归档项目导致 `PROJECTS_KEY`（`/projects?limit=200`）的结果集变化 | 切换器与项目页缓存不一致 | 二者已共用同一 key（第 3 轮 R4 的结论），语义变更对两处同时生效；项目页需要看归档项目时用**另一个 key**（`?include_archived=1`），符合「一个 key 一种形状」不变量 |
| R-9 | 看板每列查询数从 1 次变成 2×列数次（7 列 → 14 次） | 小库上反而更慢 | 列数是常量且每次查询都带 LIMIT / 是 COUNT；实测 300 单场景对比总耗时，若劣化则改为单次 `ROW_NUMBER() OVER (PARTITION BY status)`（SQLite 3.25+ 支持）作为备选方案 |
| R-10 | `_resolve_assignee` 的占位返回改变了 `assignee` 可能为 `null` 的前端假设 | 列表 / 抽屉渲染异常 | TypeScript 类型同步更新（`Assignee.deleted?: boolean`），`tsc` 会强制所有消费点被审视；存量数据零命中，属纯新增分支 |
| R-11 | 一次引入 4 个破坏性动作，误删风险上升 | 用户数据丢失 | 统一 `ConfirmDialog`（pending 禁用 / 错误就地显示 / 删项目需键入 key）；删除工单以外的三种都有引用守卫；三者都写审计或结构化日志 |
| R-12 | 本轮改动面横跨 17 个后端文件 + 16 个前端文件 | 一次性合入风险大 | §10 的四阶段实施顺序，每阶段独立可门禁（各自跑全量 pytest + typecheck），阶段间无回滚耦合 |

---

## 8. Out of Scope（本轮明确不做，及理由）

1. **删除用户（硬删）**——`users.id` 被三处真外键引用且 `PRAGMA foreign_keys=ON`
   （首手复现 `IntegrityError`）；删干净必须销毁审计，与产品核心价值冲突。停用是正解。
2. **工单软删 / 回收站**——会推翻第 3 轮已定型并写进 README 的硬删 + 级联结论，且需要在
   四个查询面加「排除软删」，漏一处即错数据。
3. **`agent_runs` 运行历史表 / Agent 可观测性面板**——有价值，但属于「新功能」，
   与本轮「生命周期闭环」主题正交，且必然引入新表（与本轮零新表的取舍冲突）。
4. **改密码吊销旧 token**——本轮建立的 blocklist 钩子已让它变得很便宜（加
   `password_changed_at` 并比对 `iat` 即可），但它是认证策略而非生命周期，
   混入会让验收边界模糊。**已具备落地前置，建议列为下一轮首选项。**
5. **评论的编辑 / 删除**——一条错评论的伤害远小于一张删不掉的单；且评论删除会牵动
   `notify_comment` 的历史收件人集合与 feed 排序，成本收益不划算。
6. **引入 Alembic**——见 §2.3 的取舍与 §7 R-3 的升级判据。
7. **`_reindex_column` 与截断列的精确交互**——本轮接受偏差并在 UI 标注（§2.8）；
   连续两轮改写同一段高风险排序逻辑不明智。
8. **WebSocket / SSE 实时化**——通知与看板仍走 SWR 轮询，与前三轮结论一致。

---

## 9. 设计取舍说明（含被排除的候选缺陷）

我在审查中还列过下面几条候选，**经复现后主动排除**，记录在此以免下游重复劳动：

- **「`POST /api/auth/register` 是开放注册」**——排除。它是 `@require_role("admin")`
  （`routes/auth.py:55`），且前端零调用。不是缺陷，只是一个冗余端点。
- **「`GET /api/{entity}/:id/comments` 与 `/activities` 是死端点」**——排除为缺陷、
  保留为观察。前端只用 `/feed`，但这两个端点是公开 REST 契约的一部分，删除它们是
  破坏性变更且无收益。本轮只给 `/activities` 补分页（P2-1）。
- **「看板 `setdefault` 容错分桶会隐藏非法状态」**（`routes/board.py:25`）——排除。
  写入侧由邻接表保证合法，该分支正常不可达，且注释已说明其防御意图。为它加告警属噪音。
- **「`notify_comment` 会给同一人同时发 commented 与 mentioned 两条」**——排除为本轮范围。
  这是**有意的**：两种事件语义不同（有人回复 vs 有人点名找你），合并反而丢信息。
- **「`/api/stats` 的 `activities_this_week` 不随项目过滤」**——排除。第 3 轮已作为
  有意保持全局的字段并要求前端标注，本轮不推翻上一轮的结论。
- **「`login` 的限流是进程内的，重启即清零」**——排除为本轮范围。`services/ratelimit.py`
  的 MVP 单机定位在 Phase-2 已明示；把它做成持久化需要引入 Redis 或新表，属于部署形态
  的演进，不在「生命周期」主题内。

---

## 10. 实施顺序建议（给 Subtask #2 · 严格四阶段，每阶段独立门禁）

**阶段 1 — 地基（必须最先，且单独跑通门禁）**
`schema_sync.py` + `app.py` 接入 + `models/user.py` / `models/project.py` 加列 +
`test_schema_sync.py`。门禁：`pytest -q` 全绿；**并用一份真实的存量 `aragon.db` 副本
启动一次**，确认日志出现 `schema_sync applied` 且登录正常（冒烟 E1/E2）。
**这一阶段不通过，后面一步都不能做。**

**阶段 2 — P0 治理与撤销**
`lifecycle.py`（`would_orphan_admins` + `unassign_ticket`）+ `routes/users.py` +
`routes/auth.py` + `errors.py` 的 blocklist + `requirements.py`/`bugs.py` 的取消指派 +
前端 `ConfirmDialog` + `TicketDrawer` 的删除与取消指派 + `useTicket` + `swr-keys.ts`。
门禁：`pytest -q` 全绿；冒烟 A1/A2/B1-B4 全 PASS。

**阶段 3 — P1 资源生命周期**
`lifecycle.py`（引用守卫）+ `routes/projects.py` + `routes/agents.py` +
`_resolve_assignee` 降级 + `notifications.py` 的停用跳过 + 前端 team / projects /
agents 三页与 `ProjectFormModal` / `AssigneePicker` / `Avatar` / `project-scope`。
门禁：`pytest -q` 全绿；冒烟 C1-C10 全 PASS。

**阶段 4 — P1 看板分页 + P2 收口**
`board_page.py` + `routes/board.py` + `KanbanColumn` / `useBoard` + §2.10 的五条 P2 +
`README.md` / `CLAUDE.md`。门禁：`pytest -q` ≥ 315 全绿；`tsc --noEmit` 0 error；
`next build` 全页成功；冒烟 D1/D2/Z1 全 PASS。

每个阶段结束都要能独立回答一句话：「这一阶段之后，用户多了哪一种以前做不到的事？」
——若答不上来，说明阶段划分错了。


---

## 实施过程发现的方案缺陷（Issues Found During Implementation）

> 由 Subtask #2（实施）在按 §3 文件变更计划落地时发现并就地修正。每条都说明「方案怎么写的 /
> 实际是什么 / 改成了什么」，供后续评审复核。

### F1｜`/activities` 的默认上限没有落点（§7 R-5 的缓解措施无法实现）

§7 R-5 承诺「实现时把 `/activities` 的默认上限设为 `MAX_LIMIT=200` 而非 50，把截断风险降到最低」，
但 `services/pagination.py::paginate()` 的签名是 `paginate(query)`，默认条数写死为模块常量
`DEFAULT_LIMIT=50`，**没有任何形参可以表达「这个端点的默认上限不一样」**。照字面实现只能二选一：
要么改全局 `DEFAULT_LIMIT`（波及全部列表端点，远超本轮范围），要么在 `/activities` 里再手搓一份
`limit` 解析（与「不写第四份整型解析」的收口原则冲突）。

**处理**：给 `paginate()` 补一个 additive 关键字参数 `default_limit`（默认值仍是 `DEFAULT_LIMIT`，
既有 9 个调用点行为逐字节不变），`/activities` 两处显式传 `MAX_LIMIT`。`services/pagination.py`
因此进入本轮的改动清单（§3.1 未列出它，属方案遗漏）。

### F2｜看板「查看全部」的落点不存在（§2.8 的出口链路断在最后一跳）

§2.8 写「点『查看全部』跳到对应列表页并预置 `?status=<key>` 筛选（列表页已有 status 过滤条与分页条，
天然承接）」。实际核对 `app/(app)/requirements/page.tsx:49-63` 与 bugs 侧同构代码：列表页 mount 时
**只读取 `?q=`**，从不读 `?status=`。照方案实现，点「查看全部」会跳到一个**未经筛选的全量列表**，
用户以为筛过了、其实没有——正是本轮要消灭的那类谎话。

**处理**：在两个列表页已有的 mount effect 里补读 `?status=`，并**只接受合法列 key**
（`REQUIREMENT_COLUMNS` / `BUG_COLUMNS`），避免把任意查询串灌进过滤条。这两个文件因此进入本轮
改动清单（§3.3 未列出它们）。

### F3｜项目页需要看到归档项目，但 `PROJECTS_KEY` 按定义看不到

§2.6 规定 `GET /api/projects` 默认只返回未归档，§7 R-8 也据此推论「项目页需要看归档项目时用**另一个
key**（`?include_archived=1`）」——但 §3.3 的文件变更计划里，项目页仍写着沿用 `PROJECTS_KEY`。二者
直接矛盾：沿用 `PROJECTS_KEY` 的话，项目一旦归档就从项目页消失，**再也没有任何界面能取消归档**，
本轮自己制造一个新的「没有回头路」。

**处理**：按 §7 R-8 执行——项目页改用独立的 `PROJECTS_ALL_KEY = "/projects?limit=200&include_archived=1"`，
切换器与建单表单仍只读 `PROJECTS_KEY`（不含归档），「一个 key 一种形状」不变量成立。归档 / 删除后
两份缓存一起失效（`invalidateAdminViews`）。

### F4｜项目 / Agent 的删除审计无处可写（G3③ 与 `Activity` 的实体枚举冲突）

G3③ 要求每个破坏性动作都「写审计或结构化日志」，§2.6 / §2.7 也照此描述。但
`models/activity.py::ENTITY_TYPES` 只有 `("requirement", "bug")`，`activities` 表的语义与索引都绑定在
工单上——为项目 / Agent 的删除写 `Activity` 行等于**偷偷扩张审计表的实体域**，且这些行没有任何查看入口
（时间线只按工单查询），还会污染 `/stats.activities_this_week`。

**处理**：取 G3③ 的「或结构化日志」分支——`delete_project` / `delete_agent` 各写一条
`log.info("... deleted: id=%s key=%s by=%s", ...)`（含操作者用户名），复用 `observability.py` 已装配的
结构化日志管道，不动 `Activity` 的实体枚举。

### F5｜`notifications._short` 是私有函数，`lifecycle` 需要同一套截断策略

§2.4-B2 规定取消指派的通知文案是「你不再负责{需求|BUG}「…」」，其中标题必须与既有通知一样截断到 40 字
（否则撑破 `message VARCHAR(255)`）。该逻辑在 `services/notifications.py::_short`，是带下划线的私有函数；
从 `services/lifecycle.py` 直接引用私有名会制造一处隐性耦合，各写一份又是第二真相。

**处理**：在 `notifications.py` 暴露一个薄公开别名 `short_text()`（内部仍调 `_short`），`lifecycle` 用它。
零行为变化，模块边界清晰。

### F6｜`test_schema_sync.py` 的「模型列 ⊆ 清单」守卫在内存库上不可实现

§7 R-2 要求补一条断言「模型列集合 ⊆ (create_all 建出的列 ∪ 清单)」。但测试用的是 `TestConfig` 内存库，
`create_all()` 一次把**全部**模型列都建出来，该包含关系**恒真**——这条断言在测试环境里永远绿，抓不到任何
漂移，是一条假的护栏。

**处理**：改为可真实失败的反向守卫——断言 `ADDITIVE_COLUMNS` 里登记的每一项都**确实存在于模型**
（登记了却没加列 / 列名拼错时立即失败）；「加了列却忘了登记」这一侧由 `CLAUDE.md` 的硬约束 + 本轮在两个
模型文件的列定义旁写下的注释承接。此偏差已在 §6.1 的用例意图内如实反映。

