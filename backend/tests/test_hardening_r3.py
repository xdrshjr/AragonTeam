"""第 3 轮稳健化回归（scale-and-project-scope §2.6 / §2.7 / §2.9）。

主题：**剩余的真 500 清零**。超界整型有三条互相独立的路径，必须各自收口：
  A · URL 路径（<int:id> 转换器）→ 404
  B · 请求体（want_int）      → 400
  C · 查询串（want_query_int）→ 400   ← 评审 R1 补入，v1 遗漏
外加四处未校验的 description、关键字段 max_len、删单串档、claim-next 门禁、软锁泄漏。
"""
from services import scope, validation

# 20 位十进制，远超 2**63-1（9223372036854775807）。
HUGE = "99999999999999999999"
HUGE_INT = int(HUGE)


# ————————————————— ① A 路径：URL 超界 id → 404（不是 500）—————————————————

def test_oversized_path_ids_return_404(client, auth, data):
    headers = auth("admin")
    paths = [
        f"/api/requirements/{HUGE}",
        f"/api/bugs/{HUGE}",
        f"/api/users/{HUGE}",
        f"/api/agents/{HUGE}",
        f"/api/projects/{HUGE}",
    ]
    for p in paths:
        r = client.get(p, headers=headers)
        assert r.status_code == 404, (p, r.status_code)
    r = client.post(f"/api/notifications/{HUGE}/read", headers=headers)
    assert r.status_code == 404


def test_normal_path_ids_still_work(client, auth, data):
    """收紧转换器不得影响正常 id —— 这是 §2.6①-A 明确要求的对照断言。"""
    headers = auth("pm")
    r = client.get(f"/api/projects/{data['project_id']}", headers=headers)
    assert r.status_code == 200
    r = client.get(f"/api/agents/{data['dev_agent_id']}", headers=headers)
    assert r.status_code == 200
    # 不存在但在界内的 id 仍是领域 404（而非路由不匹配）。
    r = client.get("/api/requirements/999999", headers=headers)
    assert r.status_code == 404
    assert r.get_json()["error"] == "requirement not found"


# ————————————————— ② B 路径：请求体超界 id → 400 —————————————————

def test_oversized_body_ids_return_400(client, auth, make_requirement):
    headers = auth("pm")
    req = make_requirement()

    r = client.patch(f"/api/requirements/{req['id']}/assign",
                     json={"assignee_type": "user", "assignee_id": HUGE_INT}, headers=headers)
    assert r.status_code == 400, r.get_json()

    r = client.post("/api/requirements", json={"title": "x", "project_id": HUGE_INT},
                    headers=headers)
    assert r.status_code == 400
    assert r.get_json()["detail"]["expected"] == "integer within 64-bit range"

    r = client.post("/api/bugs", json={"title": "x", "related_requirement_id": HUGE_INT},
                    headers=headers)
    assert r.status_code == 400


def test_hard_bound_is_unconditional(client, auth):
    """【评审 R6】64 位硬界不得实现为 minimum/maximum 的默认值——否则显式传 maximum=
    的调用方（如 /tick 的 claim_count）会把硬界覆盖掉。"""
    r = client.post("/api/agents/1/tick", json={"claim_count": HUGE_INT}, headers=auth("pm"))
    assert r.status_code == 400


# ————————————————— ⑧ C 路径（评审 R1 硬门槛）：查询串超界 → 400 —————————————————

def test_oversized_query_ints_return_400(client, auth):
    """spec §6.3-D3：七条请求全部 400，**无一 500**。"""
    headers = auth("pm")
    cases = [
        ("/api/requirements", "assignee_id"),
        ("/api/requirements", "reporter_id"),
        ("/api/requirements", "offset"),
        ("/api/requirements", "project_id"),
        ("/api/board/requirements", "project_id"),
        ("/api/bugs", "offset"),
        ("/api/notifications", "offset"),
    ]
    for path, field in cases:
        r = client.get(f"{path}?{field}={HUGE}", headers=headers)
        assert r.status_code == 400, (path, field, r.status_code)
        body = r.get_json()
        assert body["error"] == f"invalid {field}"
        assert body["detail"]["field"] == field
        assert body["detail"]["expected"] == "integer within 64-bit range"


def test_limit_clamping_semantics_preserved(client, auth):
    """D3 对照组：`?limit=` 是「上限」而非取值，超界照钳不报错（既有语义逐字节不变）。"""
    headers = auth("pm")
    assert client.get(f"/api/requirements?limit={HUGE}", headers=headers).status_code == 200
    assert client.get("/api/requirements?limit=0", headers=headers).status_code == 200
    assert client.get("/api/requirements?limit=-5", headers=headers).status_code == 200
    # 非整数 limit 由「静默忽略」收紧为 400（§2.9-G2）。
    assert client.get("/api/requirements?limit=abc", headers=headers).status_code == 400


def test_negative_offset_now_400(client, auth):
    """§4-⑫：offset 为负由「静默归零」改为 400；offset=0 行为完全不变。"""
    headers = auth("pm")
    assert client.get("/api/requirements?offset=-1", headers=headers).status_code == 400
    assert client.get("/api/requirements?offset=0", headers=headers).status_code == 200


def test_malformed_filter_ints_return_400(client, auth):
    """§2.9-G2：畸形过滤值此前被静默丢弃（200 且返**全部**行），现在明确 400。"""
    headers = auth("pm")
    for field in ("assignee_id", "reporter_id"):
        r = client.get(f"/api/requirements?{field}=abc", headers=headers)
        assert r.status_code == 400
        assert r.get_json()["detail"]["field"] == field


# ————————————————— ⑨ 两处 64 位常量必须相等（防漂移）—————————————————

def test_db_int_bounds_agree_across_modules():
    """validation 与 scope 有意各自定义（互不依赖的叶子边界模块），数值必须一致。"""
    assert validation._MAX_DB_INT == scope.MAX_DB_INT
    assert validation._MIN_DB_INT == scope.MIN_DB_INT


# ————————————————— ③ 四处 description → 400 —————————————————

def test_non_string_description_returns_400(client, auth, data, make_requirement):
    headers = auth("pm")
    r = client.post("/api/projects",
                    json={"name": "n", "key": "K1", "description": {"a": 1}}, headers=headers)
    assert r.status_code == 400, r.get_json()

    r = client.post("/api/agents", json={"name": "z", "description": {"a": 1}}, headers=headers)
    assert r.status_code == 400

    r = client.patch(f"/api/agents/{data['dev_agent_id']}",
                     json={"description": [1, 2]}, headers=headers)
    assert r.status_code == 400

    req = make_requirement()
    client.patch(f"/api/requirements/{req['id']}/move",
                 json={"status": "assigned"}, headers=headers)
    client.patch(f"/api/requirements/{req['id']}/move",
                 json={"status": "in_development"}, headers=headers)
    client.patch(f"/api/requirements/{req['id']}/move",
                 json={"status": "testing"}, headers=headers)
    r = client.post(f"/api/requirements/{req['id']}/convert-to-bug",
                    json={"description": {"a": 1}}, headers=headers)
    assert r.status_code == 400


# ————————————————— ④ 关键字段 max_len —————————————————

def test_oversized_strings_return_400(client, auth):
    headers = auth("admin")
    r = client.post("/api/projects", json={"name": "n", "key": "K" * 100}, headers=headers)
    assert r.status_code == 400
    r = client.post("/api/projects", json={"name": "N" * 200, "key": "K2"}, headers=headers)
    assert r.status_code == 400
    r = client.post("/api/agents", json={"name": "N" * 300}, headers=headers)
    assert r.status_code == 400
    r = client.post("/api/users", json={"username": "u" * 100, "password": "p"}, headers=headers)
    assert r.status_code == 400
    r = client.post("/api/users",
                    json={"username": "u1", "password": "p", "email": "x" * 300}, headers=headers)
    assert r.status_code == 400
    # 管理员改邮箱路径此前既无长度也无格式校验，现补齐到 me.py 同一水位。
    r = client.post("/api/users",
                    json={"username": "u2", "password": "p", "email": "not-an-email"},
                    headers=headers)
    assert r.status_code == 400
    # 合法输入行为不变。
    r = client.post("/api/users",
                    json={"username": "u3", "password": "p", "email": "u3@example.com"},
                    headers=headers)
    assert r.status_code == 201


# ————————————————— ⑤ 删单串档（§2.7）—————————————————

def test_deleted_ticket_leaves_no_activity_for_reused_id(client, auth):
    """SQLite 复用主键：删单必须一并删审计，否则下一张同 id 的单继承别人的时间线
    （既是错数据，也是已删单标题的信息泄露）。"""
    headers = auth("pm")
    r = client.post("/api/requirements", json={"title": "OLD-SECRET"}, headers=headers)
    old = r.get_json()
    client.post(f"/api/requirements/{old['id']}/comments",
                json={"body": "机密讨论"}, headers=headers)
    assert client.delete(f"/api/requirements/{old['id']}", headers=headers).status_code == 204

    r = client.post("/api/requirements", json={"title": "BRAND-NEW"}, headers=headers)
    new = r.get_json()
    feed = client.get(f"/api/requirements/{new['id']}/feed", headers=headers).get_json()
    dumped = str(feed)
    assert "OLD-SECRET" not in dumped
    assert "机密讨论" not in dumped

    acts = client.get(f"/api/requirements/{new['id']}/activities", headers=headers).get_json()
    # 只应有新单自己的 "created"。
    assert [a["action"] for a in acts] == ["created"]


def test_bug_activities_endpoint_exists(client, auth, make_bug):
    """§2.9-G4：BUG 侧此前缺 /activities，纯路由不对称。"""
    bug = make_bug()
    r = client.get(f"/api/bugs/{bug['id']}/activities", headers=auth("pm"))
    assert r.status_code == 200
    assert [a["action"] for a in r.get_json()] == ["created"]
    assert client.get(f"/api/bugs/{HUGE}/activities", headers=auth("pm")).status_code == 404


# ————————————————— ⑥ claim-next 门禁（§2.2⑤）—————————————————

def test_offline_agent_cannot_claim(client, auth, data):
    """离线 Agent 此前认领成功（200）却在 /autorun 时 409 —— 「吞了又不干」的陷阱态。"""
    headers = auth("pm")
    aid = data["dev_agent_id"]
    assert client.patch(f"/api/agents/{aid}", json={"status": "offline"},
                        headers=headers).status_code == 200
    r = client.post(f"/api/agents/{aid}/claim-next", json={}, headers=headers)
    assert r.status_code == 409
    assert r.get_json()["error"] == "agent is busy or offline"


def test_idle_agent_can_still_claim(client, auth, data, make_requirement):
    """门禁不得误伤正常路径。"""
    headers = auth("pm")
    make_requirement(title="待认领")
    r = client.post(f"/api/agents/{data['dev_agent_id']}/claim-next", json={}, headers=headers)
    assert r.status_code == 200
    assert r.get_json()["claimed"]["title"] == "待认领"


# ————————————————— ⑦ 软锁不泄漏（§2.9-G3）—————————————————

def test_agent_returns_to_idle_after_failed_run(client, auth, data, monkeypatch):
    """_run_with_lock 的 finally 必须先 rollback：否则 commit 自身抛 PendingRollbackError，
    软锁恢复丢失 → Agent 永久 busy，此后每次 autorun/tick 都 409。"""
    from services import agent_autopilot

    headers = auth("pm")
    aid = data["dev_agent_id"]

    def boom(*args, **kwargs):
        raise RuntimeError("模拟推进期崩溃")

    monkeypatch.setattr(agent_autopilot, "autorun", boom)
    r = client.post(f"/api/agents/{aid}/autorun", json={}, headers=headers)
    assert r.status_code == 500

    monkeypatch.undo()
    agent = client.get(f"/api/agents/{aid}", headers=headers).get_json()
    assert agent["status"] == "idle"
    # 且软锁确实已释放：下一次 autorun 不再 409。
    assert client.post(f"/api/agents/{aid}/autorun", json={},
                       headers=headers).status_code == 200
