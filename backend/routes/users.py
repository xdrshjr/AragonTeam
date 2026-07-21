"""用户路由（§4.2）。list / create / get / patch。"""
from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required
from sqlalchemy import or_

from extensions import db
from models.user import User, ROLES, USER_SOURCES
from services import app_settings, avatars, lifecycle
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
    # 【§2.2】非串 username/display_name → 400（此前 .strip() 500）；role 走 choices 归一。
    # 【§2.6③】max_len 对齐 models/user.py 列宽（username 64 / display_name 128 / email 255）。
    data = json_body()
    username = want_str(data, "username", max_len=64)
    password = want_str(data, "password", strip=False)
    role = want_str(data, "role", default="member", choices=ROLES)
    display_name = want_str(data, "display_name", max_len=128) or username
    # 【§2.4-C2 / §2.6③】非串 email → 400；超长 / 格式非法 → 400（此前管理员路径两者都没有）。
    email = want_email(data)

    if not username or not password:
        return jsonify({"error": "username and password are required"}), 400
    # 【self-service-registration §2.2 B-4 / R-15】保留用户名守卫：否则管理员仍能建出一个
    # 叫 ROOT_ADMIN_USERNAME 的普通成员，等下一次重启被 ensure_root_admin 静默提成
    # 不可降级的根管理员。响应体与下面的普通重名 409 **逐字节相同**，不额外泄露
    # 「这个名字是根管理员用户名」这一条信息。
    if app_settings.is_reserved_username(username):
        return jsonify({"error": "username already exists"}), 409
    if User.query.filter_by(username=username).first():
        return jsonify({"error": "username already exists"}), 409

    user = User(username=username, role=role, display_name=display_name, email=email,
                source="admin", avatar_color=avatars.pick_color(username))
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify(user.to_dict()), 201


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

    changed = False
    if new_role is not None:
        user.role = new_role
        changed = True
    if new_active is not None:
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
        user.set_password(want_str(data, "password", strip=False, required=True))
        changed = True

    # 【P2-5】与 patch_requirement 的 changed 模式对齐：此前无字段被识别仍返 200 +
    # 完整用户体，管理员以为改了、其实什么都没发生（与 §2.4-B2 同类的「静默成功」）。
    if not changed:
        return jsonify({"error": "no updatable field"}), 400

    db.session.commit()
    return jsonify(user.to_dict()), 200
