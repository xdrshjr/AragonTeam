"""查询串整型边界 + 项目作用域过滤（scale-and-project-scope §2.4 / §2.6①-C）。

【为什么在这里】`services/validation.py` 管的是**请求体**（已归一为 dict 的字段），
`app.py::BoundedIntConverter` 管的是**URL 路径**。查询串是第三条独立路径：
`request.args.get(k, type=int)` 会把任意长度的十进制串解析成 Python 大整数，随后
`filter_by(...)` / `.offset(...)` 把它绑进 SQLite，触
`OverflowError: Python int too large to convert to SQLite INTEGER` → 500。
本模块把「取一个查询串整数」收敛为一处带 64 位钳制的边界函数。

契约：`?project_id=` 缺省 / 空串 = 不过滤；整数 = 该项目；字面量 `none` = 未归属
（`project_id IS NULL`）；其余取值（含超界整数）= 400（沿用前两轮「坏输入一律 400」的既定契约）。
"""
from flask import request, jsonify

UNASSIGNED = "none"

# SQLite / 多数 RDBMS 的 INTEGER 值域（64 位有符号）。与 app.py::MAX_DB_INT 同一常量语义，
# 但**有意各自定义**：app.py 属应用装配层，services 不反向依赖它（避免 service→app 依赖倒置）。
MIN_DB_INT = -(2 ** 63)
MAX_DB_INT = 2 ** 63 - 1


class QueryParamError(Exception):
    """查询串参数取值非法（类型错 / 超界）；由 errors.py 的全局处理器统一转成 400 响应。

    稳定异常类，勿更名（对外错误契约，CLAUDE.md §五）。
    """

    def __init__(self, field: str, got, expected: str):
        super().__init__(f"invalid {field}")
        self.field = field
        self.got = got
        self.expected = expected


# 【向后兼容别名】早期草稿用的名字；保留以免下游按旧名 import。
ProjectScopeError = QueryParamError


def want_query_int(field: str, *, default=None, minimum=None, maximum=None,
                   clamp: bool = False):
    """从查询串取一个整数，缺省返回 default；非法 / 超界一律抛 QueryParamError（→ 400）。

    Args:
        field: 查询串参数名（同时用作错误体的 detail.field）。
        default: 参数缺省 / 空串时的返回值。
        minimum: 调用方附加下界；**与 64 位硬界取交集**，不得放宽它。
        maximum: 调用方附加上界；同上。
        clamp: 越界时钳到界内而非报错（仅用于「取值本身就是一个上限」的参数，如
            `?limit=`——它从不被当作主键绑进 SQL，钳制是其既有且更友好的语义；见
            spec §实施过程发现的方案缺陷 F1）。非整数仍恒报错。

    Returns:
        int 或 default。

    Raises:
        QueryParamError: 非十进制整数；或（clamp=False 时）落在界外。
    """
    raw = request.args.get(field)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise QueryParamError(field, raw, "integer")
    # 硬界优先：超出 64 位的值不可能命中任何主键，也不能被绑进 SQLite。
    lo = MIN_DB_INT if minimum is None else max(minimum, MIN_DB_INT)
    hi = MAX_DB_INT if maximum is None else min(maximum, MAX_DB_INT)
    if clamp:
        return max(lo, min(value, hi))
    if value < MIN_DB_INT or value > MAX_DB_INT:
        raise QueryParamError(field, raw, "integer within 64-bit range")
    if value < lo or value > hi:
        raise QueryParamError(field, raw, f"integer in [{lo}, {hi}]")
    return value


def want_query_str(field: str, *, default=None, choices=None):
    """从查询串取一个字符串，缺省 / 空串返回 default；不在 choices 内抛 QueryParamError（→ 400）。

    「空串等价于不传」是全站列表筛选的既定语义（`?q=` 被清空时前端仍会带上这个键）。

    Args:
        field: 查询串参数名（同时用作错误体的 detail.field）。
        default: 参数缺省 / 空串时的返回值。
        choices: 合法取值集合；为 None 表示任意串（如自由文本 `?q=`）。

    Returns:
        str 或 default。

    Raises:
        QueryParamError: 给了 choices 且取值不在其中。
    """
    raw = request.args.get(field)
    if raw is None:
        return default
    value = raw.strip()
    if value == "":
        return default
    if choices is not None and value not in set(choices):
        raise QueryParamError(field, raw, f"one of {sorted(set(choices))}")
    return value


_TRUE_LITERALS = ("true", "1")
_FALSE_LITERALS = ("false", "0")


def want_query_bool(field: str, *, default=None):
    """从查询串取一个布尔值，接受 true/false/1/0（大小写不敏感）；其余取值一律 400。

    **有意不做**「无法解析就当 False」的宽容处理：`?is_active=ture` 这样的手滑会静默
    变成「只看已停用的人」，管理员据此以为团队里没人——错得无声无息，比 400 危险得多。

    Args:
        field: 查询串参数名。
        default: 参数缺省 / 空串时的返回值。

    Returns:
        bool 或 default。

    Raises:
        QueryParamError: 取值不是可识别的布尔字面量。
    """
    raw = request.args.get(field)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in _TRUE_LITERALS:
        return True
    if value in _FALSE_LITERALS:
        return False
    raise QueryParamError(field, raw, "one of ['0', '1', 'false', 'true']")


def project_scope():
    """解析 `?project_id=`。返回 None（不过滤）/ UNASSIGNED / int。非法值抛 QueryParamError。"""
    if request.args.get("project_id") == UNASSIGNED:
        return UNASSIGNED
    return want_query_int("project_id")


def apply_project_filter(query, model, scope):
    """把 project_scope() 的结果套到 query 上；scope 为 None 时原样返回。

    Args:
        query: 任意 SQLAlchemy Query（模型查询或聚合查询皆可）。
        model: 提供 project_id 列的模型类。
        scope: project_scope() 的返回值。
    """
    if scope is None:
        return query
    if scope == UNASSIGNED:
        return query.filter(model.project_id.is_(None))
    return query.filter(model.project_id == scope)


def query_error_response(exc: QueryParamError):
    """统一 400 响应体，与既有 validation 错误契约（{error, detail:{field, expected}}）同形。

    路由内一般**无需**调用它——errors.py 已注册全局处理器；仅供确实需要提前返回的场景。
    """
    return jsonify({
        "error": f"invalid {exc.field}",
        "detail": {"field": exc.field, "expected": exc.expected, "got": str(exc.got)},
    }), 400


# 【向后兼容别名】同上。
scope_error_response = query_error_response
