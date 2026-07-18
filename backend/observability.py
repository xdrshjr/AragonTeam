"""可观测性（Phase-2 §2.5-1）——结构化日志 + 请求 ID + 访问日志。

在 create_app 内 `init_observability(app)`：
- 每请求生成/透传 `X-Request-Id`（挂 g.request_id，回写响应头）；
- after_request 记一行 `method path status 耗时ms`（带 request_id）；
- 日志格式统一含 [request_id]，非请求上下文的记录以 '-' 兜底。

不泄露堆栈到响应体（沿用 Phase-1 §2.6）；500 的堆栈仅入日志（errors.py 负责）。
"""
import logging
import time
import uuid

from flask import g, request


class _RequestIdFilter(logging.Filter):
    """给每条日志记录补 request_id 字段，避免 format 引用缺字段而抛错。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            try:
                record.request_id = g.get("request_id", "-")
            except RuntimeError:  # 无请求/应用上下文
                record.request_id = "-"
        return True


def init_observability(app) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"
    ))
    handler.addFilter(_RequestIdFilter())

    root = logging.getLogger()
    # 替换 root handlers，避免与 basicConfig 默认 handler 叠加导致重复行。
    root.handlers = [handler]
    root.setLevel(logging.INFO)

    @app.before_request
    def _assign_request_id():
        rid = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:12]
        g.request_id = rid
        g.request_start = time.perf_counter()

    @app.after_request
    def _log_access(response):
        start = g.get("request_start")
        dur_ms = (time.perf_counter() - start) * 1000 if start is not None else 0.0
        rid = g.get("request_id", "-")
        response.headers["X-Request-Id"] = rid
        app.logger.info(
            "%s %s -> %s (%.1fms)",
            request.method, request.path, response.status_code, dur_ms,
        )
        return response
