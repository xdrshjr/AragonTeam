"""用户路由（§4.2 + account-security-and-governance §2.2 / §2.3）。

list / create / get / patch / **reset-password** / **activities**。

建号已下沉到 `services/accounts.py::create_user_by_admin`（与 `POST /api/auth/register`
共用同一份实现）；本模块只负责响应形状与状态码。
"""
from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required
from sqlalchemy import or_

from extensions import db, utcnow
from models.user import User, ROLES, USER_SOURCES
from services import accounts, audit, lifecycle, login_guard, passwords
from services.auth_helpers import current_user, require_role
from services.pagination import paginate, with_total_count
from services.scope import want_query_bool, want_query_str
from services.search import escape_like
from services.validation import json_body, want_bool, want_email, want_str

bp = Blueprint("users", __name__, url_prefix="/api/users")


def _apply_user_filters(query):
    """把 `?q= &role= &is_active= &source=` 四个筛选套到用户查询上（additive）。

    非法取值一律抛 `QueryParamError` → 全局 400（`services/scope.py` 的既有契约），
    不在这里发明第二套错误体。空串等价于不传，故默认行为逐字不变
    （self-service-registration §2.3 C-2）。

    Args:
        query: 已建好的 User 查询。

    Returns:
        套上筛选后的查询。
    """
    keyword = want_query_str("q")
    if keyword:
        # escape_like + escape="\\" 两步缺一不可：少了转义，用户搜 `_` 就成了通配符。
        like = f"%{escape_like(keyword)}%"
        query = query.filter(or_(
            User.username.ilike(like, escape="\\"),
            User.display_name.ilike(like, escape="\\"),
            User.email.ilike(like, escape="\\"),
        ))
    role = want_query_str("role", choices=ROLES)
    if role is not None:
        query = query.filter(User.role == role)
    is_active = want_query_bool("is_active")
    if is_active is not None:
        query = query.filter(User.is_active.is_(is_active))
    source = want_query_str("source", choices=USER_SOURCES)
    if source is not None:
        query = query.filter(User.source == source)
    # 【login-hardening-and-audit-console §1.2 B-8】第五个筛选：锁定状态。
    # 它是 to_dict 已暴露事实的查询形式，保持全员可用；非法取值 → 既有 400。
    locked = want_query_bool("locked")
    if locked is not None:
        now = utcnow()
        query = query.filter(User.locked_until > now) if locked \
            else query.filter(or_(User.locked_until.is_(None), User.locked_until <= now))
    return query


@bp.get("")
@jwt_required()
def list_users():
    # 【§2.9-G1】补分页 + X-Total-Count（响应体仍是裸数组，契约不变）；消费方显式传 limit=200。
    q = _apply_user_filters(User.query).order_by(User.id.asc())
    rows, total = paginate(q)
    resp = jsonify([u.to_dict() for u in rows])
    return with_total_count(resp, total), 200


@bp.post("")
@require_role("admin")
def create_user():
    """建号（account-security-and-governance §4.1）。

    `password` **可选**：缺省时服务端生成一次性口令，201 响应体额外带一个
    `temporary_password`（明文，**仅此一次**，之后任何接口都读不回来）。
    """
    try:
        user = accounts.create_user_by_admin(json_body(), current_user(),
                                             allow_generated=True)
    except accounts.UsernameTaken:
        return jsonify({"error": "username already exists"}), 409
    db.session.commit()
    body = user.to_dict()
    body["temporary_password"] = getattr(user, "temporary_password", None)
    return jsonify(body), 201


@bp.get("/<int:user_id>")
@jwt_required()
def get_user(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        return jsonify({"error": "user not found"}), 404
    return jsonify(user.to_dict()), 200


def _reject_root_mutation(user, data, *, new_role, new_active):
    """根管理员的三条受保护变更：命中返回 409 响应，未命中返回 None。

    保护的是**治理锚点**本身，不是这个人的资料：改角色 / 停用 / 被他人重置密码会让
    「所有人都被锁在门外时还能靠改配置 + 重启破窗」这条恢复路径失效
    （self-service-registration §2.1 A-4 的拦截矩阵）。

    **本函数只服务 `PATCH /api/users/:id`；它的口令分支以 `data["password"]` 存在为前提，
    任何 body 可空的端点都不得复用它。** 复用会让判据恒假 → 任意 admin 都能重置根管理员
    的口令并接管破窗账号（account-security-and-governance 评审 P0-1）。`reset_password`
    因此另写了一条与请求体无关的判据。

    Args:
        user: 被改动的用户。
        data: 已归一的请求体（用于判断本次是否要改密码）。
        new_role: 本次请求要改成的角色；None 表示不改。
        new_active: 本次请求要改成的启用状态；None 表示不改。

    Returns:
        (响应, 409) 元组，或 None 表示放行。
    """
    if not lifecycle.is_protected_root(user):
        return None
    if new_role is not None and new_role != user.role:
        return lifecycle.conflict_root_admin("role of the root administrator cannot be changed")
    if new_active is not None and not new_active:
        return lifecycle.conflict_root_admin("the root administrator cannot be deactivated")
    if data.get("password"):
        actor = current_user()
        if actor is None or actor.id != user.id:
            return lifecycle.conflict_root_admin(
                "only the root administrator can change its own password")
    return None


@bp.patch("/<int:user_id>")
@require_role("admin")
def patch_user(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        return jsonify({"error": "user not found"}), 404
    data = json_body()

    # 【lifecycle-and-governance §2.2】末任管理员不变量：降级与停用是同一个治理死锁的
    # 两张脸（admin 数归零后 POST /users、POST /auth/register、PATCH /users/:id 三个
    # 端点同时且永久地失去唯一的合法调用者，产品内无恢复路径），故在改任何字段**之前**
    # 用同一个守卫判定一次。命中返回 409（请求本身合法，是系统状态不允许）。
    new_role = want_str(data, "role", required=True, choices=ROLES) if "role" in data else None
    new_active = want_bool(data, "is_active", required=True) if "is_active" in data else None

    # 【self-service-registration §2.1 A-4】根管理员守卫**排在末任管理员守卫之前**：
    # 它更具体、错误信息更可操作（「改后端配置并重启」而不是「至少留一个管理员」）。
    # 改昵称 / 邮箱不威胁治理，故放行；本人改密走 POST /api/me/password，也放行。
    root_conflict = _reject_root_mutation(user, data, new_role=new_role, new_active=new_active)
    if root_conflict is not None:
        return root_conflict

    if (new_role is not None or new_active is not None) and \
            lifecycle.would_orphan_admins(user, new_role=new_role, new_active=new_active):
        return lifecycle.conflict_last_admin()

    actor = current_user()
    changed = False
    if new_role is not None:
        # 【account-security-and-governance §2.3 C-3-3】治理动作留痕：改角色 / 停用 /
        # 启用 / 重置口令此前**零审计**，第二天没有任何人能说出这些事发生过。
        if new_role != user.role:
            audit.log_user_event(
                user, "role_changed", actor, from_value=user.role, to_value=new_role,
                message=f"把角色从「{audit.role_label(user.role)}」"
                        f"改为「{audit.role_label(new_role)}」")
        user.role = new_role
        changed = True
    if new_active is not None:
        if bool(new_active) != bool(user.is_active):
            audit.log_user_event(
                user, "activated" if new_active else "deactivated", actor,
                from_value="active" if user.is_active else "disabled",
                to_value="active" if new_active else "disabled",
                message="启用了该账号" if new_active else "停用了该账号")
        user.is_active = new_active
        changed = True
    if "display_name" in data:
        # 非串 display_name → 400（此前直接赋值，落库后 to_dict 类型脏）；超长 → 400（§2.6③）。
        user.display_name = want_str(data, "display_name", max_len=128)
        changed = True
    if "email" in data:
        # 【§2.4-C2 / §2.6③】非串 / 超长 / 格式非法 → 400；空 → None。
        user.email = want_email(data)
        changed = True
    if data.get("password"):
        # 【account-security-and-governance §2.1 A-2】本轮起这条路径也过全站策略。
        _apply_new_password(user, want_str(data, "password", strip=False, required=True),
                            actor)
        changed = True

    # 【P2-5】与 patch_requirement 的 changed 模式对齐：此前无字段被识别仍返 200 +
    # 完整用户体，管理员以为改了、其实什么都没发生（与 §2.4-B2 同类的「静默成功」）。
    if not changed:
        return jsonify({"error": "no updatable field"}), 400

    db.session.commit()
    return jsonify(user.to_dict()), 200


def _apply_new_password(user, password: str, actor) -> None:
    """校验并写入一个由管理台设置的口令，同步置 / 清标记并写审计（**不 commit**）。

    `PATCH /api/users/:id` 与 `POST /api/users/:id/reset-password` 共用本函数——
    两条路径的置位判据必须是同一份，否则「谁改了谁的口令」这个语义会在两处漂移。

    Args:
        user: 被改口令的账号。
        password: 已由调用方取出的明文口令（尚未过策略）。
        actor: 施动者。

    Raises:
        ValidationError: 口令不满足策略（→ 全局 400）。
    """
    passwords.validate_password(password, username=user.username)
    user.set_password(password)
    # 【§2.2 B-2 / 评审 P1-7】判据是「谁改了谁的口令」，不是「走了哪条路径」：
    # 无条件置位会让任何用管理台给自己改密的人（含根管理员）当场被闸门自锁。
    user.must_change_password = accounts.should_force_change(actor, user)
    if user.must_change_password:
        audit.log_user_event(user, "password_reset", actor,
                             message="重置了该账号的密码，下次登录需修改")
    else:
        audit.log_user_event(user, "password_changed", actor, message="修改了自己的密码")


@bp.post("/<int:user_id>/reset-password")
@require_role("admin")
def reset_password(user_id):
    """重置口令（account-security-and-governance §4.2）。

    body 可空（服务端生成一次性口令）或 `{"password": "..."}`（管理员指定，仍过策略）。

    **判定顺序是契约的一部分**：404 → 409 根管理员保护 → 读 body → 400 口令策略。
    """
    user = db.session.get(User, user_id)
    if user is None:
        return jsonify({"error": "user not found"}), 404
    # 【§2.2 B-4② / 评审 P0-1】判据是「谁在重置谁」，**与请求体无关**——本端点的主用法
    # 是空 body。绝不复用 `_reject_root_mutation`：那个函数的口令分支挂在
    # `data.get("password")` 上，对空 body 恒放行，在这里就是一个失败开放的后门
    # （任意 admin 拿到根管理员的一次性口令 = 完全接管破窗账号）。
    actor = current_user()
    if lifecycle.is_protected_root(user) and (actor is None or actor.id != user.id):
        return lifecycle.conflict_root_admin(
            "only the root administrator can change its own password")

    explicit = want_str(json_body(), "password", strip=False)
    generated = not explicit
    password = explicit or passwords.generate_temporary_password()
    _apply_new_password(user, password, actor)
    db.session.commit()
    return jsonify({
        "user": user.to_dict(),
        # 明文，**仅此一次**：管理员指定的口令由他自己知道，不必回传。
        "temporary_password": password if generated else None,
    }), 200


@bp.post("/<int:user_id>/unlock")
@require_role("admin")
def unlock_user(user_id):
    """解除账号的登录锁定（login-hardening-and-audit-console §2.2 / B-6）。

    body 忽略（空 body 合法）。**没有根管理员 409 守卫**——根管理员结构上不可能被锁
    （note_failed_login 首行 `if user.is_root: return False`），对它调用本端点是一次幂等
    no-op，返回 200 + `unlocked: false`。为一个不可能发生的状态写 409 分支，正是
    CLAUDE.md §五禁止的「为理论上不会发生的分支写防御性代码」。

    `unlocked: false` 时**不写审计**——一次没有改变任何状态的操作不该在时间线上留一行。
    """
    user = db.session.get(User, user_id)
    if user is None:
        return jsonify({"error": "user not found"}), 404
    unlocked = login_guard.unlock(user, current_user())
    if unlocked:
        db.session.commit()
    return jsonify({"user": user.to_dict(), "unlocked": unlocked}), 200


@bp.get("/<int:user_id>/activities")
@require_role("admin")
def user_activities(user_id):
    """该账号的治理时间线（account-security-and-governance §4.3）。

    `require_role("admin")` 而非 `require_root()`：普通 admin 本来就能改这个人的角色与
    状态，让他看不到自己刚做的动作没有道理。响应体是**裸数组** + `X-Total-Count`，
    与 `GET /api/users` 的既有形状一致。
    """
    user = db.session.get(User, user_id)
    if user is None:
        # 「不存在」与「没有动态」是两件事，不返回空数组。
        return jsonify({"error": "user not found"}), 404
    rows, total = paginate(audit.user_timeline(user.id))
    resp = jsonify([a.to_dict() for a in rows])
    return with_total_count(resp, total), 200
