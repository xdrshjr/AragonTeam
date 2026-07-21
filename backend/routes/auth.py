"""鉴权路由（§4.1 + Phase-2 + self-service-registration §2.2）。

login（含限流）/ me / register(admin) / **signup（公开自助注册）** / registration-meta（公开）。

既有 `POST /api/auth/register` 的鉴权与请求契约**逐字不变**——它被存量测试与管理台使用，
改动它等于破坏性变更。自助注册是**全新端点** `/api/auth/signup`。
"""
from flask import Blueprint, jsonify, current_app
from flask_jwt_extended import create_access_token, jwt_required
from sqlalchemy.exc import IntegrityError

from extensions import db
from models.user import User, ROLES
from services.auth_helpers import current_user, require_role
from services import app_settings, avatars, notifications, passwords, ratelimit
from services.validation import json_body, want_email, want_str

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
    # 【self-service-registration §2.2 B-2′】IP 口径改读 ratelimit.client_ip()——
    # 同一个部署里两套 IP 口径是必然会漂移的第二真相。默认配置下取值与 remote_addr 相同。
    key = f"{ratelimit.client_ip()}:{username}"
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
    return jsonify({"token": _issue_token(user), "user": user.to_dict()}), 200


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
                source="admin", avatar_color=avatars.pick_color(username))
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify({"user": user.to_dict()}), 201


# ————————————————————— 自助注册（self-service-registration §2.2）—————————————————————

@bp.get("/registration-meta")
def registration_meta():
    """公开元信息：注册页 / 登录页据此决定要不要渲染注册入口。

    **绝不**回传邀请码本身——那是凭据，只有根管理员经 `/api/settings/registration` 可读。
    `invite_required` 恒为 true（本轮不做无码注册），保留字段是为了让前端文案与未来的
    开关模式共用同一份渲染逻辑（§2.2 B-3）。
    """
    settings = app_settings.get_registration_settings()
    return jsonify({
        "enabled": settings["enabled"],
        "invite_required": True,
        "password_min_length": passwords.PASSWORD_MIN_LENGTH,
    }), 200


@bp.post("/signup")
def signup():
    """公开自助注册。执行顺序即 §2.2 B-2 的编号，任何一步失败都立即返回、不留半条记录。"""
    # 1 限流：成功与失败**都**计数——这里要挡的既是暴力猜邀请码，也是批量注册。
    key = f"signup:{ratelimit.client_ip()}"
    max_attempts = current_app.config.get("SIGNUP_MAX_ATTEMPTS", 10)
    if ratelimit.is_blocked(key, max_attempts):
        return jsonify({"error": "too many attempts, try later"}), 429
    ratelimit.record_failure(key)

    # 2 边界：任一不合法 → ValidationError → 全局 400，绝不 500。
    data = json_body()
    username = want_str(data, "username", max_len=64)
    password = want_str(data, "password", strip=False)
    invite_code = want_str(data, "invite_code", max_len=64)
    display_name = want_str(data, "display_name", max_len=128) or username
    email = want_email(data)
    if not username or not password:
        return jsonify({"error": "username and password are required"}), 400

    # 3 开关 → 4 邀请码。选 403 不选 401：「码不对」不是「你没登录」。
    settings = app_settings.get_registration_settings()
    if not settings["enabled"]:
        return jsonify({"error": "registration is disabled"}), 403
    if not app_settings.verify_invite_code(invite_code):
        return jsonify({"error": "invalid invite code",
                        "detail": {"field": "invite_code"}}), 403

    # 5 口令强度（不满足即抛 ValidationError → 400）。
    passwords.validate_signup_password(password, username)

    # 6 保留名 + 重名：两者**同一个响应体**，既堵住抢注，又不泄露「这是根管理员用户名」。
    if app_settings.is_reserved_username(username) or \
            User.query.filter_by(username=username).first():
        return jsonify({"error": "username already exists"}), 409

    return _create_signup_user(settings, username=username, password=password,
                               display_name=display_name, email=email)


def _create_signup_user(settings, *, username, password, display_name, email):
    """7–10 步：落库 + 通知管理员 + 提交 + 发令牌。竞态下的重名收敛在这里。

    Args:
        settings: `get_registration_settings()` 的返回值（default_role 已过白名单）。
        username: 已校验的用户名。
        password: 已过强度校验的明文口令（只用于 set_password，绝不落库、绝不记日志）。
        display_name: 显示名（调用方已回退为 username）。
        email: 可选邮箱，已校验。

    Returns:
        (响应, 状态码)。201 成功；409 表示并发同名注册的输家。
    """
    user = User(username=username, role=settings["default_role"], source="signup",
                is_root=False, is_active=True, display_name=display_name, email=email,
                avatar_color=avatars.pick_color(username))
    user.set_password(password)
    try:
        db.session.add(user)
        db.session.flush()                       # 拿到 user.id 供通知引用
        notifications.notify_user_registered(user)
        db.session.commit()
    except IntegrityError:
        # username 唯一索引下两个并发同名注册，输家在 commit 时抛 IntegrityError，
        # 会被全局兜底渲染成 500。第 6 步的预检负责友好路径，这里负责竞态路径。
        db.session.rollback()
        return jsonify({"error": "username already exists"}), 409
    # 形状与 /login 完全一致，前端可复用同一条落地逻辑。
    return jsonify({"token": _issue_token(user), "user": user.to_dict()}), 201


def _issue_token(user) -> str:
    """签发访问令牌。【R-01】identity 必须是字符串，否则受保护接口会 422。"""
    return create_access_token(identity=str(user.id),
                               additional_claims={"role": user.role})
