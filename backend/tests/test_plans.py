"""计划路由回归（version-plan-hierarchy §8.1）。

覆盖：CRUD；建计划自动写 project_id=version.project_id；PATCH version_id 跨项目 → 400；
?version_id= 过滤；删非空计划 → 409；计数富化 {requirement_count, bug_count, done_count}
正确（done 用 workflow.terminal_statuses 判定）。
"""
from extensions import db
from models.bug import Bug
from models.requirement import Requirement


def _create_version(client, auth, project_id, **over):
    body = {"name": "v2.0", "project_id": project_id}
    body.update(over)
    return client.post("/api/versions", json=body, headers=auth("pm"))


def _create_plan(client, auth, version_id, role="pm", **over):
    body = {"name": "迭代 1", "version_id": version_id}
    body.update(over)
    return client.post("/api/plans", json=body, headers=auth(role))


# ————————————————————— 创建 —————————————————————

def test_create_plan_derives_project_id_from_version(client, auth, data):
    ver = _create_version(client, auth, data["project_id"]).get_json()
    r = _create_plan(client, auth, ver["id"])
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert body["version_id"] == ver["id"]
    # 反范式：project_id 由版本推导写入（§3.3），客户端未传。
    assert body["project_id"] == data["project_id"]
    assert body["status"] == "planning"
    assert body["requirement_count"] == 0 and body["bug_count"] == 0 and body["done_count"] == 0


def test_create_plan_requires_existing_version(client, auth):
    r = client.post("/api/plans", json={"name": "x", "version_id": 999999}, headers=auth("pm"))
    assert r.status_code == 400
    assert r.get_json()["error"] == "version not found"


def test_create_plan_with_dates(client, auth, data):
    ver = _create_version(client, auth, data["project_id"]).get_json()
    r = _create_plan(client, auth, ver["id"], start_date="2026-07-01", end_date="2026-07-31")
    assert r.status_code == 201, r.get_json()
    assert r.get_json()["start_date"] == "2026-07-01"
    assert r.get_json()["end_date"] == "2026-07-31"


def test_create_plan_requires_pm_or_admin(client, auth, data):
    ver = _create_version(client, auth, data["project_id"]).get_json()
    r = _create_plan(client, auth, ver["id"], role="member")
    assert r.status_code == 403


# ————————————————————— 列表 / 过滤 —————————————————————

def test_list_filters_by_version(client, auth, data):
    pid = data["project_id"]
    v1 = _create_version(client, auth, pid, name="v1").get_json()
    v2 = _create_version(client, auth, pid, name="v2").get_json()
    p1 = _create_plan(client, auth, v1["id"], name="p1").get_json()
    _create_plan(client, auth, v2["id"], name="p2").get_json()

    ids = [p["id"] for p in
           client.get(f"/api/plans?version_id={v1['id']}", headers=auth("pm")).get_json()]
    assert ids == [p1["id"]]


def test_list_hides_archived_by_default(client, auth, data):
    ver = _create_version(client, auth, data["project_id"]).get_json()
    active = _create_plan(client, auth, ver["id"], name="a", status="active").get_json()
    archived = _create_plan(client, auth, ver["id"], name="b", status="archived").get_json()

    default_ids = [p["id"] for p in
                   client.get(f"/api/plans?version_id={ver['id']}", headers=auth("pm")).get_json()]
    assert active["id"] in default_ids and archived["id"] not in default_ids


# ————————————————————— PATCH —————————————————————

def test_patch_plan_change_version_same_project_ok(client, auth, data):
    pid = data["project_id"]
    v1 = _create_version(client, auth, pid, name="v1").get_json()
    v2 = _create_version(client, auth, pid, name="v2").get_json()
    plan = _create_plan(client, auth, v1["id"]).get_json()

    r = client.patch(f"/api/plans/{plan['id']}", json={"version_id": v2["id"]}, headers=auth("pm"))
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["version_id"] == v2["id"]
    assert r.get_json()["project_id"] == pid           # 同项目 → project_id 不变


def test_patch_plan_change_version_cross_project_400(client, auth, data):
    """§3.3 不变量 B：改挂版本必须同项目。"""
    pid = data["project_id"]
    v1 = _create_version(client, auth, pid).get_json()
    plan = _create_plan(client, auth, v1["id"]).get_json()
    other = client.post("/api/projects", json={"name": "另一个", "key": "OTH"},
                        headers=auth("pm")).get_json()
    v_other = _create_version(client, auth, other["id"], name="v-other").get_json()

    r = client.patch(f"/api/plans/{plan['id']}", json={"version_id": v_other["id"]},
                     headers=auth("pm"))
    assert r.status_code == 400
    assert r.get_json()["detail"]["field"] == "version_id"


def test_patch_without_updatable_field_is_400(client, auth, data):
    ver = _create_version(client, auth, data["project_id"]).get_json()
    plan = _create_plan(client, auth, ver["id"]).get_json()
    assert client.patch(f"/api/plans/{plan['id']}", json={}, headers=auth("pm")).status_code == 400


# ————————————————————— DELETE —————————————————————

def test_delete_plan_with_tickets_conflicts(client, auth, data):
    pid = data["project_id"]
    ver = _create_version(client, auth, pid).get_json()
    plan = _create_plan(client, auth, ver["id"]).get_json()
    client.post("/api/requirements",
                json={"title": "占着计划", "project_id": pid, "plan_id": plan["id"]},
                headers=auth("pm"))

    r = client.delete(f"/api/plans/{plan['id']}", headers=auth("pm"))
    assert r.status_code == 409, r.get_json()
    assert r.get_json()["error"] == "plan still has tickets"
    assert r.get_json()["detail"]["requirements"] == 1
    assert r.get_json()["detail"]["bugs"] == 0
    assert "allowed" not in r.get_json()


def test_delete_empty_plan_succeeds(client, auth, data):
    ver = _create_version(client, auth, data["project_id"]).get_json()
    plan = _create_plan(client, auth, ver["id"]).get_json()
    assert client.delete(f"/api/plans/{plan['id']}", headers=auth("pm")).status_code == 204


# ————————————————————— 计数富化 —————————————————————

def test_plan_counts_enrichment(client, auth, app, data):
    pid = data["project_id"]
    ver = _create_version(client, auth, pid).get_json()
    plan = _create_plan(client, auth, ver["id"]).get_json()

    r1 = client.post("/api/requirements",
                     json={"title": "a", "project_id": pid, "plan_id": plan["id"]},
                     headers=auth("pm")).get_json()
    client.post("/api/requirements",
                json={"title": "b", "project_id": pid, "plan_id": plan["id"]}, headers=auth("pm"))
    client.post("/api/bugs",
                json={"title": "c", "project_id": pid, "plan_id": plan["id"]}, headers=auth("pm"))

    with app.app_context():
        db.session.get(Requirement, r1["id"]).status = "done"
        db.session.commit()

    got = client.get(f"/api/plans/{plan['id']}", headers=auth("pm")).get_json()
    assert got["requirement_count"] == 2
    assert got["bug_count"] == 1
    assert got["done_count"] == 1        # 只有 r1 进终态（done）
