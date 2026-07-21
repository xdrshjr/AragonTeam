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

from flask import jsonify, request
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
from flask_jwt_extended.exceptions import JWTExtendedException
from jwt.exceptions import PyJWTError

from extensions import db
from models.user import User

# 【account-security-and-governance §2.2 B-3】强制改密闸门的豁免集：`(method, path)`
# 精确匹配。**只放三类**——公开端点、读「我是谁」、改密码本身。
# 失效方向是**变严**（`/api/me/password` 被自己拦住 = 一个没有出口的死循环），
# 故 tests 里有一条用例遍历本集合、断言每条都能在 `app.url_map` 里解析到。
_PASSWORD_GATE_EXEMPT = frozenset({
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/signup"),
    ("GET", "/api/auth/registration-meta"),
    ("GET", "/api/auth/me"),          # 前端要靠它读回 must_change_password
    ("POST", "/api/me/password"),     # 闸门要求你做的那件事，不能被闸门自己挡住
    ("GET", "/api/health"),
})


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


def require_root():
    """要求当前用户是**根管理员**（is_root），否则 403。隐含要求已登录（jwt）。

    与 `require_role` 形状一致：以库内字段为准（二次查库），不信任任何 JWT claim——
    is_root 从不写进 token，一个在签发之后才被清标的账号必须立刻失去这项能力
    （self-service-registration §2.4）。
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            user = current_user()
            if user is None:
                return jsonify({"error": "unauthorized"}), 401
            if not user.is_root:
                return jsonify({
                    "error": "forbidden",
                    "detail": {"required": "root_admin", "your_role": user.role},
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


def can_manage_document(user, document) -> bool:
    """文档级 RBAC 裁决（ticket-document-management §2.7）。

    True 当且仅当：user 为 admin/pm，或 user 是该文档的**上传者本人**。
    与 `can_manage_ticket` 并列，供编辑元数据 / 新增版本 / 删除三个写操作内联调用。
    读（列表 / 详情 / 下载 / 正文）对所有已认证用户开放，见 §2.7 的理由。
    """
    if user is None or document is None:
        return False
    if user.role in ("admin", "pm"):
        return True
    return getattr(document, "uploader_id", None) == user.id


def install_password_gate(app) -> None:
    """安装「必须改密」全局闸门（account-security-and-governance §2.2 B-3）。

    选 `before_request` 而不是逐路由装饰器：路由有 40+ 个，漏挂一个就是一个后门；
    而这条规则天然是「除了这几个豁免，全都拦」的形状。

    Args:
        app: Flask 应用；须在 `register_blueprints(app)` 之后调用（顺序对 Flask 无影响，
            但能让 create_app 的阅读顺序保持「装扩展 → 装错误处理 → 装路由 → 装全局闸门」）。
    """

    @app.before_request
    def _require_password_change():
        # ① OPTIONS 必须第一个放行：CORS 预检响应由 after_request 产出，这里返 403 会让
        #    预检失败，浏览器侧表现为「所有跨域请求都挂了」，而后端日志里只有一串 403。
        if request.method == "OPTIONS":
            return None
        if not request.path.startswith("/api/"):
            return None
        if (request.method, request.path) in _PASSWORD_GATE_EXEMPT:
            return None
        if not app.config.get("FORCE_PASSWORD_CHANGE", True):
            return None
        try:
            verify_jwt_in_request(optional=True)
        except (JWTExtendedException, PyJWTError):
            # ② 异常吞掉是有意的、且范围最小：令牌畸形 / 过期 / 已吊销（账号被停用）时
            #    本闸门不表态，交给端点自己的 @jwt_required() 产出既有的 401 契约体
            #    （errors.py）。本闸门在语义上**不负责鉴权**，它只回答「这个已认证的人
            #    是否欠一次改密」。
            return None
        # ③ 闸门内**不得**做第二次查库：verify_jwt_in_request 已触发 blocklist loader 的
        #    一次 db.session.get(User, uid)，此处同主键的 get 由 SQLAlchemy 的 identity map
        #    在同一个 session 内命中，不打库。禁止为了「拿全字段」另发查询或 expire()。
        user = current_user()
        if user is None or not user.must_change_password:
            return None
        return jsonify({
            # 稳定错误串，前端据它分流，勿更名（对外错误契约，CLAUDE.md §五）。
            # **不带 `allowed` 键**——前端看板拖拽以 err.allowed 是否存在分流错误。
            "error": "password change required",
            "detail": {
                "reason": "your password was set by an administrator",
                "endpoint": "POST /api/me/password",
            },
        }), 403


def forbidden(detail=None):
    """统一 403 响应体（与 require_role 形状一致：{error:"forbidden", detail}）。"""
    return jsonify({"error": "forbidden", "detail": detail or {}}), 403
