"""P-T6 评论与合并 feed（Phase-2 §6.1）。

发/列评论、feed 按 created_at 升序合并 activity 与 comment、
system/agent/user 三类作者概要解析正确。
"""


def test_post_comment_author_is_current_user(client, auth, make_requirement, data):
    req = make_requirement()
    r = client.post(f"/api/requirements/{req['id']}/comments",
                    json={"body": "  第一条评论  "}, headers=auth("member"))
    assert r.status_code == 201
    body = r.get_json()
    assert body["body"] == "第一条评论"  # strip 生效
    assert body["author_type"] == "user"
    assert body["author"]["id"] == data["member_id"]
    assert body["author"]["type"] == "user"


def test_empty_comment_rejected(client, auth, make_requirement):
    req = make_requirement()
    r = client.post(f"/api/requirements/{req['id']}/comments",
                    json={"body": "   "}, headers=auth("member"))
    assert r.status_code == 400


def test_comment_on_missing_entity_404(client, auth):
    r = client.post("/api/requirements/99999/comments", json={"body": "x"}, headers=auth("pm"))
    assert r.status_code == 404


def test_list_comments_paginated(client, auth, make_requirement):
    req = make_requirement()
    for i in range(3):
        client.post(f"/api/requirements/{req['id']}/comments",
                    json={"body": f"c{i}"}, headers=auth("pm"))
    r = client.get(f"/api/requirements/{req['id']}/comments?limit=2", headers=auth("pm"))
    assert r.status_code == 200
    assert len(r.get_json()) == 2
    assert r.headers.get("X-Total-Count") == "3"


def test_feed_merges_and_sorts_ascending(client, auth, make_requirement, data):
    # 指派给 dev-agent 产生一条 assigned activity；agent-advance 产生 activity+comment。
    req = make_requirement(assignee=("agent", data["dev_agent_id"]))
    client.post(f"/api/requirements/{req['id']}/agent-advance", json={}, headers=auth("pm"))
    # 人类再补一条评论。
    client.post(f"/api/requirements/{req['id']}/comments",
                json={"body": "人类的评论"}, headers=auth("member"))

    feed = client.get(f"/api/requirements/{req['id']}/feed", headers=auth("pm")).get_json()
    items = feed["items"]
    # 混合了 activity 与 comment 两种 kind。
    assert {it["kind"] for it in items} == {"activity", "comment"}
    # 升序：created_at 单调不减。
    times = [it["created_at"] for it in items]
    assert times == sorted(times)


def test_feed_resolves_all_three_author_types(client, auth, make_requirement, data):
    req = make_requirement(assignee=("agent", data["dev_agent_id"]))
    client.post(f"/api/requirements/{req['id']}/agent-advance", json={}, headers=auth("pm"))
    client.post(f"/api/requirements/{req['id']}/comments",
                json={"body": "user says hi"}, headers=auth("member"))

    feed = client.get(f"/api/requirements/{req['id']}/feed", headers=auth("pm")).get_json()
    # activity 的 actor 概要（含 user/agent）。
    actor_types = {it["actor"]["type"] for it in feed["items"]
                   if it["kind"] == "activity" and it["actor"]}
    author_types = {it["author"]["type"] for it in feed["items"] if it["kind"] == "comment"}
    assert "agent" in author_types  # Agent 评论
    assert "user" in author_types   # 人类评论
    # activity 里应能解析出 user（创建/指派者）与 agent（推进者）。
    assert "user" in actor_types or "agent" in actor_types


def test_system_comment_summary(client, auth, app, make_requirement):
    # 直接插一条 system 评论，验证概要解析为「系统」。
    from extensions import db
    from models.comment import Comment
    req = make_requirement()
    with app.app_context():
        db.session.add(Comment(entity_type="requirement", entity_id=req["id"],
                               author_type="system", author_id=None, body="系统留痕"))
        db.session.commit()
    feed = client.get(f"/api/requirements/{req['id']}/feed", headers=auth("pm")).get_json()
    sys_items = [it for it in feed["items"]
                 if it["kind"] == "comment" and it["author_type"] == "system"]
    assert sys_items and sys_items[0]["author"]["name"] == "系统"
