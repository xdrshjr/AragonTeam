"""鉴权路由（§4.1 + Phase-2）。login（含限流）/ me / register(admin)。"""
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import create_access_token, jwt_required

from extensions import db
from models.user import User, ROLES
from services.auth_helpers import current_user, require_role
from services import ratelimit
from services.validation import json_body, want_str

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.post("/login")
def login():
    # 【§2.2】json_body()/want_str 堵可复现 500：非对象体（5/[1]/"x"）→ 400（公开接口）；
    # 非串 username（123）→ 400（此前 .strip() 500）。password 不 strip（保留原字符）。
    data = json_body()
    username = want_str(data, "username")
    password = want_str(data, "password", strip=False)
    if not username or not password:
        return jsonify({"error": "username and password are required"}), 400

    # 【Phase-2 §2.5-4】登录限流：键为 ip:username，仅拦失败尝试；成功清零。
    ip = request.remote_addr or "unknown"
    key = f"{ip}:{username}"
    max_attempts = current_app.config.get("LOGIN_MAX_ATTEMPTS", 10)
    if ratelimit.is_blocked(key, max_attempts):
        return jsonify({"error": "too many attempts, try later"}), 429

    user = User.query.filter_by(username=username).first()
    if user is None or not user.check_password(password):
        ratelimit.record_failure(key)
        return jsonify({"error": "invalid username or password"}), 401

    # 【lifecycle-and-governance §2.5】账号已停用 → 403，与「密码错误」明确区分：
    # 这是管理动作，用户需要知道去找谁。**不计入限流失败**（不是猜密码），也不多泄露信息。
    # 选 403 而非 401 纯粹是语义更准：401 会触发前端自动登出流程，而此时用户本就未登录。
    if not user.is_active:
        return jsonify({"error": "account is disabled, contact an administrator"}), 403

    ratelimit.clear(key)  # 成功清零，避免误伤后续正常登录。
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
    # 【§2.2】非串 username/display_name → 400（此前 .strip() 500）；role 走 choices 归一。
    # 【§2.6③】max_len 对齐 models/user.py 列宽（username String(64) / display_name String(128)）。
    data = json_body()
    username = want_str(data, "username", max_len=64)
    password = want_str(data, "password", strip=False)
    role = want_str(data, "role", default="member", choices=ROLES)
    display_name = want_str(data, "display_name", max_len=128) or username
    # 【§2.4-C2】非串 email（{"x":1}）绑到 String 列 → commit 触 InterfaceError 500；
    # want_str 保证非串即 400。缺省/空 → None（保持既有宽松语义，格式校验仍只在 me.py 自助改资料处）。
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
    return jsonify({"user": user.to_dict()}), 201


# 头像底色调色板（与 seed 保持一致的暖色系）。
_PALETTE = ["#C15F3C", "#3B6EA5", "#6E8B3D", "#8A5A9B", "#C99A2E", "#4B8B8B"]


def _pick_color(seed: str) -> str:
    return _PALETTE[sum(ord(c) for c in seed) % len(_PALETTE)]
