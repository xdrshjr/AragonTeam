"""P3-T1 Agent 自主协作闭环（Phase-3 §2.2 · 核心）。

claim-next 认领最久未指派单 + new→assigned + actor=agent 审计 + reporter 通知；
autorun 推进名下全部可推进单、跳过无动作、置回 idle；busy 软锁 409；tick；autorun-all；
**断言每次推进目标 ∈ can_transition 允许集（绝不绕过状态机）**。
"""
from extensions import db
from models.agent import Agent
from services import workflow


def test_claim_next_assigns_oldest_new(client, auth, make_requirement, data):
    r1 = make_requirement(title="老需求")  # 先建，created_at 最早
    make_requirement(title="新需求")
    res = client.post(f"/api/agents/{data['dev_agent_id']}/claim-next",
                      json={}, headers=auth("pm"))
    assert res.status_code == 200
    claimed = res.get_json()["claimed"]
    assert claimed is not None
    assert claimed["id"] == r1["id"]  # 最久未指派者
    assert claimed["assignee_type"] == "agent"
    assert claimed["assignee_id"] == data["dev_agent_id"]
    assert claimed["status"] == "assigned"  # new→assigned（经 can_transition）

    # actor=agent 的 assigned 审计。
    acts = client.get(f"/api/requirements/{r1['id']}/activities", headers=auth("pm")).get_json()
    assigned = [a for a in acts if a["action"] == "assigned"]
    assert assigned and assigned[0]["actor_type"] == "agent"
    assert assigned[0]["actor_id"] == data["dev_agent_id"]

    # reporter(pm) 收到 assigned 通知。
    notes = client.get("/api/notifications?unread=1", headers=auth("pm")).get_json()
    assert any(n["type"] == "assigned" and n["entity_id"] == r1["id"] for n in notes)


def test_claim_next_no_candidate_returns_null(client, auth, data):
    res = client.post(f"/api/agents/{data['dev_agent_id']}/claim-next",
                      json={}, headers=auth("pm"))
    assert res.status_code == 200
    assert res.get_json()["claimed"] is None


def test_qa_agent_claims_nothing(client, auth, make_requirement, data):
    make_requirement()  # 未指派 new
    res = client.post(f"/api/agents/{data['qa_agent_id']}/claim-next",
                      json={}, headers=auth("pm"))
    assert res.get_json()["claimed"] is None  # qa 不主动认领「新」单


def test_claim_next_entity_filter(client, auth, make_requirement, make_bug, data):
    make_requirement(title="需求单")
    make_bug(title="缺陷单")
    res = client.post(f"/api/agents/{data['dev_agent_id']}/claim-next",
                      json={"entity": "bug"}, headers=auth("pm"))
    claimed = res.get_json()["claimed"]
    assert claimed is not None
    # 只认领 bug；requirement 仍未指派。
    assert "severity" in claimed


def test_autorun_advances_and_returns_idle(client, auth, make_requirement, data):
    make_requirement(assignee=("agent", data["dev_agent_id"]))  # → assigned
    res = client.post(f"/api/agents/{data['dev_agent_id']}/autorun", json={}, headers=auth("pm"))
    assert res.status_code == 200
    body = res.get_json()
    assert body["agent"]["status"] == "idle"  # finally 归 idle
    advanced = body["advanced"]
    assert len(advanced) == 1
    assert advanced[0]["from"] == "assigned"
    assert advanced[0]["to"] == "in_development"


def test_autorun_run_all_until_no_action(client, auth, make_requirement, data):
    req = make_requirement(assignee=("agent", data["dev_agent_id"]))
    res = client.post(f"/api/agents/{data['dev_agent_id']}/autorun?run=all",
                      json={}, headers=auth("pm"))
    body = res.get_json()
    tos = [a["to"] for a in body["advanced"]]
    assert tos == ["in_development", "testing"]  # dev 推到 testing 后需 qa，停
    assert body["agent"]["status"] == "idle"
    # 最终工单落 testing。
    after = client.get(f"/api/requirements/{req['id']}", headers=auth("pm")).get_json()
    assert after["status"] == "testing"


def test_autorun_skips_no_action_ticket(client, auth, make_requirement, data):
    # qa-agent 名下 assigned 需求 → 无预置动作 → skipped no-action。
    make_requirement(assignee=("agent", data["qa_agent_id"]))
    res = client.post(f"/api/agents/{data['qa_agent_id']}/autorun", json={}, headers=auth("pm"))
    body = res.get_json()
    assert body["advanced"] == []
    assert any(s["reason"] == "no-action" for s in body["skipped"])


def test_autorun_busy_soft_lock_409(client, auth, app, data):
    with app.app_context():
        a = db.session.get(Agent, data["dev_agent_id"])
        a.status = "busy"
        db.session.commit()
    res = client.post(f"/api/agents/{data['dev_agent_id']}/autorun", json={}, headers=auth("pm"))
    assert res.status_code == 409
    assert res.get_json()["error"] == "agent is busy"


def test_tick_claims_then_advances(client, auth, make_requirement, data):
    make_requirement()  # 未指派 new
    res = client.post(f"/api/agents/{data['dev_agent_id']}/tick",
                      json={"claim": True, "claim_count": 1}, headers=auth("pm"))
    assert res.status_code == 200
    body = res.get_json()
    assert len(body["claimed"]) == 1
    assert any(a["to"] == "in_development" for a in body["advanced"])
    assert body["agent"]["status"] == "idle"


def test_autorun_all_aggregates(client, auth, make_requirement, data):
    make_requirement(assignee=("agent", data["dev_agent_id"]))  # dev 名下 assigned
    make_requirement()  # 未指派 new，供 dev 认领
    res = client.post("/api/agents/autorun-all", json={"claim": True}, headers=auth("pm"))
    assert res.status_code == 200
    runs = res.get_json()["runs"]
    assert len(runs) == 2  # dev + qa
    dev_run = next(r for r in runs if r["agent"]["id"] == data["dev_agent_id"])
    assert dev_run["claimed"] or dev_run["advanced"]


def test_autorun_never_bypasses_workflow(client, auth, make_requirement, data):
    make_requirement(assignee=("agent", data["dev_agent_id"]))
    res = client.post(f"/api/agents/{data['dev_agent_id']}/autorun?run=all",
                      json={}, headers=auth("pm"))
    for a in res.get_json()["advanced"]:
        assert workflow.can_transition(a["entity"], a["from"], a["to"]), a
