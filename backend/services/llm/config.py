"""LLM 服务层配置（real-agent-execution §5.2 / §5.3）。

`LLMConfig.from_env()` 把 `AGENT_LLM_*` 环境变量解析成不可变配置对象；未配置
（`provider=none` 或无凭据）即「离线模式」——执行层据此优雅回退确定性文案。
所有字段均有默认值，未设任何变量即今日行为（与 `config.Config` 同风格，开箱即用）。
"""
import os
from dataclasses import dataclass

# 支持的 provider；其余（含拼写错误 / 空值）一律归一到 "none"（离线）。
_PROVIDERS = ("anthropic", "openai", "none")

# 各 provider 官方默认端点（拼接前统一去尾 `/`，见 providers.py，P2-5）。
# openai 兼容端点**须含 `/v1`**；anthropic 内部再拼 `/v1/messages`。
_DEFAULT_BASE_URL = {
    "anthropic": "https://api.anthropic.com",
    "openai": "https://api.openai.com/v1",
}

# 各 provider 默认模型（可由 AGENT_LLM_MODEL 覆盖）。
_DEFAULT_MODEL = {
    "anthropic": "claude-opus-4-8",
    "openai": "gpt-4o-mini",
}

# provider → 凭据兜底环境变量：AGENT_LLM_API_KEY 为空时回落官方 SDK 惯用名。
_FALLBACK_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class LLMConfig:
    """一次进程内的 LLM 配置快照（不落库，`from_env()` 现读现算）。"""

    provider: str
    api_key: str
    base_url: str
    model: str
    max_tokens: int
    temperature: float
    timeout_seconds: int
    max_retries: int

    @classmethod
    def from_env(cls) -> "LLMConfig":
        provider = (os.environ.get("AGENT_LLM_PROVIDER") or "none").strip().lower()
        if provider not in _PROVIDERS:
            provider = "none"
        return cls(
            provider=provider,
            api_key=_resolve_api_key(provider),
            base_url=_resolve_base_url(provider),
            model=_resolve_model(provider),
            max_tokens=_env_int("AGENT_LLM_MAX_TOKENS", 700),
            temperature=_env_float("AGENT_LLM_TEMPERATURE", 0.4),
            timeout_seconds=_env_int("AGENT_LLM_TIMEOUT", 30),
            max_retries=_env_int("AGENT_LLM_MAX_RETRIES", 2),
        )

    @property
    def enabled(self) -> bool:
        return self.provider != "none" and bool(self.api_key)


def _resolve_api_key(provider: str) -> str:
    explicit = (os.environ.get("AGENT_LLM_API_KEY") or "").strip()
    if explicit:
        return explicit
    fallback_env = _FALLBACK_KEY_ENV.get(provider)
    return (os.environ.get(fallback_env) or "").strip() if fallback_env else ""


def _resolve_base_url(provider: str) -> str:
    raw = os.environ.get("AGENT_LLM_BASE_URL") or _DEFAULT_BASE_URL.get(provider, "")
    return raw.strip().rstrip("/")


def _resolve_model(provider: str) -> str:
    return (os.environ.get("AGENT_LLM_MODEL") or _DEFAULT_MODEL.get(provider, "")).strip()
