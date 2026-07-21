"""站点级注册设置（self-service-registration §8.2 用例 31–39、41）。

**与既有 `tests/test_settings.py` 的分工**（spec 评审 P2-1）：那个文件测的是
account-settings 轮的**成员自助**设置——`/api/me/profile`、`/api/me/password`、
`/api/me/notification-preferences`，实现在 `routes/me.py`。本文件测的是**站点级**设置
——`/api/settings/registration`，实现在 `routes/settings.py`（蓝图对象 `admin_settings_bp`），
三个端点全部 `@require_root()`。两者名字近似而语义正交，加用例前先确认落在对的文件里。
"""
import pytest

from extensions import db
from models.app_setting import AppSetting
from services import app_settings


def _get(client, headers):
    return client.get("/api/settings/registration", headers=headers)


# ————————————————————— 默认回退 —————————————————————

def test_defaults_when_no_row(app):
    with app.app_context():
        assert AppSetting.query.count() == 0

        assert app_settings.get_registration_settings() == {
            "enabled": True, "invite_code": "aragon", "default_role": "member",
        }


def test_corrupt_value_falls_back_to_default(app):
    """手工改库写了 `enabled="yes"` 之类的脏值 → 回落配置默认，**不抛异常**。

    注册开关解析失败就让整个登录体系 500，是把小故障放大成全站故障（§5.3）。
    """
    with app.app_context():
        db.session.add(AppSetting(key=app_settings.KEY_REGISTRATION_ENABLED,
                                  value="definitely-not-a-bool"))
        db.session.add(AppSetting(key=app_settings.KEY_REGISTRATION_DEFAULT_ROLE,
                                  value="admin"))
        db.session.commit()

        settings = app_settings.get_registration_settings()
        assert settings["enabled"] is True
        assert settings["default_role"] == "member"


def test_config_default_role_cannot_escape_whitelist(app):
    """【R-16】空表 + `REGISTRATION_DEFAULT_ROLE=admin` → 仍回落 member。"""
    app.config["REGISTRATION_DEFAULT_ROLE"] = "admin"

    with app.app_context():
        assert app_settings.get_registration_settings()["default_role"] == "member"


# ————————————————————— 读写端点 —————————————————————

def test_get_returns_full_shape(client, root_auth):
    body = _get(client, root_auth).get_json()

    assert body["invite_code"] == "aragon"
    assert body["allowed_default_roles"] == ["member", "pm"]
    assert body["updated_at"] is None and body["updated_by"] is None


def test_patch_persists_and_reads_back(client, root_auth, root_admin):
    r = client.patch("/api/settings/registration",
                     json={"enabled": False, "invite_code": "ARAGON-2026",
                           "default_role": "pm"}, headers=root_auth)

    assert r.status_code == 200
    body = r.get_json()
    assert (body["enabled"], body["invite_code"], body["default_role"]) == \
        (False, "ARAGON-2026", "pm")
    assert body["updated_by"]["id"] == root_admin
    assert _get(client, root_auth).get_json()["invite_code"] == "ARAGON-2026"


def test_patch_is_partial(client, root_auth):
    client.patch("/api/settings/registration", json={"invite_code": "FIRST-CODE"},
                 headers=root_auth)

    client.patch("/api/settings/registration", json={"default_role": "pm"},
                 headers=root_auth)

    body = _get(client, root_auth).get_json()
    assert body["invite_code"] == "FIRST-CODE"      # 未在第二次请求里提及 → 不受影响
    assert body["default_role"] == "pm"
    assert body["enabled"] is True


def test_patch_with_no_recognized_field_returns_400(client, root_auth):
    """杜绝「静默成功」：管理员以为改了、其实什么都没发生。"""
    r = client.patch("/api/settings/registration", json={"nonsense": 1},
                     headers=root_auth)

    assert r.status_code == 400
    assert r.get_json()["error"] == "no updatable field"


@pytest.mark.parametrize("code", ["abc", "x" * 65, "has space"])
def test_rejects_invalid_invite_code(client, root_auth, code):
    """依次是：太短 / 太长 / 含空白。邀请码要能被口述与手抄。"""
    r = client.patch("/api/settings/registration", json={"invite_code": code},
                     headers=root_auth)

    assert r.status_code == 400, r.get_json()
    assert r.get_json()["detail"]["field"] == "invite_code"


def test_rejects_admin_as_default_role(client, root_auth):
    """自助注册**永远**不能产出 admin：白名单只有 member/pm。"""
    r = client.patch("/api/settings/registration", json={"default_role": "admin"},
                     headers=root_auth)

    assert r.status_code == 400
    assert r.get_json()["detail"]["field"] == "default_role"


def test_rejects_non_boolean_enabled(client, root_auth):
    r = client.patch("/api/settings/registration", json={"enabled": "yes"},
                     headers=root_auth)

    assert r.status_code == 400


# ————————————————————— rotate —————————————————————

def test_rotate_generates_new_code_and_invalidates_old(client, root_auth):
    r = client.post("/api/settings/registration/rotate-code", headers=root_auth)

    assert r.status_code == 200
    new_code = r.get_json()["invite_code"]
    assert new_code != "aragon"
    assert app_settings.INVITE_CODE_MIN <= len(new_code) <= app_settings.INVITE_CODE_MAX

    stale = client.post("/api/auth/signup",
                        json={"username": "late", "password": "Aragon2026",
                              "invite_code": "aragon"})
    fresh = client.post("/api/auth/signup",
                        json={"username": "late", "password": "Aragon2026",
                              "invite_code": new_code})
    assert stale.status_code == 403                # 旧码立即失效，无宽限期
    assert fresh.status_code == 201


def test_generated_code_uses_unambiguous_alphabet():
    """去掉 0/O/1/l/I：邀请码要能被人念给同事听。"""
    code = app_settings.generate_invite_code()

    assert not set(code) & set("0O1lI")


# ————————————————————— 门禁 —————————————————————

def test_requires_root_not_just_admin(client, auth):
    """普通 admin 调三个端点全 403——「看得见但一按就 403」的挫败感由前端不渲染卡片规避。"""
    headers = auth("admin")

    assert _get(client, headers).status_code == 403
    assert client.patch("/api/settings/registration", json={"enabled": True},
                        headers=headers).status_code == 403
    assert client.post("/api/settings/registration/rotate-code",
                       headers=headers).status_code == 403


def test_requires_authentication(client):
    assert _get(client, {}).status_code == 401


def test_root_admin_passes_the_gate(client, root_auth):
    assert _get(client, root_auth).status_code == 200
