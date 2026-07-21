"""全站统一口令策略（account-security-and-governance §8.2 用例 1–14′）。

覆盖：四条写入路径接同一份策略、策略旋钮的钳位与脏值回落、策略下发、
以及一次性口令「构造上必然满足策略」这条不变量。

与 `tests/test_account_governance.py` 的分工：那边测**标记与闸门**（口令被设置之后
会发生什么），这边测**规则本身**（什么样的口令能被设置）。
"""
import logging
from contextlib import contextmanager

import pytest

from services import passwords

SIGNUP = {"username": "linlei", "password": "Aragon2026", "invite_code": "aragon"}


def _signup(client, **overrides):
    return client.post("/api/auth/signup", json={**SIGNUP, **overrides})


@contextmanager
def captured_warnings():
    """收集 `app` logger 上的 WARNING 文案。

    **不能用 pytest 的 caplog**：`observability.init_observability` 会把 root 上的
    handler 整个换掉（见 tests/test_root_admin.py 的同名 helper）。
    """
    records = []

    class _Collect(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = _Collect(level=logging.WARNING)
    logger = logging.getLogger("app")
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)


# ————————————————————— 1–3 自助注册（既有水位，回归钉）—————————————————————

def test_signup_rejects_7_char_password(client):
    r = _signup(client, password="Pw12345")

    assert r.status_code == 400
    assert r.get_json()["detail"]["field"] == "password"


def test_signup_rejects_single_class_password(client):
    r = _signup(client, password="abcdefghij")

    assert r.status_code == 400
    assert r.get_json()["detail"]["field"] == "password"


def test_signup_rejects_password_equal_to_username(client):
    r = _signup(client, username="Aragon2026", password="Aragon2026")

    assert r.status_code == 400
    assert r.get_json()["detail"]["field"] == "password"


# ————————————————————— 4–6 管理员路径（本轮破坏性变更）—————————————————————

def test_admin_create_rejects_weak_password(client, auth):
    """**本轮破坏性变更的正面证据**：一个字符的口令此前 201，现在 400。"""
    r = client.post("/api/users", json={"username": "weakling", "password": "p"},
                    headers=auth("admin"))

    assert r.status_code == 400
    assert r.get_json()["detail"]["field"] == "password"


def test_admin_create_accepts_strong_password(client, auth):
    r = client.post("/api/users", json={"username": "strongman", "password": "Aragon2026"},
                    headers=auth("admin"))

    assert r.status_code == 201, r.get_json()
    assert r.get_json()["temporary_password"] is None


def test_admin_reset_via_patch_rejects_weak_password(client, auth, data):
    r = client.patch(f"/api/users/{data['member_id']}", json={"password": "p"},
                     headers=auth("admin"))

    assert r.status_code == 400
    assert r.get_json()["detail"]["field"] == "password"


# ————————————————————— 7–9 自助改密（判定顺序是契约的一部分）—————————————————————

def test_self_change_rejects_weak_password(client, auth):
    r = client.post("/api/me/password",
                    json={"current_password": "member123", "new_password": "abc"},
                    headers=auth("member"))

    assert r.status_code == 400
    assert r.get_json()["detail"]["field"] == "password"


def test_self_change_still_rejects_wrong_current_password_first(client, auth):
    """旧口令判据必须**排在**策略之前：先说「新口令太弱」等于给猜口令的人反馈。"""
    r = client.post("/api/me/password",
                    json={"current_password": "wrong", "new_password": "abc"},
                    headers=auth("member"))

    assert r.status_code == 400
    assert r.get_json()["error"] == "current password is incorrect"


def test_self_change_still_rejects_same_as_current(client, auth):
    r = client.post("/api/me/password",
                    json={"current_password": "member123", "new_password": "member123"},
                    headers=auth("member"))

    assert r.status_code == 400
    assert r.get_json()["error"] == "new password must differ from current"


# ————————————————————— 10–12 旋钮的物理止挡 —————————————————————

def test_policy_clamps_absurd_min_length(app):
    """`=999` 会让所有人（含根管理员）都改不了密码，且产品内无恢复路径。"""
    app.config["PASSWORD_MIN_LENGTH"] = 999

    assert passwords.policy()["min_length"] == passwords.PASSWORD_MAX_LENGTH


def test_policy_clamps_zero_min_length(app):
    """`=0` 会让策略静默变成「没有策略」。"""
    app.config["PASSWORD_MIN_LENGTH"] = 0

    assert passwords.policy()["min_length"] == 6


def test_policy_falls_back_on_garbage_value(app):
    """脏值回落默认 + warning，**绝不抛异常**：配置写错了不该让登录体系 500。"""
    app.config["PASSWORD_MIN_LENGTH"] = "abc"

    with captured_warnings() as warnings:
        assert passwords.policy()["min_length"] == passwords.DEFAULT_MIN_LENGTH

    assert any("PASSWORD_MIN_LENGTH" in w for w in warnings), warnings


# ————————————————————— 13 策略下发 —————————————————————

def test_registration_meta_exposes_policy(client, app):
    r = client.get("/api/auth/registration-meta")

    assert r.status_code == 200
    body = r.get_json()
    policy = passwords.policy()
    assert body["password_min_length"] == policy["min_length"]
    assert body["password_max_length"] == policy["max_length"]
    assert body["password_min_char_classes"] == policy["min_char_classes"]


# ————————————————————— 14 / 14′ 一次性口令的构造保证 —————————————————————

def test_temporary_password_always_satisfies_policy(app):
    for _ in range(200):
        passwords.validate_password(passwords.generate_temporary_password())


@pytest.mark.parametrize("min_length,min_classes", [(40, 4), (128, 4)])
def test_temporary_password_satisfies_raised_policy(app, min_length, min_classes):
    """【评审 P1-1 的机器执行者】把两个旋钮一起调高，生成器必须跟着走。

    写成 `[max(min_length, 8), 32]` 的钳位在这个配置下是**空区间**，会生成一个
    32 位 3 类的口令——即一个违反自己策略的口令。本条必红。
    """
    app.config["PASSWORD_MIN_LENGTH"] = min_length
    app.config["PASSWORD_MIN_CHAR_CLASSES"] = min_classes

    for _ in range(200):
        candidate = passwords.generate_temporary_password()
        assert len(candidate) >= passwords.policy()["min_length"]
        passwords.validate_password(candidate)
