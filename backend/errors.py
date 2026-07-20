"""全局错误处理与响应契约（§2.6 / R-03）。

前端 lib/api.ts 的 ApiError 假定**所有**非 2xx 响应体恒为
`{ "error": string, "detail"?: any }` JSON。Flask 默认对未捕获异常 / 路由错误
返回 HTML 错误页，会让前端 res.json() 崩溃。这里把全部错误规整为契约 JSON。

契约铁律：任何错误路径下 `error` 字段都必须存在（前端只依赖它渲染 toast）。
"""
import logging

from flask import current_app, jsonify
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from extensions import db
from services.documents.storage import BlobMissing, StorageUnavailable
from services.scope import QueryParamError
from services.validation import ValidationError

log = logging.getLogger("aragon.errors")


def register_error_handlers(app, jwt):
    # —— HTTP 异常（400/401/403/404/405/415/409 等）——
    @app.errorhandler(HTTPException)
    def handle_http_exception(e: HTTPException):
        return jsonify({"error": e.name, "detail": e.description}), e.code

    # —— 边界校验失败（§2.2）：坏输入统一 400，绝不冒泡 500 ——
    @app.errorhandler(ValidationError)
    def handle_validation_error(e: ValidationError):
        body = {"error": e.message}
        if e.field is not None:
            body["detail"] = {"field": e.field, "expected": e.expected}
        return jsonify(body), 400

    # —— 查询串边界失败（scale-and-project-scope §2.4①'）：统一 400 ——
    # 必须走**全局**处理器而非逐路由 try/except：paginate() 被每一个列表端点调用，
    # 逐路由捕获一旦漏掉一处，该处的超界 ?offset= 就仍然 500。
    @app.errorhandler(QueryParamError)
    def handle_query_param_error(e: QueryParamError):
        return jsonify({
            "error": f"invalid {e.field}",
            "detail": {"field": e.field, "expected": e.expected, "got": str(e.got)},
        }), 400

    # —— 上传超限（ticket-document-management §2.3）——
    # 【注册顺序无关，Flask 优先匹配更具体的处理器】上面的 HTTPException catch-all 今天
    # 就会把 413 渲染成 {"error": "Request Entity Too Large"}——那串文案对用户毫无意义，
    # 也不告诉他上限是多少。这里换成稳定的领域文案 + 可操作的 detail。
    @app.errorhandler(RequestEntityTooLarge)
    def handle_too_large(e: RequestEntityTooLarge):
        max_mb = current_app.config.get("MAX_UPLOAD_MB")
        return jsonify({"error": "file too large", "detail": {"max_mb": max_mb}}), 413

    # —— 存储不可用（§2.2 / 评审 R14）：503 而非 500 ——
    # 只读挂载 / 权限不足是**运维问题，不是代码缺陷**，用户与告警系统都应该看到区别。
    @app.errorhandler(StorageUnavailable)
    def handle_storage_unavailable(e: StorageUnavailable):
        log.error("document storage is unavailable: %s", e)
        return jsonify({"error": "document storage is unavailable"}), 503

    # —— blob 与 DB 不一致（§8 R-9）：记录在、文件丢 → 410 Gone，不 500 ——
    # 语义准确且可被前端友好提示；/download 与 /content 在此**必须一致**。
    @app.errorhandler(BlobMissing)
    def handle_blob_missing(e: BlobMissing):
        return jsonify({
            "error": "document content is gone",
            "detail": {"hint": "the stored file is missing; re-upload a new version"},
        }), 410

    # —— 兜底 500：记录日志但不泄露堆栈 ——
    @app.errorhandler(Exception)
    def handle_uncaught(e: Exception):
        # HTTPException 已被上面的处理器接管，这里只处理真正未捕获的异常。
        if isinstance(e, HTTPException):
            return jsonify({"error": e.name, "detail": e.description}), e.code
        # 【Phase-2 §2.5-2】先回滚半提交事务，避免污染后续请求（连接被复用）。
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover - 回滚本身失败仅记日志，不掩盖原异常
            log.exception("rollback after unhandled exception failed")
        log.exception("Unhandled exception: %s", e)
        return jsonify({"error": "internal server error"}), 500

    # —— JWT 相关回调：缺 token / 非法 / 过期 / 撤销，统一 JSON ——
    @jwt.unauthorized_loader
    def _missing_token(reason):
        # 缺少 Authorization 头 → 401。
        return jsonify({"error": "missing authorization token", "detail": reason}), 401

    @jwt.invalid_token_loader
    def _invalid_token(reason):
        # 【§2.4-C2】token 非法 / sub 类型错（见 R-01）→ 401（前端据 401 自动登出重定向；
        # 422 会让每个请求都失败却不跳登录，会话「卡死」）。与 expired/revoked 一致。
        return jsonify({"error": "invalid token", "detail": reason}), 401

    @jwt.expired_token_loader
    def _expired_token(jwt_header, jwt_payload):
        return jsonify({"error": "token expired"}), 401

    @jwt.token_in_blocklist_loader
    def _is_revoked(jwt_header, jwt_payload):
        """已停用 / 已不存在的用户，其既有 token 立即失效
        （lifecycle-and-governance §2.5）。

        选这个钩子而不是 before_request：它由 jwt_required() 内部调用，天然只作用于
        受保护端点，不会误伤 /api/health 与 /api/auth/login；也不必在每个路由上
        各加一次守卫（漏一个就是一个后门）。
        """
        from models.user import User

        sub = jwt_payload.get("sub")
        try:
            uid = int(sub)
        except (TypeError, ValueError):
            return True
        user = db.session.get(User, uid)
        return user is None or not user.is_active

    @jwt.revoked_token_loader
    def _revoked_token(jwt_header, jwt_payload):
        # 【§2.5】文案对用户有意义：本项目唯一的吊销来源就是「账号被停用 / 被删」。
        # 仍是 401——前端 lib/api.ts 的 signalUnauthorizedIfNeeded 据 401 清 token
        # 并广播 aragon:unauthorized，被停用者下一次任何请求即被自动登出。
        return jsonify({"error": "account is disabled or removed"}), 401

    @jwt.needs_fresh_token_loader
    def _needs_fresh(jwt_header, jwt_payload):
        return jsonify({"error": "fresh token required"}), 401
