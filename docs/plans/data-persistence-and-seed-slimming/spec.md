# 数据持久化确证与示例数据瘦身（Data Persistence & Seed Slimming）

> 迭代代号：`data-persistence-and-seed-slimming`
> **文档版本：v2**（v1 → v2：吸收设计评审，修复 2 个 P0、9 个 P1；评审记录见下一节）
> 目标：**数据存得住、丢不了、看得见**；**每一类示例数据只留一条**，存量库里的旧演示数据可被安全清除。
> 本文档是实现级设计，下游工程师应能据此逐行落地，不再需要二次决策。

---

## 0. 评审记录（Review Notes）

评审对象：v1 全文，逐节对照 **可行性 / 完备性 / 一致性 / 规模适配** 四个维度，并与仓库实际代码
（`backend/extensions.py`、`config.py`、`app.py`、`seed.py`、`services/lifecycle.py`、
`routes/requirements.py:278-297`、`routes/bugs.py::delete_bug`、`tests/conftest.py`、`.gitignore`、
`frontend/app/login/page.tsx`、`README.md`）逐条核对。**P0 / P1 已在正文中改掉，下表保留问题原貌以备追溯。**

| # | 维度 | 严重度 | 问题（v1 原样） | 处置（v2 正文） |
|---|---|---|---|---|
| **P0-1** | 完备性 / 数据安全 | **P0** | §2.6 步骤 4 的「每类按 id 升序保留第 1 条」被 §5.3 末句显式套用到 `comments` / `activities` / `notifications` 上；§4.2 报告样例也写着这三类各 `delete 3`。这三类里绝大多数是**用户真实产生的审计轨迹与讨论**，且它们不在指纹表里、无从与演示数据区分——照此实现，`--apply` 会把真实审计时间线删到只剩一条，与 R-3「不误删」和文档自称的「审计是平台核心价值」直接冲突，且不可逆。 | §2.6 步骤 4 改为**仅对有出身证明的类**（users / agents / projects / requirements / bugs）套用「每类留一」；这三类只删「`seed_records` 登记的 ∪ 被删工单级联带走的 ∪ 指向不存在实体的孤儿」三类行，**永不按计数裁剪**。§5.3、§4.2 报告样例同步改写。 |
| **P0-2** | 可行性 | **P0** | §2.6 要求 CLI 复用 `lifecycle.*`（`would_orphan_admins` / `agent_open_workload` / `delete_ticket_cascade`），这些函数走 `Model.query`，**必须**有 Flask-SQLAlchemy 应用上下文；而 `backend/app.py:99` 有模块级 `app = create_app()`——**只要 import 到 `app` 模块，就会立刻对「默认 DATABASE_URL 指向的库」执行 `create_all` + `schema_sync` + `seed_if_empty`（v2 还要加解锁 busy）**。后果有二：(a) dry-run 也写库，`test_dry_run_writes_nothing` 与 §6.3-6「库文件 mtime 不变」双双不可能成立；(b) `--database-url` 指向 B 库时，工具仍会顺手创建/播种 A 库。 | §2.6 新增「**CLI 启动契约（顺序不可换）**」：argparse → 写 `DATABASE_URL` / `SEED_ON_STARTUP=false` / `RELEASE_STALE_LOCKS_ON_STARTUP=false` 三个环境变量 → 备份 → **此时才** `import app` 并 `create_app(PurgeConfig)`。§6.3-6 的 mtime 判据改为「各表行计数不变」（`create_all` 建 `seed_records` 空表必然动 mtime，这是可接受且必要的写）。 |
| **P1-3** | 可行性 | P1 | §2.3 要求在 `extensions.py::_set_sqlite_pragma` 里读 `SQLITE_SYNCHRONOUS`、失败时 `app.logger.warning`；但该函数是挂在 `sqlalchemy.Engine` 上的**全局 connect 监听器**，触发时机（引擎首连、连接池补连、后台线程）不保证有 Flask 应用上下文，`app.config` / `current_app.logger` 都取不到。§3 又把这两个开关列进 `config.py`，两处互相矛盾。 | §2.3 改为：PRAGMA 取值**只从 `os.environ` 读**，降级告警用模块级 `logging.getLogger(__name__)`；`config.py` 里的同名字段降级为**文档性镜像**（供 `/api/health` 与 README 展示），明确标注「不是 PRAGMA 的读取源」。 |
| **P1-4** | 完备性 | P1 | §4.1 的 `storage` 块示例写 `"synchronous": "NORMAL"`、`"foreign_keys": true`，但 `PRAGMA synchronous` 返回**整数** 0/1/2/3、`PRAGMA foreign_keys` 返回 0/1，v1 没给映射；更要命的是没写 PRAGMA 自身抛错时怎么办——照直实现会让一个**探针端点**因为自省失败而 500。 | §4.1 补齐整数→字面量映射表、布尔转换，并规定整块 `try/except` 降级为 `{"persistent": …, "journal_mode": "unknown", …}`；**HTTP 状态码判据仍只由 `SELECT 1` 决定**，自省失败绝不改变 200/503。 |
| **P1-5** | 可行性 | P1 | §6.1 的 `test_stale_lock_release_can_be_disabled` 写「`RELEASE_STALE_LOCKS_ON_STARTUP=false` 时」。但 `config.py` 的字段是在**类定义（import）时**求值的，用例里 `monkeypatch.setenv` 对已导入的 `Config` 类不产生任何影响——该用例会静默地测了个寂寞。 | 全文统一措辞为「配置项（由同名环境变量在**进程启动时**初始化）」；§6.1 明确：用例一律通过 **config 子类属性覆盖**，只有 CLI（独立进程，见 P0-2）才用环境变量。 |
| **P1-6** | 一致性 | P1 | §2.7 的 `delete_ticket_cascade(entity, ticket) -> dict` 契约不完整：(a) 没说是否 `db.session.delete(ticket)` 本身；(b) 实测 `routes/requirements.py:285` 比 `routes/bugs.py::delete_bug` **多一步** `Bug.related_requirement_id` 置空，两条路径并不对称，签名却没有分支说明——照 v1 抽取无法做到「行为逐字不变」。 | §2.7 补完整函数契约：显式声明**只清理引用、不删工单本体**（由调用方 `db.session.delete`），并把 `related_requirement_id` 置空写成 `entity == "requirement"` 分支，附「BUG 侧本就没有这一步，加上即行为漂移」的注释要求。 |
| **P1-7** | 完备性 | P1 | §2.6 步骤 5 列了删除顺序，但没写守卫的**求值时机**。legacy 库里 `qa-agent` 名下有一张 `fixing` 的 BUG（`seed.py:92`），若在删工单**之前**评估 `agent_open_workload`，qa-agent 会被永远跳过，「每类留一」达不成，且报告会给出一个用户无法理解的 skip 理由。 | §2.6 步骤 5 显式写死：工单删除后**先 `session.flush()` 再评估** agent / user 守卫，并说明理由。 |
| **P1-8** | 完备性 | P1 | §4.2 定义「退出码 2 = 因守卫部分跳过」，而 §6.1 的 `test_dry_run_writes_nothing` 断言退出码 0；dry-run 同样会产生守卫跳过（legacy 库上几乎必然），两条规格互相打架。 | §4.2 写死退出码与 dry-run/apply **无关**，只反映「本次是否存在守卫跳过」；§6.1 对应用例的断言改为「各表行计数不变」，不绑定退出码。 |
| **P1-9** | 一致性 | P1 | §6.2 写「≥315 既有用例」；实测 `backend/tests/test_*.py` 共 **327** 个 `def test_`（parametrize 展开后更多），而 `CLAUDE.md` 的质量门禁一节写的是 93——三个数字互不相同。把固定数字写进门禁会让门禁本身变成噪音。 | §6.2 改为「**不新增失败、用例总数不减**」的相对判据，并注明基线以落地当天本地 `pytest -q` 实测为准；同时提示实现者顺手订正 `CLAUDE.md` 里陈旧的 93（本轮评审不改代码/其他文档，仅提示）。 |
| **P1-10** | 一致性 | P1 | §2.5 的新 seed 自相矛盾：示例需求**未指派**，却给 `admin` 造一条 `type=assigned` 的通知；而示例评论作者又是 `admin` 本人——若走 `notifications.notify`，「不给自己发」的既有不变量（`services/notifications.py`）会让这条通知根本发不出来，硬塞则演示数据违反了平台自己的规则。 | §2.5 改为：唯一的示例评论由 **dev-agent** 撰写（`author_type=agent`），唯一的通知随之改为 `type=commented`、`actor=(agent, dev-agent)`、收件人 `admin`——语义自洽（别人评论了我报的单），且不触碰「不给自己发」不变量。 |
| P2-11 | 完备性 | P2 | 删 Agent 会在**真实**工单上留下悬空 `assignee_id`（多态软引用，无外键）；与既有 `DELETE /api/agents` 行为一致，但 purge 是批量的，用户更难察觉。 | §2.6 报告增加一行「受影响的悬空指派」计数，仅提示不阻断。已在 §7 R-12 登记。 |
| P2-12 | 规模适配 | P2 | `/api/health` 每次探针多打 3 次 PRAGMA。 | §4.1 注明 `journal_mode` / `synchronous` 在启动期读一次并缓存进 `app.config`，请求路径只读缓存 + 一次 `SELECT 1`。 |
| P2-13 | 完备性 | P2 | §2.6 步骤 3「先剔除孤儿 `seed_records`」未区分 dry-run。 | §2.6 注明 dry-run 下只统计不删。 |
| P2-14 | 规模适配 | P2 | 缺「为什么不直接删库重建」的取舍说明——这是评审时第一个会被问到的替代方案。 | §1 末尾补一段显式取舍。 |
| P2-15 | 可行性 | P2 | `file_app` fixture 未 dispose 引擎：Windows 上 SQLite 文件被占用会让 `tmp_path` 清理报 `PermissionError`（本项目主力平台是 Windows）。 | §6.1 fixture 补 `db.engine.dispose()` 的 teardown 与显式 `restart()` 语义。 |
| P2-16 | 一致性 | P2 | `LEGACY_FINGERPRINT` 的 `project_key: ("ARA",)` 与**新** seed 的项目 key 相同，读者会怀疑新库被误判。 | §5.3 注明这是有意复用，且 `Project.key` 有 `unique=True`（`models/project.py:10`），不可能同时存在两个 ARA，「每类留一」恒保留它。 |

**未发现的问题类别**（已核对、确认无风险，记录以免下次重复核）：`.gitignore` 的 `*.db` 确实**不**覆盖
`aragon.db-wal` / `-shm`，v1 已正确列出补充项；本轮**零新增列**、只加一张表，`schema_sync.ADDITIVE_COLUMNS`
无需登记，与 `CLAUDE.md` 的硬约束一致；`services/workflow.py` 全程未被触碰。

---

## 1. 概述（Overview）

本轮需求只有两句话：「数据需要持久化，确保数据持久化 OK」「相关 MOCK 数据需要清除，每一类只保留一个示例数据即可」。
表面看是两件小事，落到本仓库的真实状态上却是两个互相咬合的问题：**清理演示数据必须以「不误删用户真实数据」为前提，
而「不误删」正是持久化可信度的一部分**。当前 `backend/aragon.db` 里有 10 条需求、7 个 BUG、11 条通知、25 条审计，
其中约 7 条需求 / 5 个 BUG 来自 `backend/seed.py`，其余是使用过程中真实产生的——两者在库里**没有任何可区分的标记**。
因此本轮的第一性问题不是「删哪些行」，而是「凭什么知道哪些行是演示数据」。

**持久化侧（P 组）**：现状其实已经不差——`config.py` 用 `os.path.dirname(__file__)` 解析出绝对路径，
无论从仓库根还是 `backend/` 启动都命中同一个 `aragon.db`；`.gitignore` 已忽略 `*.db`，数据不会被版本控制污染；
`extensions.py` 已有 `PRAGMA foreign_keys=ON`。真正的缺口有四处：(a) 库处于 `journal_mode=delete`，
在 `threaded=True` + LLM 长调用的并发写场景下容易 `database is locked`，且崩溃窗口更大；
(b) `agents.status='busy'` 是一把**落库的软锁**，进程被 Ctrl+C 杀死时 `finally` 不执行，锁会永久留在库里，
该 Agent 此后每一次 autopilot 调用都 409，产品内没有任何解锁入口；(c) 没有任何一条测试跑在**真实文件库**上——
全部 327 个用例（实测 `def test_` 计数，评审 P1-9 订正）都用 `sqlite:///:memory:`，
「重启后数据还在吗」这个问题在 CI 里从未被回答过；
(d) README 把 `DATABASE_URL` 默认值写成相对路径 `sqlite:///backend/aragon.db`，照文档设环境变量的人会得到
一个随工作目录漂移的第二个库文件，表现就是「数据莫名其妙消失了」。

**示例数据侧（S 组）**：`seed.py` 目前一次性写入 4 个用户、2 个 Agent、1 个项目、7 条需求、5 个 BUG、
4 条评论、4 条审计、4 条通知——共 31 行，本意是「看板一启动就有内容」，代价是新用户第一眼看到的全是假数据，
且真假混杂之后再也分不开。本轮把 seed 收敛为**每类恰好 1 条**（共 8 行），并引入 `seed_records` 登记表，
让**今后**写入的每一条种子行都自带出身证明；对**存量**库则提供一次性维护工具 `tools/purge_demo_data.py`，
以「历史 seed 指纹 + 默认 dry-run + 自动一致性备份 + 引用中的用户停用而非删除」四重保险完成清理。
两侧合在一起构成本轮的验收命题：**清完之后重启，剩下的东西一条不少，被清掉的东西一条不回来。**

**为什么不直接删库重建**（评审 P2-14）：「删掉 `aragon.db` 再启动」确实能一步得到干净的 8 行示例数据，
成本远低于一个 CLI 加一张表。之所以不采用，是因为它**要求用户先接受「我这段时间建的真实单全部丢掉」**——
而本轮的另一半需求恰恰是「确保数据持久化 OK」，用「把数据全删了」来交付「数据存得住」是自相矛盾的。
删库重建仍然是**可用的兜底路径**，写进 README 供「我这库里本来就没有真东西」的用户使用（一条命令，零风险）；
`tools/purge_demo_data.py` 服务的是另一类人：**库里真假混杂，且真的那部分丢不起**。两条路径并存，
文档里并排给出，由用户按自己的库状态选。

---

## 2. 技术设计（Technical Design）

### 2.1 架构位置

```
启动路径（backend/app.py::create_app 的 app_context 内，顺序不可换）
  import models              ← 注册全部表定义（含新增 SeedRecord）
  db.create_all()            ← 建缺失的表（seed_records 由此创建，无需 ALTER）
  schema_sync.sync_additive_columns(engine)
  persistence.log_storage_summary(app)        ← 【新】把解析后的绝对库路径 / journal_mode 写进启动日志
  persistence.release_stale_agent_locks(db.session)  ← 【新】崩溃残留的 busy 软锁自愈
  seed_if_empty()            ← 【改】每类 1 条 + 登记 seed_records

连接路径（backend/extensions.py 的 Engine "connect" 事件，每条新连接执行一次）
  PRAGMA foreign_keys=ON     ← 既有
  PRAGMA journal_mode=WAL    ← 【新】仅文件库；内存库跳过
  PRAGMA synchronous=NORMAL  ← 【新】可由 SQLITE_SYNCHRONOUS 覆盖
  PRAGMA busy_timeout=15000  ← 【新】与 connect_args timeout 对齐，显式化

维护路径（离线 CLI，不挂任何 HTTP 面）
  backend/tools/purge_demo_data.py
    → 解析 DATABASE_URL → sqlite3.Connection.backup() 一致性备份
    → 组装删除集合（seed_records ∪ LEGACY_FINGERPRINT）
    → 每类保留 id 最小的一条，其余经 lifecycle.delete_ticket_cascade 级联删除
    → 被引用的 seed 用户改为 is_active=False（停用）而非删除
    → 打印人类可读报告（或 --json）
```

### 2.2 P-1｜单一库文件真相与可见性

- `config.Config.SQLALCHEMY_DATABASE_URI` **保持不变**（已是绝对路径），但新增模块 `services/persistence.py`
  提供 `describe_storage(uri) -> dict`，返回 `{"backend": "sqlite"|"other", "persistent": bool, "path": str|None}`。
  `persistent` 的判据：URI 以 `sqlite:` 开头且解析出的文件名不为空且不是 `:memory:`。
- **启动日志**（`app.logger.info`）打印 `storage: sqlite file=<绝对路径> exists=<bool> size=<bytes>`。
  这是唯一会出现完整路径的地方——服务端日志，不经网络暴露。
- **健康检查 additive**：`GET /api/health` 的响应**保持 `db: "ok"|"error"` 字段字面不变**（对外契约稳定），
  additive 新增只读块：

  ```json
  "storage": { "persistent": true, "journal_mode": "wal", "foreign_keys": true, "synchronous": "NORMAL" }
  ```

  **有意不含 `path`**——`/api/health` 无需鉴权，回传服务器文件系统路径是无谓的信息泄露。
  `journal_mode` 通过 `PRAGMA journal_mode`（只读查询形式，不带 `=`）读回**真实生效值**而非配置值：
  网络盘 / 某些同步盘上 WAL 会静默失败，此处必须报告事实。
- **文档修正**：README 环境变量表把 `DATABASE_URL` 的默认值写为
  「`sqlite:///<repo>/backend/aragon.db`（由 `config.py` 所在目录解析为绝对路径，从任何工作目录启动都是同一个文件）」。

### 2.3 P-2｜SQLite 持久化 PRAGMA

在 `extensions.py::_set_sqlite_pragma` 内扩展（仍限 sqlite3 方言）：

| PRAGMA | 值 | 理由 |
|---|---|---|
| `foreign_keys` | `ON` | 既有，不动 |
| `journal_mode` | `WAL` | 崩溃安全 + 读不阻塞写；`threaded=True` 下的 LLM 长事务不再让看板整页 503 |
| `synchronous` | `NORMAL`（可被环境变量 `SQLITE_SYNCHRONOUS` 覆盖为 `FULL`）| WAL + NORMAL 仍能防进程崩溃丢数据，仅极端断电可能丢最后一个事务；FULL 会让每次提交等一次 fsync |
| `busy_timeout` | `15000`（毫秒，对齐既有 `connect_args={"timeout":15}`）| 把「隐含在连接参数里」的等待显式化，读代码的人不必再猜 |

**内存库必须跳过 WAL**：`TestConfig` 与 `tmp` 之外的用例全部用 `:memory:`，对其设 WAL 无意义。
判别方式**不猜 URI**，而是查连接自己的事实：

```python
row = cursor.execute("PRAGMA database_list").fetchone()   # (seq, name, file)
is_file_backed = bool(row and row[2])                      # 内存库 file 列为空串
```

`journal_mode` 的 `execute` 会返回一行结果，**必须 `fetchall()` 消费掉**，否则连接会持有未读游标。
若返回值不是 `wal`（网络盘 / 只读挂载），记一条 `warning` 并继续启动——**降级但不阻断**：
拿不到 WAL 不代表数据存不住，只是并发差一些。

**【评审 P1-3】取值与日志的来源，只能是进程级设施，不能是 Flask 设施。**
`_set_sqlite_pragma` 是挂在 `sqlalchemy.Engine` 上的**全局 connect 监听器**，它的触发时机是
「引擎首次连接 / 连接池补连 / 后台线程取连接」，**不保证处在 Flask 应用上下文里**。因此：

```python
import logging, os
_logger = logging.getLogger(__name__)            # ← 不是 app.logger / current_app.logger

_SYNCHRONOUS_ALLOWED = ("OFF", "NORMAL", "FULL", "EXTRA")

def _wanted_synchronous() -> str:
    raw = (os.environ.get("SQLITE_SYNCHRONOUS") or "NORMAL").strip().upper()
    return raw if raw in _SYNCHRONOUS_ALLOWED else "NORMAL"   # 坏值静默回落，不阻断启动
```

- 取值**只读 `os.environ`**。`config.py` 里的 `SQLITE_SYNCHRONOUS` 字段是**文档性镜像**——
  只服务 `/api/health` 展示与 README 表格，**不是 PRAGMA 的读取源**，字段旁必须写死这句注释，
  否则下一个人会去改 config 却发现 PRAGMA 纹丝不动。
- 白名单校验不可省：`PRAGMA synchronous=<值>` 是拼进 SQL 的字面量，允许任意环境变量值直通即是注入面。
- 日志用模块级 logger。它会被 `init_observability` 配置的 root handler 接住，输出格式与 `app.logger` 一致。

### 2.4 P-3｜崩溃残留软锁自愈

`services/persistence.py::release_stale_agent_locks(session) -> list[str]`：把所有 `Agent.status == "busy"`
的行改回 `"idle"`，提交，返回被解锁的 Agent 名列表供日志。启动时执行，由**配置项**
`RELEASE_STALE_LOCKS_ON_STARTUP`（默认 `true`，由同名环境变量在**进程启动时**初始化）门控。

**【评审 P1-5】「配置项」与「环境变量」不是一回事，本文档此后一律按下面的口径用词**：
`config.py` 的字段在**类定义（import）时**求值一次，此后改 `os.environ` 不再有任何影响。因此——

- **应用内**（`app.py` 启动序列、路由）一律读 `app.config[...]`；
- **测试**要改这些开关，一律**继承 config 子类覆盖类属性**（如 `class NoUnlockConfig(TestConfig): RELEASE_STALE_LOCKS_ON_STARTUP = False`），
  `monkeypatch.setenv` 对已导入的 `Config` **无效**，写了也是假绿；
- 只有**独立进程**（`tools/purge_demo_data.py`，见 §2.6 CLI 启动契约）才通过在 import 之前设置环境变量来影响配置；
- 唯一的例外是 §2.3 的 PRAGMA——它在 Flask 之外运行，只能读 `os.environ`。

**为什么在启动时做是安全的**：本项目是单进程开发部署（`app.run(threaded=True)`，README 明示），
进程刚起来时不可能有正在运行的 autopilot，因此此刻库里的每一个 `busy` 都必然是上次崩溃的残留。
**为什么要留开关**：将来若用 gunicorn 多 worker 部署，第二个 worker 启动会误解锁第一个 worker 正在跑的 Agent；
届时把该变量置 `false` 并改用带心跳时间戳的锁——这条升级判据写进模块 docstring。

**有意不做**：不把 `busy` 锁改成带 TTL 的租约。那是并发模型的改造，超出本轮范围，且会动 autopilot 的核心路径。

### 2.5 S-1｜新的 seed 契约：每类恰好一条

`seed.py::seed_if_empty()` 重写。幂等门**保持** `User.query.count() > 0 → return False`（不改判据，
存量库不会被二次 seed）。写入内容：

| 类别 | 保留的唯一一条 | 关键字段 |
|---|---|---|
| `users` | `admin` / `admin123` | `role=admin`, `display_name="Ada（管理员）"`, `is_active=True` |
| `agents` | `dev-agent` | `kind=dev`, `status=idle` |
| `projects` | `AragonTeam Platform` | `key=ARA`, `owner_id=admin.id` |
| `requirements` | 「示例需求：熟悉需求流转」 | `status=new`, `priority=medium`, **未指派**, `reporter_id=admin.id`, `position=0` |
| `bugs` | 「示例缺陷：熟悉 BUG 流转」 | `status=open`, `severity=major`, **未指派**, `reporter_id=admin.id`, `position=0` |
| `comments` | 挂在示例需求上的 1 条 | `author_type=agent`, `author_id=dev_agent.id`（**评审 P1-10 改**）|
| `activities` | 示例需求的 `created` | `actor=("user", admin.id)`, `to_status="new"` |
| `notifications` | 收件人 `admin` 的 1 条未读 | `type=commented`（**评审 P1-10 改**）, `entity=requirement`, `actor_type=agent`, `actor_id=dev_agent.id` |
| `notification_preferences` | **0 条**（有意）| 缺省全 `true` 由 `services/notification_prefs.py` 提供，无需落行 |

共 8 行（原 31 行）。四条设计约束：

1. **示例工单一律 `new`/`open` 且未指派。** 原 seed 把需求预置在 `testing`、把 BUG 预置在 `fixing` 并指派给 Agent，
   历史上多次造成「泊死单」（见 `feature-completeness` 与 `scale-and-project-scope` 两轮的救火）。未指派的
   `new` 单既能演示全流程，又不可能一启动就卡住。
2. **只留 `dev-agent`，不留 `qa-agent`。** 「每类一条」的字面要求。后果是 dev→qa 交接演示需要用户在
   Agents 页点一下「新建 Agent」——该入口早已存在（admin-console 轮次）。因为示例需求不指派、不进
   `testing`，所以**不会**出现「推到 testing 后无人接手」的卡死。这一取舍写进 README。
3. **只留 `admin` 一个账号。** 其余成员由管理台真实创建（`POST /api/users` 已具备）。
   `末任管理员不变量`（`lifecycle.would_orphan_admins`）因此变得更关键——它已实现，本轮不动。
4. **【评审 P1-10】示例评论与示例通知必须自洽，且不得违反平台自身的不变量。**
   只剩 `admin` 一个人类账号之后，v1 的写法（评论作者 `admin`、通知收件人 `admin`、`type=assigned`）有两处不成立：
   (a) 示例工单**未指派**，却告诉用户「指派给你」，点进去看到一张无人负责的单；
   (b) 收件人与施动者若同为 `admin`，就撞上 `services/notifications.py` 的「**不给自己发**」既有不变量——
   走 `notify()` 发不出来，绕过 `notify()` 直接落行则等于让示例数据违反平台自己的规则，是最坏的示范。
   故改为：**唯一的示例评论由 `dev-agent` 撰写**，**唯一的通知随之为 `type=commented`、actor 为 `dev-agent`、收件人 `admin`**。
   语义链完整闭合：admin 报了一张单 → dev-agent 在单下留言 → admin 收到「你的需求有新评论」。
   施动者是 Agent 而非人类，天然绕开自发自收，且顺带演示了「Agent 会在工单里说话」这一核心卖点。

**每写一行就登记一条 `SeedRecord`**（见 §5.2），在同一个事务里提交。

### 2.6 S-2｜存量 mock 清理工具

新增 `backend/tools/purge_demo_data.py`（可执行脚本，非蓝图）。

#### 2.6.0 CLI 启动契约（**评审 P0-2 新增；顺序不可换**）

本工具必须复用 `lifecycle.*`（`would_orphan_admins` / `agent_open_workload` / `delete_ticket_cascade`），
它们走 `Model.query`，**必须**有 Flask-SQLAlchemy 应用上下文。而 `backend/app.py:99` 有一行模块级
`app = create_app()`——**只要 `import app`，Python 就会立刻对「默认 `DATABASE_URL` 指向的库」执行
`create_all` + `schema_sync` + `seed_if_empty`（本轮还要加 `release_stale_agent_locks`）**。
天真地在文件顶部 `from app import create_app`，会同时造成两个后果：dry-run 也写库；
`--database-url` 指向 B 库时仍会顺手创建并播种 A 库。因此启动序列写死为：

```python
def main(argv=None) -> int:
    args = _parse_args(argv)                       # 1. 先解析参数，此时**尚未** import app
    url = args.database_url or os.environ.get("DATABASE_URL") or _default_url_from_config()
    if args.apply and not args.no_backup:
        backup_path = _backup_sqlite(url)          # 2. 备份用裸 sqlite3，不碰 ORM（见 §7 R-4）
    os.environ["DATABASE_URL"] = url               # 3. 三个开关必须在 import 之前落定
    os.environ["SEED_ON_STARTUP"] = "false"        #    绝不能让清理工具顺手播种
    os.environ["RELEASE_STALE_LOCKS_ON_STARTUP"] = "false"   # 清理不是运维解锁，别夹带副作用
    from app import create_app                     # 4. 此刻才 import：模块级 app 亦指向目标库
    from config import Config
    flask_app = create_app(Config)
    with flask_app.app_context():
        return _run(args)                          # 5. 全部 ORM 操作都在这个上下文里
```

- `_default_url_from_config()` **不 import `app`**，只 `from config import Config` 读 `SQLALCHEMY_DATABASE_URI`。
  `config.py` 无副作用（纯常量），可以安全早读。
- 即便如此，**dry-run 仍会有一次无害的写**：`create_all()` 会在存量库里建出空的 `seed_records` 表。
  这是必要的（否则查询登记表即 `no such table`），且不删任何行。**因此 §6.3-6 的验收判据从
  「库文件 mtime 不变」改为「各表行计数不变」**——mtime 判据在 v1 里是错的，实现者按它验收必然对不上。
- `--database-url` 若指向**不存在**的文件：dry-run 直接报「库不存在」退出码 1，不创建空库
  （用户几乎总是路径写错了，替他建一个空库只会掩盖问题）。

#### 2.6.1 算法

```
1. 解析 DATABASE_URL → 若非 sqlite 且未给 --no-backup → 退出码 1 并提示
2. --apply 时：sqlite3.connect(src).backup(sqlite3.connect(bak))  ← 一致性备份，见 §7 R-4
   备份名 aragon.db.bak-YYYYmmddHHMMSS，与源库同目录；**在 import app 之前完成**（§2.6.0）
3. 候选集 = rows(seed_records) ∪ match(LEGACY_FINGERPRINT)
   - LEGACY_FINGERPRINT 是冻结的历史常量表（旧 seed 的 7 条需求标题、5 个 BUG 标题、
     4 个用户名、2 个 Agent 名、项目 key "ARA"）
   - seed_records 里指向已不存在实体的孤儿行：apply 时顺带删除（幂等）；
     **dry-run 时只统计不删**（评审 P2-13）
4. 【评审 P0-1】「每类留一」**只适用于有出身证明的五类**：users / agents / projects /
   requirements / bugs。这五类按 id 升序保留第 1 条，其余进入删除集
5. 执行删除（单事务，顺序不可换）：
   a. requirements / bugs → lifecycle.delete_ticket_cascade() + session.delete(ticket)
   b. session.flush()            ← 【评审 P1-7】守卫必须在工单已删之后求值
   c. comments / activities / notifications → 见 2.6.2，**不做计数裁剪**
   d. agents → 有未终态在手工单则跳过并在报告中说明（复用 lifecycle.agent_open_workload）
   e. users → 见 2.6.3
6. 报告：每类「保留 1 / 删除 N / 跳过 M（原因）」，dry-run 时打印 [DRY-RUN] 前缀且不提交
```

**为什么 5b 的 `flush()` 不能省（评审 P1-7）**：legacy 库里 `qa-agent` 名下有一张 `fixing` 的 BUG
（`seed.py:92`），它本身就在删除集里。若在删工单**之前**评估 `agent_open_workload(qa_agent.id)`，
它会返回 1，qa-agent 被判「仍有在手工单」而永远跳过——「每类留一」达不成，且用户会看到一条
指向已被同一次运行删掉的工单的 skip 理由，无从理解也无从处置。`flush()` 让守卫看见的是**删除后的世界**。

#### 2.6.2 评论 / 审计 / 通知：绝不按计数裁剪（**评审 P0-1，本轮最重要的修正**）

v1 把「每类留一」也套在 `comments` / `activities` / `notifications` 上。这是**会造成不可逆数据丢失的错误**：
这三张表里绝大多数行是用户在真实使用中产生的——审计时间线是本平台自称的核心价值，讨论是协作的全部内容——
而它们**没有任何出身标记**（不进指纹表，v1 §5.3 末句自己也承认），照 v1 实现，`--apply` 会把用户几个月的
审计轨迹删到只剩一条。这与 §7 R-3「不误删用户真实数据」正面冲突。

v2 的规则：**这三类只删下面三种行，其余一律不动，不做任何计数裁剪。**

| 来源 | 判据 | 说明 |
|---|---|---|
| 有登记 | 该行 id 在 `seed_records` 中 | v2 及以后的 seed 写入的行，出身确凿 |
| 被级联 | 其所属实体（`entity_id`）在本次工单删除集中 | 由 `delete_ticket_cascade` 带走，与既有删单行为一字不差 |
| 是孤儿 | `entity_id` 指向的实体已不存在 | 历史遗留脏数据，删掉是净收益；幂等 |

**代价与接受理由**：存量（v1）库里挂在**被保留**的那条示例需求上的旧演示评论 / 审计会残留。
实测这不是问题——v1 的 4 条示例评论全部挂在 `requirements[2]`（「接入 dev-agent 自动认领需求」，
`seed.py:125`），它不是 id 最小的一条，必然进删除集，评论随级联一起消失；4 条示例审计里 3 条挂在
被删的需求上，仅 `requirements[0]` 的那条 `created` 会留下——而它**正好**就是「每类保留一条示例」所要的那条。
即便某天残留了一两条旧演示评论，代价也只是「示例数据多了一条」；反过来把真实审计删光是不可逆的。
**这个不对称就是选择保守规则的全部理由。**

#### 2.6.3 用户的特殊处理

（本工具最重要的安全阀）`users.id` 被 `requirements.reporter_id`、`bugs.reporter_id`、
`projects.owner_id` 真外键引用，且 `PRAGMA foreign_keys=ON`——硬删必 `IntegrityError`。且删干净就等于销毁
审计轨迹，与平台核心价值直接冲突。因此：

- 若某 seed 用户**仍被任何未被删除的行引用**（reporter / owner / comment.author / activity.actor / notification 收件人或 actor）
  → **停用**（`is_active=False`），不删除，报告里如实写「停用（仍被 3 条需求引用）」。
- 否则才删除。
- 无论哪条路径，先过 `lifecycle.would_orphan_admins` 守卫；会导致有效管理员归零则**跳过**该用户并报告。
- 「每类留一」在 users 上恒保留 id 最小者（存量库即 `admin`），因此**清理后 `users` 数量恒 ≥ 1**，
  `seed_if_empty()` 的幂等门（`User.query.count() > 0`）不会被意外打开、不会二次播种。这条是设计保证，不是巧合。

**默认 dry-run**：不带任何参数即等价 `--dry-run`。只有显式 `--apply` 才写库。这条不可配置。

**悬空指派的告知义务（评审 P2-11）**：`assignee_type/assignee_id` 是多态**软引用**（无外键），
删掉 `qa-agent` 会让「真实工单上指向它的终态单」留下查不到的 assignee——这与既有 `DELETE /api/agents`
的行为一致（本轮不改那条既有语义），但 purge 是批量的，用户更难察觉。因此报告中**必须**多打一行
`dangling assignments: requirements N, bugs M`，让人在 `--apply` 之前看见。只提示，不阻断。

### 2.7 抽取 `delete_ticket_cascade`（消除第二份真相）

`routes/requirements.py::delete_requirement`（:278-297）与 `routes/bugs.py::delete_bug` 各内联了一份级联清理逻辑。
purge 工具是第三个调用点——再复制一份就必然漂移。本轮把它抽到
`services/lifecycle.py::delete_ticket_cascade(entity: str, ticket) -> dict`，两个路由改为调用它。

**【评审 P1-6】完整函数契约（v1 未定义，照 v1 抽取做不到「行为不变」）**：

```python
def delete_ticket_cascade(entity: str, ticket) -> dict:
    """清理一张工单的全部引用，**但不删除工单本体**。

    Args:
        entity: "requirement" | "bug"。
        ticket: Requirement / Bug 实例（调用方保证非 None）。

    Returns:
        {"comments": int, "notifications": int, "activities": int} —— 各表实际删除的行数。

    契约（三条，逐条对应一个曾经踩过的坑）：
    1. **不 commit**，也**不 db.session.delete(ticket)**。工单本体由调用方删除——
       路由要在删除后返回 204，purge 要把几十张单放进同一个事务，两者对「何时删本体、
       何时提交」的诉求不同，服务层不替调用方决定。
    2. `Bug.related_requirement_id` 置空**只在 entity == "requirement" 时执行**。
       实测 routes/bugs.py::delete_bug **没有**这一步（BUG 不被别的 BUG 引用），
       无条件执行等于给 BUG 删除路径加了一次多余的全表 UPDATE —— 那就是行为漂移。
    3. 顺序逐字保留原路由：related 置空 → comments → notifications → activities。
    """
```

**行为逐字保持不变**，两条既有删除用例（`test_requirements.py` / `test_bugs.py`）即为回归护栏；
`git diff` 应显示两个路由侧净减行数、服务层净增。

---

## 3. 文件 / 模块变更计划

| 文件 | 动作 | 意图（一句话）|
|---|---|---|
| `backend/services/persistence.py` | 新增 | 存储自省（`describe_storage`）、启动日志、崩溃残留 busy 锁自愈 |
| `backend/models/seed_record.py` | 新增 | `SeedRecord` 模型：登记每条种子行的出身，供清理工具精确定位 |
| `backend/tools/__init__.py` | 新增 | 空包声明，让 `python tools/purge_demo_data.py` 与 `python -m tools.purge_demo_data` 都可用 |
| `backend/tools/purge_demo_data.py` | 新增 | 存量 mock 数据清理 CLI（默认 dry-run + 一致性备份 + 五类各留一；评论/审计/通知只清「登记∪级联∪孤儿」，见 §2.6.2）|
| `backend/tests/test_persistence.py` | 新增 | **真实文件库**上的重启存活 / 幂等 / PRAGMA / 锁自愈回归 |
| `backend/tests/test_seed_minimal.py` | 新增 | 新 seed 契约：每类恰好 1 条 + 登记齐全 + 二次启动不重复 |
| `backend/tests/test_purge_demo_data.py` | 新增 | 清理工具：dry-run 不删行、五类各留一、**真实评论/审计/通知零损伤（P0-1 护栏）**、被引用用户停用而非删除 |
| `backend/extensions.py` | 修改 | connect 钩子扩展 WAL / synchronous / busy_timeout，内存库跳过并降级告警 |
| `backend/seed.py` | 修改 | 重写为每类 1 条（31 行 → 8 行）+ 同事务登记 `SeedRecord` |
| `backend/models/__init__.py` | 修改 | 导出 `SeedRecord`，确保 `create_all` 能看到新表 |
| `backend/app.py` | 修改 | 启动序列插入 `log_storage_summary` 与 `release_stale_agent_locks`；`/api/health` additive `storage` 块 |
| `backend/config.py` | 修改 | 新增 `RELEASE_STALE_LOCKS_ON_STARTUP`（真开关，应用内读 `app.config`）与 `SQLITE_SYNCHRONOUS`（**文档性镜像**，PRAGMA 的真实读取源是 `os.environ`，见 §2.3 评审 P1-3）|
| `backend/services/lifecycle.py` | 修改 | 抽取 `delete_ticket_cascade`，成为工单级联删除的唯一真相 |
| `backend/routes/requirements.py` | 修改 | 删除路由改调 `delete_ticket_cascade`（行为不变）|
| `backend/routes/bugs.py` | 修改 | 同上 |
| `backend/tests/conftest.py` | 修改 | 新增 `file_app` fixture（tmp_path 上的**文件**库 + 开启 seed），供持久化用例使用 |
| `frontend/app/login/page.tsx` | 修改 | 演示账号快捷登录从 4 条改为 1 条（`admin`）|
| `.gitignore` | 修改 | 补 `*.db-wal` / `*.db-shm` / `*.db.bak-*`，WAL 附属文件与备份不入库 |
| `README.md` | 修改 | 默认账号表改 1 行、内置 Agent 改 1 个、`DATABASE_URL` 默认值写清绝对路径语义、新增「示例数据与清理」小节 |

**不改**：`services/workflow.py`（状态机圣域，一字不动）、`services/schema_sync.py::ADDITIVE_COLUMNS`
（本轮**零新增列**，只新增一张表 → `create_all` 自动处理，无需登记；这条已按 CLAUDE.md 的硬约束核对过）。

---

## 4. 接口设计

### 4.1 REST（唯一变更：`GET /api/health` additive）

```jsonc
// 200 OK —— 既有字段全部保持字面不变
{
  "status": "ok",
  "service": "aragonteam-backend",
  "db": "ok",
  "llm": { "enabled": false, "provider": "none", "model": null },
  "storage": {                       // ← 本轮新增，只读，永不含路径
    "persistent": true,              // false ⇔ 库是 :memory:，重启即失忆
    "journal_mode": "wal",           // PRAGMA 读回的真实值，可能是 "delete"（降级）
    "synchronous": "NORMAL",
    "foreign_keys": true
  }
}
```

**【评审 P1-4】字段取值与失败路径（v1 只给了示例值，照抄会写出错误类型且会让探针 500）**：

| 字段 | 来源 | 转换 | 备注 |
|---|---|---|---|
| `persistent` | `describe_storage(uri)["persistent"]` | 已是 `bool` | 纯字符串判断，不打库 |
| `journal_mode` | `PRAGMA journal_mode` | 原样小写字符串（`"wal"` / `"delete"`）| 启动期读一次并缓存 |
| `synchronous` | `PRAGMA synchronous` | **返回整数**，按 `{0:"OFF",1:"NORMAL",2:"FULL",3:"EXTRA"}` 映射；未知值输出 `str(原值)` | v1 直接写 `"NORMAL"` 是错的 |
| `foreign_keys` | `PRAGMA foreign_keys` | **返回 0/1**，转 `bool` | v1 直接写 `true` 是错的 |

- **自省失败绝不改变健康检查的成败判据**：整个 `storage` 块包在 `try/except Exception` 里，
  任一 PRAGMA 抛错则降级为 `{"persistent": <字符串判断结果>, "journal_mode": "unknown",
  "synchronous": "unknown", "foreign_keys": null}` 并记 `warning`。
  **HTTP 状态码仍只由既有的 `SELECT 1` 决定**（200 / 503）——一个探针端点因为「自省自己」而 500，
  是本轮能犯的最讽刺的错误。
- **【评审 P2-12】三个 PRAGMA 在启动期（`create_app` 的 `app_context` 内）读一次，缓存进
  `app.config["STORAGE_INFO"]`**，请求路径只读缓存。这些值在进程生命周期内不会变，
  没有理由让每一次 k8s / 探针心跳都多打三次库。

**无新增写端点**。批量破坏性清理**有意不做成 HTTP 面**——它没有幂等语义、没有回滚入口，
一个手滑的 `curl` 就能清掉生产演示环境；离线 CLI 天然要求人在服务器上，且能强制 dry-run。

### 4.2 CLI

```bash
# 在 backend/ 目录下执行（PowerShell / cmd / bash 通用，不含任何 shell 特有语法）
python tools/purge_demo_data.py                 # 默认 dry-run：只报告，不写库
python tools/purge_demo_data.py --apply         # 备份后真正执行
python tools/purge_demo_data.py --apply --json  # 机器可读报告（供 CI / 上层编排消费）
python tools/purge_demo_data.py --apply --no-backup
```

| 参数 | 默认 | 语义 |
|---|---|---|
| `--dry-run` / `--apply` | `--dry-run` | 互斥；不给参数即 dry-run |
| `--no-backup` | 关 | 跳过备份（非 SQLite 库时**必须**显式给出）|
| `--json` | 关 | 报告输出为 JSON |
| `--database-url URL` | 取 `DATABASE_URL` 或 config 默认 | 指定库，供测试与多环境 |

退出码：

| 码 | 含义 |
|---|---|
| `0` | 正常结束，且**没有**任何守卫跳过 |
| `1` | 参数错误 / 库不存在 / 前置校验失败（未执行任何删除）|
| `2` | 正常结束，但**存在**守卫跳过（末任管理员 / Agent 仍有在手工单）|

**【评审 P1-8】退出码与 `--dry-run` / `--apply` 无关**，只反映「本次是否存在守卫跳过」。
v1 把 `2` 描述成「部分跳过（即部分执行）」，同时又要求 `test_dry_run_writes_nothing` 断言退出码 `0`——
而 dry-run 在存量库上几乎必然产生跳过，两条规格互相打架。现在的口径下，同一个库
dry-run 与 apply 拿到**同一个退出码**，这也正是 dry-run 该有的语义：预演结果必须能预测真实结果。

报告格式（人类可读）：

```
[DRY-RUN] AragonTeam demo-data purge — sqlite:///.../backend/aragon.db
  users          keep admin(1)          delete 0    deactivate 3 (pm/alice/bob, 仍被引用)
  agents         keep dev-agent(1)      delete 1    skip 0
  projects       keep ARA(1)            delete 0    skip 0
  requirements   keep #1                delete 6    skip 0
  bugs           keep #1                delete 4    skip 0
  ——— 以下三类不做计数裁剪，只清「登记的 / 被级联的 / 孤儿」（§2.6.2）———
  comments       seeded 0  cascaded 4  orphan 0     kept(真实) 12
  activities     seeded 0  cascaded 9  orphan 0     kept(真实) 31
  notifications  seeded 0  cascaded 5  orphan 1     kept(真实) 6
未受影响的真实数据：requirements 3, bugs 2, comments 12, activities 31, notifications 6
dangling assignments（指向被删 Agent 的终态单）：requirements 0, bugs 1
提示：加 --apply 执行；执行前会自动备份到 aragon.db.bak-<时间戳>
```

报告有两处是刻意设计的，实现时不得省略：
最后的「未受影响的真实数据」让操作者在按下 `--apply` **之前**就能核对「我自己建的那几张单确实不在删除集里」；
`comments/activities/notifications` 三行**按来源拆开**而不是给一个总数，是为了让人一眼看出
「这三类没有被按数量裁剪过」——把 §2.6.2 那条安全规则做成肉眼可验证的，而不只是文档里的一句承诺。

---

## 5. 数据模型

### 5.1 无列变更

本轮**不新增任何列**，因此 `services/schema_sync.py::ADDITIVE_COLUMNS` 保持两条不变。
（CLAUDE.md 的硬约束是「加列必须登记」，加表不适用——`db.create_all()` 会建**不存在的表**，
这正是 Phase-3 新增 `notifications` 时走过的路径。）

### 5.2 新表 `seed_records`

```sql
CREATE TABLE seed_records (
    id           INTEGER      NOT NULL PRIMARY KEY,
    entity_type  VARCHAR(32)  NOT NULL,      -- user|agent|project|requirement|bug|comment|activity|notification
    entity_id    INTEGER      NOT NULL,      -- 多态引用，与 comments/notifications 的既有惯例一致，不建真外键
    seed_version VARCHAR(16)  NOT NULL,      -- 写入时的 seed 契约版本，本轮为 "2"
    created_at   DATETIME     NOT NULL,
    CONSTRAINT uq_seed_records_entity UNIQUE (entity_type, entity_id)
);
CREATE INDEX ix_seed_records_entity_type ON seed_records (entity_type);
```

模型（`models/seed_record.py`）：

```python
class SeedRecord(db.Model):
    __tablename__ = "seed_records"
    __table_args__ = (db.UniqueConstraint("entity_type", "entity_id", name="uq_seed_records_entity"),)
    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(32), nullable=False, index=True)
    entity_id = db.Column(db.Integer, nullable=False)
    seed_version = db.Column(db.String(16), nullable=False, default=SEED_VERSION)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    @staticmethod
    def mark(entity_type: str, entity_id: int) -> "SeedRecord": ...
```

**不建真外键的理由**：`entity_type` 是多态判别列，SQLite 无法为多态引用建约束；
且真外键会让「用户删掉示例需求」这一完全合法的操作被外键挡住。孤儿记录由 purge 工具在第 3 步顺带清理。

**不暴露给任何 REST 端点**：它是内部出身元数据，没有任何 UI 需要它。

### 5.3 冻结常量：历史 seed 指纹

放在 `tools/purge_demo_data.py` 顶部，附**不得修改**的注释：

```python
# 【冻结常量】v1 seed（2026-07 之前）写入的行的指纹。存量库里这些行没有 seed_records
# 登记，只能靠内容匹配。本表**只读、只增不改**：改了会让老库里的旧演示数据永远删不掉。
# 新 seed 一律靠 seed_records 识别，禁止再往这里加条目。
LEGACY_FINGERPRINT = {
    "user":        ("admin", "pm", "alice", "bob"),
    "agent":       ("dev-agent", "qa-agent"),
    "project_key": ("ARA",),
    "requirement": ("搭建 AragonTeam 项目骨架", "需求看板支持拖拽排序", "接入 dev-agent 自动认领需求",
                    "统一全局错误响应契约", "BUG 看板与需求看板打通", "导出协作活动时间线报表",
                    "修复登录态刷新丢失问题"),
    "bug":         ("拖拽后偶发卡片位置错乱", "Agent 指派后头像不显示", "看板列计数未实时刷新",
                    "登录 token 过期未跳转", "次要文案错别字"),
}
```

匹配用**精确相等**，不用 `LIKE`/前缀——用户完全可能新建一张标题里含「拖拽」的真单，模糊匹配会误伤。

**【评审 P0-1】`comments` / `activities` / `notifications` 不进指纹表，因此它们也【绝不】按「每类留一」处理。**
v1 这里原本写着「剩余的按每类留一规则处理」——那一句会让 `--apply` 删光用户真实的审计与讨论，
是本轮评审发现的唯一 P0。正确规则见 §2.6.2：只删「已登记 ∪ 被级联 ∪ 孤儿」，其余一行不动。
**没有出身证明的行，一律推定为真实数据。** 这条推定方向不可反转。

**【评审 P2-16】关于 `project_key: ("ARA",)`**：新 seed 的示例项目**有意沿用同一个 key `ARA`**
（新库靠 `seed_records` 识别，指纹表只服务存量库，两条路径互不干扰）。
`Project.key` 有 `unique=True`（`models/project.py:10`），库里不可能同时存在两个 `ARA`，
因此「每类留一」在 projects 上恒等于「保留这一个」，不存在把用户真实项目误判成演示项目的路径。

---

## 6. 测试与验收标准

### 6.1 新增用例（backend/pytest）

`tests/conftest.py` 新增 fixture：

```python
@pytest.fixture
def file_app(tmp_path):
    """真实文件库上的 app 工厂：反复调用即模拟「进程重启」，库文件跨次保留。

    【评审 P1-5】开关一律用 config 子类属性覆盖（**不是** monkeypatch.setenv）——
    Config 的字段在 import 时求值，用例里改环境变量对已导入的类无效，写了也是假绿。
    【评审 P2-15】每次重建前 dispose 上一个引擎：Windows 上 SQLite 文件句柄未释放会让
    tmp_path 清理抛 PermissionError（本项目主力平台是 Windows，这不是理论风险）。
    """
    db_path = tmp_path / "aragon.db"
    made = []

    def _make(seed=True, **overrides):
        if made:                                  # 上一个 app 先彻底放掉连接，再模拟重启
            with made[-1].app_context():
                db.session.remove()
                db.engine.dispose()
        attrs = {
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path.as_posix()}",
            "SEED_ON_STARTUP": seed,
            "TESTING": True,
            **overrides,                          # 如 RELEASE_STALE_LOCKS_ON_STARTUP=False
        }
        FileConfig = type("FileConfig", (Config,), attrs)
        app = create_app(FileConfig)
        made.append(app)
        return app

    yield _make, db_path

    for app in made:                              # teardown：确保没有句柄留在 tmp_path 上
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
```

| 文件 | 用例 | 断言 |
|---|---|---|
| `test_persistence.py` | `test_written_row_survives_app_restart` | 第一个 app 里建需求 → dispose → 第二个 app 里仍能查到，标题一致 |
| | `test_second_start_does_not_reseed` | 连起两次 app，`Requirement.query.count()` 恒为 1，`SeedRecord` 不翻倍 |
| | `test_file_backed_db_enables_wal_and_foreign_keys` | `PRAGMA journal_mode` == `wal`，`PRAGMA foreign_keys` == 1 |
| | `test_memory_db_skips_wal_without_error` | `TestConfig` 下建 app 不抛异常，`journal_mode` 不是 `wal` |
| | `test_health_reports_persistent_storage` | 文件库 → `storage.persistent is True`；内存库 → `False`；**响应体不含任何路径** |
| | `test_stale_busy_agent_is_released_on_startup` | 手改库把 Agent 置 `busy` → 重启 app → 变回 `idle` |
| | `test_stale_lock_release_can_be_disabled` | 以 `file_app(..., RELEASE_STALE_LOCKS_ON_STARTUP=False)` 重启 → `busy` 保持（**评审 P1-5**：用 config 子类属性，不用环境变量）|
| | `test_health_storage_survives_pragma_failure` | **评审 P1-4**：打桩让 PRAGMA 抛错 → `/api/health` 仍 200，`storage.journal_mode == "unknown"` |
| `test_seed_minimal.py` | `test_seed_writes_exactly_one_row_per_category` | 8 类各 `count() == 1`，`notification_preferences` 为 0 |
| | `test_seed_ticket_is_unassigned_and_initial` | 需求 `status=new` 且 `assignee_type is None`；BUG `status=open` 同理 |
| | `test_seed_registers_every_row` | `SeedRecord.query.count() == 8` 且每条都指向存在的实体 |
| | `test_seed_notification_actor_is_not_the_recipient` | **评审 P1-10**：唯一通知的 `actor_type == "agent"`、收件人 `admin`、`type == "commented"`，不违反「不给自己发」不变量 |
| | `test_admin_can_login_with_seeded_credentials` | `POST /api/auth/login {admin, admin123}` → 200 |
| `test_purge_demo_data.py` | `test_dry_run_writes_nothing` | 跑完**各表行计数不变**（**评审 P1-8**：不断言退出码；**评审 P0-2**：允许 `create_all` 建出空的 `seed_records` 表）|
| | `test_dry_run_and_apply_agree_on_exit_code` | **评审 P1-8**：同一个库上 dry-run 与 apply 的退出码相同 |
| | `test_apply_keeps_exactly_one_per_category` | 灌入 v1 风格演示数据 → `--apply` → users/agents/projects/requirements/bugs 各恰好 1 条 |
| | `test_apply_never_touches_real_rows` | 混入 3 条用户真实需求 → 清理后 3 条全在，id 不变 |
| | **`test_apply_never_prunes_real_activities_and_comments`** | **评审 P0-1 的回归护栏（最重要的一条）**：灌 20 条用户真实 `Activity` + 12 条真实 `Comment` + 6 条真实 `Notification`（均挂在**被保留**的工单上）→ `--apply` → 三类**一条不少**；若有人把「每类留一」改回这三类上，本用例必红 |
| | `test_referenced_seed_user_is_deactivated_not_deleted` | 被 reporter_id 引用的 pm → 仍在库，`is_active is False` |
| | `test_purge_never_orphans_admins` | 构造「唯一 admin 也在删除集」→ 该用户被跳过，退出码 2 |
| | `test_agent_with_only_deleted_open_tickets_is_removed` | **评审 P1-7**：qa-agent 名下唯一的 `fixing` BUG 本身就在删除集 → flush 后守卫放行，qa-agent 被删而非跳过 |
| | `test_cascade_removes_orphan_comments_and_activities` | 被删需求的评论 / 审计 / 通知全清零 |
| | `test_orphan_seed_records_are_reported_but_not_deleted_on_dry_run` | **评审 P2-13**：dry-run 后 `seed_records` 计数不变 |
| | `test_backup_file_created_before_apply` | `--apply` 后同目录出现 `aragon.db.bak-*` 且可独立打开 |
| | `test_target_database_url_does_not_touch_default_db` | **评审 P0-2**：`--database-url` 指向 tmp 库运行后，默认库路径**不被创建** |

### 6.2 回归门禁（必须全绿）

```powershell
cd backend
pytest -q            # 判据见下
```

**【评审 P1-9】门禁判据是相对的，不是一个写死的数字。** v1 写「≥315 既有用例」；实测
`backend/tests/test_*.py` 共 **327** 个 `def test_`（parametrize 展开后更多），而 `CLAUDE.md`
的质量门禁一节写的是 **93**——三个数字互不相同，说明写死的计数只会随时间腐化成噪音。故门禁定为：

> **落地前先跑一次 `pytest -q` 记下基线；落地后：失败数为 0，且用例总数 ≥ 基线 + 本轮新增（~22 例）。**

顺带提示实现者：`CLAUDE.md` 里「93 cases」已严重陈旧，建议在本轮 PR 里一并订正
（本次评审只改 `spec.md`，不动代码与其他文档）。
```
cd frontend
npm run typecheck    # tsc --noEmit → 0 error
npm run build        # next build → 16/16 页成功
```

### 6.3 人工验收清单（逐条可复核）

1. 删掉 `backend/aragon.db` 后启动后端 → 日志出现 `storage: sqlite file=<绝对路径> exists=False`，
   随后库被创建，8 条种子行写入。
2. `GET /api/health` → `storage.persistent === true`、`storage.journal_mode === "wal"`，**响应体里搜不到任何路径串**。
3. 用 `admin/admin123` 登录 → 需求列表 1 条、BUG 列表 1 条、项目 1 个、Agents 1 个、团队 1 人、铃铛 1 条未读。
4. 新建一条需求，`Ctrl+C` 强杀后端，重新启动 → 该需求仍在，且列表仍是「1 条示例 + 1 条自己的」。
5. 在 Agents 页点「自动一轮」的**同时**强杀进程 → 重启后该 Agent 状态为 `idle`（不是永久 `busy`）。
6. 在**存量**库上跑 `python tools/purge_demo_data.py` → 报告列出每类保留 1 / 删除 N，且「未受影响的真实数据」
   与自己实际建过的单数吻合；**各表行计数一条不变**（dry-run 不删任何行）。
   **【评审 P0-2】判据是「行计数不变」而非 v1 写的「库文件 mtime 不变」**——工具必须建出空的
   `seed_records` 表才能查登记（§2.6.0），mtime 必然变化，按 v1 验收必然对不上。
7. `python tools/purge_demo_data.py --apply` → 生成 `aragon.db.bak-*`；重启后端，每类恰好 1 条示例，
   自建数据一条不少；`pm/alice/bob` 显示为「已停用」而非消失（其提交过的单的 reporter 仍可读）。
8. **【评审 P0-1】清理前后各打开一次工单详情抽屉**：自己写过的评论、时间线上自己操作过的审计记录
   **一条不少**（这三类永不按计数裁剪）。这是本轮最该由人肉眼确认一次的事。
9. 重复执行 `--apply` → 第二次报告全为 `delete 0`（幂等），不报错，退出码与第一次一致。

---

## 7. 风险与缓解

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R-1 | WAL 在网络盘 / 只读挂载 / 某些云同步目录上不可用 | 启动即失败 | PRAGMA 结果**读回校验**，非 `wal` 只记 `warning` 并继续；`/api/health` 如实报告真实 journal_mode，不粉饰 |
| R-2 | `synchronous=NORMAL` 在**掉电**时可能丢最后一个事务 | 极端场景数据丢失 | 明示取舍；提供 `SQLITE_SYNCHRONOUS=FULL` 一键回到原语义；进程崩溃（远比掉电常见）在 WAL+NORMAL 下**不丢** |
| R-3 | purge 工具误删用户真实数据 | 不可逆 | 四重保险：默认 dry-run、精确相等匹配（不用 LIKE）、`--apply` 前自动备份、报告先列「未受影响的真实数据」供人核对 |
| R-4 | 直接 `shutil.copy` 一个正在写的 SQLite 会得到撕裂副本（WAL 下尤甚）| 备份不可用 | 备份必须用 `sqlite3.Connection.backup()` 在线备份 API，它对 WAL 与并发写是安全的；`test_backup_file_created_before_apply` 断言备份可独立打开并查得到表 |
| R-5 | 启动自动解锁 `busy` 在多进程部署下会误解锁正在跑的 Agent | 并发推进错乱 | `RELEASE_STALE_LOCKS_ON_STARTUP` 开关 + 模块 docstring 写死升级判据（换多 worker 就必须换成带心跳的租约锁）|
| R-6 | seed 账号从 4 个减到 1 个，README / 登录页 / 团队页演示体验改变 | 文档与实现脱节 | 同一 PR 内改 README 默认账号表、登录页快捷登录、并在「示例数据与清理」小节写明「其余成员请在团队页创建」；`tests/conftest.py` 自建 fixture，**不依赖 seed**，315 个既有用例零影响 |
| R-7 | 只留 `dev-agent`，dev→qa 交接的开箱演示消失 | 首次体验缩水 | 示例需求为 `new` 且未指派，**不会**推进到 `testing` 后卡死；README 写明「需要演示交接请在 Agents 页一键新建 qa-agent」|
| R-8 | `LEGACY_FINGERPRINT` 随时间僵化，被误当成「新 seed 也要往里加」| 老库清不干净 / 新库误删 | 常量表加「冻结、只读、禁止新增」注释；新 seed 一律走 `seed_records`，两条路径在代码里物理分离 |
| R-9 | `seed_records` 与实体删除不同步，留下孤儿记录 | 清理工具统计失真 | purge 第 3 步先剔除孤儿并顺带删除（幂等）；不给 `seed_records` 建真外键正是为了让「用户删掉示例需求」这一合法操作不被挡 |
| R-10 | 抽取 `delete_ticket_cascade` 时行为漂移 | 删单回归 | 抽取**逐字保留**原逻辑（含 `related_requirement_id` 置空的顺序），既有两条删除用例即回归护栏；`git diff` 应显示路由侧净减行数 |
| R-11 | 用户在 `--apply` 之后想要回演示数据 | 无法恢复 | 备份文件即恢复路径（文档给出 `copy aragon.db.bak-<ts> aragon.db`）；另可删库重启由新 seed 重建 8 行 |
| R-12 | **（评审 P0-1）** 后人「顺手统一一下」，把「每类留一」重新套回 comments / activities / notifications | 用户真实审计与讨论被不可逆删除 | §2.6.2 把规则与理由写死；`test_apply_never_prunes_real_activities_and_comments` 是专门为这条规则设的护栏用例；报告按来源分行打印，让违规**肉眼可见** |
| R-13 | **（评审 P0-2）** 后人把 `from app import create_app` 提到文件顶部，破坏 CLI 启动契约 | dry-run 写库；误创建/播种非目标库 | `import` 语句就地加注释说明为何必须延迟；`test_target_database_url_does_not_touch_default_db` 会在提前 import 时变红 |
| R-14 | 删除 Agent 在真实终态工单上留下悬空 `assignee_id`（多态软引用无外键）| UI 显示未知指派人 | 与既有 `DELETE /api/agents` 行为一致，本轮不改该语义；报告增打 `dangling assignments` 计数，让人在 `--apply` 前知情（§2.6.3）|

---

## 8. 实施顺序（建议）

1. `models/seed_record.py` + `models/__init__.py` 导出 → 跑一次 `pytest -q` 确认建表不破坏任何既有用例。
2. `services/persistence.py` + `extensions.py` PRAGMA + `app.py` 启动序列与 health additive → `test_persistence.py`。
3. `services/lifecycle.py::delete_ticket_cascade` 抽取 + 两个路由改调用 → 既有删除用例仍绿。
4. `seed.py` 重写 + `test_seed_minimal.py`。
5. `tools/purge_demo_data.py` + `test_purge_demo_data.py`。
6. 前端登录页 + `.gitignore` + README 收尾，跑完整门禁。

每一步结束都应能独立通过 `pytest -q`——**不允许出现「中间状态是坏的、最后一步才修好」的提交**。

**评审补充的落地要求**：第 5 步（purge 工具）请**先写 `test_apply_never_prunes_real_activities_and_comments`
再写实现**——它是 P0-1 的护栏，也是本轮唯一一条「写反了就会不可逆删数据」的规则，
符合 `CLAUDE.md` 七「修 bug 先写复现用例」的精神（这里是「防 bug 先写护栏用例」）。

---

## 9. 评审结论（Review Verdict）

**结论：有条件通过（Approved with conditions）。**

v1 的整体方向、问题诊断与取舍质量都很高：把「清演示数据」正确地识别为「先解决怎么区分真假」的问题，
拒绝把批量破坏性操作做成 HTTP 端点，坚持默认 dry-run 与在线备份 API，为「只留 1 个 Agent / 1 个账号」
逐条推演了后果并写进 README——这些都是对的。评审发现的问题集中在**实现细节与仓库现实的咬合处**，
而非方向性错误，因此不打回重做，全部 P0 / P1 已在 v2 正文中直接改掉。

放行条件（合入前必须逐条满足，缺一不可）：

1. **§2.6.2 的规则不得被弱化**：`comments` / `activities` / `notifications` 永不按计数裁剪，
   且 `test_apply_never_prunes_real_activities_and_comments` 必须存在并通过。
   这是唯一一条「写错了就不可逆」的规则，也是本次评审的唯一 P0-1。
2. **§2.6.0 的 CLI 启动契约按序实现**，且 `test_target_database_url_does_not_touch_default_db` 通过——
   证明工具不会碰非目标库、dry-run 不删任何行。
3. **§2.3 的 PRAGMA 只读 `os.environ`、日志用模块级 logger**，`config.py` 中的
   `SQLITE_SYNCHRONOUS` 必须带「文档性镜像，非读取源」的注释。
4. **§4.1 的 `storage` 块带整数→字面量映射与整块 try/except**，且
   `/api/health` 的 HTTP 状态码判据不因自省失败而改变（`test_health_storage_survives_pragma_failure` 通过）。
5. **测试里的开关一律用 config 子类属性覆盖**，仓库中不得出现用 `monkeypatch.setenv` 改
   `RELEASE_STALE_LOCKS_ON_STARTUP` / `SEED_ON_STARTUP` 的用例（那是假绿）。
6. **§6.3 人工验收第 6、8 条必须真人执行一次**（行计数不变、真实评论与审计一条不少），
   并把结果贴进 PR 描述。自动化用例覆盖不了「操作者是否看得懂报告」这件事。
7. 合入前跑满 §6.2 门禁：`pytest -q` 零失败且总数不减、`npm run typecheck`、`npm run build` 全绿。

不作为放行条件、但建议同 PR 顺手处理：订正 `CLAUDE.md` 中陈旧的「93 cases」（实测 327 个测试函数）。

遗留的 P2（P2-11～P2-16）已在 v2 正文中一并处理，无未决项。
**当前无未解决的 P0 / P1。**


---

## 实施过程发现的方案缺陷（Issues Found During Implementation）

落地 v2 时逐条对照仓库现实，发现下列 4 处方案缺口。均**未静默偏离**：此处记录问题、
纠正方案与理由，实现按纠正后的方案执行。

| # | 位置 | 问题 | 纠正后的做法 |
|---|---|---|---|
| **I-1** | §6.1 `test_apply_keeps_exactly_one_per_category` ⟷ §2.6.3 | 用例要求 apply 后「users 恰好 1 条」，但 §2.6.3 又规定**被引用的 seed 用户停用而非删除**。两者在 legacy 库上必然打架：`pm` 是项目 `ARA` 的 `owner_id`，而 `ARA` 是 projects 类里唯一的候选、「每类留一」恒保留它 ⇒ `pm` 永远处于「仍被引用」状态 ⇒ 永远被停用 ⇒ 它的行永远留在 `users` 表里，计数恒 ≥ 2。照 v2 字面写用例必然红。 | users 的判据改为「**启用中**的用户恰好 1 人」（`User.query.filter_by(is_active=True).count() == 1`），其余四类仍断言行数为 1。这既保住了「每类只保留一个示例」的产品语义，又不牺牲 §2.6.3 那条安全阀。 |
| **I-2** | §4.2 报告的 `dangling assignments` ⟷ §2.6.3 引用清单 | 报告行只写「指向被删 **Agent** 的终态单」，但 §2.6.3 的引用清单（reporter / owner / comment.author / activity.actor / notification 收件人或 actor）**有意不含 `assignee`**——`assignee_id` 是无外键的软引用。于是一个「只当过 assignee」的 seed 用户（如 legacy 库里的 alice / bob，其审计与通知都随被删工单级联消失后）会被判定为「无引用」而**硬删**，在存活工单上留下与删 Agent 一模一样的悬空指派，而报告对此只字不提。 | 实现把**被删 Agent 与被删用户**一起统计，报告行标签写成「指向被删 Agent / 用户的存活工单」。这是严格更诚实的超集，不改变任何删除行为，只是让 P2-11 那条「告知义务」覆盖它本该覆盖的全部情形。 |
| **I-3** | §2.6.1 步骤 5 | 删除顺序列了 requirements/bugs → comments/activities/notifications → agents → users，**唯独没有 projects**，而 projects 是「每类留一」的五类之一。实践中 `Project.key` 有 `unique=True` 且指纹里只有一个 `"ARA"`，候选集恒为 1 条、删除集恒为空，所以 v2 不写也跑得通；但一旦将来有人往指纹表里加第二个 key（R-8 已警告过这种冲动），硬删一个仍有工单的项目会撞 `requirements.project_id` 外键 → `IntegrityError` → 被 `errors.py` 兜底成 500，而这正是 `services/lifecycle.py` 开篇明令禁止的「依赖数据库外键异常兜底」。 | 补一个与既有 `DELETE /api/projects` 同源的前置守卫：复用 `lifecycle.project_references`，名下仍有工单则**跳过并在报告中说明**，绝不硬删。正常路径上它恒不触发，是纯防御。 |
| **I-4** | §2.6.1 / §6.1 `test_dry_run_and_apply_agree_on_exit_code` | v2 要求 dry-run 与 apply 得出**同一个**退出码与同一份报告，却没说实现上怎么保证。最自然的读法（「dry-run 只统计、apply 才删」）等于写两套代码路径，而两套路径的一致性只能靠人工对齐——`flush()` 之后才求值的 Agent 守卫（P1-7）恰恰要求统计发生在「删除后的世界」里，两套路径必然漂移。 | 实现采用**单一路径**：无论哪种模式都照常执行全部删除与统计，末尾按模式 `commit()` 或 `rollback()`。于是「预演结果必须能预测真实结果」不再是一句需要人工维护的承诺，而是结构性成立的事实；§6.3-6 的「各表行计数不变」也由事务回滚直接保证。 |

**基线订正（对应 P1-9）**：落地当天本地 `pytest -q` 实测基线为 **342 passed / 0 failed**
（v2 §6.2 提到的 327 是 `def test_` 计数，parametrize 展开后更多）。落地后为 **371 passed / 0 failed**
（本轮新增 29 例：test_persistence 9 / test_seed_minimal 6 / test_purge_demo_data 14）。`CLAUDE.md` 里陈旧的「93 cases」已按建议一并订正为相对判据。
