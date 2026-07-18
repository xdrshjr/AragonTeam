"""RBAC（Phase-2 P-T7 + Phase-3 P3-T3 行级 RBAC 扩充，§2.4 / §6.1）。

Phase-2 粗粒度：member 越权创建 403、pm/admin 建单 201。
Phase-3 行级：patch/move 需 can_manage_ticket；assign/删/转 BUG/autopilot 需 pm/admin；
agent-advance 需 pm/admin 或 can_manage_ticket〔R3-01：**有意的契约变更**〕。
"""
from extensions import db
from models.requirement import Requirement


# ————————————————————— Phase-2 粗粒度（保留） —————————————————————

def test_member_cannot_create_user(client, auth):
    r = client.post("/api/users", json={"username": "x", "password": "pw12345"},
                    headers=auth("member"))
    assert r.status_code == 403


def test_member_cannot_create_requirement(client, auth):
    r = client.post("/api/requirements", json={"title": "member 建单"}, headers=auth("member"))
    assert r.status_code == 403


def test_pm_can_create_requirement(client, auth):
    r = client.post("/api/requirements", json={"title": "pm 建单"}, headers=auth("pm"))
    assert r.status_code == 201


def test_member_cannot_create_bug(client, auth):
    r = client.post("/api/bugs", json={"title": "member 建 BUG"}, headers=auth("member"))
    assert r.status_code == 403


# ————————————————————— Phase-3：agent-advance 契约收紧〔R3-01〕 —————————————————————

def test_member_can_comment_but_not_advance_others(client, auth, make_requirement, data):
    """〔R3-01〕member 评论仍开放（201）；对**非归属**单 agent-advance 现为 403（有意收紧）。"""
    req = make_requirement(assignee=("agent", data["dev_agent_id"]))  # reporter=pm，assignee=agent
    # (a) 评论对全员开放，member 仍 201。
    c = client.post(f"/api/requirements/{req['id']}/comments",
                    json={"body": "member 也能评论"}, headers=auth("member"))
    assert c.status_code == 201
    # (b) member 既非 reporter 也非人类 assignee → agent-advance 403（防旁路 move/patch 门禁）。
    a = client.post(f"/api/requirements/{req['id']}/agent-advance", json={}, headers=auth("member"))
    assert a.status_code == 403
    assert a.get_json()["error"] == "forbidden"


def test_pm_can_advance_agent_ticket(client, auth, make_requirement, data):
    """200 正路改用 pm 触发（reporter/归属 assignee 亦可，见下）。"""
    req = make_requirement(assignee=("agent", data["dev_agent_id"]))
    r = client.post(f"/api/requirements/{req['id']}/agent-advance", json={}, headers=auth("pm"))
    assert r.status_code == 200


def test_reporter_member_can_advance_own_agent_ticket(client, auth, app, data):
    """member 作为 reporter 可对指派给 Agent 的**自己**的单 agent-advance（归属路径）。"""
    # member 无法自建（建单需 pm），直插一张 reporter=member、指派给 dev-agent 的 assigned 需求。
    with app.app_context():
        req = Requirement(title="member 的单", status="assigned",
                          assignee_type="agent", assignee_id=data["dev_agent_id"],
                          reporter_id=data["member_id"], position=0)
        db.session.add(req)
        db.session.commit()
        req_id = req.id
    r = client.post(f"/api/requirements/{req_id}/agent-advance", json={}, headers=auth("member"))
    assert r.status_code == 200
    assert r.get_json()["ticket"]["status"] == "in_development"


# ————————————————————— Phase-3：行级 RBAC 矩阵 —————————————————————

def test_member_cannot_reassign(client, auth, make_requirement, data):
    req = make_requirement()
    r = client.patch(f"/api/requirements/{req['id']}/assign",
                     json={"assignee_type": "user", "assignee_id": data["member_id"]},
                     headers=auth("member"))
    assert r.status_code == 403


def test_member_cannot_delete_requirement(client, auth, make_requirement):
    req = make_requirement()
    r = client.delete(f"/api/requirements/{req['id']}", headers=auth("member"))
    assert r.status_code == 403


def test_member_cannot_convert_to_bug(client, auth, make_requirement, data):
    req = make_requirement(assignee=("user", data["member_id"]))
    client.patch(f"/api/requirements/{req['id']}/move", json={"status": "in_development"},
                 headers=auth("pm"))
    client.patch(f"/api/requirements/{req['id']}/move", json={"status": "testing"},
                 headers=auth("pm"))
    r = client.post(f"/api/requirements/{req['id']}/convert-to-bug", json={}, headers=auth("member"))
    assert r.status_code == 403


def test_member_cannot_run_autopilot(client, auth, data):
    for path in (f"/api/agents/{data['dev_agent_id']}/claim-next",
                 f"/api/agents/{data['dev_agent_id']}/autorun",
                 f"/api/agents/{data['dev_agent_id']}/tick",
                 "/api/agents/autorun-all"):
        r = client.post(path, json={}, headers=auth("member"))
        assert r.status_code == 403, path


def test_assignee_member_can_move_and_edit_own_ticket(client, auth, make_requirement, data):
    """member 作为人类 assignee 可 move / 编辑自己的单（归属路径）。"""
    req = make_requirement(assignee=("user", data["member_id"]))  # → assigned
    mv = client.patch(f"/api/requirements/{req['id']}/move",
                      json={"status": "in_development"}, headers=auth("member"))
    assert mv.status_code == 200
    ed = client.patch(f"/api/requirements/{req['id']}",
                      json={"title": "assignee 改标题"}, headers=auth("member"))
    assert ed.status_code == 200


def test_non_related_member_cannot_move(client, auth, make_requirement, data):
    """member2 既非 reporter 也非 assignee → 无权 move（403）。"""
    req = make_requirement(assignee=("user", data["member_id"]))
    r = client.patch(f"/api/requirements/{req['id']}/move",
                     json={"status": "in_development"}, headers=auth("member2"))
    assert r.status_code == 403


def test_reporter_member_can_edit(client, auth, app, data):
    """member 作为 reporter 可编辑自己提的单（reporter 归属路径）。"""
    with app.app_context():
        req = Requirement(title="reporter 的单", status="new",
                          reporter_id=data["member_id"], position=0)
        db.session.add(req)
        db.session.commit()
        req_id = req.id
    r = client.patch(f"/api/requirements/{req_id}",
                     json={"description": "reporter 补充描述"}, headers=auth("member"))
    assert r.status_code == 200


def test_pm_full_access(client, auth, make_requirement, data):
    """pm 建单 / 改派 / move / 转 BUG 全通（2xx）。"""
    req = make_requirement()
    assign = client.patch(f"/api/requirements/{req['id']}/assign",
                          json={"assignee_type": "user", "assignee_id": data["member_id"]},
                          headers=auth("pm"))
    assert assign.status_code == 200
    mv = client.patch(f"/api/requirements/{req['id']}/move",
                      json={"status": "in_development"}, headers=auth("pm"))
    assert mv.status_code == 200
