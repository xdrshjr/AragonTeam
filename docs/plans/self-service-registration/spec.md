# AragonTeam 自助注册与根管理员治理（Self-Service Registration）Spec

> **文档版本：v2**（2026-07-21 设计评审后修订；v1 为初稿）
> 本轮把「谁能进这个系统」从**只有管理员能造人**，变成**凭邀请码自助注册 + 根管理员可配置 + 管理员可治理**。
> 目标读者：下游实现工程师。本文档的详细程度以「照着写、不需要再做任何设计决策」为准。
> v2 相对 v1 的全部改动都可在 §0 评审记录里逐条追溯；正文中被修订的段落均带 `【v2】` 标记。

---

## 0. 评审记录（Review Notes）

评审人：Anthropic 工程团队资深评审。评审维度：**可行性 / 完备性 / 一致性 / 规模适配**。
下列结论全部经过**读码核对**（引用到具体 `文件:行`），不是纸面推演。
P0 = 会让应用起不来或让存量用例成批变红；P1 = 会造成安全 / 数据 / 契约层面的真实事故；P2 = 应当修正但不阻塞。

**P0 与 P1 已在 v2 正文中逐条修复，无遗留。**

### P0

| # | 维度 | 问题 | 证据 | v2 处置 |
|---|---|---|---|---|
| **P0-1** | 可行性 | **循环导入，应用整体起不来。** v1 §2.2 B-2 要求 `routes/auth.py::signup` 复用 `routes/users.py::_want_email`，但 `routes/users.py:11` 已经 `from routes.auth import _pick_color`。`routes/__init__.py:2` 先导入 `routes.auth`；auth 执行到顶部 import 时回头拉 users，users 又回头拉 auth 中**定义在文件末尾**（`routes/auth.py:91`）的 `_pick_color` —— 此时 auth 只执行到第 12 行，必抛 `ImportError: cannot import name '_pick_color' from partially initialized module`。同一个问题的镜像版本出现在 §2.1 A-3：`services/bootstrap.py` 要调 `_pick_color`，那是 service→route 的反向依赖。 | `routes/users.py:11`、`routes/auth.py:91`、`routes/__init__.py:2` | 两个共享工具**下沉到服务层**：新增 `services/avatars.py::pick_color`（`routes/auth.py`、`routes/users.py`、`seed.py`、`services/bootstrap.py` 四个调用点统一改读，顺带消灭 `seed.py:27` 那份 `_COLORS` 复制），邮箱校验下沉为 `services/validation.py::want_email`。见 §2.1 A-3、§2.2 B-2 第 2/7 步、§3.1 / §3.2。 |
| **P0-2** | 一致性 | **只关 `TestConfig` 挡不住 bootstrap，且会写脏 CLI 工具的目标库。** v1 §2.1 A-1 断言「全套存量用例的 app fixture 都走 `create_app(TestConfig)`」——**不成立**。`tests/conftest.py:103` 的 `file_app` fixture 是 `type("FileConfig", (Config,), attrs)`，基类是 `Config`，`ROOT_ADMIN_BOOTSTRAP` 恒为 True。后果是可复现的成批失败：`tests/test_purge_demo_data.py:150` 先 `make(seed=False)` 建空库（bootstrap 就地建出 `admin` 行），随后 `_install_legacy_principals()` 再插一个 `username="admin"` → 撞 `users.username` 唯一索引 → 该文件 **15 条用例集体炸**。同一个根因还有第二张脸：`tools/purge_demo_data.py:629`、`tools/purge_trash.py:170`、`tools/gc_orphan_blobs.py:185` 三个 CLI 都以 `Config` 为基类建 app，于是**三个只读 / 清理型工具会在目标库里凭空写出一个用户行**——`purge_demo_data` 的模块开篇第一原则就是「dry-run 绝不写库」，这直接违背它。 | `tests/conftest.py:103`、`tests/test_purge_demo_data.py:150`、`tools/purge_demo_data.py:629`、`tools/purge_trash.py:170`、`tools/gc_orphan_blobs.py:185` | 关 bootstrap 的地方由 1 处扩到 5 处：`TestConfig` + `file_app` 默认值 + 三个 CLI 的 config 子类与环境变量。`file_app` 保留 `**overrides` 通道，供 §8.2 用例 26 显式打开。见 §2.1 A-1、§2.1 A-3「关闭清单」、§3.2。 |

### P1

| # | 维度 | 问题 | 证据 | v2 处置 |
|---|---|---|---|---|
| **P1-1** | 完备性 | **限流键 `request.remote_addr` 在本项目的实际部署形态下退化成全局单桶。** 本仓库自带 nginx 反代模板（`ops/templates/aragonteam-nginx-http`，`ops/config.env` 已填 `NGINX_DOMAIN`），而后端**没有** `ProxyFix`（全仓库 grep 只在 `.venv` 里命中）。于是线上每个请求的 `remote_addr` 恒为 `127.0.0.1`：`SIGNUP_MAX_ATTEMPTS=10` 变成「整个站点 5 分钟内一共只能尝试 10 次注册」，一个人手滑三次就把全公司挡在门外；对真攻击者反而毫无作用（他就是那唯一的桶）。既有 `/login` 因为键是 `ip:username` 而侥幸没暴露这个问题，signup 只按 IP 建键，把它暴露成了产品级故障。 | `ops/templates/`、`backend/routes/auth.py:25-29`、无 `ProxyFix` | 新增 `services/ratelimit.py::client_ip()` + `TRUST_PROXY_COUNT` 配置（默认 0 = 不信任任何转发头，保持今天行为）；`/signup` 与 `/login` 共用它。见 §2.1 A-1、§2.2 B-2 第 1 步、§7 R-14。 |
| **P1-2** | 一致性 | **自助改密端点是 `POST /api/me/password`，不是 `PATCH`。** v1 在 §2.1 A-4 拦截矩阵、§2.2 B-4 作用范围、§2.4 权限矩阵三处都写成 `PATCH`，§8.3 验收清单也按 PATCH 手测——照着写会得到 405。 | `routes/me.py:120` `@bp.post("/password")` | 三处全部改为 `POST /api/me/password`。 |
| **P1-3** | 完备性 | **R-5 的缓解措施是假护栏。** v1 §2.1 A-2 与 §7 R-5 都声称「漏登记 `ADDITIVE_COLUMNS` 时 `test_schema_sync.py` 的漂移守卫会直接失败」。实际那条守卫是**单向**的：`tests/test_schema_sync.py:107-112` 只遍历清单去查模型，其注释白纸黑字写着「反向（模型有列而清单没有）由本轮的人工登记 + CLAUDE.md 硬约束保证」。所以漏登记 `is_root` / `source` 时**没有任何测试会红**，直到存量 `aragon.db` 上线全线 `no such column` → 500。 | `tests/test_schema_sync.py:102-112` | 不再假装有自动护栏。本轮**顺手把守卫补成双向**（新增 `test_every_model_column_is_creatable_or_registered`，见 §8.2 用例 40），并把 R-5 的缓解改写为「双向守卫 + DoD-3 的存量库实起」。 |
| **P1-4** | 可行性 | **`ROOT_ADMIN_USERNAME` 是一条可抢注的提权路径。** `users.username` 没有保留字概念，任何人（管理员建号、或本轮开放后的自助注册）都能占用 `admin` 这个名字。而 `ensure_root_admin` 的语义是「同名即认领并强制提为 admin + is_root」。于是：① 存量部署里若有人早先建过一个叫 `admin` 的普通成员，下次重启他被静默提为不可降级的根管理员；② `ROOT_ADMIN_BOOTSTRAP=false` 的部署、或「改了 `ROOT_ADMIN_USERNAME` 但还没重启」的窗口期内，攻击者可以抢注那个用户名，等下一次重启把自己变成 root。 | `models/user.py:14`（username 无保留字）、v1 §2.1 A-3 提权分支 | ① `POST /auth/signup` 与 `POST /api/users` 双双拒绝等于 `ROOT_ADMIN_USERNAME` 的用户名（409，稳定文案）；② `ensure_root_admin` 提权既有账号时**必打 warning 并记 user id**。见 §2.1 A-3、§2.2 B-2 第 6 步、§7 R-15。 |
| **P1-5** | 完备性 | **`GET /api/users` 的新筛选参数没有可用的校验原语。** v1 §2.3 C-2 说 `role` / `is_active` / `source` 非法时抛 `QueryParamError` → 全局 400，但 `services/scope.py` 里**只有** `want_query_int`（它是全仓库唯一的 `QueryParamError` 生产者），没有字符串枚举与布尔的对应物；§3.2 的文件变更表也没登记 `services/scope.py`。实现者到这一步只能自己发明第二套 400 契约。 | `services/scope.py`（只有 `want_query_int` / `project_scope` / `apply_project_filter` / `query_error_response`）、`errors.py:39-44` | 明确新增 `scope.want_query_str(field, *, choices=None)` 与 `scope.want_query_bool(field)`，并登记进 §3.2 变更表。 |
| **P1-6** | 完备性 | **前端通知类型有三份手写镜像，其中两份漏改不会被 `npm run typecheck` 拦住。** v1 §2.3 C-1 断言「唯一需要手改的镜像是 `NotificationPrefsCard.tsx`」——这既与它自己的 §3.4（列了 `types.ts` / `constants.ts` / `NotificationPrefsCard.tsx` 三个文件）自相矛盾，也与代码不符：`lib/constants.ts:140/150` 的 `NOTIFICATION_LABELS` / `NOTIFICATION_ICONS` 是 `Record<string, string>`，取值函数 `notificationLabel()` 还带 `|| type` 兜底，所以漏改**编译通过**，只会在通知铃里显示英文原文 `user_registered` + 🔔。DoD 的 typecheck 门禁在这里守不住任何东西。 | `frontend/lib/constants.ts:140,150,160-166`、`frontend/components/settings/NotificationPrefsCard.tsx:14-22`、`frontend/lib/types.ts:210-217` | 把两个 map 收紧为 `Record<NotificationType, string>`，把 `NotificationPrefsCard` 的 `TYPES` 改为从单一常量派生 —— 让「漏改一处」成为编译错误，typecheck 门禁才真的成立。见 §2.3 C-1、§3.4。 |
| **P1-7** | 完备性 | **`ROOT_ADMIN_SYNC_PASSWORD` 的忘密码恢复流程留了一个会静默吞掉新密码的空窗。** v1 写的是「设 true → 重启 → 登录 → 立刻设回 false」，但把 flag 设回 false **需要第二次重启**。若管理员登录后先在 `/settings` 改了密码、之后才（或忘了）设回 false，下一次任何原因的重启都会把新密码**静默改回**配置里的旧值——正是这个 flag 存在的理由所要防的那件事，只是延后了一次重启。 | v1 §2.1 A-1 注释 | 恢复流程改写为**四步且顺序不可换**（先把 flag 设回 false 并重启，**再**改密码），并要求 `ensure_root_admin` 在该 flag 为真时**每次启动都打 warning**，使它不可能被忘记。 |
| **P1-8** | 完备性 | **配置兜底路径绕过了 `SIGNUP_ROLES` 白名单，一个环境变量即可让自助注册直接产出管理员。** §2.2 B-1 立了「自助注册**永远**不能产出 admin」这条不变量，`PATCH /api/settings/registration` 也确实按白名单校验。但 `get_registration_settings()` 的「无行 = 用配置默认」会把 `Config.REGISTRATION_DEFAULT_ROLE`（`os.environ.get(..., "member")`）**原样**交给 §2.2 B-2 第 7 步落库。全新库上 `app_settings` 恰恰是空的，于是设一个 `REGISTRATION_DEFAULT_ROLE=admin` 环境变量，任何拿到邀请码的人注册即为管理员。 | v1 §2.2 B-1 / §5.3 与 §2.2 B-2 第 7 步的组合 | `get_registration_settings()` 对 `default_role` **无条件过白名单**（不在 `SIGNUP_ROLES` 内 → 回落 `"member"` + warning），与 §5.3 既有的「脏值回落」同一处理；§5.3 表补一行说明兜底默认值同样受约束。 |

### P2（不阻塞实施，已在 v2 中一并处理或备案）

| # | 问题 | 处置 |
|---|---|---|
| P2-1 | `backend/tests/test_settings.py` **已存在**（25 条，测的是 account-settings 轮的 `/api/me/profile`、`/api/me/password`、`/api/me/notification-preferences`）。本轮新建的 `routes/settings.py` 与 `tests/test_app_settings.py` 名字与它高度相似，下一个人极易往错的文件里加用例。 | 新蓝图对象命名为 `admin_settings_bp`（URL 前缀仍是 `/api/settings`），并要求在 `tests/test_app_settings.py` 顶部 docstring 写清与 `test_settings.py` 的分工。 |
| P2-2 | `Notification.message` 是 `String(255) NOT NULL`，`notify()` 对 `message` 走 `_clip(message or "")`。v1 §2.3 C-1 的签名说明没写 message，实现者可能漏传而落一条空文案通知。 | §2.3 C-1 补上确切文案模板。 |
| P2-3 | `services/notification_prefs.py::effective_map` 的 docstring 写死「6 类通知」，本轮之后是 8 类（`document_added` 上轮已经没改）。CLAUDE.md §四禁止僵尸注释。 | 列入 §3.2 变更表。 |
| P2-4 | v1 §2.3 C-3 把团队页说成「底部加 `Pagination`」，像是增量；实际 `app/(app)/team/page.tsx:24` 用的是 `useSWR(USERS_KEY, swrFetcher)`——**没有** `listFetcher`、没有 `X-Total-Count`、没有任何分页接线，是把数据层整体替换。另外根管理员禁用态要在 `MemberFormModal` 的 `EditMemberForm`（角色 `Select`）与 `ResetPasswordForm` **两处**都拦。 | §2.3 C-3 与 §3.4 已按实际改写。 |
| P2-5 | `/register` 是**真正的公开路由**：全仓库无 `middleware.ts`，唯一的登录守卫是 `app/(app)/layout.tsx:15-17` 的客户端 `useEffect`。 | §6.1 补一句：该页任何数据获取都必须容忍 401，不得依赖任何服务端保护。 |
| P2-6 | `frontend/lib/auth.tsx` 的 `AuthState` 没有 `export`，也没有 `setToken` / `setUser` 成员（只有 `login` / `logout` / `refresh` / `applyUser`）；`setToken` 是从 `lib/api` import 的模块级函数。v1 §3.4 的措辞「`setToken` + `setUser`」容易被读成公开 API。 | §3.4 改为描述内部实现，并点明 `signup` 与既有 `login`（`lib/auth.tsx:67-74`）逐行同构。 |
| P2-7 | CLAUDE.md 里「380+ 用例」与 v1 §8.1 的引用都已过期。实测 `python -m pytest -q --collect-only` = **597** 条（39 个文件）。 | §8.1 记录实测基线数字，并保留「相对判据」的表述。 |
| P2-8 | 新增 `source` 筛选让任意已登录 `member` 可以枚举「谁是自助注册进来的」。`GET /api/users` 今天就对全体登录用户开放且返回完整 `to_dict()`（含 email），故这不是**新增**泄露面，但确实是一次微小扩大。 | 备案于 §7 R-18，本轮不改 `GET /api/users` 的鉴权（改它是破坏性变更，属独立一轮）。 |

---

## 1. Overview（概述）

AragonTeam 当前的用户来源只有一条路径：管理员在「团队」页点「+ 新增成员」，由
`POST /api/users`（`@require_role("admin")`）代填用户名与初始密码，再把密码线下告诉本人。
这在只有一两个人的演示环境里成立，一旦团队规模超过十人就立刻暴露三个问题：
**（一）** 管理员成为人力瓶颈，每来一个人就要手工建号、手工传密码，密码明文经由 IM 流转；
**（二）** 新人没有任何自助入口，`/login` 页面下方还赫然写着「演示账号（点击填充）admin / admin123」，
这在任何真实部署里都是一个开放的管理员后门；**（三）** 系统里的「管理员」是靠 seed 写死的一行数据，
没有任何机制保证它一定存在、一定可恢复——`lifecycle.would_orphan_admins` 只能防住「主动把最后一个
admin 降级/停用」，防不住「管理员忘了密码」或「管理员账号被误删的历史数据带走」。

本轮引入三样东西，把这三个问题一次性收口。**第一，邀请码门禁的自助注册**：新增公开端点
`POST /api/auth/signup` 与公开页面 `/register`，任何人填对邀请码即可自己建号并直接登录；邀请码默认
`aragon`，存放在新建的 `app_settings` 键值表里，**根管理员**可在「设置」页随时修改或一键重新生成。
**第二，根管理员由配置文件定义**：`ROOT_ADMIN_USERNAME` / `ROOT_ADMIN_PASSWORD` 写在后端配置
（环境变量覆盖）里，应用启动时由 `services/bootstrap.py::ensure_root_admin` 幂等地保证这个账号存在、
是 admin、是启用状态，并在 `users.is_root` 上打标。根管理员**不可被降级、不可被停用、不可被他人重置
密码**——它是整个权限体系的锚点，也是「所有人都被锁在门外」时唯一的破窗入口（改配置 + 重启）。
**第三，管理员的用户治理面板补齐**：`GET /api/users` 增加 `q` / `role` / `is_active` / `source` 四个筛选
参数与真实分页，「团队」页据此获得搜索框、筛选器与分页器，并对自助注册进来的人显示「自助注册」标记，
让管理员在人一多之后仍然能一眼看清「这批人是谁、从哪来、还该不该留着」。

设计上本轮**严格遵守既有硬约束**：`app_settings` 是本轮唯一新增的表（`create_all` 自动建，无迁移风险）；
`users` 新增的两列 `is_root` / `source` 全部登记进 `services/schema_sync.py::ADDITIVE_COLUMNS`；
既有的 `POST /api/auth/register`（admin-only）**契约逐字不变**，自助注册走全新的 `/signup` 端点，
存量调用方与存量测试零改动；新增的通知类型 `user_registered` 沿用 `NotificationPreference` 的
「无行=启用」语义，存量用户零回填。

---

## 2. 技术设计（Technical Design）

### 2.1 支柱 A —— 根管理员：配置文件是唯一真相

#### A-1 配置项（`backend/config.py`）

```python
# —— 根管理员（self-service-registration §2.1）——
# 【为什么放配置而不是库】它是「所有管理员都进不来」时唯一的破窗入口：
# 改环境变量 + 重启 = 恢复。放库里就没有这条恢复路径。
ROOT_ADMIN_USERNAME = os.environ.get("ROOT_ADMIN_USERNAME", "admin")
ROOT_ADMIN_PASSWORD = os.environ.get("ROOT_ADMIN_PASSWORD", "admin123")
ROOT_ADMIN_EMAIL = os.environ.get("ROOT_ADMIN_EMAIL", "admin@aragon.dev")
ROOT_ADMIN_DISPLAY_NAME = os.environ.get("ROOT_ADMIN_DISPLAY_NAME", "Ada（管理员）")
# 启动期是否执行根管理员保障。**测试环境必须关**（见 TestConfig 注释）。
ROOT_ADMIN_BOOTSTRAP = _env_bool("ROOT_ADMIN_BOOTSTRAP", True)
# 是否在每次启动时把库内密码重置回配置值。**默认 false**：默认 true 会让
# 「根管理员在 /settings 改了密码 → 重启后被环境变量悄悄改回去」，是静默数据丢失。
# 【v2 · P1-7】置 true 是唯一的忘密码恢复流程，但**四步顺序不可换**：
#   1) 设 true  2) 重启（此刻库内口令 = 配置口令）  3) 用配置口令登录
#   4) **先把 flag 设回 false 并再重启一次**，之后才去 /settings 改新密码。
# 把第 4 步的两半颠倒（先改密码、后关 flag）会让新密码在下一次重启时被静默改回旧值——
# 那正是本 flag 默认 false 所要防的事，只是延后了一次重启。
# 为让这条流程不可能被忘记：flag 为真时 ensure_root_admin **每次启动都打 warning**（A-3）。
ROOT_ADMIN_SYNC_PASSWORD = _env_bool("ROOT_ADMIN_SYNC_PASSWORD", False)

# —— 自助注册（§2.2）——
# 邀请码/开关/默认角色的**兜底默认值**；库内 app_settings 有行时以库为准（§2.2 B-1）。
REGISTRATION_INVITE_CODE = os.environ.get("REGISTRATION_INVITE_CODE", "aragon")
REGISTRATION_ENABLED = _env_bool("REGISTRATION_ENABLED", True)
# 【v2 · P1-8】本项**不是**最终真相：get_registration_settings() 会无条件把它过一遍
# SIGNUP_ROLES 白名单。否则 `REGISTRATION_DEFAULT_ROLE=admin` 一个环境变量就能让
# 任何拿到邀请码的人注册即为管理员——白名单只挡了 PATCH 端点，挡不住配置兜底路径。
REGISTRATION_DEFAULT_ROLE = os.environ.get("REGISTRATION_DEFAULT_ROLE", "member")
# 5 分钟窗口内单个客户端的注册尝试上限（成功与失败都计数，§2.2 B-2 第 1 步）。
SIGNUP_MAX_ATTEMPTS = _env_int("SIGNUP_MAX_ATTEMPTS", 10)
# 【v2 · P1-1】信任几层反向代理的 X-Forwarded-For。**默认 0 = 一个都不信**，
# 即 client_ip() 恒等于 request.remote_addr，与今天的 /login 行为逐字节相同。
# 本仓库自带 nginx 反代模板（ops/templates/aragonteam-nginx-http），在那种部署下
# remote_addr 恒为 127.0.0.1，限流会退化成**全站单桶**；此时必须置 1。
# 选「显式配置」而不是无脑接 ProxyFix：无条件信任转发头等于把限流键交给客户端伪造。
TRUST_PROXY_COUNT = _env_int("TRUST_PROXY_COUNT", 0)
```

`TestConfig` 追加两行，**缺一不可**：

```python
class TestConfig(Config):
    ...
    # 【必须关】若启动期自动建根管理员，users 表在每个用例开始时就多一行，
    # `GET /api/users` 的长度断言、`active_admin_count` 断言、末任管理员 409 用例
    # 会**成批失败**。需要根管理员的用例由专用 fixture 显式调用 ensure_root_admin。
    ROOT_ADMIN_BOOTSTRAP = False
    # 阈值调小以便用 3 次请求测出 429（与 LOGIN_MAX_ATTEMPTS=3 同一手法）。
    SIGNUP_MAX_ATTEMPTS = 3
```

> **【v2 · P0-2】关 bootstrap 的地方不止 `TestConfig` 一处。**
> v1 曾断言「全套存量用例的 app fixture 都走 `create_app(TestConfig)`」——**这是错的**，
> 照它实现会让 `tests/test_purge_demo_data.py` 的 15 条用例集体变红，并让三个 CLI 工具
> 开始往目标库里写用户行。必须关闭的**五处**见 §2.1 A-3 末尾的「bootstrap 关闭清单」。

#### A-2 `users` 新增两列

| 列 | 类型 | 默认 | 语义 |
|---|---|---|---|
| `is_root` | BOOLEAN NOT NULL | `0` | 根管理员标记。全库**至多一行为真**，由 `ensure_root_admin` 维护 |
| `source` | VARCHAR(16) NOT NULL | `'admin'` | 账号来源：`seed` / `admin` / `signup` / `root`。仅供治理展示，不参与任何鉴权判定 |

两列都必须**同时**登记进 `services/schema_sync.py::ADDITIVE_COLUMNS`（CLAUDE.md 硬约束）。

> **【v2 · P1-3】不要指望现有的漂移守卫替你兜底。**
> `tests/test_schema_sync.py:102-112` 的 `test_additive_columns_cover_every_model_column`
> 是**单向**的：它只遍历清单去查模型（「清单里写的列必须真实存在」），其注释明确写着
> 「反向（模型有列而清单没有）由本轮的人工登记 + CLAUDE.md 硬约束保证」。
> 也就是说，**漏登记 `is_root` / `source` 不会让任何一条现有用例变红**，只会在存量
> `aragon.db` 上线后全线 `no such column` → 500。本轮顺手把守卫补成双向
> （§8.2 用例 40：模型列 ⊆ create_all 基线列 ∪ `ADDITIVE_COLUMNS`），
> 让这条 CLAUDE.md 硬约束第一次真正有机器执行者。

```python
ADDITIVE_COLUMNS = [
    ...
    ("users", "is_root", "BOOLEAN NOT NULL DEFAULT 0"),
    ("users", "source", "VARCHAR(16) NOT NULL DEFAULT 'admin'"),
]
```

`User.to_dict()` 追加 `"is_root": bool(self.is_root)` 与 `"source": self.source or "admin"`
（additive，前端旧代码不受影响）。`User.summary()` **不加**——指派选择器与时间线不关心谁是根管理员，
多传一个字段只会让 `AssigneeSummary` 变胖。

#### A-3 `services/bootstrap.py::ensure_root_admin(app)`

幂等、可重复执行，返回一个供日志使用的动作描述，**绝不打印密码**。

```
ensure_root_admin(app) -> dict:
    username = config["ROOT_ADMIN_USERNAME"].strip()
    if not username: 抛 RuntimeError（配置写空 = 部署事故，应当起不来而不是静默跳过）
    user = User.query.filter_by(username=username).first()
    if user is None:
        建号：role="admin", is_active=True, is_root=True, source="root",
              display_name=ROOT_ADMIN_DISPLAY_NAME, email=ROOT_ADMIN_EMAIL,
              avatar_color=avatars.pick_color(username),   # ← 【v2 · P0-1】服务层，不是 routes.auth
              set_password(ROOT_ADMIN_PASSWORD)
        action = "created"
    else:
        was_ordinary = (user.role != "admin") or (not user.is_root)
        强制归位：role="admin"、is_active=True、is_root=True（三者任一被改过都拉回来）
        若 ROOT_ADMIN_SYNC_PASSWORD: set_password(ROOT_ADMIN_PASSWORD); action="password_synced"
        else: action = "promoted" if 有字段被改 else "unchanged"
        # 【v2 · P1-4】把一个既有账号提成不可降级的根管理员是一次**不可逆的授权变更**，
        # 绝不允许它静默发生——运维必须能在启动日志里看到「是谁被提权了」。
        if was_ordinary:
            app.logger.warning(
                "ensure_root_admin promoted existing account to root: id=%s username=%s",
                user.id, username)
    # 单根不变量：配置文件是唯一真相，其余 is_root 行一律清标并写 warning 日志
    User.query.filter(User.username != username, User.is_root.is_(True))
              .update({"is_root": False})
    db.session.commit()
    # 默认口令告警：生产环境仍在用 admin123 必须刺眼
    if password == "admin123" and not app.debug and not app.config.get("TESTING"):
        app.logger.warning("ROOT_ADMIN_PASSWORD is still the built-in default — change it")
    # 【v2 · P1-7】同步口令模式是一个**临时恢复态**，不是稳态。每次启动都喊一遍，
    # 让「登录完忘了关」这件事在下一次重启时就被发现，而不是等新密码被静默吞掉。
    if config["ROOT_ADMIN_SYNC_PASSWORD"] and not app.config.get("TESTING"):
        app.logger.warning(
            "ROOT_ADMIN_SYNC_PASSWORD is ON — the root password is being reset from config "
            "on every boot; turn it off and restart before changing the password")
    return {"action": action, "username": username}
```

**【v2 · P0-1】`avatars.pick_color` 是新增的 `services/avatars.py`，不是 `routes/auth.py::_pick_color`。**
后者今天定义在 `routes/auth.py:91`（文件末尾），从服务层去 import 它既是 service→route 的
反向依赖，也会与 `routes/users.py:11` 既有的 `from routes.auth import _pick_color`
凑成一个**在应用启动时必炸的循环导入**（详见 §0 P0-1）。本轮把调色板与选色函数一次性
下沉到 `services/avatars.py`，四个调用点（`routes/auth.py`、`routes/users.py`、`seed.py`、
`services/bootstrap.py`）统一改读——顺带消灭 `seed.py:27` 那份 `_COLORS` 复制，
它今天靠一句「与 auth._PALETTE 一致」的注释维持同步，是典型的第二真相。

**调用位置与顺序（不可调换）**，在 `app.py::create_app` 的 `with app.app_context()` 块内：

```
db.create_all()
schema_sync.sync_additive_columns(db.engine)
persistence.log_storage_summary / collect_storage_info
release_stale_agent_locks
if SEED_ON_STARTUP: seed_if_empty()          # ← 先 seed
if ROOT_ADMIN_BOOTSTRAP: bootstrap.ensure_root_admin(app)   # ← 后 bootstrap
```

**为什么必须在 seed 之后**：`seed_if_empty()` 的幂等判据是 `User.query.count() == 0`。
若先建根管理员，全新库上 users 恒非空，**示例项目 / 示例需求 / 示例 BUG / 示例评论一行都不会写入**，
「首次启动开箱有内容」这条既有承诺当场失效。放在 seed 之后，全新库的时序是：
seed 建出 `admin` → bootstrap 找到同名账号 → 只打 `is_root` 标 → **默认配置下与今天的行为逐字相同**。

配套地，`seed.py` 里写死的 `username="admin"` / `set_password("admin123")` 改为读
`current_app.config["ROOT_ADMIN_USERNAME"] / ["ROOT_ADMIN_PASSWORD"]`，`source="seed"`。
这样自定义了 `ROOT_ADMIN_USERNAME=root` 的部署，seed 直接建 `root`，bootstrap 认领同一行，
**不会出现两个管理员**。默认值不变，故存量库与 `test_seed_minimal.py` 的断言不受影响。

#### A-3′ bootstrap 关闭清单（**五处，v2 · P0-2**）

`ROOT_ADMIN_BOOTSTRAP` 默认 True 是对的（否则这根支柱等于没上线），但下列五个入口
**必须显式关掉**。v1 只写了第 1 条，照它实现会立刻踩两个坑。

| # | 位置 | 怎么关 | 不关会怎样 |
|---|---|---|---|
| 1 | `config.py::TestConfig` | `ROOT_ADMIN_BOOTSTRAP = False` | 内存库用例里每个 users 计数断言都多一行 |
| 2 | `tests/conftest.py::file_app` 的 `attrs` | 加 `"ROOT_ADMIN_BOOTSTRAP": False`，**放在 `**overrides` 之前**，让用例可显式打开 | `FileConfig` 基类是 `Config`（`conftest.py:103`）而**不是** `TestConfig`。`tests/test_purge_demo_data.py:150` 的 `legacy_db` 先 `make(seed=False)` 建空库（bootstrap 就地建出 `admin`），随后 `_install_legacy_principals()` 再插一个同名 `admin` → 撞唯一索引 → **该文件 15 条用例集体炸** |
| 3 | `tools/purge_demo_data.py` | `os.environ["ROOT_ADMIN_BOOTSTRAP"]="false"` **且** `PurgeConfig` 子类里 `ROOT_ADMIN_BOOTSTRAP=False`（两处都要，与既有 `SEED_ON_STARTUP` 同一手法，`tools/purge_demo_data.py:623-633`） | 清理工具在目标库里凭空写一个用户行；**dry-run 也会写**——直接违背该模块开篇「dry-run 绝不写库」的第一原则 |
| 4 | `tools/purge_trash.py`（`:165-174`） | 同上 | 同上 |
| 5 | `tools/gc_orphan_blobs.py`（`:180-189`） | 同上 | 同上 |

三个 CLI 都是「只读 / 只删」的运维工具，**任何写用户表的副作用都是缺陷**，
与它们已经关掉 `SEED_ON_STARTUP` / `RELEASE_STALE_LOCKS_ON_STARTUP` 是同一条理由。

#### A-4 根管理员保护（`services/lifecycle.py` 新增）

```python
def is_protected_root(user) -> bool:
    return bool(getattr(user, "is_root", False))

def conflict_root_admin(reason: str):
    """根管理员受保护 409。与本模块既有三种 409 一致：**不带 `allowed` 键**
    （前端看板拖拽以 err.allowed 是否存在分流错误，不得误伤）。"""
    return jsonify({
        "error": "root administrator is protected",
        "detail": {
            "reason": reason,
            "hint": "change ROOT_ADMIN_* in the backend config and restart",
        },
    }), 409
```

拦截矩阵（在 `routes/users.py::patch_user` 中，**排在末任管理员守卫之前**，因为它更具体、
错误信息更可操作）：

| 目标是根管理员时的操作 | 结果 |
|---|---|
| `PATCH /users/:id {"role": ...}` | 409 `role of the root administrator cannot be changed` |
| `PATCH /users/:id {"is_active": false}` | 409 `the root administrator cannot be deactivated` |
| `PATCH /users/:id {"password": ...}` 且调用者 ≠ 本人 | 409 `only the root administrator can change its own password` |
| `PATCH /users/:id {"display_name"/"email"}` | **放行**（改昵称邮箱不威胁治理） |
| 根管理员本人走 `POST /api/me/password` | **放行**（`me` 蓝图无角色门禁，语义就是自助） |

> **【v2 · P1-2】自助改密是 `POST /api/me/password`，不是 `PATCH`**（`routes/me.py:120`
> `@bp.post("/password")`）。v1 在本表、§2.2 B-4、§2.4 权限矩阵、§8.3 验收清单四处都写成
> `PATCH`，照着写会得到 405。全文已统一。

`would_orphan_admins` 保留不动：根管理员恒为 admin+active 使它在默认部署下几乎不可达，
但 `ROOT_ADMIN_BOOTSTRAP=false` 的部署仍然只有它兜底，属于纵深防御。

### 2.2 支柱 B —— 邀请码与自助注册

#### B-1 `app_settings` 键值表 + `services/app_settings.py`

不给每个开关加一列，而是建**一张键值表**：本轮只需要三个设置项，且未来一定还会有第四第五个
（SMTP、站点名、默认项目…）。逐个加列意味着每次都要动 `schema_sync`，键值表把这类演进
一次性压平。**代价**是失去列级类型约束，故类型收敛到服务层的键注册表里，路由层永远不直接读表。

```python
# backend/models/app_setting.py
class AppSetting(db.Model):
    __tablename__ = "app_settings"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, nullable=True)          # 一律存字符串，类型由服务层解释
    updated_by_id = db.Column(db.Integer, nullable=True)  # 无 DB 外键（与 comments/activities 一致）
    created_at / updated_at = ... (utcnow / onupdate=utcnow)
```

```python
# backend/services/app_settings.py
KEY_REGISTRATION_ENABLED = "registration.enabled"
KEY_REGISTRATION_INVITE_CODE = "registration.invite_code"
KEY_REGISTRATION_DEFAULT_ROLE = "registration.default_role"

# 自助注册**永远**不能产出 admin：一个知道邀请码的人不该能直接成为管理员。
SIGNUP_ROLES = ("member", "pm")

INVITE_CODE_MIN, INVITE_CODE_MAX = 4, 64
# 人类可口述、可手抄：去掉 0/O/1/l/I 等易混字符。
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

def get_registration_settings() -> dict:
    """返回生效值 {enabled: bool, invite_code: str, default_role: str}。
    「无行 = 用配置默认」——与 notification_prefs 的「无行 = 启用」同一模式，存量库零回填。

    【v2 · P1-8 · 安全不变量】返回的 default_role **无条件**过一遍 SIGNUP_ROLES 白名单：
    库内脏值与**配置兜底值**一视同仁，不在白名单内即回落 "member" 并打 warning。
    少了这一步，`REGISTRATION_DEFAULT_ROLE=admin` 一个环境变量就能让任何拿到邀请码的人
    注册即为管理员——PATCH 端点的白名单校验只管住了「改设置」这条路径，管不住
    「全新库上 app_settings 为空、直接走配置兜底」这条路径，而后者恰恰是每次全新部署的常态。
    """

def set_registration_settings(changes: dict, actor_id: int) -> dict:
    """幂等 upsert，**不 commit**（由路由统一提交）。仅识别注册表里的三个键；
    值已在路由层用 validation.want_* 校验过类型，这里只做业务约束（枚举 / 长度 / 字符集）。"""

def generate_invite_code(length: int = 10) -> str:
    """secrets.choice 生成，格式化为 XXXXX-XXXXX。CSPRNG，禁止 random 模块。"""

def verify_invite_code(candidate: str) -> bool:
    """hmac.compare_digest 定长比较，规避计时侧信道。
    输入先 .strip()，**大小写敏感**（邀请码是凭据不是标识符，宽松匹配等于缩小密钥空间）。"""
```

**读取策略：不缓存**。每次注册请求打一次 `app_settings` 的唯一索引查询——本地 SQLite 下这是
微秒级开销，而进程内缓存在 gunicorn 多 worker 下必然失效不同步（根管理员改了码，只有一个 worker 生效），
是典型的「优化制造出的 bug」。

邀请码**明文存储**：根管理员必须能读回来才能发给同事，哈希存储会让「查看当前邀请码」这个核心操作
不可能实现。这是有意识的取舍，见 §7 R-2。

#### B-2 `POST /api/auth/signup`（公开）

既有 `POST /api/auth/register` 保持 `@require_role("admin")` **逐字不变**——它被存量测试与
管理台使用，改动它的鉴权等于破坏性变更。自助注册是**新端点**。

执行时序（编号即实现顺序，任何一步失败都立即返回，不留半条记录）：

```
1  限流：key = f"signup:{ratelimit.client_ip()}"          ← 【v2 · P1-1】不是 request.remote_addr
       ratelimit.is_blocked(key, SIGNUP_MAX_ATTEMPTS) → 429 {"error":"too many attempts, try later"}
       ★ 成功与失败**都** record_failure(key)：这里要挡的既是暴力猜码，也是批量注册。
         （复用 ratelimit 的 record_failure 作为通用事件计数器；不改其对外命名——稳定 API。）
2  边界：json_body() + want_str
       username     max_len=64  required
       password     strip=False required
       invite_code  max_len=64  required
       display_name max_len=128 optional → 缺省回退 username
       email        max_len=255 optional → validation.want_email(data)  ← 【v2 · P0-1】服务层
       任一不合法 → ValidationError → 全局 400，绝不 500
3  开关：settings = app_settings.get_registration_settings()
       not settings["enabled"] → 403 {"error":"registration is disabled"}
4  邀请码：verify_invite_code(invite_code) 为假 → 403
       {"error":"invalid invite code","detail":{"field":"invite_code"}}
       ★ 选 403 不选 401：401 会被前端 api.ts 的会话失效广播语义污染（虽然
         signalUnauthorizedIfNeeded 对 /auth/ 前缀已豁免，见 lib/api.ts:69-74，
         但语义上「码不对」不是「你没登录」）。
5  口令强度：services/passwords.validate_signup_password(password, username)
       不满足 → 400 {"error": "...", "detail":{"field":"password", "expected":"..."}}
6  保留名 + 重名：                                        ← 【v2 · P1-4】6a 是新增的一步
   6a username.casefold() == config["ROOT_ADMIN_USERNAME"].strip().casefold()
       → 409 {"error":"username already exists"}           ← 与 6b **同一个响应体**
   6b User.query.filter_by(username=...).first() → 409 {"error":"username already exists"}
       ★ 6a 用与 6b 完全相同的响应体是有意的：既堵住抢注，又不额外泄露
         「这个名字是根管理员用户名」这一条信息。
7  落库：User(role=settings["default_role"], source="signup", is_root=False,
              is_active=True, avatar_color=avatars.pick_color(username)) + set_password
       db.session.add → db.session.flush()          ← 拿到 user.id
8  告知管理员：notifications.notify_user_registered(new_user)  （不 commit，见 §2.3）
9  db.session.commit()
       ★ 用 try/except IntegrityError 包住 7–9：username 唯一索引下两个并发同名注册，
         输家会在 commit 时抛 IntegrityError，被全局兜底处理器渲染成 500。
         捕获 → db.session.rollback() → 返回与第 6 步**同一个** 409 体。
         第 6 步的预检不删除：它负责友好路径，try/except 负责竞态路径。
10 发令牌：create_access_token(identity=str(user.id), additional_claims={"role": user.role})
       返回 201 {"token": ..., "user": user.to_dict()}   ← 形状与 /login 完全一致，前端可复用
```

**关于用户名枚举**：第 6 步的 409 让攻击者能探测用户名是否存在。这是有意接受的：这是一个
邀请码门禁的内部协作平台，攻击者要先拿到邀请码；而把 409 换成模糊错误会让真实用户在
「换个名字重试」时完全失去反馈。写进 §7 R-11 备案。

#### B-2′ `ratelimit.client_ip()`（**v2 · P1-1 新增**）

```python
# backend/services/ratelimit.py
def client_ip() -> str:
    """限流用的客户端标识。**默认与 request.remote_addr 逐字节相同**。

    【为什么不直接接 werkzeug 的 ProxyFix】ProxyFix 是全局中间件，一旦装上，
    **所有**读 remote_addr 的地方都无条件相信 X-Forwarded-For。而这个头是客户端可写的：
    直连部署下装它，等于把限流键的取值权交给攻击者，每个请求换一个伪造 IP 即可绕过限流。
    故这里改为显式配置 + 只在服务端可控的那几跳上取值。

    TRUST_PROXY_COUNT = N（N>0）时：取 X-Forwarded-For 列表**从右往左**第 N 个
    （右端是最靠近服务端、最不可伪造的一跳）；列表长度不足或头缺失则回落 remote_addr。
    TRUST_PROXY_COUNT = 0（默认）时：直接返回 remote_addr，不看任何转发头。
    """
```

`routes/auth.py::login` 的限流键也同步改用 `client_ip()`（键仍是 `f"{ip}:{username}"`，
语义与既有测试逐字节不变）——同一个部署里两套 IP 口径是必然会漂移的第二真相。

**部署侧配套**：`ops/config.env` 与 `README.md` 的配置表都要写明：
**走 nginx 反代时 `TRUST_PROXY_COUNT` 必须置 1**，否则全站共用一个限流桶
（一个人手滑三次就把所有人挡在注册门外，见 §7 R-14）。

#### B-3 `GET /api/auth/registration-meta`（公开）

登录页/注册页需要知道「现在还开不开放注册」，但**绝不能**把邀请码本身发给未登录的人。

```
200 {"enabled": true, "invite_required": true, "password_min_length": 8}
```

`invite_required` 恒为 `true`（本轮不做「无码注册」模式），保留字段是为了让前端文案与未来的
开关模式共用同一份渲染逻辑，而不是将来再加一个字段导致前端两处分支。

#### B-4 口令强度（`services/passwords.py`）

```python
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128

def validate_signup_password(password: str, username: str) -> None:
    """不满足即抛 ValidationError（→ 400）。规则：
    1. 长度 ∈ [8, 128]
    2. 至少命中两类字符：小写 / 大写 / 数字 / 其他可打印
    3. 不等于用户名（大小写不敏感比较）
    """
```

**作用范围严格限定为 `/auth/signup`**。有意**不**套用到
`POST /api/users`（管理员建号）与 `POST /api/me/password`（自助改密，`routes/me.py:120`）：
那两条路径今天没有任何长度约束（前端 `MemberFormModal` 只在客户端要求 ≥6 位），
存量测试里存在 6 位口令的用例，收紧它们等于一次破坏性变更。统一口令策略是明确的
后续项（§10 Non-Goals），不在本轮。

> **【v2 · P1-4 例外】** `POST /api/users`（管理员建号）虽然不受口令策略约束，
> 但**必须**加上与 §2.2 B-2 第 6a 步同款的保留用户名守卫：否则管理员仍能建出一个
> 叫 `ROOT_ADMIN_USERNAME` 的普通成员，等下一次重启把他静默提成不可降级的根管理员。
> 两条注册路径必须用**同一个** `app_settings.is_reserved_username(name)` 判据，
> 不得各写一份。

### 2.3 支柱 C —— 管理员治理面

#### C-1 新通知类型 `user_registered`

`models/notification.py::NOTIFICATION_TYPES` 追加 `"user_registered"`。
后端下游 `services/notification_prefs.py`（`effective_map` 从元组派生）与 `routes/me.py`
自动跟随，**后端零额外改动**。

> **【v2 · P1-6】前端不是「一处镜像」，是三处，而且其中两处漏改不会编译失败。**
> v1 声称「唯一需要手改的是 `NotificationPrefsCard.tsx`」，这既与自己的 §3.4（列了三个文件）
> 矛盾，也与代码不符。实际情况：
>
> | 前端镜像 | 位置 | 漏改的后果 |
> |---|---|---|
> | `NotificationType` 联合 | `lib/types.ts:210-217` | **编译失败**（唯一守得住的一处） |
> | `NOTIFICATION_LABELS` / `NOTIFICATION_ICONS` | `lib/constants.ts:140,150` | **静默通过**——两者是 `Record<string, string>`，取值函数 `notificationLabel()`（`:160-162`）还带 `\|\| type` 兜底，铃铛里直接显示英文原文 `user_registered` + 🔔 |
> | `TYPES` 数组 | `components/settings/NotificationPrefsCard.tsx:14-22` | **静默通过**——设置页少一个开关，用户永远关不掉这类通知 |
>
> 也就是说 DoD 的 `npm run typecheck` 门禁在这里守不住任何东西。本轮**顺手把类型收紧**，
> 让「漏改一处」变成编译错误，这个门禁才第一次真正成立：
>
> 1. `lib/constants.ts`：两个 map 的类型由 `Record<string, string>` 改为
>    `Record<NotificationType, string>`（这是纯类型收紧，运行时零变化）。
> 2. `lib/types.ts`：新增 `export const NOTIFICATION_TYPE_LIST: readonly NotificationType[]`，
>    与联合类型放在一起维护。
> 3. `NotificationPrefsCard.tsx`：`TYPES` 改为 `NOTIFICATION_TYPE_LIST`，删掉手写数组。
>
> 同一处收紧**有意不外扩**到 `STATUS_STYLES` / `ROLE_LABELS` / `ACTION_LABELS`
> （它们同样是 `Record<string, …>`）——那是另一轮的清理，本轮只动通知这一条链路。

`services/notifications.py` 新增：

```python
def notify_user_registered(new_user) -> int:
    """向全部**有效管理员**（role=admin AND is_active）扇出一条注册通知；返回实际发出条数。
    - message 必传（Notification.message 是 String(255) NOT NULL，notify 内部走 _clip）。
      文案模板：f"新用户 {_short(new_user.display_name or new_user.username)} 通过邀请码注册"
    - entity_type / entity_id 传 None：这条通知不指向任何工单。
      前端 NotificationBell.onOpenItem 已有 `if (n.entity_type && n.entity_id != null)` 守卫
      （NotificationBell.tsx:73），点击只标已读、不跳转——**不需要**改动，
      但必须在验收里手测一次（§8.3 / §7 R-6）。
    - actor = ("user", new_user.id)：施动者就是注册的人。
    - notify() 的「不给自己发」不变量天然成立（新用户角色恒 ∈ SIGNUP_ROLES，不含 admin）。
    - 收件人查询必须包在 db.session.no_autoflush 内：调用点（§2.2 B-2 第 8 步）处于
      「已 flush 新用户、尚未 commit」的写事务中，与 notify() 内部既有的收敛同款。
    - 不 commit（沿用本模块既有约定，由调用方事务统一提交）。
    """
```

#### C-2 `GET /api/users` 增加筛选（additive，默认行为逐字不变）

| 参数 | 取值 | 非法时 |
|---|---|---|
| `q` | 任意串，对 `username` / `display_name` / `email` 做 LIKE（**必须走 `services/search.escape_like` + `escape="\\"`**） | 空串等价于不传 |
| `role` | `admin` / `pm` / `member` | `QueryParamError` → 全局 400 |
| `is_active` | `true` / `false` / `1` / `0` | 同上 |
| `source` | `seed` / `admin` / `signup` / `root` | 同上 |
| `limit` / `offset` | 既有 `paginate`（默认 50，上限 200） | 既有语义 |

实现收敛在 `routes/users.py::_apply_user_filters(query)` 一个私有函数里（≤50 行、圈复杂度 ≤10）。
响应体仍是**裸数组**，总数继续只走 `X-Total-Count` 头——这是全站分页契约，不得在本轮开洞。

> **【v2 · P1-5】上表所依赖的校验原语今天不存在，必须一并新增。**
> `services/scope.py` 里只有 `want_query_int`——它是全仓库唯一的 `QueryParamError`
> 生产者（`errors.py:39-44` 有对应的全局 400 处理器），没有字符串枚举与布尔的对应物。
> 本轮在同一模块新增两个同构函数，让四个筛选参数共用同一套 400 契约，
> 而不是让实现者在路由里发明第二套：
>
> ```python
> # backend/services/scope.py
> def want_query_str(field: str, *, default=None, choices=None):
>     """取一个查询串字段。缺失 / 空串 → default（空串等价于不传，见上表 q 的语义）；
>     给了 choices 且取值不在其中 → 抛 QueryParamError（→ 全局 400）。"""
>
> def want_query_bool(field: str, *, default=None):
>     """取一个布尔查询参数，接受 true/false/1/0（大小写不敏感）；
>     其余取值 → 抛 QueryParamError。**不做**「无法解析就当 False」的宽容处理——
>     那会让 ?is_active=ture 这样的手滑静默变成「只看已停用的人」。"""
> ```
>
> `q` 走 `want_query_str(…)` 后仍需 `services.search.escape_like` + `escape="\\"`
> 才能拼进 `ilike`（`services/search.py` 已提供，两步缺一不可）。

#### C-3 前端「团队」页

- **数据层整体替换（v2 · P2-4，不是增量）**：团队页今天是
  `useSWR<User[]>(USERS_KEY, swrFetcher)`（`app/(app)/team/page.tsx:24`）——用的是普通
  `swrFetcher`，**不读 `X-Total-Count`**，页面里没有任何分页接线，靠 `limit=200` 硬扛。
  本轮要改成 `useSWR(teamKey, listFetcher)` 并从返回的 `{items, total}` 里取值
  （`listFetcher` 见 `lib/api.ts:187-193`）。请按「重写这一段」而不是「加个组件」来估工。
- 顶部加 `MemberFilterBar`：搜索框（300ms 防抖，复用 `GlobalSearch.tsx:32` 的 `DEBOUNCE_MS`
  同一手法）+ 角色下拉 + 状态下拉。
- 底部加 `Pagination`（既有组件 `components/ui/Pagination.tsx:23`，`total <= limit` 时自渲染为
  `null`）；任一筛选变化时**重置到第 1 页**（与 `requirements` / `bugs` 列表页同一约定）。
- 行内新增两个标记：`is_root` → 「根管理员」徽章（clay 色，最高视觉权重）；`source === "signup"` →
  「自助注册」淡色徽章。根管理员那一行的「停用 / 重置密码」按钮**渲染为禁用并带 title 解释**，
  而不是隐藏——隐藏会让管理员以为是自己权限不够，禁用+解释才是诚实的。
- **SWR key 隔离（关键）**：团队页自建 key（形如 `/users?limit=50&offset=0&q=…`），
  **不得**复用 `USERS_KEY`（`/users?limit=200`）。后者是 `AssigneePicker` 等选择器的单一 key，
  被筛选结果污染会让指派下拉突然只剩几个人。两者都以 `/users` 开头，
  `lib/swr-keys.ts::invalidateAdminViews` 的**前缀失效**因此同时覆盖二者，无需额外改动。

#### C-4 「设置」页的注册配置卡

新增 `components/settings/RegistrationCard.tsx`，**仅当 `user.is_root === true` 时渲染**
（非根管理员连卡片都看不到，避免出现「看得见但一按就 403」的挫败感）。卡片内容：

- 「开放注册」`Toggle`（复用既有 UI 组件）；关闭后下方表单整体降为禁用态并显示灰化说明。
- 「邀请码」`Input`（`autoComplete="off"`、可见/隐藏切换）+ 「复制」按钮 + 「重新生成」按钮
  （后者走 `ConfirmDialog` 二次确认，文案明确写出「旧邀请码立即失效，已注册账号不受影响」）。
- 「新用户默认角色」`Select`，选项只有「成员 / 项目经理」——**没有管理员选项**，与后端
  `SIGNUP_ROLES` 白名单互为镜像。
- 只读的注册链接展示（`{origin}/register`）+ 复制按钮。
- 底部一行说明：根管理员账号密码在后端配置文件（`ROOT_ADMIN_*`）中配置，此处不可修改。

### 2.4 权限矩阵（本轮全部新增能力）

| 能力 | 未登录 | member | pm | admin（非根） | root |
|---|:---:|:---:|:---:|:---:|:---:|
| `GET /auth/registration-meta` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `POST /auth/signup` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `GET /settings/registration`（含明文邀请码） | ❌ 401 | ❌ 403 | ❌ 403 | ❌ 403 | ✅ |
| `PATCH /settings/registration` | ❌ 401 | ❌ 403 | ❌ 403 | ❌ 403 | ✅ |
| `POST /settings/registration/rotate-code` | ❌ 401 | ❌ 403 | ❌ 403 | ❌ 403 | ✅ |
| `GET /users?q=…`（筛选） | ❌ 401 | ✅ | ✅ | ✅ | ✅ |
| 改根管理员的角色 / 停用 / 代改密码 | — | 403 | 403 | **409** | 409（本人改密走 `POST /api/me/password`） |

`services/auth_helpers.py` 新增装饰器 `require_root()`，与 `require_role` 形状一致：

```python
def require_root():
    """要求当前用户 is_root。以库内字段为准（二次查库），不信任任何 JWT claim。
    403 体：{"error":"forbidden","detail":{"required":"root_admin","your_role": user.role}}"""
```

---

## 3. 文件 / 模块变更计划

### 3.1 后端 —— 新建

| 文件 | 一句话意图 |
|---|---|
| `backend/models/app_setting.py` | `AppSetting` 键值表模型（本轮唯一新表） |
| `backend/services/app_settings.py` | 注册设置的读/写/生成/校验，「无行=用配置默认」+ `is_reserved_username` |
| `backend/services/bootstrap.py` | `ensure_root_admin(app)`：幂等保障根管理员存在且归位 |
| `backend/services/passwords.py` | `validate_signup_password`，仅服务于 `/auth/signup` |
| `backend/services/avatars.py` | **【v2 · P0-1】** `pick_color(seed)` + 调色板。从 `routes/auth.py:88-92` 下沉到服务层，消灭 `seed.py:27` 的重复，并打断 `routes.auth ↔ routes.users` 的循环导入 |
| `backend/routes/settings.py` | `/api/settings/registration` 三个端点，全部 `@require_root()`。蓝图对象名 `admin_settings_bp`（**v2 · P2-1**：与既有 `tests/test_settings.py` 所测的 `/api/me/*` 账号设置区分） |
| `backend/tests/test_registration.py` | 自助注册全路径（开关/码/强度/重名/限流/竞态/通知） |
| `backend/tests/test_root_admin.py` | 根管理员 bootstrap 幂等性与四条保护规则 |
| `backend/tests/test_app_settings.py` | 键值表默认回退、类型校验、rotate、`require_root` 门禁。**顶部 docstring 必须写清与既有 `tests/test_settings.py`（account-settings 轮的 `/api/me/*`）的分工** |

### 3.2 后端 —— 修改

| 文件 | 一句话意图 |
|---|---|
| `backend/config.py` | 加 `ROOT_ADMIN_*` / `REGISTRATION_*` / `SIGNUP_MAX_ATTEMPTS` / **`TRUST_PROXY_COUNT`**；`TestConfig` 关 bootstrap、调小限流阈 |
| `backend/models/user.py` | 加 `is_root` / `source` 两列，`to_dict()` 追加二字段 |
| `backend/models/__init__.py` | **两处都要登记**：`from .app_setting import AppSetting` 与 `__all__` |
| `backend/models/notification.py` | `NOTIFICATION_TYPES` 追加 `"user_registered"` |
| `backend/services/schema_sync.py` | `ADDITIVE_COLUMNS` 登记 `users.is_root` / `users.source` |
| `backend/services/auth_helpers.py` | 新增 `require_root()` 装饰器 |
| `backend/services/lifecycle.py` | 新增 `is_protected_root` / `conflict_root_admin`（不带 `allowed` 键） |
| `backend/services/notifications.py` | 新增 `notify_user_registered(new_user)`，向有效管理员扇出 |
| `backend/services/notification_prefs.py` | **【v2 · P2-3】** `effective_map` docstring 里写死的「6 类」改为从 `NOTIFICATION_TYPES` 描述，消灭僵尸注释（CLAUDE.md §四） |
| `backend/services/validation.py` | **【v2 · P0-1】** 新增 `want_email(data, key="email")`：把 `routes/users.py:17-22` 的 `_want_email` 与 `routes/me.py:39` 的 `_EMAIL_RE` 下沉为单一真相，三个调用方（users / me / **新的 auth.signup**）统一改读 |
| `backend/services/scope.py` | **【v2 · P1-5】** 新增 `want_query_str` / `want_query_bool`，与既有 `want_query_int` 共用 `QueryParamError` → 全局 400 |
| `backend/services/ratelimit.py` | **【v2 · P1-1】** 新增 `client_ip()`（`TRUST_PROXY_COUNT` 驱动）；模块 docstring 补一句「本模块也被用作通用事件计数器（signup）」 |
| `backend/routes/auth.py` | 新增 `signup` 与 `registration_meta`；`_PALETTE`/`_pick_color` 迁往 `services/avatars.py`；`login` 的限流键改读 `client_ip()`。**其余（`login` 主体 / `me` / `register`）一行不改** |
| `backend/routes/me.py` | **【v2 · P0-1】** `_EMAIL_RE` 与 `_apply_profile` 的邮箱校验改读 `validation.want_email`（`routes/users.py:12` 今天正是从这里 import `_EMAIL_RE`） |
| `backend/routes/users.py` | 加 `_apply_user_filters`；`patch_user` 前置根管理员守卫；`create_user` 加保留用户名守卫（**v2 · P1-4**）；`_want_email` / `_pick_color` 改读服务层 |
| `backend/routes/__init__.py` | 注册 `admin_settings_bp`（第 15 个蓝图；今天是 14 个，`routes/__init__.py:19-35`） |
| `backend/seed.py` | admin 行的用户名/密码改读 `ROOT_ADMIN_*` 配置，`source="seed"`；`_COLORS` 改读 `services/avatars` |
| `backend/app.py` | seed 之后调用 `bootstrap.ensure_root_admin(app)`，记 info 日志 |
| `backend/tools/purge_demo_data.py` | **跳过 `is_root=True` 的用户行**，即使它带着 `SeedRecord`；**并关闭 `ROOT_ADMIN_BOOTSTRAP`**（§2.1 A-3′ 第 3 条） |
| `backend/tools/purge_trash.py` | **【v2 · P0-2】** 关闭 `ROOT_ADMIN_BOOTSTRAP`（§2.1 A-3′ 第 4 条） |
| `backend/tools/gc_orphan_blobs.py` | **【v2 · P0-2】** 关闭 `ROOT_ADMIN_BOOTSTRAP`（§2.1 A-3′ 第 5 条） |
| `backend/tests/conftest.py` | **【v2 · P0-2】** `file_app` 的 `attrs` 默认 `ROOT_ADMIN_BOOTSTRAP=False`（放在 `**overrides` 之前）；新增 `root_admin` / `root_auth` fixture（显式调用 `ensure_root_admin`） |
| `backend/tests/test_schema_sync.py` | **【v2 · P1-3】** 补一条**反向**漂移守卫（§8.2 用例 40），让漏登记 `ADDITIVE_COLUMNS` 第一次能被机器发现 |

### 3.3 前端 —— 新建

| 文件 | 一句话意图 |
|---|---|
| `frontend/app/register/page.tsx` | 公开注册页（在 `(app)` 组之外，天然不受登录守卫拦截） |
| `frontend/components/auth/AuthSplitLayout.tsx` | 从 `login/page.tsx` 抽出的左品牌右表单双栏骨架，登录/注册共用 |
| `frontend/components/auth/RegisterForm.tsx` | 注册表单：六字段 + 逐字段内联校验 + 提交后自动登录 |
| `frontend/components/auth/PasswordStrength.tsx` | 四段式强度条 + 规则清单（命中打勾），与后端规则逐条对应 |
| `frontend/components/settings/RegistrationCard.tsx` | 根管理员专属的注册配置卡 |
| `frontend/components/admin/MemberFilterBar.tsx` | 团队页搜索 + 角色 + 状态筛选条（300ms 防抖） |
| `frontend/hooks/useRegistrationMeta.ts` | 公开元信息 SWR（登录页/注册页共用，失败时按「开放」降级） |
| `frontend/hooks/useRegistrationSettings.ts` | 根管理员设置读写 + 乐观更新 + 失败回滚 |

### 3.4 前端 —— 修改

| 文件 | 一句话意图 |
|---|---|
| `frontend/app/login/page.tsx` | 改用 `AuthSplitLayout`；底部加「还没有账号？立即注册」（按 meta 开关显示）；**删除 DEMO_ACCOUNTS 一键填充块** |
| `frontend/app/(app)/settings/page.tsx` | 根管理员时挂载 `RegistrationCard` |
| `frontend/app/(app)/team/page.tsx` | **数据层由 `swrFetcher` 换成 `listFetcher`**（`:24`，今天没有任何分页接线）；接筛选条 + 分页；根管理员/自助注册徽章；根管理员行的危险操作禁用 |
| `frontend/lib/auth.tsx` | 新增 `signup(payload) => Promise<void>`，与既有 `login`（`:67-74`）**逐行同构**：内部 `setToken(token)` + `setUser(user)`。**注**（v2 · P2-6）：`setToken` 是从 `lib/api` import 的模块级函数，`setUser` 是 provider 内的 `useState` setter；`AuthState` 对外只暴露 `login/logout/refresh/applyUser`，本轮追加 `signup` |
| `frontend/lib/types.ts` | `User` 加 `is_root: boolean` / `source: UserSource`；新增 `SignupPayload` / `RegistrationMeta` / `RegistrationSettings`；`NotificationType` 联合追加 `"user_registered"`；**新增 `NOTIFICATION_TYPE_LIST`**（v2 · P1-6） |
| `frontend/lib/constants.ts` | `NOTIFICATION_LABELS` / `NOTIFICATION_ICONS` 各加一项，**并把两者的类型由 `Record<string,string>` 收紧为 `Record<NotificationType,string>`**（v2 · P1-6，否则漏改不报错）；新增 `USER_SOURCE_LABELS` |
| `frontend/lib/api.ts` | 加 `REGISTRATION_META_KEY` / `REGISTRATION_SETTINGS_KEY` 常量（单一 SWR key 惯例） |
| `frontend/components/settings/NotificationPrefsCard.tsx` | `TYPES` 手写数组（`:14-22`）改为 `NOTIFICATION_TYPE_LIST`（v2 · P1-6） |
| `frontend/components/admin/MemberFormModal.tsx` | **两处都要拦**（v2 · P2-4）：`EditMemberForm` 的角色 `Select` 禁用 + 解释文案；`ResetPasswordForm` 在目标为根管理员时整体禁用并说明「请由根管理员本人在设置页改密」 |

### 3.5 文档 —— 修改

| 文件 | 一句话意图 |
|---|---|
| `README.md` | 「常用配置」表补 `ROOT_ADMIN_*` / `REGISTRATION_*` / **`TRUST_PROXY_COUNT`**（并写明「走 nginx 反代必须置 1」）；快速开始改为「默认账号来自 `ROOT_ADMIN_*`」 |
| `ops/config.env` | **【v2 · P1-1 / R-1】** 补 `ROOT_ADMIN_PASSWORD`（带「生产必须覆盖」注释）与 `TRUST_PROXY_COUNT=1`（该文件的部署形态恒为 nginx 反代，`NGINX_DOMAIN` 已填） |
| `docs/iterations.md` | 追加本轮迭代记录（设计取舍、契约变更、验收结论） |
| `CLAUDE.md` | Project-Specific Notes 补**三条**：① 根管理员由配置文件定义，`purge` 工具永不删 `is_root` 行；② **新增 CLI 工具 / 新增 app fixture 时必须显式关闭 `ROOT_ADMIN_BOOTSTRAP`**（与既有 `SEED_ON_STARTUP` 并列，v2 · P0-2）；③ 顺手把「93 cases / 380+」的陈旧基线换成「跑 `pytest -q --collect-only` 现场取基线」 |

---

## 4. 接口设计（REST）

统一错误体沿用全站契约：`{"error": str, "detail"?: {...}}`。

### 4.1 `POST /api/auth/signup` —— 公开

```jsonc
// 请求
{
  "username": "linlei",           // 必填, ≤64, 唯一
  "password": "Aragon@2026",      // 必填, 8~128, 至少两类字符, ≠username
  "invite_code": "aragon",        // 必填, ≤64, 大小写敏感
  "display_name": "林磊",          // 选填, ≤128, 缺省回退 username
  "email": "linlei@example.com"   // 选填, ≤255, 格式校验同 /me/profile
}
// 201
{ "token": "eyJ...", "user": { "id": 12, "username": "linlei", "role": "member",
                               "is_root": false, "source": "signup", ... } }
```

| 状态码 | 触发条件 | 响应体要点 |
|---|---|---|
| 400 | 字段缺失 / 类型错 / 超长 / 邮箱格式 / 口令不达标 | `detail.field` + `detail.expected` |
| 403 | 注册开关关闭 | `{"error":"registration is disabled"}` |
| 403 | 邀请码错误 | `{"error":"invalid invite code","detail":{"field":"invite_code"}}` |
| 409 | 用户名已存在（含并发竞态） | `{"error":"username already exists"}` |
| 429 | 单 IP 5 分钟内尝试超阈 | `{"error":"too many attempts, try later"}` |

### 4.2 `GET /api/auth/registration-meta` —— 公开

```jsonc
200 { "enabled": true, "invite_required": true, "password_min_length": 8 }
```

### 4.3 `GET /api/settings/registration` —— `@require_root()`

```jsonc
200 {
  "enabled": true,
  "invite_code": "aragon",          // 明文；仅根管理员可见
  "default_role": "member",
  "allowed_default_roles": ["member", "pm"],
  "updated_at": "2026-07-21T09:12:33Z",   // 无行时为 null
  "updated_by": { "id": 1, "name": "Ada（管理员）" }  // 无行时为 null
}
```

### 4.4 `PATCH /api/settings/registration` —— `@require_root()`

请求体为**部分更新**，三个键均可选；一个都没带 → 400 `no updatable field`
（与 `patch_user` 的 `changed` 模式对齐，杜绝「静默成功」）。

```jsonc
{ "enabled": false, "invite_code": "ARAGON-2026", "default_role": "pm" }
```

| 状态码 | 触发条件 |
|---|---|
| 400 | 类型错误 / 邀请码长度越界（<4 或 >64）/ 邀请码含空白字符 / `default_role` ∉ `["member","pm"]` / 无可更新字段 |
| 403 | 非根管理员（含普通 admin） |

成功返回与 4.3 完全相同的结构（前端可直接 `mutate` 替换缓存，省一次往返）。

### 4.5 `POST /api/settings/registration/rotate-code` —— `@require_root()`

无请求体。生成新码并落库，返回与 4.3 相同结构。旧码**立即失效**（无宽限期——邀请码
不是会话令牌，宽限期只会让「我刚刚撤销的码还能用」这件事变得难以解释）。

### 4.6 `GET /api/users` —— 扩展（既有契约不变）

```
GET /api/users?q=lin&role=member&is_active=true&source=signup&limit=50&offset=0
200 [ {...}, {...} ]        // 裸数组
Headers: X-Total-Count: 137
```

---

## 5. 数据模型

### 5.1 新表 DDL（由 `create_all` 生成，无需 `schema_sync` 登记）

```sql
CREATE TABLE app_settings (
    id            INTEGER PRIMARY KEY,
    key           VARCHAR(64)  NOT NULL UNIQUE,
    value         TEXT,
    updated_by_id INTEGER,
    created_at    DATETIME     NOT NULL,
    updated_at    DATETIME     NOT NULL
);
CREATE UNIQUE INDEX ix_app_settings_key ON app_settings (key);
```

`updated_by_id` **不建 DB 外键**——与 `comments` / `activities` / `seed_records` 的一贯做法一致：
删用户不应该被一行设置记录挡住，展示时按 id 软解析，解析不到就降级为占位。

### 5.2 `users` 加列（必须登记 `ADDITIVE_COLUMNS`）

```sql
ALTER TABLE users ADD COLUMN is_root BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN source  VARCHAR(16) NOT NULL DEFAULT 'admin';
```

两条 DDL 的默认值都是**常量**（SQLite `ADD COLUMN` 的硬性要求），且 SQLite / PostgreSQL 双方言均接受。
存量行零回填即获得正确语义：存量用户确实都是管理员建的（`source='admin'`），
且都不是根管理员（`is_root=0`）——直到 `ensure_root_admin` 在同一次启动的稍后一步把那一行标起来。

### 5.3 键值表的值编码约定

| key | 编码 | 合法值 | 兜底默认 |
|---|---|---|---|
| `registration.enabled` | `"true"` / `"false"` | 二者之一 | `Config.REGISTRATION_ENABLED` |
| `registration.invite_code` | 原文 | 长度 4~64、无空白字符的可打印 ASCII | `Config.REGISTRATION_INVITE_CODE`（`"aragon"`） |
| `registration.default_role` | 原文 | `"member"` / `"pm"` | `Config.REGISTRATION_DEFAULT_ROLE`，**且兜底值同样过白名单**（v2 · P1-8） |

读取时任何**无法解析的脏值**（比如有人手工改库写了 `registration.enabled = "yes"`）一律**回落到配置默认
并写一条 warning 日志**，不抛异常：注册开关解析失败就让整个登录体系 500，是把小故障放大成全站故障。

> **【v2 · P1-8】`default_role` 的兜底值不是可信输入。**
> 上表最后一列的「兜底默认」对另外两个键是终点，对 `default_role` **不是**：
> `Config.REGISTRATION_DEFAULT_ROLE` 来自 `os.environ`，若被设成 `admin`，
> 而全新库上 `app_settings` 恰恰是空表（这是每次全新部署的常态），
> 「无行 = 用配置默认」就会把 `admin` 原样送进 §2.2 B-2 第 7 步落库，
> 让任何拿到邀请码的人注册即为管理员——`PATCH /api/settings/registration` 上的白名单
> 校验完全管不到这条路径。故 `get_registration_settings()` 对 `default_role` 的处理是
> **「库内脏值」与「配置兜底值」一视同仁，都必须过 `SIGNUP_ROLES`**，
> 不在白名单内一律回落 `"member"` 并打 warning。

### 5.4 前端类型（`lib/types.ts`）

```ts
export type UserSource = "seed" | "admin" | "signup" | "root";

export interface User {
  /* …既有字段逐字不变… */
  /** true = 根管理员：由后端配置文件定义，不可降级 / 停用 / 被他人改密。 */
  is_root: boolean;
  /** 账号来源，仅供治理展示，不参与任何前端鉴权判断。 */
  source: UserSource;
}

export interface SignupPayload {
  username: string; password: string; invite_code: string;
  display_name?: string; email?: string;
}
export interface RegistrationMeta {
  enabled: boolean; invite_required: boolean; password_min_length: number;
}
export interface RegistrationSettings {
  enabled: boolean; invite_code: string; default_role: Role;
  allowed_default_roles: Role[];
  updated_at: string | null;
  updated_by: { id: number; name: string } | null;
}
```

---

## 6. 前端设计（信息架构与交互）

### 6.1 `/register` 页面

沿用 `/login` 的暖色双栏骨架（`AuthSplitLayout`：左品牌区 `bg-clay-soft/40`，右表单区 `bg-bg`，
`lg` 以下折叠为单栏、品牌 lockup 上移）。字段自上而下：用户名 → 显示名称 → 邮箱（选填）→
密码 → 确认密码 → 邀请码。

交互细则（每条都对应一个具体的人机交互原则）：

1. **失焦即校验，键入即消错**：`onBlur` 触发内联错误，`onChange` 立刻清掉该字段的错误。
   避免「打字过程中被红字追着骂」，也避免「提交后才知道错在哪」。
2. **口令强度实时反馈**：`PasswordStrength` 显示四段进度条与规则清单（长度 ≥8 / 至少两类字符 /
   不等于用户名），每条规则命中即打勾。规则文案与后端 `validate_signup_password` **逐条对应**，
   前端提前拦下的一定是后端也会拒的，反之亦然。
3. **确认密码**只在两次都非空且不一致时报错，且不阻塞输入。
4. **邀请码字段** `autoComplete="off"`、`spellCheck={false}`，占位符写 `请向管理员索取`。
   服务端返回 403「邀请码错误」时，**只在该字段下方**渲染错误并自动聚焦回该字段——
   而不是弹一个 toast 让用户自己找哪里错了。
5. **提交按钮**在提交中禁用并显示「注册中…」；成功后 `signup()` 已写入 token 与 user，
   `toast.success("注册成功，欢迎加入")` 后 `router.replace("/dashboard")`。
   用 `replace` 不用 `push`：注册页不该留在返回栈里。
6. **注册关闭态**：`useRegistrationMeta` 返回 `enabled === false` 时，右栏渲染 `EmptyState`
   —「当前未开放自助注册，请联系管理员为你创建账号」+ 「返回登录」按钮，表单完全不渲染。
   meta 请求失败时**按开放处理**（渲染表单），让后端做最终裁决——网络抖动不该把人挡在门外。
7. **已登录访问 `/register`** → `useEffect` 里 `router.replace("/dashboard")`，与登录页
   （`app/login/page.tsx:29`）同一守卫。
8. **429 的文案**必须具体：「尝试过于频繁，请 5 分钟后再试」，而不是干巴巴的「请求失败」。
9. **【v2 · P2-5】`/register` 是真正的公开路由，没有任何服务端保护。**
   全仓库无 `middleware.ts`；唯一的登录守卫是 `app/(app)/layout.tsx:15-17` 的客户端
   `useEffect` 重定向，而 `/register` 与 `/login` 一样是 `(app)` 组的**同级兄弟**，
   天然在守卫之外。因此该页的任何请求都必须自己容忍 401 / 网络失败（第 6 条的
   「meta 失败按开放处理」正是这条原则的一个实例），不得假设「能打开这个页面 = 有会话」。

### 6.2 可访问性（a11y）

- 每个输入都有真实 `<label for>`（复用既有 `Input` 组件，它已内建）；错误文案容器带
  `role="alert"` + `aria-live="polite"`，屏幕阅读器能读到刚出现的校验错误。
- 密码可见性切换按钮带 `aria-label="显示密码 / 隐藏密码"` 与 `aria-pressed`。
- 强度条本身 `aria-hidden`，真实语义由其下的规则清单文本承载——进度条对读屏用户是噪音。
- 全键盘可达：Tab 顺序即视觉顺序，表单内 Enter 提交，`ConfirmDialog`（重新生成邀请码）
  支持 Esc 关闭并在关闭后把焦点还给触发按钮。
- 颜色对比度 ≥ 4.5:1；强度/状态**不单靠颜色**表达，必须同时有文字（「弱 / 中 / 强」）。
- 尊重 `prefers-reduced-motion`：强度条与卡片展开的过渡在该媒体查询下降为无动画。

### 6.3 「团队」页的信息层级

`根管理员` 徽章 > `已停用` 徽章 > `自助注册` 徽章，视觉权重依次递减（clay 实心 → 描边 → 淡灰）。
一行最多同时出现两个徽章。表格在 `md` 以下折叠为卡片列表（邮箱与角色降为次行小字），
避免今天的五列表格在手机上横向溢出。

---

## 7. 风险与缓解

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R-1 | 根管理员口令写在配置/环境变量里，运维可见、可能进版本库 | 提权 | 默认值 `admin123` 在非 debug 且非 TESTING 时**启动即打 warning**；`ops/config.env` 加注释要求覆盖；README 明确「生产必须覆盖」；`.env*` 已在 `.gitignore` |
| R-2 | 邀请码明文存库 | 拿到 DB 即可注册 | 有意取舍（根管理员必须能读回来分发）。缓解：可随时一键 rotate；注册开关可关；`app_settings` 只有根管理员能读；DB 文件本身的访问控制是既有边界 |
| R-3 | 开放注册 = 垃圾账号 / 撞库入口 | 数据污染、资源耗尽 | 单 IP 5 分钟窗口计数（成功也计）；`enabled` 总开关；`default_role` 白名单永不含 admin；`is_active` 让管理员可事后一键停用 |
| R-4 | `ensure_root_admin` 与 `seed_if_empty` 顺序写反 | 全新库丢失全部示例数据 | 顺序在 §2.1 A-3 明确写死；`test_root_admin.py` 用一个「全新库启动后示例需求仍存在」的用例把顺序钉住 |
| R-5 | 新列漏登记 `ADDITIVE_COLUMNS` | 存量 `aragon.db` 全线 `no such column` → 500 | **【v2 · P1-3 改写】** 既有守卫 `test_additive_columns_cover_every_model_column`（`test_schema_sync.py:102-112`）是**单向**的，漏登记时不会红——v1 把它当自动护栏是错的。本轮补一条反向守卫（§8.2 用例 40）+ DoD-3 拿存量 `aragon.db` 实起一次 |
| R-6 | `user_registered` 通知的 `entity_type` 为 `null` | 通知铃点击崩溃 | `NotificationBell.onOpenItem` 已有 `if (n.entity_type && n.entity_id != null)` 守卫（本轮不改）；验收清单里**必须手测一次**点击该条通知 |
| R-7 | 根管理员保护与末任管理员不变量互相遮蔽 | 409 文案答非所问 | 守卫顺序固定：根管理员守卫**在前**（更具体），末任管理员守卫在后；两条各自有独立用例 |
| R-8 | 只在 `TestConfig` 关 `ROOT_ADMIN_BOOTSTRAP` | **【v2 · P0-2 改写】** `file_app` 基类是 `Config` 而非 `TestConfig`（`conftest.py:103`），`test_purge_demo_data.py:150` 的空库上会先被建出 `admin`，再撞上 `_install_legacy_principals()` 的同名插入 → 唯一索引冲突，该文件 **15 条用例集体炸**；三个 CLI 工具还会往目标库写用户行 | §2.1 A-3′ 的「bootstrap 关闭清单」列全 5 处；开工先跑 `pytest -q --collect-only` 记基线（实测 597），收工比对 |
| R-9 | `purge_demo_data` 把已成为根管理员的 seed `admin` 行删掉 | 治理死锁（清完演示数据没人能登录） | 工具层显式跳过 `is_root=True` 的用户行；`test_purge_demo_data.py` 补一条守卫用例 |
| R-10 | 团队页筛选复用 `USERS_KEY` | 指派选择器被筛选结果污染，突然只剩几个人 | §2.3 C-3 明确要求独立 key；前缀失效天然覆盖两者 |
| R-11 | `/signup` 的 409 可用于枚举用户名 | 信息泄露 | 有意接受（邀请码是前置门禁；模糊错误会让真实用户失去可操作反馈）。备案于此，若将来开放无码注册需重新评估 |
| R-12 | 多 worker 部署下若给设置加进程内缓存 | 改了邀请码只有一个 worker 生效 | §2.2 B-1 明令不缓存；每次请求一次索引查询 |
| R-13 | 删除登录页的演示账号填充块导致演示流程受影响 | 演示体验 | README 快速开始改为「默认账号来自 `ROOT_ADMIN_*`（开发默认 `admin` / `admin123`）」，信息不丢失，只是不再在公开页面上以一键按钮的形式暴露（今天是 `app/login/page.tsx:15` 的 `DEMO_ACCOUNTS` + `:102-122` 的点击填充块） |
| **R-14**<br>（v2 · P1-1） | 反代部署下 `remote_addr` 恒为 `127.0.0.1`，注册限流退化为**全站单桶** | 一个人手滑几次就把全公司挡在注册门外；对真攻击者反而无效（他就是那唯一的桶） | `ratelimit.client_ip()` + `TRUST_PROXY_COUNT`（默认 0 = 保持今天行为，反代部署置 1）；`ops/config.env` 与 README 都写明；`/login` 与 `/signup` 共用同一口径 |
| **R-15**<br>（v2 · P1-4） | `ROOT_ADMIN_USERNAME` 可被抢注 → 下次重启即被提为不可降级的根管理员 | 提权 | `/auth/signup` 与 `POST /api/users` 双双拒绝该用户名（共用 `is_reserved_username`，响应体与普通重名 409 完全一致，不额外泄露信息）；`ensure_root_admin` 提权既有账号时必打 warning 并记 user id |
| **R-16**<br>（v2 · P1-8） | `REGISTRATION_DEFAULT_ROLE` 环境变量绕过 `SIGNUP_ROLES` 白名单 | 拿到邀请码即成为管理员 | `get_registration_settings()` 对 `default_role` **无条件**过白名单，库内脏值与配置兜底值一视同仁；§8.2 用例 41 钉死 |
| **R-17**<br>（v2 · P1-6） | 前端通知类型三处镜像里有两处漏改不报错 | 铃铛显示英文原文 `user_registered`，设置页少一个开关，且 `npm run typecheck` 门禁一路绿灯 | 把两个 map 收紧为 `Record<NotificationType, string>`、`TYPES` 改为从 `NOTIFICATION_TYPE_LIST` 派生，让漏改成为编译错误 |
| **R-18**<br>（v2 · P2-8） | `?source=signup` 让任意 member 能枚举「谁是自助注册进来的」 | 微小的信息面扩大 | 有意接受并备案：`GET /api/users` 今天就对全体登录用户开放且返回含 email 的完整 `to_dict()`，本轮不是新增泄露面。收紧它的鉴权是破坏性变更（`AssigneePicker` 等选择器依赖它），属独立一轮 |

---

## 8. 测试与验收标准

### 8.1 质量门禁（硬性）

```powershell
cd backend
python -m pytest -q --collect-only    # 开工前先记基线条数
python -m pytest -q                   # 要求：零失败，且用例总数不低于基线
cd frontend
npm run typecheck         # tsc --noEmit → 0 error
npm run build             # next build → 成功
```

> 按 CLAUDE.md 的要求**相对判据**：不对着任何写死的数字验收，只要求「零失败 + 总数不下降」。
> **【v2 · P2-7】** 评审当日实测基线 = **597 条 / 39 个文件**（CLAUDE.md 里的「380+」与
> v1 引用的数字都已过期）。这个数字**只作为本次评审的记录**，实施者仍须自己现场取一次基线——
> 写死数字正是它过期的原因。
>
> **另外注意：`npm run typecheck` 目前守不住通知类型的镜像**（§2.3 C-1 / R-17）。
> 必须先完成那处类型收紧，这道门禁在本轮才是有效的。

### 8.2 后端用例清单（新增，每条对应一个真实失败模式）

**`test_registration.py`**

1. `signup_creates_user_and_returns_token` —— 201，体形状与 `/login` 一致，可用返回的 token 直接调 `/auth/me`
2. `signup_assigns_configured_default_role` —— 默认 `member`；改设置为 `pm` 后新注册者是 `pm`
3. `signup_marks_source_as_signup` —— `user.source == "signup"`，`is_root is False`
4. `rejects_wrong_invite_code` —— 403 且 `detail.field == "invite_code"`
5. `invite_code_is_case_sensitive` —— `"Aragon"` 被拒
6. `invite_code_accepts_surrounding_whitespace` —— `" aragon "` 通过（只 strip 不改大小写）
7. `rejects_when_registration_disabled` —— 403 `registration is disabled`
8. `rejects_duplicate_username` —— 409
9. `rejects_short_password` / `rejects_single_charclass_password` / `rejects_password_equal_to_username` —— 400 且 `detail.field == "password"`
10. `rejects_non_string_fields` —— `{"username": 123}` → 400 而非 500（与 `test_validation.py` 同一水位）
11. `rejects_non_object_body` —— body 为 `5` / `[1]` / `"x"` → 400
12. `rejects_invalid_email_format` —— 400
13. `rate_limits_after_threshold` —— 第 4 次（`SIGNUP_MAX_ATTEMPTS=3`）返回 429
14. `successful_signups_also_count_toward_limit` —— 连续 3 次成功后第 4 次 429
15. `duplicate_username_race_returns_409_not_500` —— monkeypatch 让预检放行、commit 抛 `IntegrityError`，断言 409 且会话已 rollback
16. `notifies_all_active_admins` —— 两个 admin（一个已停用）→ 只有启用的那个收到 `user_registered`
17. `notification_has_null_entity` —— `entity_type is None and entity_id is None`
18. `respects_notification_preference` —— admin 关掉 `user_registered` 后不再收到
19. `signup_endpoint_is_public` —— 不带 Authorization 头也能 201
20. `admin_register_endpoint_unchanged` —— `POST /auth/register` 仍为 admin-only、仍不校验邀请码（回归守卫）
20a. `rejects_reserved_root_username`（**v2 · P1-4**）—— 用 `ROOT_ADMIN_USERNAME` 注册 → 409，
     且响应体与普通重名 409 **逐字节相同**（不泄露「这是根管理员用户名」）
20b. `admin_create_user_rejects_reserved_username`（**v2 · P1-4**）—— `POST /api/users` 同上
20c. `rate_limit_key_respects_trust_proxy_count`（**v2 · P1-1**）—— `TRUST_PROXY_COUNT=1` 时，
     两个不同 `X-Forwarded-For` 的客户端各自计数、互不牵连；`TRUST_PROXY_COUNT=0`（默认）时
     该头被完全忽略（防伪造回归守卫）

**`test_root_admin.py`**

21. `bootstrap_creates_root_when_absent` / `bootstrap_is_idempotent`（连调两次无副作用）
22. `bootstrap_promotes_existing_username`（同名普通用户被提为 admin + is_root）
23. `bootstrap_restores_demoted_or_deactivated_root`（手工改成 member/停用 → 重跑后归位）
24. `bootstrap_enforces_single_root`（另一行手工置 is_root → 重跑后被清标）
25. `bootstrap_does_not_reset_password_by_default` / `syncs_password_when_flag_on`
26. `seed_runs_before_bootstrap_on_fresh_db` —— 全新库启动后示例需求 / 示例 BUG 仍在（钉死 R-4）
27. `cannot_demote_root` / `cannot_deactivate_root` / `cannot_reset_root_password_as_other_admin` —— 全部 409，且响应体**不含 `allowed` 键**
28. `root_can_change_own_password_via_me` —— `POST /api/me/password` → 200（**v2 · P1-2**：是 POST 不是 PATCH）
29. `root_display_name_and_email_are_editable` —— 200
30. `purge_tool_never_deletes_root_user` —— 在 `test_purge_demo_data.py` 中补
30a. `bootstrap_warns_when_promoting_existing_account`（**v2 · P1-4**）—— 用 `caplog` 断言
     提权路径打出了含 user id 的 warning；`created` 与 `unchanged` 路径**不打**该 warning
30b. `cli_tools_do_not_create_root_admin`（**v2 · P0-2**）—— 在空库上跑
     `purge_demo_data --dry-run`，断言 `users` 表行数**保持为 0**。这条是 P0-2 的回归钉子：
     它同时守住「dry-run 绝不写库」与「运维工具无用户表副作用」两条约定

**`test_app_settings.py`**

31. `defaults_when_no_row` —— 空表下 `get_registration_settings()` 全部回落配置值
32. `patch_persists_and_reads_back` / `patch_is_partial`（只带一个键不影响其余两个）
33. `patch_with_no_recognized_field_returns_400`
34. `rejects_invite_code_too_short` / `too_long` / `with_whitespace` —— 400
35. `rejects_admin_as_default_role` —— 400（白名单只有 member/pm）
36. `rotate_generates_new_code_and_invalidates_old` —— 旧码随后 signup 得 403
37. `requires_root_not_just_admin` —— 普通 admin 调三个端点全 403
38. `corrupt_value_falls_back_to_default` —— 手写 `enabled="yes"` → 回落且不抛异常
39. `registration_meta_is_public_and_leaks_no_code` —— 无 token 可读，响应体**不含** `invite_code`

**v2 新增（补 P0/P1 的回归钉子）**

40. `every_model_column_is_creatable_or_registered`（**P1-3**，落在 `test_schema_sync.py`）——
    对 `db.metadata` 里的每张表的每一列，断言它 ∈（一份**冻结的 create_all 基线列清单**）∪
    `ADDITIVE_COLUMNS`。把既有的单向守卫补成双向：漏登记 `is_root` / `source` 时这条会先红，
    而不是等存量库上线 500
41. `config_default_role_cannot_escape_whitelist`（**P1-8**）—— 把
    `REGISTRATION_DEFAULT_ROLE` 覆盖为 `"admin"` 且 `app_settings` 为空表，
    断言 `get_registration_settings()["default_role"] == "member"`，且随后 signup 出来的人
    **不是** admin
42. `want_query_str_and_bool_reject_garbage`（**P1-5**，落在 `test_project_scope.py` 或
    `test_validation.py`）—— `?role=root` / `?is_active=ture` / `?source=magic` 各 400，
    响应体形状与既有 `want_query_int` 的 `QueryParamError` 契约一致
43. `signup_email_validation_matches_admin_path`（**P0-1**）—— 同一个非法邮箱在
    `/auth/signup`、`POST /api/users`、`PATCH /api/me/profile` 三条路径上得到**同一水位**的 400，
    证明三者确实共用了下沉后的 `validation.want_email`
44. `sync_password_flag_warns_on_every_boot`（**P1-7**）—— `ROOT_ADMIN_SYNC_PASSWORD=true`
    时连起两次 app，两次都打出 warning

> **【v2 · P0-1 的回归钉子在哪】** 循环导入不需要专门写用例：它会让
> `from app import create_app` 直接抛 `ImportError`，**全部 597 条用例同时收集失败**。
> 换句话说，第 1 步跑通 `pytest -q` 就是它的验收。

### 8.3 前端 / 手动验收清单

- [ ] 未登录访问 `/register` 可见表单；填对码 → 直接进 `/dashboard`，右上角头像即新用户
- [ ] 邀请码填错 → 错误出现在邀请码字段下方且焦点回到该字段，不是一个无处着落的 toast
- [ ] 口令强度条与规则清单随输入实时更新；前端拦下的口令，后端也一定拒绝（反之亦然）
- [ ] 根管理员在「设置」页看到「注册配置」卡；普通 admin **看不到该卡**
- [ ] 改邀请码 → 用旧码注册失败、新码成功；关闭开关 → `/register` 变为「未开放」空态
- [ ] 「重新生成」有二次确认，确认后新码立即展示且可一键复制
- [ ] 「团队」页搜索 / 角色 / 状态筛选生效，切换筛选自动回到第 1 页，分页器在总数 ≤ 每页数时不渲染
- [ ] 自助注册的人带「自助注册」徽章；根管理员那一行带「根管理员」徽章，其「停用 / 重置密码」按钮为禁用且有 title 解释
- [ ] 管理员的通知铃收到「新用户 X 通过邀请码注册」；**点击它不跳转也不报错**（R-6）
- [ ] 指派选择器的人员列表不受团队页筛选影响（R-10）
- [ ] 手机宽度下注册页折叠为单栏、团队页折叠为卡片列表，均无横向滚动
- [ ] 全流程可纯键盘完成；读屏可读到校验错误
- [ ] **（v2 · P1-2）** 根管理员本人在设置页改密走的是 `POST /api/me/password` 且 200
- [ ] **（v2 · P1-6）** 通知铃里这条通知显示的是中文标签与专属图标，**不是** `user_registered` + 🔔；
      设置页的通知偏好里能看到并关掉它
- [ ] **（v2 · P1-1）** 若在反代后验收：两台不同外网 IP 的机器各自计数，不互相牵连

### 8.4 Definition of Done

1. §8.1 三道门禁全绿，且后端用例总数**不低于**开工基线。
2. §8.2 全部用例存在且通过；§8.3 清单逐条手测通过。
3. 存量 `backend/aragon.db` 直接启动新代码：`schema_sync` 补出两列，能登录、能看板、能注册。
4. 删库重启：seed 8 行 + 根管理员 = 与今天完全一致的开箱体验（默认配置下 users 表仍只有 1 行）。
5. `README.md` 配置表与 `docs/iterations.md` 已更新；`CLAUDE.md` 补上根管理员与 purge 守卫两条注记。
6. 全部改动满足 CLAUDE.md 阈值：单文件 ≤800 行、单方法 ≤50 行、形参 ≤5、圈复杂度 ≤10、嵌套 ≤4。
7. **【v2】评审记录（§0）中的 P0 与 P1 逐条落地**，特别是这四条最容易被跳过的：
   ① `services/avatars.py` / `validation.want_email` 已下沉，`routes/auth.py` **没有**
   `from routes.users import ...`（P0-1）；② `ROOT_ADMIN_BOOTSTRAP` 的五个关闭点全部到位，
   `tests/test_purge_demo_data.py` 全绿（P0-2）；③ `TRUST_PROXY_COUNT` 已进 `README.md` 与
   `ops/config.env`（P1-1）；④ `lib/constants.ts` 的两个 map 已收紧为
   `Record<NotificationType, string>`（P1-6）。

---

## 9. 建议实施顺序（每步独立可提交、可回滚）

0. **【v2 新增 · 纯重构，必须第一步做】拆依赖**：新建 `services/avatars.py::pick_color`，
   把 `validation.want_email` 下沉，四 / 三个调用点改读；补 `scope.want_query_str` /
   `want_query_bool` 与 `ratelimit.client_ip()`。此步**对外零行为变化**，
   跑一次 `pytest -q` 必须与基线逐条相同。放在最前面是因为 P0-1 的循环导入一旦发生，
   后续每一步都会在 `import app` 处炸掉，无法二分定位。
1. **数据层**：`users` 两列 + `ADDITIVE_COLUMNS` 登记 + 反向漂移守卫（P1-3）+
   `app_setting.py` + `models/__init__.py` 两处登记。
   跑一次 `pytest -q`，确认存量全绿（此步对外零行为变化）。
2. **根管理员**：`config.py` 配置项 + **§2.1 A-3′ 的五个 bootstrap 关闭点（P0-2，与本步同一提交）** +
   `services/bootstrap.py` + `app.py` 接线 + `seed.py` 改读配置 + `lifecycle` 保护 +
   `routes/users.py` 守卫 + 保留用户名守卫（P1-4）+ `test_root_admin.py`。
3. **设置服务与端点**：`services/app_settings.py` + `auth_helpers.require_root` + `routes/settings.py` +
   蓝图注册 + `test_app_settings.py`。
4. **自助注册**：`services/passwords.py` + `routes/auth.py::signup` / `registration_meta` +
   `notifications.notify_user_registered` + 通知类型 + `test_registration.py`。
5. **前端公开侧**：`AuthSplitLayout` 抽取 → `/register` 页 + `RegisterForm` + `PasswordStrength` +
   `useRegistrationMeta` + `auth.tsx::signup` + 登录页改造。
6. **前端管理侧**：`RegistrationCard` + `useRegistrationSettings` + 设置页挂载 +
   团队页筛选/分页/徽章 + `MemberFormModal` 根管理员禁用态。
7. **治理与文档**：`purge_demo_data` 的 `is_root` 守卫 + README / iterations.md / CLAUDE.md。

---

## 10. 明确不做（Non-Goals）

- **邮箱验证 / 找回密码**：需要 SMTP 依赖与外发邮件通道，是独立一轮的量级。
- **注册审批队列**（注册后置为 pending、管理员审批才能登录）：本轮用「邀请码 + 可事后停用」
  达到同等治理效果，复杂度低一个数量级。若将来确实需要，`users.source` 已经为它留好了识别依据。
- **统一全站口令策略**：收紧 `POST /api/users` 与 `POST /api/me/password` 会破坏存量契约与存量用例，
  需要单独一轮 + 存量用户的过渡期设计。
- **多根管理员 / 组织级 RBAC 重构**：本轮的 `is_root` 是**单个**治理锚点，不是新的角色维度。
- **SSO / OAuth / LDAP 接入**：与本轮的本地账号体系正交，属于另一条演进线。
- **分布式限流**：`services/ratelimit.py` 仍是单机内存实现（模块 docstring 里的
  `TODO(ratelimit-distributed)` 依旧成立），多副本部署需换 Redis 后端。
  **【v2 注】** 本轮新增的 `client_ip()` 只解决「反代下 IP 全都一样」这一个问题（R-14），
  **不**解决「多 worker / 多副本各算各的」——`ops/templates/aragonteam-backend.service`
  下 gunicorn 若开多 worker，`SIGNUP_MAX_ATTEMPTS` 的实际生效阈值是 `N × 配置值`。
  这与既有 `/login` 限流是完全相同的性质与相同的已知缺口，本轮**有意不扩大战场**。
- **统一全站保留用户名机制**：本轮只把 `ROOT_ADMIN_USERNAME` 一个名字设为保留（R-15），
  没有引入通用的保留字表（`admin` / `system` / `root` / `api` …）。真需要时它是
  `services/app_settings.py::is_reserved_username` 的一次内部扩展，不影响任何契约。

---

## 11. 评审结论（Review Verdict）

### **有条件通过（Approved with Conditions）**

这是一份**质量显著高于平均水平**的设计文档：它对本仓库既有约定的引用大部分是准确的
（`app.py` 的启动顺序、`ADDITIVE_COLUMNS` 硬约束、`notify()` 的四条跳过条件、
`invalidateAdminViews` 的前缀失效、`NotificationBell` 的 `entity_type` 守卫、
lifecycle 三种 409「不带 `allowed` 键」的分流理由、`escape_like` + `escape="\\"` 的两步用法、
`json_body()` 对非对象体的归一——逐条核对均属实），
风险表里 R-4 / R-6 / R-9 / R-10 / R-12 都是**只有读过这份代码的人才提得出来**的真问题。
scope 也是克制的：一张新表、两个 additive 列、一个新蓝图，`/auth/register` 逐字不动。

拦下它的是**四个会真实伤人的缺陷**，其中两个是 P0：一个循环导入会让应用整体起不来（P0-1），
一个错误的测试环境假设会让 15 条存量用例集体变红并让三个运维 CLI 开始写用户表（P0-2）；
另外两条安全缺口——反代下限流退化为全站单桶（P1-1）、以及一个环境变量即可让自助注册
直接产出管理员（P1-8）——都发生在「兜底路径」上，恰恰是最容易被认为「已经有白名单挡着了」
的地方。这四条的共同特征是：**它们都不是设计思路的错误，而是"没有把假设拿去和代码对一遍"**。
v2 已在正文中逐条修复。

**放行条件（全部为可机器验证的硬条件，缺一不可）：**

1. **§0 的 P0-1 / P0-2 必须在第 0 步与第 2 步各自的提交里落地并验证。**
   具体判据：`backend/routes/auth.py` 中**不存在**任何 `from routes.users import ...`；
   `python -m pytest -q tests/test_purge_demo_data.py` 全绿；
   §8.2 用例 30b（空库跑 `purge_demo_data --dry-run` 后 `users` 行数仍为 0）通过。
2. **§0 的六条 P1 各自对应的用例（20a / 20b / 20c / 30a / 40 / 41 / 42 / 43 / 44）必须存在并通过。**
   P1 的修复如果没有钉子钉住，下一轮重构就会把它们悄悄弹回来——尤其是 P1-3 与 P1-6
   这两条，它们**本身就是「以为有护栏、其实没有」**的产物。
3. **`README.md` 与 `ops/config.env` 必须同时写明 `TRUST_PROXY_COUNT`（反代部署置 1）
   与 `ROOT_ADMIN_PASSWORD`（生产必须覆盖）。** 这两条是纯部署侧的，代码里没有任何东西
   会在它们缺失时报警；文档就是它们唯一的载体。
4. **收工时按 §8.1 用 `pytest -q --collect-only` 现场取一次基线并与开工前比对**，
   要求零失败且总数不下降（评审当日实测 597 条，仅供参照，不作为验收数字）。

**明确不作为放行条件的：** §0 的全部 P2。它们已在 v2 中一并处理或备案，
若实施过程中有一两条因为工期被推迟，只需在 `docs/iterations.md` 里记一笔，不必回来重评审。

**下一轮的建议输入**（本轮 Non-Goals 中优先级最高的两条）：
统一全站口令策略（今天 `POST /api/users` 与 `POST /api/me/password` 完全没有长度约束，
前端 `MemberFormModal` 的 ≥6 位是纯客户端的），以及找回密码通道
（本轮把「忘密码」的唯一出路压在 `ROOT_ADMIN_SYNC_PASSWORD` + 两次重启上，
这对根管理员勉强可接受，对普通成员完全不可接受——他们今天只能去找管理员代改）。

---

## 12. 实施过程发现的方案缺陷（Issues Found During Implementation）

按 §「Constraints」的要求记录：下列各条都是**照着 v2 写会踩到**的偏差，实施时已按
「记录 + 采用修正方案」处理，未静默偏离。

| # | 位置 | 方案里写的 | 实际情况与已采用的处置 |
|---|---|---|---|
| **F-1** | §3.5 / 放行条件 3 —— `ops/config.env` | 「把 `ROOT_ADMIN_PASSWORD` 与 `TRUST_PROXY_COUNT=1` 补进 `ops/config.env`」，语气上把该文件当作运行时配置源 | **`ops/config.env` 不会把变量传给后端进程。** 它只被 `ops/install.sh` `source` 一次（用于生成 systemd unit、nginx 站点等）；后端进程实际读的是 `templates/aragonteam-backend.service:16` 的 `EnvironmentFile=/etc/aragonteam/aragonteam.env`，而**仓库里没有任何脚本创建那个文件**。照 v2 写完，运维会以为已经设好了 `TRUST_PROXY_COUNT=1`，实际线上仍是默认 0——正是 R-14 那个全站单桶。**处置**：两项仍按放行条件写进 `ops/config.env`（它确实是运维查「这套部署怎么配的」的第一现场），但配上一段显式说明——真正生效的位置是 `/etc/aragonteam/aragonteam.env`，需要人工拷过去并重启。**未做**：改 `install.sh` 去生成那个 env 文件——那超出本轮 scope（会改变部署脚本的契约），应当作为独立一轮的 ops 改动 |
| **F-2** | §8.2 用例 30a / 44 —— `caplog` 断言 | 「用 `caplog` 断言 bootstrap 打出了 warning」 | **`caplog` 在本项目里抓不到 app logger。** `observability.py:38` 执行 `root.handlers = [handler]`，每次 `create_app` 都把 pytest 挂在 root 上的捕获 handler 整个换掉。照 v2 写的用例恒为 0 条记录、永远失败。**处置**：`tests/test_root_admin.py` 内提供 `captured_warnings()` 上下文管理器，直接把收集 handler 挂到 `logging.getLogger("app")`（该 logger 不被那行代码触及）。断言语义与 v2 完全一致 |
| **F-3** | §8.2 用例 44 —— `sync_password_flag_warns_on_every_boot` | 与 §2.1 A-3 的 `if ROOT_ADMIN_SYNC_PASSWORD and not TESTING` 直接冲突 | `file_app` 的 `attrs` 里恒有 `TESTING: True`，故该 warning 在测试里默认被静音，用例必然为 0 条。**处置**：保留 A-3 的 TESTING 静音（它是对的——否则每个用例都刷两行 warning，真告警会被淹没），用例改为显式 `make(seed=False, TESTING=False, …)` 打开它。断言「连起两次、两次都打」不变 |
| **F-4** | §8.2 现有用例 `test_adds_missing_column_to_existing_table` | 未提及 | 该用例硬断言 `applied == ["users.is_active"]`，而本轮新增的 `users.is_root` / `users.source` 会让同一份 legacy 库补出三列。**处置**：断言更新为三列全补。这是「加列必然带动的既有断言」，不是行为回归 |
| **F-5** | §2.1 A-3 —— seed 的头像底色 | 「`seed.py` 的 `_COLORS` 改读 `services/avatars`」 | 字面照做有两种读法：`avatars.PALETTE[0]`（原值 `#C15F3C`）或 `avatars.pick_color(username)`（对 `admin` 会算出 `#4B8B8B`）。后者会让**存量演示账号的头像颜色无缘无故变一次**。**处置**：seed 用 `PALETTE[0]` 保持逐字节相同；`ensure_root_admin` 新建账号时才用 `pick_color`（那是一个此前不存在的行，没有「变色」问题） |
| **F-7** | §2.2 B-4 / R-15 —— 保留用户名的覆盖面 | 只要求 `POST /auth/signup` 与 `POST /api/users` 两条路径加保留名守卫 | **第三条建号路径 `POST /api/auth/register` 没有被覆盖**，而它同样能建出任意用户名。触发条件与 R-15 描述的窗口完全相同（改了 `ROOT_ADMIN_USERNAME` 但尚未重启、或 `ROOT_ADMIN_BOOTSTRAP=false`），只是提权方向从「任何拿到邀请码的人 → root」收窄为「admin → root」。**处置：不修**——§2.2 B-2 与放行条件都把「`/auth/register` 契约逐字不变」立为硬约束（`test_admin_register_endpoint_unchanged` 正是它的回归钉子），本轮不应该为一个更窄的边缘路径破这条约束。**备案**：`/auth/register` 与 `POST /api/users` 本就是两份高度重复的建号实现，合并它们（届时守卫自然统一）是下一轮的合理输入 |
| **F-6** | §2.2 B-2 第 1 步 —— 限流计数时机 | 只说「成功与失败都 `record_failure`」，未说清相对于 `is_blocked` 的先后 | 若先处理请求再计数，`SIGNUP_MAX_ATTEMPTS=3` 时实际放行 4 次。**处置**：实现为「`is_blocked` 判定 → 立即 `record_failure` → 再处理」，于是第 4 次请求被拦，与用例 13「第 4 次返回 429」一致 |

以上均**不影响** §11 的四条放行条件：F-1 的两项文档仍已落到 `README.md` 与 `ops/config.env`
（并额外指明了真正的生效位置），F-2 / F-3 是用例写法的修正而非删减，F-4 / F-5 / F-6
是实现细节的收敛。
