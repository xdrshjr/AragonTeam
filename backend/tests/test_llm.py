"""real-agent-execution §7.1 —— LLM 服务层单测（全程 monkeypatch，绝不触网）。

覆盖：Provider 解析（Anthropic/OpenAI）、响应异形 → parse LLMError、超时 → timeout
LLMError、重试后成功、4xx 不重试、`is_enabled` 真值表、禁用时从不触网。
"""
import json
import socket
import urllib.error
import urllib.request

import pytest

from services import llm
from services.llm.config import LLMConfig
from services.llm.providers import (
    AnthropicProvider, OpenAICompatProvider, LLMError, _post_json,
)

# 所有可能影响 from_env() 的环境变量，逐测清空，保证测试对开发机 / CI env 完全 hermetic。
_LLM_ENV = (
    "AGENT_LLM_PROVIDER", "AGENT_LLM_API_KEY", "AGENT_LLM_MODEL", "AGENT_LLM_BASE_URL",
    "AGENT_LLM_MAX_TOKENS", "AGENT_LLM_TEMPERATURE", "AGENT_LLM_TIMEOUT",
    "AGENT_LLM_MAX_RETRIES", "AGENT_LLM_WALL_BUDGET", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
)


@pytest.fixture(autouse=True)
def _clean_llm_env(monkeypatch):
    for name in _LLM_ENV:
        monkeypatch.delenv(name, raising=False)
    yield


class _FakeResp:
    """模拟 urlopen 返回的上下文管理器；`.read()` 回罐头 JSON 字节。"""

    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _cfg(provider="anthropic", **over):
    base = dict(provider=provider, api_key="sk-test",
                base_url="https://api.anthropic.com" if provider == "anthropic"
                else "https://api.openai.com/v1",
                model="test-model", max_tokens=700, temperature=0.4,
                timeout_seconds=30, max_retries=2)
    base.update(over)
    return LLMConfig(**base)


def _patch_urlopen(monkeypatch, fn):
    monkeypatch.setattr(urllib.request, "urlopen", fn)


# —————————————————— 9. Provider 解析 ——————————————————

def test_anthropic_parse(monkeypatch):
    payload = {"content": [{"type": "text", "text": "真实产物X"}],
               "usage": {"input_tokens": 5, "output_tokens": 7}}
    _patch_urlopen(monkeypatch, lambda req, timeout=None: _FakeResp(payload))
    res = AnthropicProvider().complete("sys", "usr", _cfg("anthropic"))
    assert res.text == "真实产物X"
    assert res.provider == "anthropic"
    assert res.usage == {"input_tokens": 5, "output_tokens": 7}


def test_openai_parse(monkeypatch):
    payload = {"choices": [{"message": {"role": "assistant", "content": "OpenAI产物Y"}}]}
    _patch_urlopen(monkeypatch, lambda req, timeout=None: _FakeResp(payload))
    res = OpenAICompatProvider().complete("sys", "usr", _cfg("openai"))
    assert res.text == "OpenAI产物Y"
    assert res.provider == "openai"


# —————————————————— 10. 响应异形 → parse LLMError ——————————————————

@pytest.mark.parametrize("payload", [
    {"content": []},                                   # 空 content
    {"content": [{"type": "image"}]},                  # 首块非 text
    {"usage": {}},                                     # 缺 content 键
    {"content": [{"text": 123}]},                      # text 非字符串
])
def test_malformed_anthropic_raises_parse_llmerror(monkeypatch, payload):
    _patch_urlopen(monkeypatch, lambda req, timeout=None: _FakeResp(payload))
    with pytest.raises(LLMError) as ei:
        AnthropicProvider().complete("s", "u", _cfg("anthropic"))
    assert ei.value.kind == "parse"


@pytest.mark.parametrize("payload", [
    {"choices": []},                                   # 空 choices
    {"choices": [{"message": {}}]},                    # 缺 content
    {"choices": [{}]},                                 # 缺 message
])
def test_malformed_openai_raises_parse_llmerror(monkeypatch, payload):
    _patch_urlopen(monkeypatch, lambda req, timeout=None: _FakeResp(payload))
    with pytest.raises(LLMError) as ei:
        OpenAICompatProvider().complete("s", "u", _cfg("openai"))
    assert ei.value.kind == "parse"


# —————————————————— 11. 超时 → timeout LLMError ——————————————————

def test_timeout_raises_llmerror(monkeypatch):
    def _raise(req, timeout=None):
        raise socket.timeout("timed out")
    _patch_urlopen(monkeypatch, _raise)
    with pytest.raises(LLMError) as ei:
        _post_json("https://api.anthropic.com/v1/messages", {}, {"a": 1}, 30)
    assert ei.value.kind == "timeout"


def test_network_error_raises_llmerror(monkeypatch):
    def _raise(req, timeout=None):
        raise urllib.error.URLError("connection refused")
    _patch_urlopen(monkeypatch, _raise)
    with pytest.raises(LLMError) as ei:
        _post_json("https://api.anthropic.com/v1/messages", {}, {"a": 1}, 30)
    assert ei.value.kind == "network"


# —————————————————— 12. 重试后成功 ——————————————————

def test_retry_then_success(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("AGENT_LLM_API_KEY", "sk-test")
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)  # 免真实退避耗时
    calls = {"n": 0}
    ok_payload = {"content": [{"type": "text", "text": "第三次成功"}]}

    def _flaky(req, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise socket.timeout("timed out")
        return _FakeResp(ok_payload)

    _patch_urlopen(monkeypatch, _flaky)
    res = llm.complete("sys", "usr")
    assert res.text == "第三次成功"
    assert calls["n"] == 3  # 前 2 次超时 + 第 3 次成功（max_retries=2）


# —————————————————— 13. 4xx 不重试 ——————————————————

def test_4xx_no_retry(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("AGENT_LLM_API_KEY", "sk-test")
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def _unauth(req, timeout=None):
        calls["n"] += 1
        raise urllib.error.HTTPError("http://x", 401, "Unauthorized", {}, None)

    _patch_urlopen(monkeypatch, _unauth)
    with pytest.raises(LLMError) as ei:
        llm.complete("sys", "usr")
    assert ei.value.kind == "http_4xx"
    assert calls["n"] == 1  # 立即失败，绝不重试


def test_5xx_retries_then_raises(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("AGENT_LLM_API_KEY", "sk-test")
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def _fail(req, timeout=None):
        calls["n"] += 1
        raise urllib.error.HTTPError("http://x", 503, "Unavailable", {}, None)

    _patch_urlopen(monkeypatch, _fail)
    with pytest.raises(LLMError) as ei:
        llm.complete("sys", "usr")
    assert ei.value.kind == "http_5xx"
    assert calls["n"] == 3  # 初次 + max_retries(2) 次重试


# —————————————————— 14. is_enabled 真值表 ——————————————————

@pytest.mark.parametrize("env,expected", [
    ({}, False),                                                       # 全空 → none
    ({"AGENT_LLM_PROVIDER": "anthropic"}, False),                     # 有 provider 无 key
    ({"AGENT_LLM_PROVIDER": "anthropic", "AGENT_LLM_API_KEY": "k"}, True),
    ({"AGENT_LLM_PROVIDER": "openai", "AGENT_LLM_API_KEY": "k"}, True),
    ({"AGENT_LLM_PROVIDER": "none", "AGENT_LLM_API_KEY": "k"}, False),  # none 恒禁用
    ({"AGENT_LLM_PROVIDER": "bogus", "AGENT_LLM_API_KEY": "k"}, False),  # 未知 provider → none
    ({"AGENT_LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "k"}, True),  # 回落官方 key
])
def test_is_enabled_matrix(monkeypatch, env, expected):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert llm.is_enabled() is expected


def test_describe_hides_secrets(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("AGENT_LLM_API_KEY", "sk-super-secret")
    d = llm.describe()
    assert d == {"enabled": True, "provider": "anthropic", "model": "claude-opus-4-8"}
    assert "sk-super-secret" not in json.dumps(d)  # 密钥绝不外泄


# —————————————————— 15. 禁用时从不触网 ——————————————————

def test_disabled_never_calls_network(monkeypatch):
    def _boom(req, timeout=None):
        raise AssertionError("network must not be touched when LLM is disabled")
    _patch_urlopen(monkeypatch, _boom)
    assert llm.is_enabled() is False
    # 禁用下 complete 也在触网前即抛 config，不会调用 urlopen。
    with pytest.raises(LLMError) as ei:
        llm.complete("sys", "usr")
    assert ei.value.kind == "config"
