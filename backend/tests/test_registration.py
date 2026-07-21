"""自助注册全路径（self-service-registration §8.2 用例 1–20c）。

覆盖：开关 / 邀请码 / 口令强度 / 重名与保留名 / 限流（含反代口径）/ 并发竞态 / 通知扇出，
以及一条**回归守卫**——既有 `POST /api/auth/register`（admin-only）契约逐字不变。

与 `tests/test_app_settings.py` 的分工：那边测**设置本身**的读写与门禁，这边测
「设置生效之后注册会怎样」。
"""
import pytest
from sqlalchemy.exc import IntegrityError

from extensions import db
from models.notification import Notification
from models.user import User
from services import app_settings

GOOD = {"username": "linlei", "password": "Aragon2026", "invite_code": "aragon"}


def _signup(client, **overrides):
    return client.post("/api/auth/signup", json={**GOOD, **overrides})


# ————————————————————— 正常路径 —————————————————————

def test_signup_creates_user_and_returns_token(client):
    r = _signup(client)

    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert set(body) == {"token", "user"}          # 形状与 /login 完全一致
    me = client.get("/api/auth/me",
                    headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200
    assert me.get_json()["user"]["username"] == "linlei"


def test_signup_assigns_configured_default_role(client, app, root_auth):
    assert _signup(client).get_json()["user"]["role"] == "member"

    r = client.patch("/api/settings/registration", json={"default_role": "pm"},
                     headers=root_auth)
    assert r.status_code == 200, r.get_json()

    assert _signup(client, username="linlei2").get_json()["user"]["role"] == "pm"


def test_signup_marks_source_as_signup(client):
    user = _signup(client).get_json()["user"]

    assert user["source"] == "signup"
    assert user["is_root"] is False


def test_signup_endpoint_is_public(client):
    """不带 Authorization 头也能 201——这正是本轮要开的那扇门。"""
    assert _signup(client).status_code == 201


def test_signup_defaults_display_name_to_username(client):
    assert _signup(client).get_json()["user"]["display_name"] == "linlei"


# ————————————————————— 邀请码 —————————————————————

def test_rejects_wrong_invite_code(client):
    r = _signup(client, invite_code="nope")

    assert r.status_code == 403
    assert r.get_json()["detail"]["field"] == "invite_code"


def test_invite_code_is_case_sensitive(client):
    """邀请码是凭据不是标识符，宽松匹配等于缩小密钥空间。"""
    assert _signup(client, invite_code="Aragon").status_code == 403


def test_invite_code_accepts_surrounding_whitespace(client):
    """从 IM 里复制常带空格：只 strip，不改大小写。"""
    assert _signup(client, invite_code="  aragon  ").status_code == 201


def test_rejects_non_ascii_invite_code_without_500(client):
    """中文邀请码曾让 hmac.compare_digest 抛 TypeError → 公开端点 500（回归钉子）。"""
    r = _signup(client, invite_code="邀请码")

    assert r.status_code == 403
    assert r.get_json()["detail"]["field"] == "invite_code"


def test_non_ascii_invite_code_can_be_set_and_used(client, root_auth):
    """根管理员把邀请码设成中文后，注册链路两端仍必须能走通。"""
    r = client.patch("/api/settings/registration", json={"invite_code": "阿拉贡2026"},
                     headers=root_auth)
    assert r.status_code == 200, r.get_json()

    assert _signup(client, invite_code="aragon").status_code == 403
    assert _signup(client, invite_code="阿拉贡2026").status_code == 201


def test_rejects_when_registration_disabled(client, root_auth):
    r = client.patch("/api/settings/registration", json={"enabled": False},
                     headers=root_auth)
    assert r.status_code == 200, r.get_json()

    r = _signup(client)
    assert r.status_code == 403
    assert r.get_json()["error"] == "registration is disabled"


# ————————————————————— 用户名 —————————————————————

def test_rejects_duplicate_username(client):
    assert _signup(client).status_code == 201

    assert _signup(client).status_code == 409


def test_rejects_reserved_root_username(client, app):
    """【R-15】抢注 ROOT_ADMIN_USERNAME → 下次重启即被提为不可降级的根管理员。

    响应体必须与普通重名 409 **逐字节相同**，否则等于额外泄露「这个名字是根管理员用户名」。
    """
    app.config["ROOT_ADMIN_USERNAME"] = "rootowner"      # 库里并不存在这个用户
    reserved = _signup(client, username="rootowner")
    assert _signup(client, username="taken").status_code == 201
    duplicate = _signup(client, username="taken")

    assert reserved.status_code == 409
    assert reserved.get_json() == duplicate.get_json()


def test_admin_create_user_rejects_reserved_username(client, app, auth):
    """【R-15】管理员建号这条路径必须用**同一个**保留名判据，否则堵一条漏一条。"""
    app.config["ROOT_ADMIN_USERNAME"] = "rootowner"

    r = client.post("/api/users",
                    json={"username": "rootowner", "password": "pw12345"},
                    headers=auth("admin"))

    assert r.status_code == 409
    assert r.get_json()["error"] == "username already exists"


def test_duplicate_username_race_returns_409_not_500(client, monkeypatch):
    """预检放行但 commit 撞唯一索引（两个并发同名注册的输家）→ 409，且会话已回滚。"""
    def _boom():
        raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed"))

    monkeypatch.setattr(db.session, "commit", _boom, raising=False)

    r = _signup(client)

    assert r.status_code == 409
    assert r.get_json()["error"] == "username already exists"
    monkeypatch.undo()
    assert User.query.filter_by(username="linlei").first() is None


# ————————————————————— 口令强度 —————————————————————

@pytest.mark.parametrize("password", ["Ab1", "aragonaragon", "linlei"])
def test_rejects_weak_password(client, password):
    """依次是：太短 / 只有一类字符 / 等于用户名。三条都必须 400 且指向 password 字段。"""
    r = _signup(client, password=password)

    assert r.status_code == 400, r.get_json()
    assert r.get_json()["detail"]["field"] == "password"


def test_rejects_password_equal_to_username_case_insensitively(client):
    r = _signup(client, username="Aragon2026", password="aragon2026")

    assert r.status_code == 400
    assert r.get_json()["detail"]["field"] == "password"


# ————————————————————— 边界输入 —————————————————————

def test_rejects_non_string_fields(client):
    r = client.post("/api/auth/signup",
                    json={**GOOD, "username": 123})

    assert r.status_code == 400
    assert r.get_json()["detail"]["field"] == "username"


@pytest.mark.parametrize("body", [5, [1], "x"])
def test_rejects_non_object_body(client, body):
    assert client.post("/api/auth/signup", json=body).status_code == 400


def test_rejects_invalid_email_format(client):
    r = _signup(client, email="not-an-email")

    assert r.status_code == 400
    assert r.get_json()["detail"]["field"] == "email"


def test_signup_email_validation_matches_admin_path(client, auth):
    """【P0-1】同一个非法邮箱在三条路径上得到同一水位的 400——证明三者共用 want_email。"""
    bad = "not-an-email"
    signup = _signup(client, email=bad)
    created = client.post("/api/users",
                          json={"username": "u9", "password": "pw12345", "email": bad},
                          headers=auth("admin"))
    profile = client.patch("/api/me/profile", json={"email": bad}, headers=auth("member"))

    assert signup.status_code == created.status_code == profile.status_code == 400
    for r in (signup, created, profile):
        assert r.get_json()["detail"]["field"] == "email"


# ————————————————————— 限流 —————————————————————

def test_rate_limits_after_threshold(client):
    """TestConfig 的 SIGNUP_MAX_ATTEMPTS=3：第 4 次尝试被拦。"""
    for i in range(3):
        _signup(client, username=f"u{i}", invite_code="wrong")

    r = _signup(client)
    assert r.status_code == 429


def test_successful_signups_also_count_toward_limit(client):
    """成功也计数——这里要挡的既是暴力猜码，也是批量注册。"""
    for i in range(3):
        assert _signup(client, username=f"ok{i}").status_code == 201

    assert _signup(client, username="ok3").status_code == 429


def test_rate_limit_key_respects_trust_proxy_count(client, app):
    """【R-14】TRUST_PROXY_COUNT=1 时两个客户端各自计数，互不牵连。"""
    app.config["TRUST_PROXY_COUNT"] = 1
    first = {"X-Forwarded-For": "203.0.113.7"}
    second = {"X-Forwarded-For": "198.51.100.9"}
    for i in range(3):
        client.post("/api/auth/signup", json={**GOOD, "username": f"a{i}"}, headers=first)

    blocked = client.post("/api/auth/signup", json={**GOOD, "username": "a9"}, headers=first)
    other = client.post("/api/auth/signup", json={**GOOD, "username": "b0"}, headers=second)

    assert blocked.status_code == 429
    assert other.status_code == 201


def test_forwarded_header_is_ignored_by_default(client):
    """默认 TRUST_PROXY_COUNT=0：转发头完全不看，否则每请求换一个伪造 IP 即可绕过限流。"""
    for i in range(3):
        client.post("/api/auth/signup", json={**GOOD, "username": f"c{i}"},
                    headers={"X-Forwarded-For": f"203.0.113.{i}"})

    r = client.post("/api/auth/signup", json={**GOOD, "username": "c9"},
                    headers={"X-Forwarded-For": "203.0.113.250"})
    assert r.status_code == 429


# ————————————————————— 通知 —————————————————————

def test_notifies_all_active_admins(client, app, data):
    with app.app_context():
        extra = User(username="admin2", role="admin", display_name="A2", is_active=False)
        extra.set_password("pw12345")
        db.session.add(extra)
        db.session.commit()
        disabled_id = extra.id

    assert _signup(client).status_code == 201

    with app.app_context():
        rows = Notification.query.filter_by(type="user_registered").all()
        assert [n.user_id for n in rows] == [data["admin_id"]]
        assert disabled_id not in {n.user_id for n in rows}


def test_notification_has_null_entity(client, app):
    """这条通知不指向任何工单；前端铃铛的 entity_type 守卫据此只标已读、不跳转（R-6）。"""
    _signup(client)

    with app.app_context():
        n = Notification.query.filter_by(type="user_registered").one()
        assert n.entity_type is None and n.entity_id is None
        assert n.actor_type == "user"
        assert "linlei" in n.message


def test_respects_notification_preference(client, app, auth):
    r = client.patch("/api/me/notification-preferences",
                     json={"preferences": {"user_registered": False}},
                     headers=auth("admin"))
    assert r.status_code == 200, r.get_json()

    _signup(client)

    with app.app_context():
        assert Notification.query.filter_by(type="user_registered").count() == 0


# ————————————————————— 回归守卫 —————————————————————

def test_admin_register_endpoint_unchanged(client, auth):
    """`POST /auth/register` 仍是 admin-only、仍不校验邀请码——契约逐字不变。"""
    anonymous = client.post("/api/auth/register",
                            json={"username": "x1", "password": "pw12345"})
    as_member = client.post("/api/auth/register",
                            json={"username": "x1", "password": "pw12345"},
                            headers=auth("member"))
    as_admin = client.post("/api/auth/register",
                           json={"username": "x1", "password": "pw12345"},
                           headers=auth("admin"))

    assert anonymous.status_code == 401
    assert as_member.status_code == 403
    assert as_admin.status_code == 201            # 没有 invite_code 也能建


def test_registration_meta_is_public_and_leaks_no_code(client):
    r = client.get("/api/auth/registration-meta")

    assert r.status_code == 200
    body = r.get_json()
    assert body == {"enabled": True, "invite_required": True, "password_min_length": 8}
    assert "invite_code" not in body


def test_config_default_role_cannot_escape_whitelist(client, app):
    """【R-16】`REGISTRATION_DEFAULT_ROLE=admin` + 空 app_settings 表 → 仍只能是 member。"""
    app.config["REGISTRATION_DEFAULT_ROLE"] = "admin"

    with app.app_context():
        assert app_settings.get_registration_settings()["default_role"] == "member"

    assert _signup(client).get_json()["user"]["role"] == "member"
