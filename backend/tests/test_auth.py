"""P-T2 鉴权（Phase-2 §6.1）。登录成功/失败、me、register admin-only、限流 429。"""


def test_login_success(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["token"]
    assert body["user"]["role"] == "admin"


def test_login_wrong_password(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "nope"})
    assert r.status_code == 401
    assert r.get_json()["error"]  # 错误契约：error 字段恒存在


def test_me_restores_identity(client, auth):
    r = client.get("/api/auth/me", headers=auth("member"))
    assert r.status_code == 200
    assert r.get_json()["user"]["username"] == "member"


def test_me_requires_token(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_register_is_admin_only(client, auth):
    payload = {"username": "newbie", "password": "Pw123456", "role": "member"}
    # member 无权 register
    r = client.post("/api/auth/register", json=payload, headers=auth("member"))
    assert r.status_code == 403
    # admin 可以
    r2 = client.post("/api/auth/register", json=payload, headers=auth("admin"))
    assert r2.status_code == 201
    assert r2.get_json()["user"]["username"] == "newbie"


def test_login_ratelimit_429(client):
    # TestConfig LOGIN_MAX_ATTEMPTS=3：同一 key 连续失败达阈后返回 429（【R-03】计数随 app 重建）。
    for _ in range(3):
        r = client.post("/api/auth/login", json={"username": "admin", "password": "bad"})
        assert r.status_code == 401
    blocked = client.post("/api/auth/login", json={"username": "admin", "password": "bad"})
    assert blocked.status_code == 429
    # 即便此刻给对密码，仍被限流拦截（仅对失败计数，窗口内不放行）。
    still = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert still.status_code == 429


def test_login_success_clears_counter(client):
    # 两次失败（未达阈 3）后成功登录清零，不误伤后续。
    for _ in range(2):
        client.post("/api/auth/login", json={"username": "pm", "password": "bad"})
    ok = client.post("/api/auth/login", json={"username": "pm", "password": "pm123"})
    assert ok.status_code == 200
    # 清零后再失败一次不应立即 429。
    again = client.post("/api/auth/login", json={"username": "pm", "password": "bad"})
    assert again.status_code == 401


def test_invalid_token_returns_401(client):
    # 【§2.4-C2】伪造 / 篡改 token → 401（此前 422 会让前端不跳登录、会话卡死）。
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer forged.invalid.token"})
    assert r.status_code == 401
    assert r.status_code != 422
    assert r.get_json()["error"]
