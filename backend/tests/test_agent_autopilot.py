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
    # 【§2.6-E1】入口门禁在 busy 之外加 offline，错误文案统一为 "agent is busy or offline"。
    assert res.get_json()["error"] == "agent is busy or offline"


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


def test_patch_agent_cannot_set_busy(client, auth, data):
    """【§2.3-B3】busy 是 autopilot 运行期软锁；手动置 busy 会让 /autorun /tick 恒 409
    且无自动恢复，Agent 永久卡死。故 PATCH status=busy → 400；idle/offline → 200。"""
    bad = client.patch(f"/api/agents/{data['dev_agent_id']}", json={"status": "busy"},
                       headers=auth("pm"))
    assert bad.status_code == 400
    ok = client.patch(f"/api/agents/{data['dev_agent_id']}", json={"status": "idle"},
                      headers=auth("pm"))
    assert ok.status_code == 200
    assert ok.get_json()["status"] == "idle"


# ————————————————————— §2.2：dev→qa 交接闭合自主闭环（核心 P1）—————————————————————

def test_autorun_all_closes_loop_requirement_reaches_reviewing(
        client, auth, make_requirement, data):
    """一次 autorun-all?run=all：dev 推到 testing→交接 qa→reviewing（reviewing→done 属人工审批）。"""
    req = make_requirement(assignee=("agent", data["dev_agent_id"]))
    res = client.post("/api/agents/autorun-all?run=all", json={"claim": True}, headers=auth("pm"))
    assert res.status_code == 200
    after = client.get(f"/api/requirements/{req['id']}", headers=auth("pm")).get_json()
    assert after["status"] == "reviewing"
    # 已交接给 qa-agent（多态 assignee 易主，状态由 advance_one 合法推进）。
    assert after["assignee_type"] == "agent"
    assert after["assignee_id"] == data["qa_agent_id"]


def test_autorun_all_closes_loop_bug_reaches_closed(client, auth, make_bug, data):
    """BUG 场景：dev 推到 verifying→交接 qa→closed（终态）。"""
    bug = make_bug(assignee=("agent", data["dev_agent_id"]))
    res = client.post("/api/agents/autorun-all?run=all", json={"claim": True}, headers=auth("pm"))
    assert res.status_code == 200
    after = client.get(f"/api/bugs/{bug['id']}", headers=auth("pm")).get_json()
    assert after["status"] == "closed"
    assert after["assignee_id"] == data["qa_agent_id"]


def test_handoff_notifies_reporter_with_assigned(client, auth, make_requirement, data):
    """【评审 R1】交接经 notify_claim 通知 reporter（人类）；notify_assignment 对 agent 静默不发。"""
    req = make_requirement(assignee=("agent", data["dev_agent_id"]))
    client.post("/api/agents/autorun-all?run=all", json={"claim": True}, headers=auth("pm"))
    notes = client.get("/api/notifications", headers=auth("pm")).get_json()
    assert any(n["type"] == "assigned" and n["entity_type"] == "requirement"
               and n["entity_id"] == req["id"] for n in notes)


def test_autorun_all_no_qa_stops_gracefully_at_testing(
        client, auth, make_requirement, data):
    """无可用 qa-agent（离线）时交接 no-op，需求停在 testing（行为与旧版一致）。"""
    client.patch(f"/api/agents/{data['qa_agent_id']}", json={"status": "offline"},
                 headers=auth("pm"))
    req = make_requirement(assignee=("agent", data["dev_agent_id"]))
    client.post("/api/agents/autorun-all?run=all", json={"claim": True}, headers=auth("pm"))
    after = client.get(f"/api/requirements/{req['id']}", headers=auth("pm")).get_json()
    assert after["status"] == "testing"
    assert after["assignee_id"] == data["dev_agent_id"]  # 未交接（无可用 qa）


def test_autorun_all_rescues_stale_testing_ticket(
        client, auth, make_requirement, app, data):
    """【评审 R2】存量已停在 testing 且指派给 dev 的单（模拟 seed 演示单）经
    `except NoAgentAction` 分支交接给 qa，最终到达 reviewing（否则永久卡死）。"""
    req = make_requirement(assignee=("agent", data["dev_agent_id"]))
    with app.app_context():
        from models.requirement import Requirement
        r = db.session.get(Requirement, req["id"])
        r.status = "testing"  # 绕过推进直接置存量态，复现「NoAgentAction 于交接之前」
        db.session.commit()
    res = client.post("/api/agents/autorun-all?run=all", json={"claim": True}, headers=auth("pm"))
    assert res.status_code == 200
    after = client.get(f"/api/requirements/{req['id']}", headers=auth("pm")).get_json()
    assert after["status"] == "reviewing"
    assert after["assignee_id"] == data["qa_agent_id"]


# ————————————————————— §2.6：Agent offline 语义收口 —————————————————————

def test_offline_agent_autorun_rejected_and_status_preserved(client, auth, data):
    """offline agent 被 /autorun 拒（409），且事后仍 offline（未被清成 idle）。"""
    client.patch(f"/api/agents/{data['dev_agent_id']}", json={"status": "offline"},
                 headers=auth("pm"))
    res = client.post(f"/api/agents/{data['dev_agent_id']}/autorun", json={}, headers=auth("pm"))
    assert res.status_code == 409
    assert "offline" in res.get_json()["error"]
    got = client.get(f"/api/agents/{data['dev_agent_id']}", headers=auth("pm")).get_json()
    assert got["status"] == "offline"  # 未被 _run_with_lock 清成 idle


def test_autorun_all_skips_offline_agent(client, auth, data):
    """autorun-all 中 offline agent 计入 skipped(reason="offline")，状态不被改写。"""
    client.patch(f"/api/agents/{data['dev_agent_id']}", json={"status": "offline"},
                 headers=auth("pm"))
    res = client.post("/api/agents/autorun-all", json={"claim": True}, headers=auth("pm"))
    runs = res.get_json()["runs"]
    dev_run = next(r for r in runs if r["agent"]["id"] == data["dev_agent_id"])
    assert any(s.get("reason") == "offline" for s in dev_run["skipped"])
    assert dev_run["agent"]["status"] == "offline"
