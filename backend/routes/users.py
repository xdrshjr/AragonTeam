"""用户路由（§4.2）。list / create / get / patch。"""
from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required

from extensions import db
from models.user import User, ROLES
from services.auth_helpers import require_role
from services.validation import json_body, want_str
from routes.auth import _pick_color

bp = Blueprint("users", __name__, url_prefix="/api/users")


@bp.get("")
@jwt_required()
def list_users():
    users = User.query.order_by(User.id.asc()).all()
    return jsonify([u.to_dict() for u in users]), 200


@bp.post("")
@require_role("admin")
def create_user():
    # 【§2.2】非串 username/display_name → 400（此前 .strip() 500）；role 走 choices 归一。
    data = json_body()
    username = want_str(data, "username")
    password = want_str(data, "password", strip=False)
    role = want_str(data, "role", default="member", choices=ROLES)
    display_name = want_str(data, "display_name") or username
    # 【§2.4-C2】非串 email → 400（此前绑到 String 列 commit 触 500）；缺省/空 → None。
    email = want_str(data, "email", required=False) or None

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

    if "role" in data:
        user.role = want_str(data, "role", required=True, choices=ROLES)
    if "display_name" in data:
        # 非串 display_name → 400（此前直接赋值，落库后 to_dict 类型脏）。
        user.display_name = want_str(data, "display_name")
    if "email" in data:
        # 【§2.4-C2】非串 email → 400（此前直接赋值，commit 触 500）；空 → None。
        user.email = want_str(data, "email", required=False) or None
    if data.get("password"):
        user.set_password(want_str(data, "password", strip=False, required=True))

    db.session.commit()
    return jsonify(user.to_dict()), 200
