"""me 蓝图（Phase-3 §4.3 / 〔R3-02 修复〕 + account-settings §6）。

`GET /api/me/work`「我的工作」聚合：当前用户为**人类 assignee** 的单 + 其 **reporter**
的单，各按更新时间倒序、limit 兜底。

account-settings 新增四个**成员自助**端点（均 jwt_required，作用于当前登录用户自身）：
- `PATCH  /api/me/profile`                  自助改资料（display_name/email/avatar_color）
- `POST   /api/me/password`                 改自身密码（校旧 → 设新，pbkdf2:sha256）
- `GET    /api/me/notification-preferences` 读有效偏好（缺省全开，存量行覆盖）
- `PATCH  /api/me/notification-preferences` 部分更新偏好（upsert，并发下唯一约束收敛）

**必须**承载于本蓝图（url_prefix="/api/me"）——不得挂进 users 蓝图（/api/users），
否则真实路径会变成 /api/users/work，与 §4.3 契约不符（Flask 蓝图路由无法逃逸 url_prefix）。

落地约定〔评审 P2-1/P2-2〕：① 请求体一律 `request.get_json(silent=True) or {}`，缺
Content-Type 的畸形 / 空体降级为 `{}`；② 合法 token 但用户已删（current_user() is None）
一律返 **401**，与同蓝图 my_work 一致（不采用 auth.py /me 的 404）。
"""
import re

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from sqlalchemy.exc import IntegrityError

from extensions import db
from models.requirement import Requirement
from models.bug import Bug
from models.notification import NOTIFICATION_TYPES
from services.auth_helpers import current_user
from services import notification_prefs

bp = Blueprint("me", __name__, url_prefix="/api/me")

# 「我的工作」各分区兜底上限，防单人海量单撑爆响应（MVP 单机量级足够）。
WORK_LIMIT = 100

# 资料校验正则：邮箱务实匹配（含 @ 且有域名段）；头像底色严格 #RRGGBB。
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# 密码长度区间（§6.2）。
_PASSWORD_MIN = 6
_PASSWORD_MAX = 128


def _assigned(model, user_id):
    return model.query.filter_by(assignee_type="user", assignee_id=user_id)\
        .order_by(model.updated_at.desc(), model.id.desc()).limit(WORK_LIMIT).all()


def _reported(model, user_id):
    return model.query.filter_by(reporter_id=user_id)\
        .order_by(model.updated_at.desc(), model.id.desc()).limit(WORK_LIMIT).all()


@bp.get("/work")
@jwt_required()
def my_work():
    user = current_user()
    if user is None:
        return jsonify({"error": "unauthorized"}), 401
    return jsonify({
        "assigned": {
            "requirements": [r.to_dict() for r in _assigned(Requirement, user.id)],
            "bugs": [b.to_dict() for b in _assigned(Bug, user.id)],
        },
        "reported": {
            "requirements": [r.to_dict() for r in _reported(Requirement, user.id)],
            "bugs": [b.to_dict() for b in _reported(Bug, user.id)],
        },
    }), 200


# ————————————————————— 自助资料 —————————————————————

@bp.patch("/profile")
@jwt_required()
def update_profile():
    """自助改资料（§6.1）。白名单键 display_name/email/avatar_color；username/role 恒忽略。"""
    user = current_user()
    if user is None:
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    error = _apply_profile(user, data)
    if error is not None:
        return jsonify({"error": error}), 400
    db.session.commit()
    return jsonify({"user": user.to_dict()}), 200


def _apply_profile(user, data) -> str | None:
    """校验并就地写入白名单字段；命中非法值返回错误串（不写库），否则返回 None。

    安全：username / role 即使传入也**恒忽略**，杜绝自助越权（§6.1 / R6）。
    """
    if "display_name" in data:
        name = (data.get("display_name") or "").strip()
        if not 1 <= len(name) <= 128:
            return "display_name must be 1..128 chars"
        user.display_name = name
    if "email" in data:
        email = "" if data.get("email") is None else str(data.get("email")).strip()
        if email == "":
            user.email = None  # 空串视为清空（§6.1 / R5）。
        elif len(email) > 255 or not _EMAIL_RE.match(email):
            return "invalid email"
        else:
            user.email = email
    if "avatar_color" in data:
        color = data.get("avatar_color") or ""
        if not _COLOR_RE.match(color):
            return "invalid avatar_color (expect #RRGGBB)"
        user.avatar_color = color
    return None


# ————————————————————— 改密码 —————————————————————

@bp.post("/password")
@jwt_required()
def change_password():
    """改自身密码（§6.2）。校旧密码 → 设新（pbkdf2:sha256）；不回传任何口令 / 哈希。"""
    user = current_user()
    if user is None:
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    current_password = data.get("current_password") or ""
    new_password = data.get("new_password") or ""
    if not current_password or not new_password:
        return jsonify({"error": "current_password and new_password are required"}), 400
    if not user.check_password(current_password):
        return jsonify({"error": "current password is incorrect"}), 400
    if not _PASSWORD_MIN <= len(new_password) <= _PASSWORD_MAX:
        return jsonify({"error": f"new password must be {_PASSWORD_MIN}..{_PASSWORD_MAX} chars"}), 400
    if new_password == current_password:
        return jsonify({"error": "new password must differ from current"}), 400
    user.set_password(new_password)
    db.session.commit()
    # JWT 无状态不吊销（§10 R4）：旧 token 在过期前仍有效，属 MVP 可接受权衡。
    return jsonify({"ok": True}), 200


# ————————————————————— 通知偏好 —————————————————————

@bp.get("/notification-preferences")
@jwt_required()
def get_notification_preferences():
    """读有效偏好（§6.3）：6 类缺省全 true，被存量行覆盖。"""
    user = current_user()
    if user is None:
        return jsonify({"error": "unauthorized"}), 401
    return jsonify({"preferences": notification_prefs.effective_map(user.id)}), 200


@bp.patch("/notification-preferences")
@jwt_required()
def update_notification_preferences():
    """部分更新偏好（§6.4）。校验 type∈枚举 & 值为 bool；upsert 后返回全量 effective_map。"""
    user = current_user()
    if user is None:
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    prefs = data.get("preferences")
    invalid = _validate_preferences(prefs)
    if invalid is not None:
        return invalid
    _commit_preferences(user.id, prefs)
    return jsonify({"preferences": notification_prefs.effective_map(user.id)}), 200


def _validate_preferences(prefs):
    """校验 preferences 载荷；合法返回 None，否则返回 (响应, 400) 元组。"""
    if not isinstance(prefs, dict) or not prefs:
        return jsonify({"error": "preferences must be a non-empty object"}), 400
    unknown = [k for k in prefs if k not in NOTIFICATION_TYPES]
    if unknown:
        return jsonify({
            "error": "unknown notification type",
            "detail": {"allowed": list(NOTIFICATION_TYPES), "unknown": unknown},
        }), 400
    if any(not isinstance(v, bool) for v in prefs.values()):
        return jsonify({"error": "preference values must be boolean"}), 400
    return None


def _commit_preferences(user_id, prefs) -> None:
    """upsert 偏好并提交；命中唯一约束（并发同键已 INSERT）则回滚重跑一次（走 UPDATE，幂等收敛）〔§10 R10〕。"""
    notification_prefs.set_preferences(user_id, prefs)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        notification_prefs.set_preferences(user_id, prefs)
        db.session.commit()
