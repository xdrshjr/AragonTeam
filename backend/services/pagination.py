"""列表分页（Phase-2 §2.5-3 · 非破坏性）。

契约铁律：响应体**仍是裸数组**（保持 Phase-1 契约不变），分页信息仅经
新增响应头 `X-Total-Count` 暴露。跨域下该头须由 CORS `expose_headers` 放行
（§2.5-7 / app.py），否则浏览器 JS 读不到（pytest test client 同源可读）。
"""
from flask import request

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def paginate(query):
    """按 `?limit=`（默认 50、上限 200）与 `?offset=`（默认 0）分页。

    返回 (rows, total)。total 为**未分页前**的总数，供 X-Total-Count。
    传入的 query 可已带 order_by；count 时去序以省一次无谓排序。
    """
    limit = request.args.get("limit", type=int)
    offset = request.args.get("offset", type=int)

    if limit is None:
        limit = DEFAULT_LIMIT
    limit = max(1, min(limit, MAX_LIMIT))

    if offset is None or offset < 0:
        offset = 0

    total = query.order_by(None).count()
    rows = query.limit(limit).offset(offset).all()
    return rows, total


def with_total_count(response, total: int):
    """给响应挂 X-Total-Count 头并原样返回，便于路由 `return with_total_count(...)`。"""
    response.headers["X-Total-Count"] = str(total)
    return response
