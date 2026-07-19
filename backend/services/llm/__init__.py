"""LLM 公共 API（real-agent-execution §3.3 / §5.2）。

对外只暴露四件事：
- `is_enabled()`：当前环境是否配置了可用凭据（决定「真 / 离线」）。
- `complete(system, user)`：一次带**有界重试 + 结构化日志 + 归一异常**的补全调用；
  只可能抛 `LLMError`（provider 层已把一切失败归一）。
- `describe()`：`/api/health` 用的只读快照（**从不**含密钥）。
- `LLMResult` / `LLMError`：由 providers 定义、此处再导出的公共数据结构。

重试策略：仅对 timeout / http_5xx / network 重试，指数退避 0.5s、1s；对 http_4xx
（鉴权/参数）/ parse / config **立即抛出不重试**（重试无益、徒增 p99）。
结构化日志只记 provider / model / latency / usage / retries / 降级因，
**绝不**记 Authorization / x-api-key 头与请求 payload（§8 R7 / P2-4）。
"""
import logging
import time
from dataclasses import replace

from .config import LLMConfig
from .providers import LLMError, LLMResult, get_provider

__all__ = ["is_enabled", "complete", "describe", "LLMConfig", "LLMResult", "LLMError"]

_LOG = logging.getLogger(__name__)

# 可重试的错误类型（瞬时 / 服务端 / 网络）；其余立即抛出。
_RETRYABLE = frozenset({"timeout", "http_5xx", "network"})


def is_enabled() -> bool:
    """是否配置了可用的模型凭据（`provider != none` 且 `api_key` 非空）。"""
    return LLMConfig.from_env().enabled


def describe() -> dict:
    """`/api/health` 只读块：启用时报 provider/model，否则统一 none/null（**不回传密钥**）。"""
    cfg = LLMConfig.from_env()
    if not cfg.enabled:
        return {"enabled": False, "provider": "none", "model": None}
    return {"enabled": True, "provider": cfg.provider, "model": cfg.model}


def complete(system: str, user: str, *, max_tokens=None, temperature=None) -> LLMResult:
    """一次补全（含重试 / 日志）。未配置 → `LLMError(config)`；失败 → 对应 kind 的 `LLMError`。"""
    cfg = _effective_config(max_tokens, temperature)
    if not cfg.enabled:
        raise LLMError("config", "LLM is not configured")
    provider = get_provider(cfg)

    attempt = 0
    while True:
        try:
            result = provider.complete(system, user, cfg)
            _log_success(result, attempt)
            return result
        except LLMError as err:
            if err.kind not in _RETRYABLE or attempt >= cfg.max_retries:
                _log_failure(cfg, err, attempt)
                raise
            _LOG.info("llm.complete retry provider=%s kind=%s attempt=%d",
                      cfg.provider, err.kind, attempt)
            time.sleep(_backoff(attempt))
            attempt += 1


def _effective_config(max_tokens, temperature) -> LLMConfig:
    """按可选覆盖派生本次调用配置（不改环境快照本体）。"""
    cfg = LLMConfig.from_env()
    overrides = {}
    if max_tokens is not None:
        overrides["max_tokens"] = max_tokens
    if temperature is not None:
        overrides["temperature"] = temperature
    return replace(cfg, **overrides) if overrides else cfg


def _backoff(attempt: int) -> float:
    """指数退避：attempt 0 → 0.5s，attempt 1 → 1.0s（§3.3）。"""
    return 0.5 * (2 ** attempt)


def _log_success(result: LLMResult, retries: int) -> None:
    _LOG.info("llm.complete ok provider=%s model=%s latency_ms=%d retries=%d usage=%s",
              result.provider, result.model, result.latency_ms, retries, result.usage)


def _log_failure(cfg: LLMConfig, err: LLMError, retries: int) -> None:
    _LOG.warning("llm.complete failed provider=%s model=%s kind=%s retries=%d detail=%s",
                 cfg.provider, cfg.model, err.kind, retries, err.detail)
