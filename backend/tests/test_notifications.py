"""P3-T2 通知中心（Phase-3 §2.3 / §6.1）。

指派通知人类 assignee；评论通知参与者、排除作者、不给自己 / Agent 发；未读数；
单条 / 全部已读且幂等；他人通知不可读。
"""


def test_assign_notifies_human_assignee(client, auth, make_requirement, data):
    req = make_requirement()
    client.patch(f"/api/requirements/{req['id']}/assign",
                 json={"assignee_type": "user", "assignee_id": data["member_id"]},
                 headers=auth("pm"))
    notes = client.get("/api/notifications", headers=auth("member")).get_json()
    assert any(n["type"] == "assigned" and n["entity_id"] == req["id"] for n in notes)


def test_assign_to_agent_makes_no_human_notification(client, auth, make_requirement, data):
    # 指派给 Agent → Agent 不作收件人；除 actor 外无人被通知 assigned。
    req = make_requirement()
    client.patch(f"/api/requirements/{req['id']}/assign",
                 json={"assignee_type": "agent", "assignee_id": data["dev_agent_id"]},
                 headers=auth("pm"))
    for role in ("member", "member2"):
        notes = client.get("/api/notifications?unread=1", headers=auth(role)).get_json()
        assert not any(n["type"] == "assigned" for n in notes)


def test_comment_notifies_participants_excluding_author(client, auth, make_requirement, data):
    # reporter=pm；指派给 member。member2 评论 → pm + member 收到，member2（作者）不收。
    req = make_requirement(assignee=("user", data["member_id"]))
    client.post(f"/api/requirements/{req['id']}/comments",
                json={"body": "hi team"}, headers=auth("member2"))
    pm_n = client.get("/api/notifications?unread=1", headers=auth("pm")).get_json()
    mem_n = client.get("/api/notifications?unread=1", headers=auth("member")).get_json()
    m2_n = client.get("/api/notifications?unread=1", headers=auth("member2")).get_json()
    assert any(n["type"] == "commented" for n in pm_n)
    assert any(n["type"] == "commented" for n in mem_n)
    assert not any(n["type"] == "commented" for n in m2_n)  # 作者本人不收


def test_no_self_notification_on_own_comment(client, auth, make_requirement, data):
    # pm 是 reporter，pm 自己评论 → pm 不收（收件人==施动者跳过）。
    req = make_requirement()
    client.post(f"/api/requirements/{req['id']}/comments",
                json={"body": "自己评论"}, headers=auth("pm"))
    pm_n = client.get("/api/notifications?unread=1", headers=auth("pm")).get_json()
    assert not any(n["type"] == "commented" for n in pm_n)


def test_agent_advance_notifies_reporter(client, auth, make_requirement, data):
    req = make_requirement(assignee=("agent", data["dev_agent_id"]))  # reporter=pm
    client.post(f"/api/requirements/{req['id']}/agent-advance", json={}, headers=auth("pm"))
    pm_n = client.get("/api/notifications?unread=1", headers=auth("pm")).get_json()
    assert any(n["type"] == "agent_advanced" and n["entity_id"] == req["id"] for n in pm_n)


def test_mention_notifies_user(client, auth, make_requirement, data):
    req = make_requirement()
    client.post(f"/api/requirements/{req['id']}/comments",
                json={"body": "cc @member 请看"}, headers=auth("pm"))
    mem_n = client.get("/api/notifications?unread=1", headers=auth("member")).get_json()
    assert any(n["type"] == "mentioned" for n in mem_n)


def test_unread_count_and_read_flow(client, auth, make_requirement, data):
    req = make_requirement()
    # 给 member 造两条：指派 + 评论。
    client.patch(f"/api/requirements/{req['id']}/assign",
                 json={"assignee_type": "user", "assignee_id": data["member_id"]},
                 headers=auth("pm"))
    client.post(f"/api/requirements/{req['id']}/comments",
                json={"body": "note"}, headers=auth("pm"))

    def count():
        return client.get("/api/notifications/unread-count",
                          headers=auth("member")).get_json()["count"]

    assert count() == 2
    nlist = client.get("/api/notifications", headers=auth("member")).get_json()
    nid = nlist[0]["id"]
    r = client.post(f"/api/notifications/{nid}/read", headers=auth("member"))
    assert r.status_code == 200
    assert r.get_json()["notification"]["is_read"] is True
    # 幂等再读无副作用。
    r2 = client.post(f"/api/notifications/{nid}/read", headers=auth("member"))
    assert r2.status_code == 200
    assert count() == 1
    # 全部已读。
    ra = client.post("/api/notifications/read-all", headers=auth("member"))
    assert ra.status_code == 200
    assert ra.get_json()["updated"] == 1
    assert count() == 0


def test_cannot_read_others_notification(client, auth, make_requirement, data):
    req = make_requirement()
    client.patch(f"/api/requirements/{req['id']}/assign",
                 json={"assignee_type": "user", "assignee_id": data["member_id"]},
                 headers=auth("pm"))
    nlist = client.get("/api/notifications", headers=auth("member")).get_json()
    nid = nlist[0]["id"]
    r = client.post(f"/api/notifications/{nid}/read", headers=auth("member2"))
    assert r.status_code == 403


def test_read_missing_notification_404(client, auth):
    r = client.post("/api/notifications/99999/read", headers=auth("pm"))
    assert r.status_code == 404


def test_unread_filter(client, auth, make_requirement, data):
    req = make_requirement()
    client.patch(f"/api/requirements/{req['id']}/assign",
                 json={"assignee_type": "user", "assignee_id": data["member_id"]},
                 headers=auth("pm"))
    all_n = client.get("/api/notifications", headers=auth("member")).get_json()
    assert len(all_n) >= 1
    # X-Total-Count 反映过滤后总数。
    r = client.get("/api/notifications?unread=1", headers=auth("member"))
    assert r.headers.get("X-Total-Count") == str(len(r.get_json()))
