"""账号级登录锁定 + 用户序列化/筛选
（login-hardening-and-audit-console §7.2 C 组 27–48/42′、D 组 49–53）。

**本组的前置条件（评审 P1-2）**：限流键是 `ip:username`，`TestConfig.LOGIN_MAX_ATTEMPTS = 3`，
所以同一用户名的**第 4 次**登录请求起恒 429，压根走不到 note_failed_login 与 B-4 第 4 步。
凡是需要「超过 3 次尝试」或「锁定后再登录」的用例，一律先 `ratelimit.reset()` 复位**内存
限流**——账号侧的 failed_login_count / locked_until 落在库里不受影响，这正是账号级锁定的理由。
"""
import logging
from contextlib import contextmanager
from datetime import timedelta

from extensions import db, utcnow
from models.activity import Activity
from models.notification import Notification
from models.user import User
from services import login_guard, ratelimit


CRED = {"admin": "admin123", "pm": "pm123", "member": "member123"}


def _login(client, username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def _fail(client, username, times=1):
    """打 `times` 次错口令登录，每次之间**不**复位限流（调用方按需 reset）。"""
    last = None
    for _ in range(times):
        last = _login(client, username, "definitely-wrong")
    return last


def _fail_with_reset(client, username, times):
    """打 `times` 次错口令登录，每次**先复位 IP 桶**（测账号侧连续失败，绕开 IP 限流）。"""
    last = None
    for _ in range(times):
        ratelimit.reset()
        last = _login(client, username, "definitely-wrong")
    return last


def _get(app, uid):
    return db.session.get(User, uid)


@contextmanager
def captured_warnings():
    """收集 `app` logger 上的 WARNING 文案（不能用 caplog，见 test_password_policy 同名 helper）。"""
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


# ————————————————————— 27–28 策略钳位 —————————————————————

def test_lock_policy_clamps_all_three_knobs(app):
    app.config["LOGIN_LOCK_THRESHOLD"] = 0
    app.config["LOGIN_LOCK_MINUTES"] = 0
    app.config["LOGIN_LOCK_NOTIFY_COOLDOWN_MINUTES"] = -1
    with app.app_context():
        assert login_guard.lock_policy() == {"threshold": 3, "minutes": 1, "notify_cooldown": 0}

    app.config["LOGIN_LOCK_THRESHOLD"] = 999
    app.config["LOGIN_LOCK_MINUTES"] = 99999
    app.config["LOGIN_LOCK_NOTIFY_COOLDOWN_MINUTES"] = 99999
    with app.app_context():
        assert login_guard.lock_policy() == {
            "threshold": 100, "minutes": 1440, "notify_cooldown": 10080}


def test_lock_policy_dirty_value_warns_with_login_guard_prefix(app):
    """评审 P1-4：抽 config_knobs 时若忘了传 source，warning 前缀会是 passwords 而非 login_guard。"""
    app.config["LOGIN_LOCK_THRESHOLD"] = "abc"
    with captured_warnings() as warnings, app.app_context():
        policy = login_guard.lock_policy()
    assert policy["threshold"] == 8              # 回落默认
    assert any("login_guard: unparsable LOGIN_LOCK_THRESHOLD" in m for m in warnings)
    assert not any("passwords: unparsable LOGIN_LOCK_THRESHOLD" in m for m in warnings)


# ————————————————————— 29–30 连续失败与触发 —————————————————————

def test_below_threshold_not_locked(client, app, data):
    _fail_with_reset(client, "member", 2)          # threshold=3，错 2 次
    with app.app_context():
        user = _get(app, data["member_id"])
        assert not user.is_locked()
        assert user.failed_login_count == 2


def test_threshold_failure_returns_401_but_sets_lock(client, app, data):
    """第 3 次失败仍返回 401（锁定检查排在口令校验之后），但 locked_until 已被置。"""
    for i in range(3):
        ratelimit.reset()
        r = _login(client, "member", "wrong")
        assert r.status_code == 401
    with app.app_context():
        user = _get(app, data["member_id"])
        assert user.locked_until is not None
        assert user.is_locked()


# ————————————————————— 31–34 锁定后的 HTTP 行为（必须先 reset）—————————————————————

def test_correct_password_when_locked_returns_403(client, app, data):
    _fail(client, "member", 3)                     # 触发锁定 + 填满 IP 桶
    ratelimit.reset()                              # 不 reset 就是 429，测不到本分支（P1-2）
    r = _login(client, "member", "member123")
    assert r.status_code == 403
    assert r.get_json()["error"] == "account is temporarily locked"


def test_locked_403_carries_retry_after_seconds(client, app, data):
    _fail(client, "member", 3)
    ratelimit.reset()
    r = _login(client, "member", "member123")
    retry = r.get_json()["detail"]["retry_after_seconds"]
    assert 0 < retry <= 15 * 60


def test_wrong_password_when_locked_returns_401(client, app, data):
    """R-1：锁定态下错口令 → 仍 401，不是 403（403 只在口令对时才可能出现）。"""
    _fail(client, "member", 3)
    ratelimit.reset()
    r = _login(client, "member", "still-wrong")
    assert r.status_code == 401
    assert r.get_json()["error"] == "invalid username or password"


def test_locked_wrong_password_identical_to_unknown_user(client, app, data):
    """R-1：锁定 + 错口令 与 不存在的用户名 + 任意口令，响应体逐字节相同。"""
    _fail(client, "member", 3)
    ratelimit.reset()
    locked = _login(client, "member", "still-wrong")
    ghost = _login(client, "no-such-user-ever", "whatever")
    assert locked.status_code == ghost.status_code == 401
    assert locked.get_json() == ghost.get_json()


# ————————————————————— 35 写放大短路 —————————————————————

def test_locked_period_does_not_amplify_writes(client, app, data):
    """R-3：锁定期内再打 5 次（每次 reset）→ activities 不增、failed_login_count 不变。"""
    _fail(client, "member", 3)                      # 已锁定，写了 1 条 account_locked
    with app.app_context():
        before = Activity.query.filter_by(entity_type="user",
                                          entity_id=data["member_id"]).count()
        count_before = _get(app, data["member_id"]).failed_login_count
    _fail_with_reset(client, "member", 5)
    with app.app_context():
        after = Activity.query.filter_by(entity_type="user",
                                         entity_id=data["member_id"]).count()
        count_after = _get(app, data["member_id"]).failed_login_count
    assert after == before
    assert count_after == count_before == 0         # 触发锁定时已归零


# ————————————————————— 36–38 自然到期 / 连续判据 / 成功清零 —————————————————————

def test_expired_lock_allows_login_without_any_job(client, app, data):
    with app.app_context():
        user = _get(app, data["member_id"])
        user.locked_until = utcnow() - timedelta(minutes=1)     # 手工改到过去
        user.failed_login_count = 0
        db.session.commit()
    r = _login(client, "member", "member123")
    assert r.status_code == 200


def test_counter_resets_on_success_between_failures(client, app, data):
    """R-4：错 2 次 → 成功一次 → 再错 2 次 → 未锁定（判据是连续失败）。"""
    _fail_with_reset(client, "member", 2)
    ratelimit.reset()
    assert _login(client, "member", "member123").status_code == 200
    _fail_with_reset(client, "member", 2)
    with app.app_context():
        assert not _get(app, data["member_id"]).is_locked()


def test_successful_login_writes_last_login_and_clears(client, app, data):
    _fail_with_reset(client, "member", 2)
    ratelimit.reset()
    assert _login(client, "member", "member123").status_code == 200
    with app.app_context():
        user = _get(app, data["member_id"])
        assert user.last_login_at is not None
        assert user.failed_login_count == 0
        assert user.locked_until is None


# ————————————————————— 39–40 根管理员豁免（一正一反）—————————————————————

def test_root_admin_never_locks(client, app, root_admin):
    """R-2：根管理员连错 20 次（每次 reset）→ 从不锁定、计数恒 0。"""
    _fail_with_reset(client, "admin", 20)
    with app.app_context():
        user = _get(app, root_admin)
        assert user.locked_until is None
        assert user.failed_login_count == 0


def test_root_admin_still_hits_ip_ratelimit(client, app, root_admin):
    """40：根管理员连错超过 IP 阈值（**不 reset**）→ 仍 429（IP 限流对它照常生效）。"""
    _fail(client, "admin", 3)                       # 填满 IP 桶
    r = _login(client, "admin", "definitely-wrong")
    assert r.status_code == 429


# ————————————————————— 41–43 审计 / 通知 / 冷却 —————————————————————

def test_lock_writes_exactly_one_system_audit(client, app, data):
    _fail(client, "member", 3)
    with app.app_context():
        rows = Activity.query.filter_by(entity_type="user", entity_id=data["member_id"],
                                        action="account_locked").all()
        assert len(rows) == 1
        assert rows[0].actor_type == "system"
        assert rows[0].actor_id is None


def test_lock_notifies_active_admins_only(client, app, data):
    # 追加一个停用的 admin；它不该收到通知。
    with app.app_context():
        dead = User(username="deadadmin", role="admin", is_active=False,
                    display_name="Dead")
        dead.set_password("Aragon2026")
        db.session.add(dead)
        db.session.commit()
        dead_id, admin_id = dead.id, data["admin_id"]
    _fail(client, "member", 3)
    with app.app_context():
        got_admin = Notification.query.filter_by(user_id=admin_id,
                                                 type="account_locked").count()
        got_dead = Notification.query.filter_by(user_id=dead_id,
                                                type="account_locked").count()
        assert got_admin == 1
        assert got_dead == 0


def test_notify_cooldown_suppresses_second_notification(client, app, data):
    """42′：二次锁定 → activities +1、notifications +0（默认 24h 冷却）；冷却置 0 后两者都 +1。"""
    _fail(client, "member", 3)                      # 第一次锁定
    with app.app_context():
        acts1 = Activity.query.filter_by(entity_type="user", entity_id=data["member_id"],
                                         action="account_locked").count()
        notis1 = Notification.query.filter_by(type="account_locked").count()
        # 手工解锁到过去，模拟自然到期后再被锁
        user = _get(app, data["member_id"])
        user.locked_until = utcnow() - timedelta(minutes=1)
        user.failed_login_count = 0
        db.session.commit()
    _fail_with_reset(client, "member", 3)           # 第二次锁定（冷却窗口内）
    with app.app_context():
        acts2 = Activity.query.filter_by(entity_type="user", entity_id=data["member_id"],
                                         action="account_locked").count()
        notis2 = Notification.query.filter_by(type="account_locked").count()
    assert acts2 == acts1 + 1                        # 审计不冷却
    assert notis2 == notis1                          # 通知被冷却压掉

    # 冷却置 0 重来一轮 → 两者都 +1。
    app.config["LOGIN_LOCK_NOTIFY_COOLDOWN_MINUTES"] = 0
    with app.app_context():
        user = _get(app, data["member_id"])
        user.locked_until = utcnow() - timedelta(minutes=1)
        user.failed_login_count = 0
        db.session.commit()
    _fail_with_reset(client, "member", 3)
    with app.app_context():
        acts3 = Activity.query.filter_by(entity_type="user", entity_id=data["member_id"],
                                         action="account_locked").count()
        notis3 = Notification.query.filter_by(type="account_locked").count()
    assert acts3 == acts2 + 1
    assert notis3 == notis2 + 1


def test_locked_admin_receives_own_notification(client, app, data):
    """43：被锁的人自己是 admin 时也收到那条通知（actor=system，「不给自己发」不触发）。"""
    with app.app_context():
        victim = User(username="adminvictim", role="admin", is_active=True,
                      display_name="Victim")
        victim.set_password("Aragon2026")
        db.session.add(victim)
        db.session.commit()
        victim_id = victim.id
    _fail(client, "adminvictim", 3)
    with app.app_context():
        assert Notification.query.filter_by(user_id=victim_id,
                                            type="account_locked").count() == 1


# ————————————————————— 44 停用账号顺序 —————————————————————

def test_disabled_account_wrong_password_is_401(client, app, disabled_user):
    """停用账号 + 错口令 → 401（口令校验先于停用检查，顺序不变）。"""
    r = _login(client, "member", "definitely-wrong")
    assert r.status_code == 401


# ————————————————————— 45–48 解锁端点 —————————————————————

def _lock_member(client):
    _fail(client, "member", 3)
    ratelimit.reset()


def test_unlock_by_admin_clears_and_audits(client, app, data, auth):
    _lock_member(client)
    r = client.post(f"/api/users/{data['member_id']}/unlock", headers=auth("admin"))
    assert r.status_code == 200
    body = r.get_json()
    assert body["unlocked"] is True
    assert body["user"]["is_locked"] is False
    with app.app_context():
        user = _get(app, data["member_id"])
        assert user.locked_until is None
        rows = Activity.query.filter_by(entity_type="user", entity_id=data["member_id"],
                                        action="account_unlocked").all()
        assert len(rows) == 1


def test_unlock_unlocked_account_is_noop_without_audit(client, app, data, auth):
    r = client.post(f"/api/users/{data['member_id']}/unlock", headers=auth("admin"))
    assert r.status_code == 200
    assert r.get_json()["unlocked"] is False
    with app.app_context():
        assert Activity.query.filter_by(entity_type="user", entity_id=data["member_id"],
                                        action="account_unlocked").count() == 0


def test_unlock_root_admin_is_noop(client, app, root_admin, auth):
    """47：根管理员结构上不可能被锁 → unlock 返回 unlocked:false，无 409 分支。"""
    r = client.post(f"/api/users/{root_admin}/unlock", headers=auth("admin"))
    assert r.status_code == 200
    assert r.get_json()["unlocked"] is False


def test_unlock_permission_and_404(client, app, data, auth):
    assert client.post(f"/api/users/{data['member_id']}/unlock",
                       headers=auth("member")).status_code == 403
    assert client.post("/api/users/999999/unlock", headers=auth("admin")).status_code == 404


# ————————————————————— D. 用户序列化与筛选 49–53 —————————————————————

def test_to_dict_has_lock_keys_but_not_failed_count(client, app, data):
    with app.app_context():
        body = _get(app, data["member_id"]).to_dict()
    assert "last_login_at" in body
    assert "locked_until" in body
    assert "is_locked" in body
    assert "failed_login_count" not in body


def test_summary_adds_no_new_key(client, app, data):
    with app.app_context():
        keys = set(_get(app, data["member_id"]).summary().keys())
    assert keys == {"type", "id", "name", "avatar_color", "is_active"}


def test_is_locked_server_side_with_past_locked_until(client, app, data):
    with app.app_context():
        user = _get(app, data["member_id"])
        user.locked_until = utcnow() - timedelta(minutes=1)
        db.session.commit()
        body = user.to_dict()
    assert body["is_locked"] is False
    assert body["locked_until"] is None             # 过期后回传 null


def test_locked_filter_partitions_users(client, app, data, auth):
    with app.app_context():
        user = _get(app, data["member_id"])
        user.locked_until = utcnow() + timedelta(minutes=10)
        db.session.commit()
    locked = client.get("/api/users?locked=true", headers=auth("admin")).get_json()
    unlocked = client.get("/api/users?locked=false", headers=auth("admin")).get_json()
    locked_ids = {u["id"] for u in locked}
    unlocked_ids = {u["id"] for u in unlocked}
    assert data["member_id"] in locked_ids
    assert data["member_id"] not in unlocked_ids
    assert data["admin_id"] in unlocked_ids         # locked_until IS NULL 归入未锁定


def test_locked_filter_rejects_garbage(client, app, auth):
    r = client.get("/api/users?locked=ture", headers=auth("admin"))
    assert r.status_code == 400
