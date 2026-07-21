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
from services import app_settings, audit
from services.auth_helpers import current_user, require_root
from services.pagination import paginate, with_total_count
from services.scope import want_query_datetime, want_query_int, want_query_str
from services.validation import json_body, want_bool, want_int, want_str

admin_settings_bp = Blueprint("admin_settings", __name__, url_prefix="/api/settings")

# 请求体里可更新的键 → 取值函数。**顺序即校验顺序**，与 §4.4 的 400 条件表一一对应。
# 【login-hardening-and-audit-console §2.5】新增 expires_at / max_uses，排在末尾。
_UPDATABLE_KEYS = ("enabled", "invite_code", "default_role", "expires_at", "max_uses")


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
    stored = app_settings._stored_values()
    settings = app_settings._settings_from_rows(stored)
    uses = app_settings.invite_uses(stored)
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
        # 【login-hardening-and-audit-console §2.4】五个 additive 键。datetime 逐个走
        # _iso()——**禁止 {**settings} 直出**：jsonify 会把 datetime 写成 RFC 822，
        # 那是一次没有任何测试会红的静默契约破坏（评审 P0-1）。
        "invite_expires_at": _iso(settings["invite_expires_at"]),
        "invite_max_uses": settings["invite_max_uses"],
        "invite_uses": uses,
        "invite_issued_at": _iso(app_settings.invite_issued_at(stored)),
        "invite_status": app_settings.invite_status(settings, uses),
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
    # 【login-hardening-and-audit-console §2.5】期限 + 额度。类型与列宽在这里，业务约束
    # （必须在未来、0..10000）在服务层。
    if "expires_at" in data:
        # None 与 "" 都表示清除；非串 → 400（want_str 抛）。
        changes["expires_at"] = want_str(data, "expires_at", max_len=64) or None
    if "max_uses" in data:
        # want_int 只接受 JSON 数字（不接受 "20" 串）、显式排除 bool，64 位硬界无条件生效，
        # minimum/maximum 只在其内部再收窄——三条既有语义直接满足需求，不另写一个。
        changes["max_uses"] = want_int(data, "max_uses", required=True,
                                       minimum=0, maximum=app_settings.INVITE_MAX_USES_CEIL)

    if not changes:
        return jsonify({
            "error": "no updatable field",
            "detail": {"allowed": list(_UPDATABLE_KEYS)},
        }), 400

    actor = current_user()
    app_settings.set_registration_settings(changes, actor.id)
    # 【account-security-and-governance §2.3 C-3-7】message **只列被改动的键名，绝不带值**——
    # invite_code 的值是凭据，而审计流的读者面比「只有根管理员能打开的设置页」宽得多。
    audit.log_settings_event("registration_updated", actor,
                             message=f"更新了注册配置：{'、'.join(sorted(changes))}")
    db.session.commit()
    return jsonify(_registration_payload()), 200


@admin_settings_bp.post("/registration/rotate-code")
@require_root()
def rotate_invite_code():
    """生成新邀请码并落库。旧码**立即失效**，无宽限期。

    宽限期只会让「我刚刚撤销的码还能用」这件事变得难以解释——邀请码不是会话令牌，
    它的全部价值就在于「说撤就撤」。已注册的账号不受影响。

    【login-hardening-and-audit-console §1.1 A-5】rotate 走同一条 set_registration_settings
    路径，因此**自动归零用量**（新码 != 当前码，必写 issued_at），而 `expires_at` /
    `max_uses` **原样保留**——rotate 的语义是「换一把钥匙」，不是「重置整套门禁策略」。
    """
    actor = current_user()
    app_settings.set_registration_settings(
        {"invite_code": app_settings.generate_invite_code()}, actor.id)
    audit.log_settings_event("invite_code_rotated", actor, message="重新生成了邀请码")
    db.session.commit()
    return jsonify(_registration_payload()), 200


def _resolve_ref(refs, key):
    """把一个 id 从 resolve_actors 的结果里取出，缺失降级为 None（绝不抛，§2.3）。"""
    return refs.get(key)


@admin_settings_bp.get("/audit")
@require_root()
def get_governance_audit():
    """站点治理审计的读出口（login-hardening-and-audit-console §2.3）。

    `@require_root()` 而非 `require_role("admin")`：本端点会返回 `app_setting` 事件，
    而站点设置本身就是 root-only（本文件三处 `@require_root()`）。让普通 admin 从审计流里
    读到「根管理员什么时候改了注册配置」等于绕过那三道门禁——普通 admin 需要的粒度已由
    `GET /api/users/<id>/activities`（admin-only）给足。

    响应是**裸数组** + `X-Total-Count` 头（与 `GET /api/users` 完全一致），每行是
    `Activity.to_dict()` 加 `actor` / `target` 两个批量解析块（一次 IN 查询，不做 N+1）。
    """
    entity_type = want_query_str("entity_type",
                                 choices=audit.GOVERNANCE_ENTITY_TYPES)
    action = want_query_str("action", choices=audit.ALL_ACTIONS)
    actor_id = want_query_int("actor_id")
    since = want_query_datetime("since")

    query = audit.governance_timeline(entity_type=entity_type, action=action,
                                      actor_id=actor_id, since=since)
    rows, total = paginate(query)
    refs = audit.resolve_actors(rows)
    payload = []
    for row in rows:
        item = row.to_dict()
        # actor：actor_type == "user" 且解析得到时为 {id, name}，否则 null（system 事件恒 null）。
        item["actor"] = _resolve_ref(refs, row.actor_id) \
            if row.actor_type == "user" else None
        # target：entity_type == "user" 且解析得到时为 {id, name}，否则 null
        # （app_setting 是站点单例，没有目标对象）。
        item["target"] = _resolve_ref(refs, row.entity_id) \
            if row.entity_type == audit.ENTITY_USER else None
        payload.append(item)
    resp = jsonify(payload)
    return with_total_count(resp, total), 200
