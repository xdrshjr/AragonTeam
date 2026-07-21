"""登录限流（Phase-2 §2.5-4 · 内存滑动窗口）。

仅拦**失败**登录尝试：某 (ip:username) 键在 5 分钟窗口内失败次数达阈值即拒绝；
登录成功清零。明确为 **MVP 单机版**：重启即清空、多副本不共享，
生产改 Redis（# TODO(ratelimit-distributed)）——不作为唯一安全边界。

【R-03 测试隔离】存储**不用**裸模块级全局字典（否则跨用例不复位、429 断言顺序
敏感）：挂到 `app.extensions["ratelimit"]` 上，随每个测试 app 实例自然重建；
另提供 reset() 供 conftest autouse fixture 兜底复位。

【self-service-registration §2.2 B-2】本模块也被 `/auth/signup` 用作**通用事件计数器**：
那里成功与失败都调 `record_failure`（要挡的既是暴力猜邀请码，也是批量注册）。函数名
沿用不改——它是稳定 API，改名等同破坏性变更（CLAUDE.md §五）。
"""
import time

from flask import current_app, request

# 滑动窗口宽度（秒）。
WINDOW_SECONDS = 300


def client_ip() -> str:
    """限流用的客户端标识。**默认与 `request.remote_addr` 逐字节相同**。

    【为什么不直接接 werkzeug 的 ProxyFix】ProxyFix 是全局中间件，一旦装上，**所有**读
    remote_addr 的地方都无条件相信 `X-Forwarded-For`。而这个头是客户端可写的：直连部署下
    装它，等于把限流键的取值权交给攻击者，每个请求换一个伪造 IP 即可绕过限流。故改为
    显式配置 + 只在服务端可控的那几跳上取值（self-service-registration §2.2 B-2′ / R-14）。

    - `TRUST_PROXY_COUNT = 0`（默认）：直接返回 remote_addr，**不看任何转发头**。
    - `TRUST_PROXY_COUNT = N > 0`：取 `X-Forwarded-For` 列表**从右往左**第 N 个
      （右端是最靠近服务端、最不可伪造的一跳）；列表长度不足或头缺失则回落 remote_addr。

    【部署提醒】本仓库自带 nginx 反代模板（`ops/templates/aragonteam-nginx-http`），
    那种部署下 remote_addr 恒为 127.0.0.1，限流会退化成**全站单桶**；此时必须置 1。

    Returns:
        非空字符串；完全取不到时返回 "unknown"（与既有 login 的兜底逐字相同）。
    """
    fallback = request.remote_addr or "unknown"
    trusted = current_app.config.get("TRUST_PROXY_COUNT", 0) or 0
    if trusted <= 0:
        return fallback
    forwarded = request.headers.get("X-Forwarded-For", "")
    hops = [h.strip() for h in forwarded.split(",") if h.strip()]
    if len(hops) < trusted:
        return fallback
    return hops[-trusted]


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
