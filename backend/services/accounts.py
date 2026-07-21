"""管理员建号的唯一实现（account-security-and-governance §2.4 D-1）。

`POST /api/users` 与 `POST /api/auth/register` 两条路由**都**调 `create_user_by_admin`；
两条路由只负责自己的响应形状（前者裸 user dict，后者 `{"user": ...}`）与状态码。
此前两处各写一份，上一轮已经因此漏掉了保留用户名守卫（self-service-registration §12 F-7）
——那个漏洞在合并之前一直在线：`routes/users.py` 有 `is_reserved_username` 守卫，
`routes/auth.py` 没有。本函数的合并动作顺带把它补上。

两条路由契约的**全部**差异落在 `allow_generated` 一个参数上，不允许再有第二处分叉。
"""
from extensions import db
from models.user import User, ROLES
from services import app_settings, audit, avatars, passwords
from services.validation import ValidationError, want_email, want_str


class UsernameTaken(Exception):
    """用户名已被占用（重名**或**命中保留名）。

    路由统一渲染成 `{"error": "username already exists"}, 409`，**两者响应体逐字节相同**：
    不额外泄露「这个名字是保留名」这一条信息。稳定异常类，勿更名（CLAUDE.md §五）。
    """


def should_force_change(actor, target) -> bool:
    """口令是不是**别人**替这个人设的（account-security-and-governance §2.2 B-2）。

    判据不是「走了哪条路径」，而是「谁改了谁的口令」——`PATCH /api/users/:id` 明确
    放行本人给自己改密（根管理员今天的自助改密路径就是它），无条件置位会让任何用
    管理台给自己改密的人当场被闸门锁住。

    Args:
        actor: 施动者；None 视为系统动作（一定不是本人）。
        target: 被改口令的账号。

    Returns:
        True 表示应置位 `must_change_password`。
    """
    return actor is None or actor.id != target.id


def _resolve_password(raw_password: str, username: str):
    """定出本次要写入的明文口令，并回答「它是不是服务端生成的」。

    空串在此已确定意味着「服务端生成」——`allow_generated=False` 的调用方在更早一步就
    因为缺 password 而 400 了，走不到这里。

    **调用时机**：必须排在重名 / 保留名 409 **之后**——一个用弱口令去抢注保留名的请求
    应当得到 409（「这个名字不能用」），而不是 400（「换个更强的口令再来抢」）。
    既有用例 `test_admin_create_user_rejects_reserved_username` 钉着这个顺序。

    Args:
        raw_password: 请求体里的明文口令（可能是空串 = 未提供）。
        username: 已校验的用户名（供策略的「不等于用户名」规则）。

    Returns:
        `(明文口令, 是否服务端生成)`。

    Raises:
        ValidationError: 口令不满足策略。
    """
    if not raw_password:
        return passwords.generate_temporary_password(), True
    passwords.validate_password(raw_password, username=username)
    return raw_password, False


def create_user_by_admin(data: dict, actor, *, allow_generated: bool) -> User:
    """管理员建号的唯一实现。

    Args:
        data: 已由路由 `json_body()` 归一的请求体。
        actor: 当前登录的管理员（用于审计与 `should_force_change` 判据）。
        allow_generated: password 缺省时是否允许服务端生成一次性口令。
            `POST /api/users` 传 True（新能力）；`POST /api/auth/register` 传 **False**
            （契约不变，缺 password 仍是既有的 400）。这个参数就是两条路由契约差异的
            **全部**落点。

    Returns:
        已 add 进 session、已 flush（有 id）、**尚未 commit** 的 User。
        `user.temporary_password` 是一个**瞬时属性**（非列），仅当口令由服务端生成时存在；
        `allow_generated=False` 时它恒不存在，故 register 的响应体**结构上不可能**泄漏它。

    Raises:
        ValidationError: 字段非法 / 口令不满足策略 / (allow_generated=False 且缺 password)。
        UsernameTaken: 保留名或重名。
    """
    # 【§2.2】非串 username/display_name → 400（此前 .strip() 500）；role 走 choices 归一。
    # 【§2.6③】max_len 对齐 models/user.py 列宽（username 64 / display_name 128 / email 255）。
    username = want_str(data, "username", max_len=64)
    role = want_str(data, "role", default="member", choices=ROLES)
    display_name = want_str(data, "display_name", max_len=128) or username
    email = want_email(data)
    # 【R-13】空串按「未提供」处理——want_str 的既有归一语义就是空串，前端老代码传 `""`
    # 时走生成分支，而不是拿一个空口令去撞策略。
    raw_password = want_str(data, "password", strip=False)
    if not username or (not raw_password and not allow_generated):
        raise ValidationError("username and password are required",
                              field="username" if not username else "password",
                              expected="non-empty string")

    # 【self-service-registration §2.2 B-4 / R-15】保留用户名守卫：否则管理员仍能建出一个
    # 叫 ROOT_ADMIN_USERNAME 的普通成员，等下一次重启被 ensure_root_admin 静默提成
    # 不可降级的根管理员。两种 409 的响应体**逐字节相同**，不额外泄露「这个名字是保留名」。
    if app_settings.is_reserved_username(username) or \
            User.query.filter_by(username=username).first():
        raise UsernameTaken(username)

    password, generated = _resolve_password(raw_password, username)

    user = User(username=username, role=role, display_name=display_name, email=email,
                source="admin", avatar_color=avatars.pick_color(username))
    user.set_password(password)
    # 建号时 actor ≠ target 恒成立（target 还没有 id），故这里恒为 True；仍走同一个判据
    # 函数而不是写死 True——「谁改了谁的口令」只允许有一份实现。
    user.must_change_password = should_force_change(actor, user)
    db.session.add(user)
    db.session.flush()                      # 拿到 user.id 供审计引用
    audit.log_user_event(
        user, "user_created", actor, to_value=user.role,
        message=f"创建了成员「{user.display_name or user.username}」"
                f"（{audit.role_label(user.role)}）")
    if generated:
        # 非列，仅本次响应用；绝不落库、绝不记日志。
        user.temporary_password = password
    return user
