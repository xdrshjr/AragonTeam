# 账号与通知设置：自助资料 / 改密 / 通知偏好（account-settings）开发方案

> 文档版本：**v2**（Subtask #0 产出 → Subtask #1 设计评审修订；新增「评审记录 / 评审结论」，P1 已在正文直接修复）
> 迭代：Loop Iteration 2/5 · 阶段目标「对项目中的所有 mock / 占位逻辑真实化，完善接口与功能，稳健可靠」
> 前置：Iteration 1 已把项目**唯一的业务 Mock**（Agent 执行引擎罐头文案）真实化（见 `docs/plans/real-agent-execution/spec.md`，commit `12c5a4c`）。
> 语言约定：正文中文（沿用既有 spec 风格），标识符 / 契约 / 代码英文。

---

## 评审记录（Review Notes · Subtask #1 设计评审）

> 评审人：资深评审（Anthropic Eng）｜方法：对全仓逐文件核验后按四维（可行性 / 完备性 / 一致性 / 规模适配）逐节评审。
>
> **核验结论**：设计与现有技术栈**高度契合**，几乎每一处对既有代码的断言均经核验属实——`me` 蓝图 `url_prefix="/api/me"` 与 `jwt_required`/`current_user`（`routes/me.py`）、`notify()` 的「跳过自己」接缝与调用点 `type` 全 ∈ 六元组（`services/notifications.py`）、`NOTIFICATION_TYPES` 逐字为 `assigned/commented/mentioned/status_changed/agent_advanced/converted`（`models/notification.py`）、`User.{display_name(128),email(255),avatar_color(9),updated_at(onupdate)}` 与 `set_password(pbkdf2:sha256)`（`models/user.py`）、`import models` 后 `db.create_all()` 加性建表（`app.py:62-66` + `models/__init__.py`）、`swr ^2.2.5` 依赖与 `swrFetcher`（`package.json`/`lib/api.ts`）、`Input` 以 `{...rest}` 透传 `type`（`components/ui/Input.tsx`）、`constants.ts` 的 `NOTIFICATION_LABELS/ICONS` 六类、`api.{get,post,patch,del}` 与 `ApiError.allowed`（`lib/api.ts`）、conftest 的 `app/client/auth/data` fixtures 及 `member2`（`tests/conftest.py`）、既有 **125** 例 pytest（`pytest --collect-only` 实测）——均一一属实。**无 P0**。发现 **1 个 P1**（并发 upsert 竞态）与 6 个 P2，P1 已在本 v2 正文直接修复。

| 编号 | 维度 | 严重度 | 位置 | 问题 | 处置 |
|------|------|--------|------|------|------|
| P1-1 | 健壮性/完备性 | **P1** | §5 `set_preferences` | check-then-insert 非并发安全：服务器 `threaded=True`（`app.py:80`），同一 `(user_id,type)` 的两次重叠 PATCH（乐观 UI 快速连拨）可能双双走 INSERT，撞 `uq_notif_pref_user_type` 唯一约束 → 未捕获 `IntegrityError` → 500 | **本版已修**：路由 commit 包 `try/except IntegrityError → rollback → 重跑一次 set_preferences`（行已存在走 UPDATE，bool 幂等收敛）；见 §3.2(C)、§4、§5、§6.4、§9、§10 R10 |
| P2-1 | 一致性 | P2 | §6 各端点 | 空用户（合法 token 但用户已删，`current_user() is None`）兜底码不统一：`auth.py /me` 返 404、`me.py /work` 返 401 | 本版 §6 统一为 **401**（与同蓝图 `my_work` 一致） |
| P2-2 | 一致性 | P2 | §3.2/§6 | 请求体解析未点明全仓统一写法 `request.get_json(silent=True) or {}`（缺 `Content-Type` 的畸形体须降级为 `{}` 而非 415/500） | 本版 §6 显式声明沿用该约定 |
| P2-3 | 语义 | P2 | §3.1 偏好闸 | `notify_claim` 复用 `type="assigned"`：静音「指派」将**同时**静音「Agent 认领」提醒 | 本版 §3.1 标注为**有意合并**（模型枚举注释即「指派/自主认领」），非缺陷，供实现者知悉 |
| P2-4 | 完备性 | P2 | §9 集成用例 | 叙述用 alice/bob，需映射到 conftest 既有 fixtures | 本版 §9 标注 alice→`member`、bob→`member2` |
| P2-5 | 性能 | P2 | §3.2(C) | `notify_comment/advance` 按收件人循环，每人一次 `is_enabled` SELECT（事件级 N 次查询） | MVP 单机量级可接受；§10 R11 记录未来可「每事件一次 `effective_map` 批量取」的优化点 |
| P2-6 | 规模适配 | P2 | §10 R9 | R9「`ui/Input` 是否透传 `type=password` 未知」已可判定 | 本版 R9 由「未知风险」降级为「已核实解除」 |

---

## 0. 剩余 Mock / 占位全盘点（本轮选题依据）

对全仓一次系统审计（前后端逐页 + `services/*` + `routes/*`）后确认：**业务路由中已无任何伪造 / 硬编码的 API 响应**，所有读接口均落库真实数据；Agent 执行引擎已在上一轮真实化。剩余的「占位 / 未接线 / 半成品」清单如下（按用户可见影响排序）：

| # | 位置 | 现状 | 类型 | 本轮 |
|---|------|------|------|------|
| A1 | `frontend/app/(app)/settings/page.tsx:10-68` | 设置页只读展示头像/用户名/邮箱/角色 + 登出；第 62-64 行明写「MVP 阶段设置项为占位；后续将支持修改资料、密码与通知偏好」 | 前端占位（且后端亦无对应端点） | **✅ 纳入** |
| A2 | `backend/routes/me.py` / `routes/auth.py` | 无自助资料 / 改密端点；唯一改用户端点是 `PATCH /api/users/<id>`（`@require_role("admin")`），普通成员改不了自己 | 前后端均缺 | **✅ 纳入** |
| A3 | 通知偏好 | 全仓无模型 / 路由 / UI；`notify()` 无条件扇出，用户无法静音任一类型 | 前后端均缺 | **✅ 纳入** |
| A4 | `backend/services/llm/config.py:49,60-74` | LLM 凭据仅 `AGENT_LLM_*` 环境变量、显式「不落库」 | 运行时无配置端点 / UI | **❌ 本轮不做**（见 §11） |
| B5 | `frontend/components/layout/Header.tsx:48-55` | 全局搜索框恒 `push('/requirements?q=')`，占位文案称「搜索需求 / BUG」但 BUG 永不可达 | 前端半成品 | ❌ 后续迭代 |
| B6 | `frontend/app/(app)/bugs/page.tsx` | 未监听 `aragon:search` 事件；后端 `bugs.py` 的 `q` ilike 搜索能力闲置 | 缺集成 | ❌ 后续迭代 |
| C7 | `frontend/components/collab/CommentComposer.tsx` | 纯 textarea，占位宣传「@用户名 可提醒」但无自动补全（后端 `notify_mentions` 已能解析 @） | 前端缺 UI | ❌ 后续迭代 |
| D8-11 | `routes/projects.py` / `POST /users` / `POST /agents` / `PATCH /agents` | 后端存在但前端无入口（项目 API、建用户、建/改 Agent；Team 页仅提交 `role`） | 后端能力无前端 | ❌ 后续迭代 |
| E12 | `backend/seed.py` | 幂等示例种子（受 `SEED_ON_STARTUP` 门控，测试关闭），文档已声明「示例种子而非业务 Mock」 | 设计如此 | ❌ 不需改 |
| F13 | `dashboard/page.tsx:53` `href:"/dashboard"` 自链接；`TicketDrawer` 取消指派 toast 提示不支持 | 轻微 no-op | ❌ 不阻塞 |

**选题结论**：本轮聚焦 **A1–A3** —— 把项目**最后一处显式用户占位（设置页）** 真实化为端到端可用的「账号自助中心」，落地三块高内聚能力：① 个人资料编辑；② 修改密码；③ 通知偏好（并在扇出唯一收口 `notify()` 处真正生效）。B/C/D 作为 §11「后续迭代路线」明确交棒给 Iteration 3–5，保证整个 Loop 的「所有接口与功能」目标可追踪、可收敛，而非本轮贪多导致质量塌陷。

---

## 1. 概述（Overview）

AragonTeam 是「AI 时代（Agent 可参与协作）的研发协作管理平台」。经上一轮真实化，平台的业务主链路（鉴权、需求/BUG 看板、指派、状态机流转、评论/时间线、通知扇出、Agent 自主执行）均已由真实数据与真实 LLM 驱动。全仓审计显示，唯一仍以文字自认「占位」的用户界面是**设置页**——它只读展示账号信息，既不能改资料、也不能改密码、更没有通知偏好；对应的后端端点也完全缺失（普通成员只能靠管理员 `PATCH /api/users/<id>` 间接改动）。这是当前用户体验上最刺眼、也最容易触发「这平台还没做完」观感的缺口。

本方案把设置页真实化为一个**自助账号中心**，覆盖三项高内聚能力：**（1）个人资料编辑**——成员自助改 `display_name` / `email` / 头像底色，改完 Header 头像即时刷新；**（2）修改密码**——校验旧密码后设新密码，复用既有 `pbkdf2:sha256` 哈希；**（3）通知偏好**——按 6 类通知（指派 / 评论 / 提及 / 状态流转 / Agent 推进 / 转 BUG）逐类开关，且在通知扇出的**唯一收口** `services/notifications.notify()` 处前置生效——被静音的类型根本不落库。三者都是**成员自助**（`jwt_required`，作用于「当前登录用户自身」），与既有 admin-only 的用户管理（Team 页）职责正交、互不干扰。

设计的第一性原则是**稳健与向后兼容**：全部新增能力只挂在既有 `me` 蓝图（`/api/me`）与既有 `notify()` 收口上，**不改任何既有返回 shape、不改任何既有既存表的列**。通知偏好的存储采用**一张加性新表** `notification_preferences`——因为 `db.create_all()` 只会「补建缺失的表」，**不会 ALTER 既有表加列**；给 `users` 加列会让线上既有 `aragon.db` 在不写迁移时直接崩，而加一张新表则零迁移、开箱即建（完全复用 Phase-3 引入 `notifications` 表时验证过的向后兼容策略）。偏好语义取「**缺省全开**（无行即启用）」，因此**在无人静音时，`notify()` 行为逐字节不变，既有 125 个 pytest 用例全部无需改动即绿**。

---

## 2. 目标与非目标

**目标（Definition of Done 对齐）**
- 设置页从只读占位变为三块真实可用卡片，全部接线真实后端。
- 后端新增 4 个自助端点 + 1 张加性表 + 1 个偏好服务，并在 `notify()` 前置偏好闸。
- 通知静音端到端生效：静音某类型后，该类型通知不再产生（其它人 / 其它类型不受影响）。
- 质量门：`pytest -q` 全绿（既有 125 + 新增 ≈ 15）；前端 `npm run typecheck` + `npm run build` 零错误。
- 向后兼容：无既有表列变更、无既有接口 shape 变更、无 seed 依赖变更。

**非目标（本轮明确不做，见 §11）**
- 运行时配置 LLM 凭据（安全反模式，坚持 env-only）。
- 全局搜索覆盖 BUG、@提及自动补全、项目/建用户/建 Agent 的管理 UI。
- 密码策略强度校验器（大小写/符号）、双因子、邮箱验证发信、JWT 主动吊销。

---

## 3. 技术设计（Technical Design）

### 3.1 架构与接缝

自助能力全部落在**既有 `me` 蓝图**（`backend/routes/me.py`，`url_prefix="/api/me"`），与它现有的 `GET /api/me/work` 同域，符合「/api/me 承载当前用户自身视角」的语义（该蓝图注释已强调路由不得逃逸 `url_prefix`）。这样新增端点天然带 `jwt_required`，且**不新增蓝图、不改 `register_blueprints`**。

数据侧只加**一张加性表**：`notification_preferences(user_id, type, enabled)`，每 `(user_id, type)` 一行、唯一约束收敛。缺省语义「无行=启用」，所以既有用户零回填。偏好读写封装进新的 `services/notification_prefs.py`，对外仅暴露三个纯函数：`effective_map(user_id)` / `is_enabled(user_id, type)` / `set_preferences(user_id, mapping)`。

**扇出闸的唯一插入点**：`services/notifications.notify()` 是所有事件级 helper（`notify_assignment/comment/advance/convert/mentions/claim`）落库前的唯一收口。只需在其「跳过自己」判断之后加一行偏好闸——被静音则 `return None`，其余逻辑一字不改。因为通知 `type` 取值集合与 `NOTIFICATION_TYPES`（`assigned/commented/mentioned/status_changed/agent_advanced/converted`）逐字一致，闸判定无需任何映射。**语义提示**〔P2-3〕：`notify_claim`（Agent 认领源单）复用 `type="assigned"`，故用户静音「指派」将**同时**静音「Agent 认领我的单」提醒——这与模型枚举注释「`assigned` = 指派 / 自主认领」一致，属**有意合并**而非缺陷；`NOTIFICATION_LABELS["assigned"]="指派"` 已隐含此语义，实现者知悉即可（如需拆分须新增枚举，属后续迭代）。

前端把 `settings/page.tsx` 从只读页重写为三卡容器，拆出 `components/settings/{ProfileCard,PasswordCard,NotificationPrefsCard}.tsx` 三个受控组件（每文件 < 800 行、每方法 < 50 行，符合 CLAUDE.md 阈值）。资料保存成功后调用 `AuthProvider` 新增的 `applyUser(user)` 就地刷新登录态（Header 头像/名字即时更新，免二次 `GET /auth/me`）。偏好卡走新 hook `useNotificationPreferences`（SWR + 乐观更新 + 失败回滚），复用既有 `ui/Toggle`（本轮新增的极小开关组件）。

### 3.2 关键代码路径与序列

**（A）改资料** `PATCH /api/me/profile`
```
SettingsPage → ProfileCard 提交
  → api.patch("/me/profile", {display_name?, email?, avatar_color?})
  → me.update_profile: current_user() → 白名单键校验(长度/邮箱正则/#RRGGBB)
      → 命中即写字段（username/role 恒忽略）→ db.commit → 返回 {user}
  → ProfileCard: applyUser(user) + toast「资料已更新」；Header 头像即时刷新
```

**（B）改密码** `POST /api/me/password`
```
PasswordCard 提交(current,new,confirm；前端先校 new==confirm & 长度)
  → api.post("/me/password", {current_password, new_password})
  → me.change_password: current_user()
      → check_password(current) 失败 → 400「current password is incorrect」
      → len(new)∉[6,128] → 400；new==current → 400「must differ」
      → set_password(new)（pbkdf2:sha256）→ db.commit → 200 {ok:true}
  → PasswordCard: 清空三框 + toast；JWT 无状态不吊销（§10 R4）
```

**（C）通知偏好读/写 + 扇出生效**
```
读: NotificationPrefsCard mount → useNotificationPreferences (SWR GET /me/notification-preferences)
    → effective_map: 6 类缺省 True，被存量行覆盖 → 渲染 6 个 Toggle
写: 拨动某 Toggle → 乐观置位 → api.patch("/me/notification-preferences",{preferences:{[type]:next}})
    → me.update_notification_preferences: get_json(silent=True) or {} → 校验 type∈NOTIFICATION_TYPES & 值为 bool
        → set_preferences upsert（无行则 add，有行则改 enabled）
        → try: db.commit  except IntegrityError: rollback → set_preferences 重跑一次（并发下另一请求已 INSERT，此时走 UPDATE）→ commit  〔P1-1〕
        → 返回全量 effective_map
    → 失败则 SWR 回滚 + toast
生效: 任一事件 → notify_*(...) → notify(user_id,type,...)
        → 跳过自己后：if not notification_prefs.is_enabled(user_id,type): return None
        → 命中静音则不落 Notification 行（no_autoflush 读，避免写事务提前 flush）
```

---

## 4. 文件 / 模块变更计划（File / Module Change Plan）

### 后端（`backend/`）

| 文件 | 动作 | 一句话意图 |
|------|------|-----------|
| `models/notification_preference.py` | **新增** | `NotificationPreference` 模型：`(user_id, type, enabled)` + 唯一约束 `uq_notif_pref_user_type` + `to_dict` |
| `models/__init__.py` | 改 | 追加 `from .notification_preference import NotificationPreference` 并加入 `__all__`（保证 `create_all` 注册新表） |
| `services/notification_prefs.py` | **新增** | 偏好服务三函数 `effective_map` / `is_enabled`（`no_autoflush` 读）/ `set_preferences`（upsert，不 commit） |
| `services/notifications.py` | 改 | `notify()` 在「跳过自己」后前置一行偏好闸：`if not notification_prefs.is_enabled(user_id, type): return None`；顶部 `from services import notification_prefs` |
| `routes/me.py` | 改 | 新增 `PATCH /profile`、`POST /password`、`GET /notification-preferences`、`PATCH /notification-preferences` 四端点；请求体统一 `request.get_json(silent=True) or {}`〔P2-2〕；空用户兜底返 **401**（与同蓝图 `my_work` 一致）〔P2-1〕；写偏好的 commit 包 `try/except IntegrityError → rollback → 重跑一次 set_preferences`〔P1-1，需 `from sqlalchemy.exc import IntegrityError`〕；补充 import 与邮箱/颜色正则常量 |
| `tests/test_settings.py` | **新增** | 覆盖资料/改密/偏好三块正常 + 异常路径，及「静音后不扇出」集成用例（≈15 例） |

> 说明：**无需改 `app.py`**——`import models` 已触发 `models/__init__` 加载全部表定义，`create_all()` 自动补建 `notification_preferences`。**无需改 `routes/__init__.py`**——端点挂既有 `me` 蓝图。

### 前端（`frontend/`）

| 文件 | 动作 | 一句话意图 |
|------|------|-----------|
| `app/(app)/settings/page.tsx` | **重写** | 三卡容器（Profile / Password / NotificationPrefs）+ 登出；移除占位文案 |
| `components/settings/ProfileCard.tsx` | **新增** | 受控表单：`display_name`/`email`/头像底色调色板；`api.patch` + `applyUser` + toast |
| `components/settings/PasswordCard.tsx` | **新增** | 三密码框；前端校 `new==confirm` 与长度；`api.post` + 清空 + toast |
| `components/settings/NotificationPrefsCard.tsx` | **新增** | 6 类通知 Toggle 行（图标/中文名取 `constants`）；调 `useNotificationPreferences.setPreference` |
| `components/ui/Toggle.tsx` | **新增** | 无依赖可复用开关（`role="switch"` + `aria-checked`，键盘/可达） |
| `hooks/useNotificationPreferences.ts` | **新增** | SWR `GET /me/notification-preferences` + `setPreference` 乐观更新/回滚 |
| `lib/auth.tsx` | 改 | `AuthState` 新增 `applyUser(u: User): void`；`applyUser = useCallback(u=>setUser(u),[])` 并入 provider value |
| `lib/types.ts` | 改 | 新增 `NotificationPreferences = Record<NotificationType, boolean>` 与 `ProfileUpdate` 载荷类型 |

---

## 5. 数据模型（Data Model）

**新表 `notification_preferences`**（加性；`create_all` 首启自动建；对既有 `aragon.db` 零迁移；不改 `users`/`notifications` 任何既有列）：

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| `id` | Integer | PK | |
| `user_id` | Integer | NOT NULL, index | 收件人 = 人类 `User.id` |
| `type` | String(32) | NOT NULL | ∈ `NOTIFICATION_TYPES` |
| `enabled` | Boolean | NOT NULL, default `True` | `False` = 静音该类型 |
| `created_at` | DateTime | NOT NULL, default `utcnow` | |
| `updated_at` | DateTime | NOT NULL, `onupdate=utcnow` | |

约束：`UniqueConstraint("user_id", "type", name="uq_notif_pref_user_type")`。

**缺省语义**：某 `(user_id, type)` 无行即视为 `enabled=True`；仅当用户显式关闭才落一行 `enabled=False`（再次开启则 upsert 回 `True`）。因此**既有用户无需回填**，且**无人静音时 `notify()` 行为不变**。

**模型骨架**（`models/notification_preference.py`）：
```python
from extensions import db, utcnow
from models.notification import NOTIFICATION_TYPES  # 逐字复用 6 类枚举

class NotificationPreference(db.Model):
    __tablename__ = "notification_preferences"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    type = db.Column(db.String(32), nullable=False)      # ∈ NOTIFICATION_TYPES
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    __table_args__ = (
        db.UniqueConstraint("user_id", "type", name="uq_notif_pref_user_type"),
    )
    def to_dict(self) -> dict:
        return {"type": self.type, "enabled": self.enabled}
```

**偏好服务**（`services/notification_prefs.py`，含关键健壮性注释）：
```python
from extensions import db
from models.notification import NOTIFICATION_TYPES
from models.notification_preference import NotificationPreference

def effective_map(user_id: int) -> dict:
    """6 类通知的有效开关：缺省 True，存量行覆盖。"""
    stored = {p.type: p.enabled
              for p in NotificationPreference.query.filter_by(user_id=user_id).all()}
    return {t: stored.get(t, True) for t in NOTIFICATION_TYPES}

def is_enabled(user_id: int, ntype: str) -> bool:
    """扇出前置闸；未知类型默认放行。读包在 no_autoflush 内——notify() 处于写事务中
    （工单/评论已 add 未 flush），此 SELECT 不得触发 autoflush 提前刷未完成对象。"""
    with db.session.no_autoflush:
        row = NotificationPreference.query.filter_by(user_id=user_id, type=ntype).first()
    return row.enabled if row is not None else True

def set_preferences(user_id: int, mapping: dict) -> None:
    """按 type->bool 逐项 upsert（不 commit，随路由事务提交）。

    并发注记〔P1-1〕：本函数只做「查-改/增」，不 commit；唯一约束
    (uq_notif_pref_user_type) 的冲突处理由**路由收口**——服务器 threaded=True，
    同一 (user_id, type) 的两个重叠请求可能双双走 INSERT，路由须
    `except IntegrityError: rollback + 重跑一次本函数`（届时行已存在走 UPDATE，
    bool 幂等收敛）。故本函数保持纯粹、可被安全重跑。
    """
    for ntype, enabled in mapping.items():
        row = NotificationPreference.query.filter_by(user_id=user_id, type=ntype).first()
        if row is None:
            db.session.add(NotificationPreference(user_id=user_id, type=ntype, enabled=bool(enabled)))
        else:
            row.enabled = bool(enabled)
```

**用户资料**：不新增列——`User` 已有 `display_name` / `email` / `avatar_color` / `updated_at(onupdate)`，直接复用。

---

## 6. 接口设计（Interface Design）

统一错误契约沿用 §2.6：非 2xx 恒为 `{ "error": string, "detail"?: any }`。全部端点 `jwt_required`，作用于「当前登录用户自身」。

**全端点两条落地约定（评审补充）**：① 请求体一律 `data = request.get_json(silent=True) or {}`，缺 `Content-Type` 的畸形/空体降级为 `{}` 再按字段校验（沿用 `auth.py`/`users.py` 全仓写法）〔P2-2〕；② 合法 token 但用户已删（`current_user() is None`）一律返 **401 `{"error":"unauthorized"}`**，与同蓝图 `my_work` 一致，不采用 `auth.py /me` 的 404〔P2-1〕。

### 6.1 `PATCH /api/me/profile` — 自助改资料
- 请求（键均可选，仅提供的键才更新）：
  ```json
  { "display_name": "Alice L.", "email": "alice@x.dev", "avatar_color": "#6E8B3D" }
  ```
- 校验：`display_name` strip 后 1..128 非空；`email` 为空串视为清空(→null)，否则须匹配 `^[^@\s]+@[^@\s]+\.[^@\s]+$` 且 ≤255；`avatar_color` 须匹配 `^#[0-9a-fA-F]{6}$`。
- **安全**：`username`、`role` 即使传入也**恒忽略**（白名单键），杜绝自助越权。
- 200 → `{ "user": { …to_dict() } }`；400 校验失败；401 未登录。

### 6.2 `POST /api/me/password` — 修改自身密码
- 请求：`{ "current_password": "...", "new_password": "..." }`
- 校验：二者非空（否则 400）；`current` 校验失败 → 400 `current password is incorrect`；`new` 长度 ∈[6,128]，否则 400；`new==current` → 400 `new password must differ from current`。
- 200 → `{ "ok": true }`；不回传任何口令/哈希。

### 6.3 `GET /api/me/notification-preferences` — 读有效偏好
- 200 → `{ "preferences": { "assigned": true, "commented": true, "mentioned": true, "status_changed": true, "agent_advanced": true, "converted": true } }`（缺省全 true，被存量行覆盖）。

### 6.4 `PATCH /api/me/notification-preferences` — 部分更新偏好
- 请求（部分 map 即可）：`{ "preferences": { "assigned": false } }`
- 校验：`preferences` 须为非空对象；每个 key 须 ∈ `NOTIFICATION_TYPES`，否则 400 `{error:"unknown notification type", detail:{allowed:[...], unknown:[...]}}`；每个 value 须为 bool。
- 幂等：重复提交同值无副作用。
- **并发安全**〔P1-1〕：`set_preferences` 后的 `db.session.commit()` 须包在 `try/except IntegrityError` 内——命中唯一约束（并发下另一同键请求已 INSERT）则 `db.session.rollback()` 并重跑一次 `set_preferences`（此时走 UPDATE）再 commit；bool 幂等，重跑必收敛，对客户端仍是一次成功的 200。
- 200 → 与 6.3 同 shape 的**全量** `effective_map`。

> **前端客户端复用**：`lib/api.ts` 已有 `get/post/patch/del`——四端点分别映射 `get / post / patch / patch`，**无需新增 HTTP 方法**（写偏好用 PATCH 而非 PUT，语义上本就是「部分更新」）。

---

## 7. 前端交互与组件契约

- **ProfileCard**：初值取 `useAuth().user`；头像底色用 6 色调色板 swatch（复用 seed/auth 的暖色系 `#C15F3C/#3B6EA5/#6E8B3D/#8A5A9B/#C99A2E/#4B8B8B`）；`onSave` → `api.patch<{user:User}>("/me/profile", diff)` → `applyUser(res.user)` + `toast.success`；`ApiError` → `toast.error(e.message)`；提交中禁用按钮。
- **PasswordCard**：三个 `ui/Input type="password"`（current/new/confirm）；前端先校 `new===confirm` 与 `new.length>=6`；`onSave` → `api.post("/me/password", {current_password,new_password})` → 成功清空三框 + toast；后端 400 直接 toast 其 `error`。（评审已核实 `components/ui/Input.tsx` 以 `{...rest}` 透传原生属性，`type="password"` 直接生效，无需回退原生 `<input>`〔P2-6〕。）
- **NotificationPrefsCard**：`useNotificationPreferences()` 取 `prefs`；6 行 = `NOTIFICATION_LABELS`/`NOTIFICATION_ICONS`（已存在于 `constants.ts`）+ `ui/Toggle`；拨动 → `setPreference(type, next)` 乐观更新，失败 SWR 自动回滚 + toast。
- **useNotificationPreferences**：`useSWR("/me/notification-preferences", swrFetcher)`；`setPreference` 用 `mutate(patchThunk, {optimisticData, rollbackOnError:true, revalidate:false})`。**缓存信封统一**〔P2-7〕：GET 响应、`optimisticData`、PATCH 返回体三者同为 `{ preferences: Record<type,boolean> }`，避免 SWR 缓存 shape 漂移；`patchThunk` resolve 出 PATCH 返回的权威 `{preferences}` 作为最终缓存值。
- **AuthProvider.applyUser**：`const applyUser = useCallback((u:User)=>setUser(u),[])`，纳入 context value 与 `AuthState` 接口——让资料变更即时反映到 Header/头像，避免多一次 `/auth/me` 往返。
- **ui/Toggle**：`{checked,onChange,disabled?,label?}`，`<button role="switch" aria-checked={checked}>`，clay 高亮态，无第三方依赖。

---

## 8. 实施顺序（建议给 Subtask #2 的落地次序）

1. 后端模型 `notification_preference.py` → 注册进 `models/__init__.py`。
2. 服务 `notification_prefs.py`（三函数）。
3. `notifications.py` 加偏好闸（一行 + 顶部 import）。
4. `routes/me.py` 四端点。
5. 后端 `tests/test_settings.py`，`pytest -q` 转绿（含既有 125）。
6. 前端 `lib/types.ts` / `lib/auth.tsx(applyUser)` / `ui/Toggle.tsx` / `hooks/useNotificationPreferences.ts`。
7. `components/settings/*` 三卡 → 重写 `settings/page.tsx`。
8. `npm run typecheck` + `npm run build` 转绿。

---

## 9. 测试与验收标准（Testing & Acceptance Criteria）

**后端 `tests/test_settings.py`（复用 `conftest` 的 app/client/auth/data fixtures）**
- 资料：改 `display_name`/`email`/`avatar_color` 成功且 `to_dict` 生效；`display_name` 空串/超长 → 400；非法 `email` → 400；非法 `avatar_color`（非 `#RRGGBB`）→ 400；未带 token → 401；**传入 `username`/`role` 被忽略**（改后二者不变）。
- 改密：正确旧密码 → 200，且**旧密码不能再登录、新密码能登录**（走真实 `/api/auth/login`，不 mock 哈希——遵守 CLAUDE.md「鉴权签名不得 mock」）；错误旧密码 → 400；新密码过短 → 400；新==旧 → 400；缺字段 → 400。
- 偏好：`GET` 缺省 6 类全 true；`PATCH {assigned:false}` 持久化后 `GET` 反映；未知 type → 400（带 `allowed`）；非 bool 值 → 400；重复 PATCH 幂等。
- **并发 upsert 收敛（回归）**〔P1-1〕：预置一行 `(member,"assigned")` 后再对同键 `PATCH` 相反值，断言最终单行且值为最后一次提交——即「另一请求已 INSERT」后本请求走 UPDATE 而非 500；等价地直接对 `set_preferences` 二次运行断言其幂等、不抛、不产生重复行。
- **静音生效（集成）**〔命名映射 P2-4：alice→`member`、bob→`member2`，均 conftest 既有 fixture〕：`member` 静音 `assigned` 后，pm 把某单指派给 `member` → **不产生** `member` 的 `assigned` 通知；同事件对**未静音**的 `member2` 仍正常产生；`member` 重新开启后再次指派 → 恢复产生。
- **回归护栏**：既有 `test_notifications.py` 全绿（缺省全开 ⇒ `notify()` 行为逐字节不变）。

**前端**
- `npm run typecheck`（`tsc --noEmit`）0 error；`npm run build` 成功。
- 手测主流程：改资料后 Header 头像/名字即时更新；改密后用新密码可登录；拨动任一 Toggle 后刷新页仍保持；断网时 Toggle 乐观态回滚并 toast。

**验收硬指标**
- `pytest -q` 全绿（125 既有 + ≈15 新增）。
- 仅新增 1 张加性表；无既有表列变更；无既有接口 shape 变更。
- 设置页三卡全部真实可用，页面不再出现「占位」字样。

---

## 10. 风险与缓解（Risks & Mitigations）

| # | 风险 | 缓解 |
|---|------|------|
| R1 | 给 `users` 加列会让线上既有 `aragon.db` 崩（`create_all` 不 ALTER 既有表） | **改用加性新表** `notification_preferences`；`create_all` 只补建缺失表，零迁移（同 Phase-3 `notifications` 表策略） |
| R2 | `notify()` 内查偏好触发 autoflush，提前 flush 未完成对象或引 SQLite 写锁 | `is_enabled` 的 SELECT 包在 `db.session.no_autoflush` 内（复用 real-agent-execution 同款写锁收敛） |
| R3 | 破坏既有 125 用例 | 缺省「无行=启用」⇒ 无人静音时 `notify()` 行为逐字节不变；仅新增用例，不改既有断言 |
| R4 | 改密不吊销既有 JWT（无状态）| MVP 可接受，spec 明记；未来可加 `token_version` 声明校验（本轮非目标） |
| R5 | 邮箱/颜色校验过严或过松 | 采用务实正则（邮箱含 `@` 且有域名段、≤255；颜色严格 `#RRGGBB`）；空邮箱视为清空 |
| R6 | 自助端点被用于越权改 `role`/`username` | 端点**白名单键**，`role`/`username` 恒忽略；改角色仍只能走 admin 的 `PATCH /api/users/<id>` |
| R7 | 前端 `api` 客户端无 `put` 方法 | 写偏好用 `PATCH`（语义即部分更新），复用既有 `api.patch`，零客户端改动 |
| R8 | 偏好卡乐观更新与后端不一致 | SWR `rollbackOnError:true`；PATCH 返回全量 `effective_map` 作为权威态 |
| R9 | `ui/Input` 是否透传 `type="password"` | **评审已核实解除**〔P2-6〕：`components/ui/Input.tsx` 以 `{...rest}` 透传原生属性，`type="password"` 直接生效，无需回退 |
| R10 | 偏好写入并发竞态：`threaded=True`（`app.py:80`）下同键重叠 PATCH 双 INSERT 撞唯一约束 → 500 | 〔P1-1〕路由 commit 包 `try/except IntegrityError → rollback → 重跑一次 set_preferences`（走 UPDATE，bool 幂等收敛）；补「并发 upsert 收敛」回归用例 |
| R11 | 事件扇出对每个收件人各查一次 `is_enabled`（N 次 SELECT） | 〔P2-5〕MVP 单机量级可接受，暂不优化；未来热点事件可改「每事件一次 `effective_map` 批量取 + 本地判定」，不改 helper 对外契约 |

---

## 11. 后续迭代路线（本轮 Out of Scope，交棒 Iteration 3–5）

按价值/风险排序，供后续 loop 迭代选题（对应 §0 审计项）：

1. **统一全局搜索**（B5/B6）：新增 `GET /api/search?q=` 聚合返回需求+BUG 命中，Header 搜索改下拉预览并可跳 BUG 列表（后端 BUG 搜索能力现成、闲置）。
2. **@提及自动补全**（C7）：`CommentComposer` 加 `@` 触发的用户下拉（拉 `GET /api/users`），补全后端已支持的提及链路。
3. **管理台 UI**（D8–D11）：Team 页「新增成员 / 改姓名邮箱 / 重置密码」（接 `POST /api/users`、全量 `PATCH /api/users/<id>`）、Agents 页「建/改 Agent」（接 `POST/PATCH /api/agents`）、项目管理页（接 `projects.py`）。
4. **LLM 运行时配置**（A4，谨慎）：若确要做，须避免明文落库密钥——采用「仅存 provider/model/base_url + 密钥走 env/密钥库引用」的折中，并 admin-only；本轮坚持 env-only。

---

## 12. 与既有架构约定的一致性核对

- **状态机神圣**：本特性**不触碰**任何工单状态迁移，`workflow.can_transition` 零改动。
- **通知收口唯一**：偏好闸只加在 `notify()` 一处，不侵入任何事件级 helper 的对外契约。
- **向后兼容**：唯一新增表；无既有列/接口 shape 变更；无 seed 依赖变更（不为偏好写 seed，缺省即全开）。
- **风格一致**：Python PEP8 + Google docstring；TS 公共类型用 `interface`/`type` 沿用既有；文件<800 行、方法<50 行、参数≤5、嵌套≤4（三卡拆分即为满足尺寸阈值）。
- **平台约定**：Windows / PowerShell 5.1 命令分开执行、勿用 `&&`；测试禁 mock 鉴权哈希（改密用例走真实 `login` 验证）。

---

## 评审结论（Review Verdict）

**有条件通过（Approved with conditions）。**

设计经对全仓逐文件核验，可行性 / 完备性 / 一致性 / 规模适配四维均达标，**无 P0**；唯一 P1（并发 upsert 竞态）已在本 v2 正文直接修复（§3.2(C)、§4、§5、§6.4、§9、§10 R10）。设计与既有架构高度一致——只挂既有 `me` 蓝图与 `notify()` 唯一收口、只加一张加性表、缺省全开保证既有 **125** 例零改动即绿，充分尊重「状态机神圣」「通知收口唯一」「向后兼容」三条铁律；规模适配得当（B/C/D 明确交棒 Iter3–5，不贪多）。可行性无阻塞：所依赖的既有接缝（`me` 蓝图 / `notify()` 跳过自己 / `NOTIFICATION_TYPES` / `User` 字段 / `create_all` 加性建表 / SWR / `Input` 透传 / `constants` 标签 / conftest fixtures）逐一核验属实。

**放行条件（实现 Subtask #2 时须逐条落实；除条件 1 外均为 P2，不阻塞设计定稿）**：
1. 〔P1-1，已在正文修复，实现须照做〕写偏好 commit 必须 `try/except IntegrityError → rollback → 重跑一次 set_preferences`，并附「并发 upsert 收敛」回归用例。
2. 〔P2-1〕`me` 蓝图空用户兜底统一返 **401**（勿沿用 `auth.py /me` 的 404）。
3. 〔P2-2〕四端点请求体统一 `request.get_json(silent=True) or {}`。
4. 〔P2-3〕UI/文案宜提示「指派」开关同时覆盖「Agent 认领」提醒（有意合并）。
5. 〔P2-4〕集成用例命名映射 alice→`member`、bob→`member2`。
6. 〔P2-7〕`useNotificationPreferences` 三处数据同为 `{preferences}` 信封。

达成上述后，方案可直接进入实现。**质量门维持不变**：`pytest -q` 全绿（125 既有 + ≈15 新增）、前端 `npm run typecheck` + `npm run build` 零错误。

—— 评审人：资深评审（Anthropic Eng）· Subtask #1 · Loop Iteration 2/5
