"""LLM Provider 适配（real-agent-execution §3.3）。

两个 Provider 共用签名 `complete(system, user, cfg) -> LLMResult`：
- `AnthropicProvider`：Anthropic Messages API（`POST {base}/v1/messages`）。
- `OpenAICompatProvider`：OpenAI 兼容 Chat Completions（`POST {base}/chat/completions`），
  覆盖 OpenAI / vLLM / DashScope 兼容端点等自建网关。

**仅用标准库 `urllib`**，零第三方依赖（延续项目「零新依赖」传统）。

契约铁律（§3.3 · P1-2 / P2-3）：本层**只允许 `LLMError` 向上逃逸**——一切网络 /
HTTP / 超时 / JSON / 响应异形都在此归一为 `LLMError(kind=...)`，绝不让
`KeyError/IndexError/TypeError` 裸抛，从而配合上层兜底守住「外部故障绝不冒泡成 5xx」。
"""
import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from .config import LLMConfig


@dataclass
class LLMResult:
    """一次成功 LLM 调用的产物（§5.2）。"""

    text: str
    model: str
    provider: str
    latency_ms: int
    usage: dict | None = None


class LLMError(Exception):
    """LLM 调用的唯一对外异常（§5.2）。

    `kind ∈ {config, http_4xx, http_5xx, timeout, network, parse}`——
    供 `complete()` 判定是否重试、供 `generate_work` 记录降级原因。
    """

    def __init__(self, kind: str, detail: str):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


def _post_json(url: str, headers: dict, payload: dict, timeout: int) -> dict:
    """POST JSON 并解析 JSON 响应；一切失败归一为 `LLMError`（§3.3）。

    仅用 `urllib`；非 2xx 凭 `HTTPError.code` 分 4xx/5xx，超时 / 网络 / JSON 解析各归其类。
    """
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        kind = "http_4xx" if 400 <= exc.code < 500 else "http_5xx"
        raise LLMError(kind, f"HTTP {exc.code}") from exc
    except socket.timeout as exc:
        raise LLMError("timeout", f"request timed out after {timeout}s") from exc
    except urllib.error.URLError as exc:
        # URLError 可能包裹 socket.timeout（连接阶段超时），归一到 timeout。
        if isinstance(exc.reason, socket.timeout):
            raise LLMError("timeout", f"request timed out after {timeout}s") from exc
        raise LLMError("network", f"network error: {exc.reason}") from exc
    try:
        return json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise LLMError("parse", "response body is not valid JSON") from exc


class AnthropicProvider:
    """Anthropic Messages API 适配。"""

    name = "anthropic"

    def complete(self, system: str, user: str, cfg: LLMConfig) -> LLMResult:
        url = cfg.base_url.rstrip("/") + "/v1/messages"
        headers = {
            "x-api-key": cfg.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": cfg.model,
            "max_tokens": cfg.max_tokens,
            "temperature": cfg.temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        started = time.monotonic()
        resp = _post_json(url, headers, payload, cfg.timeout_seconds)
        latency_ms = int((time.monotonic() - started) * 1000)
        return LLMResult(
            text=_parse_anthropic(resp), model=cfg.model, provider=self.name,
            latency_ms=latency_ms, usage=_as_usage(resp.get("usage")),
        )


class OpenAICompatProvider:
    """OpenAI 兼容 Chat Completions 适配（覆盖自建 / 国产兼容网关）。"""

    name = "openai"

    def complete(self, system: str, user: str, cfg: LLMConfig) -> LLMResult:
        url = cfg.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {cfg.api_key}",
            "content-type": "application/json",
        }
        payload = {
            "model": cfg.model,
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        started = time.monotonic()
        resp = _post_json(url, headers, payload, cfg.timeout_seconds)
        latency_ms = int((time.monotonic() - started) * 1000)
        return LLMResult(
            text=_parse_openai(resp), model=cfg.model, provider=self.name,
            latency_ms=latency_ms, usage=_as_usage(resp.get("usage")),
        )


def _parse_anthropic(resp: dict) -> str:
    """解析 Anthropic 响应首个 text 块；空 content / 异形块 → LLMError(parse)（P2-3）。"""
    content = resp.get("content") if isinstance(resp, dict) else None
    if not isinstance(content, list) or not content:
        raise LLMError("parse", "anthropic response has empty content")
    first = content[0]
    text = first.get("text") if isinstance(first, dict) else None
    if not isinstance(text, str):
        raise LLMError("parse", "anthropic first content block is not text")
    return text


def _parse_openai(resp: dict) -> str:
    """解析 OpenAI 响应首条 message；空 choices / 缺 content → LLMError(parse)（P2-3）。"""
    choices = resp.get("choices") if isinstance(resp, dict) else None
    if not isinstance(choices, list) or not choices:
        raise LLMError("parse", "openai response has empty choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    text = message.get("content") if isinstance(message, dict) else None
    if not isinstance(text, str):
        raise LLMError("parse", "openai message content is missing")
    return text


def _as_usage(usage) -> dict | None:
    return usage if isinstance(usage, dict) else None


def get_provider(cfg: LLMConfig):
    """按 cfg.provider 选择 Provider；未知 provider → LLMError(config)。"""
    if cfg.provider == "anthropic":
        return AnthropicProvider()
    if cfg.provider == "openai":
        return OpenAICompatProvider()
    raise LLMError("config", f"unsupported provider: {cfg.provider}")
