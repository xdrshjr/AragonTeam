"""P-T8 健康检查（Phase-2 §6.1）。"""


def test_health_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "ok"
    assert body["service"] == "aragonteam-backend"
    assert body["db"] == "ok"


def test_health_sets_request_id_header(client):
    r = client.get("/api/health")
    # 可观测性：每个响应都回写 X-Request-Id（§2.5-1）。
    assert r.headers.get("X-Request-Id")
