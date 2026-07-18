"""用户路由（§4.2）。list / create / get / patch。"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from extensions import db
from models.user import User, ROLES
from services.auth_helpers import require_role
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
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    role = data.get("role") or "member"
    display_name = data.get("display_name") or username
    email = data.get("email")

    if not username or not password:
        return jsonify({"error": "username and password are required"}), 400
    if role not in ROLES:
        return jsonify({"error": "invalid role", "detail": {"allowed": list(ROLES)}}), 400
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
    data = request.get_json(silent=True) or {}

    if "role" in data:
        if data["role"] not in ROLES:
            return jsonify({"error": "invalid role", "detail": {"allowed": list(ROLES)}}), 400
        user.role = data["role"]
    if "display_name" in data:
        user.display_name = data["display_name"]
    if "email" in data:
        user.email = data["email"]
    if data.get("password"):
        user.set_password(data["password"])

    db.session.commit()
    return jsonify(user.to_dict()), 200
