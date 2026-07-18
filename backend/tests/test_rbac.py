"""P-T7 RBAC（Phase-2 §6.1）。member 越权 403、pm 建单 201、member 建单 403。"""


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


def test_member_can_comment_and_advance(client, auth, make_requirement, data):
    # 协作动作（评论 / agent-advance）仅需登录（【R-08】行级权限本期不做）。
    req = make_requirement(assignee=("agent", data["dev_agent_id"]))
    c = client.post(f"/api/requirements/{req['id']}/comments",
                    json={"body": "member 也能评论"}, headers=auth("member"))
    assert c.status_code == 201
    a = client.post(f"/api/requirements/{req['id']}/agent-advance", json={}, headers=auth("member"))
    assert a.status_code == 200
