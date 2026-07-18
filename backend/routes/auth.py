"""鉴权路由（§4.1）。login / me / register(admin)。"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required

from extensions import db
from models.user import User, ROLES
from services.auth_helpers import current_user, require_role

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return jsonify({"error": "username and password are required"}), 400

    user = User.query.filter_by(username=username).first()
    if user is None or not user.check_password(password):
        return jsonify({"error": "invalid username or password"}), 401

    # 【R-01】identity 必须是字符串（str(user.id)），否则受保护接口会 422。
    token = create_access_token(
        identity=str(user.id),
        additional_claims={"role": user.role},
    )
    return jsonify({"token": token, "user": user.to_dict()}), 200


@bp.get("/me")
@jwt_required()
def me():
    user = current_user()
    if user is None:
        return jsonify({"error": "user not found"}), 404
    return jsonify({"user": user.to_dict()}), 200


@bp.post("/register")
@require_role("admin")
def register():
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
    return jsonify({"user": user.to_dict()}), 201


# 头像底色调色板（与 seed 保持一致的暖色系）。
_PALETTE = ["#C15F3C", "#3B6EA5", "#6E8B3D", "#8A5A9B", "#C99A2E", "#4B8B8B"]


def _pick_color(seed: str) -> str:
    return _PALETTE[sum(ord(c) for c in seed) % len(_PALETTE)]
