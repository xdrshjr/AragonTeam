"""登录限流（Phase-2 §2.5-4 · 内存滑动窗口）。

仅拦**失败**登录尝试：某 (ip:username) 键在 5 分钟窗口内失败次数达阈值即拒绝；
登录成功清零。明确为 **MVP 单机版**：重启即清空、多副本不共享，
生产改 Redis（# TODO(ratelimit-distributed)）——不作为唯一安全边界。

【R-03 测试隔离】存储**不用**裸模块级全局字典（否则跨用例不复位、429 断言顺序
敏感）：挂到 `app.extensions["ratelimit"]` 上，随每个测试 app 实例自然重建；
另提供 reset() 供 conftest autouse fixture 兜底复位。
"""
import time

from flask import current_app

# 滑动窗口宽度（秒）。
WINDOW_SECONDS = 300


def _store() -> dict:
    """取当前 app 的限流存储（不存在则建），实现「随 app 实例重建」。"""
    ext = current_app.extensions
    store = ext.get("ratelimit")
    if store is None:
        store = {}
        ext["ratelimit"] = store
    return store


def _fresh(key: str, now: float) -> list:
    """返回 key 的窗口内有效失败时间戳列表（顺带剔除过期项、回写）。"""
    store = _store()
    times = [t for t in store.get(key, ()) if now - t < WINDOW_SECONDS]
    store[key] = times
    return times


def is_blocked(key: str, max_attempts: int) -> bool:
    """窗口内失败数是否已达阈值（达到即应拦截，返回 429）。"""
    return len(_fresh(key, time.monotonic())) >= max_attempts


def record_failure(key: str) -> None:
    """记录一次失败尝试。"""
    now = time.monotonic()
    times = _fresh(key, now)
    times.append(now)
    _store()[key] = times


def clear(key: str) -> None:
    """登录成功：清零该键。"""
    _store().pop(key, None)


def reset() -> None:
    """清空当前 app 的全部限流计数（测试 autouse fixture 用）。"""
    try:
        _store().clear()
    except RuntimeError:
        # 无 app context 时静默（测试环境外不会触及）。
        pass
