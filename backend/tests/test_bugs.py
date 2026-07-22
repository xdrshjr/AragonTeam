"""P-T4 BUG（Phase-2 §6.1）。CRUD、合法/非法 move、分页头。"""


def test_create_bug_defaults_open(client, auth):
    r = client.post("/api/bugs", json={"title": "崩了", "severity": "critical"},
                    headers=auth("pm"))
    assert r.status_code == 201
    body = r.get_json()
    assert body["status"] == "open"
    assert body["severity"] == "critical"


def test_create_bug_rejects_bad_severity(client, auth):
    # 【§2.2.3 归一回归】非法 severity 仍 400；错误体归一为统一 {error, detail:{field,expected}}
    # 契约（message 由 "invalid severity" 归一为 "severity is invalid"，仍 400、语义不变）。
    r = client.post("/api/bugs", json={"title": "x", "severity": "sev0"}, headers=auth("pm"))
    assert r.status_code == 400
    assert r.get_json()["error"]
    assert r.get_json()["detail"]["field"] == "severity"


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


def test_move_non_string_status_returns_400_not_500(client, auth, make_bug, data):
    """【§2.3-B1】非串 status 此前触 unhashable 500——现 400。"""
    bug = make_bug(assignee=("user", data["member_id"]))
    r = client.patch(f"/api/bugs/{bug['id']}/move", json={"status": ["fixing"]},
                     headers=auth("pm"))
    assert r.status_code == 400
    assert r.status_code != 500


def test_list_default_order_by_recent_update(client, auth):
    """【§2.3】BUG 扁平列表按 updated_at 降序（最近更新在前），而非旧的列内 position 序。"""
    a = client.post("/api/bugs", json={"title": "A"}, headers=auth("pm")).get_json()
    b = client.post("/api/bugs", json={"title": "B"}, headers=auth("pm")).get_json()
    c = client.post("/api/bugs", json={"title": "C"}, headers=auth("pm")).get_json()
    # 更新最早创建的 A → 其 updated_at 前移到最新。
    client.patch(f"/api/bugs/{a['id']}", json={"title": "A2"}, headers=auth("pm"))
    items = client.get("/api/bugs", headers=auth("pm")).get_json()
    ids = [x["id"] for x in items]
    assert ids[0] == a["id"]                    # 最近更新在最前
    assert ids == [a["id"], c["id"], b["id"]]   # updated_at desc, id desc


# ————————————————————— version-plan-hierarchy §8.1：BUG 归属计划 —————————————————————

def _plan_for(client, auth, project_id):
    ver = client.post("/api/versions", json={"name": "v1", "project_id": project_id},
                      headers=auth("pm")).get_json()
    plan = client.post("/api/plans", json={"name": "迭代 1", "version_id": ver["id"]},
                       headers=auth("pm")).get_json()
    return ver, plan


def test_create_bug_with_plan_enriches_context(client, auth, data):
    _ver, plan = _plan_for(client, auth, data["project_id"])
    r = client.post("/api/bugs",
                    json={"title": "带计划的缺陷", "project_id": data["project_id"],
                          "plan_id": plan["id"]}, headers=auth("pm"))
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert body["plan_id"] == plan["id"]
    assert body["plan"]["name"] == "迭代 1"
    assert body["plan"]["version_name"] == "v1"


def test_create_bug_nonexistent_plan_400(client, auth, data):
    r = client.post("/api/bugs",
                    json={"title": "x", "project_id": data["project_id"], "plan_id": 999999},
                    headers=auth("pm"))
    assert r.status_code == 400
    assert r.get_json()["detail"]["field"] == "plan_id"


def test_patch_bug_sets_and_clears_plan(client, auth, data):
    _ver, plan = _plan_for(client, auth, data["project_id"])
    bug = client.post("/api/bugs", json={"title": "改归属", "project_id": data["project_id"]},
                      headers=auth("pm")).get_json()

    set_r = client.patch(f"/api/bugs/{bug['id']}", json={"plan_id": plan["id"]}, headers=auth("pm"))
    assert set_r.status_code == 200
    assert set_r.get_json()["plan_id"] == plan["id"]

    clear_r = client.patch(f"/api/bugs/{bug['id']}", json={"plan_id": None}, headers=auth("pm"))
    assert clear_r.status_code == 200
    assert clear_r.get_json()["plan_id"] is None


def test_list_bugs_filter_by_version_and_none(client, auth, data):
    pid = data["project_id"]
    ver, plan = _plan_for(client, auth, pid)
    a = client.post("/api/bugs", json={"title": "归属", "project_id": pid, "plan_id": plan["id"]},
                    headers=auth("pm")).get_json()
    b = client.post("/api/bugs", json={"title": "未归属", "project_id": pid},
                    headers=auth("pm")).get_json()

    by_version = [r["id"] for r in client.get(
        f"/api/bugs?version_id={ver['id']}", headers=auth("pm")).get_json()]
    assert a["id"] in by_version and b["id"] not in by_version

    unassigned = [r["id"] for r in client.get(
        "/api/bugs?version_id=none", headers=auth("pm")).get_json()]
    assert b["id"] in unassigned and a["id"] not in unassigned
