"""account-settings §9 —— 账号自助中心（资料 / 改密 / 通知偏好）。

覆盖三块能力的正常 + 异常路径，并含两条关键回归：
- 偏好 upsert 收敛（同键重复 PATCH 只留单行、走 UPDATE，不产生重复行）〔§10 R10〕；
- 静音端到端生效（静音某类型后该类型不再扇出，未静音的他人不受影响）。

改密用例走**真实** /api/auth/login 验证（遵守 CLAUDE.md「鉴权签名不得 mock」）。
"""
from extensions import db
from models.notification import NOTIFICATION_TYPES
from models.notification_preference import NotificationPreference
from services import notification_prefs


# ————————————————————— 资料（profile） —————————————————————

def test_update_profile_all_fields(client, auth):
    r = client.patch("/api/me/profile",
                     json={"display_name": "Mia L.", "email": "mia@x.dev",
                           "avatar_color": "#6E8B3D"},
                     headers=auth("member"))
    assert r.status_code == 200, r.get_json()
    user = r.get_json()["user"]
    assert user["display_name"] == "Mia L."
    assert user["email"] == "mia@x.dev"
    assert user["avatar_color"] == "#6E8B3D"


def test_update_profile_clears_email_with_empty_string(client, auth):
    r = client.patch("/api/me/profile", json={"email": ""}, headers=auth("member"))
    assert r.status_code == 200
    assert r.get_json()["user"]["email"] is None


def test_update_profile_rejects_empty_display_name(client, auth):
    r = client.patch("/api/me/profile", json={"display_name": "   "}, headers=auth("member"))
    assert r.status_code == 400
    assert r.get_json()["error"]


def test_update_profile_rejects_overlong_display_name(client, auth):
    r = client.patch("/api/me/profile", json={"display_name": "x" * 129}, headers=auth("member"))
    assert r.status_code == 400


def test_update_profile_rejects_invalid_email(client, auth):
    r = client.patch("/api/me/profile", json={"email": "not-an-email"}, headers=auth("member"))
    assert r.status_code == 400


def test_update_profile_rejects_invalid_avatar_color(client, auth):
    r = client.patch("/api/me/profile", json={"avatar_color": "red"}, headers=auth("member"))
    assert r.status_code == 400


def test_update_profile_requires_token(client):
    r = client.patch("/api/me/profile", json={"display_name": "x"})
    assert r.status_code == 401


def test_update_profile_ignores_username_and_role(client, auth):
    before = client.get("/api/auth/me", headers=auth("member")).get_json()["user"]
    r = client.patch("/api/me/profile",
                     json={"username": "hacker", "role": "admin", "display_name": "Mia Q."},
                     headers=auth("member"))
    assert r.status_code == 200
    user = r.get_json()["user"]
    assert user["display_name"] == "Mia Q."
    assert user["username"] == before["username"]  # 白名单外键恒忽略
    assert user["role"] == before["role"]          # 仍是 member，未越权升 admin


# ————————————————————— 改密（password） —————————————————————

def test_change_password_success_relogin(client, auth, login):
    r = client.post("/api/me/password",
                    json={"current_password": "member123", "new_password": "newpass456"},
                    headers=auth("member"))
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    assert login("member", "member123").status_code == 401   # 旧密码失效
    assert login("member", "newpass456").status_code == 200   # 新密码可登录


def test_change_password_wrong_current(client, auth):
    r = client.post("/api/me/password",
                    json={"current_password": "wrong", "new_password": "newpass456"},
                    headers=auth("member"))
    assert r.status_code == 400
    assert "incorrect" in r.get_json()["error"]


def test_change_password_too_short(client, auth):
    r = client.post("/api/me/password",
                    json={"current_password": "member123", "new_password": "123"},
                    headers=auth("member"))
    assert r.status_code == 400


def test_change_password_must_differ(client, auth):
    r = client.post("/api/me/password",
                    json={"current_password": "member123", "new_password": "member123"},
                    headers=auth("member"))
    assert r.status_code == 400


def test_change_password_missing_field(client, auth):
    r = client.post("/api/me/password", json={"current_password": "member123"},
                    headers=auth("member"))
    assert r.status_code == 400


def test_change_password_requires_token(client):
    r = client.post("/api/me/password",
                    json={"current_password": "member123", "new_password": "newpass456"})
    assert r.status_code == 401


# ————————————————————— 通知偏好（preferences） —————————————————————

def test_get_preferences_defaults_all_true(client, auth):
    r = client.get("/api/me/notification-preferences", headers=auth("member"))
    assert r.status_code == 200
    prefs = r.get_json()["preferences"]
    assert set(prefs.keys()) == set(NOTIFICATION_TYPES)
    assert all(prefs.values())


def test_patch_preference_persists(client, auth):
    r = client.patch("/api/me/notification-preferences",
                     json={"preferences": {"assigned": False}}, headers=auth("member"))
    assert r.status_code == 200
    assert r.get_json()["preferences"]["assigned"] is False
    again = client.get("/api/me/notification-preferences", headers=auth("member")).get_json()
    assert again["preferences"]["assigned"] is False
    assert again["preferences"]["commented"] is True  # 其它类型不受影响


def test_patch_preference_unknown_type(client, auth):
    r = client.patch("/api/me/notification-preferences",
                     json={"preferences": {"bogus": False}}, headers=auth("member"))
    assert r.status_code == 400
    body = r.get_json()
    assert body["error"] == "unknown notification type"
    assert "assigned" in body["detail"]["allowed"]
    assert body["detail"]["unknown"] == ["bogus"]


def test_patch_preference_non_bool_value(client, auth):
    r = client.patch("/api/me/notification-preferences",
                     json={"preferences": {"assigned": "no"}}, headers=auth("member"))
    assert r.status_code == 400


def test_patch_preference_empty_object(client, auth):
    r = client.patch("/api/me/notification-preferences",
                     json={"preferences": {}}, headers=auth("member"))
    assert r.status_code == 400


def test_patch_preference_idempotent(client, auth):
    headers = auth("member")
    first = client.patch("/api/me/notification-preferences",
                         json={"preferences": {"assigned": False}}, headers=headers)
    second = client.patch("/api/me/notification-preferences",
                          json={"preferences": {"assigned": False}}, headers=headers)
    assert first.status_code == second.status_code == 200
    assert second.get_json()["preferences"]["assigned"] is False


def test_preferences_requires_token(client):
    assert client.get("/api/me/notification-preferences").status_code == 401
    r = client.patch("/api/me/notification-preferences", json={"preferences": {"assigned": False}})
    assert r.status_code == 401


# ————————————————————— 并发 upsert 收敛（回归 §10 R10） —————————————————————

def test_repeat_patch_converges_to_single_row(client, auth, data, app):
    """同键相反值重复 PATCH：DB 恒单行、值为最后一次提交（行已存在走 UPDATE，非 500）。"""
    headers = auth("member")
    assert client.patch("/api/me/notification-preferences",
                        json={"preferences": {"assigned": False}}, headers=headers).status_code == 200
    r2 = client.patch("/api/me/notification-preferences",
                      json={"preferences": {"assigned": True}}, headers=headers)
    assert r2.status_code == 200
    assert r2.get_json()["preferences"]["assigned"] is True
    rows = NotificationPreference.query.filter_by(
        user_id=data["member_id"], type="assigned").all()
    assert len(rows) == 1
    assert rows[0].enabled is True


def test_set_preferences_rerun_is_idempotent(app, data):
    """服务函数二次运行幂等、不抛、不产生重复行——路由 IntegrityError 重跑所依赖的收敛性。"""
    uid = data["member_id"]
    notification_prefs.set_preferences(uid, {"assigned": False})
    db.session.commit()
    notification_prefs.set_preferences(uid, {"assigned": False})  # 重跑同 mapping
    db.session.commit()
    rows = NotificationPreference.query.filter_by(user_id=uid, type="assigned").all()
    assert len(rows) == 1
    assert rows[0].enabled is False


# ————————————————————— 静音端到端生效（集成 §9） —————————————————————

def _assigned_notes(client, auth, role):
    notes = client.get("/api/notifications?unread=1", headers=auth(role)).get_json()
    return [n for n in notes if n["type"] == "assigned"]


def test_muting_suppresses_only_that_user_and_type(client, auth, make_requirement, data):
    """member 静音 assigned → 指派给 member 不产生通知；未静音的 member2 仍正常收。"""
    # member 静音「指派」。
    assert client.patch("/api/me/notification-preferences",
                        json={"preferences": {"assigned": False}},
                        headers=auth("member")).status_code == 200
    # pm 指派两张单：一张给 member（静音），一张给 member2（未静音）。
    make_requirement(assignee=("user", data["member_id"]))
    make_requirement(assignee=("user", data["member2_id"]))
    assert _assigned_notes(client, auth, "member") == []          # 被静音，不落库
    assert len(_assigned_notes(client, auth, "member2")) >= 1     # 他人不受影响


def test_reenabling_restores_notification(client, auth, make_requirement, data):
    """member 静音后再开启 → 后续指派恢复产生通知。"""
    headers = auth("member")
    client.patch("/api/me/notification-preferences",
                 json={"preferences": {"assigned": False}}, headers=headers)
    make_requirement(assignee=("user", data["member_id"]))
    assert _assigned_notes(client, auth, "member") == []
    # 重新开启。
    client.patch("/api/me/notification-preferences",
                 json={"preferences": {"assigned": True}}, headers=headers)
    make_requirement(assignee=("user", data["member_id"]))
    assert len(_assigned_notes(client, auth, "member")) >= 1
