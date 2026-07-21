"""账号与站点治理审计（account-security-and-governance §2.3）。

路由层只调本模块，**不直接调 `Activity.log`**——那会让 action 字符串散落在 6 个路由
文件里，第一次拼写不一致就是一条查不出来的审计。与 `services/lifecycle.py` 的定位一致：
「破坏性动作的前置检查与语义」收在服务层，路由只做「取参 → 调服务 → 渲染契约」。

本模块**绝不**把口令、口令哈希、邀请码明文写进 message —— 审计要能被广泛阅读，
凭据不能。这条是硬约束，不是建议。

两个 `log_*` 一律**不 commit**（沿用 `Activity.log` 与 `notifications.notify` 的既有
约定），由调用方事务统一提交。
"""
from models.activity import Activity, APP_SETTING_ENTITY_ID
from models.user import User

ENTITY_USER = "user"
ENTITY_APP_SETTING = "app_setting"

USER_ACTIONS = (
    "user_created",       # 管理员建号
    "user_registered",    # 凭邀请码自助注册
    "role_changed",       # from_status/to_status = 旧/新角色
    "activated",
    "deactivated",
    "password_reset",     # 他人重置（含一次性口令）
    "password_changed",   # 本人自助改密
    # 【login-hardening-and-audit-console §1.3 C-4-1】登录闸门两个 system/admin 动作。
    # 前端 lib/types.ts 的 UserActivityAction 与 lib/constants.ts 的两个
    # Record<UserActivityAction, string> map 是它的镜像，漏改任一处即 npm run typecheck 报错。
    "account_locked",     # 连续失败触发锁定（actor=system）
    "account_unlocked",   # 管理员显式解锁
)

SETTINGS_ACTIONS = ("registration_updated", "invite_code_rotated")

# 【login-hardening-and-audit-console §1.3 C-1】站点级治理审计的实体维度与动作全集。
GOVERNANCE_ENTITY_TYPES = (ENTITY_USER, ENTITY_APP_SETTING)
ALL_ACTIONS = USER_ACTIONS + SETTINGS_ACTIONS      # 供路由做 ?action= 的 choices 校验

# 审计 message 是给人读的，角色代号不是。**唯一一份**中文角色词典：
# 前端另有一份（lib/constants.ts），两侧都只是展示，不参与任何判定。
ROLE_LABELS = {"admin": "管理员", "pm": "项目经理", "member": "成员"}


def role_label(role: str) -> str:
    """角色代号 → 中文词；未知代号原样回显（审计不该因为一个新角色而写不出来）。"""
    return ROLE_LABELS.get(role, role)


def _actor_ref(actor):
    """把一个 User 对象归一成 `Activity.log` 要的 `(actor_type, actor_id)`；None → system。"""
    if actor is None:
        return None
    return ("user", actor.id)


def log_user_event(target_user, action, actor, *, from_value=None,
                   to_value=None, message=None):
    """写一条账号治理审计（不 commit）。

    Args:
        target_user: 被治理的账号（entity_id 取它的 id）。
        action: USER_ACTIONS 之一。
        actor: 施动者 User；None 记为 system（如启动期动作）。
        from_value: 迁移前取值（角色 / active|disabled），借用 from_status 列。
        to_value: 迁移后取值，借用 to_status 列。
        message: 中文一句话说明，**绝不含任何凭据**。

    Returns:
        已 add 进 session 的 Activity。
    """
    return Activity.log(ENTITY_USER, target_user.id, action, actor=_actor_ref(actor),
                        from_status=from_value, to_status=to_value, message=message)


def log_settings_event(action, actor, *, message=None):
    """写一条站点设置治理审计（不 commit）。

    Args:
        action: SETTINGS_ACTIONS 之一。
        actor: 施动者 User（站点设置只有根管理员能改）。
        message: 中文一句话说明；**只列被改动的键名，绝不带值**——`invite_code`
            的值是凭据，而审计流的读者面比「设置页」宽得多。

    Returns:
        已 add 进 session 的 Activity。
    """
    return Activity.log(ENTITY_APP_SETTING, APP_SETTING_ENTITY_ID, action,
                        actor=_actor_ref(actor), message=message)


def user_timeline(user_id: int):
    """该账号的治理时间线查询（**未分页**，供路由套 paginate）。

    Args:
        user_id: 被治理账号的 id。

    Returns:
        按时间倒序的 Activity 查询对象。
    """
    return Activity.query.filter_by(entity_type=ENTITY_USER, entity_id=user_id)\
        .order_by(Activity.created_at.desc(), Activity.id.desc())


def governance_timeline(*, entity_type=None, action=None, actor_id=None, since=None):
    """站点级治理审计查询（**未分页**，供路由套 paginate；login-hardening §1.3 C-1）。

    与 `user_timeline` 并列：那个回答「这个人身上发生过什么」，本函数回答
    「这个站点上发生过什么」。`entity_type` 默认取**两者**是关键——`app_setting` 事件
    今天写了读不到，本轮的第一目的就是让它可读，写成默认只查 user 等于把缺陷带进新端点。

    Args:
        entity_type: 限定 `user` / `app_setting`；None = 两者。
        action: 限定单个 action；None = 不过滤（取值合法性由路由的 choices 保证）。
        actor_id: 限定施动者（仅 actor_type == "user" 的行）；None = 不过滤。
        since: 只取此时刻及之后（naive UTC）；None = 不过滤。

    Returns:
        按时间倒序的 Activity 查询对象。
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


def resolve_actors(rows) -> dict:
    """把一页审计行里出现的所有 user id 一次性解析成 `{id: {"id":.., "name":..}}`。

    需要解析的 id 有两个来源：施动者（`actor_type == "user"` 的 actor_id）与被治理对象
    （`entity_type == "user"` 的 entity_id）。合成一个集合、发**一次** `IN` 查询——逐行
    `db.session.get` 在 50 行的默认页宽下就是 100 次往返（§1.3 C-2 / §7 R-9）。

    解析不到的 id 不入结果 dict，调用方据此降级为 null——`activities` 没有 DB 外键，
    被删的用户必须能安全渲染成占位。
    """
    ids = set()
    for row in rows:
        if row.actor_type == "user" and row.actor_id is not None:
            ids.add(row.actor_id)
        if row.entity_type == ENTITY_USER:
            ids.add(row.entity_id)
    if not ids:
        return {}
    users = User.query.filter(User.id.in_(ids)).all()
    return {u.id: {"id": u.id, "name": u.display_name or u.username} for u in users}
