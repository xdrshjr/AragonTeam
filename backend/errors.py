"""全局错误处理与响应契约（§2.6 / R-03）。

前端 lib/api.ts 的 ApiError 假定**所有**非 2xx 响应体恒为
`{ "error": string, "detail"?: any }` JSON。Flask 默认对未捕获异常 / 路由错误
返回 HTML 错误页，会让前端 res.json() 崩溃。这里把全部错误规整为契约 JSON。

契约铁律：任何错误路径下 `error` 字段都必须存在（前端只依赖它渲染 toast）。
"""
import logging

from flask import jsonify
from werkzeug.exceptions import HTTPException

from extensions import db
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

    @jwt.revoked_token_loader
    def _revoked_token(jwt_header, jwt_payload):
        return jsonify({"error": "token revoked"}), 401

    @jwt.needs_fresh_token_loader
    def _needs_fresh(jwt_header, jwt_payload):
        return jsonify({"error": "fresh token required"}), 401
