"""P-T3 需求（Phase-2 §6.1）。CRUD、assign、move、convert-to-bug、分页头。"""


def test_create_requirement_defaults_new(client, auth):
    r = client.post("/api/requirements", json={"title": "做点事", "priority": "high"},
                    headers=auth("pm"))
    assert r.status_code == 201
    body = r.get_json()
    assert body["status"] == "new"
    assert body["priority"] == "high"
    assert body["assignee"] is None


def test_create_requirement_rejects_unknown_project(client, auth):
    # §2.8-1：不存在的 project_id → 400。
    r = client.post("/api/requirements", json={"title": "x", "project_id": 99999},
                    headers=auth("pm"))
    assert r.status_code == 400
    assert r.get_json()["error"] == "project not found"


def test_assign_to_agent_auto_transitions(client, auth, data):
    req = client.post("/api/requirements", json={"title": "指派给 Agent"},
                      headers=auth("pm")).get_json()
    r = client.patch(f"/api/requirements/{req['id']}/assign",
                     json={"assignee_type": "agent", "assignee_id": data["dev_agent_id"]},
                     headers=auth("pm"))
    assert r.status_code == 200
    body = r.get_json()
    assert body["assignee_type"] == "agent"
    assert body["status"] == "assigned"  # new → assigned 自动迁移


def test_legal_move_writes_activity(client, auth, make_requirement, data):
    req = make_requirement(assignee=("user", data["member_id"]))  # → assigned
    # assigned → in_development 合法
    r = client.patch(f"/api/requirements/{req['id']}/move",
                     json={"status": "in_development"}, headers=auth("pm"))
    assert r.status_code == 200
    assert r.get_json()["status"] == "in_development"
    # 时间线应含 moved
    acts = client.get(f"/api/requirements/{req['id']}/activities", headers=auth("pm")).get_json()
    assert any(a["action"] == "moved" for a in acts)


def test_illegal_move_returns_409_with_allowed(client, auth):
    req = client.post("/api/requirements", json={"title": "非法迁移"},
                      headers=auth("pm")).get_json()
    # new → done 非法
    r = client.patch(f"/api/requirements/{req['id']}/move",
                     json={"status": "done"}, headers=auth("pm"))
    assert r.status_code == 409
    body = r.get_json()
    assert body["error"] == "illegal transition"
    assert body["allowed"] == ["assigned"]


def test_convert_to_bug_links_source(client, auth, make_requirement, data):
    req = make_requirement(assignee=("user", data["member_id"]))
    # 推到 testing 才能转 BUG
    client.patch(f"/api/requirements/{req['id']}/move", json={"status": "in_development"},
                 headers=auth("pm"))
    client.patch(f"/api/requirements/{req['id']}/move", json={"status": "testing"},
                 headers=auth("pm"))
    r = client.post(f"/api/requirements/{req['id']}/convert-to-bug", json={}, headers=auth("pm"))
    assert r.status_code == 201
    bug = r.get_json()
    assert bug["related_requirement_id"] == req["id"]
    # 源需求转入 bug_fixing
    src = client.get(f"/api/requirements/{req['id']}", headers=auth("pm")).get_json()
    assert src["status"] == "bug_fixing"


def test_list_returns_total_count_header(client, auth):
    client.post("/api/requirements", json={"title": "一"}, headers=auth("pm"))
    client.post("/api/requirements", json={"title": "二"}, headers=auth("pm"))
    r = client.get("/api/requirements", headers=auth("pm"))
    assert r.status_code == 200
    assert r.headers.get("X-Total-Count") == "2"
    assert isinstance(r.get_json(), list)  # 响应体仍是裸数组（Phase-1 契约不变）


def test_pagination_limits_rows(client, auth):
    for i in range(5):
        client.post("/api/requirements", json={"title": f"R{i}"}, headers=auth("pm"))
    r = client.get("/api/requirements?limit=2&offset=1", headers=auth("pm"))
    assert r.status_code == 200
    assert len(r.get_json()) == 2
    assert r.headers.get("X-Total-Count") == "5"  # 总数为未分页前的量


def test_patch_requirement_logs_updated(client, auth):
    req = client.post("/api/requirements", json={"title": "旧标题"}, headers=auth("pm")).get_json()
    r = client.patch(f"/api/requirements/{req['id']}", json={"title": "新标题"}, headers=auth("pm"))
    assert r.status_code == 200
    assert r.get_json()["title"] == "新标题"
    acts = client.get(f"/api/requirements/{req['id']}/activities", headers=auth("pm")).get_json()
    assert any(a["action"] == "updated" for a in acts)


def test_same_column_reorder_by_position(client, auth):
    # 三张 new 列的需求，把最后一张插到索引 0。
    ids = [client.post("/api/requirements", json={"title": f"N{i}"},
                       headers=auth("pm")).get_json()["id"] for i in range(3)]
    r = client.patch(f"/api/requirements/{ids[2]}/move",
                     json={"status": "new", "position": 0}, headers=auth("pm"))
    assert r.status_code == 200
    assert r.get_json()["position"] == 0
    # 该列按 position 排序，被移动的卡应排在最前。
    new_col = client.get("/api/requirements?status=new", headers=auth("pm")).get_json()
    assert new_col[0]["id"] == ids[2]


def test_list_default_order_by_recent_update(client, auth):
    """【§2.3】扁平列表按 updated_at 降序（最近更新在前），而非旧的列内 position 序。"""
    a = client.post("/api/requirements", json={"title": "A"}, headers=auth("pm")).get_json()
    b = client.post("/api/requirements", json={"title": "B"}, headers=auth("pm")).get_json()
    c = client.post("/api/requirements", json={"title": "C"}, headers=auth("pm")).get_json()
    # 更新最早创建的 A → 其 updated_at 前移到最新。
    client.patch(f"/api/requirements/{a['id']}", json={"title": "A2"}, headers=auth("pm"))
    items = client.get("/api/requirements", headers=auth("pm")).get_json()
    ids = [r["id"] for r in items]
    assert ids[0] == a["id"]                 # 最近更新在最前
    assert ids == [a["id"], c["id"], b["id"]]  # updated_at desc, id desc


def test_move_non_string_status_returns_400_not_500(client, auth, make_requirement, data):
    """【§2.3-B1】非串 status（list）此前 `status in _table`(dict) 触 unhashable 500——现 400。"""
    req = make_requirement(assignee=("user", data["member_id"]))
    r = client.patch(f"/api/requirements/{req['id']}/move",
                     json={"status": ["assigned"]}, headers=auth("pm"))
    assert r.status_code == 400
    assert r.status_code != 500


# ————————————————————— version-plan-hierarchy §8.1：需求归属计划 —————————————————————

def _plan_for(client, auth, project_id):
    """建一个版本 + 计划，返回 (version, plan) 两个 dict。"""
    ver = client.post("/api/versions", json={"name": "v1", "project_id": project_id},
                      headers=auth("pm")).get_json()
    plan = client.post("/api/plans", json={"name": "迭代 1", "version_id": ver["id"]},
                       headers=auth("pm")).get_json()
    return ver, plan


def test_create_requirement_with_plan_enriches_context(client, auth, data):
    _ver, plan = _plan_for(client, auth, data["project_id"])
    r = client.post("/api/requirements",
                    json={"title": "带计划", "project_id": data["project_id"], "plan_id": plan["id"]},
                    headers=auth("pm"))
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert body["plan_id"] == plan["id"]
    assert body["plan"]["name"] == "迭代 1"
    assert body["plan"]["version_name"] == "v1"


def test_create_requirement_without_project_adopts_plan_project(client, auth, data):
    """无 project 的工单带 plan_id → 采纳计划的项目（§3.2）。"""
    _ver, plan = _plan_for(client, auth, data["project_id"])
    r = client.post("/api/requirements", json={"title": "无项目", "plan_id": plan["id"]},
                    headers=auth("pm"))
    assert r.status_code == 201, r.get_json()
    assert r.get_json()["project_id"] == data["project_id"]


def test_create_requirement_nonexistent_plan_400(client, auth, data):
    r = client.post("/api/requirements",
                    json={"title": "x", "project_id": data["project_id"], "plan_id": 999999},
                    headers=auth("pm"))
    assert r.status_code == 400
    assert r.get_json()["detail"]["field"] == "plan_id"


def test_create_requirement_cross_project_plan_400(client, auth, data):
    _ver, plan = _plan_for(client, auth, data["project_id"])
    other = client.post("/api/projects", json={"name": "另一个", "key": "OTH"},
                        headers=auth("pm")).get_json()
    r = client.post("/api/requirements",
                    json={"title": "跨项目", "project_id": other["id"], "plan_id": plan["id"]},
                    headers=auth("pm"))
    assert r.status_code == 400
    assert "same project" in r.get_json()["error"]


def test_patch_requirement_sets_and_clears_plan(client, auth, data):
    _ver, plan = _plan_for(client, auth, data["project_id"])
    req = client.post("/api/requirements",
                      json={"title": "改归属", "project_id": data["project_id"]},
                      headers=auth("pm")).get_json()
    assert req["plan_id"] is None

    set_r = client.patch(f"/api/requirements/{req['id']}", json={"plan_id": plan["id"]},
                         headers=auth("pm"))
    assert set_r.status_code == 200
    assert set_r.get_json()["plan_id"] == plan["id"]

    clear_r = client.patch(f"/api/requirements/{req['id']}", json={"plan_id": None},
                          headers=auth("pm"))
    assert clear_r.status_code == 200
    assert clear_r.get_json()["plan_id"] is None
    assert clear_r.get_json()["plan"] is None


def test_list_filters_by_plan_and_version(client, auth, data):
    pid = data["project_id"]
    ver, plan = _plan_for(client, auth, pid)
    a = client.post("/api/requirements",
                    json={"title": "归属", "project_id": pid, "plan_id": plan["id"]},
                    headers=auth("pm")).get_json()
    b = client.post("/api/requirements", json={"title": "未归属", "project_id": pid},
                    headers=auth("pm")).get_json()

    by_plan = [r["id"] for r in client.get(
        f"/api/requirements?plan_id={plan['id']}", headers=auth("pm")).get_json()]
    assert a["id"] in by_plan and b["id"] not in by_plan

    by_version = [r["id"] for r in client.get(
        f"/api/requirements?version_id={ver['id']}", headers=auth("pm")).get_json()]
    assert a["id"] in by_version and b["id"] not in by_version

    unassigned = [r["id"] for r in client.get(
        "/api/requirements?plan_id=none", headers=auth("pm")).get_json()]
    assert b["id"] in unassigned and a["id"] not in unassigned


def test_convert_to_bug_inherits_plan(client, auth, data):
    pid = data["project_id"]
    _ver, plan = _plan_for(client, auth, pid)
    req = client.post("/api/requirements",
                      json={"title": "会转BUG", "project_id": pid, "plan_id": plan["id"]},
                      headers=auth("pm")).get_json()
    # 推到 testing 才能转 BUG：new→assigned→in_development→testing。
    headers = auth("pm")
    client.patch(f"/api/requirements/{req['id']}/assign",
                 json={"assignee_type": "user", "assignee_id": data["member_id"]}, headers=headers)
    for to in ("in_development", "testing"):
        client.patch(f"/api/requirements/{req['id']}/move", json={"status": to}, headers=headers)

    r = client.post(f"/api/requirements/{req['id']}/convert-to-bug", json={}, headers=headers)
    assert r.status_code == 201, r.get_json()
    assert r.get_json()["plan_id"] == plan["id"]     # 新 BUG 继承源需求 plan_id
