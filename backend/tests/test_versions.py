"""版本路由回归（version-plan-hierarchy §8.1）。

覆盖：CRUD；project_id 存在性 400；PATCH 拒改 project_id；?status= / ?include_archived=
过滤；删非空版本 → 409（detail 带 plans 计数、无 allowed）；分页 X-Total-Count；富化
plan_count / total_count / done_count 正确；released_at 服务端托管（进出 released 由后端
stamp / 清空，客户端传值不生效）。
"""
from extensions import db
from models.bug import Bug
from models.requirement import Requirement


def _create_version(client, auth, project_id, role="pm", **over):
    body = {"name": "v2.0", "project_id": project_id}
    body.update(over)
    return client.post("/api/versions", json=body, headers=auth(role))


def _create_plan(client, auth, version_id, **over):
    body = {"name": "迭代 1", "version_id": version_id}
    body.update(over)
    return client.post("/api/plans", json=body, headers=auth("pm"))


# ————————————————————— 创建 —————————————————————

def test_create_version_success(client, auth, data):
    r = _create_version(client, auth, data["project_id"], description="首个版本")
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert body["name"] == "v2.0"
    assert body["project_id"] == data["project_id"]
    assert body["status"] == "planning"          # 默认态
    assert body["released_at"] is None
    assert body["plan_count"] == 0
    assert body["total_count"] == 0 and body["done_count"] == 0


def test_create_version_with_target_date(client, auth, data):
    r = _create_version(client, auth, data["project_id"], target_date="2026-09-30")
    assert r.status_code == 201, r.get_json()
    assert r.get_json()["target_date"] == "2026-09-30"


def test_create_version_invalid_target_date_400(client, auth, data):
    r = _create_version(client, auth, data["project_id"], target_date="2026-13-99")
    assert r.status_code == 400
    assert r.get_json()["detail"]["field"] == "target_date"


def test_create_version_requires_existing_project(client, auth):
    r = _create_version(client, auth, 999999)
    assert r.status_code == 400
    assert r.get_json()["error"] == "project not found"


def test_create_version_requires_name(client, auth, data):
    r = client.post("/api/versions", json={"project_id": data["project_id"]}, headers=auth("pm"))
    assert r.status_code == 400


def test_create_version_requires_pm_or_admin(client, auth, data):
    r = _create_version(client, auth, data["project_id"], role="member")
    assert r.status_code == 403


# ————————————————————— 列表 / 过滤 —————————————————————

def test_list_hides_archived_by_default_and_filters_status(client, auth, data):
    pid = data["project_id"]
    active = _create_version(client, auth, pid, name="A", status="active").get_json()
    archived = _create_version(client, auth, pid, name="B", status="archived").get_json()

    default_ids = [v["id"] for v in
                   client.get(f"/api/versions?project_id={pid}", headers=auth("pm")).get_json()]
    assert active["id"] in default_ids
    assert archived["id"] not in default_ids       # 归档默认隐藏

    with_flag = [v["id"] for v in client.get(
        f"/api/versions?project_id={pid}&include_archived=1", headers=auth("pm")).get_json()]
    assert archived["id"] in with_flag

    only_active = [v["id"] for v in client.get(
        f"/api/versions?project_id={pid}&status=active", headers=auth("pm")).get_json()]
    assert active["id"] in only_active and archived["id"] not in only_active


def test_list_exposes_total_count(client, auth, data):
    pid = data["project_id"]
    for i in range(3):
        _create_version(client, auth, pid, name=f"v{i}")
    r = client.get(f"/api/versions?project_id={pid}", headers=auth("pm"))
    assert r.status_code == 200
    assert r.headers.get("X-Total-Count") == "3"


def test_list_invalid_status_is_400(client, auth, data):
    r = client.get(f"/api/versions?project_id={data['project_id']}&status=bogus",
                   headers=auth("pm"))
    assert r.status_code == 400


# ————————————————————— 取单个 / 404 —————————————————————

def test_get_missing_version_is_404(client, auth):
    assert client.get("/api/versions/999999", headers=auth("pm")).status_code == 404


# ————————————————————— PATCH —————————————————————

def test_patch_version_updates_fields(client, auth, data):
    ver = _create_version(client, auth, data["project_id"]).get_json()
    r = client.patch(f"/api/versions/{ver['id']}",
                     json={"name": "v2.1", "description": "改过"}, headers=auth("pm"))
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["name"] == "v2.1"


def test_patch_without_updatable_field_is_400(client, auth, data):
    ver = _create_version(client, auth, data["project_id"]).get_json()
    r = client.patch(f"/api/versions/{ver['id']}", json={}, headers=auth("pm"))
    assert r.status_code == 400
    assert r.get_json()["error"] == "no updatable field"


def test_patch_rejects_project_id_change(client, auth, data):
    """§3.3 不变量 A：版本 project_id 创建后不可变（请求体带了也忽略）。"""
    ver = _create_version(client, auth, data["project_id"]).get_json()
    other = client.post("/api/projects", json={"name": "另一个", "key": "OTH"},
                        headers=auth("pm")).get_json()

    # 只传 project_id → 不计入 changed → no updatable field 400。
    only = client.patch(f"/api/versions/{ver['id']}", json={"project_id": other["id"]},
                        headers=auth("pm"))
    assert only.status_code == 400

    # project_id + name → name 改，project_id 不变。
    combo = client.patch(f"/api/versions/{ver['id']}",
                         json={"project_id": other["id"], "name": "renamed"}, headers=auth("pm"))
    assert combo.status_code == 200
    assert combo.get_json()["name"] == "renamed"
    assert combo.get_json()["project_id"] == data["project_id"]


def test_released_at_is_server_managed(client, auth, data):
    """§4.1 / §6.1 评审 P1-C：released_at 随 status 进出 released 由后端 stamp / 清空。"""
    ver = _create_version(client, auth, data["project_id"]).get_json()
    assert ver["released_at"] is None

    entered = client.patch(f"/api/versions/{ver['id']}", json={"status": "released"},
                           headers=auth("pm"))
    assert entered.status_code == 200
    assert entered.get_json()["released_at"] is not None   # 进入 released → stamped

    # 客户端传 released_at 不是可改字段 → 无改动 → 400（服务端托管，不接受客户端写时间戳）。
    client_write = client.patch(f"/api/versions/{ver['id']}",
                                json={"released_at": "2020-01-01T00:00:00Z"}, headers=auth("pm"))
    assert client_write.status_code == 400

    left = client.patch(f"/api/versions/{ver['id']}", json={"status": "active"},
                        headers=auth("pm"))
    assert left.status_code == 200
    assert left.get_json()["released_at"] is None          # 转出 released → 清空


def test_create_released_version_stamps_released_at(client, auth, data):
    r = _create_version(client, auth, data["project_id"], status="released")
    assert r.status_code == 201
    assert r.get_json()["released_at"] is not None


def test_patch_requires_pm_or_admin(client, auth, data):
    ver = _create_version(client, auth, data["project_id"]).get_json()
    r = client.patch(f"/api/versions/{ver['id']}", json={"name": "x"}, headers=auth("member"))
    assert r.status_code == 403


# ————————————————————— DELETE —————————————————————

def test_delete_version_with_plans_conflicts(client, auth, data):
    ver = _create_version(client, auth, data["project_id"]).get_json()
    _create_plan(client, auth, ver["id"])

    r = client.delete(f"/api/versions/{ver['id']}", headers=auth("pm"))

    assert r.status_code == 409, r.get_json()
    assert r.get_json()["error"] == "version still has plans"
    assert r.get_json()["detail"]["plans"] == 1
    assert "allowed" not in r.get_json()          # 不带 allowed（看板拖拽错误分流不误伤）


def test_delete_empty_version_succeeds(client, auth, data):
    ver = _create_version(client, auth, data["project_id"]).get_json()
    assert client.delete(f"/api/versions/{ver['id']}", headers=auth("pm")).status_code == 204
    assert client.get(f"/api/versions/{ver['id']}", headers=auth("pm")).status_code == 404


def test_delete_missing_version_is_404(client, auth):
    assert client.delete("/api/versions/999999", headers=auth("pm")).status_code == 404


# ————————————————————— 富化聚合进度（评审 P1-B）—————————————————————

def test_version_aggregated_progress(client, auth, app, data):
    """建版本 → 两计划 → 各挂工单并推一张进终态 → 断言版本聚合 done/total 服务端算对。"""
    pid = data["project_id"]
    ver = _create_version(client, auth, pid).get_json()
    p1 = _create_plan(client, auth, ver["id"], name="迭代 1").get_json()
    p2 = _create_plan(client, auth, ver["id"], name="迭代 2").get_json()

    r1 = client.post("/api/requirements",
                     json={"title": "a", "project_id": pid, "plan_id": p1["id"]},
                     headers=auth("pm")).get_json()
    client.post("/api/requirements",
                json={"title": "b", "project_id": pid, "plan_id": p1["id"]}, headers=auth("pm"))
    b1 = client.post("/api/bugs",
                     json={"title": "c", "project_id": pid, "plan_id": p2["id"]},
                     headers=auth("pm")).get_json()

    with app.app_context():
        db.session.get(Requirement, r1["id"]).status = "done"
        db.session.get(Bug, b1["id"]).status = "closed"
        db.session.commit()

    got = client.get(f"/api/versions/{ver['id']}", headers=auth("pm")).get_json()
    assert got["plan_count"] == 2
    assert got["total_count"] == 3       # r1 + r2 + b1（跨两计划的工单两跳聚合）
    assert got["done_count"] == 2        # r1 done + b1 closed
