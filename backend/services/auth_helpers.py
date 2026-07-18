"""鉴权辅助（§3.2 backend/services/auth_helpers.py + Phase-3 §2.4 行级 RBAC）。

- current_user()：唯一封装 int(get_jwt_identity()) 的类型转换（【R-01】）。
  业务代码**不得**直接把 get_jwt_identity() 当作 int 使用。
- require_role(*roles)：装饰器级粗粒度校验（§2.4）。敏感操作以库内
  User.role 为准（二次查库），不信任 JWT 里的 role claim（§7 安全项）。
- can_manage_ticket(user, ticket)：**Phase-3 唯一真正新增**的行级裁决函数——
  依赖 ticket 归属（装饰器无法表达），以内联守卫调用〔R3-03：复用既有 require_role，
  不新增 require_roles，保持 403 体形状一致〕。
- forbidden(detail)：统一 403 响应体，与 require_role 形状一致（{error:"forbidden", detail}）。
"""
from functools import wraps

from flask import jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity

from extensions import db
from models.user import User


def current_user():
    """从 JWT 取当前登录用户对象；无 / 非法 identity 返回 None。

    【R-01 修复】JWT 的 identity（sub）为字符串，这里统一 int() 转回主键。
    """
    identity = get_jwt_identity()
    if identity is None:
        return None
    try:
        uid = int(identity)
    except (TypeError, ValueError):
        return None
    return db.session.get(User, uid)


def require_role(*roles):
    """要求当前用户角色 ∈ roles，否则 403。隐含要求已登录（jwt）。

    以库内 User.role 为准（二次查库），不信任 token 内的 role claim。
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            user = current_user()
            if user is None:
                return jsonify({"error": "unauthorized"}), 401
            if user.role not in roles:
                return jsonify({
                    "error": "forbidden",
                    "detail": {"required_roles": list(roles), "your_role": user.role},
                }), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def can_manage_ticket(user, ticket) -> bool:
    """行级 RBAC 裁决（Phase-3 §2.4）。

    True 当且仅当：user 为 admin/pm，或 user 是该单 reporter，或 user 是该单**人类
    assignee 本人**。供 patch / move / agent-advance 等依赖归属的操作以内联守卫调用。
    """
    if user is None or ticket is None:
        return False
    if user.role in ("admin", "pm"):
        return True
    if getattr(ticket, "reporter_id", None) == user.id:
        return True
    if ticket.assignee_type == "user" and ticket.assignee_id == user.id:
        return True
    return False


def forbidden(detail=None):
    """统一 403 响应体（与 require_role 形状一致：{error:"forbidden", detail}）。"""
    return jsonify({"error": "forbidden", "detail": detail or {}}), 403
