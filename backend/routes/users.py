"""用户路由（§4.2）。list / create / get / patch。"""
from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required

from extensions import db
from models.user import User, ROLES
from services import lifecycle
from services.auth_helpers import require_role
from services.pagination import paginate, with_total_count
from services.validation import json_body, want_bool, want_str, ValidationError
from routes.auth import _pick_color
from routes.me import _EMAIL_RE

bp = Blueprint("users", __name__, url_prefix="/api/users")


def _want_email(data, key="email"):
    """取一个可选邮箱：非串 / 超 255 / 格式非法 → 400（与 me.py 自助改资料同一水位，§2.6③）。"""
    email = want_str(data, key, required=False, max_len=255) or None
    if email is not None and not _EMAIL_RE.match(email):
        raise ValidationError(f"{key} is invalid", field=key, expected="email address")
    return email


@bp.get("")
@jwt_required()
def list_users():
    # 【§2.9-G1】补分页 + X-Total-Count（响应体仍是裸数组，契约不变）；消费方显式传 limit=200。
    q = User.query.order_by(User.id.asc())
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
    email = _want_email(data)

    if not username or not password:
        return jsonify({"error": "username and password are required"}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({"error": "username already exists"}), 409

    user = User(username=username, role=role, display_name=display_name, email=email,
                avatar_color=_pick_color(username))
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
        user.email = _want_email(data)
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
