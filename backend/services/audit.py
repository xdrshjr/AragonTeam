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
)

SETTINGS_ACTIONS = ("registration_updated", "invite_code_rotated")

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
