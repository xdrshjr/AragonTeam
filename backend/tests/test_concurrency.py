"""P3-T4 乐观并发守卫（Phase-3 §2.5 / §6.1）。

陈旧 expected_updated_at → 409（detail.current_updated_at 存在、无 allowed）；
正确 / 缺省 → 200；与状态机 409（有 allowed、无 current_updated_at）可区分。
"""

_STALE = "2000-01-01T00:00:00.000000Z"


def test_stale_expected_updated_at_conflict_on_patch(client, auth, make_requirement, data):
    req = make_requirement(assignee=("user", data["member_id"]))
    r = client.patch(f"/api/requirements/{req['id']}",
                     json={"title": "新标题", "expected_updated_at": _STALE},
                     headers=auth("pm"))
    assert r.status_code == 409
    body = r.get_json()
    assert body["error"].startswith("conflict")
    assert "current_updated_at" in body["detail"]
    assert "allowed" not in body  # 并发 409 无 allowed


def test_correct_expected_updated_at_ok(client, auth, make_requirement, data):
    req = make_requirement(assignee=("user", data["member_id"]))
    cur = client.get(f"/api/requirements/{req['id']}", headers=auth("pm")).get_json()["updated_at"]
    r = client.patch(f"/api/requirements/{req['id']}",
                     json={"title": "改", "expected_updated_at": cur}, headers=auth("pm"))
    assert r.status_code == 200
    assert r.get_json()["title"] == "改"


def test_absent_expected_updated_at_ok(client, auth, make_requirement, data):
    req = make_requirement(assignee=("user", data["member_id"]))
    r = client.patch(f"/api/requirements/{req['id']}",
                     json={"title": "无守卫"}, headers=auth("pm"))
    assert r.status_code == 200


def test_stale_conflict_on_move(client, auth, make_requirement, data):
    req = make_requirement(assignee=("user", data["member_id"]))  # assigned
    r = client.patch(f"/api/requirements/{req['id']}/move",
                     json={"status": "in_development", "expected_updated_at": _STALE},
                     headers=auth("pm"))
    assert r.status_code == 409
    body = r.get_json()
    assert "current_updated_at" in body["detail"]
    assert "allowed" not in body


def test_same_column_move_also_guarded(client, auth, make_requirement, data):
    # 同列早退分支也须先过并发守卫〔放行条件4〕。
    req = make_requirement(assignee=("user", data["member_id"]))  # assigned
    r = client.patch(f"/api/requirements/{req['id']}/move",
                     json={"status": "assigned", "position": 0, "expected_updated_at": _STALE},
                     headers=auth("pm"))
    assert r.status_code == 409
    assert "current_updated_at" in r.get_json()["detail"]


def test_state_machine_conflict_distinct_from_concurrency(client, auth, make_requirement, data):
    req = make_requirement(assignee=("user", data["member_id"]))  # assigned
    # assigned → done 非法（无 expected_updated_at）→ 状态机 409：有 allowed、无 current_updated_at。
    r = client.patch(f"/api/requirements/{req['id']}/move",
                     json={"status": "done"}, headers=auth("pm"))
    assert r.status_code == 409
    body = r.get_json()
    assert "allowed" in body
    assert "current_updated_at" not in body.get("detail", {})


def test_bug_concurrency_guard(client, auth, make_bug, data):
    bug = make_bug(assignee=("user", data["member_id"]))  # assigned
    r = client.patch(f"/api/bugs/{bug['id']}/move",
                     json={"status": "fixing", "expected_updated_at": _STALE},
                     headers=auth("pm"))
    assert r.status_code == 409
    assert "current_updated_at" in r.get_json()["detail"]
