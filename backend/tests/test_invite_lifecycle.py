"""邀请码生命周期：期限 / 额度 / 用量派生 / issued_at 回落链 / reason 分流 / 状态下发
（login-hardening-and-audit-console §7.2 A 组 1–20/11′、B 组 21–26）。

与 `tests/test_app_settings.py` 的分工：那边测既有三键的读写与门禁，这边测本轮新增的
期限 / 额度 / 用量三条语义。signup 前一律 `ratelimit.reset()` 复位，把 SIGNUP_MAX_ATTEMPTS
从测试变量里排除掉——本文件只测邀请码逻辑。
"""
from datetime import timedelta

from extensions import db, utcnow
from models.app_setting import AppSetting
from models.user import User
from services import app_settings, ratelimit


def _signup(client, username, code="aragon"):
    ratelimit.reset()
    return client.post("/api/auth/signup", json={
        "username": username, "password": "Aragon2026", "invite_code": code})


def _set_raw(app, key, value):
    """直接写一行设置，绕过路由校验（用于构造「过去的失效时刻」等非法态）。"""
    with app.app_context():
        row = AppSetting.query.filter_by(key=key).first()
        if row is None:
            db.session.add(AppSetting(key=key, value=value))
        else:
            row.value = value
        db.session.commit()


def _patch(client, root_auth, **body):
    return client.patch("/api/settings/registration", json=body, headers=root_auth)


def _reg(client, root_auth):
    return client.get("/api/settings/registration", headers=root_auth).get_json()


# ————————————————————— A. 期限与额度 1–20（含 11′）—————————————————————

def test_no_quota_rows_signup_unchanged(client):
    assert _signup(client, "alice").status_code == 201


def test_future_expiry_allows_signup(client, root_auth):
    future = (utcnow() + timedelta(days=1)).isoformat()
    assert _patch(client, root_auth, expires_at=future).status_code == 200
    assert _signup(client, "bob").status_code == 201


def test_past_expiry_rejects_signup(client, app):
    _set_raw(app, app_settings.KEY_INVITE_EXPIRES_AT,
             (utcnow() - timedelta(days=1)).isoformat())
    r = _signup(client, "carol")
    assert r.status_code == 403
    assert r.get_json()["error"] == "invite code has expired"


def test_expiry_exactly_now_is_expired(client, app):
    _set_raw(app, app_settings.KEY_INVITE_EXPIRES_AT, utcnow().isoformat())
    r = _signup(client, "dave")
    assert r.status_code == 403                     # 判据是 >=，边界闭
    assert r.get_json()["error"] == "invite code has expired"


def test_max_uses_zero_is_unlimited(client, root_auth):
    assert _patch(client, root_auth, max_uses=0).status_code == 200
    for name in ("u1", "u2", "u3"):
        assert _signup(client, name).status_code == 201


def test_max_uses_two_blocks_third(client, root_auth):
    assert _patch(client, root_auth, max_uses=2).status_code == 200
    assert _signup(client, "e1").status_code == 201
    assert _signup(client, "e2").status_code == 201
    r = _signup(client, "e3")
    assert r.status_code == 403
    assert r.get_json()["error"] == "invite code has reached its limit"


def test_max_uses_counts_only_signup_source(client, app, root_auth):
    # 两个 admin-source 用户不占用额度。
    with app.app_context():
        for name in ("adm1", "adm2"):
            u = User(username=name, role="member", source="admin")
            u.set_password("Aragon2026")
            db.session.add(u)
        db.session.commit()
    assert _patch(client, root_auth, max_uses=2).status_code == 200
    assert _signup(client, "f1").status_code == 201
    assert _signup(client, "f2").status_code == 201


def test_rotate_resets_usage(client, root_auth):
    assert _patch(client, root_auth, max_uses=1).status_code == 200
    assert _signup(client, "g1").status_code == 201
    assert _signup(client, "g2").status_code == 403         # 用尽
    client.post("/api/settings/registration/rotate-code", headers=root_auth)
    new_code = _reg(client, root_auth)["invite_code"]
    assert _signup(client, "g3", code=new_code).status_code == 201


def test_new_invite_code_resets_usage(client, root_auth):
    assert _patch(client, root_auth, max_uses=1).status_code == 200
    assert _signup(client, "h1").status_code == 201
    assert _signup(client, "h2").status_code == 403
    assert _patch(client, root_auth, invite_code="BRANDNEWCODE").status_code == 200
    assert _signup(client, "h3", code="BRANDNEWCODE").status_code == 201


def test_resaving_same_code_does_not_reset_usage(client, root_auth):
    """10：额度用尽后把 invite_code 原样再保存一次 → 用量**不**归零（A-3 的核心判据）。"""
    assert _patch(client, root_auth, max_uses=1).status_code == 200
    assert _signup(client, "i1").status_code == 201
    assert _signup(client, "i2").status_code == 403
    assert _patch(client, root_auth, invite_code="aragon").status_code == 200   # 原样
    assert _signup(client, "i3").status_code == 403                             # 仍用尽


def test_resave_by_other_actor_does_not_reset_usage(client, app, root_auth):
    """11：换一个施动者原样保存码 → 用量仍不归零（updated_by_id 陷阱，值判等短路）。"""
    assert _patch(client, root_auth, max_uses=1).status_code == 200
    assert _signup(client, "j1").status_code == 201
    with app.app_context():
        # 直接在服务层以一个不同 actor_id 原样保存——值没变 → 整条短路，不弄脏码行。
        app_settings.set_registration_settings({"invite_code": "aragon"}, actor_id=999)
        db.session.commit()
    assert _signup(client, "j2").status_code == 403


def test_never_changed_code_db_survives_other_actor_resave(client, app, root_auth):
    """11′【评审 P1-1】从未改过码的库（只设 max_uses，anchor 由 _ensure_invite_anchor 补出）
    → 换一个根管理员原样保存 → 用量**不**归零。v1 的写法在这条路径上会静默归零。"""
    assert _patch(client, root_auth, max_uses=1).status_code == 200
    # anchor 已被补出：issued_at 行存在。
    with app.app_context():
        assert AppSetting.query.filter_by(
            key=app_settings.KEY_INVITE_ISSUED_AT).first() is not None
        issued_before = AppSetting.query.filter_by(
            key=app_settings.KEY_INVITE_ISSUED_AT).first().value
    assert _signup(client, "k1").status_code == 201
    assert _signup(client, "k2").status_code == 403                 # 用尽
    with app.app_context():
        app_settings.set_registration_settings({"invite_code": "aragon"}, actor_id=999)
        db.session.commit()
        issued_after = AppSetting.query.filter_by(
            key=app_settings.KEY_INVITE_ISSUED_AT).first().value
    assert issued_after == issued_before            # 锚点未被移动
    assert _signup(client, "k3").status_code == 403                 # 仍用尽


def test_wrong_code_and_expired_reports_mismatch(client, app):
    _set_raw(app, app_settings.KEY_INVITE_EXPIRES_AT,
             (utcnow() - timedelta(days=1)).isoformat())
    r = _signup(client, "l1", code="WRONGCODE")
    assert r.status_code == 403
    assert r.get_json()["error"] == "invalid invite code"          # 不泄露过期事实


def test_wrong_code_and_exhausted_reports_mismatch(client, root_auth):
    assert _patch(client, root_auth, max_uses=1).status_code == 200
    assert _signup(client, "m1").status_code == 201
    r = _signup(client, "m2", code="WRONGCODE")
    assert r.status_code == 403
    assert r.get_json()["error"] == "invalid invite code"


def test_verify_alias_matches_check(client, app):
    with app.app_context():
        assert app_settings.verify_invite_code("aragon") is True
        assert app_settings.verify_invite_code("aragon") == \
            app_settings.check_invite_code("aragon").ok
        assert app_settings.verify_invite_code("nope") is False


def test_chinese_invite_code_does_not_500(client, app):
    """15【上一轮 F-1 回归护栏，必须保留】中文邀请码 + 中文候选 → 不 500。"""
    with app.app_context():
        app_settings.set_registration_settings({"invite_code": "中文邀请码"}, actor_id=None)
        db.session.commit()
    r = _signup(client, "n1", code="中文邀请码")
    assert r.status_code == 201


def test_patch_past_expiry_is_400(client, root_auth):
    past = (utcnow() - timedelta(days=1)).isoformat()
    r = _patch(client, root_auth, expires_at=past)
    assert r.status_code == 400
    assert r.get_json()["detail"]["field"] == "expires_at"


def test_patch_empty_expiry_clears(client, root_auth):
    future = (utcnow() + timedelta(days=1)).isoformat()
    assert _patch(client, root_auth, expires_at=future).status_code == 200
    assert _patch(client, root_auth, expires_at="").status_code == 200
    assert _reg(client, root_auth)["invite_expires_at"] is None


def test_patch_max_uses_bounds(client, root_auth):
    assert _patch(client, root_auth, max_uses=-1).status_code == 400
    assert _patch(client, root_auth, max_uses=10001).status_code == 400
    assert _patch(client, root_auth, max_uses="x").status_code == 400


def test_patch_max_uses_integer_ok(client, root_auth):
    assert _patch(client, root_auth, max_uses=5).status_code == 200
    assert _reg(client, root_auth)["invite_max_uses"] == 5


def test_expiry_with_z_roundtrips(client, root_auth):
    """20（R-14）：带 Z 的失效时刻提交 → 200，回读一致。"""
    assert _patch(client, root_auth, expires_at="2026-12-01T00:00:00Z").status_code == 200
    body = _reg(client, root_auth)
    assert body["invite_expires_at"] == "2026-12-01T00:00:00Z"


# ————————————————————— B. 用量与状态下发 21–26 —————————————————————

def test_registration_payload_has_all_additive_keys(client, root_auth):
    body = _reg(client, root_auth)
    for key in ("invite_expires_at", "invite_max_uses", "invite_uses",
                "invite_issued_at", "invite_status"):
        assert key in body
    # 既有六键仍在。
    for key in ("enabled", "invite_code", "default_role", "allowed_default_roles",
                "updated_at", "updated_by"):
        assert key in body


def test_invite_uses_increments_with_signup(client, root_auth):
    assert _reg(client, root_auth)["invite_uses"] == 0
    assert _signup(client, "o1").status_code == 201
    assert _reg(client, root_auth)["invite_uses"] == 1
    assert _signup(client, "o2").status_code == 201
    assert _reg(client, root_auth)["invite_uses"] == 2


def test_invite_status_disabled_takes_priority(client, root_auth):
    assert _patch(client, root_auth, enabled=False).status_code == 200
    assert _reg(client, root_auth)["invite_status"] == "disabled"


def test_invite_status_expired_and_exhausted(client, app, root_auth):
    _set_raw(app, app_settings.KEY_INVITE_EXPIRES_AT,
             (utcnow() - timedelta(days=1)).isoformat())
    assert _reg(client, root_auth)["invite_status"] == "expired"

    _set_raw(app, app_settings.KEY_INVITE_EXPIRES_AT, "")      # 清期限
    assert _patch(client, root_auth, max_uses=1).status_code == 200
    assert _signup(client, "p1").status_code == 201
    assert _reg(client, root_auth)["invite_status"] == "exhausted"


def test_issued_at_three_level_fallback(client, app):
    with app.app_context():
        # 第 3 级：全新库无任何行 → None，用量 = 全部 signup。
        rows = app_settings._stored_values()
        assert app_settings.invite_issued_at(rows) is None

        u = User(username="q1", role="member", source="signup")
        u.set_password("Aragon2026")
        db.session.add(u)
        db.session.commit()
        rows = app_settings._stored_values()
        assert app_settings.invite_uses(rows) == 1

        # 第 2 级：写了码行、无 issued_at 行 → 用码行 updated_at。
        app_settings._upsert(app_settings.KEY_REGISTRATION_INVITE_CODE, "aragon", None)
        db.session.commit()
        rows = app_settings._stored_values()
        assert app_settings.KEY_INVITE_ISSUED_AT not in rows
        assert app_settings.invite_issued_at(rows) is not None


def test_registration_read_forbidden_for_non_root(client, auth):
    assert client.get("/api/settings/registration",
                      headers=auth("admin")).status_code == 403
