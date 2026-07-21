"""整数配置旋钮的读取与钳位（login-hardening-and-audit-console §1.2 B-2）。

本模块从 `services/passwords.py::_clamped_config_int` 提升而来——出现**第二个**调用点
（`services/login_guard.py`）正是抽取的时机，在此之前把它留在口令模块里是对的。

与 `services/app_settings.py` 的「脏值一律回落 + warning，绝不抛」同一取向：一个写错的
配置项不该让整个登录体系 500。钳位不是防御性编程，是给人类可写的旋钮加物理止挡——
`PASSWORD_MIN_LENGTH=0` 会让策略静默变成「没有策略」，`LOGIN_LOCK_THRESHOLD=0` 会让
第一次敲错就锁死全站。
"""
from flask import current_app


def clamped_int(key: str, default: int, low: int, high: int, *, source: str) -> int:
    """读一个整数旋钮并钳到 [low, high]；脏值回落默认 + warning，**不抛异常**。

    Args:
        key: config 键名。
        default: 缺省 / 脏值时的回落值。
        low: 钳位下界（含）。
        high: 钳位上界（含）。
        source: 打日志时的模块前缀。**必传且无默认值**：格式串原先把 `"passwords: …"`
            硬编在里面，共用之后一个写错的 `LOGIN_LOCK_THRESHOLD` 会打出
            `passwords: unparsable LOGIN_LOCK_THRESHOLD=…`，运维照这条日志去翻口令模块——
            一条**主动误导**的日志比没有日志更贵（spec 评审 P1-4）。

    Returns:
        钳位后的整数。
    """
    raw = current_app.config.get(key, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        current_app.logger.warning(
            "%s: unparsable %s=%r, falling back to %s", source, key, raw, default)
        value = default
    return max(low, min(value, high))
