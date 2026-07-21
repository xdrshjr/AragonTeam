"""应用级设置路由（self-service-registration §4.3–§4.5）——目前只有注册配置一组。

蓝图对象名 **`admin_settings_bp`**（不是裸 `bp`）：本项目已有一个 `tests/test_settings.py`，
测的是 account-settings 轮的 `/api/me/profile` / `/api/me/password` /
`/api/me/notification-preferences`——那是**成员自助**设置，住在 `routes/me.py`。
本模块是**站点级**设置，全部 `@require_root()`。两者名字近似而语义正交，
故在这里把区别写死（spec 评审 P2-1）。

三个端点共用同一个响应形状（§4.3），因此 PATCH / rotate 成功后前端可以直接 `mutate`
替换缓存，省一次往返。
"""
from flask import Blueprint, jsonify

from extensions import db
from models.app_setting import AppSetting
from models.user import User
from services import app_settings
from services.auth_helpers import current_user, require_root
from services.validation import json_body, want_bool, want_str

admin_settings_bp = Blueprint("admin_settings", __name__, url_prefix="/api/settings")

# 请求体里可更新的键 → 取值函数。**顺序即校验顺序**，与 §4.4 的 400 条件表一一对应。
_UPDATABLE_KEYS = ("enabled", "invite_code", "default_role")


def _updated_by(row):
    """把 updated_by_id 软解析成 {id, name}；解析不到降级为 None（无 DB 外键，§5.1）。"""
    if row is None or row.updated_by_id is None:
        return None
    user = db.session.get(User, row.updated_by_id)
    if user is None:
        return None
    return {"id": user.id, "name": user.display_name or user.username}


def _registration_payload():
    """§4.3 的响应体：生效值 + 白名单 + 最后一次改动的时间与人。

    `updated_at` / `updated_by` 取三行里**最近改动**的那一行；一行都没有（全新库走配置
    兜底）时均为 null——前端据此显示「尚未自定义」。
    """
    settings = app_settings.get_registration_settings()
    rows = AppSetting.query.filter(
        AppSetting.key.in_(app_settings.REGISTRATION_KEYS)).all()
    latest = max(rows, key=lambda r: r.updated_at) if rows else None
    return {
        "enabled": settings["enabled"],
        # 明文；仅根管理员可见（§7 R-2 的有意取舍：他必须能读回来才能发给同事）。
        "invite_code": settings["invite_code"],
        "default_role": settings["default_role"],
        "allowed_default_roles": list(app_settings.SIGNUP_ROLES),
        "updated_at": _iso(latest.updated_at) if latest else None,
        "updated_by": _updated_by(latest),
    }


def _iso(dt):
    return dt.isoformat() + "Z" if dt else None


@admin_settings_bp.get("/registration")
@require_root()
def get_registration():
    return jsonify(_registration_payload()), 200


@admin_settings_bp.patch("/registration")
@require_root()
def patch_registration():
    """部分更新（三个键均可选）。一个都没带 → 400 `no updatable field`。

    与 `patch_user` 的 changed 模式对齐，杜绝「静默成功」——管理员以为改了、其实什么
    都没发生，是本仓库反复踩过的同一类坑。
    """
    data = json_body()
    changes = {}
    if "enabled" in data:
        changes["enabled"] = want_bool(data, "enabled", required=True)
    if "invite_code" in data:
        # 长度 / 空白字符的业务约束在服务层，这里只保证类型与列宽。
        changes["invite_code"] = want_str(data, "invite_code", required=True,
                                          max_len=app_settings.INVITE_CODE_MAX)
    if "default_role" in data:
        changes["default_role"] = want_str(data, "default_role", required=True)

    if not changes:
        return jsonify({
            "error": "no updatable field",
            "detail": {"allowed": list(_UPDATABLE_KEYS)},
        }), 400

    actor = current_user()
    app_settings.set_registration_settings(changes, actor.id)
    db.session.commit()
    return jsonify(_registration_payload()), 200


@admin_settings_bp.post("/registration/rotate-code")
@require_root()
def rotate_invite_code():
    """生成新邀请码并落库。旧码**立即失效**，无宽限期。

    宽限期只会让「我刚刚撤销的码还能用」这件事变得难以解释——邀请码不是会话令牌，
    它的全部价值就在于「说撤就撤」。已注册的账号不受影响。
    """
    actor = current_user()
    app_settings.set_registration_settings(
        {"invite_code": app_settings.generate_invite_code()}, actor.id)
    db.session.commit()
    return jsonify(_registration_payload()), 200
