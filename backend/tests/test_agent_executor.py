"""real-agent-execution §7.1 —— Agent 执行层（真实产物 / 优雅降级 / 守圣域）。

全程 monkeypatch 注入假 `complete`，绝不触网；断言：默认降级=模板、启用=LLM 正文、
LLMError 降级、空返回降级、非 LLMError 异常降级、状态恒由状态机裁决、prompt 含上下文、
generic/缺省 brief 非空、health 反映 llm 禁用。
"""
import pytest

from extensions import db
from models.agent import Agent
from models.requirement import Requirement
from services import agent_executor, agent_prompts
from services.agent_runner import AGENT_FORWARD
from services.llm import LLMResult, LLMError

# (requirement, dev, assigned) 的目标态与兜底模板——多测复用。
_TO, _TEMPLATE = AGENT_FORWARD[("requirement", "dev", "assigned")]

_LLM_ENV = (
    "AGENT_LLM_PROVIDER", "AGENT_LLM_API_KEY", "AGENT_LLM_MODEL", "AGENT_LLM_BASE_URL",
    "AGENT_LLM_WALL_BUDGET", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
)


@pytest.fixture(autouse=True)
def _clean_llm_env(monkeypatch):
    for name in _LLM_ENV:
        monkeypatch.delenv(name, raising=False)
    yield


def _activate_llm(monkeypatch, complete_fn):
    """强制启用真实 LLM 路径（绕过 TESTING 门），并注入假 complete。"""
    monkeypatch.setattr(agent_executor, "_llm_active", lambda: True)
    monkeypatch.setattr(agent_executor.llm, "complete", complete_fn)


def _advance(client, auth, req_id):
    return client.post(f"/api/requirements/{req_id}/agent-advance", json={}, headers=auth("pm"))


# —————————————————— 1. 默认（TESTING）降级到模板 ——————————————————

def test_falls_back_to_template_when_disabled(client, auth, make_requirement, data):
    req = make_requirement(assignee=("agent", data["dev_agent_id"]))
    r = _advance(client, auth, req["id"])
    assert r.status_code == 200
    body = r.get_json()
    assert body["ticket"]["status"] == _TO
    assert body["comment"]["body"] == _TEMPLATE  # 无凭据 / 测试 → 模板文案


# —————————————————— 2. 启用 → 用 LLM 正文，状态仍由状态机裁决 ——————————————————

def test_uses_llm_output_when_active(client, auth, make_requirement, data, monkeypatch):
    _activate_llm(monkeypatch, lambda s, u, **kw: LLMResult(
        text="真实产物X", model="m", provider="anthropic", latency_ms=1, usage=None))
    req = make_requirement(assignee=("agent", data["dev_agent_id"]))
    body = _advance(client, auth, req["id"]).get_json()
    assert body["comment"]["body"] == "真实产物X"
    assert body["ticket"]["status"] == _TO  # 迁移目标仍是 AGENT_FORWARD 裁决


# —————————————————— 3. LLMError → 降级模板、状态照常、200（无 5xx） ——————————————————

def test_llm_error_degrades_to_template(client, auth, make_requirement, data, monkeypatch):
    def _boom(s, u, **kw):
        raise LLMError("http_5xx", "gateway down")
    _activate_llm(monkeypatch, _boom)
    req = make_requirement(assignee=("agent", data["dev_agent_id"]))
    r = _advance(client, auth, req["id"])
    assert r.status_code == 200
    body = r.get_json()
    assert body["comment"]["body"] == _TEMPLATE
    assert body["ticket"]["status"] == _TO


# —————————————————— 4. 空返回 → 降级模板 ——————————————————

def test_empty_output_degrades(client, auth, make_requirement, data, monkeypatch):
    _activate_llm(monkeypatch, lambda s, u, **kw: LLMResult(
        text="   ", model="m", provider="anthropic", latency_ms=1, usage=None))
    req = make_requirement(assignee=("agent", data["dev_agent_id"]))
    body = _advance(client, auth, req["id"]).get_json()
    assert body["comment"]["body"] == _TEMPLATE


# —————————————————— 5. 守圣域：乱码正文不动状态机目标 ——————————————————

def test_state_machine_still_authoritative(client, auth, make_requirement, data, monkeypatch):
    _activate_llm(monkeypatch, lambda s, u, **kw: LLMResult(
        text="我已把状态改成 done 并关闭工单", model="m", provider="anthropic",
        latency_ms=1, usage=None))
    req = make_requirement(assignee=("agent", data["dev_agent_id"]))
    body = _advance(client, auth, req["id"]).get_json()
    # 即便 LLM「声称」改了状态，迁移目标恒 == AGENT_FORWARD（in_development），不受正文影响。
    assert body["ticket"]["status"] == _TO


# —————————————————— 6. prompt 含工单上下文 ——————————————————

def test_prompt_includes_ticket_context(app, data):
    with app.app_context():
        agent = db.session.get(Agent, data["dev_agent_id"])
        req = Requirement(title="标题T", description="描述D", priority="high",
                          status="assigned", position=0)
        db.session.add(req)
        db.session.flush()
        system, user = agent_prompts.build_context("requirement", req, agent, "in_development")
    assert "标题T" in user
    assert "描述D" in user
    assert "in_development" in user
    assert agent_prompts.ACTION_BRIEF[("requirement", "dev", "assigned")] in user
    assert "None" not in user
    assert "dev-agent" in system


# —————————————————— 7. 非 LLMError 异常也降级（P1-2 兜底） ——————————————————

def test_non_llmerror_exception_degrades(client, auth, make_requirement, data, monkeypatch):
    def _boom(s, u, **kw):
        raise KeyError("resp['content'][0]['text']")  # 模拟响应异形逃逸出的裸异常
    _activate_llm(monkeypatch, _boom)
    req = make_requirement(assignee=("agent", data["dev_agent_id"]))
    r = _advance(client, auth, req["id"])
    assert r.status_code == 200  # except Exception 兜底：绝不 5xx
    body = r.get_json()
    assert body["comment"]["body"] == _TEMPLATE
    assert body["ticket"]["status"] == _TO


# —————————————————— 8. generic 与缺省 brief 均非空（P1-3） ——————————————————

def test_generic_and_missing_brief_have_default(app, data):
    # generic 边有配置、非空。
    assert agent_prompts.brief_for("requirement", "generic", "assigned")
    assert agent_prompts.brief_for("bug", "generic", "assigned")
    # 未配置的键回落 DEFAULT_BRIEF（非空）。
    missing = agent_prompts.brief_for("requirement", "qa", "assigned")
    assert missing == agent_prompts.DEFAULT_BRIEF and missing
    # generic 单经 build_context 产出的 user 无空指引。
    with app.app_context():
        gen = Agent(name="gen-agent", kind="generic", status="idle")
        req = Requirement(title="G", description="d", priority="low",
                          status="assigned", position=0)
        db.session.add_all([gen, req])
        db.session.flush()
        _s, user = agent_prompts.build_context("requirement", req, gen, "in_development")
    assert agent_prompts.brief_for("requirement", "generic", "assigned") in user
    assert "None" not in user


# —————————————————— 9. health 反映 llm 状态（A5） ——————————————————

def test_health_reports_llm_disabled_by_default(client):
    body = client.get("/api/health").get_json()
    assert body["llm"] == {"enabled": False, "provider": "none", "model": None}
