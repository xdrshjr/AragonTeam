"""鉴权辅助（§3.2 backend/services/auth_helpers.py）。

- current_user()：唯一封装 int(get_jwt_identity()) 的类型转换（【R-01】）。
  业务代码**不得**直接把 get_jwt_identity() 当作 int 使用。
- require_role(*roles)：装饰器级粗粒度校验（§2.4）。敏感操作以库内
  User.role 为准（二次查库），不信任 JWT 里的 role claim（§7 安全项）。
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
