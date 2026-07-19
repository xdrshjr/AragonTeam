"""统一 JSON 输入边界校验（reliability-hardening §2.2 硬化新增）。

【为什么】既有路由用 `request.get_json(silent=True) or {}` + `(data.get(k) or "").strip()`，
只防「字段缺失」，不防「类型错误」：非对象 JSON 体（5/[1]/"x"）为真值 → .get 触 AttributeError；
非字符串字段（123）为真值 → .strip()/正则触 TypeError；均在边界冒泡成 500（含公开 /login）。
本模块把「拿到一个 dict」「取一个受校验字段」收敛为可复用、可单测的边界函数，
错误统一走 400 JSON 契约 {error, detail:{field, expected}}，绝不 500。
"""
from typing import Optional, Iterable

from flask import request


# SQLite / 多数 RDBMS 的 INTEGER 值域（64 位有符号）。与 services/scope.py 的同名常量
# **有意各自定义**（两者互不依赖，都是叶子边界模块），数值必须一致——测试断言其相等防漂移。
_MIN_DB_INT = -(2 ** 63)
_MAX_DB_INT = 2 ** 63 - 1


class ValidationError(Exception):
    """边界校验失败 → 由 errors.py 统一渲染为 400。稳定异常类，勿更名（对外错误契约）。"""

    def __init__(self, message: str, *, field: Optional[str] = None,
                 expected: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.field = field
        self.expected = expected


def json_body() -> dict:
    """始终返回 dict：非 JSON / 非对象体一律回 {}（缺字段交由各字段的必填/默认校验）。"""
    d = request.get_json(silent=True)
    return d if isinstance(d, dict) else {}


def want_str(data: dict, key: str, *, required: bool = False, default: str = "",
             strip: bool = True, max_len: Optional[int] = None,
             choices: Optional[Iterable[str]] = None) -> str:
    """从 data 取一个字符串字段；类型错误抛 ValidationError（→ 400），绝不 500。

    Args:
        data: 已经过 json_body() 归一的 dict。
        key: 字段名。
        required: 缺失 / 空串是否视为错误。
        default: 缺失时的返回值（required=False 时生效）。
        strip: 是否去除首尾空白。
        max_len: 最大长度（含）；超出即 400。
        choices: 合法取值集合；不在集合内即 400。**空串回退 default**（§2.5，不落库非法 ""）。

    不变量（【评审 R6】）：**非必填的枚举调用方（`required=False` + `choices=`）必须同时传
    `default`（且 `default ∈ choices`）**——否则归一后的空串会回退成非法的默认空串 ""，绕过枚举校验。
    `required=True` 的枚举调用方不受此约束（空串已在上面 raise，走不到回退分支）。现网非必填枚举
    调用方（priority→medium / severity→major / kind→generic / role→member）均满足此不变量。

    Returns:
        清洁后的字符串。

    Raises:
        ValidationError: 类型错误 / 必填缺失 / 超长 / 越界枚举。
    """
    v = data.get(key, None)
    if v is None:
        if required:
            raise ValidationError(f"{key} is required", field=key, expected="non-empty string")
        return default
    if not isinstance(v, str):
        raise ValidationError(f"{key} must be a string", field=key, expected="string")
    if strip:
        v = v.strip()
    if required and not v:
        raise ValidationError(f"{key} is required", field=key, expected="non-empty string")
    if max_len is not None and len(v) > max_len:
        raise ValidationError(f"{key} is too long", field=key, expected=f"length<={max_len}")
    if choices is not None and not v:
        # 【§2.5】有枚举 + 归一后为空 → 回退 default（不落库非法空串；required=True 的空串已在上面 raise）。
        return default
    if choices is not None and v not in set(choices):
        raise ValidationError(f"{key} is invalid", field=key,
                              expected=f"one of {sorted(set(choices))}")
    return v


def want_int(data: dict, key: str, *, required: bool = False, default: Optional[int] = None,
             minimum: Optional[int] = None, maximum: Optional[int] = None) -> Optional[int]:
    """从 data 取一个整数字段；类型错误抛 ValidationError（→ 400）。

    不接受数字字符串（JSON 体应传数字）；bool 是 int 子类，显式排除。

    不变量（scale-and-project-scope §2.6①-B / 评审 R6）：64 位硬界**无条件**生效，
    调用方的 minimum/maximum 只能在其内部再收窄、不能放宽——故硬界**不经形参暴露**。
    """
    v = data.get(key, None)
    if v is None:
        if required:
            raise ValidationError(f"{key} is required", field=key, expected="integer")
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise ValidationError(f"{key} must be an integer", field=key, expected="integer")
    # 【§2.6①-B】64 位硬界：超出即不可能是任何主键，且绑进 SQLite 会 OverflowError → 500。
    if v < _MIN_DB_INT or v > _MAX_DB_INT:
        raise ValidationError(f"{key} is out of range", field=key,
                              expected="integer within 64-bit range")
    if minimum is not None and v < minimum:
        raise ValidationError(f"{key} is out of range", field=key, expected=f">={minimum}")
    if maximum is not None and v > maximum:
        raise ValidationError(f"{key} is out of range", field=key, expected=f"<={maximum}")
    return v


def want_bool(data: dict, key: str, *, default: bool = False) -> bool:
    """从 data 取一个布尔字段；类型错误抛 ValidationError（→ 400）。"""
    v = data.get(key, None)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise ValidationError(f"{key} must be a boolean", field=key, expected="boolean")
    return v
