# AragonTeam 账号安全与治理收口（Account Security & Governance）Spec

> 版本：**v2**（第 2 轮设计节点产出 → 第 2 轮设计评审后修订）
> 上一轮：`docs/plans/self-service-registration/spec.md` v2（已实现并提交，commit `04506e5`）
> 目标读者：下游实现工程师。本文档要求详细到**逐行可实现、无需再做设计决策**。
> 语言约定：正文中文；标识符、路径、HTTP 契约一律原样英文。
> v1 → v2 的全部改动均由下面的「评审记录」驱动，逐条可追溯；未在评审记录里出现的段落逐字未动。

---

## 评审记录（Review Notes）

评审人以「可行性 / 完备性 / 一致性 / 规模适当性」四维逐节审阅 v1，**每一条结论都在本仓库源码上实测复核过**
（读了 `backend/{app,config,errors,observability}.py`、`backend/routes/{auth,users,me,stats,settings,projects}.py`、
`backend/services/{passwords,auth_helpers,app_settings,schema_sync,bootstrap,lifecycle,validation}.py`、
`backend/models/{user,activity,__init__}.py`、`backend/tools/purge_demo_data.py`、
`backend/tests/{conftest,test_schema_sync,test_admin_console,test_lifecycle,test_settings,test_auth,test_registration}.py`
与整个 `frontend/`），不基于对 v1 文字的信任。

**P0 = 会造成安全漏洞 / 契约无法实现 / 验收判据失真，必须改；P1 = 会导致实现走偏或返工，必须改；P2 = 建议，已顺手改掉或标注。**

| # | 严重度 | 位置 | 问题 | v2 的处置 |
|---|---|---|---|---|
| P0-1 | **P0** | §2.2 B-4②、§4.2 | **根管理员保护失败开放**。v1 说新端点 `POST /api/users/:id/reset-password` 「复用 `_reject_root_mutation` 判据」，但该函数的口令分支判据是 `data.get("password")`（`backend/routes/users.py:125`）——而新端点的**主用法恰恰是空 body**（服务端生成一次性口令）。判据恒假 → 任意 admin 都能把根管理员的口令重置成一个自己看得见的一次性口令，**直接接管破窗账号**，而这正是上一轮 §2.1 A-4 拦截矩阵存在的全部理由。§8.2 第 35 条用例按 v1 实现必红 | §2.2 B-4②、§4.2 改为**不依赖请求体**的独立判据；`_reject_root_mutation` 明确标注为「只服务 PATCH」 |
| P0-2 | **P0** | §2.4 D-1、§4 | **两条路由共用一个服务函数，但只定义了其中一条的契约**。`POST /api/users` 的 password 变可选、201 多一个 `temporary_password`、新增保留名 409——`POST /api/auth/register` 走同一个 `create_user_by_admin`，这三件事会不会跟着变？v1 未答。而 `backend/routes/auth.py:5` 的模块 docstring 明写该端点契约「逐字不变」。实现者只能猜，猜错就是一次没人告示的破坏性变更 | 新增 §4.1′ 明确 register 的完整契约（password **保持必填**、**不回传** `temporary_password`、保留名 409 是修复既有漏洞），并说明服务函数如何用一个参数表达这两种形状 |
| P0-3 | **P0** | §8.1、§8.4 | **影响分析漏掉了本轮最具侵入性的改动**。v1 自述扫描范围是「`POST /api/users` 与 `POST /api/auth/register` 的调用点」，但本轮实际收紧了**四条**写入路径（另两条是 `PATCH /api/users/:id` 带 password 与 `POST /api/me/password`），并且**完全没有分析强制改密闸门对既有用例的影响**——闸门会让任何「经 API 建号 / 重置后再用该账号发非豁免请求」的用例集体 403。§8.4 的「零失败」DoD 建立在这份不完整的分析上 | §8.1 整节重写：给出四条路径的完整扫描结论 + 闸门影响的专门判据（评审已现场跑完这次扫描，结论见新 §8.1） |
| P1-1 | P1 | §2.1 A-1 | `generate_temporary_password` 的长度钳位写成 `[max(policy()["min_length"], 8), 32]`——而 `policy()` 允许 `min_length` 钳到 **128**，此时该区间为空（下界 128 > 上界 32），「构造上必然满足策略」这条不变量在**合法配置**下为假。同理 `min_char_classes` 可钳到 4，生成器却只保证 3 类。§8.2 第 14 条（生成的口令恒过策略）与第 10 条（min_length 可为 128）互相矛盾，两条用例不可能同时绿 | 上界改为跟随策略（`max(policy.min_length + 4, 16)`，硬顶 64），字符集补第 4 类，`assert` 改为直接调 `validate_password` |
| P1-2 | P1 | §2.1 A-3、§3.4 | 新建 `hooks/usePasswordPolicy.ts` 读 `REGISTRATION_META_KEY`——但 `frontend/hooks/useRegistrationMeta.ts` **已经存在**，已经读同一个 SWR key，已经暴露 `password_min_length` 并带编译期回落 8（`:11`），且已被 `app/login/page.tsx:23` 与 `app/register/page.tsx:22` 消费。再建一个 hook 就是同一个 key 上的第二份真相——正是本文档 §2.4 D-1 花一整节反对的东西 | 删掉新 hook，改为**扩展既有 `useRegistrationMeta`**；§3.4 少一个新建文件 |
| P1-3 | P1 | §3.5 | **`PasswordStrength` 按 v1 写法参数化不到判据**。真正的判据入口是两个**模块级纯函数** `passwordRules(password, username)`（`PasswordStrength.tsx:39`）与 `isPasswordAcceptable(password, username)`（`:56`），后者被 `RegisterForm.tsx:38` 在组件**之外**调用。给组件加 props 完全影响不到它们，结果是：根管理员把 `PASSWORD_MIN_LENGTH` 调到 12 之后，注册页仍按 8 放行、点提交才 400——恰好是 `PasswordStrength.tsx:5-10` 注释里发誓要避免的那种困惑。而且 `RegisterForm.tsx` 根本不在 v1 的变更清单里 | §2.1 A-3 与 §3.5 改为把 policy 穿进两个纯函数的签名；变更清单补 `RegisterForm.tsx` |
| P1-4 | P1 | §2.3 C-5-2 | 引用的函数**不存在**：`tools/purge_demo_data.py` 里没有 `_user_reference_count`，真名是 **`_user_references`**，在 **`:354-380`**（v1 写 `:360-380`）。实现者会 grep 不到 | 改为真名与真行号；同时补一条 v1 漏掉的事实：该函数 `:377` **已经**统计了「该用户作为施动者」的 activities，本轮补的是「该用户作为被治理对象」的那一半 |
| P1-5 | P1 | §3.4、§6.3 | **仓库里没有通用 `Drawer` 组件**。`frontend/components/ui/` 共 15 个文件（Avatar/Badge/Button/Checkbox/ConfirmDialog/EmptyState/ErrorState/Input/**Modal**/Pagination/ProgressBar/Select/Skeleton/Textarea/**Toggle**），没有 Drawer；唯一的抽屉 `components/TicketDrawer.tsx` 与工单强耦合（`useTicket` / 评论流 / agent-advance），不可复用为壳。v1 的 `MemberActivityDrawer` 等于隐含要求先造一个抽屉框架，却未计入工作量 | 改用**既有 `Modal`**（`ui/Modal.tsx`，已带 focus trap / Esc / `aria-modal`），§6.3 相应改写。规模适当性判断：为一条只读时间线造抽屉框架不划算 |
| P1-6 | P1 | §6.1、§3.5 | `/force-password` 在 `(app)` 路由组**之外**（与 `/login`、`/register` 同级），因此**拿不到** `(app)/layout.tsx:16` 那条登录守卫。v1 只写了「`(app)` 里发现标记 → 跳过去」，没写这个页面自己的两条反向守卫，结果是：未登录直接敲 `/force-password` 会渲染一个空表单；标记已清的人敲它会被永久停在一个没有出口的页面 | §6.1 补两条反向守卫；并说明根 `app/page.tsx` 的既有重定向会多一跳，属可接受 |
| P1-7 | P1 | §2.2 B-2 | **置位判据写成了「走了哪条路径」，应该是「谁改的谁的口令」**。v1 表里「`PATCH /api/users/:id` 带 password → 置 True」是无条件的，但 `_reject_root_mutation`（`routes/users.py:125-129`）**明确放行本人给自己改密**——根管理员今天的自助改密路径就是它。按 v1 实现：根管理员自己改完密码立刻被闸门锁住，必须再去 `/me/password` 改第二次才能进系统。同一个问题也命中任何给自己改密的 admin | B-2 表的判据改为 `actor.id != target.id`；§2.3 C-3 第 5 行的审计动作随之分叉 |
| P2-1 | P2 | §3.2、§8.2、§8.4 | 计数对不上：§3.2 表头写「修改（13）」实为 14 行；§8.2 标题写「46 条」但正文是 46 条编号 + 末尾 4 条未编号 = **50**；§8.4 因此把 `674+46=720` 少算了 4 | 已全部订正为 14 / 50 / 724 |
| P2-2 | P2 | §0.1 E-4 | 前端硬编码不止 3 处，实为 **6** 处：`MemberFormModal.tsx:81`、`:107`（placeholder「至少 6 位」）、`:190`、`:232`（placeholder）、`PasswordCard.tsx:19`、`:55`（label「新密码（至少 6 位）」）。占位符与 label 是用户**真正读到**的那半 | E-4 与 §3.5 补齐 6 处 |
| P2-3 | P2 | §3.2 | `backend/models/__init__.py:12,30` 是本仓库的符号再导出约定（`ENTITY_TYPES` 就在里面）。新增的 `TICKET_ENTITY_TYPES` / `APP_SETTING_ENTITY_ID` 未登记 = 制造一个新孤岛（CLAUDE.md 评审清单第 8 条） | 变更清单补该文件 |
| P2-4 | P2 | §2.3 C-1 | `backend/routes/projects.py:147-148` 有一句注释「Activity 只承载 requirement/bug 两种实体（models/activity.py::ENTITY_TYPES），故项目 / Agent 的删除走结构化日志」——本轮之后它就是一句**过期注释**（僵尸注释，CLAUDE.md §四） | 变更清单补该文件的注释修订，并说明「项目/Agent 删除仍走结构化日志」是**本轮的非目标**，不是遗漏 |
| P2-5 | P2 | §2.2 B-3 | 闸门给每个 `/api/*` 请求加一次 `verify_jwt_in_request` + 一次 `current_user()`；而 `errors.py:101-118` 的 blocklist loader 本身就查一次库，端点上的 `require_role` 又查一次 | 补一条实现约束：闸门内**不得**做第二次查库，依赖 SQLAlchemy identity map 的同会话命中；并写明这是有意接受的开销 |
| P2-6 | P2 | §2.1 A-1 | 新符号表删掉了 `PASSWORD_MIN_LENGTH` / `MIN_CHAR_CLASSES` 两个模块常量，但没说全仓引用点。实测：`PASSWORD_MIN_LENGTH` 的唯一外部引用是 `routes/auth.py:104`，`MIN_CHAR_CLASSES` 无外部引用，测试里都没有 | A-1 补一行显式说明，免得实现者不敢删 |
| P2-7 | P2 | §2.2 B-3 | 豁免集是硬编码路径串，与蓝图 `url_prefix` 是两份真相；且未规定尾斜杠归一 | 补一条自检用例：豁免集里的每条 `(method, path)` 必须能在 `app.url_map` 里解析到 |

**没有发现的问题（评审确认为正确，特此记录以免下一轮重复怀疑）**：
`activities` 复用 `from_status`/`to_status` 承载角色/状态迁移（`String(24)` 够宽，`Activity.log` 签名逐字匹配）；
`entity_type` 是 `String(16)`，`"app_setting"` 不超宽；`_is_orphan`（`purge_demo_data.py:292-301`）对不在 `alive` 字典里的
`entity_type` 恒返回 False，治理审计确实不会被判成孤儿（E-10 属实）；`must_change_password` 只需登记
`ADDITIVE_COLUMNS` 即可被**双向**漂移守卫覆盖（`tests/test_schema_sync.py:104` 与 `:133` 两条都在，
`_BASELINE_COLUMNS` 快照「只减不增」的约定意味着新列**不必**动那份快照）；`summary()` 不加新键与
`models/user.py:59-61` 的既有判据一致；`observability.py:53-56` 的访问日志确实只记 `method / path / status / 耗时`，
不记 body，R-6 属实；`ROOT_ADMIN_PASSWORD` 的内置默认 `admin123` 恰好满足新策略（8 位 2 类），
升级不会把既有部署的破窗口令变成非法值——但见新增的 R-14。

---

## 0. 本轮定位：上一轮留下的是什么

第 1 轮（`self-service-registration`）交付了三根支柱并已上线：**配置文件锚定的根管理员**、
**邀请码自助注册**、**管理员的团队治理面**。原始需求的字面要求已全部满足。本轮不重复它们，
而是把上一轮**自己在评审结论里点名的下一轮范围**（`self-service-registration/spec.md` §11
「下一轮的建议范围」）与实施后暴露的结构性缺口收口。

### 0.1 已核对的既有事实（本轮全部设计基于这些实测结论，不基于记忆）

| # | 事实 | 证据 |
|---|---|---|
| E-1 | 口令强度策略**只作用于自助注册**一条路径 | `backend/services/passwords.py:1-11` 模块 docstring 明写「作用范围严格限定为 `POST /api/auth/signup`」 |
| E-2 | 管理员建号 / 改密**零口令约束**：一个字符的口令也能 201 | `backend/routes/users.py:75-91`、`backend/routes/users.py:174-176`；实测用例 `tests/test_hardening_r3.py:179` 用 `"password": "p"` 断言 201 |
| E-3 | 自助改密的下限是 **6 位**，与注册的 8 位分叉 | `backend/routes/me.py:43-44` `_PASSWORD_MIN = 6` |
| E-4 | 前端**六处**硬编码「至少 6 位」，与后端注册页的 8 位规则分叉。**校验逻辑 3 处 + 用户真正读到的文案 3 处**（评审 P2-2：v1 只点了前者，但 placeholder 与 label 才是造成「界面说 6 位、后端要 8 位」这种困惑的那一半） | 校验：`frontend/components/admin/MemberFormModal.tsx:81`、`:190`、`frontend/components/settings/PasswordCard.tsx:19`；文案：`MemberFormModal.tsx:107`、`:232`（placeholder「至少 6 位」）、`PasswordCard.tsx:55`（label「新密码（至少 6 位）」） |
| E-5 | 管理员重置密码后，**管理员永久知道该同事的口令**，产品内无强制改密机制 | `backend/routes/users.py:174-176` 只 `set_password` 后 `commit` |
| E-6 | 用户治理动作（改角色 / 停用 / 启用 / 重置密码 / 改注册配置）**零审计**：`activities` 表只接受 `("requirement", "bug")` | `backend/models/activity.py:8` `ENTITY_TYPES = ("requirement", "bug")` |
| E-7 | 保留用户名只有 `ROOT_ADMIN_USERNAME` 一个 | `backend/services/app_settings.py:219-232`；上一轮 §10 明确写了「没有做通用的保留名表」 |
| E-8 | `POST /api/auth/register` 与 `POST /api/users` 是两份高度重复的管理员建号实现 | `backend/routes/auth.py:63-87` vs `backend/routes/users.py:62-91`；上一轮 §12 F-7 记为「合并是下一轮的候选项」 |
| E-9 | `GET /api/stats` 的 `recent_activities` / `activities_this_week` **不带任何 entity_type 过滤** | `backend/routes/stats.py:52-58` |
| E-10 | `tools/purge_demo_data.py::_is_orphan` 对**不在 `alive` 字典里的 entity_type 恒返回 False** | `backend/tools/purge_demo_data.py:292-301` |
| E-11 | 停用账号的既有 token 由 `token_in_blocklist_loader` 立即失效，机制健全 | `backend/errors.py:101-125` |
| E-12 | 本轮起点的测试基线：**674 用例 / 42 文件**，`pytest -q --collect-only` 实测 | 本次会话现场采集（不引用任何文档里写死的数字，CLAUDE.md 质量门要求） |

### 0.2 本轮解决的四个问题（一句话版）

1. **口令策略碎片化**（E-1/E-2/E-3/E-4）：同一个系统里有 4 条设置口令的路径、3 套规则、
   2 个前端硬编码常量。收敛为**一份策略、一个真相源、前后端同源**。
2. **管理员重置密码没有闭环**（E-5）：改为「一次性口令 + 强制改密」，让管理员**不需要也不应该**
   知道同事的长期口令。
3. **治理动作没有留痕**（E-6）：谁在什么时候把谁停用了、把谁提成了 pm、改了邀请码——今天查不到。
   补一条**只增不删**的账号审计线，并在团队页可见。
4. **建号路径两份实现**（E-8）与**保留名只有一个**（E-7）：收敛为一个服务函数、一张可配置的保留名表。

---

## 1. Overview（概述）

AragonTeam 现在允许两种方式产生账号：管理员代建，与凭邀请码自助注册。第 1 轮把「谁能进这个系统」
这件事治理住了，但**没有治理「进来之后，口令这件事由谁负责」**。今天的实际状态是：自助注册的人被要求
一个 8 位、两类字符、不等于用户名的口令；而管理员代建的同事可以拿到一个 `p` 作为口令，并且这个口令
会一直是他的长期口令——管理员知道它，浏览器保存它，没有任何机制促使它被换掉。同一个产品里，
安全水位由「你是怎么进来的」决定，这本身就是缺陷。

本轮把口令收敛成**一条策略**（`services/passwords.py` 是唯一真相源，配置只提供两个阈值旋钮），
并让它作用于**所有**会写 `password_hash` 的路径：自助注册、管理员建号、管理员重置、成员自助改密。
同时把「管理员重置密码」这个动作从「管理员替你想一个口令」改成「系统生成一个一次性口令，
你下次登录必须改掉它」——`users.must_change_password` 是这条流程的落点，后端一道全局闸门保证
带着这个标记的人在改掉口令之前，除了「读自己是谁」和「改密码」以外什么也做不了。这不是前端的
善意提示，是服务端的硬约束。

第三件事是留痕。平台的核心价值主张是「人与 Agent 混合协作可追溯」，工单侧做得很彻底
（`activities` 表 + 时间线 + 通知），而**账号侧一片空白**：一个管理员可以把同事降级、停用、
重置密码，第二天没有任何人能说出这三件事发生过。本轮把 `activities` 的实体维度扩到 `user` 与
`app_setting`，用同一张表、同一个 `Activity.log` 写入口承载账号治理审计，并在团队页给出
「账号动态」入口。**扩表的同时必须把 `GET /api/stats` 的两处无过滤查询钉死在工单实体上**
（E-9）——否则「把某人停用」会出现在所有成员都能看到的仪表盘「最近动态」里，那是一次实打实的
信息泄露，而且是那种上线两周后才被发现的。

最后是两处结构性收敛：`POST /api/auth/register` 与 `POST /api/users` 合并到同一个服务函数
（两份实现必然漂移，上一轮 §12 F-7 已经预言了这件事），以及把保留用户名从「只有根管理员一个」
扩成一张可配置的表。二者都很小，但它们是「同一件事只有一份实现」这条仓库级约定的直接体现。

---

## 2. 技术设计（Technical Design）

### 2.1 支柱 A —— 全站统一口令策略

#### A-1 唯一真相源：`backend/services/passwords.py`（改写）

现有模块的 docstring 第一句就是「作用范围严格限定为 `POST /api/auth/signup`」——本轮把这句话
连同它描述的边界一起删掉。改写后的模块对外暴露四个符号：

```python
PASSWORD_MAX_LENGTH = 128          # 与 users.password_hash 无关，是输入上限，防超长哈希开销
DEFAULT_MIN_LENGTH = 8
DEFAULT_MIN_CHAR_CLASSES = 2

def policy() -> dict:
    """当前生效的口令策略。**唯一**读取配置的地方。

    Returns:
        {"min_length": int, "max_length": int, "min_char_classes": int}
    """

def count_char_classes(password: str) -> int:      # 逐字保留现有实现，不改
    ...

def validate_password(password: str, *, username: str | None = None,
                      current_password: str | None = None) -> None:
    """校验口令；不满足即抛 ValidationError（→ 全局 400）。

    规则与判定**顺序**（顺序是契约的一部分，见 §8.1 对既有用例的影响分析）：
      1. 长度 ∈ [min_length, max_length]
      2. 至少命中 min_char_classes 类字符（小写 / 大写 / 数字 / 其他可打印）
      3. 若给了 username：不等于用户名（casefold 比较）
      4. 若给了 current_password：不等于当前口令（区分大小写，逐字节比较）

    Raises:
        ValidationError: `detail.field` 恒为 "password"，`expected` 恒为人类可读的完整规则串。
    """

def validate_signup_password(password: str, username: str) -> None:
    """**保留的稳定别名**（= validate_password(password, username=username)）。

    改名等同破坏性变更（CLAUDE.md §五）。它今天的唯一调用点是 routes/auth.py::signup，
    但它已经出现在上一轮 spec 的接口表里，删掉等于让那份文档说谎。
    """

def generate_temporary_password(length: int | None = None) -> str:
    """生成一个**构造上必然满足策略**的一次性口令。
    """
```

> **【评审 P2-6】被删除的两个旧常量的全仓引用点**（已实测 grep，实现者可直接删）：
> `PASSWORD_MIN_LENGTH` 只有一个外部引用——`backend/routes/auth.py:104`，本轮 §2.1 A-3 已改写它；
> `MIN_CHAR_CLASSES` 无任何外部引用。**测试目录零引用**，删掉不会造成 collection error。
> `PASSWORD_MAX_LENGTH` 保留（同名同值），因为它同时是前端 `PasswordStrength.tsx:13` 的镜像。

**`policy()` 的实现细节（逐条对应一个真实失败模式）**：

- 读 `current_app.config["PASSWORD_MIN_LENGTH"]` / `["PASSWORD_MIN_CHAR_CLASSES"]`，缺省用
  上面两个 `DEFAULT_*`。
- **下限钳位**：`min_length = max(6, min(int(raw), PASSWORD_MAX_LENGTH))`，
  `min_char_classes = max(1, min(int(raw), 4))`。理由：这两个值来自环境变量，
  `PASSWORD_MIN_LENGTH=0` 会让策略静默变成「没有策略」，而 `=999` 会让**所有人都改不了密码**，
  包括根管理员——那是一个由手滑造成的、产品内无恢复路径的死锁。钳位不是防御性编程，
  是给一个人类可写的旋钮加物理止挡。
- 值非法（非整数）→ 回落默认 + `current_app.logger.warning`，**不抛异常**。与
  `services/app_settings.py:66-68` 的「脏值一律回落 + warning」同一取向：口令策略配置写错了
  不该让整个登录体系 500。

**`generate_temporary_password()` 的实现细节**（**v2 重写，评审 P1-1**）：

> **v1 错在哪**：长度钳位写成 `[max(policy()["min_length"], 8), 32]`，而 `policy()` 允许
> `min_length` 被钳到 **128**——那时下界 128 > 上界 32，区间为空，`min(max(...))` 的结果是 32，
> 于是这个函数在**合法配置**下会生成一个**违反自己策略**的口令。同理 `min_char_classes`
> 可被钳到 4，而 v1 的字符集只有三类。「构造上必然满足策略」这句话在 v1 里不成立，
> 而 §8.2 第 14 条用例正是要断言它——它与第 10 条（`PASSWORD_MIN_LENGTH=999` → 生效 128）
> 互相矛盾，两条不可能同时绿。**上界必须跟随策略，不能是一个与策略无关的魔数。**

- 字符集去掉易混字符，与 `app_settings._CODE_ALPHABET` 同一取向（人要口述 / 手抄它）：
  ```python
  _UPPER  = "ABCDEFGHJKMNPQRSTUVWXYZ"   # 去掉 I O
  _LOWER  = "abcdefghijkmnpqrstuvwxyz"  # 去掉 l o
  _DIGIT  = "23456789"                  # 去掉 0 1
  _SYMBOL = "!@#$%*+-="                 # 第四类；**去掉引号 / 反斜杠 / 空格**——
                                        # 它们会在复制粘贴、shell、CSV 里被吃掉或转义
  _CLASSES = (_UPPER, _LOWER, _DIGIT, _SYMBOL)
  ```
- **长度**：
  ```python
  pol = policy()
  hard_cap = 64                                   # 人还要手抄它；也远低于 PASSWORD_MAX_LENGTH
  lower = max(pol["min_length"] + 4, 16)           # 恒 ≥ 策略下限，且留 4 位余量
  upper = max(lower, min(hard_cap, pol["max_length"]))
  size  = min(max(length or current_app.config.get("TEMP_PASSWORD_LENGTH", 16), lower), upper)
  ```
  `lower` 由 `min_length` **派生**而不是与它并列取 max，这是本次修复的要点：区间恒非空
  （`upper >= lower` 由上式的 `max(lower, ...)` 保证），且下界恒严格满足策略。
  `policy()["min_length"]` 的上钳值 128 > `hard_cap` 时，`upper == lower == 132`——
  超过 64 是有意的：**宁可生成一个抄起来很痛苦的口令，也不能生成一个不合法的口令**。
- **构造保证策略**：先从**前 `min(pol["min_char_classes"], 4)` 个**子集各取 1 个字符
  （`secrets.choice`；因为 `min_char_classes` 已被钳到 `[1, 4]`，而这里正好有 4 类），
  再从并集补足 `size`，最后用 `secrets.randbelow` 做 Fisher–Yates 洗牌。
  **禁止 `random` 模块**（凭据不可预测，与 `app_settings.generate_invite_code` 同一条铁律）。
- 生成后不写 `assert count_char_classes(...) >= 3` 这种与策略脱钩的常数断言，改为
  **直接把成品喂给策略本身**：
  ```python
  validate_password(result)          # 不传 username / current_password：此刻两者都不适用
  return result
  ```
  这不是防御性编程，是让「构造保证」这个不变量由**唯一真相源**来裁决——策略以后怎么改，
  这一行都不会说谎。它抛异常即 500，而那正是我们要的：生成器与策略脱钩是代码缺陷，
  不是用户输入问题，不该被静默降级。

#### A-2 四条写入路径全部接同一份策略

| 路径 | 文件:行（现状） | 本轮改为 |
|---|---|---|
| 自助注册 | `routes/auth.py:137` | 不变（已经在调 `validate_signup_password`） |
| 管理员建号（新） | `routes/users.py:75-91` | 经 `services/accounts.py::create_user_by_admin()` 调 `validate_password(pw, username=username)` |
| 管理员建号（旧路径） | `routes/auth.py:63-87` | 同上，**共用同一个服务函数**（§2.4 D-1） |
| 管理员重置 | `routes/users.py:174-176` | `validate_password(pw, username=user.username)` + 置 `must_change_password` |
| 成员自助改密 | `routes/me.py:131-134` | 删掉 `_PASSWORD_MIN/_PASSWORD_MAX` 两个常量，改调 `validate_password(new, username=user.username, current_password=current)` |

**`routes/me.py` 的改动有一个必须保留的语义**：现有代码先校验旧口令正确（`me.py:129-130`，
400 `current password is incorrect`），再校验新口令。**这个顺序不能换**——先告诉一个不知道旧口令
的人「你的新口令太弱」是在给猜口令的人提供反馈。改写后仍是：旧口令 → 新口令策略 → 新旧不同。
「新旧不同」这条判据从 `me.py:133-134` 的手写 if **搬进** `validate_password` 的规则 4，
错误串保持 `"new password must differ from current"` 不变（对外错误契约，勿更名）。

#### A-3 前后端同源：策略下发

`GET /api/auth/registration-meta`（公开、无鉴权）**追加**两个键（additive，既有键逐字不变）：

```jsonc
{
  "enabled": true,
  "invite_required": true,
  "password_min_length": 8,          // 既有键，改为读 policy()["min_length"]
  "password_max_length": 128,        // 新增
  "password_min_char_classes": 2     // 新增
}
```

前端**不再硬编码** 8/2。落地方式经评审修正为两条（P1-2 / P1-3）：

**① 读策略：扩展既有 `hooks/useRegistrationMeta.ts`，不新建 hook。**

> **v1 错在哪**：v1 要新建 `hooks/usePasswordPolicy.ts` 去读 `REGISTRATION_META_KEY`。
> 但 `frontend/hooks/useRegistrationMeta.ts` **已经存在**，已经读同一个 SWR key，已经
> 暴露 `password_min_length` 并带编译期回落 8（`:11`），且已被 `app/login/page.tsx:23`
> 与 `app/register/page.tsx:22` 消费。再建一个 hook 就是同一个 key 上的第二份真相——
> 正是本文档 §2.4 D-1 花一整节反对的东西。

改法：在 `useRegistrationMeta` 的返回值上**追加一个派生对象**（既有返回字段逐字不变，
现有两个调用点零改动）：

```ts
// frontend/hooks/useRegistrationMeta.ts
const policy: PasswordPolicy = {
  minLength:      meta?.password_min_length      ?? PASSWORD_MIN_LENGTH,      // 编译期回落 8
  maxLength:      meta?.password_max_length      ?? PASSWORD_MAX_LENGTH,      // 回落 128
  minCharClasses: meta?.password_min_char_classes ?? DEFAULT_MIN_CHAR_CLASSES, // 回落 2
};
return { meta, resolved, policy };   // ← 只加一个键
```

**② 用策略：把它穿进 `PasswordStrength` 的两个模块级纯函数，不是穿进组件 props。**

> **v1 错在哪**：v1 说「常量改为可选 props（`minLength` / `minCharClasses`）」。但真正的
> 判据入口是两个**模块级纯函数**——`passwordRules(password, username)`
> （`PasswordStrength.tsx:39`）与 `isPasswordAcceptable(password, username)`（`:56`），
> 后者被 `RegisterForm.tsx:38` 在组件**之外**调用来决定要不要拦住提交。给组件加 props
> 完全影响不到它们。按 v1 实现的结果是：根管理员把 `PASSWORD_MIN_LENGTH` 调到 12 之后，
> 注册页仍按 8 放行、点提交才 400——恰好是 `PasswordStrength.tsx:5-10` 注释里发誓要避免的
> 那种困惑。而且 `RegisterForm.tsx` 根本不在 v1 的变更清单里。

签名改为（三个函数一致地把 policy 作为**可选末位参数**，默认值 = 现有常量，
故任何未迁移的调用点行为逐字不变）：

```ts
export function passwordRules(password: string, username: string,
                              policy: PasswordPolicy = DEFAULT_POLICY): PasswordRule[]
export function isPasswordAcceptable(password: string, username: string,
                                     policy: PasswordPolicy = DEFAULT_POLICY): boolean
export default function PasswordStrength(
  props: { password: string; username: string; policy?: PasswordPolicy })
```

调用点同步迁移（**两处，缺一不可**）：`RegisterForm.tsx:38` 的 `isPasswordAcceptable(...)`
与它渲染的 `<PasswordStrength>`，都传 `useRegistrationMeta().policy`。
`countCharClasses`（`:24`，Unicode 版）**逐字不动**——它是上一轮评审 P1 修过的前后端同源实现。

这就是「前端提前拦下的一定是后端也会拒的」这条既有不变量在**策略可配置**之后的正确形态。

> **不做的事**：不把策略下发做成需要鉴权的新端点。注册页本来就要读这个端点，
> 复用它意味着零新增往返；而口令策略本身不是秘密——它印在每一个注册页上。

---

### 2.2 支柱 B —— 一次性口令 + 强制改密

#### B-1 数据落点：`users.must_change_password`

```python
# backend/models/user.py（新增列，紧邻 source 之后）
# 【account-security-and-governance §2.2 B-1】true = 该账号的口令是别人设的（管理员建号 /
# 管理员重置），本人尚未改过。带此标记的人只能读「我是谁」和改密码，其余 /api/* 一律 403。
# 默认 False：存量行零回填即获得正确语义——他们的口令确实是自己在用的那个。
# 新增列必须同时登记进 services/schema_sync.py::ADDITIVE_COLUMNS，否则存量库必炸。
must_change_password = db.Column(db.Boolean, nullable=False, default=False,
                                 server_default="0")
```

`to_dict()` 追加 `"must_change_password": bool(self.must_change_password)`；
**`summary()` 有意不加**——指派选择器与时间线不关心这件事，多传只会让 `AssigneeSummary` 变胖
（与 `is_root` / `source` 同一判据，见 `models/user.py:59-61`）。

`ADDITIVE_COLUMNS` 追加一条（`services/schema_sync.py:32` 之后）：

```python
("users", "must_change_password", "BOOLEAN NOT NULL DEFAULT 0"),
```

#### B-2 何时置位、何时清位

**判据不是「走了哪条路径」，是「谁改了谁的口令」**（v2 修正，评审 P1-7）：

```python
# services/accounts.py 的唯一判据，四条写入路径全部调它
def should_force_change(actor, target) -> bool:
    """口令是不是**别人**替这个人设的。"""
    return actor is None or actor.id != target.id
```

> **v1 错在哪**：v1 表里「`PATCH /api/users/:id` 带 password → 置 True」是无条件的。
> 但 `_reject_root_mutation`（`routes/users.py:125-129`）**明确放行本人给自己改密**——
> 根管理员今天的自助改密路径就是它（`only the root administrator can change its own password`）。
> 按 v1 实现：根管理员刚给自己改完密码就被闸门锁住，必须再去 `/me/password` 改第二次
> 才能进系统。同一个问题命中任何用管理台给自己改密的 admin。

| 事件 | `must_change_password` | 理由 |
|---|---|---|
| 管理员建号（`POST /api/users` / `POST /api/auth/register`） | **置 True** | 口令是别人想的（建号时 actor ≠ target 恒成立） |
| 他人重置口令（`PATCH /api/users/:id` 带 password，或 `POST /api/users/:id/reset-password`，且 `actor.id != target.id`） | **置 True** | 同上 |
| **本人**经上述两条路径给自己改密（`actor.id == target.id`） | **清 False** | 口令是本人当场设的，与 `/me/password` 同义。这条是 v1 漏掉的分支 |
| 自助注册（`POST /api/auth/signup`） | 保持 False | 口令是本人当场设的 |
| 成员自助改密（`POST /api/me/password`） | **清 False** | 这正是闸门要的动作 |
| `ensure_root_admin` 建号 / 同步口令 | **恒不置位** | 根管理员的口令真相在配置文件里。给它置位等于让「破窗账号」一进来就被闸门挡住，而破窗的场景恰恰是「别的路都断了」——这条路必须最短、最不容易出岔子。**实现约束**：`services/bootstrap.py` **不得** import `services/accounts.py`，它有意保持一条不依赖任何策略的最短路径（见 §7 R-14） |
| 管理员改角色 / 停用 / 改邮箱 | 不动 | 与口令无关 |

#### B-3 服务端闸门：`services/auth_helpers.py::install_password_gate(app)`

**这是本轮技术上最容易写错的一段，逐条给死**：

```python
# backend/services/auth_helpers.py（追加）
from flask import request
from flask_jwt_extended import verify_jwt_in_request
from flask_jwt_extended.exceptions import JWTExtendedException
from jwt.exceptions import PyJWTError

# 豁免集：(method, path) 精确匹配。**只放三类**——公开端点、读「我是谁」、改密码本身。
_PASSWORD_GATE_EXEMPT = frozenset({
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/signup"),
    ("GET", "/api/auth/registration-meta"),
    ("GET", "/api/auth/me"),          # 前端要靠它读回 must_change_password
    ("POST", "/api/me/password"),     # 闸门要求你做的那件事，不能被闸门自己挡住
    ("GET", "/api/health"),
})


def install_password_gate(app) -> None:
    """安装「必须改密」全局闸门（account-security-and-governance §2.2 B-3）。

    选 before_request 而不是逐路由装饰器：路由有 40+ 个，漏挂一个就是一个后门；
    而这条规则天然是「除了这几个豁免，全都拦」的形状。
    """

    @app.before_request
    def _require_password_change():           # noqa: WPS430 - 闭包是 Flask 的既有形状
        if request.method == "OPTIONS":
            return None                       # CORS 预检绝不能被拦，否则全站跨域当场瘫痪
        if not request.path.startswith("/api/"):
            return None
        if (request.method, request.path) in _PASSWORD_GATE_EXEMPT:
            return None
        if not app.config.get("FORCE_PASSWORD_CHANGE", True):
            return None
        try:
            verify_jwt_in_request(optional=True)
        except (JWTExtendedException, PyJWTError):
            # 令牌畸形 / 过期 / 已吊销（账号被停用）→ 本闸门不表态，
            # 交给端点自己的 @jwt_required() 产出既有的 401 契约体（errors.py:88-125）。
            return None
        user = current_user()
        if user is None or not user.must_change_password:
            return None
        return jsonify({
            "error": "password change required",
            "detail": {
                "reason": "your password was set by an administrator",
                "endpoint": "POST /api/me/password",
            },
        }), 403
```

**四条不可动摇的约束**：

1. **`OPTIONS` 必须第一个放行**。Flask-CORS 的预检响应由 `after_request` 产出，
   `before_request` 返回 403 会让预检失败，浏览器侧表现为「所有跨域请求都挂了」，
   而后端日志里只有一串 403 —— 这是最难定位的一类故障。
2. **异常吞掉是有意的、且范围最小**。这里只捕获 JWT 解析/校验族异常，其余原样抛出。
   捕获它们不是「防御理论上不会发生的事」，而是因为本闸门在**语义上不负责鉴权**：
   它只回答「这个已认证的人是否欠一次改密」。令牌问题的唯一权威回答者是端点上的 `@jwt_required()`。
3. **注册位置**：`create_app` 中 `register_blueprints(app)` **之后**调用
   `auth_helpers.install_password_gate(app)`（`backend/app.py:87` 之后）。Flask 的
   `before_request` 与蓝图注册顺序无关，但把它放在这里能让 `create_app` 的阅读顺序保持
   「装扩展 → 装错误处理 → 装路由 → 装全局闸门」。
4. **`FORCE_PASSWORD_CHANGE=false` 只关跳转，不关标记**。标记仍会被置位与清除，
   前端仍会提示，只是不再硬拦。这是给「升级当天发现闸门误伤了某个集成脚本」准备的止血阀，
   不是长期形态；README 必须写明这一点。
5. **【评审 P2-5】闸门内不得做第二次查库**。`verify_jwt_in_request` 会触发
   `errors.py:101-118` 的 blocklist loader（一次 `db.session.get(User, uid)`），紧接着
   `current_user()` 又是一次同主键的 `db.session.get`——后者由 SQLAlchemy 的 identity map
   在**同一个 session** 内命中，不打库。因此每个已认证请求的真实增量是 **1 次 SELECT**
   （blocklist loader 那次；端点上的 `@jwt_required()` 之后再触发时同样命中 identity map）。
   这是有意接受的开销：换来的是「漏挂一个路由就是一个后门」这个风险彻底消失。
   **禁止**在闸门里为了「拿全字段」而另发查询或 `db.session.expire()`。
6. **【评审 P2-7】豁免集必须有自检**。它是硬编码路径串，与蓝图的 `url_prefix` 是两份真相，
   任何一次路由重构都可能让某条豁免静默失效（失效方向是**变严**：`/api/me/password` 被自己
   拦住 = 死循环）。故必须有一条用例遍历 `_PASSWORD_GATE_EXEMPT`，断言每条 `(method, path)`
   都能在 `app.url_map.bind("localhost").match(path, method=method)` 里解析到。
   同时 `request.path` **不做尾斜杠归一**：Flask 的 strict_slashes 会把 `/api/auth/me/`
   在路由层 308 到 `/api/auth/me`，重定向响应本身不带鉴权语义，闸门放行它是正确的。

#### B-4 管理员侧的两个入口

**① 建号时不必想口令**：`POST /api/users` 的 `password` 由必填改为**可选**。
未提供 → 服务端 `generate_temporary_password()`，201 响应体**额外**带一个
`temporary_password` 字段（明文，**仅此一次**，之后任何接口都读不回来）。
提供了 → 走策略校验，`temporary_password` 为 `null`。

> **契约影响**：`{"username": "x"}`（无 password）此前是 400，现在是 201。这是**放宽**，
> 不是收紧，不破坏任何既有调用方。而 `{"username": "x", "password": "p"}` 由 201 变 400，
> **是本轮唯一一次有意的破坏性变更**，见 §7 R-1 与 §8.1 的既有用例清单。
>
> **【评审 P0-2】这条放宽只作用于 `POST /api/users`，不作用于 `POST /api/auth/register`。**
> 两条路由共用 `create_user_by_admin`，但 password 的必填性由**调用方**决定，
> 见 §4.1′ 与 §2.4 D-1 的 `allow_generated` 参数。

**② 重置口令有了专属端点**：`POST /api/users/<id>/reset-password`（admin）。
body 可空（生成一次性口令）或 `{"password": "..."}`（管理员指定，仍过策略）。
响应 200 `{"user": {...}, "temporary_password": "..."|null}`。

既有的 `PATCH /api/users/:id` 带 `password` 的路径**保留且行为收紧**（策略校验 + 置位），
因为 `MemberFormModal` 的重置表单今天走的就是它（`MemberFormModal.tsx:194`），
而存量测试 `tests/test_admin_console.py:48` 也钉着它。新端点是**更好的那条路**，
前端本轮改走新端点；旧路径作为契约兼容保留。

**根管理员保护（v2 重写，评审 P0-1 —— 本轮最严重的一处）**：

> **v1 错在哪**：v1 说新端点「复用 `_reject_root_mutation` 判据」。但那个函数的口令分支是
> ```python
> if data.get("password"):            # routes/users.py:125
>     actor = current_user()
>     if actor is None or actor.id != user.id:
>         return lifecycle.conflict_root_admin(...)
> ```
> 判据挂在**请求体里有没有 password** 上——而新端点的**主用法恰恰是空 body**
> （服务端生成一次性口令）。于是判据恒假，**任意 admin 都能把根管理员的口令重置成一个
> 自己看得见的一次性口令，然后拿着它登录、改密、完全接管破窗账号**。
> 这一步直接摧毁上一轮 §2.1 A-4 拦截矩阵的全部价值，而且它长得和上一轮 §12 F-7
> 记录的那类漏洞一模一样：新端点复用了一个**为另一种形状写的**守卫。
> §8.2 第 35 条用例按 v1 实现必红。

新端点必须用**不依赖请求体**的独立判据，且排在读 body **之前**：

```python
@bp.post("/<int:user_id>/reset-password")
@require_role("admin")
def reset_password(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        return jsonify({"error": "user not found"}), 404
    # 【account-security-and-governance §2.2 B-4② / 评审 P0-1】
    # 判据是「谁在重置谁」，**与请求体无关**——本端点的主用法是空 body。
    # 绝不复用 routes/users.py::_reject_root_mutation：那个函数的口令分支挂在
    # `data.get("password")` 上，对空 body 恒放行，在这里就是一个失败开放的后门。
    actor = current_user()
    if lifecycle.is_protected_root(user) and (actor is None or actor.id != user.id):
        return lifecycle.conflict_root_admin(
            "only the root administrator can change its own password")
    ...
```

`_reject_root_mutation` 的 docstring 同步加一句：**「本函数只服务 `PATCH /api/users/:id`；
它的口令分支以 `data['password']` 存在为前提，任何 body 可空的端点都不得复用它。」**
这不是注释洁癖——它是让下一个想复用它的人**在复用之前**就看见这个前提。

**根管理员的自助重置**（`actor.id == user.id`）放行，且按 §2.2 B-2 的判据**不置位**——
根管理员给自己生成一个一次性口令再自己改掉，是一条合理但没什么用的路；不置位保证
它至少不会把破窗账号关进闸门。

---

### 2.3 支柱 C —— 账号治理审计

#### C-1 复用 `activities` 表，不建新表

```python
# backend/models/activity.py
# 【account-security-and-governance §2.3 C-1】实体维度扩到账号与站点设置。
# 工单实体单独成组：GET /api/stats 与所有时间线查询都**只认这一组**，
# 治理事件绝不能漏进面向全员的「最近动态」（§2.3 C-3）。
TICKET_ENTITY_TYPES = ("requirement", "bug")
ENTITY_TYPES = TICKET_ENTITY_TYPES + ("user", "app_setting")

# app_setting 是站点级单例，没有自然主键；用 0 作哨兵 entity_id
# （entity_id 列 nullable=False，不能传 None）。
APP_SETTING_ENTITY_ID = 0
```

**为什么不建新表**：`activities` 已经具备本轮需要的全部字段（多态实体、多态施动者、
`from_status`/`to_status`、`message`、时间索引），且 CLAUDE.md 已经把「activities 永不按数量清理」
写成了仓库级不变量——审计数据落在这张表上，天然继承那条保护。建第二张审计表意味着第二套
保留策略、第二套清理规则、第二个会漂移的真相。

**`from_status` / `to_status` 的复用是有意的**：这两列是 `String(24)`，本轮用它们承载
「角色 A → 角色 B」与「active → disabled」。这算不算语义滥用？算一点。但替代方案是加两列
（`from_value`/`to_value`）——为一个纯展示用途在一张已上线的表上加列，代价（`schema_sync` 登记 +
存量库 ALTER + 两条永远二选一的空列）明显高于收益。**在 `models/activity.py` 的列注释上写清这件事**，
让下一个读者不必猜。

#### C-2 写入口：`backend/services/audit.py`（新建）

```python
"""账号与站点治理审计（account-security-and-governance §2.3）。

路由层只调本模块，**不直接调 Activity.log** —— 那会让 action 字符串散落在 6 个路由文件里，
第一次拼写不一致就是一条查不出来的审计。与 services/lifecycle.py 的定位一致：
「破坏性动作的前置检查与语义」收在服务层，路由只做「取参 → 调服务 → 渲染契约」。

本模块**绝不**把口令、口令哈希、邀请码明文写进 message —— 审计要能被广泛阅读，
凭据不能。这条是硬约束，不是建议。
"""

USER_ACTIONS = (
    "user_created",       # 管理员建号
    "user_registered",    # 凭邀请码自助注册
    "role_changed",       # from_status/to_status = 旧/新角色
    "activated",
    "deactivated",
    "password_reset",     # 他人重置（含一次性口令）
    "password_changed",   # 本人自助改密
)

SETTINGS_ACTIONS = ("registration_updated", "invite_code_rotated")


def log_user_event(target_user, action, actor, *, from_value=None,
                   to_value=None, message=None): ...

def log_settings_event(action, actor, *, message=None): ...

def user_timeline(user_id):
    """该账号的治理时间线查询（未分页，供路由套 paginate）。"""
    return Activity.query.filter_by(entity_type="user", entity_id=user_id)\
        .order_by(Activity.created_at.desc(), Activity.id.desc())
```

两个 `log_*` 一律 **不 commit**（沿用 `Activity.log` 与 `notifications.notify` 的既有约定），
由调用方事务统一提交。

#### C-3 接入点（7 处，逐一给死）

| # | 位置 | action | from/to | message（中文，≤255） |
|---|---|---|---|---|
| 1 | `services/accounts.py::create_user_by_admin` | `user_created` | –/角色 | `创建了成员「{显示名}」（{角色}）` |
| 2 | `routes/auth.py::_create_signup_user` | `user_registered` | –/角色 | `通过邀请码自助注册` |
| 3 | `routes/users.py::patch_user`（role 变更） | `role_changed` | 旧/新 | `把角色从「{旧}」改为「{新}」` |
| 4 | `routes/users.py::patch_user`（is_active 变更） | `activated`/`deactivated` | `disabled`/`active` | `启用了该账号` / `停用了该账号` |
| 5 | `routes/users.py::patch_user` + `reset_password`，**且 `actor.id != target.id`** | `password_reset` | – | `重置了该账号的密码，下次登录需修改` |
| 5′ | 同上两处，但 `actor.id == target.id`（本人经管理台给自己改密） | `password_changed` | – | `修改了自己的密码` |
| 6 | `routes/me.py::change_password` | `password_changed` | – | `修改了自己的密码` |
| 7 | `routes/settings.py::patch_registration` / `rotate_invite_code` | `registration_updated` / `invite_code_rotated` | – | `更新了注册配置：{改动键列表}` / `重新生成了邀请码` |

第 7 条的 message **只列被改动的键名**（`enabled`/`invite_code`/`default_role`），
**绝不带值**——`invite_code` 的值是凭据（`services/app_settings.py:19-22` 已经把「明文存储是有意取舍」
论证过一遍，但那是给根管理员读的，不是给审计流读的）。

#### C-4 读出口：`GET /api/users/<id>/activities`

`@require_role("admin")`（不是 `require_root`：普通 admin 本来就能改这个人的角色与状态，
让他看不到自己刚做的动作没有道理）。套既有 `paginate` + `with_total_count`，
响应体是**裸数组**，与 `GET /api/users` 的既有形状一致。

#### C-5 必须同时修的两处外溢（**漏掉任何一处都是缺陷**）

1. **`routes/stats.py:52-58`**：两个 `Activity.query` 都追加
   `.filter(Activity.entity_type.in_(TICKET_ENTITY_TYPES))`。
   否则「停用了张三」会出现在**所有成员**都能打开的仪表盘「最近动态」上（E-9）。
   这不是洁癖：`recent_activities` 的消费方是 `frontend/app/(app)/dashboard/page.tsx`，
   它对每条动态按 `entity_type` 渲染跳转链接，`user` 类型会渲染成一个指向不存在工单的死链。
2. **`tools/purge_demo_data.py::_user_references`（`:354-380`）**：追加一项
   `Activity.query.filter_by(entity_type="user", entity_id=user_id).count()`。

   > **【评审 P1-4】v1 把函数名写成了 `_user_reference_count`、行号写成 `:360-380`，
   > 两个都不对**——仓库里没有那个名字，实现者会 grep 不到。真名 `_user_references`，
   > 定义在 `:354`，`return` 表达式在 `:368-380`。
   > 另需知道一件 v1 没说的事：该函数 **`:377` 已经**统计了
   > `Activity.query.filter_by(actor_type="user", actor_id=user_id)`——即「这个人**做过**
   > 治理动作」。本轮补的是另一半：「这个人**被**治理过」。两半都要有，因为一条
   > `role_changed` 记录同时指向施动者与被改的人，只计一半仍会漏掉「从没做过管理动作、
   > 但被停用过一次」的普通成员。

   理由与该函数已有的 8 项完全同构：一个有治理历史的用户被**硬删**之后，SQLite 会复用它的主键，
   下一个同 id 的用户会继承这段治理时间线——正是 `services/lifecycle.py:164-166` 记录过的
   「时间线串档」在账号维度的翻版。计入引用后，这类用户走的是「停用而非删除」分支。
   **`_is_orphan`（:292-301）不需要改**：`entity_type` 为 `"user"` 时不在 `alive` 字典里，
   函数第一个条件直接返回 False，治理审计永远不会被判成孤儿删掉（E-10 已实测）。

---

### 2.4 支柱 D —— 建号路径收敛 + 保留用户名表

#### D-1 `backend/services/accounts.py`（新建）

```python
def create_user_by_admin(data: dict, actor, *, allow_generated: bool) -> User:
    """管理员建号的唯一实现（account-security-and-governance §2.4 D-1）。

    `POST /api/users` 与 `POST /api/auth/register` 两条路由**都**调它；两条路由只负责
    自己的响应形状（前者裸 user dict，后者 {"user": ...}）与状态码。此前两处各写一份，
    上一轮已经因此漏掉了保留用户名守卫（self-service-registration §12 F-7）——
    **那个漏洞今天仍然在线**：`routes/users.py:81` 有 `is_reserved_username` 守卫，
    `routes/auth.py:79` 没有。本函数的合并动作顺带把它补上（见 §4.1′）。

    Args:
        data: 已由路由 json_body() 归一的请求体。
        actor: 当前登录的管理员（用于审计与 should_force_change 判据）。
        allow_generated: **【评审 P0-2】password 缺省时是否允许服务端生成一次性口令。**
            `POST /api/users` 传 True（新能力）；`POST /api/auth/register` 传 **False**
            （契约不变，缺 password 仍是既有的 400 `username and password are required`）。
            这个参数就是两条路由契约差异的**全部**落点——不允许再有第二处分叉。

    Returns:
        已 add 进 session、已 flush（有 id）、**尚未 commit** 的 User。
        `user.temporary_password` 是一个**瞬时属性**（非列），仅当口令由服务端生成时存在；
        `allow_generated=False` 时它恒不存在，故 register 的响应体天然不可能泄漏它。

    Raises:
        ValidationError: 字段非法 / 口令不满足策略 / (allow_generated=False 且缺 password)。
        UsernameTaken: 保留名或重名（路由渲染成 409，**两者响应体逐字节相同**）。
    """
```

`UsernameTaken` 定义在同模块，路由 `except UsernameTaken:` → 既有的
`{"error": "username already exists"}, 409`。**不改错误串**。

> **瞬时属性 vs 返回元组**：选 `user.temporary_password`（SQLAlchemy 允许在实例上挂非列属性）
> 会让「这个值是否要回传」这件事跟着对象走，路由不用多接一个变量。风险是有人误以为它入库了——
> 用属性名 + 一行注释钉死：`# 非列，仅本次响应用；绝不落库、绝不记日志`。

#### D-2 保留用户名表

`services/app_settings.py::is_reserved_username` 扩展（**签名与语义不变**）：

```python
_BUILTIN_RESERVED = ("admin", "administrator", "root", "system", "aragon",
                     "api", "support", "security", "me", "null", "undefined")

def reserved_usernames() -> frozenset:
    """当前生效的保留名集合（全部 casefold 后比较）。

    = 内置表 ∪ RESERVED_USERNAMES 配置项 ∪ {ROOT_ADMIN_USERNAME}。
    空配置项、空白项一律忽略；空的 ROOT_ADMIN_USERNAME 不入集（与现状一致）。
    """
```

**只作用于「新建账号」这一刻**，不追溯任何存量行：一个叫 `system` 的既有账号继续正常工作。
这一点必须在 README 写明，否则升级后运维会以为要去改数据。

**`me`/`null`/`undefined` 为什么在表里**：它们是前端路由与 JSON 序列化里最典型的歧义源
（`/api/users/me` 这类路径在未来一定会有人想加）。现在拦下的成本是零。

---

### 2.5 权限矩阵（本轮涉及的端点，全表）

| 端点 | 匿名 | member | pm | admin | root | 备注 |
|---|---|---|---|---|---|---|
| `POST /api/auth/signup` | ✅ | ✅ | ✅ | ✅ | ✅ | 限流 + 邀请码 |
| `GET /api/auth/registration-meta` | ✅ | ✅ | ✅ | ✅ | ✅ | 含策略三键 |
| `POST /api/users` | ❌401 | ❌403 | ❌403 | ✅ | ✅ | password 可选 |
| `POST /api/users/:id/reset-password` | ❌401 | ❌403 | ❌403 | ✅ | ✅ | 目标为 root → 409 |
| `GET /api/users/:id/activities` | ❌401 | ❌403 | ❌403 | ✅ | ✅ | |
| `POST /api/me/password` | ❌401 | ✅ | ✅ | ✅ | ✅ | 闸门豁免 |
| `GET/PATCH /api/settings/registration` | ❌401 | ❌403 | ❌403 | ❌403 | ✅ | 现状不变 |
| **任意其他 `/api/*`（带 must_change_password）** | – | ❌403 | ❌403 | ❌403 | ❌403 | 闸门；root 理论上不会置位 |

---

## 3. 文件 / 模块变更计划

### 3.1 后端 —— 新建（4）

| 文件 | 意图（一句话） |
|---|---|
| `backend/services/accounts.py` | 管理员建号的唯一实现，两条路由共用；`UsernameTaken` 异常 |
| `backend/services/audit.py` | 账号 / 站点治理审计的唯一写入口 + 时间线查询 |
| `backend/tests/test_password_policy.py` | 统一口令策略 + 一次性口令生成的用例 |
| `backend/tests/test_account_governance.py` | 强制改密闸门 + 治理审计 + 保留名表的用例 |

### 3.2 后端 —— 修改（17）

| 文件 | 改动 |
|---|---|
| `backend/config.py` | 新增 `PASSWORD_MIN_LENGTH` / `PASSWORD_MIN_CHAR_CLASSES` / `TEMP_PASSWORD_LENGTH` / `RESERVED_USERNAMES` / `FORCE_PASSWORD_CHANGE`；`TestConfig` 保持默认（**不放宽策略**，让用例跑在真实水位上） |
| `backend/services/passwords.py` | 改写为全站策略模块（§2.1 A-1）；`validate_signup_password` 保留为别名 |
| `backend/services/auth_helpers.py` | 新增 `install_password_gate(app)` + 豁免集 |
| `backend/services/app_settings.py` | `reserved_usernames()` + `is_reserved_username` 走新集合 |
| `backend/services/schema_sync.py` | `ADDITIVE_COLUMNS` 追加 `users.must_change_password` |
| `backend/models/user.py` | 新增列 + `to_dict` 追加键（`summary()` 不动） |
| `backend/models/activity.py` | `TICKET_ENTITY_TYPES` / `ENTITY_TYPES` / `APP_SETTING_ENTITY_ID`；`from_status` 列注释说明复用 |
| `backend/app.py` | `register_blueprints` 之后调 `install_password_gate(app)` |
| `backend/routes/users.py` | 建号改调 `accounts.create_user_by_admin`；`patch_user` 接策略 + 置位 + 审计；新增 `reset_password` 与 `user_activities` 两个端点 |
| `backend/routes/auth.py` | `register` 改调同一服务函数；`signup` 追加审计；`registration_meta` 追加两键 |
| `backend/routes/me.py` | 删两个私有常量，改调 `validate_password`；成功后清 `must_change_password` + 写审计 |
| `backend/routes/settings.py` | 两个写端点追加审计 |
| `backend/routes/stats.py` | 两处 `Activity.query` 追加 `entity_type.in_(TICKET_ENTITY_TYPES)` |
| `backend/tools/purge_demo_data.py` | `_user_references`（`:354`）追加「被治理」计数 |
| `backend/models/__init__.py` | **【评审 P2-3】** `:12` 的 import 与 `:30` 的 `__all__` 追加 `TICKET_ENTITY_TYPES` / `APP_SETTING_ENTITY_ID`——本仓库的符号再导出约定，不登记就是新孤岛 |
| `backend/routes/projects.py` | **【评审 P2-4】** `:147-148` 的注释「Activity 只承载 requirement/bug 两种实体」在本轮之后成为**过期注释**（僵尸注释，CLAUDE.md §四）。改写为：「Activity 现已承载 user/app_setting，但**项目 / Agent 的删除有意仍走结构化日志**——它们不是账号治理，给它们建实体维度会让 `entity_type` 变成一个什么都装的垃圾桶（本轮非目标，见 §10）。」 |
| `backend/services/bootstrap.py` | 仅加注释：**不得** import `services/accounts.py`；破窗路径有意不依赖任何口令策略（§7 R-14） |

### 3.3 后端 —— 既有用例的必要修改（4 处，见 §8.1）

| 文件:行 | 现状 | 改为 |
|---|---|---|
| `tests/test_hardening_r3.py:179` | `password: "p"` 断言 201 | `password: "Aragon2026"`，断言仍为 201 |
| `tests/test_validation.py:353` | `password: "pw12345"` 断言 201 | `password: "Pw123456"` |
| `tests/test_auth.py:30` | `password: "pw12345"`（admin 分支断言 201） | `password: "Pw123456"` |
| `tests/test_settings.py:95` | `new_password: "123"` 断言 400 | 保持不变（仍 400），**只核对错误串是否被断言**；若断言了旧串则同步 |

### 3.4 前端 —— 新建（5）

| 文件 | 意图 |
|---|---|
| `frontend/app/force-password/page.tsx` | 强制改密页（在 `(app)` 分组**之外**，无侧边栏，与 `/login` 同级）。**自带两条反向守卫**，见 §6.1 |
| `frontend/components/admin/TemporaryPasswordDialog.tsx` | 一次性口令的**唯一一次**展示 + 复制 + 「已保存」确认 |
| `frontend/components/admin/MemberActivityModal.tsx` | 账号动态（治理时间线）。**【评审 P1-5】由「抽屉」改为「Modal」**——仓库里没有通用 `Drawer`（`components/ui/` 15 个文件里没有；唯一的 `TicketDrawer.tsx` 与工单强耦合，含 `useTicket` / 评论流 / agent-advance，不可复用为壳）。为一条只读时间线先造一套抽屉框架不划算；既有 `ui/Modal.tsx` 已带 focus trap / Esc / `aria-modal` / `useOverlayLayer` 层级管理 |
| `frontend/hooks/useUserActivities.ts` | 分页读 `/users/:id/activities` |
| `frontend/components/ui/CopyButton.tsx` | 从 `RegistrationCard.tsx:28-45` 提取（实测：全仓 `clipboard` 只有那 4 处命中，本轮要用第三次，正是提取的时机） |

> **v1 的 `frontend/hooks/usePasswordPolicy.ts` 已删除**（评审 P1-2）：改为扩展既有
> `frontend/hooks/useRegistrationMeta.ts`，见 §2.1 A-3 ①。

### 3.5 前端 —— 修改（12）

| 文件 | 改动 |
|---|---|
| `frontend/lib/types.ts` | `User.must_change_password`；新增 `PasswordPolicy` / `UserActivity` / `UserActivityAction` / `CreatedUser`（含 `temporary_password`）；`RegistrationMeta` 追加两键 |
| `frontend/lib/api.ts` | 新增 `signalPasswordChangeRequired`（403 + `error === "password change required"` → 广播 `aragon:password-change-required`）。形状与既有 `signalUnauthorizedIfNeeded`（`:75-80`）逐条对齐，**但绝不 `setToken(null)`**——那是登出，不是本轮语义 |
| `frontend/lib/auth.tsx` | 订阅该事件 → 调 `restore()` 刷新登录态（不清 token，**这不是登出**）。`restore()` 是 `AuthProvider` 内的 `useCallback`（`:36`），监听器就装在同一个组件里（与既有 `aragon:unauthorized` 监听器 `:61-68` 并列），作用域天然可达；对外仍只暴露 `refresh()` |
| `frontend/hooks/useRegistrationMeta.ts` | **【评审 P1-2】** 返回值追加派生的 `policy: PasswordPolicy`；既有 `meta` / `resolved` 两键逐字不变，`login/page.tsx:23` 与 `register/page.tsx:22` 零改动 |
| `frontend/app/(app)/layout.tsx` | 守卫追加：`user.must_change_password` → `router.replace("/force-password")`（排在既有的 `!user → /login` 之后） |
| `frontend/components/auth/PasswordStrength.tsx` | **【评审 P1-3】** `passwordRules` / `isPasswordAcceptable` / 默认导出组件三者统一追加**可选末位参数** `policy`（默认值 = 现有常量，故未迁移的调用点行为逐字不变）；`countCharClasses`（`:24`）逐字不动 |
| `frontend/components/auth/RegisterForm.tsx` | **【评审 P1-3，v1 漏列】** `:38` 的 `isPasswordAcceptable(...)` 与它渲染的 `<PasswordStrength>` 都传 `useRegistrationMeta().policy`。**不改这一处，策略可配置就是假的**：注册页仍按 8 放行、点提交才 400 |
| `frontend/components/settings/PasswordCard.tsx` | **【评审 P2-2】** 删**两处**硬编码——`:19` 的 `next.length < 6` 与 `:55` 的 label「新密码（至少 6 位）」；接 `useRegistrationMeta().policy` + `PasswordStrength` |
| `frontend/components/admin/MemberFormModal.tsx` | 建号：口令改为「自动生成（默认）/ 手动输入」二选一（用既有 `ui/Toggle.tsx`）；重置：改走新端点，成功后弹 `TemporaryPasswordDialog`；**【评审 P2-2】删四处硬编码**——`:81`、`:190` 两处 `length < 6`，以及 `:107`、`:232` 两处 placeholder「至少 6 位」 |
| `frontend/app/(app)/team/page.tsx` | `RowActions`（`:264-297`）追加「动态」；接 `MemberActivityModal`；重置成功后展示一次性口令。既有的 `disabled={user.is_root}` 与 `ROOT_LOCK_HINT` 逐字保留 |
| `frontend/components/settings/RegistrationCard.tsx` | 内联的 `CopyButton`（`:28-45`）迁到 `ui/CopyButton.tsx`，两个调用点（`:163` / `:190`）改 import |
| `frontend/lib/constants.ts` | `USER_ACTIVITY_LABELS: Record<UserActivityAction, string>`（**收紧到 Record，漏一个即编译错误**——与既有 `NOTIFICATION_LABELS`（`:148`）同款手法，也是上一轮评审 P1-6 的同款手法） |

### 3.6 文档（2，由实现节点在同一提交内完成）

| 文件 | 改动 |
|---|---|
| `README.md` | 配置表追加 5 个新键；新增「口令策略」与「忘记密码 / 重置流程」两小节；写明保留名表不追溯存量 |
| `docs/iterations.md` | 追加本轮小节（含破坏性变更告示） |

---

## 4. 接口设计（REST）

### 4.1 `POST /api/users` —— 扩展（admin）

**Request**

```jsonc
{
  "username": "linlei",          // 必填，≤64，非保留名
  "password": "Aragon2026",      // **可选**（新）；缺省 → 服务端生成一次性口令
  "role": "member",              // 可选，∈ ROLES，默认 member
  "display_name": "林磊",         // 可选，≤128
  "email": "lin@example.com"     // 可选，格式校验
}
```

**Response 201**

```jsonc
{
  "id": 12, "username": "linlei", "role": "member", "display_name": "林磊",
  "email": "lin@example.com", "avatar_color": "#3B6EA5",
  "is_active": true, "is_root": false, "source": "admin",
  "must_change_password": true,          // 新增
  "created_at": "…", "updated_at": "…",
  "temporary_password": "Kx7mPq2Rn9tD"   // 新增；仅当服务端生成时非 null，**此后永不可读**
}
```

| 状态码 | 触发条件 |
|---|---|
| 400 | 用户名缺失 / 非串 / 超长；email 非串 / 超长 / 格式非法；role 不在枚举；**口令不满足策略（新）** |
| 401 | 未登录 |
| 403 | 非 admin |
| 409 | 用户名已存在**或**命中保留名（响应体逐字节相同） |

### 4.1′ `POST /api/auth/register` —— 收紧但**不放宽**（admin）【评审 P0-2 新增】

v1 只写了 `POST /api/users` 的契约，却让两条路由共用同一个服务函数——于是「register 的
password 会不会也变可选、要不要回传 `temporary_password`、要不要加保留名 409」这三个问题
全部悬空，而 `backend/routes/auth.py:5` 的模块 docstring 还明写着该端点契约「逐字不变」。
本节把它定死。

**Request**：字段与今天**逐字相同**（`username` 必填、`password` **仍必填**、`role` / `display_name` / `email` 可选）。

**Response 201**：`{"user": {…}}` —— 形状不变，`user` 内多一个 additive 的
`must_change_password: true`；**顶层不含 `temporary_password`**（`allow_generated=False`
时服务函数根本不会挂那个瞬时属性，故这里不是「记得别回传」，而是**结构上不可能回传**）。

| 状态码 | 与今天相比 | 说明 |
|---|---|---|
| 400 缺 username / password | **不变** | `allow_generated=False` 保住了这条既有契约。**register 有意不获得「不填口令」这个新能力**——它是给存量管理台与脚本用的兼容端点，扩它的能力面等于制造第二个主入口；新能力只长在 `POST /api/users` 上 |
| 400 口令不满足策略 | **新增（破坏性）** | 与 §4.1 同一次破坏性变更，同一条 R-1，同一条告示。§8.1 已列出受影响的既有用例 |
| 409 命中保留名 | **新增（修复）** | **这不是破坏性变更，是补一个今天真实存在的缺口**：`routes/users.py:81` 有 `is_reserved_username` 守卫，`routes/auth.py:79` **没有**。两条建号路径的水位从上一轮起就是分叉的（self-service-registration §12 F-7 预言的漂移，现在被合并动作顺带修掉）。响应体与重名 409 逐字节相同 |
| 401 / 403 / 其他 400 | 不变 | 门禁与字段校验逐字不动 |

`routes/auth.py:5` 的模块 docstring 必须同步改写——留着「逐字不变」这句话而实际改了三处，
是让下一个读者被文档骗一次（CLAUDE.md §四：删除僵尸注释）。

### 4.2 `POST /api/users/<int:user_id>/reset-password` —— 新增（admin）

**Request**：`{}` 或 `{"password": "Aragon2026"}`

**Response 200**：`{"user": {…}, "temporary_password": "…"|null}`

| 状态码 | 触发条件 |
|---|---|
| 400 | 指定的口令不满足策略 |
| 401 / 403 | 未登录 / 非 admin |
| 404 | 用户不存在 |
| 409 | 目标是根管理员且操作者不是他本人（`lifecycle.conflict_root_admin`，错误体与既有一致） |

> **【评审 P0-1】409 的判据与请求体无关。** 空 body（生成一次性口令）**同样** 409。
> 判定顺序必须是：`404 用户不存在` → `409 根管理员保护` → `读 body` → `400 口令不满足策略`。
> 把根管理员守卫排在读 body 之后、或复用 `_reject_root_mutation`，都会让空 body 的重置
> 悄悄放行——那是一条完整的破窗账号接管路径。实现细节与理由见 §2.2 B-4。

### 4.3 `GET /api/users/<int:user_id>/activities` —— 新增（admin）

Query：`limit`（≤200，默认 50）/ `offset`。
Response 200：`Activity.to_dict()` 的**裸数组** + `X-Total-Count` 头。
404：用户不存在（不是返回空数组——不存在与没有动态是两件事）。

### 4.4 `POST /api/me/password` —— 收紧（任意登录用户）

请求体不变（`current_password` / `new_password`）。变化：

- 新口令改由 `validate_password` 判定 → 400，`detail.field = "password"`，
  `detail.expected` 是完整规则串（此前是一句裸文案，无 `detail`）。
  **既有错误串 `"new password must differ from current"` 与
  `"current password is incorrect"` 逐字保留**。
- 成功时清 `must_change_password` 并写一条 `password_changed` 审计。
- 响应体仍是 `{"ok": true}`（不变）。

### 4.5 `GET /api/auth/registration-meta` —— additive

见 §2.1 A-3。既有三键逐字不变，新增两键。

### 4.6 全局 403 契约（闸门）

```jsonc
{
  "error": "password change required",
  "detail": { "reason": "your password was set by an administrator",
              "endpoint": "POST /api/me/password" }
}
```

**`error` 串是前端的判据，勿更名**（对外错误契约，CLAUDE.md §五）。
**不带 `allowed` 键**——前端看板拖拽以 `err.allowed` 是否存在分流错误
（`services/lifecycle.py:83-85` 的既有约定），不得误伤。

---

## 5. 数据模型

### 5.1 `users` 新增列

| 列 | 类型 | 约束 | 迁移 |
|---|---|---|---|
| `must_change_password` | BOOLEAN | NOT NULL DEFAULT 0 | `ADDITIVE_COLUMNS` 追加 `("users", "must_change_password", "BOOLEAN NOT NULL DEFAULT 0")` |

存量行零回填即语义正确。**`schema_sync` 的双向漂移守卫用例**（上一轮 P1-4 加的那条）会自动
覆盖这一列——它断言「模型里的列集合 ⊆ 清单」与反向，漏登记即红。

### 5.2 `activities` —— 无 DDL 变更

只扩 Python 侧枚举。**这意味着零迁移风险**：`entity_type` 是 `String(16)`，
`"user"` / `"app_setting"` 都在列宽内。

### 5.3 审计行的取值约定

| 场景 | entity_type | entity_id | actor | from_status | to_status |
|---|---|---|---|---|---|
| 建号 | `user` | 新用户 id | `("user", admin.id)` | `None` | 角色 |
| 自助注册 | `user` | 新用户 id | `("user", 本人 id)` | `None` | 角色 |
| 改角色 | `user` | 目标 id | `("user", admin.id)` | 旧角色 | 新角色 |
| 停用 / 启用 | `user` | 目标 id | `("user", admin.id)` | `active`/`disabled` | `disabled`/`active` |
| 他人重置口令 | `user` | 目标 id | `("user", admin.id)` | `None` | `None` |
| 本人改密 | `user` | 本人 id | `("user", 本人 id)` | `None` | `None` |
| 注册配置变更 | `app_setting` | `0` | `("user", root.id)` | `None` | `None` |

### 5.4 前端类型（`lib/types.ts`）

```ts
export interface PasswordPolicy {
  minLength: number;
  maxLength: number;
  minCharClasses: number;
}

export type UserActivityAction =
  | "user_created" | "user_registered" | "role_changed"
  | "activated" | "deactivated" | "password_reset" | "password_changed";

export interface UserActivity {
  id: number;
  entity_type: "user";
  entity_id: number;
  action: UserActivityAction;
  from_status: string | null;
  to_status: string | null;
  actor_type: AuthorType | null;
  actor_id: number | null;
  message: string | null;
  created_at: string;
}

/** POST /api/users 与 reset-password 的响应：一次性口令仅此一次可读。 */
export interface CreatedUser extends User {
  temporary_password: string | null;
}
```

`User` 追加 `must_change_password: boolean`。

---

## 6. 前端设计（信息架构与交互）

### 6.1 `/force-password` 强制改密页

- **布局**：复用 `components/auth/AuthSplitLayout`（`{title, subtitle, children, footer?}`，
  与 `/login`、`/register` 同一视觉语言）。**不渲染侧边栏**——此刻用户不能去任何别的地方，
  给他看导航是残忍的假象。
- **两条反向守卫（【评审 P1-6】v1 漏了，缺了会出两种坏状态）**：本页在 `(app)` 路由组
  **之外**，因此**拿不到** `(app)/layout.tsx:16` 那条 `!user → /login` 守卫，必须自己写：

  ```tsx
  const { user, loading } = useAuth();
  useEffect(() => {
    if (loading) return;
    if (!user) router.replace("/login");                    // ① 未登录 → 别渲染空表单
    else if (!user.must_change_password) router.replace("/dashboard");  // ② 已改完 → 别把人停在没有出口的页面
  }, [user, loading, router]);
  ```

  形状与 `app/login/page.tsx:29-31` 的既有反向守卫（`user → /dashboard`）一致，
  不发明第二套写法。`loading` 期间与既有页面一样渲染「正在加载…」，
  避免守卫在会话复原完成前误跳。
- **多一跳是可接受的**：根 `app/page.tsx:14` 的既有重定向是 `user ? /dashboard : /login`，
  所以一个被标记的人从 `/` 进来会走 `/` → `/dashboard` →（`(app)/layout` 守卫）→
  `/force-password`。三跳都是 `router.replace`，浏览器历史里只留最后一个，
  用户看到的是一次加载。**有意不改 `app/page.tsx`**：让根重定向去关心口令状态，
  等于把这条规则复制到第三个地方。
- **文案层次**（三行，从「发生了什么」到「你要做什么」）：
  标题「请先设置你的新密码」；副标题「当前密码由管理员设置，仅用于首次登录」；
  正文一句「设置完成后会自动进入工作台」。
- **表单**：当前密码（= 管理员给的一次性口令）/ 新密码 / 确认新密码 + `PasswordStrength`。
- **成功后**：`refresh()` 刷新登录态 → `must_change_password` 变 false →
  `router.replace("/dashboard")`。
- **右上角保留「退出登录」**：一个不想现在改的人必须能走开，否则这个页面就是一个死循环。
- **a11y**：三个输入框 `autoComplete` 分别为 `current-password` / `new-password` / `new-password`；
  错误文案 `role="alert" aria-live="polite"`（与 `RegisterForm.tsx:79-85` 同款）。

### 6.2 一次性口令对话框

- 触发：管理员建号成功且 `temporary_password != null`，或重置口令成功。
- 形态：`Modal` + 等宽字体大字号展示口令 + 「复制」按钮 + 一行强提示
  「**这是唯一一次看到它**，关闭后无法再查看；请立刻发给 {显示名}」。
- **关闭需要显式确认**（一个「我已保存并发送」按钮），不允许点遮罩关闭——
  这是本产品里少数几个「误关就丢数据」的对话框之一。
- 复制失败必须说出来（复用 `RegistrationCard.tsx:28-45` 的 `CopyButton` 做法，
  **提取为 `components/ui/CopyButton.tsx` 共用**，而不是复制第三份）。

### 6.3 团队页：账号动态

- 行操作从「编辑 / 重置密码 / 停用」变为「编辑 / 重置密码 / 动态 / 停用」（`RowActions`，
  `team/page.tsx:264-297`）。4 个操作在 md 以下会挤——移动端卡片布局里把「动态」收进第二行
  （该布局已存在，`team/page.tsx:139-146`，桌面表格与移动卡片共用同一个 `RowActions`）。
  既有的 `disabled={user.is_root}` + `ROOT_LOCK_HINT` 只作用于「重置密码 / 停用」两项，
  **「动态」对根管理员照常可用**——看治理历史不是危险操作。
- **【评审 P1-5】容器是 `ui/Modal.tsx`，不是抽屉**。仓库里没有通用 `Drawer`：
  `components/ui/` 的 15 个文件（Avatar / Badge / Button / Checkbox / ConfirmDialog /
  EmptyState / ErrorState / Input / **Modal** / Pagination / ProgressBar / Select /
  Skeleton / Textarea / **Toggle**）里没有它；唯一的抽屉 `components/TicketDrawer.tsx`
  与工单强耦合（`useTicket` / 评论流 / agent-advance），不是可复用的壳。
  为一条只读时间线先造一套抽屉框架，代价明显高于收益——而 `Modal` 已经带了
  focus trap、Esc（经 `lib/overlay-stack.ts` 判定是否为顶层）、`role="dialog"` /
  `aria-modal`，正是这块内容需要的全部东西。`width` 传 640。
- 内容：倒序时间线，每行 = 图标 + 中文动作短语 + 施动者 + 相对时间；
  空态用既有 `ui/EmptyState.tsx`，文案「这个账号还没有治理记录」。
- **权限**：非 admin 不渲染入口（后端 `require_role("admin")` 才是门禁，
  前端隐藏只为体验，与 `RegistrationCard` 的既有取向一致）。

### 6.4 建号表单的口令交互

默认态是「**自动生成一次性密码**」（一个 `Toggle`，默认开）。开着时口令输入框隐藏，
提交后弹一次性口令对话框。关掉则显示口令输入框 + `PasswordStrength`。
这个默认值是本轮 UX 的核心主张：**管理员不该替别人想密码**，产品要让「正确的事」成为默认路径。

---

## 7. 风险与缓解

| # | 风险 | 缓解 |
|---|---|---|
| R-1 | **破坏性变更**：`POST /api/users` / `POST /api/auth/register` 的弱口令由 201 变 400 | 唯一一次有意破坏，README + `docs/iterations.md` 显式告示；§8.1 逐条列出受影响的既有用例；**登录路径永不重新校验口令**，存量弱口令用户不会被锁在门外 |
| R-2 | 闸门拦住 CORS 预检 → 全站跨域瘫痪 | `OPTIONS` 第一顺位放行 + 专门用例 `test_gate_never_blocks_options` |
| R-3 | 闸门把根管理员也关进去（破窗路径断裂） | `ensure_root_admin` 恒不置位；`FORCE_PASSWORD_CHANGE` 兜底开关；用例断言 root 建号后该列为 False |
| R-4 | 闸门的豁免集写漏 `GET /api/auth/me` → 前端读不回登录态，白屏死循环 | 豁免集是 frozenset 常量 + 逐条用例；`/force-password` 页只依赖 `/auth/me` 与 `/me/password` 两个端点 |
| R-5 | `verify_jwt_in_request(optional=True)` 对**已吊销**（停用）token 抛异常，若不捕获则 500 | 捕获 `JWTExtendedException` / `PyJWTError` 后放行，让端点的 `@jwt_required()` 产出既有 401；用例 `test_disabled_user_still_gets_401_not_500` |
| R-6 | 一次性口令泄露（日志 / 审计 / 二次可读） | 只在生成它的那一次响应体里出现；`audit.py` 模块级硬约束；`observability.py` 的访问日志只记路径与状态码，不记 body（现状，需在用例里钉住） |
| R-7 | 治理审计外溢到全员可见的仪表盘 | §2.3 C-5-1 的 `entity_type.in_(TICKET_ENTITY_TYPES)` + 用例 `test_stats_never_leaks_user_activities` |
| R-8 | 硬删用户后审计串档（SQLite 主键复用） | §2.3 C-5-2 的引用计数；用例断言「有治理历史的用户被 purge 判为停用而非删除」 |
| R-9 | `PASSWORD_MIN_LENGTH` 被设成荒谬值导致全员改不了密码 | `policy()` 钳位到 `[6, 128]` / `[1, 4]`；用例覆盖 `0` / `999` / `"abc"` 三种脏值 |
| R-10 | 保留名表误伤存量账号 | 只在建号那一刻判定；README 写明不追溯；用例断言存量 `system` 用户仍能登录与被改资料 |
| R-11 | `activities` 增长（每次改密都写一行） | 本轮新增的写入点都是**低频人工动作**（建号 / 改角色 / 停用 / 改密），量级远低于工单流转；且 CLAUDE.md 已规定这张表永不按数量清理，本轮不引入新策略 |
| R-12 | 前端 `PasswordStrength` 参数化后与后端再次分叉 | 参数只有两个阈值，判据函数 `countCharClasses` **逐字不动**（它是上一轮 P1 修过的 Unicode 同源实现）；策略值统一由 `registration-meta` 下发 |
| R-13 | `POST /api/users` 的 `password` 变可选后，前端老代码传 `""` 空串 | 空串按「未提供」处理（`want_str` 的既有归一语义就是空串），走生成分支；用例钉住 |
| R-14 | **【评审新增】** 有人「顺手」让 `ensure_root_admin` 也过一遍口令策略 → 存量部署里一个 7 位的 `ROOT_ADMIN_PASSWORD` 会让**应用起不来**，而这个账号是唯一的破窗入口，等于把一次配置瑕疵升级成一次完全无法自愈的全站宕机 | `services/bootstrap.py` **不得** import `services/accounts.py` 或 `validate_password`，破窗路径有意不依赖任何策略（§2.2 B-2 表末行 + §3.2 该文件的注释改动）；`_warn_about_weak_setup`（`bootstrap.py:94`）已有的启动期 warning 是这条风险的正确处置方式——**告警，不阻断** |
| R-15 | **【评审新增】** 新端点 `POST /api/users/:id/reset-password` 复用了一个为 `PATCH` 形状写的守卫 → 根管理员被他人重置口令（P0-1 的原始形态） | §2.2 B-4 的独立判据 + §4.2 的判定顺序 + `_reject_root_mutation` docstring 上的「不得复用」前提 + 用例 35（含**空 body** 与**带 password** 两个变体） |
| R-16 | **【评审新增】** 前端策略只穿进了 `PasswordStrength` 组件，没穿进 `isPasswordAcceptable` → 「前端拦下的一定是后端也会拒的」这条不变量在策略被调高后**静默失效**（P1-3 的原始形态） | §2.1 A-3 ② 的三函数统一签名 + §3.5 显式列出 `RegisterForm.tsx:38`；`npm run typecheck` **拦不住**这一类（可选参数有默认值），故 §8.3 增一条手工验收 |

---

## 8. 测试与验收标准

### 8.1 既有用例的影响分析（**实施前必须先跑这一节**）【评审 P0-3：整节重写】

> **v1 错在哪**：v1 自述扫描范围是「`POST /api/users` 与 `POST /api/auth/register` 的调用点」，
> 但本轮实际收紧了**四条**写入路径（另两条是 `PATCH /api/users/:id` 带 password 与
> `POST /api/me/password`），并且**完全没有分析强制改密闸门对既有用例的影响**——
> 闸门是本轮侵入性最强的改动，它能让任何「经 API 建号 / 重置口令之后，再拿那个账号发
> 非豁免请求」的用例集体 403。§8.4 的「零失败」DoD 建立在这份分析上，分析漏了一半，
> DoD 就是假的。下面是评审现场重跑的完整扫描。

#### 8.1.1 口令策略：四条路径的完整扫描

策略校验的**位置**决定了影响面：它排在用户名 / email / role 校验**之后**、落库**之前**。
因此所有「因别的字段非法而断言 400」的用例行为不变。

**路径 ① `POST /api/users`**（14 个调用点）与**路径 ② `POST /api/auth/register`**（6 个调用点）
——断言会翻转的只有 3 条：

| 文件:行 | 口令 | 现断言 | 新行为 | 处理 |
|---|---|---|---|---|
| `tests/test_hardening_r3.py:179` | `"p"` | 201 | 400 | 改口令为 `"Aragon2026"` |
| `tests/test_validation.py:353` | `"pw12345"`（7 位） | 201 | 400 | 改为 `"Pw123456"` |
| `tests/test_auth.py:30-35` | `"pw12345"` | member 403 / admin 201 | admin 分支 400 | 改为 `"Pw123456"` |

**路径 ③ `PATCH /api/users/:id` 带 password**（v1 未扫）——唯一调用点
`tests/test_admin_console.py:47-51`，口令 `"newpw123"`（8 位、小写 + 数字 = 2 类、≠ 用户名
`member`）**过策略，断言不翻转**。但它现在会给 `member` 置上 `must_change_password`——
该用例随后只调 `login()`（闸门豁免），故仍绿。**这条必须写下来**：它是全套用例里唯一
「经 API 改口令后还继续用那个账号」的地方，也是闸门影响面的边界。

**路径 ④ `POST /api/me/password`**（v1 未扫）——`tests/test_settings.py` 四条，逐条核对：

| 文件:行 | 新口令 | 现断言 | 新行为 | 结论 |
|---|---|---|---|---|
| `:75-82` | `"newpass456"` | 200 | 10 位、2 类、≠ `member`、≠ 旧 → 过 | 不变 |
| `:85-90` | `"newpass456"`（旧口令错） | 400 `incorrect` | 旧口令判据**排在策略之前**（§2.1 A-2 明写顺序不可换） | 不变 |
| `:93-97` | `"123"` | 400 | 3 位 → 长度规则先失败 | 仍 400，**但错误串从 `new password must be 6..128 chars` 变为 `password must be 8..128 chars`**。该用例只断言状态码，故绿；**下游实现者仍须知道这个串变了**（README 的口令策略小节要写） |
| `:100-104` | `"member123"`（= 旧口令） | 400 `must differ` | 规则 4 命中，串逐字保留 | 不变 |

#### 8.1.2 强制改密闸门：对既有用例的影响（v1 完全缺失）

判据是三条同时成立才会出事：**(a)** 某个账号的口令由 API 设过（建号或他人重置），
**(b)** 该账号随后取得 token，**(c)** 拿它调了一个**非豁免**端点。

评审已对全部 42 个测试文件扫描 `client.post("/api/users"` / `"/api/auth/register"` 之后是否
出现 `login(<新账号>` 或以其 token 发请求。**结论：零命中。** 逐条说明：

- `test_lifecycle.py:39` / `:52` 建 `admin2` 后，所有后续请求都用 **fixture 的 admin** 发出（`auth("admin")`），从不以 `admin2` 登录；
- `test_admin_console.py:14` / `:27` / `:56`、`test_registration.py:137` / `:204`、`test_auth.py:35`、`test_validation.py:89` / `:278` / `:353`、`test_hardening_r3.py:168-179`、`test_rbac.py:14` 建完即断言，不再使用该账号；
- `conftest.py::_install_fixtures`（`:28-54`）的 admin / pm / member / member2 **直接经模型构造**，`must_change_password` 走列默认 `False`，全套用例的 `auth(role)` 因此不受闸门影响；
- 自助注册路径（`test_registration.py` 的 `_signup`）按 §2.2 B-2 保持 `False`，其后续请求正常。

**因此：闸门不会让任何既有用例翻转。** 但这个结论**依赖于「conftest 不改」**——
实施节点若为了省事把 fixture 用户改成走 `POST /api/users` 创建，全套 674 条会成片 403。
故 §8.2 增一条防回归用例 `fixture_users_are_not_flagged`（编号 30′）把它钉住。

#### 8.1.3 明确不受影响（逐条核对过）

`test_admin_console.py:14/27/56`（`"pw123456"` = 8 位 2 类，过策略）、
`test_lifecycle.py:39/52`（`"admin2123"` 过）、`test_rbac.py:14`（断言 403，门禁先于校验）、
`test_hardening_r3.py:168/170/174`（断言 400，用户名 / email 先失败）、
`test_registration.py:137/204/304`、`test_validation.py:41/89/269/278`（同上）、
`test_settings.py:77`（`"newpass456"` 过）、
`tests/test_schema_sync.py:104` 与 `:133` 的双向漂移守卫（新列只需登记 `ADDITIVE_COLUMNS`；
`_BASELINE_COLUMNS` 快照的既有约定是「只减不增」，**不必**动它）。

### 8.2 新增后端用例清单（**56 条**，每条对应一个真实失败模式）

> **【评审 P2-1】计数订正**：v1 标题写「46 条」，但正文是 46 条编号 + 末尾 4 条未编号 = 50。
> v2 在评审驱动下再增 6 条（编号 14′ / 30′ / 35′ / 38′ / 47 / 48），合计 **56**。

**口令策略（`test_password_policy.py`，14 条）**

1. `signup_rejects_7_char_password` — 400 + `detail.field == "password"`
2. `signup_rejects_single_class_password`
3. `signup_rejects_password_equal_to_username`
4. `admin_create_rejects_weak_password` — **本轮破坏性变更的正面证据**
5. `admin_create_accepts_strong_password`
6. `admin_reset_via_patch_rejects_weak_password`
7. `self_change_rejects_weak_password`
8. `self_change_still_rejects_wrong_current_password_first` — 顺序不变的回归钉
9. `self_change_still_rejects_same_as_current`
10. `policy_clamps_absurd_min_length` — `PASSWORD_MIN_LENGTH=999` → 生效值 128
11. `policy_clamps_zero_min_length` — `=0` → 生效值 6
12. `policy_falls_back_on_garbage_value` — `="abc"` → 默认 8 + 一条 warning
13. `registration_meta_exposes_policy` — 三键齐全且与 `policy()` 一致
14. `temporary_password_always_satisfies_policy` — 生成 200 次逐个过 `validate_password`
14′. **【评审 P1-1】** `temporary_password_satisfies_raised_policy` — 把
    `PASSWORD_MIN_LENGTH=40` / `PASSWORD_MIN_CHAR_CLASSES=4` 一起调高，再生成 200 次逐个过
    `validate_password`。**这条就是 P1-1 的机器执行者**：v1 的钳位区间
    `[max(min_length, 8), 32]` 在这个配置下是空区间，会生成 32 位 3 类的口令，本条必红

**一次性口令与强制改密（`test_account_governance.py` 第一组，16 条）**

15. `create_without_password_returns_temporary_password`
16. `create_with_password_returns_null_temporary_password`
17. `created_user_must_change_password_is_true`
18. `signup_user_must_change_password_is_false`
19. `temporary_password_can_log_in`
20. `gate_blocks_normal_endpoint_with_403`
21. `gate_body_has_stable_error_string` — `"password change required"` 逐字
22. `gate_body_has_no_allowed_key` — 看板错误分流不被误伤
23. `gate_allows_get_auth_me`
24. `gate_allows_post_me_password`
25. `gate_never_blocks_options` — CORS 预检
26. `gate_never_blocks_login_and_signup`
27. `changing_password_clears_the_flag_and_unblocks`
28. `disabled_user_still_gets_401_not_500` — R-5
29. `gate_off_by_config_lets_request_through` — `FORCE_PASSWORD_CHANGE=false`
30. `root_admin_is_never_flagged` — 破窗路径不被闸门断掉
30′. **【评审 P0-3】** `fixture_users_are_not_flagged` — 断言 conftest 的
    admin / pm / member / member2 四个 fixture 用户 `must_change_password` 恒为 False。
    §8.1.2 的「闸门不翻转任何既有用例」这个结论**依赖于 fixture 走模型构造**；
    哪天有人为了省事把它改成走 `POST /api/users`，本条会在那一刻红，
    而不是让 674 条用例成片 403、再由人去猜发生了什么
30″. **【评审 P1-7】** `self_service_password_change_via_patch_does_not_flag` —
    admin 用 `PATCH /api/users/<自己的 id>` 改自己的口令 → `must_change_password` 恒 False，
    且随后可以正常访问非豁免端点。v1 的无条件置位会让管理台自助改密变成一次自锁

**重置端点（10 条）**

31. `reset_password_generates_temporary_password`
32. `reset_password_accepts_explicit_password`
33. `reset_password_rejects_weak_explicit_password`
34. `reset_password_sets_must_change_flag`
35. `reset_password_on_root_conflicts_409_with_explicit_password` — body 带 password，
    错误体 = `conflict_root_admin`
35′. **【评审 P0-1，本轮最重要的一条】** `reset_password_on_root_conflicts_409_with_empty_body`
    —— body 为 `{}`（新端点的**主用法**）。v1 复用 `_reject_root_mutation` 的写法在这条上
    **必红**：那个函数的口令分支挂在 `data.get("password")` 上，空 body 恒放行 →
    任意 admin 拿到根管理员的一次性口令 → 破窗账号被完全接管。
    断言必须同时覆盖「返回 409」**与**「根管理员的 `password_hash` 逐字节未变」——
    只断状态码挡不住「先改了库再返 409」这种半吊子实现
36. `reset_password_404_for_unknown_user`
37. `reset_password_forbidden_for_pm_and_member`
38. `old_password_stops_working_after_reset`
38′. **【评审 P0-1】** `root_can_reset_own_password_and_is_not_flagged` — 根管理员对自己调
    新端点 → 200，且 `must_change_password` 恒 False（§2.2 B-2 末行的不变量）

**治理审计（`test_account_governance.py` 第二组，8 条）**

39. `role_change_writes_activity_with_from_and_to`
40. `deactivate_and_activate_write_two_activities`
41. `password_reset_writes_activity_without_any_secret` — 断言 message 不含口令子串
42. `signup_writes_user_registered_activity`
43. `settings_patch_writes_activity_without_invite_code` — 断言 message 不含码值
44. `user_activities_endpoint_paginates_and_sets_total_count`
45. `user_activities_forbidden_for_member`
46. `stats_never_leaks_user_activities` — **R-7 的机器执行者**：造一条 `user` 活动，
    断言 `recent_activities` 里没有它、`activities_this_week` 不计它

**保留名与 purge（另 4 条，编号 47–50）**

47. `reserved_username_table_blocks_root_system_api`
48. `reserved_check_is_case_insensitive`
49. `existing_user_with_reserved_name_still_works`
50. `purge_keeps_user_with_governance_history` — R-8。**造数据时该用户必须只作为
    `entity_id`（被治理对象）出现、不作为 `actor_id`**，否则 `_user_references:377` 那一项
    已经会命中，用例即使在没打补丁的代码上也是绿的——那是一条假绿的护栏

**契约与合并（评审新增，编号 51–56）**

51. **【P0-2】** `register_still_requires_password` — `POST /api/auth/register` 不带
    password → 400 `username and password are required`（**不是** 201 + 一次性口令）
52. **【P0-2】** `register_response_never_contains_temporary_password` — 断言 201 响应体
    的 JSON 里不存在 `temporary_password` 这个键（含 `user` 子对象内）
53. **【P0-2】** `register_now_blocks_reserved_username` — 合并顺带修掉的既有缺口
    （`routes/auth.py:79` 今天没有这道守卫），响应体与重名 409 逐字节相同
54. **【P0-2】** `both_create_paths_produce_identical_user_rows` — 同一份 payload 分别经
    `POST /api/users` 与 `POST /api/auth/register` 建号，除 id / username / 时间戳外
    逐字段相同。这是「同一件事只有一份实现」的机器执行者：两条路由哪天再漂移，它先红
55. **【P2-7】** `every_gate_exemption_resolves_to_a_real_route` — 遍历
    `_PASSWORD_GATE_EXEMPT`，断言每条 `(method, path)` 都能在 `app.url_map` 里解析到。
    豁免集失效的方向是**变严**（`/api/me/password` 被自己拦住 = 死循环），
    而那种故障在人工测试里表现为「改密码按钮点了没反应」，极难定位
56. **【R-14】** `weak_root_admin_password_does_not_break_boot` — 用
    `ROOT_ADMIN_PASSWORD="pw"` + `ROOT_ADMIN_BOOTSTRAP=True` 起一个 `file_app`，
    断言启动成功且该账号可登录。把破窗路径钉死在「不依赖任何口令策略」上

### 8.3 前端 / 手动验收清单

1. `npm run typecheck` 零错误——`USER_ACTIVITY_LABELS` 收紧为
   `Record<UserActivityAction, string>` 后，漏一个动作即编译失败。
2. `npm run build` 成功，产物里存在 `/force-password` 路由。
3. 管理员建号（不填口令）→ 弹出一次性口令 → 复制 → 退出 → 用新账号登录 →
   **自动落在 `/force-password`，侧边栏不可见，手动敲 `/dashboard` 会被弹回**。
4. 改完密码 → 自动进入工作台，再次刷新不再被拦。
5. 团队页「动态」抽屉能看到刚才的「创建了成员」「重置了密码」两条。
6. 用普通成员账号登录 → 仪表盘「最近动态」里**看不到**任何账号治理事件。
7. 设置页「修改密码」卡片的规则清单与注册页**逐条一致**（同一份 `PasswordStrength`）。
8. 键盘可达性：`/force-password` 上 Tab 顺序 = 当前密码 → 新密码 → 确认 → 提交 → 退出登录。
9. **【评审 R-16，typecheck 拦不住的那一类】** 把 `PASSWORD_MIN_LENGTH=12` 设进后端环境变量
   重启，刷新注册页：规则清单必须显示「至少 12 位」，且输入一个 10 位口令时**提交按钮就该被拦住**
   （而不是点下去才 400）。这条验证的是 `RegisterForm.tsx:38` 那个调用点确实传了 policy——
   `policy` 是带默认值的可选参数，漏传不会有任何编译错误。
10. **【评审 P1-6】** 未登录直接敲 `/force-password` → 跳 `/login`；已改完密码的人再敲它 →
    跳 `/dashboard`。两条都不能停在空表单上。
11. **【评审 P1-5】** 「账号动态」用 Esc 能关；它开着时再开一个 `ConfirmDialog`，Esc 先关上面那个
    （`lib/overlay-stack.ts` 的既有层级语义没被破坏）。

### 8.4 Definition of Done

- `cd backend && python -m pytest -q` → **零失败**，用例总数 **≥ 674 + 56 = 730**
  （基线 674 为设计节点现场采集；**实施前必须按 CLAUDE.md 的质量门再采一次
  `pytest -q --collect-only`，以那一次为准**——本文档里写死的任何数字都可能已经过期）。
- `cd frontend && npm run typecheck && npm run build` 均通过。
- `git status` 干净（无 `.next/`、无临时文件）；提交用 `git add <显式路径>`，
  **禁止 `git add -A/.`**。
- README 与 `docs/iterations.md` 已更新，且**破坏性变更有显式告示**。
- 手动清单 §8.3 全部通过。

---

## 9. 建议实施顺序（每步可独立提交、可回滚）

0. **先采基线**：`cd backend && python -m pytest -q --collect-only`，记下**这一次**的
   用例数与文件数。不要用本文档里的 674 / 42（CLAUDE.md 明写「每一个写下来的数字都会过期」）。
1. **策略模块**：`passwords.py` 改写 + `config.py` 五个新键 + `test_password_policy.py`
   的 14 + 1 条（含评审新增的 14′）。此步**只加不接**，全绿后再往下。
   14′ 是这一步的验收关键——它是 P1-1 那个空区间钳位的机器执行者。
2. **接策略**：`services/accounts.py`（含 `allow_generated` 与 `should_force_change`）
   + 三个路由改调 + §8.1 的 3 条既有用例修正 + 用例 51–54。
   这一步产生本轮唯一的破坏性变更，也顺带修掉 `routes/auth.py` 缺失保留名守卫这个既有缺口，
   单独成一个提交便于回滚。
3. **数据列**：`users.must_change_password` + `schema_sync` 登记 + `to_dict`。
   跑一次 `test_schema_sync.py` 确认双向漂移守卫通过。
4. **闸门**：`install_password_gate` + `app.py` 接线 + 用例 20–30″ + 用例 55。
   **落地后立刻整跑一次全量 `pytest -q`**：这是本轮侵入性最强的一步，§8.1.2 的分析说它
   不该翻转任何既有用例——那个结论必须被一次真实的整跑证实，而不是被相信。
5. **重置端点**：`POST /api/users/:id/reset-password` + 用例 31–38′。
   **35′ 必须先写、先看它红**（P0-1 的复现用例），再写守卫让它绿——
   这是 CLAUDE.md §七「修 bug 必须先写一个能稳定复现的用例」在设计缺陷上的同款做法。
6. **审计**：`services/audit.py` + 7 个接入点 + **`stats.py` 与 `purge_demo_data.py` 两处外溢修复**
   （§2.3 C-5，与审计同一提交，绝不拆开——拆开就会有一个只跑了一半的中间态被合并）。
7. **保留名表**：`reserved_usernames()` + 用例。
8. **前端**：类型 → hooks → 组件 → 页面 → 布局守卫，最后跑 typecheck + build。
9. **文档**：README + `docs/iterations.md`。

---

## 10. 明确的非目标（Non-Goals）

- **注册审批队列**：新用户仍是「注册即可用」。上一轮已论证过它可由「关开关 + 管理员代建」
  或「注册后立即停用」近似达成；本轮引入 `must_change_password` 之后，审批态会与它形成
  两个正交的「半激活」状态，产品语义会变浑浊。要做就单独一轮，并把两者合并成一个状态机。
- **口令历史 / 禁止复用最近 N 次**：需要新表 + 保留策略，且对本产品的威胁模型收益有限。
- **口令过期（90 天强制轮换）**：现代口令指南（NIST SP 800-63B）明确反对无理由的定期轮换，
  它把用户推向 `Password1` → `Password2`。**有意不做**。
- **二次验证 / TOTP**：与本轮正交，且需要移动端流程设计。
- **邮件找回密码**：仍需 SMTP，仍是上一轮的非目标。管理员重置 + 一次性口令已经把
  「忘记密码」的恢复路径从「改配置重启」降到了「找管理员点一下」——这是本轮实际交付的改善。
- **分布式限流**：`services/ratelimit.py` 仍是单机内存实现（`TODO(ratelimit-distributed)`）。
- **RBAC 重构 / 多级管理员**：`is_root` 仍是唯一的治理锚点。
- **审计的导出 / 检索**：本轮只做「某个账号的时间线」，不做全局审计检索页。

---

## 11. 附录：本轮设计所依赖的既有约定（勿违背）

1. **状态机神圣**：本轮不触碰 `services/workflow.py`，也不给账号引入状态机。
2. **加列即两步**：任何新列必须同时登记 `ADDITIVE_COLUMNS`（本轮 1 列）。
3. **五处 bootstrap 关闭点**：本轮不新增 CLI 工具，故清单仍为五处，不变。
4. **seed 一行一登记**：本轮不新增 seed 行。
5. **`comments` / `activities` / `notifications` 永不按数量清理**：本轮新增的审计行天然受这条保护。
6. **错误串是对外契约**：本轮新增 `"password change required"`，
   复用 `"username already exists"` / `"new password must differ from current"` /
   `"current password is incorrect"` / `conflict_root_admin` 的既有串，一个字都不改。
7. **前端三处通知镜像**：本轮**不新增通知类型**，故 `NOTIFICATION_TYPES` 与它的三处前端镜像
   一律不动。审计不是通知——治理事件写审计、不推送，避免把管理员的收件箱变成日志窗口。

---

## 评审结论（Review Verdict）

### **有条件通过（Approved with conditions）**

v1 是一份成色很高的设计：它没有重复上一轮，选的四个问题都是真问题（口令水位由「你是怎么进来的」
决定、管理员永久知道同事的口令、账号侧零留痕、同一件事两份实现），技术判断也大多经得起对源码的
逐条复核——复用 `activities` 而不建第二张审计表、`stats.py` 与 `purge_demo_data.py` 两处外溢的
自我发现、`OPTIONS` 必须第一顺位放行、NIST 反对定期轮换因而不做口令过期，这些都是对的，
而且是那种「不亲手读过这个仓库就写不出来」的对。

但它有**三处会直接造成事故或返工的缺陷**，其中 P0-1 是一个完整的**权限提升路径**：
新端点复用了一个为另一种请求形状写的守卫，导致任意 admin 都能接管根管理员账号——
而这个账号的全部存在意义就是「别的路都断了时的破窗入口」。这类缺陷的形状与上一轮
§12 F-7 记录的那一个几乎完全相同，说明「新端点复用旧守卫」是这个代码库反复出现的失误模式，
值得在 CLAUDE.md 里单独记一笔。

**全部 3 个 P0 与 7 个 P1 已在本文档 v2 正文中直接修复**，逐条对照见开头的「评审记录」表；
7 个 P2 也一并改掉，仅余 3 条明确记入下一轮候选（见下）。
文档现已具备「逐行可实现、无需再做设计决策」的成色。

### 放行条件（4 条，全部机器可检验）

实现节点在提交前必须逐条确认，任何一条不满足即视为未完成：

1. **用例 35′（空 body 重置根管理员 → 409 且哈希未变）先红后绿。**
   必须能拿出「打补丁前它红」的证据。这是 P0-1 唯一可信的验收方式——只写守卫不写复现用例，
   下一次重构还会把它拆掉。
2. **用例 14′（`PASSWORD_MIN_LENGTH=40` + `MIN_CHAR_CLASSES=4` 下生成的临时口令仍过策略）通过。**
   它是 P1-1 的机器执行者；顺带证明 `policy()` 的钳位与生成器的钳位是同一套逻辑派生的，
   而不是两个各自拍脑袋的魔数。
3. **第 4 步（闸门落地）之后立刻整跑一次全量 `pytest -q`，且用例总数不低于步骤 0 采集的基线。**
   §8.1.2 断言闸门不翻转任何既有用例——那是评审的静态扫描结论，必须被一次真实整跑证实。
   同时 `fixture_users_are_not_flagged`（30′）必须在库里，把这个结论钉成护栏。
4. **手工验收 §8.3 第 9 条（把 `PASSWORD_MIN_LENGTH` 调到 12，注册页必须按 12 拦）通过。**
   `npm run typecheck` 对这一类**结构上无能为力**（policy 是带默认值的可选参数，漏传不报错），
   而漏传的后果正是本产品反复承诺要避免的「界面说没问题、提交却 400」。

### 遗留的 P2（不阻塞合并，记入下一轮候选）

- 闸门给每个已认证请求增加 1 次 SELECT（P2-5）。当前量级完全无需优化，但如果哪天
  `/api/*` 的 QPS 成为问题，正确的做法是把 blocklist loader 与闸门合并成一次查询，
  而不是给闸门加缓存——**不要**在鉴权路径上引入缓存一致性问题。
- `_PASSWORD_GATE_EXEMPT` 与蓝图 `url_prefix` 仍是两份真相，用例 55 只能保证「解析得到」，
  保证不了「语义仍然对」。真正的收敛是给端点加装饰器标记再由闸门反查 `url_map`——
  那是一次值得单独做的重构，本轮的 6 条豁免还不值得。
- 项目 / Agent 的删除仍走结构化日志而非 `activities`（§10 非目标）。本轮把 `entity_type`
  的口子开了之后，下一轮会有人想把它们也塞进来。**建议不要**：那会让 `entity_type`
  从「有语义的实体维度」退化成「什么都装的垃圾桶」，而 §2.3 C-5-1 那个过滤器就是它
  开始失控的第一个征兆。

### 一句话总结

**方向对、成色高、但有一个必须先修的权限提升缺陷。修完即可实施。**

---

## 实施过程发现的方案缺陷

> 本节由**实施节点**追加，逐条记录「按 v2 正文逐字实现会出错 / 会漏」的地方，以及实际采取的
> 修正做法。凡在此列出的，实现均已按修正后的做法落地并有用例覆盖；**没有静默偏离**。

### I-1（对应评审 P1-1，**修复本身仍不完整**）一次性口令的下界必须再被 `max_length` 上钳

§2.1 A-1 把生成器的长度区间改写为 `lower = max(min_length + 4, 16)`，并明写
「`policy()["min_length"]` 的上钳值 128 > `hard_cap` 时，`upper == lower == 132`——
超过 64 是有意的」。**这一句是错的**：`policy()` 的 `max_length` 恒为 128，`min_length`
被钳到 128 时区间落在 `[132, 132]`，生成出的 132 位口令**违反策略的第 1 条规则**
（`password must be 128..128 chars`）→ `validate_password(result)` 抛异常 → 建号 / 重置
路径 500。P1-1 修的是「下界大于上界」，但换来的新写法在同一处越过了另一条边界。

**实测证据**：`test_temporary_password_satisfies_raised_policy[128-4]` 在 v2 正文的写法下
必红，报错为 `ValidationError: password must be 128..128 chars`。

**修正**：`lower = min(max(pol["min_length"] + 4, 16), pol["max_length"])`，即下界在派生之后
再被策略上限钳一次。用例改为参数化 `(40, 4)` 与 `(128, 4)` 两组——后者是这条边界的执行者，
前者是评审原本要求的 14′。

### I-2（对应评审 P0-3）§8.1 的既有用例扫描漏了 3 处，其中 1 处是口令路径

§8.1.1 的表格列出「断言会翻转的只有 3 条」。实测重跑发现**还有 3 条**：

| 文件:行 | 现状 | 为什么会翻 | 处理 |
|---|---|---|---|
| `tests/test_registration.py:305 / :307 / :310` | `test_admin_register_endpoint_unchanged` 用 `"pw12345"`（7 位）调 `POST /auth/register`，admin 分支断言 **201** | 正是 §8.1.1 说的路径 ②，但这三行不在它的 6 个调用点清单里 | 改为 `"Pw123456"`，断言保持 201 |
| `tests/test_registration.py:323` | `test_registration_meta_is_public_and_leaks_no_code` 断言 `body == {enabled, invite_required, password_min_length}`（**全等**，不是包含） | §2.1 A-3 给该端点加了两个 additive 键 | 期望字典补上两个新键 |
| `tests/test_schema_sync.py:56` | `test_adds_missing_column_to_existing_table` 断言 `applied == ["users.is_active", "users.is_root", "users.source"]`（**全等**） | §5.1 新增一列 | 期望列表补 `"users.must_change_password"` |

后两条是**同一类失败模式**：§8.1.3 只核对了 `test_schema_sync.py` 的两条双向漂移守卫
（结论正确），却没注意到同一文件里还有一条对 `applied` 列表做**全等**断言的用例；
「additive 变更不影响既有用例」这个直觉在**全等断言**面前不成立。下一轮做影响分析时，
判据应当是「grep 该端点 / 该函数的所有断言」，而不是「grep 该端点的调用点」。

### I-3 口令策略校验必须排在**重名 / 保留名 409 之后**

§8.1.1 只说策略校验「排在用户名 / email / role 校验之后、落库之前」，没有规定它与 409
的先后。实测：既有用例 `test_admin_create_user_rejects_reserved_username`
（`tests/test_registration.py:133`）用 `{"username": "rootowner", "password": "pw12345"}`
断言 **409**——若策略排在 409 之前，它会得到 400 而变红。

**修正**：`create_user_by_admin` 的顺序钉为
`字段解析 → 400 缺 username/password → 409 保留名/重名 → 400 口令策略 → 落库`，
并在 `_resolve_password` 的 docstring 上写明这条时序前提与它的执行者。
语义上这也是对的：一个用弱口令去抢注保留名的请求应当得到「这个名字不能用」（409），
而不是「换个更强的口令再来抢」（400）。

### I-4 两条建号路由合并后，`register` 的 email 校验水位被顺带提高（不可避免，且是修复）

§4.1′ 的状态码表写「401 / 403 / 其他 400 不变 —— 门禁与字段校验逐字不动」。但两条路由
此前的 email 校验**本就分叉**：`routes/users.py` 用 `want_email`（含格式校验），
`routes/auth.py:75` 用 `want_str(...) or None`（**只挡非串，不挡格式**）。合并到一个服务
函数意味着必须二选一，而选宽松的那个等于把 `POST /api/users` 的既有水位**降下来**。

**修正**：统一用 `want_email`。后果是 `POST /auth/register` 传 `"not-an-email"` 由 201 变
400——这与 §4.1′ 的「409 保留名是修复而非破坏」属同一性质（补一个真实缺口），
且**零既有用例受影响**（`test_registration.py:200` 的三路径同水位用例反而因此更成立）。
本条已在 README 的破坏性变更告示里一并写出。

### I-5 §8.2 的用例计数与实际条目数不符（56 vs 61）

§8.2 标题写「56 条」，但正文实际枚举出的**不同用例**是 61 条：
口令策略 15（1–14 + 14′）、一次性口令与闸门 18（15–30 + 30′ + 30″）、重置端点 10
（31–38 + 35′ + 38′）、治理审计 8（39–46）、保留名与 purge 4（47–50）、契约与合并 6（51–56）。
P2-1 的订正只修了「46 + 4」那一处，没有把带撇号的新增条目计进去。

**处理**：全部 61 条**逐条实现**（另加一条 `user_activities_404_for_unknown_user`——
§4.3 明写「404：用户不存在（不是返回空数组）」却没有对应用例），实际收集到 **68 条**
（含 3 处参数化展开）。DoD 的下限 `674 + 56 = 730` 因此被满足且有余量。

### I-6 §8.2 用例 35 需要一个「非根管理员的第二个 admin」，而 conftest 没有这个 fixture

用例 35 / 35′ 的语义是「**别的** admin 去重置根管理员的口令」。`conftest.py` 的
`root_admin` fixture 把 fixture 里唯一的 admin 提成了根管理员，用 `auth("admin")` 发请求
等于「本人重置自己」→ 200，用例形同虚设。§8.2 没有提到这个前提。

**处理**：在 `tests/test_account_governance.py` 内加一个模块级 helper `_second_admin_headers`
（形状与 `tests/test_root_admin.py::_second_admin` 一致，不新建 conftest fixture——
它只服务这一个文件的两条用例）。

### 释放条件的执行证据

1. **用例 35′ 先红后绿**：把 `reset_password` 临时改回 v1 的「复用 `_reject_root_mutation`」
   写法后实测，空 body 重置根管理员返回 **200**（不是 409），即一条完整的破窗账号接管路径；
   恢复正确守卫后转绿。
2. **用例 14′ 通过**：见 I-1，并额外覆盖了 `min_length == max_length` 这个边界。
3. **闸门落地后整跑全量 `pytest -q`**：见提交说明中的实测数字（基线 674 条 / 42 文件）。
4. **手工验收 §8.3 第 9 条**：`policy` 已穿进 `RegisterForm.tsx` 的 `isPasswordAcceptable`
   与 `<PasswordStrength>` 两个调用点，另同样穿进了 `PasswordCard`、`MemberFormModal`
   的建号 / 重置两个表单与 `/force-password` 页——五处调用点全部显式传参，无一处依赖默认值。
