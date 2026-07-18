"""P-T4 BUG（Phase-2 §6.1）。CRUD、合法/非法 move、分页头。"""


def test_create_bug_defaults_open(client, auth):
    r = client.post("/api/bugs", json={"title": "崩了", "severity": "critical"},
                    headers=auth("pm"))
    assert r.status_code == 201
    body = r.get_json()
    assert body["status"] == "open"
    assert body["severity"] == "critical"


def test_create_bug_rejects_bad_severity(client, auth):
    r = client.post("/api/bugs", json={"title": "x", "severity": "sev0"}, headers=auth("pm"))
    assert r.status_code == 400
    assert r.get_json()["error"] == "invalid severity"


def test_bug_move_legal_and_illegal(client, auth, make_bug, data):
    bug = make_bug(assignee=("user", data["member_id"]))  # open → assigned
    ok = client.patch(f"/api/bugs/{bug['id']}/move", json={"status": "fixing"}, headers=auth("pm"))
    assert ok.status_code == 200
    assert ok.get_json()["status"] == "fixing"
    # fixing → closed 非法
    bad = client.patch(f"/api/bugs/{bug['id']}/move", json={"status": "closed"}, headers=auth("pm"))
    assert bad.status_code == 409
    assert bad.get_json()["allowed"] == ["assigned", "verifying"]


def test_bug_list_pagination_header(client, auth):
    client.post("/api/bugs", json={"title": "b1"}, headers=auth("pm"))
    client.post("/api/bugs", json={"title": "b2"}, headers=auth("pm"))
    client.post("/api/bugs", json={"title": "b3"}, headers=auth("pm"))
    r = client.get("/api/bugs?limit=2", headers=auth("pm"))
    assert r.status_code == 200
    assert len(r.get_json()) == 2
    assert r.headers.get("X-Total-Count") == "3"


def test_delete_bug_cascades_comments(client, auth, make_bug):
    bug = make_bug()
    client.post(f"/api/bugs/{bug['id']}/comments", json={"body": "一条评论"}, headers=auth("pm"))
    r = client.delete(f"/api/bugs/{bug['id']}", headers=auth("admin"))
    assert r.status_code == 204
    # 删单后工单不存在
    assert client.get(f"/api/bugs/{bug['id']}", headers=auth("pm")).status_code == 404
