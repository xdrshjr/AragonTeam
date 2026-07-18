"""P-T5 Agent 协作运行时（Phase-2 §6.1 · 核心）。

断言 agent-advance：推进 + Agent 评论 + actor=agent 的 activity、未指派→409、
无预置动作→409、**推进目标永远 ∈ workflow 允许集（绝不绕过状态机）**、终态 idle。
"""
from services import workflow
from services.agent_runner import AGENT_FORWARD


def test_advance_moves_ticket_and_leaves_traces(client, auth, make_requirement, data):
    req = make_requirement(assignee=("agent", data["dev_agent_id"]))  # → assigned
    assert req["status"] == "assigned"

    r = client.post(f"/api/requirements/{req['id']}/agent-advance", json={}, headers=auth("pm"))
    assert r.status_code == 200
    body = r.get_json()
    # 1) 工单被推进：assigned → in_development（dev 的前进边）。
    assert body["ticket"]["status"] == "in_development"
    # 2) 返回一条 Agent 作者的工作说明评论。
    assert body["comment"]["author_type"] == "agent"
    assert body["comment"]["author"]["type"] == "agent"
    assert body["comment"]["body"]
    # 3) 单步终态恒为 idle（【R-04】busy 不在单步内产生）。
    assert body["agent"]["status"] == "idle"

    # 4) 时间线新增一条 action=agent_advanced 且 actor_type=agent 的 activity。
    acts = client.get(f"/api/requirements/{req['id']}/activities", headers=auth("pm")).get_json()
    adv = [a for a in acts if a["action"] == "agent_advanced"]
    assert adv and adv[0]["actor_type"] == "agent"
    assert adv[0]["actor_id"] == data["dev_agent_id"]

    # 5) feed 里既有该 activity 又有该 comment。
    feed = client.get(f"/api/requirements/{req['id']}/feed", headers=auth("pm")).get_json()
    kinds = {(it["kind"], it.get("action")) for it in feed["items"]}
    assert ("activity", "agent_advanced") in kinds
    assert any(it["kind"] == "comment" and it["author"]["type"] == "agent" for it in feed["items"])


def test_advance_unassigned_agent_409(client, auth, make_requirement):
    req = make_requirement()  # 未指派
    r = client.post(f"/api/requirements/{req['id']}/agent-advance", json={}, headers=auth("pm"))
    assert r.status_code == 409
    assert r.get_json()["error"] == "ticket is not assigned to an agent"


def test_advance_no_action_for_state_409(client, auth, make_requirement, data):
    # qa-agent 处理 assigned 需求 → 表中无预置动作 → 409，不改库。
    req = make_requirement(assignee=("agent", data["qa_agent_id"]))
    r = client.post(f"/api/requirements/{req['id']}/agent-advance", json={}, headers=auth("pm"))
    assert r.status_code == 409
    assert r.get_json()["error"] == "agent has no action for this state"
    # 状态未变。
    after = client.get(f"/api/requirements/{req['id']}", headers=auth("pm")).get_json()
    assert after["status"] == "assigned"


def test_bug_advance(client, auth, make_bug, data):
    bug = make_bug(assignee=("agent", data["dev_agent_id"]))  # open → assigned
    r = client.post(f"/api/bugs/{bug['id']}/agent-advance", json={}, headers=auth("pm"))
    assert r.status_code == 200
    assert r.get_json()["ticket"]["status"] == "fixing"


def test_run_all_advances_until_no_action(client, auth, make_requirement, data):
    # dev-agent 连续推进 assigned → in_development → testing，随后无动作（需 qa 接手）即停。
    req = make_requirement(assignee=("agent", data["dev_agent_id"]))
    r = client.post(f"/api/requirements/{req['id']}/agent-advance?run=all", json={},
                    headers=auth("pm"))
    assert r.status_code == 200
    body = r.get_json()
    assert body["ticket"]["status"] == "testing"
    assert body["agent"]["status"] == "idle"  # finally 归 idle
    assert [s["to_status"] for s in body["steps"]] == ["in_development", "testing"]


def test_agent_forward_edges_are_all_legal():
    # 结构性断言：AGENT_FORWARD 的每条前进边都 ∈ workflow 邻接表允许集（绝不绕过状态机）。
    for (entity, _kind, frm), (to, _msg) in AGENT_FORWARD.items():
        assert workflow.can_transition(entity, frm, to), f"非法前进边: {entity} {frm}->{to}"
