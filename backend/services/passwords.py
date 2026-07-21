"""全站统一口令策略（account-security-and-governance §2.1 A-1）。

**本模块是口令规则的唯一真相源**，作用于所有会写 `users.password_hash` 的路径：
自助注册、管理员建号（两条路由）、管理员重置、成员自助改密。上一轮那句
「作用范围严格限定为 `POST /api/auth/signup`」连同它描述的边界一起被删掉了——
同一个产品里安全水位由「你是怎么进来的」决定，本身就是缺陷（spec §0.2-1）。

配置只提供两个**阈值旋钮**（`PASSWORD_MIN_LENGTH` / `PASSWORD_MIN_CHAR_CLASSES`），
它们的合法区间、脏值回落与钳位全部收敛在 `policy()` 里。

规则与前端 `components/auth/PasswordStrength.tsx` **逐条对应**：前端提前拦下的一定是
后端也会拒的，反之亦然——两边任何一侧单方面收紧，都会制造「界面说没问题、提交却 400」
或「界面标红、其实能过」的困惑。策略值经 `GET /api/auth/registration-meta` 下发，
前端不再硬编码任何阈值。
"""
import secrets

from flask import current_app

from services.validation import ValidationError

# 输入上限。与 users.password_hash 的列宽无关，纯粹是防超长哈希开销；
# 同时是前端 PasswordStrength.tsx 的镜像值，两侧必须一致。
PASSWORD_MAX_LENGTH = 128
DEFAULT_MIN_LENGTH = 8
DEFAULT_MIN_CHAR_CLASSES = 2

# 旋钮的物理止挡（见模块 docstring 与 config.py 的同一段注释）。
_MIN_LENGTH_FLOOR = 6
_CHAR_CLASSES_FLOOR = 1
_CHAR_CLASSES_CEIL = 4

# 字符类别判据。第四类是「其余可打印字符」（标点 / 符号），不枚举具体集合——
# 枚举等于把用户可用的符号限制在我们想得到的那些里。
_CHAR_CLASSES = (
    ("lowercase", str.islower),
    ("uppercase", str.isupper),
    ("digit", str.isdigit),
)

# 一次性口令的字符集：去掉易混字符，与 app_settings._CODE_ALPHABET 同一取向
# （人要口述 / 手抄它）。符号类**去掉引号 / 反斜杠 / 空格**——它们会在复制粘贴、
# shell、CSV 里被吃掉或转义。
_UPPER = "ABCDEFGHJKMNPQRSTUVWXYZ"   # 去掉 I O
_LOWER = "abcdefghijkmnpqrstuvwxyz"  # 去掉 l o
_DIGIT = "23456789"                  # 去掉 0 1
_SYMBOL = "!@#$%*+-="
_GENERATOR_CLASSES = (_UPPER, _LOWER, _DIGIT, _SYMBOL)

# 一次性口令的硬顶：人还要手抄它。**策略下限高于它时以策略为准**——
# 宁可生成一个抄起来很痛苦的口令，也不能生成一个不合法的口令。
_TEMP_PASSWORD_HARD_CAP = 64


def _clamped_config_int(key: str, default: int, low: int, high: int) -> int:
    """读一个整数旋钮并钳到 [low, high]；脏值回落默认 + warning，**不抛异常**。

    与 `services/app_settings.py` 的「脏值一律回落 + warning」同一取向：口令策略
    配置写错了不该让整个登录体系 500。

    Args:
        key: config 键名。
        default: 缺省 / 脏值时的回落值。
        low: 钳位下界（含）。
        high: 钳位上界（含）。

    Returns:
        钳位后的整数。
    """
    raw = current_app.config.get(key, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        current_app.logger.warning(
            "passwords: unparsable %s=%r, falling back to %s", key, raw, default)
        value = default
    return max(low, min(value, high))


def policy() -> dict:
    """当前生效的口令策略。**唯一**读取配置的地方。

    Returns:
        `{"min_length": int, "max_length": int, "min_char_classes": int}`。
    """
    return {
        "min_length": _clamped_config_int(
            "PASSWORD_MIN_LENGTH", DEFAULT_MIN_LENGTH,
            _MIN_LENGTH_FLOOR, PASSWORD_MAX_LENGTH),
        "max_length": PASSWORD_MAX_LENGTH,
        "min_char_classes": _clamped_config_int(
            "PASSWORD_MIN_CHAR_CLASSES", DEFAULT_MIN_CHAR_CLASSES,
            _CHAR_CLASSES_FLOOR, _CHAR_CLASSES_CEIL),
    }


def describe(pol: dict | None = None) -> str:
    """把策略渲染成一句人类可读的完整规则串（用作 ValidationError.expected）。"""
    pol = pol or policy()
    return (f"at least {pol['min_length']} chars (max {pol['max_length']}), "
            f"at least {pol['min_char_classes']} character classes, "
            f"different from the username and from the current password")


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


def validate_password(password: str, *, username: str | None = None,
                      current_password: str | None = None) -> None:
    """校验口令；不满足即抛 ValidationError（→ 全局 400）。

    规则与判定**顺序**（顺序是契约的一部分，见 spec §8.1 对既有用例的影响分析）：

    1. 长度 ∈ [min_length, max_length]。
    2. 至少命中 min_char_classes 类字符（小写 / 大写 / 数字 / 其他可打印）。
    3. 若给了 username：不等于用户名（casefold 比较）——「用户名即密码」是撞库的第一发子弹。
    4. 若给了 current_password：不等于当前口令（区分大小写，逐字节比较）。

    Args:
        password: 明文口令（**绝不记日志**）。
        username: 同一次请求里的用户名；None 表示该规则不适用。
        current_password: 当前口令明文；None 表示该规则不适用。

    Raises:
        ValidationError: `detail.field` 恒为 "password"，`expected` 恒为人类可读的完整规则串。
    """
    pol = policy()
    expected = describe(pol)
    if not pol["min_length"] <= len(password) <= pol["max_length"]:
        raise ValidationError(
            f"password must be {pol['min_length']}..{pol['max_length']} chars",
            field="password", expected=expected)
    if count_char_classes(password) < pol["min_char_classes"]:
        raise ValidationError(
            f"password must contain at least {pol['min_char_classes']} character classes",
            field="password", expected=expected)
    if username is not None and password.casefold() == (username or "").casefold():
        raise ValidationError("password must differ from the username",
                              field="password", expected=expected)
    if current_password is not None and password == current_password:
        # 对外错误契约（`POST /api/me/password` 的既有错误串），**一个字都不改**。
        raise ValidationError("new password must differ from current",
                              field="password", expected=expected)


def validate_signup_password(password: str, username: str) -> None:
    """**保留的稳定别名**（= `validate_password(password, username=username)`）。

    改名等同破坏性变更（CLAUDE.md §五）。它今天的唯一调用点是 `routes/auth.py::signup`，
    但它已经出现在上一轮 spec 的接口表里，删掉等于让那份文档说谎。
    """
    validate_password(password, username=username)


def generate_temporary_password(length: int | None = None) -> str:
    """生成一个**构造上必然满足策略**的一次性口令。

    长度区间由 `policy()` **派生**而不是与它并列取 max：`lower = min_length + 4`
    保证下界恒严格满足策略，`upper = max(lower, ...)` 保证区间恒非空。写成
    `[max(min_length, 8), 32]` 会在 `min_length > 32` 的**合法配置**下变成空区间，
    生成出一个违反自己策略的口令（spec 评审 P1-1）。

    Args:
        length: 期望长度；None 表示读 `TEMP_PASSWORD_LENGTH` 配置。仍会被钳位。

    Returns:
        明文一次性口令。**仅供本次响应体使用**：绝不落库、绝不记日志。

    Raises:
        ValidationError: 生成结果不满足策略——那是代码缺陷（生成器与策略脱钩），
            不是用户输入问题，必须 500 而不是被静默降级。
    """
    pol = policy()
    # `lower` 由 min_length **派生**（而不是与它并列取 max），保证下界恒严格满足策略；
    # 再被 max_length 上钳——`min_length == max_length == 128` 时「留 4 位余量」会派生出
    # 132，反过来撞破策略的长度上限（spec 评审 P1-1 的修复本身仍差这一步，见
    # 「实施过程发现的方案缺陷」）。
    lower = min(max(pol["min_length"] + 4, 16), pol["max_length"])
    upper = max(lower, min(_TEMP_PASSWORD_HARD_CAP, pol["max_length"]))
    wanted = length or current_app.config.get("TEMP_PASSWORD_LENGTH", 16)
    try:
        wanted = int(wanted)
    except (TypeError, ValueError):
        wanted = lower
    size = min(max(wanted, lower), upper)

    # 先从前 min_char_classes 个子集各取 1 个字符，保证类别数达标；
    # 再从并集补足 size，最后洗牌。**禁止 `random` 模块**：凭据必须不可预测
    # （与 app_settings.generate_invite_code 同一条铁律）。
    needed_classes = min(pol["min_char_classes"], len(_GENERATOR_CLASSES))
    chars = [secrets.choice(_GENERATOR_CLASSES[i]) for i in range(needed_classes)]
    pool = "".join(_GENERATOR_CLASSES)
    chars.extend(secrets.choice(pool) for _ in range(size - len(chars)))
    for i in range(len(chars) - 1, 0, -1):          # Fisher–Yates，取随机源同上
        j = secrets.randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]

    result = "".join(chars)
    # 让「构造保证策略」这个不变量由**唯一真相源**裁决：策略以后怎么改，这一行都不会说谎。
    validate_password(result)
    return result
