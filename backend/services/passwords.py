"""自助注册的口令强度策略（self-service-registration §2.2 B-4）。

**作用范围严格限定为 `POST /api/auth/signup`。** 有意**不**套用到
`POST /api/users`（管理员建号）与 `POST /api/me/password`（自助改密）：那两条路径今天
没有任何长度约束，存量测试里存在 6 位口令的用例，收紧它们等于一次破坏性变更。
统一全站口令策略是明确的后续项（spec §10 Non-Goals），不在本轮。

规则与前端 `components/auth/PasswordStrength.tsx` **逐条对应**：前端提前拦下的一定是
后端也会拒的，反之亦然——两边任何一侧单方面收紧，都会制造「界面说没问题、提交却 400」
或「界面标红、其实能过」的困惑。
"""
from services.validation import ValidationError

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128

# 字符类别判据。第四类是「其余可打印字符」（标点 / 符号），不枚举具体集合——
# 枚举等于把用户可用的符号限制在我们想得到的那些里。
_CHAR_CLASSES = (
    ("lowercase", str.islower),
    ("uppercase", str.isupper),
    ("digit", str.isdigit),
)

MIN_CHAR_CLASSES = 2

_EXPECTED = (f"at least {PASSWORD_MIN_LENGTH} chars, at least {MIN_CHAR_CLASSES} "
             f"character classes, and different from the username")


def count_char_classes(password: str) -> int:
    """命中的字符类别数：小写 / 大写 / 数字 / 其他可打印。

    Args:
        password: 待检查的明文口令。

    Returns:
        0~4 之间的整数。
    """
    hit = sum(1 for _name, predicate in _CHAR_CLASSES
              if any(predicate(ch) for ch in password))
    others = any(not ch.isalnum() and not ch.isspace() for ch in password)
    return hit + (1 if others else 0)


def validate_signup_password(password: str, username: str) -> None:
    """校验自助注册口令；不满足即抛 ValidationError（→ 全局 400）。

    规则（三条，全部对用户可解释）：
    1. 长度 ∈ [8, 128]。
    2. 至少命中两类字符（小写 / 大写 / 数字 / 其他可打印）。
    3. 不等于用户名（大小写不敏感比较）——「用户名即密码」是撞库的第一发子弹。

    Args:
        password: 明文口令（**绝不记日志**）。
        username: 同一次注册请求里的用户名。

    Raises:
        ValidationError: 任一规则不满足；`detail.field` 恒为 "password"。
    """
    if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        raise ValidationError(
            f"password must be {PASSWORD_MIN_LENGTH}..{PASSWORD_MAX_LENGTH} chars",
            field="password", expected=_EXPECTED)
    if count_char_classes(password) < MIN_CHAR_CLASSES:
        raise ValidationError(
            f"password must contain at least {MIN_CHAR_CLASSES} character classes",
            field="password", expected=_EXPECTED)
    if password.casefold() == (username or "").casefold():
        raise ValidationError("password must differ from the username",
                              field="password", expected=_EXPECTED)
