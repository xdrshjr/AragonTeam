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
