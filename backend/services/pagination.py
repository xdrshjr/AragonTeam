"""列表分页（Phase-2 §2.5-3 · 非破坏性）。

契约铁律：响应体**仍是裸数组**（保持 Phase-1 契约不变），分页信息仅经
新增响应头 `X-Total-Count` 暴露。跨域下该头须由 CORS `expose_headers` 放行
（§2.5-7 / app.py），否则浏览器 JS 读不到（pytest test client 同源可读）。
"""
from services.scope import want_query_int

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def paginate(query):
    """按 `?limit=`（默认 50、上限 200）与 `?offset=`（默认 0）分页。

    返回 (rows, total)。total 为**未分页前**的总数，供 X-Total-Count。
    传入的 query 可已带 order_by；count 时去序以省一次无谓排序。

    【scale-and-project-scope §2.4 / 评审 R1】两个参数改走 `want_query_int`：
    超界值此前被绑进 `.offset()` 触 OverflowError → 500，**波及每一个列表端点**；
    现统一 400（经 errors.py 的 QueryParamError 全局处理器）。
    `limit` 的既有钳制语义**逐字节不变**（仍钳到 [1,200]，超界值照钳不报错——它从不作为
    主键绑进 SQL，是「上限」而非「取值」；见 spec 验收 D3 的对照组）；非整数 `limit` 由
    「静默忽略」收紧为 400（§2.9-G2）。`offset` 为负由「静默归零」收紧为 400。
    """
    limit = want_query_int("limit", default=DEFAULT_LIMIT,
                           minimum=1, maximum=MAX_LIMIT, clamp=True)
    offset = want_query_int("offset", default=0, minimum=0)

    total = query.order_by(None).count()
    rows = query.limit(limit).offset(offset).all()
    return rows, total


def with_total_count(response, total: int):
    """给响应挂 X-Total-Count 头并原样返回，便于路由 `return with_total_count(...)`。"""
    response.headers["X-Total-Count"] = str(total)
    return response
