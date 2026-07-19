"""全局搜索路由（global-search §4.1）。GET /api/search —— 跨需求+BUG 聚合命中。

只读、jwt_required；q 空/空白宽容降级为空信封（下拉每键触发场景更稳健），
limit 缺省 5、clamp 到 [1, 20]。
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from services import search

bp = Blueprint("search", __name__, url_prefix="/api/search")


def _coerce_limit(value):
    """把 limit 参数安全 clamp 到 [1, MAX_LIMIT]；缺省/非法 → DEFAULT_LIMIT。"""
    if value is None:
        return search.DEFAULT_LIMIT
    return max(1, min(value, search.MAX_LIMIT))


@bp.get("")
@jwt_required()
def global_search():
    keyword = (request.args.get("q") or "").strip()
    limit = _coerce_limit(request.args.get("limit", type=int))
    if not keyword:
        return jsonify({
            "query": "", "requirements": [], "bugs": [],
            "counts": {"requirements": 0, "bugs": 0},
        }), 200
    result = search.search_all(keyword, limit)
    result["query"] = keyword
    return jsonify(result), 200
