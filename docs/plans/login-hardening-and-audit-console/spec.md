# 登录纵深与治理审计出口（login-hardening-and-audit-console）

> 版本：**v2（评审后修订）**——v1 为设计节点产出，本版由评审节点逐节核对真实源码后修订，
> 全部 P0 / P1 已在正文中改掉，修订处标注 `【评审 Pn-m】`。
> 轮次：自助注册主题的**第三轮**，前置为 `docs/plans/self-service-registration/spec.md`
> （已上线，commit `04506e5`）与 `docs/plans/account-security-and-governance/spec.md`
> （已上线，commit `e679ab3`）。
> 采集基线（**实测**，`cd backend && python -m pytest -q --collect-only`）：**742 用例 / 44 文件**
> （评审节点复跑确认：仍为 742 / 44，收集零错误）。
> 本文档中所有涉及既有代码的断言均带 `文件:行号`，写作时逐条对照过真实源码。

---

## 评审记录（Review Notes）

评审方式：不采信 v1 的任何转述，对每一条 `文件:行号` 断言重新打开源码核对；后端读了
`services/{app_settings,audit,scope,validation,pagination,schema_sync,ratelimit,passwords,
notifications,lifecycle,auth_helpers}.py`、`routes/{auth,users,settings}.py`、
`models/{user,activity,app_setting,notification}.py`、`config.py`，测试侧读了
`conftest.py`、`test_{auth,schema_sync,app_settings,registration,settings,account_governance,
lifecycle,root_admin}.py` 并复跑了一次 `--collect-only`，前端逐个打开了 v1 引用的 12 处。

**结论：v1 的技术判断绝大多数成立**（判定顺序、派生用量、不为每次失败写 Activity、
`registration-meta` 一个字都不加、复用 `ProgressBar` 而非新建原语，这几条都经核对为对的）。
问题集中在**两类**：一是「静态扫描说只有 1 处」——影响分析漏了两条会翻的断言，这正是
上一轮 §12 I-2 栽过的同一个坑；二是前端的四条「既有件」断言里有三条与仓库现状不符。

| # | 严重度 | 位置 | 问题 | 处置 |
|---|---|---|---|---|
| P0-1 | **P0** | §7.1 / §2.4 | **影响分析漏了第二条会翻的断言。** §1.1 A-4 的 `check_invite_code` 从 `get_registration_settings()` 里读 `invite_expires_at` / `invite_max_uses`，即该函数返回值必须扩键；而 `tests/test_app_settings.py:26-28` 是对**该函数返回值**的全等 dict 断言（`== {"enabled":…, "invite_code":…, "default_role":…}`）。§7.1 明写「会翻的，只有一条」，§2.4 还写了「已核对」——那次核对只看了 HTTP 端点的逐键断言，没看服务层。DoD 的「零失败」直接建立在这条错误结论上。 | 已在 §7.1 补入该行并给出改法；§2.4 的措辞改为区分「端点逐键断言不翻」与「服务层全等断言必翻」；§1.1 A-4 增补 `get_registration_settings()` 的返回契约与「禁止 `{**settings}` 直出 JSON」硬约束 |
| P0-2 | **P0** | §1.2 B-2 | **自相矛盾 + 一条既有用例会翻。** 同一节一边把 `TestConfig.LOGIN_LOCK_THRESHOLD` 设为 2、一边把 `threshold` 钳到 `[3,100]` → 钳位后测试里恒为 **3**，那个 2 是死值，B-2 整段「必须严格小于 `LOGIN_MAX_ATTEMPTS(=3)`」的推导随之作废。若反过来让 2 真生效，`tests/test_auth.py:52-60`（`test_login_success_clears_counter`：对 `pm` 连错 **2** 次后用**正确**口令断言 **200**）会因账号已锁而变成 403——而 §7.1 明写「`test_auth.py` 全部……逐字节不变」。 | `TestConfig.LOGIN_LOCK_THRESHOLD = 3`（= 钳位下界 = `LOGIN_MAX_ATTEMPTS`）；B-2 的推导整段重写；§7.1 把 `test_auth.py:52-60` 从「安全」改为「安全**且给出推导**（2 < 3）」 |
| P0-3 | **P0** | §2.3 | **`QueryParamError(field="since", expected="…")` 是一个 TypeError。** `services/scope.py:29` 的签名是 `__init__(self, field, got, expected)`——三个**位置**必填参数，缺 `got` 即实例化失败，被全局兜底渲染成 500。而这条分支正是「非法 `since`」的唯一出口。更根本的是：查询串侧**没有任何 datetime 原语**（`scope.py` 只有 `want_query_int/str/bool`），而 §3.2 的变更计划里**根本没有 `services/scope.py` 这一行**。 | §3.2 补入 `backend/services/scope.py`；新增 `want_query_datetime()`（容忍尾部 `Z`，非法抛三参位置调用的 `QueryParamError`）；§2.3 的错误体照 `query_error_response`（`scope.py:158`）的既有形状写死 |
| P1-1 | P1 | §1.1 A-3 / A-5 | **A-3 声称关掉的坑其实没关，用例 11 会红。** `invite_issued_at` 只在「码的值真的变了」时才写；于是在一个**从未改过码**的库上（全新部署 + 只设了 `max_uses`，这是最常见的路径），该键不存在 → 走第 2 级回落读码行 `updated_at`。此时另一个根管理员把码**原样再保存一次**：`_upsert`（`app_settings.py:147-154`）无条件写 `row.updated_by_id` → 行变脏 → `app_setting.py` 的 `onupdate=utcnow` 触发 → `updated_at` 前移 → **额度静默归零**。 | A-5 改为两步：① `_upsert` 之前判等，**值没变就整条跳过**（根本不弄脏行）；② 写 `expires_at` / `max_uses` 时若 `invite_issued_at` 行缺失则顺带补写锚点。新增用例 11′ |
| P1-2 | P1 | §7.2 C 组 | **用例 35 / 39 / 31 / 32 在 TestConfig 下走不到被测分支。** 限流键是 `ip:username`（`routes/auth.py:44`）且 `LOGIN_MAX_ATTEMPTS=3`，同一用户名第 4 次请求起恒 429。「锁定期内再打 5 次」「根管理员连错 20 次」的第 4 次起拿不到 `note_failed_login`，断言恒真且零信息——R-2 / R-3 的执行者是假的；「锁定后用正确口令 → 403」同样被 429 截胡。 | 四条用例明确要求在尝试之间调 `ratelimit.reset()`（`services/ratelimit.py:88`，conftest 已有同名 autouse fixture 作先例），或改为直接驱动 `login_guard` 的单元测试 |
| P1-3 | P1 | §1.2 B-3 / R-3 | **锁定通知是一个匿名可触发、无上限的管理员通知放大器；R-3 的「只 UPDATE 不 INSERT」在锁定迁移那一刻不成立。** 锁 15 分钟自然到期后可再锁，换 IP 的攻击者对每个已知用户名约 4 次/小时地重复该循环，每次 1 条 `activities` + N 条 `notifications`（N = 有效管理员数）。20 账号 × 3 管理员 ≈ 5.7k 行/天，而 CLAUDE.md 明写这两张表**永不按数量清理**。 | B-3 增补通知冷却（同一账号 24h 内已记过 `account_locked` 则只写审计、不再扇出通知）+ 新配置 `LOGIN_LOCK_NOTIFY_COOLDOWN_MINUTES`；R-3 按真实算术重写，不再声称「不 INSERT」；新增用例 42′ |
| P1-4 | P1 | §1.2 B-2 / R-12 | **`_clamped_config_int` 的 warning 前缀 `"passwords: …"` 硬编在格式串里**（`passwords.py:74-75`）。按 R-12 的「纯搬迁、逐字不变」抽走后，`LOGIN_LOCK_THRESHOLD` 的脏值会打出 `passwords: unparsable LOGIN_LOCK_THRESHOLD=…`，运维照这条日志去翻口令模块。而用例 28 断言的正是这条 warning。 | 抽取时加 `source: str` 形参；`passwords.py` 两个调用点显式传 `"passwords"`（输出逐字节不变），`login_guard` 传 `"login_guard"`；用例 28 断言前缀 |
| P1-5 | P1 | §5.2 / §3.4 | **`frontend/lib/format.ts` 不存在。** §5.2 说「把 `relTime()` 提到 `lib/format.ts`，不要复制第二份」——但仓库里**已经有两份**：`components/admin/MemberActivityModal.tsx:29` 与 `components/notifications/NotificationBell.tsx:15`（后者 v1 完全没提）。所以这是「新建模块 + 收口两处既有副本」，不是「搬一处」。 | §3.3 新增 `frontend/lib/format.ts` 一行（新增数由 4 补齐为标称的 5）；§3.4 补 `NotificationBell.tsx`；§5.2 措辞改正 |
| P1-6 | P1 | §3.4 | **`ADMIN_VIEW_PREFIXES` 是模块私有的**（`lib/swr-keys.ts:24`，无 `export`，对外只暴露 `invalidateAdminViews`）。写成「`+= "/settings/audit"`」会让实施者去找一个不存在的导出。 | 改为「就地扩 `swr-keys.ts:24` 的数组字面量」 |
| P1-7 | P1 | §3.4 | **`GOVERNANCE_AUDIT_KEY` 与 `api.ts` 的既有不变量冲突。** `api.ts:19-24` 把规矩写死了：一个 `*_KEY` ⇒ 一种响应形状，**分页 / 带筛选的视图不得复用它们**（`USERS_KEY = "/users?limit=200"` 正是反例）。审计页是分页 + 4 筛选的。 | 明确 `GOVERNANCE_AUDIT_KEY` 只作**路径前缀常量**（供失效前缀与 hook 拼串），页面 key 照 `team/page.tsx:65-66` 内联拼 |
| P1-8 | P1 | §5.3 | **「页面级无权限态」在本仓库没有先例。** `app/(app)/layout.tsx:15-34` 只处理未登录与强制改密；既有惯例是**整块隐藏**（`settings/page.tsx:57` 的 `{user?.is_root && <RegistrationCard />}`）与**禁用 + title**（`team/page.tsx:300-320`）。v1 的决定（渲染 EmptyState、不 redirect）本身是对的，但它是**本轮新立的一条 UI 惯例**，不写明后续一定会长出第二种做法。 | §5.3 补一句「本例为该模式的第一例，后续同类页面照此办理」，并说明它与「整块隐藏」的分工判据 |
| P2-1 | P2 | §1.2 B-3 ① | 引用错位：破窗账号配置在 `config.py:105-108`（`ROOT_ADMIN_BOOTSTRAP` 在 `:111`），不是 `:103-104`。 | 已改 |
| P2-2 | P2 | §7.1 | `tests/test_schema_sync.py:60` 是**子集**断言（`{…} <= _columns(...)`），加列不会让它翻，「同时 :60 也要补」是无害但不实的指令。 | 已改为「可选补充，非必须」 |
| P2-3 | P2 | §1.2 B-3 | `conflict_locked()` 命名误导：本仓库 `conflict_*`（`lifecycle.conflict_root_admin` / `conflict_last_admin`）一律是 **409** 构造器，本函数返 403。 | 更名 `locked_response()` |
| P2-4 | P2 | §3.3 | `ProgressBar` 的 `label` 走的是 `aria-label`（`ProgressBar.tsx:21`），**不渲染可见文字**；`className` 挂在**外层轨道**上（`:26`），所以 `[&>div]:bg-*` 才命中填充条、裸 `bg-*` 会改错元素。 | 已在该段注明 |
| P2-5 | P2 | §2.4 | `_registration_payload()` 的 `updated_at` / `updated_by` 取 `REGISTRATION_KEYS` 里最近改动的一行（`routes/settings.py:44-46`）。加 3 键后系统自动写的 `invite_issued_at` 行也进入这个 max，语义从「谁最后改了注册配置」漂成「哪一行最后被写过」。 | 已认账并要求 `invite_issued_at` 的 `updated_by_id` 传真实施动者 |
| P2-6 | P2 | §4.3 | 列宽边界没写：`Activity.action` 是 `String(32)`、`from_status/to_status` 是 `String(24)`（`models/activity.py:25,30-31`）。本轮取值都在界内，但表里该有这一行。 | 已补 |
| P2-7 | P2 | §1.2 B-7 | `last_login_at` 进 `to_dict()` ⇒ **全体成员**都能读到同事的最后登录时间（`GET /api/users` 是 `jwt_required()`，`routes/users.py:58-59`）。用 `must_change_password` 作先例成立，但「最后登录」比「该改密码了」更接近考勤数据。 | 保留决定，把这层顾虑显式写进文档 |
| P2-8 | P2 | §7.2 | C 组标题写「21 条」，枚举 27～48 实为 **22** 条（总数 68 不受影响）。 | 已改 |
| P2-9 | P2 | §3.4 | `MemberFilters` 加 `locked` 时，`EMPTY_FILTERS`（`MemberFilterBar.tsx:25`）也必须同步，否则清空筛选清不掉它；可直接照抄既有「状态」筛选（`:82-91` + `STATUS_OPTIONS :32-35`）的三态写法。 | 已补 |

**核对为「v1 说得对」的几条**（记下来免得下一轮重复怀疑）：
`test_registration.py:324` 确是全等断言且 §2.6 的决定绕开了它；`test_settings.py:125` 从常量派生不会翻；
`ADDITIVE_COLUMNS` 现 7 条、`users` 占 4 条且 `applied` 顺序确由列表顺序决定（`schema_sync.py:66-71`），
「必须追加在末尾」成立；`USER_ACTIVITY_LABELS` / `ICONS` 确是 `Record<UserActivityAction, string>`
（`constants.ts:337` / `:347`），漏改即编译错误；`ProgressBar` 的 props、`role`/`aria-*` 与
「`null` = 不确定」全部属实；`team/page.tsx:185` 的「一行最多两个徽章」与 `:33-35` 的
「禁用 + title」注释都在；`MemberFilterBar` 确有一个可照抄的三态筛选；限流状态挂在
`app.extensions` 上且 conftest 有 autouse 复位，**不跨用例泄漏**。

---

## 0. 本轮的定位：把「谁能进来」补完为「谁进来过、进来多少次、还能进来多久」

### 0.1 前两轮把「入口」修好了，但入口没有仪表盘

第一轮解决的是**能不能进来**：邀请码自助注册、配置文件锚定的根管理员、团队治理面。
第二轮解决的是**进来之后口令归谁负责**：一份口令策略管住四条写入路径、一次性口令与
强制改密闸门、账号治理审计。两轮下来，`users` 表已经有 `is_active` / `is_root` /
`source` / `must_change_password` 四列治理语义，`activities` 表已经能回答
「这个账号的角色是谁改的」。

但把整条链路拉直看，还有三处是敞着的，而且**每一处都是「功能完善可靠稳健」这句需求
直接指向的地方**：

1. **邀请码是一份没有额度、没有期限、没有用量的凭据。**
   `services/app_settings.py:208` 的 `verify_invite_code` 只做一件事：定长比较。
   码一旦被贴进任何一个群，它就永久有效、可被无限次使用，而根管理员**在产品内看不到
   它被用过几次**。今天唯一的止损动作是 `POST /api/settings/registration/rotate-code`
   （`routes/settings.py:103`）——一个「我怀疑漏了，那就全废掉重来」的核按钮。
   一份共享明文口令的真实威胁模型就是「被转发出去」，而我们对它零可观测、零限额。

2. **登录是全站唯一一个不留任何痕迹的写操作。**
   `routes/auth.py:31-61` 的 `login` 全程不写库：成功不记时间，失败不计次数。
   `services/ratelimit.py` 是**纯内存**（模块 docstring 第 4 行自陈「重启即清空、
   多副本不共享」），键为 `ip:username`（`routes/auth.py:44`）——换一个 IP 就是一个全新的桶。
   结果是两个具体缺陷：
   - 管理员无法回答「这个半年前自助注册的账号还有人在用吗」，而「停用休眠账号」
     恰恰是团队治理最高频的动作，今天他只能靠猜；
   - 针对**单个用户名**的慢速撞库没有任何持久化的刹车。停用（`is_active`）是有的，
     但那是人工的、事后的。

3. **站点设置的审计是只写不可读的。**
   `services/audit.py:66` 的 `log_settings_event` 把 `entity_type="app_setting"` 的行
   写进 `activities`，`routes/settings.py:97` 与 `:114` 各调一次。但**全仓库没有任何
   端点能把它们读回来**：`audit.user_timeline`（`services/audit.py:91`）写死
   `entity_type=ENTITY_USER`，`routes/stats.py` 已被上一轮收紧到 `TICKET_ENTITY_TYPES`
   （这是对的，见 `models/activity.py:11` 的注释）。也就是说
   **「谁改了邀请码」这条记录，今天写进去就再也拿不出来**——审计写了却读不到，
   等同于没有审计，还多付了写入成本。这是一个明确的实现缺陷，不是功能缺失。

### 0.2 本轮的一句话目标

**让邀请码变成一份有额度、有期限、有用量的真凭据；让登录留下最小但足够的痕迹并长出
一道持久化的刹车；让已经写进库里的治理审计第一次有一个出口。**

三件事共享同一个价值主张：**治理动作要有依据**。今天管理员能停用一个人，但说不出为什么该停；
能换邀请码，但说不出换之前它被用了几次；能看到某个人的时间线，但看不到全站这一周发生过什么。

### 0.3 明确不做的（详见 §10）

不做邮件、不做 TOTP、不做注册审批队列、不做分布式限流、不做口令历史。
上一轮的 §10 把这些列为非目标的理由本轮**全部仍然成立**，不重复论证。

---

## 1. 技术设计

### 1.1 支柱 A：邀请码的生命周期与用量（services/app_settings.py）

#### A-1 三个新设置键

沿用既有键值表（`models/app_setting.py`），**不加列**——这正是上一轮选择键值表的理由
（`models/app_setting.py:3-6`：「未来一定还会有第四第五个」）。

| 存储键 | 取值 | 语义 | 缺省（无行时） |
|---|---|---|---|
| `registration.invite_expires_at` | ISO8601 naive UTC 串，或空串 | 邀请码失效时刻 | 空 = **永不过期** |
| `registration.invite_max_uses` | 十进制整数串 | 本码最多可注册出多少个账号 | `"0"` = **不限** |
| `registration.invite_issued_at` | ISO8601 naive UTC 串 | 当前这个码是**什么时候开始生效**的 | 见 A-3 的回落链 |

三个键必须一并加进 `REGISTRATION_KEYS`（`services/app_settings.py:36`），
否则 `_stored_values()`（`:65`）取不到它们。

#### A-2 用量是**派生**的，不是计数器

```python
def invite_uses() -> int:
    """当前这个邀请码已经注册出多少个仍在库里的账号。"""
    issued = invite_issued_at()
    q = User.query.filter(User.source == "signup")
    if issued is not None:
        q = q.filter(User.created_at >= issued)
    return q.count()
```

**为什么不存一个 `invite_uses` 计数器**——三条理由，每条对应一个真实失败模式：

1. **计数器要读-改-写。** SQLite 单写者下两个并发注册会互相覆盖，最终计数**小于**
   真实值——一个为了限额而存在的字段，在被攻击的那一刻反而失真。派生值不存在这个问题。
2. **计数器会与真实用户数漂移。** `tools/purge_demo_data.py` 会删账号，
   计数器不会跟着降。派生值恒等于「拿这个码建出来、且现在还在库里」的账号数——
   这正是根管理员想问的那个数。
3. **rotate 不需要额外的归零写。** 换码只写 `invite_issued_at`，用量自动归零。
   少一个「忘了归零」的失败模式。

**代价**（必须在实现里认账）：用量口径是「现存账号数」，不是「历史使用次数」。
一个注册后又被 purge 掉的账号会让额度「退回来」。这在本产品里是可接受的——
purge 是一个需要人手动 `--apply` 的运维动作，不是用户可触发的路径。

**签名必须吃一个已取回的 settings，不得自己再查一遍**：

```python
def invite_uses(settings: dict) -> int: ...
def invite_issued_at(settings: dict): ...
```

`services/app_settings.py:9-11` 的模块 docstring 立了一条硬约定——
「不缓存，每次请求打**一次**唯一索引查询」。若 `check_invite_code` 先调
`get_registration_settings()`（第 1 次 `_stored_values()`），再让 `invite_uses()`
内部去调 `invite_issued_at()` → `_stored_values()`（第 2 次），
那条「一次」就在**匿名可触发的注册热路径**上悄悄变成了两次。
把 settings 当参数往下传，是让那条 docstring 继续为真的唯一方式。

#### A-3 `invite_issued_at()` 的三级回落链（**不得有静默放行分支**）

```python
def invite_issued_at(settings_rows: dict):
    """当前邀请码的生效时刻；None 表示「自古以来」（= 统计全部 signup 账号）。

    `settings_rows` 由调用方从 `_stored_values()` 取一次后传入（见 A-2 末段）。
    """
    raw = settings_rows.get(KEY_INVITE_ISSUED_AT)
    parsed = _parse_iso(raw)                       # 脏值 → None + warning
    if parsed is not None:
        return parsed
    row = get_row(KEY_REGISTRATION_INVITE_CODE)    # 存量库：码行的 updated_at 就是锚点
    if row is not None:
        return row.updated_at
    return None                                    # 全新库走配置兜底：码从未被改过
```

三级都不返回「不限量」这类放行值。第 3 级返回 `None` 时，`invite_uses()` 统计**全部**
`source="signup"` 账号——那是最严格的口径，不是最宽松的。

**为什么额外存一个 `invite_issued_at`，而不直接用码行的 `updated_at`：**
`_upsert`（`:147`）同时改 `row.value` 与 `row.updated_by_id`。当**另一个**根管理员把
邀请码原样再保存一次时，`value` 没变但 `updated_by_id` 变了 → 行变脏 → `onupdate=utcnow`
触发 → `updated_at` 前移 → **额度在码没变的情况下被悄悄重置**。
显式键 + 「值真的变了才写」的判据把这个坑一次性关掉。它只在存量库上作为第 2 级回落使用，
那里不存在这个问题（存量库还没有额度概念）。

#### A-4 `check_invite_code` 取代 `verify_invite_code` 成为判据

**【评审 P0-1】前置：`get_registration_settings()` 的返回契约由 3 键扩为 5 键。**
本函数从它读期限与额度，因此那两个键必须**在同一个 dict 里、且已经解析成 Python 类型**
（`_stored_values()` 本来就一次性取回 `REGISTRATION_KEYS` 全部行，扩键不增加往返）：

| 键 | 类型 | 说明 |
|---|---|---|
| `enabled` / `invite_code` / `default_role` | 逐字不变 | 既有三键 |
| `invite_expires_at` | `datetime \| None` | 已过 `_coerce_expires_at`；`None` = 永不过期 |
| `invite_max_uses` | `int` | 已过 `_coerce_max_uses`；`0` = 不限 |

两条随之而来的硬约束：

1. **`tests/test_app_settings.py:26-28` 会翻**——它是对本函数返回值的**全等 dict 断言**。
   这是本轮**第二条**（也是最后一条）必改的既有断言，见 §7.1。v1 漏了它。
2. **禁止 `{**get_registration_settings()}` 直出 JSON。** `_registration_payload()`
   （`routes/settings.py:47-55`）是逐键显式构造的，必须保持这个写法并对 `datetime` 逐个
   走 `_iso()`。一旦有人图省事展开这个 dict，Flask 的 `jsonify` 会把 `datetime` 序列化成
   RFC 822 的 `"Wed, 01 Aug 2026 00:00:00 GMT"`，而 §2.4 的契约和 R-14 的回环都要求 ISO 串——
   那会是一次**没有任何测试会红**的静默契约破坏（既有用例只逐键断言字符串相等）。

```python
class InviteCheck(NamedTuple):
    ok: bool
    reason: str        # "ok" | "mismatch" | "expired" | "exhausted"

def check_invite_code(candidate: str) -> InviteCheck:
    settings = get_registration_settings()
    if not hmac.compare_digest((candidate or "").strip().encode("utf-8"),
                               settings["invite_code"].encode("utf-8")):
        return InviteCheck(False, "mismatch")
    expires = settings["invite_expires_at"]                 # datetime | None
    if expires is not None and utcnow() >= expires:
        return InviteCheck(False, "expired")
    max_uses = settings["invite_max_uses"]                  # int, 0 = 不限
    if max_uses > 0 and invite_uses() >= max_uses:
        return InviteCheck(False, "exhausted")
    return InviteCheck(True, "ok")


def verify_invite_code(candidate: str) -> bool:
    """**保留的稳定别名**（CLAUDE.md §五：对外暴露的接口更名等同破坏性变更）。"""
    return check_invite_code(candidate).ok
```

`.encode("utf-8")` 的两行**逐字保留**——上一轮的 §12 F-1 记录过：
`hmac.compare_digest` 传 `str` 时只接受 ASCII，中文邀请码会让这个公开端点 500
（`services/app_settings.py:214-217` 的注释是这条约束的唯一记载，不得在重构中丢失）。

**判定顺序（是契约的一部分）**：mismatch → expired → exhausted。
理由：`expired` / `exhausted` 这两个 reason 只在**候选码与真码一致**之后才可能返回。
持码人本来就知道码，告诉他「过期了」不泄露任何东西，反而是他唯一能据以行动的信息；
不持码人恒得到 `mismatch`，可区分性为零。把顺序倒过来（先查过期）会让**任何人**
都能探测出「这个站点的邀请码已经过期了」，那才是泄露。

#### A-5 写入侧的业务约束（`set_registration_settings` 扩展）

| changes 键 | 类型 | 约束 | 违反时 |
|---|---|---|---|
| `expires_at` | `str` 或 `None` | 可被 `datetime.fromisoformat(v.rstrip("Z"))` 解析；且**必须严格晚于 `utcnow()`**；`None` / 空串 = 清除 | `ValidationError(field="expires_at")` → 400 |
| `max_uses` | `int` | `0 <= v <= 10000` | `ValidationError(field="max_uses")` → 400 |

**为什么「过去的时刻」是 400 而不是「立刻失效」**：把失效时间设到过去，98% 的情况是
时区搞错了（用户按本地时间填，我们按 UTC 存），2% 的情况是他想立刻废掉这个码——
而后者已经有两个更直白的入口（关开关 / rotate）。让手滑静默生效，代价是
「明明设成了明天，怎么现在就用不了」这种查半天的困惑。

`max_uses` 的上界 10000 不是安全约束，是防手滑：输一个天文数字对后端无害，
但会让前端的用量进度条渲染成一条永远为零的线。

`invite_code` 分支追加一步（**必须在 `_upsert` 之前判断**）：

```python
if "invite_code" in changes:
    value = _validate_invite_code(str(changes["invite_code"]).strip())
    if value != get_registration_settings()["invite_code"]:
        _upsert(KEY_INVITE_ISSUED_AT, utcnow().isoformat(), actor_id)   # 额度归零
        _upsert(KEY_REGISTRATION_INVITE_CODE, value, actor_id)
        written[KEY_REGISTRATION_INVITE_CODE] = value
    # 【评审 P1-1】值没变 → **整条跳过**，连 _upsert 都不调。见下方论证。
```

##### 【评审 P1-1】v1 在这里留了一个会让 A-3 的全部论证落空的洞

v1 的写法是「值变了才写 `issued_at`，但**无论如何都 `_upsert` 一次码行**」。
`_upsert`（`services/app_settings.py:147-154`）在行已存在时**无条件**执行
`row.value = value` **与** `row.updated_by_id = actor_id`。第二条赋值即便值相同也会把行
弄脏 → `models/app_setting.py` 的 `updated_at = db.Column(..., onupdate=utcnow)` 触发
→ `updated_at` 前移。

在**从未改过邀请码**的库上（全新部署后只设了 `max_uses`，这是最常见的路径），
`registration.invite_issued_at` 这一行**根本不存在** → `invite_issued_at()` 走第 2 级回落读
码行的 `updated_at` → **额度在码没变的情况下被悄悄重置**。这正是 A-3 花了一整段论证要
关掉的那个坑，v1 只在「显式键已存在」的前提下关掉了它，而那个前提恰好不成立。
用例 11 会红。

因此 A-5 必须是**两步**，缺一不可：

1. **值判等即整条短路**（上面的代码）：值没变就不写 `value`、不写 `updated_by_id`，
   行根本不弄脏，`updated_at` 不动。这一步把第 2 级回落也一并保护了，
   是比「加一个显式键」更根本的修法——显式键是记账，不弄脏行才是止血。
2. **额度语义诞生的那一刻补锚点**：`expires_at` / `max_uses` 任一被写入时，
   若 `KEY_INVITE_ISSUED_AT` 行缺失则顺带补写一次 `utcnow().isoformat()`。

```python
def _ensure_invite_anchor(actor_id) -> None:
    """额度/期限第一次被设置时补写生效锚点（**幂等**：已有行则不动）。

    没有这一步，「只设了额度、从没改过码」的库会一直依赖第 2 级回落，
    而回落读的那个 updated_at 不归本模块管（评审 P1-1）。
    """
    if get_row(KEY_INVITE_ISSUED_AT) is None:
        _upsert(KEY_INVITE_ISSUED_AT, utcnow().isoformat(), actor_id)
```

**`updated_by_id` 传真实施动者，不传 None**（评审 P2-5）：`_registration_payload()` 的
`updated_at` / `updated_by` 取 `REGISTRATION_KEYS` 里最近改动的一行
（`routes/settings.py:44-46`），加键后 `invite_issued_at` 行也进入这个 `max`。
传 None 会让设置页显示「最后修改人：未知」。代价要认账：该字段的语义从
「谁最后改了注册配置」轻微漂成「哪一行最后被写过」——因为两行恒由同一次请求、
同一个 actor 写出，实际显示结果不变，故接受。

`rotate_invite_code`（`routes/settings.py:103`）走同一条路径，因此 rotate 自动归零额度，
而 `expires_at` / `max_uses` **原样保留**——rotate 的语义是「换一把钥匙」，
不是「重置整套门禁策略」。这一点必须写进那个路由的 docstring。
（`generate_invite_code()` 在 31 字符表上取 10 位，撞上当前码的概率是 31⁻¹⁰，
故 rotate 恒走「值变了」分支，不必为此写防御分支。）

#### A-6 脏值一律回落 + warning，绝不抛

沿用模块 docstring 第 2 条硬约定（`services/app_settings.py:12-13`）。
新增两个 coercer：`_coerce_expires_at`（不可解析 → `None` + warning）、
`_coerce_max_uses`（不可解析 / 负数 → `0` + warning）。
**回落方向必须是「不限制」**：一个拼错的设置值不该把全站注册闸死——那是把配置故障
放大成业务故障，与开关解析失败回落配置默认是同一条价值观。

### 1.2 支柱 B：登录闸门（新模块 services/login_guard.py）

#### B-1 三个新列

| 列 | DDL | 语义 |
|---|---|---|
| `users.last_login_at` | `DATETIME` | 最近一次**成功**登录；null = 从未登录 |
| `users.failed_login_count` | `INTEGER NOT NULL DEFAULT 0` | **连续**失败次数；任何一次成功登录清零 |
| `users.locked_until` | `DATETIME` | 锁定到期时刻；null 或已过去 = 未锁定 |

三条必须同时登记进 `services/schema_sync.py::ADDITIVE_COLUMNS`（CLAUDE.md 的两步编辑铁律）。
默认值都是常量（SQLite `ADD COLUMN` 的硬性要求），存量行零回填即语义正确：
存量用户「从未记录过登录、没有失败、没有锁定」——全部为真。

**判据是「连续失败」而不是「窗口内失败」**，因此不需要第四列 `last_failed_login_at`。
一个正常用户每次成功登录都清零，只有「连续 N 次全错、中间一次都没成功」才会触发锁定。
纯累加计数器（永不衰减）会让一个用了半年、零星敲错 8 次的账号被莫名锁住——那是把
一个安全机制变成一个 bug。

#### B-2 两个新配置旋钮（`backend/config.py`）

```python
# —— 登录锁定（login-hardening-and-audit-console §1.2）——
# 与 LOGIN_MAX_ATTEMPTS（内存 IP 限流）是**两道正交的闸**：前者按 (ip, username) 计、
# 重启即失忆；本组按**账号**计、落库、跨重启有效。慢速分布式撞库只有后者挡得住。
LOGIN_LOCK_THRESHOLD = _env_int("LOGIN_LOCK_THRESHOLD", 8)
LOGIN_LOCK_MINUTES = _env_int("LOGIN_LOCK_MINUTES", 15)
```

通知冷却（评审 P1-3 引入，论证见 B-3）：

```python
LOGIN_LOCK_NOTIFY_COOLDOWN_MINUTES = _env_int("LOGIN_LOCK_NOTIFY_COOLDOWN_MINUTES", 1440)
```

`TestConfig` 追加：

```python
# 【评审 P0-2】= 钳位下界 = LOGIN_MAX_ATTEMPTS。三者相等不是巧合，见下方推导。
LOGIN_LOCK_THRESHOLD = 3
LOGIN_LOCK_MINUTES = 15
LOGIN_LOCK_NOTIFY_COOLDOWN_MINUTES = 1440
```

##### 【评审 P0-2】v1 的 `LOGIN_LOCK_THRESHOLD = 2` 是死值，而且真让它生效会打翻既有用例

v1 在同一节里一边把 `TestConfig` 设成 2、一边把 `threshold` 钳到 `[3, 100]`。
钳位之后 `lock_policy()["threshold"]` 在测试里恒为 **3**，那个 2 从来不会生效——
v1 的整段推导（「**必须严格小于** `LOGIN_MAX_ATTEMPTS(=3)`」）建立在一个不会发生的取值上。

而如果反过来把钳位下界降到 2 让它真生效，会当场打翻一条既有用例：
`tests/test_auth.py:52-60`（`test_login_success_clears_counter`）对 `pm` **连错 2 次**、
随即用**正确**口令断言 **200**。阈值为 2 时该账号在第 2 次失败就被锁，第三次请求走到
B-4 的第 4 步 → **403**，用例红。而 §7.1（v1）恰恰声称「`tests/test_auth.py` 全部……
逐字节不变」。这是与上一轮 §12 I-2 同源的失败：静态扫描只看了「响应体形状」，
没看「用例做了几次失败」。

**取 3 之后的完整推导**（三个数字必须一起看）：

| 请求序号 | IP 桶（键 `ip:username`，`is_blocked` 判据 `len >= 3`） | 账号计数 | 实际响应 |
|---|---|---|---|
| 1（错） | len=0 → 放行 | 1 | 401 |
| 2（错） | len=1 → 放行 | 2 | 401 |
| 3（错） | len=2 → 放行 | 3 → **触发锁定**，计数归零 | **仍 401**（锁定检查在口令校验之后） |
| 4（任意） | len=3 → **429** | 不变（够不到） | 429 |

推论有三条，全部要写进用例：

- `test_auth.py:40-49`（连错 3 次各断言 401，第 4 次断言 429）**逐字节仍绿**——
  第 3 次虽然触发了锁定，但响应体仍是 401，这正是 B-4 顺序契约的直接收益。
  副作用是该用例结束后 `admin` 处于锁定态并写了一条审计，用例本身不关心，无影响。
- `test_auth.py:52-60`（连错 **2** 次后正确口令断言 200）**安全**，因为 2 < 3。
- **锁定态本身在 HTTP 层不可观测，除非先复位 IP 桶**——用例 31/32/35/39 必须显式调
  `ratelimit.reset()`，见评审 P1-2 与 §7.2 C 组。

阈值钳位（沿用 `services/passwords.py::_clamped_config_int` 的取向，但**不复用那个函数**：
它在 `passwords` 模块内、绑定口令语义。把 `_clamped_config_int` 提升为
`services/config_knobs.py`——这是第二个调用点，正是抽取的时机）：

- `threshold` 钳到 `[3, 100]`；下界 3 是因为「敲错两次就锁」在真实办公场景里是骚扰。
- `minutes` 钳到 `[1, 1440]`；上界 24 小时——超过一天的锁定应该由人按「停用」，
  那是一个有审计、可解释的动作，不该由一个配置项静默产生。
- `notify_cooldown` 钳到 `[0, 10080]`；`0` = 每次锁定都通知（有意保留这个取值，
  给「小团队、宁可吵也要知情」的部署一条出路）。

**【评审 P1-4】抽取时必须加一个 `source` 形参，否则日志会指错模块。**
`services/passwords.py:74-75` 把模块名硬编进了格式串：

```python
current_app.logger.warning("passwords: unparsable %s=%r, falling back to %s", key, raw, default)
```

按 R-12 的「纯搬迁、实现逐字不变」搬走之后，一个写错的 `LOGIN_LOCK_THRESHOLD` 会打出
`passwords: unparsable LOGIN_LOCK_THRESHOLD=…`，运维照这条日志去翻口令模块——
一条**主动误导**的日志比没有日志更贵。故 `config_knobs.clamped_int` 的签名为：

```python
def clamped_int(key: str, default: int, low: int, high: int, *, source: str) -> int:
```

`passwords.py` 的两个调用点显式传 `source="passwords"`，其输出**逐字节不变**
（R-12 的回归判据因此仍然成立）；`login_guard.py` 传 `source="login_guard"`。
用例 28 断言的是 `login_guard` 前缀。

#### B-3 `services/login_guard.py` 的完整接口

```python
def lock_policy() -> dict:
    """`{"threshold": int, "minutes": int, "notify_cooldown": int}`，已钳位。

    唯一读这三个配置的地方（`services/passwords.py::policy()` 的同款收口）。
    """

def is_locked(user) -> bool:
    """该账号此刻是否处于锁定期。None / 无 locked_until / 已过期 → False。"""

def retry_after_seconds(user) -> int:
    """距解锁还有多少秒（向上取整，最小 1）；未锁定返回 0。"""

def note_failed_login(user) -> bool:
    """记一次失败登录（**不 commit**）。返回 True 表示本次刚好触发了锁定。"""

def note_successful_login(user) -> None:
    """记一次成功登录：写 last_login_at、清零计数与锁（**不 commit**）。"""

def unlock(user, actor) -> bool:
    """解除锁定（**不 commit**）。返回 False 表示本来就没锁（幂等，不写审计）。"""

def locked_response(user):
    """锁定态的 **403** 契约体。稳定错误串，勿更名。

    【评审 P2-3】v1 叫 `conflict_locked`。本仓库的 `conflict_*` 前缀
    （`lifecycle.conflict_root_admin` / `conflict_last_admin`）**一律**是 409 构造器，
    沿用它去命名一个 403 会让读者按错误的状态码去接前端分支。
    """
```

`note_failed_login` 的实现（每一行都对应一个失败模式）：

```python
def note_failed_login(user) -> bool:
    # ① 根管理员**永不锁定**。它是「所有管理员都进不来」时唯一的破窗入口
    #    （ROOT_ADMIN_* 定义在 config.py:105-108，开关在 :111）。把它锁上等于亲手拆掉
    #    那条恢复路径，而唯一的出路恰好是「改配置 + 重启」——正是我们要保住的那条。
    #    IP 限流仍然作用于它。
    if user.is_root:
        return False
    # ② 已锁定就不再累加：否则攻击者可以在锁定期内继续打，把本函数当成一个
    #    「每请求一次 UPDATE 一行」的写放大器（SQLite 单写者，这是真实的可用性风险）。
    if is_locked(user):
        return False
    user.failed_login_count = (user.failed_login_count or 0) + 1
    policy = lock_policy()
    if user.failed_login_count < policy["threshold"]:
        return False
    user.locked_until = utcnow() + timedelta(minutes=policy["minutes"])
    # ③ 归零而不是保留：解锁之后重新起算，否则解锁后再错一次就立刻又锁上。
    user.failed_login_count = 0
    # ④ actor=None → system。锁定不是任何人做的，是规则做的。
    audit.log_user_event(user, "account_locked", None,
                         to_value="locked",
                         message=f"连续 {policy['threshold']} 次登录失败，"
                                 f"已临时锁定 {policy['minutes']} 分钟")
    # ⑤ 【评审 P1-3】通知有冷却，审计没有。判据与论证见下。
    if _should_notify_lock(user):
        notifications.notify_account_locked(user)
    return True
```

**绝不为每一次失败登录写一条 Activity。** 这条是硬约束，理由是 CLAUDE.md 里那句
「`comments` / `activities` / `notifications` 永不按数量清理」——一张永不清理的表
被接上一个匿名可触发的写入源，就是一个免费的磁盘填充器。审计只在**状态迁移**
（未锁 → 已锁）的那一刻写一条。同理，成功登录也**不写 Activity**，只更新 `last_login_at`
一列：一个 20 人团队每天登录 3 次，一年就是两万条毫无信息量的行。

##### 【评审 P1-3】v1 只算了「每次失败」，没算「每个锁定周期」——通知扇出是无上限的

v1 的 R-3 论证到「已锁定即短路，所以攻击者打不出第二条记录」就停了。真实的循环还有一步：
**锁定会在 `LOGIN_LOCK_MINUTES` 后自然到期**，到期后攻击者可以再打一轮，再锁一次。
默认 15 分钟 ⇒ 约 **4 次/小时/账号**，每次产出 1 条 `activities` + **N 条 `notifications`**
（N = 有效管理员数，`notify_account_locked` 按 `notify_user_registered` 的形状对全体管理员扇出）。
一个知道 20 个用户名、有 3 个管理员的站点：

```
4 次/小时 × 24 小时 × 20 账号 =  1 920 条 activities/天
                              ×  3 管理员 =  5 760 条 notifications/天
```

两张表都在 CLAUDE.md 的「**永不按数量清理**」名单上。IP 限流挡不住这件事——
`is_blocked` 的键含 IP（`routes/auth.py:44`），换 IP 即换桶，而这正是本轮引入账号级锁定
要解决的那个场景。所以 R-3 的原文「**只 UPDATE 不 INSERT**」在锁定迁移的那一刻
**是不成立的**，那句话必须改掉（已改，见 §6 R-3）。

**处置：给通知加冷却，审计不加。**

```python
def _should_notify_lock(user) -> bool:
    """同一账号在冷却窗口内是否已经通知过（评审 P1-3）。

    判据直接查最近一条 `account_locked` 审计，不新增列、不新增表——审计行本来就在
    那一刻写，拿它当去重锚点是零成本的。cooldown=0 时恒 True（每次都通知）。
    """
    minutes = lock_policy()["notify_cooldown"]
    if minutes <= 0:
        return True
    since = utcnow() - timedelta(minutes=minutes)
    return not db.session.query(
        Activity.query.filter(Activity.entity_type == "user",
                              Activity.entity_id == user.id,
                              Activity.action == "account_locked",
                              Activity.created_at >= since).exists()).scalar()
```

**为什么审计不一起冷却**：那一条 Activity 就是本轮功能存在的理由——审计控制台要能回答
「这个账号这一周被打了几次」。把它也压掉，`GET /api/settings/audit` 就会显示一个
被截断的、比真相温和的攻击画像，那比行数本身危险。1 920 行/天是一个**被认账的上界**
（见 §6 R-3 的重写版），运维侧的对策是 nginx 层限流与「把这个账号停用」，
两者都已在产品内。

注意冷却查询发生在**已经确定要锁定**的那一刻，即每个锁定周期至多一次；正常登录路径
（成功 / 单次失败 / 已锁定短路）**一次都不会触发它**，不构成热路径开销。

#### B-4 `routes/auth.py::login` 的新执行顺序（**顺序是契约**）

```
1. IP 限流 is_blocked(f"{client_ip()}:{username}")           → 429   【逐字不变】
2. 查用户
3. user is None or not check_password(password)
     → record_failure(IP) + （user 存在时）note_failed_login(user) + commit
     → 401 "invalid username or password"                            【逐字不变】
4. is_locked(user)  → 403 "account is temporarily locked"     【新增】
5. not user.is_active → 403 "account is disabled, ..."               【逐字不变】
6. 成功：clear(IP) + note_successful_login(user) + commit → 200      【响应体逐字不变】
```

**为什么锁定检查排在口令校验之后（第 4 步）而不是之前**——这是本支柱最重要的一个
设计决定，写反了会引入一个用户枚举预言机：

- 排在**之前**：口令错 → 401；账号锁着 → 403。攻击者只要看到 403 就知道
  「这个用户名存在，而且我把它打锁了」。对不存在的用户名恒 401。**403 成为存在性信号。**
- 排在**之后**（本方案）：口令错 → **永远** 401，锁不锁都一样；只有**口令对了**
  才可能看到 403。攻击者猜不出口令就永远只见 401，增量信息为零；
  而正当用户（他知道自己的口令）能立刻读到「临时锁定，还有 12 分钟」这条可操作信息。

代价：一个已经知道口令的人（比如口令刚被泄露）会得知账号锁着。这不是泄露——
他已经有口令了。**锁定仍然拦住他**，这才是重点。

第 3 步引入了「登录失败路径上有一次 DB 写 + commit」，这是本轮唯一一处新增的
**匿名可触发写入**。三重限制：① IP 限流先于它（每 5 分钟每 (ip,username) 最多
`LOGIN_MAX_ATTEMPTS` 次）；② 已锁定后 `note_failed_login` 立即短路，不写；
③ 它是一行 UPDATE，不插入任何行。风险表 R-3 有完整论证。

#### B-5 锁定态的 403 契约体

```json
{
  "error": "account is temporarily locked",
  "detail": {
    "reason": "too many failed sign-in attempts",
    "retry_after_seconds": 738,
    "unlock_hint": "wait it out, or ask an administrator to unlock the account"
  }
}
```

**为什么是 403 而不是 423 Locked / 429**：
- `429` 已经被 IP 限流占用（`routes/auth.py:47`），两个不同原因共用一个码会让前端
  的文案分流无从下手；
- `423` 是 WebDAV 扩展码，`errors.py` 的 `HTTPException` 处理器路径上没有它的先例，
  前端 `ApiError` 也没有对应分支；
- `403` 与**紧邻它的既有分支**（`routes/auth.py:58` 的「账号已停用」）形状完全一致：
  同一个语义类（「你是谁我知道了，但你现在不能进」），同一个状态码，靠稳定 `error`
  串区分。这是本仓库已经验证过的模式，不发明第二套。

#### B-6 解锁端点与自动过期

锁定**自然到期**：`is_locked` 只比较 `locked_until` 与 `utcnow()`，
没有任何定时任务、没有任何后台线程（本项目没有调度器，见 `config.py:98-99`）。

管理员显式解锁：`POST /api/users/<id>/unlock`，`@require_role("admin")`。
**没有根管理员 409 守卫**——根管理员结构上不可能被锁（B-3 ①），
对它调用本端点是一次幂等的 no-op，返回 200 + `unlocked: false`。
为一个不可能发生的状态写一条 409 分支，正是 CLAUDE.md §五禁止的「为理论上不会发生
的分支写防御性代码」。

#### B-7 `to_dict` 的两个 additive 键

```python
"last_login_at": _iso(self.last_login_at),
"locked_until": _iso(self.locked_until) if <未过期> else None,
"is_locked": <服务端判定的布尔>,
```

- **`is_locked` 由服务端判定**，前端不拿 `locked_until` 自己跟本地时钟比——
  用户的机器时间可能偏几分钟，那会让「已解锁」的账号在界面上还显示着锁。
- **`failed_login_count` 有意不进 API。** `GET /api/users` 是 `jwt_required()` 而非
  admin-only（`routes/users.py:58-59`），全员可读。「某人已经错了 7 次」对普通成员
  没有任何用处，对一个已经拿到低权限凭据的攻击者却是有用的侦察信息。
- `last_login_at` / `is_locked` **进** `to_dict` 是有先例的：`must_change_password`
  已经全员可见（`models/user.py:73`）。同一类治理事实，同一个可见性水位，不发明例外。
  **【评审 P2-7】这条决定要把代价写明白**：`GET /api/users` 是 `jwt_required()` 而非
  admin-only（`routes/users.py:58-59`），所以「谁三个月没登录了」对**全体成员**可见。
  这比「该改密码了」更接近考勤数据，在一个 20 人的内部工具里可以接受，
  但如果本产品将来面向跨组织的租户，这两个键**必须**是第一批被降级到 admin-only 的字段。
  `?locked=` 筛选同理保持全员可用——它是 `to_dict` 已经暴露的事实的查询形式，
  单独把筛选收紧只会制造一个绕不过去的假门禁。
- `summary()`（`models/user.py:78`）**一个键都不加**——指派选择器不关心谁多久没登录。
  这条约定在 `models/user.py:66-72` 已经写死过两次，第三次照办。

#### B-8 列表筛选 `?locked=`

`routes/users.py::_apply_user_filters`（`:24`）追加第五个筛选：

```python
locked = want_query_bool("locked")
if locked is not None:
    now = utcnow()
    query = query.filter(User.locked_until > now) if locked \
        else query.filter(or_(User.locked_until.is_(None), User.locked_until <= now))
```

沿用既有契约：非法取值 → `QueryParamError` → 全局 400，空串等价于不传。

### 1.3 支柱 C：站点治理审计的出口（routes/settings.py + services/audit.py）

#### C-1 新查询函数

```python
GOVERNANCE_ENTITY_TYPES = (ENTITY_USER, ENTITY_APP_SETTING)
ALL_ACTIONS = USER_ACTIONS + SETTINGS_ACTIONS      # 供路由做 choices 校验

def governance_timeline(*, entity_type=None, action=None, actor_id=None, since=None):
    """站点级治理审计查询（**未分页**，供路由套 paginate）。

    与 `user_timeline` 并列：那个回答「这个人身上发生过什么」，
    本函数回答「这个站点上发生过什么」。
    """
    q = Activity.query.filter(Activity.entity_type.in_(
        (entity_type,) if entity_type else GOVERNANCE_ENTITY_TYPES))
    if action is not None:
        q = q.filter(Activity.action == action)
    if actor_id is not None:
        q = q.filter(Activity.actor_type == "user", Activity.actor_id == actor_id)
    if since is not None:
        q = q.filter(Activity.created_at >= since)
    return q.order_by(Activity.created_at.desc(), Activity.id.desc())
```

`entity_type` 默认取**两者**是关键：`app_setting` 事件今天写了读不到，本轮的第一目的
就是让它可读。写成默认只查 `user` 等于把缺陷原样带进新端点。

#### C-2 引用解析：一次查询，不做 N+1

```python
def resolve_actors(rows) -> dict:
    """把一页审计行里出现的所有 user id 一次性解析成 {id: {"id":.., "name":..}}。

    需要解析的 id 有两个来源：施动者（actor_type == "user" 的 actor_id）与
    被治理对象（entity_type == "user" 的 entity_id）。合成一个集合、发**一次**
    `IN` 查询——逐行 `db.session.get` 在 50 行的默认页宽下就是 100 次往返。
    """
```

**为什么不用 `Activity.resolve_actor()` 那类既有方法**：`models/comment.py::_resolve_author`
是逐行解析的，用在一条评论上没问题，用在一页 50 行审计上就是 N+1。
这里是列表端点，必须批量。

#### C-3 端点契约见 §2.3。权限是 `@require_root()` 而非 `require_role("admin")`：

本端点会返回 `app_setting` 事件，而**站点设置本身就是 root-only**
（`routes/settings.py:63` / `:69` / `:104` 三处 `@require_root()`）。
让普通 admin 从审计流里读到「根管理员什么时候改了注册配置」，等于绕过那三道门禁
读到治理面的元信息。普通 admin 需要的粒度已经由
`GET /api/users/<id>/activities`（admin-only，`routes/users.py:261`）给足了。

#### C-4 三个溢出必修（与主线同一提交，不得拆开）

1. **`services/audit.py::USER_ACTIONS` 追加两项** `account_locked` / `account_unlocked`。
   前端 `lib/types.ts:71` 的 `UserActivityAction` 是它的镜像，且
   `USER_ACTIVITY_LABELS` / `USER_ACTIVITY_ICONS` 已被上一轮收紧为
   `Record<UserActivityAction, string>`（`lib/constants.ts:337` / `:347`）——
   **漏改任何一处都是 `npm run typecheck` 的编译错误**。这是设计上刻意留下的护栏，
   实施时不要为了图快把它们改回 `Record<string, string>`。
2. **`models/notification.py::NOTIFICATION_TYPES` 追加 `account_locked`。**
   前端三处镜像：`lib/types.ts:259` 的联合类型、`:277` 的
   `NOTIFICATION_TYPE_LIST` 运行时列表、`lib/constants.ts` 的两个
   `Record<NotificationType, string>` map。`NotificationPrefsCard` 遍历
   `NOTIFICATION_TYPE_LIST`，无需单独改。
   `tests/test_settings.py:125` 断言 `set(prefs.keys()) == set(NOTIFICATION_TYPES)`——
   它从常量派生，**不会翻**。
3. **`services/notifications.py` 新增 `notify_account_locked`。**
   收件人 = 全部有效管理员，与既有 `notify_user_registered`（`:186`）**逐字同构**：
   `no_autoflush` 包住收件人查询、不 commit、message 必传、`entity_type`/`entity_id` 传 None。
   施动者传 `None`（system）——`notify()` 的「不给自己发」判据
   （`services/notifications.py:55`）因此天然不触发，被锁的人如果自己是 admin 也会收到，
   这是对的：他需要知道自己的账号刚被打锁了。

---

## 2. 接口设计

### 2.1 `POST /api/auth/login`（既有，新增一个分支）

| 情况 | 状态码 | `error` | 变化 |
|---|---|---|---|
| 缺字段 / 非串 | 400 | `username and password are required` | 不变 |
| IP 窗口内失败超阈 | 429 | `too many attempts, try later` | 不变 |
| 用户不存在 / 口令错 | 401 | `invalid username or password` | **响应体不变**，但副作用新增：失败计数 +1 |
| 口令正确但账号锁定 | **403** | **`account is temporarily locked`** | **新增**，detail 见 §1.2 B-5 |
| 口令正确但账号停用 | 403 | `account is disabled, contact an administrator` | 不变 |
| 成功 | 200 | — | 响应体 `{token, user}` 不变；`user` 多两个 additive 键 |

### 2.2 `POST /api/users/<id>/unlock`（新增，`@require_role("admin")`）

请求体：忽略（空 body 合法）。

| 情况 | 状态码 | 响应体 |
|---|---|---|
| 未登录 / 非 admin | 401 / 403 | `require_role` 既有形状 |
| id 不存在 | 404 | `{"error": "user not found"}` |
| 成功解锁 | 200 | `{"user": {...}, "unlocked": true}` |
| 本来就没锁（含根管理员） | 200 | `{"user": {...}, "unlocked": false}` |

`unlocked: false` 时**不写审计**——一次没有改变任何状态的操作不该在时间线上留一行，
那会让「这个账号被解锁过 3 次」这句话失去意义。与
`services/lifecycle.py::unassign_ticket`（`:213` 的幂等约定）同一取向。

### 2.3 `GET /api/settings/audit`（新增，`@require_root()`）

查询串：

| 参数 | 类型 | 缺省 | 非法时 |
|---|---|---|---|
| `entity_type` | `user` \| `app_setting` | 两者 | 400（`want_query_str(choices=...)`）|
| `action` | `ALL_ACTIONS` 之一 | 不过滤 | 400 |
| `actor_id` | int | 不过滤 | 400（`want_query_int`）|
| `since` | ISO8601 | 不过滤 | 400（`want_query_datetime`，**本轮新增**，见下）|
| `limit` / `offset` | int | 50 / 0 | 400（`paginate` 既有）|

#### 【评审 P0-3】`since` 需要一个不存在的原语，而 v1 的写法本身是一个 TypeError

v1 写的是 `QueryParamError(field="since", expected="ISO 8601 datetime")`。
`services/scope.py:29` 的真实签名是：

```python
def __init__(self, field: str, got, expected: str):
```

三个**位置**必填参数。少传 `got` → 实例化即 `TypeError` → 被全局兜底渲染成 **500**，
而这条分支正是「非法 `since`」的唯一出口。也就是说，`?since=乱码`（用例 60 要断言 400 的
那个输入）在 v1 的写法下**必然 500**。

更根本的问题是：查询串侧根本没有 datetime 原语。`services/scope.py` 只有
`want_query_int`（`:40`）/ `want_query_str`（`:78`）/ `want_query_bool`（`:109`），
而 §3.2 的变更计划里**没有 `services/scope.py` 这一行**——v1 默认它已经够用了。
（`services/validation.py` 管的是**请求体**，不是查询串，两者的分工写死在
`scope.py:3-8` 的模块 docstring 里，不得混用。）

因此本轮在 `services/scope.py` 追加**第四个**查询串原语，与既有三个逐字同构：

```python
def want_query_datetime(field: str, *, default=None):
    """从查询串取一个 ISO 8601 时刻；缺省 / 空串返回 default，非法抛 QueryParamError（→ 400）。

    容忍尾部 `Z`：本站的 `to_dict` 输出恒补 Z（`models/user.py:92`），
    界面上看到的值原样提交回来必须能被接住，否则就是「显示的值提交回来就 400」
    这种自相矛盾（同 R-14）。返回 **naive UTC**，与 `extensions.utcnow()` 同一口径。
    """
    raw = request.args.get(field)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip()
    try:
        return datetime.fromisoformat(value[:-1] if value.endswith("Z") else value)
    except ValueError:
        raise QueryParamError(field, raw, "ISO 8601 datetime")
```

三点必须照办：① `QueryParamError` 用**三参位置调用**；② 用 `value[:-1]` 而不是
`rstrip("Z")`——后者会把 `"...ZZZ"` 也吃掉，虽然无害，但「只削一个尾字符」是更诚实的写法；
③ 错误体不在路由里自造，由 `errors.py:39` 的全局处理器按 `query_error_response`
（`scope.py:158-166`）渲染成 `{error, detail:{field, expected, got}}`，与全站逐字同形。

响应：**裸数组** + `X-Total-Count` 头（与 `GET /api/users`、
`GET /api/users/<id>/activities` 完全一致的既有形状，前端 `listFetcher` 直接可用）。

单行形状 = `Activity.to_dict()` 加两个解析块：

```json
{
  "id": 812, "entity_type": "app_setting", "entity_id": 0,
  "action": "invite_code_rotated",
  "from_status": null, "to_status": null,
  "actor_type": "user", "actor_id": 1,
  "message": "重新生成了邀请码",
  "created_at": "2026-07-21T02:11:09.442Z",
  "actor":  { "id": 1, "name": "Ada（管理员）" },
  "target": null
}
```

- `actor`：`actor_type == "user"` 且解析得到时为 `{id, name}`，否则 `null`
  （system 事件如 `account_locked` 恒为 `null`）。
- `target`：`entity_type == "user"` 且解析得到时为 `{id, name}`，否则 `null`
  （`app_setting` 是站点单例，没有目标对象）。
- **解析不到一律降级为 `null`，绝不抛**——`activities` 没有 DB 外键
  （`models/app_setting.py:8` 记载了同一条项目惯例），被删的用户必须能安全渲染成占位。

### 2.4 `GET /api/settings/registration`（既有，五个 additive 键）

```json
{
  "enabled": true, "invite_code": "aragon", "default_role": "member",
  "allowed_default_roles": ["member", "pm"],
  "updated_at": "...", "updated_by": {"id": 1, "name": "..."},

  "invite_expires_at": "2026-08-01T00:00:00Z",
  "invite_max_uses": 20,
  "invite_uses": 7,
  "invite_issued_at": "2026-07-18T09:30:00Z",
  "invite_status": "active"
}
```

`invite_status` ∈ `active` / `expired` / `exhausted` / `disabled`（开关关闭时优先），
由服务端算一次下发——让前端自己拿 `expires_at` 与本地时钟比会重蹈 B-7 的时钟漂移坑，
而且 `exhausted` 的判据在前端根本拿不到（要数用户）。

**HTTP 响应体的既有六个键逐字不变**，故 `tests/test_app_settings.py` 里针对**端点**的断言
（`body["invite_code"] == ...`、`(body["enabled"], body["invite_code"], body["default_role"]) == ...`，
分布在 `:61-63`、`:73-76`、`:87-89`）全部继续通过——这些确实都是逐键断言。

**【评审 P0-1】但 v1 这句「已核对」只核对了端点，漏了服务层。**
`tests/test_app_settings.py:26-28` 是对 `app_settings.get_registration_settings()`
**返回值**的全等 dict 断言：

```python
assert app_settings.get_registration_settings() == {
    "enabled": True, "invite_code": "aragon", "default_role": "member",
}
```

而 §1.1 A-4 的 `check_invite_code` 正是从这个函数读期限与额度的，即它必须扩到 5 键。
**这条断言必然翻**，它是本轮第二条（也是最后一条）必改的既有断言，见 §7.1。

序列化侧的两条硬约束（同见 §1.1 A-4）：

- `invite_expires_at` / `invite_issued_at` 在 `get_registration_settings()` 里是 `datetime`，
  出到 JSON 前必须逐个走 `_iso()`（`routes/settings.py:58-59`，输出恒补 `Z`）。
  **禁止 `{**settings}` 展开**——`jsonify` 会把 `datetime` 写成 RFC 822 的
  `"Wed, 01 Aug 2026 00:00:00 GMT"`，而既有用例只逐键断言字符串相等，
  这是一次**没有任何测试会红**的静默契约破坏。
- 【评审 P2-5】`updated_at` / `updated_by` 取的是 `REGISTRATION_KEYS` 里最近改动的一行
  （`routes/settings.py:44-46`）。加 3 键后系统自动写的 `invite_issued_at` 行也进入这个
  `max`；因为它与码行恒由同一次请求、同一个 actor 写出（§1.1 A-5），显示结果不变。
  `test_app_settings.py:63`（全新库上两者为 `None`）与 `:75`（PATCH 后 `updated_by.id`
  等于施动者）都不受影响——前者无行，后者两行同 actor。

### 2.5 `PATCH /api/settings/registration`（既有，两个 additive 可更新键）

`_UPDATABLE_KEYS`（`routes/settings.py:24`）扩为
`("enabled", "invite_code", "default_role", "expires_at", "max_uses")`。
**顺序即校验顺序**（该行注释已经这么规定），新键排在末尾。

```python
if "expires_at" in data:
    # None 与 "" 都表示清除；非串 → 400（want_str 抛）。
    changes["expires_at"] = want_str(data, "expires_at", max_len=64) or None
if "max_uses" in data:
    changes["max_uses"] = want_int(data, "max_uses", required=True, minimum=0, maximum=10000)
```

`want_int` **已经存在**，签名逐字如下（`services/validation.py:94-95`）：

```python
def want_int(data, key, *, required=False, default=None, minimum=None, maximum=None)
```

三条既有语义直接满足本轮需求，**不要改它、也不要另写一个**：
① 只接受 JSON 数字，不接受 `"5"` 这种数字串（`:98`、`:108`）——
故 `{"max_uses": "20"}` 是 400，这是对的，前端必须传数字；
② `bool` 被显式排除（`:108`），`{"max_uses": true}` 是 400；
③ 64 位硬界无条件生效，`minimum` / `maximum` 只能在其内部再收窄（`:100-101`）。
错误体是既有的 `ValidationError(field="max_uses", expected=">=0" / "<=10000")`，
不发明第二套。

审计 message 仍然**只列键名、绝不带值**（`routes/settings.py:95-96` 的硬约束）——
`expires_at` / `max_uses` 本身不是凭据，但让 message 的规则出现「这两个可以带值、
那个不行」的分叉，就是下一次事故的种子。

### 2.6 `GET /api/auth/registration-meta`（既有，**一个字都不改**）

公开端点，**有意不下发**邀请码的期限 / 额度 / 用量。理由：
「这个站点的邀请码 3 天后过期、还剩 2 个名额」对一个未持码的匿名访客是纯粹的情报，
对持码者则毫无必要（他提交时会拿到精确的 403 reason）。

这条决定的直接收益：`tests/test_registration.py:324` 那条**全等**断言
（`body == {enabled, invite_required, password_min_length, password_max_length,
password_min_char_classes}`）**不会翻**。上一轮的 §12 I-2 记录过同一个失败模式，
本轮从设计上绕开它。

---

## 3. 文件 / 模块变更计划

### 3.1 后端新增（4 个）

| 文件 | 意图 |
|---|---|
| `backend/services/login_guard.py` | 登录锁定的唯一实现：策略钳位、锁定判定、失败/成功记账、解锁、403 契约体 |
| `backend/services/config_knobs.py` | 把 `passwords.py::_clamped_config_int` 提升为公共件（第二个调用点出现即抽取），**加 `source` 形参**（评审 P1-4） |
| `backend/tests/test_login_guard.py` | 支柱 B 的全部用例（策略钳位、顺序、根管理员豁免、解锁、写放大短路） |
| `backend/tests/test_invite_lifecycle.py` | 支柱 A 的全部用例（期限、额度、用量派生、issued_at 回落链、reason 分流） |

### 3.2 后端修改（15 个）

| 文件 | 改动 |
|---|---|
| `backend/config.py` | 新增 `LOGIN_LOCK_THRESHOLD` / `LOGIN_LOCK_MINUTES` / `LOGIN_LOCK_NOTIFY_COOLDOWN_MINUTES`；`TestConfig` 覆盖为 **3** / 15 / 1440（评审 P0-2、P1-3） |
| `backend/models/user.py` | 3 个新列；`to_dict` 加 `last_login_at` / `locked_until` / `is_locked`；`summary()` **不动** |
| `backend/models/notification.py` | `NOTIFICATION_TYPES` += `account_locked` |
| `backend/services/schema_sync.py` | `ADDITIVE_COLUMNS` += 3 条（两步编辑铁律） |
| `backend/services/app_settings.py` | 3 个新键 + `check_invite_code` + `invite_uses` / `invite_issued_at` + 2 个 coercer + 写入侧约束 |
| `backend/services/audit.py` | `USER_ACTIONS` += 2；`GOVERNANCE_ENTITY_TYPES` / `ALL_ACTIONS` / `governance_timeline` / `resolve_actors` |
| `backend/services/notifications.py` | `notify_account_locked`（与 `notify_user_registered` 同构） |
| `backend/services/passwords.py` | 改调 `config_knobs.clamped_int(..., source="passwords")`（**外部行为、日志串逐字节不变**，评审 P1-4） |
| `backend/services/scope.py` | **【评审 P0-3 补入】**新增第四个查询串原语 `want_query_datetime`（§2.3）。v1 的变更计划遗漏了本文件，而 `?since=` 无它不可实现 |
| ~~`backend/services/validation.py`~~ | **不改**：`want_int` 已存在于 `:94`，签名与语义直接可用（§2.5）。注意它管的是**请求体**；查询串归 `scope.py`，分工写死在 `scope.py:3-8`，不得混用 |
| `backend/tests/test_app_settings.py` | **必改**：`:26-28` 对 `get_registration_settings()` 的全等断言补 2 键（评审 P0-1，见 §7.1） |
| `backend/routes/auth.py` | `login` 按 §1.2 B-4 重排；`signup` 第 4 步改调 `check_invite_code` 并按 reason 分流 |
| `backend/routes/users.py` | `_apply_user_filters` 加 `?locked=`；新增 `POST /<id>/unlock` |
| `backend/routes/settings.py` | `_registration_payload` 加 5 键；`patch_registration` 加 2 键；新增 `GET /audit` |
| `backend/tests/test_schema_sync.py` | **必改**：`:57` 的全等断言补 3 个列名（见 §7.1） |

### 3.3 前端新增（5 个）

| 文件 | 意图 |
|---|---|
| `frontend/app/(app)/audit/page.tsx` | 站点治理审计页（root-only），筛选 + 分页 + 时间线 |
| `frontend/components/admin/AuditFilterBar.tsx` | 审计筛选条（实体 / 动作 / 施动者 / 起始时间），与 `MemberFilterBar` 同构 |
| `frontend/components/settings/InviteQuotaFields.tsx` | 邀请码期限 + 额度 + 用量进度条（挂进 `RegistrationCard`） |
| `frontend/hooks/useGovernanceAudit.ts` | `GET /settings/audit` 的 SWR 封装（含筛选串拼接） |
| `frontend/lib/format.ts` | **【评审 P1-5 补入】**相对时间 `relTime()` 的唯一真相。v1 的 §5.2 写的是「把它提到 `lib/format.ts`」，但该文件**不存在**，且 `relTime` 现在有**两份**副本（`components/admin/MemberActivityModal.tsx:29`、`components/notifications/NotificationBell.tsx:15`，后者 v1 完全没提）。所以这是「新建模块 + 收口两处既有副本」，本行补进新增清单后，本节恰为标称的 5 个（评审 P1-6 的计数问题一并解决） |

> **不新建进度条原语。** 我读了 `components/ui/ProgressBar.tsx`：它接
> `{ value: number | null; label?: string; className?: string }`，`value` 是 0~100 的
> 百分比，已带 `role="progressbar"` + `aria-valuenow/min/max/valuetext` 与
> 「`null` = 不确定模式」。用量条**直接复用它**：传
> `max_uses > 0 ? Math.round(uses / max_uses * 100) : null`，
> 「接近上限转警示色」通过 `className`（`[&>div]:bg-clay-dark` 之类）与**旁边那行状态
> 文案**表达，不改 `ProgressBar` 本身。上一轮 P1-3 的教训正是「先假设需要一个新组件、
> 结果仓库里已经有了」——这次先读了再写。
>
> **【评审 P2-4】用它的时候有两个坑，先说清楚：**
> ① `label` 走的是 `aria-label`（`ProgressBar.tsx:21`），**不渲染任何可见文字**——
> 「已用 7 / 20」这行必须自己写在组件旁边，`label` 只负责让读屏器念对；
> ② `className` 被拼到**外层轨道** div 上（`:26`），所以 `[&>div]:bg-clay-dark` 才命中
> 填充条，而一个裸的 `bg-clay-dark` 会把**轨道**染色、填充条反而看不见。

### 3.4 前端修改（11 个）

| 文件 | 改动 |
|---|---|
| `frontend/components/notifications/NotificationBell.tsx` | **【评审 P1-5 补入】**删掉本地 `relTime`（`:15`），改 import `lib/format.ts`。不做这一步，本轮就从「两份副本」变成「三份副本 + 一个公共件」 |
| `frontend/components/admin/MemberActivityModal.tsx` | 同上，删本地 `relTime`（`:29`）改 import |
| `frontend/lib/types.ts` | `User` += 3 键；`UserActivityAction` += 2；`NotificationType` + `NOTIFICATION_TYPE_LIST` += 1；`RegistrationSettings` += 5 键；新增 `GovernanceActivity` / `AuditFilters` |
| `frontend/lib/constants.ts` | `USER_ACTIVITY_LABELS` / `USER_ACTIVITY_ICONS` += 2；两个 `NOTIFICATION_*` map += 1；新增 `AUDIT_ENTITY_LABELS` |
| `frontend/lib/api.ts` | 新增 `GOVERNANCE_AUDIT_PREFIX = "/settings/audit"`。**【评审 P1-7】不叫 `*_KEY`**：`api.ts:19-24` 已经把不变量写死——一个 `*_KEY` ⇒ 一种响应形状，**分页 / 带筛选的视图不得复用它们**（`USERS_KEY = "/users?limit=200"` 正是被那段注释点名的反例）。审计页是分页 + 4 筛选的，页面 key 必须像 `team/page.tsx:65-66` 那样内联拼；这个常量只作**路径前缀**，供失效前缀与 hook 拼串 |
| `frontend/lib/swr-keys.ts` | **就地**扩 `:24` 的 `ADMIN_VIEW_PREFIXES` 数组字面量，追加 `"/settings/audit"`（解锁 / 改配置后审计页要跟着刷）。**【评审 P1-6】该常量没有 `export`**（对外只暴露 `invalidateAdminViews`，`:38`），写成「从外部 `+=`」会让实施者去找一个不存在的导出 |
| `frontend/components/layout/Sidebar.tsx` | 「审计」导航项，**仅 `user.is_root` 时渲染**；需要把 `NAV` 从模块级常量改为按 `useAuth()` 过滤 |
| `frontend/components/settings/RegistrationCard.tsx` | 挂载 `InviteQuotaFields`；底部说明补一句额度语义 |
| `frontend/components/admin/MemberFilterBar.tsx` | 第五个筛选「锁定状态」；`MemberFilters`（`:18-23`）+= `locked`；**`EMPTY_FILTERS`（`:25`）必须同步**，否则「清空筛选」清不掉它（评审 P2-9）；`toQuery`（`:105-112`）同步。三态写法直接照抄既有「状态」筛选（`:82-91` + `STATUS_OPTIONS :32-35`）：`"" \| "true" \| "false"` + `Select` 的 `placeholder` 供第三态 |
| `frontend/app/(app)/team/page.tsx` | 「已锁定」徽章 + 「解锁」行操作 + 「最后登录」列（md 以上）；确认对话框 |
| `frontend/hooks/useRegistrationSettings.ts` | `RegistrationSettingsPatch` += `expires_at?` / `max_uses?` |

### 3.5 文档（2 个）

| 文件 | 改动 |
|---|---|
| `README.md` | 配置表补 `LOGIN_LOCK_THRESHOLD` / `LOGIN_LOCK_MINUTES` / `LOGIN_LOCK_NOTIFY_COOLDOWN_MINUTES`；邀请码一节补期限 / 额度。**【评审补】必须写明 `LOGIN_LOCK_THRESHOLD` 与 `LOGIN_MAX_ATTEMPTS` 的隐式关系**：前者 ≥ 后者时账号锁定在该部署下**永远不可能触发**（IP 限流先把请求挡光），默认 8 < 10 是刻意的 |
| `docs/iterations.md` | 追加本轮条目 |

---

## 4. 数据模型

### 4.1 `users` 表（3 个新列）

```python
# —— login-hardening-and-audit-console §1.2 B-1 ——
# 三列必须同时登记进 services/schema_sync.py::ADDITIVE_COLUMNS，否则存量库全线 500。
last_login_at = db.Column(db.DateTime, nullable=True)
failed_login_count = db.Column(db.Integer, nullable=False, default=0, server_default="0")
locked_until = db.Column(db.DateTime, nullable=True)
```

`schema_sync.ADDITIVE_COLUMNS` 追加：

```python
("users", "last_login_at", "DATETIME"),
("users", "failed_login_count", "INTEGER NOT NULL DEFAULT 0"),
("users", "locked_until", "DATETIME"),
```

**追加位置必须是列表末尾**：`sync_additive_columns` 按列表顺序执行并按顺序返回
`applied`，而 `tests/test_schema_sync.py:57` 断言的是那个列表的**精确顺序**。
插在中间会让断言以一种和本轮无关的方式失败。

### 4.2 `app_settings` 表（**零结构变更**，3 个新键）

| key | value 样例 |
|---|---|
| `registration.invite_expires_at` | `"2026-08-01T00:00:00"` 或 `""` |
| `registration.invite_max_uses` | `"20"` 或 `"0"` |
| `registration.invite_issued_at` | `"2026-07-18T09:30:00.123456"` |

时间一律存 **naive UTC 的 `isoformat()`**，与 `extensions.py:86` 的 `utcnow()` 同一口径
（`datetime.now(timezone.utc).replace(tzinfo=None)`）。读回用
`datetime.fromisoformat(raw.rstrip("Z"))`——`rstrip("Z")` 是为了容忍从 API 回填的带 Z 串
（`to_dict` 输出恒补 Z，见 `models/user.py:92`），少了它就会出现「界面上显示的值原样
提交回来就 400」这种自相矛盾。

### 4.3 `activities` 表（**零结构变更**）

新增两个 `entity_type="user"` 的 action：

| action | actor | from/to_status | message |
|---|---|---|---|
| `account_locked` | `system`（actor_type=system, actor_id=NULL） | `to_status="locked"` | `连续 N 次登录失败，已临时锁定 M 分钟` |
| `account_unlocked` | `user`（施动的 admin） | `from_status="locked"` | `解除了该账号的登录锁定` |

`app_setting` 事件不新增 action，`registration_updated` 覆盖期限 / 额度的修改。

**【评审 P2-6】列宽边界**（`models/activity.py:25,30-31`）：`action` 是 `String(32)`、
`from_status` / `to_status` 是 `String(24)`、`message` 是 `String(255)` 且 `Activity.log`
已在 `:70-71` 自带截断。本轮取值 `account_locked`(14) / `account_unlocked`(16) / `locked`(6)
全部在界内，无需改列——但这一行必须写下来，否则下一个想加 action 的人得自己去量。

### 4.4 `notifications` 表（**零结构变更**）

新增类型 `account_locked`，`entity_type` / `entity_id` 均为 `NULL`
（与 `user_registered` 一致，`services/notifications.py:196-198` 记载了前端
`NotificationBell.onOpenItem` 已有的 null 守卫）。

---

## 5. 前端信息架构与交互设计

### 5.1 邀请码卡片（`RegistrationCard` 内联扩展，不新建页面）

在既有「邀请码」输入行与「新用户默认角色」之间插入一组：

```
┌────────────────────────────────────────────────────┐
│ 邀请码  [••••••••••]  [显示] [复制]                 │
│ [保存邀请码] [重新生成]   4~64 个字符，不含空格      │
│                                                    │
│ 有效期至   [2026-08-01 00:00]  [清除]   留空 = 永不过期│
│ 名额上限   [ 20 ]  个             0 = 不限            │
│ ▓▓▓▓▓▓▓░░░░░░░░  已用 7 / 20      状态：生效中        │
│                                                    │
│ 新用户默认角色  [成员 ▾]                            │
└────────────────────────────────────────────────────┘
```

交互约定（每条都对应一个可预见的困惑）：

1. **用量条的颜色分三档**：`< 80%` 用 `ink-muted`，`>= 80%` 用 `clay`，
   `>= 100%` 或已过期用 `clay-dark` 并把状态文案换成「已用尽」/「已过期」。
   颜色不是唯一信息载体——状态文案始终在旁边，满足非色觉依赖（WCAG 1.4.1）。
2. **「重新生成」的确认文案必须说明额度会归零。** 既有 `ConfirmDialog`
   （`RegistrationCard.tsx:190`）的描述里追加一句「已用名额将重新从 0 计起，
   有效期与名额上限保持不变」——这正是 §1.1 A-5 的语义，用户必须在按下之前知道。
3. **有效期用 `<input type="datetime-local">`**，提交前转 UTC ISO。
   输入框旁常驻一行小字显示「= UTC 2026-08-01 00:00」——本产品的时间全部以 UTC 存储，
   不显示换算结果就一定会有人填错八小时。
4. **过去的时刻由前端先拦一次**（`disabled` + 内联错误），不要让用户提交完才吃 400。
   后端那道 400 是权威判据，前端这道只是体验。

### 5.2 团队页（`app/(app)/team/page.tsx`）

- **新列「最后登录」**（仅 `md:table` 分支，移动端卡片里以小字追加）：
  用相对时间渲染。**【评审 P1-5】现状比 v1 描述的更糟，动作也更大**：
  `relTime()` 现在有**两份逐字相同的副本**——`components/admin/MemberActivityModal.tsx:29`
  与 `components/notifications/NotificationBell.tsx:15`（前者的注释 `:28` 自己都写了
  「形状与 NotificationBell 的同名函数一致」），而 `frontend/lib/format.ts`
  **并不存在**。所以本轮要做的不是「搬一处」，是**新建 `lib/format.ts` 并把两处副本一起
  收口**，否则加上审计页的第三个消费者就成了「一个公共件 + 三份副本」，
  比现在还差（本仓库对第二真相的态度见 `services/lifecycle.py:5-6`）。
  收口时行为逐字不变（刚刚 / N 分钟前 / N 小时前 / N 天前 / `toLocaleDateString("zh-CN")`），
  两个调用点各删一段、各加一行 import，`npm run typecheck` 是它的机器执行者。
  从未登录显示「—」，不显示「从未」——一列里混着日期和汉字会让扫读变慢。
- **「已锁定」徽章**：视觉权重排在「根管理员」之后、「已停用」之前。
  一行最多显示两个徽章（既有约定，`team/page.tsx:185`），锁定 + 停用同时成立时
  只显示「已停用」——停用是更强的状态，锁定在它面前没有信息量。
- **行操作追加「解锁」**：`user.is_locked` 为 false 时**不渲染**（不是 disabled）。
  这与「重置密码 / 停用」的 `disabled + title` 处理**有意不同**：那两个是
  「有这个能力但对这一行不适用」，而解锁是「这一行现在没有可解的东西」，
  渲染一个恒灰的按钮只是噪音。`team/page.tsx:33-35` 的注释论证了前一种情况，
  这里补一条注释论证后一种。
- **确认对话框**：解锁不是破坏性操作，但会让一个刚被系统挡住的账号重新可试口令，
  值得一次确认。文案说明「该账号将立即可以重新尝试登录；失败计数归零」。
- **筛选条第五项「锁定状态」**：`全部 / 已锁定 / 未锁定`。

### 5.3 治理审计页（`app/(app)/audit/page.tsx`，root-only）

- **路由位置**：放进 `(app)` 组，自动获得既有的登录守卫与侧栏布局。
- **非根管理员访问**：页面自身渲染一个 `EmptyState`
  （标题「仅根管理员可见」，说明「站点治理审计包含注册配置的变更记录，
  只有根管理员可以查看；你可以在团队页查看单个成员的账号动态」），
  **不做 `router.replace`**——重定向会闪一下再跳走，用户不知道发生了什么，
  而且会掩盖「这个链接不该出现在我的侧栏里」这个真实的 bug。

  **【评审 P1-8】这是本仓库的第一例「页面级无权限态」，必须当成一条新惯例写下来。**
  现状是：`app/(app)/layout.tsx:15-34` 只处理**未登录**（跳 `/login`）与**强制改密**
  （跳 `/force-password`）两种情况，没有任何页面渲染过「你没权限看这一页」。
  既有的两条惯例都是**局部**的——**整块隐藏**（`app/(app)/settings/page.tsx:57`：
  `{user?.is_root && <RegistrationCard />}`）与**禁用 + title 解释**
  （`team/page.tsx:300-320`）。分工判据（本轮定下，后续同类照办）：

  | 粒度 | 做法 | 依据 |
  |---|---|---|
  | 页面内的一块（卡片 / 按钮 / 列） | 隐藏，或禁用 + `title` 解释 | 用户还有别的事能在这一页做 |
  | 整个页面 | 渲染 `EmptyState`，**不 redirect** | 用户是被一个链接送到这里的，他需要知道为什么到不了 |

  不写这张表的后果是确定的：下一个做 root-only 页面的人会掷硬币，然后仓库里同时存在
  redirect、空白页、EmptyState 三种做法。
- **布局**：筛选条 + 时间线列表 + 分页。时间线单行的结构与
  `MemberActivityModal::ActivityRow` 同构（图标 / 标题 / 迁移 / 相对时间 / message），
  但**多一列施动者与对象**：

```
🔒  账号被锁定                   系统 → 张三          12 分钟前
    连续 8 次登录失败，已临时锁定 15 分钟

🔑  重新生成了邀请码             Ada（管理员）        2 小时前
```

- **`app_setting` 行没有 target**，那一列留空而不是显示「站点」——
  `app_setting` 是单例，写一个恒定的词只会占位。
- **空态分两种**：完全没有审计（「还没有治理记录」）与筛选无结果
  （「没有符合条件的记录」+ 清空筛选按钮），沿用 `team/page.tsx:114-125` 的既有模式。

### 5.4 登录页（`app/login/page.tsx`）

锁定态 403 的文案必须**区别于**停用态 403。前者可自愈、有明确等待时长：

> 登录尝试过于频繁，账号已临时锁定，请在 **12 分钟**后重试，或联系管理员解锁。

分钟数从 `detail.retry_after_seconds` 换算（向上取整）。
`retry_after_seconds` 缺失时降级为不带时长的句子——**绝不显示「NaN 分钟」**。

### 5.5 侧栏（`components/layout/Sidebar.tsx`）

现状 `NAV` 是模块级常量（`Sidebar.tsx:40`），组件内直接 `NAV.map`。
改动最小的做法：保留 `NAV` 不动，新增 `ROOT_ONLY_NAV`，在组件内
`const items = useMemo(() => user?.is_root ? [...NAV, ...ROOT_ONLY_NAV] : NAV, [user])`。
「审计」项插在「设置」**之前**——设置在导航末位是既有约定，不要把它挤走。

---

## 6. 风险与缓解

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R-1 | 锁定检查排到口令校验之前 | 403 成为用户存在性预言机 | §1.2 B-4 把顺序钉成契约；用例 12′ 断言「不存在的用户名 + 任意口令」与「存在但锁定的用户名 + 错口令」的响应体**逐字节相同** |
| R-2 | 根管理员被锁 | 破窗路径失效，产品内无恢复 | `note_failed_login` 首行 `if user.is_root: return False`；用例 9 断言连打 20 次后 `locked_until is None` |
| R-3 | 失败登录路径引入匿名可触发的 DB 写 | SQLite 单写者下的写放大 | **【评审 P1-3 重写】**v1 写的「只 UPDATE 不 INSERT」**在锁定迁移那一刻不成立**：那一刻会 INSERT 1 条 `activities` + N 条 `notifications`。真实上界要按**锁定周期**算而非按「每次失败」算：锁 15 分钟自然到期后可再锁，约 4 次/小时/账号；20 账号 × 3 管理员 ⇒ ~1 920 条 activities/天 + ~5 760 条 notifications/天，而两张表都在「永不按数量清理」名单上。处置：通知加 24h 冷却（§1.2 B-3 ⑤），审计**不加**（它就是本功能的产出，1 920 行/天是被认账的上界）。稳态路径（成功 / 单次失败 / 已锁定短路）仍是**零 INSERT、至多一行 UPDATE**。用例 35 断言短路、用例 42′ 断言冷却 |
| R-4 | `failed_login_count` 永不衰减 → 老账号被误锁 | 正常用户被莫名挡在门外 | 判据是**连续**失败：`note_successful_login` 清零；触发锁定时也清零（B-3 ③）。用例 7 覆盖「错 N-1 次 → 成功一次 → 再错 N-1 次」不锁 |
| R-5 | 用量派生口径 = 现存账号数，purge 后额度「退回」 | 额度语义与直觉不完全一致 | 明确写进 §1.1 A-2 与 `invite_uses` 的 docstring；purge 是需人工 `--apply` 的运维动作，非用户可触发 |
| R-6 | 并发注册可越过 `max_uses` | 额度轻微超发 | 承认并记录：判据在 commit 之前读，N 个并发请求最多超发 N-1 个。**不引入锁**——为一个软性配额加悲观锁，代价（SQLite 写锁争用）远大于收益。用例 22 断言单请求路径精确，并在 docstring 注明并发语义 |
| R-7 | `expires_at` 时区搞错 | 邀请码提前 8 小时失效 | 三道：后端拒绝过去时刻（400）、前端常驻显示 UTC 换算、前端提交前预拦 |
| R-8 | `schema_sync` 全等断言翻转 | 全套 pytest 红 | §7.1 点名 `tests/test_schema_sync.py:57`，并要求新列**追加在列表末尾** |
| R-9 | 审计端点的 N+1 | 50 行 → 100 次 `db.session.get` | `resolve_actors` 一次 `IN` 查询；用例 34 用 `SQLAlchemy` 事件计数断言「一页审计的 User 查询次数 ≤ 1」 |
| R-10 | 审计端点给了普通 admin | 绕过 root-only 的设置门禁 | `@require_root()`；用例 31 断言普通 admin 得 403 |
| R-11 | 新通知类型漏改前端镜像 | 通知铃铛渲染空白 | 三处镜像已是 `Record<NotificationType, …>`，漏改即 typecheck 失败；DoD 把 typecheck 列为门禁 |
| R-12 | `_clamped_config_int` 抽取改变 `passwords` 行为 | 口令策略静默漂移 | **【评审 P1-4 修正】**不是「逐字不变」的纯搬迁：warning 格式串把模块名 `"passwords: …"` 硬编在里面（`passwords.py:74-75`），共用之后会给 `login_guard` 打出指错模块的日志。抽取时加 `source` 形参，`passwords` 侧显式传 `"passwords"` 使其**输出**逐字节不变；`tests/test_password_policy.py` 的 16 条用例全部不改仍是回归证据 |
| R-16 | 用例被 IP 限流截胡而空转 | R-2 / R-3 的执行者是假的，风险表看起来有守卫、实际没有 | **【评审 P1-2 新增】**限流键为 `ip:username` 且 `LOGIN_MAX_ATTEMPTS=3`，同一用户名第 4 次请求起恒 429，用例 31/32/35/39 都够不到被测分支。四条用例必须在尝试之间显式调 `ratelimit.reset()`（`services/ratelimit.py:88`），见 §7.2 C 组的加粗前置条件 |
| R-13 | 侧栏改成依赖 `useAuth()` | 首屏 user 未就绪时导航闪烁 | `user` 为 undefined 时渲染 `NAV`（不含审计项），就绪后再补——宁可晚出现一项，不可先出现再消失 |
| R-14 | `datetime.fromisoformat` 在 Py<3.11 不吃 `Z` | 回填自己的值就 400 | 统一 `rstrip("Z")` 后解析；用例 20 用带 Z 的串走一次完整回环 |
| R-15 | 解锁端点被当成「重置口令」的替代 | 管理员以为解锁能救回忘密码的人 | 200 响应体不含任何口令字段；前端确认文案明确「不会改变密码」 |

---

## 7. 测试与验收标准

### 7.1 对既有用例的影响分析（**实施前必须按此逐条核对**）

v1 在这里对全部 44 个测试文件做了一次针对性扫描，结论是「会翻的只有一条」。
**评审复核后的结论是：会翻的有两条**，v1 漏掉的那条正好是 §1.1 A-4 的直接后果。
下表已按复核结果重写。

**会翻的，共两条（两条都必改）：**

| 文件:行 | 现状 | 为什么会翻 | 应改为 |
|---|---|---|---|
| `tests/test_schema_sync.py:57-58` | `assert applied == ["users.is_active", "users.is_root", "users.source", "users.must_change_password"]`（**全等**，断言跨 57–58 两行） | 本轮追加 3 列；`applied` 的顺序确由 `ADDITIVE_COLUMNS` 的列表顺序决定（`schema_sync.py:66-71`），故「追加在末尾」是必要条件 | 列表末尾追加 `"users.last_login_at", "users.failed_login_count", "users.locked_until"` |
| `tests/test_app_settings.py:26-28` | `assert app_settings.get_registration_settings() == {"enabled": True, "invite_code": "aragon", "default_role": "member"}`（**全等**） | **【评审 P0-1】**§1.1 A-4 的 `check_invite_code` 从这个函数读期限与额度 ⇒ 它必须扩到 5 键。v1 的 §2.4 写了「已核对」，但那次只核对了 HTTP **端点**的逐键断言，没看**服务层** | 补上 `"invite_expires_at": None, "invite_max_uses": 0`——全新库上的缺省即「永不过期、不限量」，与 §1.1 A-1 的缺省表一致 |

**核查过、确认不会翻的：**

| 文件:行 | 断言 | 为什么安全 |
|---|---|---|
| `tests/test_schema_sync.py:60-61` | `{"is_active", "is_root", "source", "must_change_password"} <= _columns(engine, "users")` | **【评审 P2-2】**这是**子集**断言（`<=`）而非集合全等，加列不会让它翻。v1 说「`:60` 也要补这三个名字」——补了无害（多一层护栏），但它**不是必改项**；不要因为它没红就以为自己改漏了什么 |
| `tests/test_registration.py:324-326` | `body == {enabled, invite_required, password_min_length, password_max_length, password_min_char_classes}`（全等） | §2.6 决定 `registration-meta` 一个字都不改 |
| `tests/test_registration.py:31` | `set(body) == {"token", "user"}` | 只约束**顶层**键集，不约束 `user` 子 dict；signup / login 的顶层形状不变 |
| `tests/test_settings.py:125` | `set(prefs.keys()) == set(NOTIFICATION_TYPES)` | 从常量派生，加类型时自动跟随。紧邻的 `:126` `all(prefs.values())` 也安全：`services/notification_prefs.py:20` 的「无行 = 开启」让新类型默认为 True |
| `tests/test_app_settings.py:61-63, :73-76, :87-89` | 逐键断言（`body["invite_code"] == ...`） | additive 键不影响逐键断言。`:63` 的 `updated_at is None and updated_by is None`（全新库无行）与 `:75` 的 `updated_by["id"] == root_admin`（码行与 `issued_at` 行恒由同一次请求、同一个 actor 写出）见 §2.4 的 P2-5 段 |
| `tests/test_schema_sync.py:77, :104` | `sync_additive_columns(...) == []`（幂等） | 幂等性不受列数影响 |
| `tests/test_auth.py:40-49`（`test_login_ratelimit_429`） | 连错 3 次各断言 **401**，第 4 次 429，第 5 次（正确口令）429 | **有条件安全，且条件就是 §1.2 B-2 的取值。**`LOGIN_LOCK_THRESHOLD=3` 时第 3 次失败**会触发锁定**，但响应体仍是 401（锁定检查排在口令校验之后，B-4），故逐字节不变；第 4、5 次由 IP 限流先行返回 429。副作用是用例结束时 `admin` 处于锁定态并留了一条审计，该用例不断言这些，无影响 |
| `tests/test_auth.py:52-60`（`test_login_success_clears_counter`） | 对 `pm` 连错 **2** 次 → 正确口令断言 **200** → 再错一次断言 401 | **【评审 P0-2】v1 把 `test_auth.py` 整体判成「无条件安全」是错的。**本条只在 `threshold > 2` 时安全：按 v1 的 `TestConfig` 取 2，该账号在第 2 次失败即被锁，第三次请求走到 B-4 第 4 步返回 **403**，用例红。改取 3 后 2 < 3，安全 |
| `tests/test_lifecycle.py:104-106` | 对已停用的 `member` 连续 5 次登录各断言 403 | 这 5 次走的是「口令正确 → 账号停用」分支（`routes/auth.py:57-58`），既不 `record_failure` 也不 `note_failed_login`，既不会 429 也不会被锁 |
| `tests/test_account_governance.py:348` | `[a.action for a in rows] == ["user_registered"]` | 本轮不在 signup 路径上增减任何 Activity |
| `tests/test_root_admin.py:154, :216, :226` | `User.query.count() == 1 / 0 / 0` | 走 `file_app` 的全新库，与本轮的新列 / 新键无关 |
| `tests/test_account_governance.py:358-359` | `[a.action for a in rows] == ["registration_updated"]`（对 `entity_type="app_setting"` 的 **全等**列表断言） | **有条件安全**——见下方 ⚠ |
| `tests/test_account_governance.py:371-372` | `len(...) == 2` 且 `X-Total-Count == "3"`（某成员的 3 次 `role_changed`） | 新增的两个 action 不在该用例的执行路径上 |

> ⚠ **`tests/test_account_governance.py:358` 是本轮唯一一个「取决于实现方式」的断言。**
> 它钉死了「改一次注册配置 = 恰好一条 `app_setting` 审计」。A-5 的
> `_upsert(KEY_INVITE_ISSUED_AT, ...)` 写的是一行 **AppSetting 数据**，
> 不是一条 Activity，因此按本文档实现它**不会翻**。
> 但如果实施时「顺手」给 `invite_issued_at` 的写入也补一条 `log_settings_event`，
> 这条用例会立刻变红——而那正是正确的反馈：`issued_at` 是
> `invite_code` 变更的**派生副作用**，不是一次独立的治理动作，
> 给它单独留痕会让审计流里出现两条描述同一件事的记录。
> **硬约定：`registration_updated` / `invite_code_rotated` 之外，本轮不新增任何
> `app_setting` action。**（§4.3 已如此规定，这里给出它的执行者。）
| `tests/test_rbac.py`、`tests/test_hardening_r3.py` | 用户 `to_dict` 的字段断言 | 全部是逐键断言。**评审已 grep 确认**：全仓库没有任何对用户 `to_dict()` 的整体全等断言；最接近的是 `test_account_governance.py:479-482` 的「两条建号路径互相比对（排除 volatile 键）」，它只在两条路径**发生分歧**时才红，而本轮不动那两条路径 |

**【评审已代跑】v1 留给实施节点的三条 grep，结果如下——不必再跑，但结论要照用：**

| grep | 结果 | 结论 |
|---|---|---|
| 用户 `to_dict()` / 响应体的全等或键集断言 | 全仓库仅 6 处 `set(...) ==` 型断言：`test_registration.py:31`、`test_search_documents.py:81`、`test_stats.py:30`、`test_settings.py:125`（另两处 `test_stats.py:36-37` 是 `>=` 子集）。**没有一处**是对用户 `to_dict()` 的整体全等 | 新增 3 个 additive 键安全 |
| `User.query.count(` / `len(r.get_json())` | `User.query.count()` 仅 3 处，全在 `test_root_admin.py`（`:154/:216/:226`）且都跑在 `file_app` 的全新库上；`len(r.get_json()) == N` 共 5 处，全部是工单 / 评论 / 文档列表 | 本轮不新增任何全局 fixture 用户，安全 |
| `REGISTRATION_KEYS` / `_stored_values` | 只有 3 个使用点：`app_settings.py:36`（定义）、`:67`（`_stored_values` 的 `IN` 查询）、`routes/settings.py:45`（`_registration_payload` 算 `latest` 用）。**测试里零引用** | 加 3 键只需改这两处消费点；`routes/settings.py:45` 的语义影响见 §2.4 的 P2-5 段 |

上一轮的 §12 I-2 就是栽在「静态扫描说只有 1 处，实际有 3 处」上——而本轮 v1 又在
`test_app_settings.py:26-28` 上栽了同一次（评审 P0-1）。这两次的共同根因是**只 grep 了
「端点被谁调用」，没 grep「这个函数的返回值被谁断言」**。所以判据重申一遍并加一条：

> 判据是「grep **该函数 / 该端点的所有断言**」，不是「grep 该端点的调用点」；
> 且**服务层函数与 HTTP 端点要分别 grep 一次**——同一份数据在两层有两套断言风格，
> 端点侧逐键、服务层全等，只看一层必然漏。

### 7.2 新增用例清单（**全部为实数**，逐条枚举共 **71** 条）

#### A. 邀请码生命周期（`test_invite_lifecycle.py`，21 条）

1. 无 `expires_at` / `max_uses` 行时，signup 行为与本轮之前逐字节相同（回归护栏）。
2. `expires_at` 设在未来 → signup 201。
3. `expires_at` 设在过去（直接写库，绕过路由校验）→ signup 403，`error == "invite code has expired"`。
4. `expires_at` 恰好等于 `utcnow()` → 403（判据是 `>=`，边界闭）。
5. `max_uses=0` → 注册 3 个人全部 201（0 = 不限）。
6. `max_uses=2` → 第 3 个人 403，`error == "invite code has reached its limit"`。
7. `max_uses=2` 且已有 2 个 `source="admin"` 用户 → 仍能注册 2 个（只数 signup）。
8. 额度用尽后 rotate → 用量归零，可再注册。
9. 额度用尽后把 `invite_code` **改成新值** → 用量归零。
10. 额度用尽后把 `invite_code` **原样再保存一次** → 用量**不**归零（A-3 的核心判据）。
11. 额度用尽后**换一个根管理员**把码原样保存 → 用量仍**不**归零（A-3 的 `updated_by_id` 陷阱）。
11′. **【评审 P1-1 新增，必须与 10、11 一起写】**在一个**从未改过邀请码**的库上
    （只 `PATCH {"max_uses": 2}`，`registration.invite_issued_at` 行因此由
    `_ensure_invite_anchor` 补出）注册满额 → **换一个根管理员**把码原样保存 →
    用量**不**归零。这条是 A-5 两步修法的唯一执行者：只做「显式键」不做「值判等短路」，
    或只做短路不补锚点，本条都会红。**必须先写、先看它在 v1 的写法上红**——
    v1 的写法在这条路径上会让 `_upsert` 弄脏码行、`onupdate` 前移 `updated_at`、
    额度静默归零，而用例 10 / 11 因为「码已经被改过、显式键已存在」恰好盖不住它。
12. 码错 + 已过期 → reason 为 `mismatch`（顺序判据，不泄露过期事实）。
13. 码错 + 已用尽 → reason 为 `mismatch`。
14. `verify_invite_code` 别名与 `check_invite_code(...).ok` 恒等（稳定 API 护栏）。
15. 中文邀请码 + 中文候选 → 不 500（上一轮 F-1 的回归护栏，**必须保留**）。
16. `PATCH {"expires_at": "<过去>"}` → 400，`detail.field == "expires_at"`。
17. `PATCH {"expires_at": ""}` → 200 且清除。
18. `PATCH {"max_uses": -1}` / `{"max_uses": 10001}` / `{"max_uses": "x"}` → 400。
19. `PATCH {"max_uses": 5}`（**整数字面量**）→ 200（§2.5 的 `want_int` 前提）。
20. `expires_at` 带 `Z` 提交 → 200，回读一致（R-14 的回环）。

#### B. 邀请码用量与状态下发（`test_invite_lifecycle.py` 续，6 条）

21. `GET /settings/registration` 含全部 5 个 additive 键，且既有 6 键逐字不变。
22. `invite_uses` 随注册单调递增（单请求路径精确）。
23. `invite_status` 在开关关闭时为 `disabled`（优先级最高）。
24. `invite_status` 在过期时为 `expired`、用尽时为 `exhausted`。
25. `invite_issued_at` 三级回落：无行 → 用码行 `updated_at`；无码行 → `None` 且用量 = 全部 signup 数。
26. 非根管理员读 `GET /settings/registration` → 403（既有守卫未被本轮削弱）。

#### C. 登录锁定（`test_login_guard.py`，23 条）

> **【评审 P1-2】本组的前置条件，不写清楚半数用例是空转的。**
> 限流键是 `ip:username`（`routes/auth.py:44`）、`TestConfig.LOGIN_MAX_ATTEMPTS = 3`
> （`config.py:179`），所以**同一个用户名的第 4 次登录请求起恒 429**，压根走不到
> `note_failed_login` 与 B-4 的第 4 步。v1 的用例 31 / 32 / 35 / 39 全部落在第 4 次之后：
> 它们会「通过」，但通过的原因是 429，断言恒真、零信息——R-2 与 R-3 两条风险的
> 执行者因此是**假的**。
>
> 处置：这四条用例在跨过第 3 次请求之前必须显式复位 IP 桶：
>
> ```python
> from services import ratelimit
> ratelimit.reset()          # services/ratelimit.py:88；conftest.py:132 已有同名 autouse fixture 作先例
> ```
>
> 复位的是**内存限流**，账号侧的 `failed_login_count` / `locked_until` 落在库里不受影响——
> 这正是本轮引入账号级锁定的理由，用例里也要把这层区分体现出来。
> 凡是需要「超过 3 次尝试」的断言，一律 `reset()` 后继续，或改为直接驱动
> `login_guard.note_failed_login()` 的纯函数用例。

27. `lock_policy()` 钳位：`threshold=0` → 3；`=999` → 100；`minutes=0` → 1；`=99999` → 1440；
    `notify_cooldown=-1` → 0；`=99999` → 10080。
28. `lock_policy()` 脏值（`"abc"`）→ 回落默认 + 有 warning，**且 warning 前缀是 `login_guard`
    而不是 `passwords`**（评审 P1-4 的执行者：抽 `config_knobs` 时若忘了传 `source`，本条红）。
29. 连错 `threshold-1` 次 → 未锁定，`failed_login_count == threshold-1`。
30. 第 `threshold` 次错 → 仍返回 **401**（不是 403），但 `locked_until` 已被置。
31. **`ratelimit.reset()` 之后**用**正确**口令登录 → 403，`error == "account is temporarily locked"`。
    （不 reset 就是 429，测不到本分支——评审 P1-2。）
32. 该 403 的 `detail.retry_after_seconds` ∈ `(0, minutes*60]`。
33. **`ratelimit.reset()` 之后**用**错误**口令登录 → **401**（R-1：与不存在用户逐字节相同）。
34. 用例 33 的响应体与「登录一个根本不存在的用户名」的响应体逐字节相同。
    （两者用户名不同 ⇒ 限流键不同，这一条本身不受 IP 桶影响。）
35. 锁定期内**每次 `ratelimit.reset()` 后**再打 5 次 → `activities` 行数不增、
    `failed_login_count` 不变（R-3 的写放大短路）。**不 reset 则第 4 次起恒 429，
    断言恒真而毫无证明力**——这正是评审 P1-2 点名的空转用例。
36. `locked_until` 手工改到过去 → 正确口令登录 200（自然到期，无需任何后台任务）。
37. 错 `threshold-1` 次 → 成功一次 → 再错 `threshold-1` 次 → **未锁定**（R-4）。
38. 成功登录写 `last_login_at`，且 `failed_login_count` 归零、`locked_until` 置 None。
39. 根管理员连错 20 次（**每次 `ratelimit.reset()`**）→ `locked_until is None` 且
    `failed_login_count == 0`（R-2）。**不 reset 则只有前 3 次真正落到
    `note_failed_login`，剩下 17 次是 429，用例变成一句空话**（评审 P1-2）。
40. 根管理员连错到超过 IP 阈值（**不 reset**）→ 仍会 429（IP 限流对它照常生效）。
    本条与 39 是有意配对的一正一反，两条都要有。
41. 触发锁定时写且**只写一条** `account_locked` 审计，`actor_type == "system"`。
42. 触发锁定时向全部有效管理员各发一条 `account_locked` 通知；停用的 admin 不收。
42′. **【评审 P1-3 新增】通知冷却**：同一账号解锁（或 `locked_until` 手工改到过去）后
    **再次**被锁 → `activities` 的 `account_locked` **+1**，而 `notifications` 的
    `account_locked` **+0**（默认 24h 冷却内）。再把
    `LOGIN_LOCK_NOTIFY_COOLDOWN_MINUTES` 置 0 重跑 → 两者都 +1（冷却可关）。
    没有这条，R-3 的通知放大上界就只是文档里的一句话。
43. 被锁的人自己是 admin 时**也收到**那条通知（actor 为 system，「不给自己发」不触发）。
44. 已停用账号连错 → 仍走 401 分支（停用检查在锁定之后，顺序不变）。
45. `POST /users/<id>/unlock` 由 admin 调 → 200 `unlocked: true`，`locked_until is None`，写一条 `account_unlocked`。
46. 对未锁定账号调 unlock → 200 `unlocked: false`，**不写审计**。
47. 对根管理员调 unlock → 200 `unlocked: false`（结构上不可能被锁，无 409 分支）。
48. 非 admin 调 unlock → 403；不存在的 id → 404。

#### D. 用户序列化与筛选（`test_login_guard.py` 续，5 条）

49. `to_dict()` 含 `last_login_at` / `locked_until` / `is_locked`，**不含** `failed_login_count`。
50. `summary()` 一个新键都没加（既有约定护栏）。
51. `is_locked` 由服务端判定：`locked_until` 在过去时为 `false` 且 `locked_until` 回传 `null`。
52. `GET /users?locked=true` 只返回锁定账号；`=false` 只返回未锁定（含 `locked_until is NULL`）。
53. `GET /users?locked=ture` → 400（既有 `want_query_bool` 契约）。

#### E. 站点治理审计（`test_account_governance.py` 追加，11 条）

54. `GET /settings/audit` 由根管理员调 → 200，裸数组 + `X-Total-Count`。
55. 普通 admin 调 → 403（R-10）。
56. 默认返回 `user` **与** `app_setting` 两类事件（本轮修的那个「只写不可读」缺陷）。
57. `?entity_type=app_setting` → 只剩设置事件，且能读到 `invite_code_rotated`。
58. `?action=role_changed` → 只剩该动作；`?action=不存在的动作` → 400。
59. `?actor_id=<某 admin>` → 只剩他做的；`?since=<ISO>` → 只剩之后的。
60. `?since=乱码` → **400**（不是 500），`detail.field == "since"` 且
    `detail.expected == "ISO 8601 datetime"`。**【评审 P0-3】这条必须先写、先看它红**：
    v1 的 `QueryParamError(field=..., expected=...)` 缺必填的 `got` 位置参数，
    实例化即 `TypeError` → 被全局兜底渲染成 **500**。红→绿的这一跳才是
    `want_query_datetime` 存在的证据。
60′. `?since=` 带尾部 `Z`（例如把上一次响应里的 `created_at` 原样贴回来）→ 200 且过滤生效
    （`want_query_datetime` 的 `Z` 容忍；不做这一步就是「界面显示的值提交回来就 400」）。
61. 每行含 `actor` / `target` 解析块；`app_setting` 行的 `target` 为 `null`；system 行的 `actor` 为 `null`。
62. 施动者被删后仍能渲染（`actor` 降级为 `null`，不抛）。
63. 一页 50 行审计对 `users` 表的查询次数 ≤ 1（R-9 的 N+1 护栏）。

#### F. 溢出必修的回归护栏（分散在既有文件，5 条）

64. `GET /api/stats` 的最近动态里**不含** `account_locked` / `account_unlocked`
    （`routes/stats.py` 的 `TICKET_ENTITY_TYPES` 过滤仍然生效）。
65. `tools/purge_demo_data.py` 的 `--dry-run` 在有锁定审计的库上仍然零写入。
66. `purge_demo_data` 把一个带 `account_locked` 审计的 signup 账号识别为「被治理过」。
67. `schema_sync` 双向漂移守卫：`ADDITIVE_COLUMNS` 与 `models/user.py` 的列集合互为子集。
68. 全新库启动一次 → `sync_additive_columns` 返回 `[]`（新列由 `create_all` 建出）。

> **计数（评审 P2-8 重算）**：v1 的章节标题写 62、各组小计写 20/6/21/5/10/5、
> 而实际枚举是 68——三个数字互不相等，其中 C 组标题的「21 条」对应的是 27～48 共 **22** 条。
> 评审新增 4 条（11′、42′、60′，以及 27 / 28 各自扩了断言但不单独计数），
> 各组小计已逐一改正为 **21 / 6 / 23 / 5 / 11 / 5**，合计 **71**。
> **以枚举为准**（上一轮的 I-5 记录过同一种偏差：标题写 56、枚举 61、实收 68）。
> DoD 的下限按 **742 + 71 = 813** 计。

### 7.3 手工验收清单（实施节点必须逐条按下去，截图或口述结果）

1. 全新库启动 → `/register` 用默认码 `aragon` 注册成功。
2. 根管理员在设置页把名额上限设为 1 → 再注册一个 → 界面提示「邀请码名额已用尽」。
3. 点「重新生成」→ 确认框里明确写着额度会归零 → 确认后用量条回到 0/1。
4. 有效期设为「昨天」→ 前端就地报错，提交按钮不可用。
5. 有效期设为「一小时后」→ 保存成功 → 输入框旁显示对应的 UTC 时刻。
6. 用错口令连打到阈值 → 第 N 次仍显示「用户名或密码错误」（不是「已锁定」）。
7. 用**正确**口令登录 → 显示「已临时锁定，请在 X 分钟后重试」，X 是个正整数。
8. 管理员在团队页看到该行的「已锁定」徽章与「解锁」按钮 → 点解锁 → 徽章消失。
9. 被解锁的人立刻用正确口令登录成功；团队页的「最后登录」显示「刚刚」。
10. 根管理员侧栏出现「审计」；用一个普通 admin 登录 → 侧栏**没有**该项。
11. 普通 admin 手动访问 `/audit` → 看到「仅根管理员可见」的空态，**不跳转**。
12. 审计页能看到刚才那条「账号被锁定」（施动者显示「系统」）与「重新生成了邀请码」。
13. 按动作筛选「账号被锁定」→ 只剩那一条；清空筛选恢复。
14. 把 `PASSWORD_MIN_LENGTH=12` 后重启 → 注册页仍按 12 位拦截（上一轮护栏未被本轮破坏）。
15. 移动端宽度（375px）下团队页与审计页无横向溢出。
16. **【评审补】**在审计页把「起始时间」设成刚才那条锁定记录的时刻**再往前一秒**
    → 该条仍在；往后一秒 → 该条消失。这一条同时验证 `want_query_datetime` 的
    `Z` 容忍（界面回填的值带 `Z`）与过滤边界，是 P0-3 的手工对照组。
17. **【评审补】**把同一个账号解锁后再打一遍到锁定 → 管理员通知铃铛**不**出现第二条
    「账号被锁定」，而审计页**多**出一条。这是 P1-3 冷却机制唯一的肉眼判据。

> **默认配置下这份清单是走得通的**（评审核算）：生产默认 `LOGIN_MAX_ATTEMPTS=10`、
> `LOGIN_LOCK_THRESHOLD=8`，8 < 10 ⇒ 第 8 次失败触发锁定时 IP 桶尚未满，
> 第 9 次带正确口令的请求能走到 403 而不是 429。第 6、7 条因此可手工复现。
> **这个「阈值必须小于 IP 上限」的关系是隐式的**——把 `LOGIN_LOCK_THRESHOLD` 调到
> 10 以上会让账号锁定在默认部署下**永远不可能触发**（IP 限流先把请求挡光）。
> 这条关系必须写进 README 的配置表，见 §3.5。

### 7.4 Definition of Done

- `cd backend && python -m pytest -q` → **零失败**，用例总数 **≥ 813**。
  813 = 实测基线 742（评审节点复跑确认仍是 742 / 44，收集零错误）+ 枚举 71。
  **实施前仍必须按 CLAUDE.md 重新采一次 `pytest -q --collect-only`，以那一次为准**
  （本仓库每一个被写下来的数字都在一两轮内过期；742 这个数已经过了两道核对，
  但它随时可能因为别的分支而变）。
- **两条既有断言必须被显式改掉**（§7.1）：`tests/test_schema_sync.py:57-58` 与
  `tests/test_app_settings.py:26-28`。「零失败」若是靠删用例或放宽断言换来的，本轮不算完成。
- `cd frontend && npm run typecheck` 零错误；`npm run build` 成功且产出 `/audit` 路由。
- `git status` 干净（无 `.next/`、无临时文件），提交用 `git add <显式路径>`，
  **禁止 `git add -A/.`**。
- README 与 `docs/iterations.md` 已更新。
- §7.3 的 15 条手工清单全部通过。

---

## 8. 建议实施顺序（每步可独立提交、可回滚）

0. **先采基线**：`pytest -q --collect-only`，记下真实数字。**不要相信本文档里的 742。**
1. **抽取 `config_knobs.py`**（带 `source` 形参，评审 P1-4）+ 让 `passwords.py` 改调、
   显式传 `source="passwords"`。跑一次全量 `pytest -q`——`test_password_policy.py`
   的 16 条全绿即证明**外部行为**纯搬迁。
   这一步先做，是因为它是本轮唯一一个「改既有模块但不该有任何行为变化」的动作，
   混在后面做就再也分不清是它出的问题还是新功能出的问题。
2. **加列**：`models/user.py` 三列 + `schema_sync` 三条（**追加在末尾**）
   + 改 `tests/test_schema_sync.py:57` 与 `:60` + 用例 67、68。
   独立提交，因为它是唯一一个会让**存量库**发生结构变化的动作。
3. **`login_guard.py` + 用例 27、28**（策略钳位）。纯函数，零 IO，先把地基钉死。
4. **`login` 重排 + 用例 29～44 + 42′**。
   **34 条（锁定 + 错口令 ≡ 不存在的用户）必须先写、先看它红**——
   R-1 那个用户枚举预言机只有在「顺序写反」的版本上才会露出来，
   补丁后的绿色本身不构成证据。
   本步开始前先把 `TestConfig.LOGIN_LOCK_THRESHOLD` 定成 **3**（评审 P0-2），
   然后**立刻**单独跑一次 `pytest -q tests/test_auth.py`——它是本轮受影响最直接的
   既有文件，`:52-60` 在阈值取 2 时会红、取 3 时绿，这一次单跑就是那条推导的实测证据。
   本组用例凡跨过第 3 次登录请求的，一律先 `ratelimit.reset()`（评审 P1-2）。
5. **unlock 端点 + 筛选 + 序列化**（用例 45～53）。
6. **邀请码生命周期**（`app_settings.py` + 路由 + 用例 1～26，含 11′）。
   **10、11、11′ 三条要一起写**：它们是 A-3 / A-5「为什么既要值判等短路、又要补锚点」的
   唯一执行者，缺一条那段论证就只是文档里的一句话。**11′ 尤其要先写、先看它在 v1 的
   写法上红**（评审 P1-1）——10 与 11 在「码已经被改过」的前提下会双双变绿，
   把「从未改过码的库」这条最常见的路径完全盖住。
   本步同时改 `tests/test_app_settings.py:26-28`（评审 P0-1）——它与扩键是同一个动作，
   不得拆到别的提交里，否则中间态是一个必红的仓库。
7. **审计出口**（`scope.py::want_query_datetime` + `audit.py` + `GET /settings/audit`
   + 用例 54～63、60′）。**先加 `want_query_datetime` 再写路由**：v1 假设查询串侧已经
   有 datetime 原语，实际没有（评审 P0-3），先写路由会直接撞上 `QueryParamError` 的
   三参签名。63 条（N+1 护栏）用 SQLAlchemy 的 `before_cursor_execute` 事件计数，
   不要用「跑得快不快」这种不可复现的判据。
8. **溢出必修 + 用例 64～66**（stats 不泄露、purge 不误伤）。**与第 7 步同一提交**，
   拆开就会有一个只跑了一半的中间态。
9. **前端**：`lib/format.ts`（并同步收口 `MemberActivityModal` 与 `NotificationBell`
   两处 `relTime` 副本，评审 P1-5）→ types → constants → hooks → 组件 → 页面 → 侧栏。
   每一层跑一次 `npm run typecheck`——三处通知镜像与两处审计动作镜像的
   编译错误就是最好的 checklist。
   `format.ts` 排在最前，是因为它是唯一一个**删既有代码**的动作：先做完再加新消费者，
   就不会出现「一个公共件 + 三份副本」的中间态。
10. **文档**：README + `docs/iterations.md`。

---

## 9. 明确的非目标

- **邮件**：找回口令、发送邀请、锁定告警邮件。没有 SMTP 配置、没有队列、没有重试，
  加进来就是一个会在生产环境静默失败的组件。管理员解锁 + 一次性口令已经覆盖恢复路径。
- **TOTP / 二次验证**：要一个设备绑定流程与恢复码体系，是独立一轮。
- **注册审批队列**：上一轮已论证——`pending` 状态会与 `is_active` /
  `must_change_password` 交叉出一个没人说得清的状态机。要做就先合并状态维度。
- **口令历史 / 禁止复用最近 N 个**：需要新表 + 保留策略，且对本产品威胁模型收益有限。
- **口令过期（90 天强制轮换）**：NIST SP 800-63B 明确反对无诱因的定期轮换。
- **分布式限流**：`services/ratelimit.py` 仍是单进程内存实现
  （`TODO(ratelimit-distributed)` 留在原处）。本轮的账号锁定是**落库**的，
  因此恰恰补上了内存限流在多 worker 下最要命的那个缺口——但它替代不了限流本身。
- **会话/令牌管理面**：「查看我的所有登录设备」「踢掉某个会话」需要令牌存储，
  与当前无状态 JWT 的取向冲突。停用（`is_active`）经 blocklist loader
  （`errors.py:101`）已经能立即吊销一个人的全部令牌，这是本轮的可用替代。
- **审计导出（CSV / JSON 下载）**：先让它可读、可筛选；导出是下一轮的候选。
- **RBAC 重构 / 多级管理员**：`is_root` 仍是唯一的治理锚点。

---

## 10. 附录：本轮不可违反的既有约束（违反即返工）

1. **状态机神圣**：工单状态只走 `services/workflow.py`。本轮不碰工单。
2. **加列即登记**：`models/` 每新增一列，`ADDITIVE_COLUMNS` 必须同步（本轮 3 条）。
3. **五处 bootstrap 关闭点**：`TestConfig`、`tests/conftest.py::file_app`、三个
   `tools/*.py`。本轮不新增 CLI，故清单仍为五处；若新增任何 fixture 或工具，必须补第六处。
4. **seed 一行一登记**：本轮不动 `backend/seed.py`。
5. **`comments` / `activities` / `notifications` 永不按数量清理**——
   这正是 §1.2 B-3「绝不为每次失败登录写 Activity」的根据。
6. **错误串是对外契约**：`invalid username or password`、
   `account is disabled, contact an administrator`、`invalid invite code`、
   `username already exists`、`password change required`、`conflict_root_admin`
   的错误串一个字都不许动。本轮新增的三个串
   （`account is temporarily locked`、`invite code has expired`、
   `invite code has reached its limit`）从落地那一刻起也进入这份清单。
7. **前端通知镜像四处**：新增通知类型必须同步 `lib/types.ts` 的联合类型与
   `NOTIFICATION_TYPE_LIST`、`lib/constants.ts` 的两个 `Record<NotificationType, …>` map。
8. **审计 message 绝不含凭据**：不写口令、不写口令哈希、不写邀请码明文。
   本轮的 `account_locked` message 里写次数与分钟数是安全的；
   写「他试的是什么口令」不是。
9. **`summary()` 不加治理字段**：这是第三次重申（`models/user.py:66` 与 `:71` 各一次）。
10. **`registration-meta` 是公开端点**：本轮不往里加任何一个新键（§2.6）。

---

## 附：写作时逐条核对过的 15 条「as-built 事实」

供评审节点交叉验证，每条都带行号，可直接打开对照。

| # | 事实 | 出处 |
|---|---|---|
| F-1 | `login` 全程不写库，成功与失败都不留痕 | `routes/auth.py:31-61` |
| F-2 | 限流键为 `ip:username`，纯内存、重启即清空 | `routes/auth.py:44`、`services/ratelimit.py:1-13` |
| F-3 | `verify_invite_code` 只做定长比较，无期限 / 额度 | `services/app_settings.py:208-221` |
| F-4 | `app_setting` 审计**只写不可读**：`user_timeline` 写死 `entity_type=user` | `services/audit.py:66-79` vs `:91-92` |
| F-5 | `stats` 已被收紧到 `TICKET_ENTITY_TYPES`，治理事件不会漏进仪表盘 | `models/activity.py:11`、`routes/stats.py` |
| F-6 | 停用经 blocklist loader 立即吊销既有令牌；**改口令不吊销** | `errors.py:101-118`、`routes/me.py:140` |
| F-7 | `_reject_root_mutation` 的口令分支挂在 `data.get("password")` 上，不得被空 body 端点复用 | `routes/users.py:99-106`、`:123` |
| F-8 | `reset_password` 的判定顺序 404 → 409 → 读 body → 400 是契约 | `routes/users.py:234` |
| F-9 | 口令闸门豁免集恰好 6 条，`OPTIONS` 第一顺位 | `services/auth_helpers.py:26-33`、`:143` |
| F-10 | `ADDITIVE_COLUMNS` 现有 7 条，`users` 表占 4 条 | `services/schema_sync.py:19-35` |
| F-11 | `test_schema_sync.py:57` 是**全等**断言，加列必翻 | `tests/test_schema_sync.py:57` |
| F-12 | `registration-meta` 的响应体在 `tests/test_registration.py:324` 被**全等**钉死 | `tests/test_registration.py:324` |
| F-13 | `utcnow()` 返回 naive UTC；`to_dict` 输出补 `Z` | `extensions.py:80-86`、`models/user.py:92` |
| F-14 | 前端 `USER_ACTIVITY_LABELS` / `ICONS` 已是 `Record<UserActivityAction, string>` | `lib/constants.ts:337`、`:347` |
| F-15 | `NOTIFICATION_TYPE_LIST` 是联合类型的运行时镜像，三者合起来让漏改成为编译错误 | `lib/types.ts:259`、`:277` |

**评审复核结果：F-1 ～ F-15 逐条打开核对，15 条全部属实**（F-7 的行号略有偏移——
`_reject_root_mutation` 定义在 `:96`、docstring 在 `:99-106`、口令分支在 `:123`，
不影响结论）。评审另行补 5 条 v1 没有记录、但本轮实施必须知道的 as-built 事实：

| # | 事实 | 出处 |
|---|---|---|
| F-16 | 查询串原语只有 `want_query_int` / `str` / `bool` 三个，**没有 datetime**；且 `QueryParamError.__init__(field, got, expected)` 是三个**位置**必填参数 | `services/scope.py:40`、`:78`、`:109`、`:29` |
| F-17 | `get_registration_settings()` 的返回值被 `tests/test_app_settings.py:26-28` **全等**钉死（服务层，不是端点） | `tests/test_app_settings.py:26-28` |
| F-18 | `TestConfig.LOGIN_MAX_ATTEMPTS = 3`；`is_blocked` 的判据是 `len >= max`，故同一 `ip:username` 的**第 4 次**请求才 429 | `config.py:179`、`services/ratelimit.py:70-72` |
| F-19 | `_clamped_config_int` 把模块名 `"passwords: …"` 硬编在 warning 格式串里 | `services/passwords.py:74-75` |
| F-20 | `frontend/lib/format.ts` **不存在**；`relTime()` 有两份逐字相同的副本 | `components/admin/MemberActivityModal.tsx:29`、`components/notifications/NotificationBell.tsx:15` |
| F-21 | `ADMIN_VIEW_PREFIXES` 无 `export`（模块私有）；`api.ts` 的 `*_KEY` 不变量禁止分页 / 带筛选视图复用 | `lib/swr-keys.ts:24`、`lib/api.ts:19-24` |
| F-22 | `(app)` 路由组内**没有任何**页面级「无权限」先例；既有惯例是整块隐藏或禁用 + title | `app/(app)/layout.tsx:15-34`、`settings/page.tsx:57`、`team/page.tsx:300-320` |

---

## 评审结论（Review Verdict）

### **有条件通过（Approved with Conditions）**

本设计在**技术判断**上是扎实的：判定顺序（mismatch → expired → exhausted）、锁定检查
排在口令校验之后、用量派生而非计数器、绝不为每次失败登录写 Activity、
`registration-meta` 一个字都不加、以及「先读了 `ProgressBar` 再决定不新建原语」——
这几条评审逐一核对过源码，都是对的，而且论证给到了「为什么反过来做会出事」的层次。
本轮的三个支柱也确实各自对应一个**已被证实存在**的缺陷（F-1 / F-3 / F-4），
不是为了凑一轮而发明的需求。

问题集中在**核对的彻底性**，不在设计本身：3 个 P0 里有 2 个是「影响分析漏了一条会翻的
断言」——与上一轮 §12 I-2 同源，而 v1 在 §7.1 里还专门引用了那次教训。
这说明「引用教训」和「按教训重新扫一遍」是两件事。前端的四条「既有件」断言里
有三条与仓库现状不符（P1-5 / P1-6 / P1-7），根因相同。

全部 **3 个 P0 与 8 个 P1 已在正文中改掉**，文档升为 v2。放行条件如下——
它们全部是**机器可判定**的，实施节点必须逐条给出证据，不接受「已按文档实现」这种口头结论：

| # | 放行条件 | 判定方式 |
|---|---|---|
| 1 | 用例 11′ 在 v1 的 A-5 写法上**红**、在 v2 的两步写法上**绿** | 先按 v1 写法跑一次贴出红色输出，再切到 v2 贴绿色。只有绿色不算证据——P1-1 的整段论证就靠这一跳 |
| 2 | `tests/test_auth.py` 单跑：`LOGIN_LOCK_THRESHOLD=2` 时 `:52-60` **红**，`=3` 时**绿** | 两次 `pytest -q tests/test_auth.py` 的输出。这是 P0-2 的实测证据，不是推导 |
| 3 | 用例 60（`?since=乱码`）在 v1 的 `QueryParamError(field=…, expected=…)` 写法上返回 **500**、在 `want_query_datetime` 落地后返回 **400** | 两次响应的状态码。P0-3 的红→绿 |
| 4 | `tests/test_app_settings.py:26-28` 与 `tests/test_schema_sync.py:57-58` **两条都被显式改过**，且 `git diff` 里看得到 | `git diff` 片段。零失败若靠删用例或放宽断言换来，本轮不算完成 |
| 5 | 用例 31 / 32 / 35 / 39 里能看到 `ratelimit.reset()` 的调用 | `grep -n "ratelimit.reset" backend/tests/test_login_guard.py` 至少 4 处。P1-2 的执行者 |
| 6 | 用例 42′ 证明冷却生效：同一账号二次锁定 → `activities` +1、`notifications` +0 | 用例输出。P1-3 的执行者 |
| 7 | `grep -rn "relTime" frontend/` 只在 `lib/format.ts` 里有定义，`MemberActivityModal` 与 `NotificationBell` 各只剩一行 import | grep 结果。P1-5 的执行者 |
| 8 | 既有门禁：`pytest -q` 零失败且总数 ≥ **实施前当场重采的基线 + 71**；`npm run typecheck` 零错误；`npm run build` 成功且产出 `/audit` 路由 | 三条命令的原始输出。**不要相信本文档里的 742**，实施前当场重采 |

### 遗留的、**有意不在本轮解决**的两件事（记录，不阻塞放行）

1. **`activities` 的锁定行没有上界。** 通知加了冷却，审计没有（§1.2 B-3 的论证：
   压掉它等于让审计控制台显示一个比真相温和的攻击画像）。理论上界约 1 920 行/天，
   被认账。真正的解法是给 `activities` 一套按时间的归档策略，那与 CLAUDE.md
   「永不按数量清理」的现有约定正面冲突，需要单独一轮来谈，不能夹带。
2. **`last_login_at` / `is_locked` 对全体成员可见**（P2-7）。在 20 人的内部工具里可以接受；
   如果本产品将来面向跨组织租户，这两个键是第一批该被降到 admin-only 的字段。
   本轮不改，是因为改它意味着 `GET /api/users` 要按角色返回不同形状——
   那是一个比本轮大得多的契约变更。

### 一条给下一轮的建议

本轮之后，「谁能进来 / 进来过 / 还能进来多久」这条线基本闭合。真正还敞着的是
**`services/ratelimit.py` 仍是单进程内存实现**——本轮的账号锁定补上了它在多 worker 下
最要命的缺口，但没有替代它。一旦本产品真的按 `ops/` 模板上多 worker 部署，
IP 限流就退化成「每个 worker 各拦各的」。那应该是下一轮的第一顺位，
而不是审计导出或 TOTP。
