"""P3-T5 列表过滤 / 检索 + 「我的工作」（Phase-3 §2.6 / §6.1）。

q / status / priority / severity / assignee_* / reporter_id 过滤命中正确、
X-Total-Count 随过滤变化；GET /me/work 返回当前用户 assigned / reported 聚合。
"""


def test_filter_by_status_changes_total_count(client, auth):
    client.post("/api/requirements", json={"title": "A"}, headers=auth("pm"))
    client.post("/api/requirements", json={"title": "B"}, headers=auth("pm"))
    r = client.get("/api/requirements?status=new", headers=auth("pm"))
    assert r.headers["X-Total-Count"] == "2"
    r2 = client.get("/api/requirements?status=assigned", headers=auth("pm"))
    assert r2.headers["X-Total-Count"] == "0"


def test_keyword_search(client, auth):
    client.post("/api/requirements", json={"title": "登录页面优化"}, headers=auth("pm"))
    client.post("/api/requirements", json={"title": "看板拖拽排序"}, headers=auth("pm"))
    r = client.get("/api/requirements", query_string={"q": "登录"}, headers=auth("pm"))
    items = r.get_json()
    assert len(items) == 1
    assert items[0]["title"] == "登录页面优化"
    assert r.headers["X-Total-Count"] == "1"


def test_keyword_search_matches_description(client, auth):
    client.post("/api/requirements",
                json={"title": "无关标题", "description": "涉及 OAuth 令牌刷新"}, headers=auth("pm"))
    client.post("/api/requirements", json={"title": "别的"}, headers=auth("pm"))
    r = client.get("/api/requirements", query_string={"q": "OAuth"}, headers=auth("pm"))
    assert r.headers["X-Total-Count"] == "1"


def test_filter_by_priority(client, auth):
    client.post("/api/requirements", json={"title": "P1", "priority": "urgent"}, headers=auth("pm"))
    client.post("/api/requirements", json={"title": "P2", "priority": "low"}, headers=auth("pm"))
    r = client.get("/api/requirements?priority=urgent", headers=auth("pm"))
    assert r.headers["X-Total-Count"] == "1"


def test_bug_filter_by_severity(client, auth):
    client.post("/api/bugs", json={"title": "b1", "severity": "critical"}, headers=auth("pm"))
    client.post("/api/bugs", json={"title": "b2", "severity": "minor"}, headers=auth("pm"))
    r = client.get("/api/bugs?severity=critical", headers=auth("pm"))
    assert r.headers["X-Total-Count"] == "1"


def test_filter_by_assignee_and_reporter(client, auth, make_requirement, data):
    req = make_requirement(assignee=("user", data["member_id"]))
    r = client.get(
        f"/api/requirements?assignee_type=user&assignee_id={data['member_id']}",
        headers=auth("pm"))
    assert r.headers["X-Total-Count"] == "1"
    assert r.get_json()[0]["id"] == req["id"]
    r2 = client.get(f"/api/requirements?reporter_id={data['pm_id']}", headers=auth("pm"))
    assert int(r2.headers["X-Total-Count"]) >= 1


def test_me_work_aggregates(client, auth, make_requirement, make_bug, data):
    req = make_requirement(assignee=("user", data["member_id"]))
    bug = make_bug(assignee=("user", data["member_id"]))
    res = client.get("/api/me/work", headers=auth("member"))
    assert res.status_code == 200
    body = res.get_json()
    assert req["id"] in [r["id"] for r in body["assigned"]["requirements"]]
    assert bug["id"] in [b["id"] for b in body["assigned"]["bugs"]]
    # member 未提交任何单（建单需 pm），reported 两侧为空。
    assert body["reported"]["requirements"] == []
    assert body["reported"]["bugs"] == []


def test_me_work_reported_side(client, auth, make_requirement, data):
    # pm 视角：pm 是所有 seed 单的 reporter。
    make_requirement()
    res = client.get("/api/me/work", headers=auth("pm"))
    body = res.get_json()
    assert len(body["reported"]["requirements"]) >= 1


def test_list_filter_escapes_like_metachars(client, auth):
    """【§2.4-C1】列表 q= 转义 LIKE 元字符：q=% 只匹配字面量含 % 的单，不过度匹配全部。"""
    client.post("/api/requirements", json={"title": "a%b"}, headers=auth("pm"))
    client.post("/api/requirements", json={"title": "axb"}, headers=auth("pm"))
    r = client.get("/api/requirements", query_string={"q": "%"}, headers=auth("pm"))
    # 转义生效则仅 1 条（"a%b"）；若未转义，% 作通配会命中全部 2 条。
    assert r.headers["X-Total-Count"] == "1"
    assert r.get_json()[0]["title"] == "a%b"


def test_list_filter_escapes_underscore(client, auth):
    """q=_ 作字面量：只匹配含下划线的单，不匹配任意单字符。"""
    client.post("/api/requirements", json={"title": "a_b"}, headers=auth("pm"))
    client.post("/api/requirements", json={"title": "aXb"}, headers=auth("pm"))
    r = client.get("/api/requirements", query_string={"q": "_"}, headers=auth("pm"))
    assert r.headers["X-Total-Count"] == "1"
