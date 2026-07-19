"""全局搜索路由（global-search §4.1）。GET /api/search —— 跨需求+BUG 聚合命中。

只读、jwt_required；q 空/空白宽容降级为空信封（下拉每键触发场景更稳健），
limit 缺省 5、clamp 到 [1, 20]。
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from services import search
from services.scope import want_query_int

bp = Blueprint("search", __name__, url_prefix="/api/search")


@bp.get("")
@jwt_required()
def global_search():
    # 【scale-and-project-scope §2.6①-C】查询串整型统一走 want_query_int：既有 clamp 语义
    # 不变（缺省 5、钳到 [1,20]），但非整数 limit 由「静默忽略」收紧为 400，与列表端点一致。
    keyword = (request.args.get("q") or "").strip()
    limit = want_query_int("limit", default=search.DEFAULT_LIMIT,
                           minimum=1, maximum=search.MAX_LIMIT, clamp=True)
    if not keyword:
        return jsonify({
            "query": "", "requirements": [], "bugs": [],
            "counts": {"requirements": 0, "bugs": 0},
        }), 200
    result = search.search_all(keyword, limit)
    result["query"] = keyword
    return jsonify(result), 200
