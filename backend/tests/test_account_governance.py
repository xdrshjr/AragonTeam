"""一次性口令 + 强制改密闸门 + 账号治理审计 + 保留名表
（account-security-and-governance §8.2 用例 15–56）。

分五组：
1. 一次性口令与 `must_change_password` 标记（15–30″）；
2. 重置端点 `POST /api/users/:id/reset-password`（31–38′，含 P0-1 的复现用例 35′）；
3. 治理审计与它的两处外溢修复（39–46）；
4. 保留名表与 purge 引用计数（47–50）；
5. 两条建号路由合并后的契约（51–56）。

与 `tests/test_password_policy.py` 的分工：那边测**规则本身**（什么样的口令能被设置），
这边测**口令被设置之后会发生什么**。
"""
import pytest

from extensions import db
from models.activity import Activity
from models.user import User
from services import audit
from services.auth_helpers import _PASSWORD_GATE_EXEMPT
from tools import purge_demo_data as purge

SIGNUP = {"username": "linlei", "password": "Aragon2026", "invite_code": "aragon"}


def _create(client, auth, **payload):
    return client.post("/api/users", json=payload, headers=auth("admin"))


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def flagged(client, auth):
    """建一个带 must_change_password 标记的账号，返回 `{id, username, password, headers}`。"""
    created = _create(client, auth, username="newbie")
    assert created.status_code == 201, created.get_json()
    body = created.get_json()
    login = client.post("/api/auth/login",
                        json={"username": "newbie", "password": body["temporary_password"]})
    assert login.status_code == 200, login.get_json()
    return {
        "id": body["id"],
        "username": "newbie",
        "password": body["temporary_password"],
        "headers": _bearer(login.get_json()["token"]),
    }


# ————————————————— 15–19 一次性口令 —————————————————

def test_create_without_password_returns_temporary_password(client, auth):
    r = _create(client, auth, username="nopass")

    assert r.status_code == 201, r.get_json()
    assert isinstance(r.get_json()["temporary_password"], str)
    assert r.get_json()["temporary_password"]


def test_create_with_password_returns_null_temporary_password(client, auth):
    r = _create(client, auth, username="haspass", password="Aragon2026")

    assert r.status_code == 201
    assert r.get_json()["temporary_password"] is None


def test_created_user_must_change_password_is_true(client, auth):
    r = _create(client, auth, username="mustchange")

    assert r.get_json()["must_change_password"] is True


def test_signup_user_must_change_password_is_false(client):
    """口令是本人当场设的——自助注册的人不欠任何人一次改密。"""
    r = client.post("/api/auth/signup", json=SIGNUP)

    assert r.status_code == 201, r.get_json()
    assert r.get_json()["user"]["must_change_password"] is False


def test_temporary_password_can_log_in(client, auth, flagged):
    assert client.post("/api/auth/login",
                       json={"username": flagged["username"],
                             "password": flagged["password"]}).status_code == 200


# ————————————————— 20–30″ 强制改密闸门 —————————————————

def test_gate_blocks_normal_endpoint_with_403(client, flagged):
    assert client.get("/api/stats", headers=flagged["headers"]).status_code == 403


def test_gate_body_has_stable_error_string(client, flagged):
    r = client.get("/api/stats", headers=flagged["headers"])

    assert r.get_json()["error"] == "password change required"
    assert r.get_json()["detail"]["endpoint"] == "POST /api/me/password"


def test_gate_body_has_no_allowed_key(client, flagged):
    """前端看板拖拽以 `err.allowed` 是否存在分流错误，闸门不得误伤。"""
    assert "allowed" not in client.get("/api/stats",
                                       headers=flagged["headers"]).get_json()["detail"]


def test_gate_allows_get_auth_me(client, flagged):
    """漏掉这条豁免 = 前端读不回登录态 = 白屏死循环。"""
    r = client.get("/api/auth/me", headers=flagged["headers"])

    assert r.status_code == 200
    assert r.get_json()["user"]["must_change_password"] is True


def test_gate_allows_post_me_password(client, flagged):
    r = client.post("/api/me/password",
                    json={"current_password": flagged["password"],
                          "new_password": "Aragon2026"},
                    headers=flagged["headers"])

    assert r.status_code == 200, r.get_json()


def test_gate_never_blocks_options(client, flagged):
    """CORS 预检被拦 = 全站跨域当场瘫痪，而后端日志里只有一串 403。"""
    r = client.options("/api/stats", headers=flagged["headers"])

    assert r.status_code != 403


def test_gate_never_blocks_login_and_signup(client, flagged):
    login = client.post("/api/auth/login",
                        json={"username": flagged["username"], "password": flagged["password"]})
    signup = client.post("/api/auth/signup", json=SIGNUP)

    assert login.status_code == 200
    assert signup.status_code == 201


def test_changing_password_clears_the_flag_and_unblocks(client, flagged):
    changed = client.post("/api/me/password",
                          json={"current_password": flagged["password"],
                                "new_password": "Aragon2026"},
                          headers=flagged["headers"])
    assert changed.status_code == 200

    assert client.get("/api/stats", headers=flagged["headers"]).status_code == 200
    assert client.get("/api/auth/me", headers=flagged["headers"])\
        .get_json()["user"]["must_change_password"] is False


def test_disabled_user_still_gets_401_not_500(client, auth, flagged):
    """【R-5】已吊销 token 在闸门里必须放行给端点的 @jwt_required() 去产出既有 401。"""
    client.patch(f"/api/users/{flagged['id']}", json={"is_active": False},
                 headers=auth("admin"))

    r = client.get("/api/stats", headers=flagged["headers"])

    assert r.status_code == 401
    assert r.status_code != 500


def test_gate_off_by_config_lets_request_through(client, app, flagged):
    """止血阀只关硬拦，不关标记。"""
    app.config["FORCE_PASSWORD_CHANGE"] = False

    r = client.get("/api/stats", headers=flagged["headers"])

    assert r.status_code == 200
    assert client.get("/api/auth/me", headers=flagged["headers"])\
        .get_json()["user"]["must_change_password"] is True


def test_root_admin_is_never_flagged(app, root_admin):
    """破窗路径必须最短：给它置位等于让唯一的恢复入口一进来就被闸门挡住。"""
    assert db.session.get(User, root_admin).must_change_password is False


def test_fixture_users_are_not_flagged(app, data):
    """【评审 P0-3】§8.1.2「闸门不翻转任何既有用例」这个结论依赖于 fixture 走模型构造。

    哪天有人为了省事把它改成走 `POST /api/users`，本条会在那一刻红，
    而不是让几百条用例成片 403、再由人去猜发生了什么。
    """
    ids = [data["admin_id"], data["pm_id"], data["member_id"], data["member2_id"]]

    assert all(db.session.get(User, uid).must_change_password is False for uid in ids)


def test_self_service_password_change_via_patch_does_not_flag(client, auth, app, data):
    """【评审 P1-7】用管理台给**自己**改密不是「别人替你设的口令」，不该被自锁。"""
    admin_id = data["admin_id"]
    r = client.patch(f"/api/users/{admin_id}", json={"password": "Aragon2026"},
                     headers=auth("admin"))
    assert r.status_code == 200, r.get_json()

    assert db.session.get(User, admin_id).must_change_password is False
    relogin = client.post("/api/auth/login",
                          json={"username": "admin", "password": "Aragon2026"})
    assert client.get("/api/stats",
                      headers=_bearer(relogin.get_json()["token"])).status_code == 200


# ————————————————— 31–38′ 重置端点 —————————————————

def test_reset_password_generates_temporary_password(client, auth, login, data):
    r = client.post(f"/api/users/{data['member_id']}/reset-password", json={},
                    headers=auth("admin"))

    assert r.status_code == 200, r.get_json()
    temporary = r.get_json()["temporary_password"]
    assert temporary
    assert login("member", temporary).status_code == 200


def test_reset_password_accepts_explicit_password(client, auth, login, data):
    r = client.post(f"/api/users/{data['member_id']}/reset-password",
                    json={"password": "Aragon2026"}, headers=auth("admin"))

    assert r.status_code == 200
    assert r.get_json()["temporary_password"] is None
    assert login("member", "Aragon2026").status_code == 200


def test_reset_password_rejects_weak_explicit_password(client, auth, data):
    r = client.post(f"/api/users/{data['member_id']}/reset-password",
                    json={"password": "p"}, headers=auth("admin"))

    assert r.status_code == 400
    assert r.get_json()["detail"]["field"] == "password"


def test_reset_password_sets_must_change_flag(client, auth, data):
    client.post(f"/api/users/{data['member_id']}/reset-password", json={},
                headers=auth("admin"))

    assert db.session.get(User, data["member_id"]).must_change_password is True


def test_reset_password_on_root_conflicts_409_with_explicit_password(
        client, app, auth, root_admin):
    before = db.session.get(User, root_admin).password_hash

    r = client.post(f"/api/users/{root_admin}/reset-password",
                    json={"password": "Aragon2026"}, headers=_second_admin_headers(client, app))

    assert r.status_code == 409
    assert r.get_json()["error"] == "root administrator is protected"
    assert db.session.get(User, root_admin).password_hash == before


def test_reset_password_on_root_conflicts_409_with_empty_body(client, app, root_admin):
    """【评审 P0-1，本轮最重要的一条】body 为 `{}` —— 本端点的**主用法**。

    复用 `_reject_root_mutation` 的写法在这条上必红：那个函数的口令分支挂在
    `data.get("password")` 上，空 body 恒放行 → 任意 admin 拿到根管理员的一次性口令 →
    破窗账号被完全接管。断言必须同时覆盖「409」**与**「password_hash 逐字节未变」，
    只断状态码挡不住「先改了库再返 409」这种半吊子实现。
    """
    before = db.session.get(User, root_admin).password_hash

    r = client.post(f"/api/users/{root_admin}/reset-password", json={},
                    headers=_second_admin_headers(client, app))

    assert r.status_code == 409
    assert r.get_json()["error"] == "root administrator is protected"
    assert db.session.get(User, root_admin).password_hash == before


def test_reset_password_404_for_unknown_user(client, auth):
    assert client.post("/api/users/999999/reset-password", json={},
                       headers=auth("admin")).status_code == 404


@pytest.mark.parametrize("role", ["pm", "member"])
def test_reset_password_forbidden_for_pm_and_member(client, auth, data, role):
    assert client.post(f"/api/users/{data['member_id']}/reset-password", json={},
                       headers=auth(role)).status_code == 403


def test_old_password_stops_working_after_reset(client, auth, login, data):
    client.post(f"/api/users/{data['member_id']}/reset-password", json={},
                headers=auth("admin"))

    assert login("member", "member123").status_code == 401


def test_root_can_reset_own_password_and_is_not_flagged(client, auth, root_admin):
    """根管理员对自己调新端点 → 200，且 `must_change_password` 恒 False（§2.2 B-2 末行）。"""
    r = client.post(f"/api/users/{root_admin}/reset-password", json={},
                    headers=auth("admin"))

    assert r.status_code == 200, r.get_json()
    assert db.session.get(User, root_admin).must_change_password is False


def _second_admin_headers(client, app):
    """造一个**不是**根管理员的 admin 并返回它的 Authorization 头。"""
    user = User(username="admin2", role="admin", display_name="Second",
                avatar_color="#3B6EA5")
    user.set_password("Aragon2026")
    db.session.add(user)
    db.session.commit()
    r = client.post("/api/auth/login", json={"username": "admin2", "password": "Aragon2026"})
    assert r.status_code == 200, r.get_json()
    return _bearer(r.get_json()["token"])


# ————————————————— 39–46 治理审计 —————————————————

def _user_activities(user_id):
    return Activity.query.filter_by(entity_type="user", entity_id=user_id).all()


def test_role_change_writes_activity_with_from_and_to(client, auth, data):
    client.patch(f"/api/users/{data['member_id']}", json={"role": "pm"},
                 headers=auth("admin"))

    rows = [a for a in _user_activities(data["member_id"]) if a.action == "role_changed"]
    assert len(rows) == 1
    assert (rows[0].from_status, rows[0].to_status) == ("member", "pm")
    assert rows[0].actor_type == "user" and rows[0].actor_id == data["admin_id"]


def test_deactivate_and_activate_write_two_activities(client, auth, data):
    client.patch(f"/api/users/{data['member_id']}", json={"is_active": False},
                 headers=auth("admin"))
    client.patch(f"/api/users/{data['member_id']}", json={"is_active": True},
                 headers=auth("admin"))

    actions = [a.action for a in _user_activities(data["member_id"])]
    assert sorted(actions) == ["activated", "deactivated"]


def test_password_reset_writes_activity_without_any_secret(client, auth, data):
    r = client.post(f"/api/users/{data['member_id']}/reset-password", json={},
                    headers=auth("admin"))
    temporary = r.get_json()["temporary_password"]

    rows = [a for a in _user_activities(data["member_id"]) if a.action == "password_reset"]
    assert len(rows) == 1
    assert temporary not in (rows[0].message or "")


def test_signup_writes_user_registered_activity(client):
    body = client.post("/api/auth/signup", json=SIGNUP).get_json()

    rows = _user_activities(body["user"]["id"])
    assert [a.action for a in rows] == ["user_registered"]
    assert rows[0].actor_id == body["user"]["id"]


def test_settings_patch_writes_activity_without_invite_code(client, root_auth):
    secret = "SUPER-SECRET-CODE"
    r = client.patch("/api/settings/registration", json={"invite_code": secret},
                     headers=root_auth)
    assert r.status_code == 200, r.get_json()

    rows = Activity.query.filter_by(entity_type="app_setting").all()
    assert [a.action for a in rows] == ["registration_updated"]
    assert secret not in (rows[0].message or "")


def test_user_activities_endpoint_paginates_and_sets_total_count(client, auth, data):
    for role in ("pm", "member", "pm"):
        client.patch(f"/api/users/{data['member_id']}", json={"role": role},
                     headers=auth("admin"))

    r = client.get(f"/api/users/{data['member_id']}/activities?limit=2", headers=auth("admin"))

    assert r.status_code == 200
    assert len(r.get_json()) == 2
    assert r.headers["X-Total-Count"] == "3"


def test_user_activities_forbidden_for_member(client, auth, data):
    assert client.get(f"/api/users/{data['member_id']}/activities",
                      headers=auth("member")).status_code == 403


def test_user_activities_404_for_unknown_user(client, auth):
    """「不存在」与「没有动态」是两件事。"""
    assert client.get("/api/users/999999/activities",
                      headers=auth("admin")).status_code == 404


def test_stats_never_leaks_user_activities(client, auth, data):
    """【R-7 的机器执行者】治理事件绝不能出现在**所有成员**都能打开的仪表盘上。"""
    before = client.get("/api/stats", headers=auth("admin")).get_json()["activities_this_week"]
    client.patch(f"/api/users/{data['member_id']}", json={"role": "pm"},
                 headers=auth("admin"))

    body = client.get("/api/stats", headers=auth("admin")).get_json()

    assert all(a["entity_type"] in ("requirement", "bug")
               for a in body["recent_activities"])
    assert body["activities_this_week"] == before


# ————————————————— 47–50 保留名表与 purge —————————————————

@pytest.mark.parametrize("username", ["root", "system", "api", "administrator", "security"])
def test_reserved_username_table_blocks_root_system_api(client, auth, username):
    r = _create(client, auth, username=username, password="Aragon2026")

    assert r.status_code == 409
    assert r.get_json()["error"] == "username already exists"


def test_reserved_check_is_case_insensitive(client, auth):
    assert _create(client, auth, username="RooT", password="Aragon2026").status_code == 409


def test_existing_user_with_reserved_name_still_works(client, app, login):
    """保留名**只作用于建号那一刻**，不追溯任何存量行。"""
    user = User(username="system", role="member", display_name="Legacy")
    user.set_password("Aragon2026")
    db.session.add(user)
    db.session.commit()

    assert login("system", "Aragon2026").status_code == 200


def test_purge_keeps_user_with_governance_history(app, data):
    """【R-8】造数据时该用户只作为 `entity_id` 出现、**不**作为 `actor_id`。

    否则 `_user_references` 里既有的「施动者」那一项已经会命中，本条在没打补丁的代码上
    也是绿的——那是一条假绿的护栏。
    """
    victim = User(username="victim", role="member")
    victim.set_password("Aragon2026")
    db.session.add(victim)
    db.session.flush()
    Activity.log("user", victim.id, "deactivated", actor=("user", data["admin_id"]),
                 message="停用了该账号")
    db.session.commit()

    assert purge._user_references(victim.id) >= 1


# ————————————————— 51–56 建号路径合并后的契约 —————————————————

def test_register_still_requires_password(client, auth):
    """register **有意不获得**「不填口令」这个新能力：扩它的能力面等于制造第二个主入口。"""
    r = client.post("/api/auth/register", json={"username": "nopw"}, headers=auth("admin"))

    assert r.status_code == 400


def test_register_response_never_contains_temporary_password(client, auth):
    r = client.post("/api/auth/register",
                    json={"username": "regular", "password": "Aragon2026"},
                    headers=auth("admin"))

    assert r.status_code == 201
    body = r.get_json()
    assert "temporary_password" not in body
    assert "temporary_password" not in body["user"]


def test_register_now_blocks_reserved_username(client, auth):
    """合并顺带修掉的既有缺口：此前 users.py 有这道守卫、auth.py 没有。"""
    r = client.post("/api/auth/register",
                    json={"username": "root", "password": "Aragon2026"},
                    headers=auth("admin"))

    assert r.status_code == 409
    assert r.get_json()["error"] == "username already exists"


def test_both_create_paths_produce_identical_user_rows(client, auth):
    """「同一件事只有一份实现」的机器执行者：两条路由哪天再漂移，它先红。"""
    payload = {"password": "Aragon2026", "role": "pm", "display_name": "林磊",
               "email": "lin@example.com"}
    via_users = client.post("/api/users", json={**payload, "username": "path1"},
                            headers=auth("admin")).get_json()
    via_register = client.post("/api/auth/register", json={**payload, "username": "path2"},
                               headers=auth("admin")).get_json()["user"]

    volatile = {"id", "username", "created_at", "updated_at", "avatar_color",
                "temporary_password"}
    assert {k: v for k, v in via_users.items() if k not in volatile} == \
           {k: v for k, v in via_register.items() if k not in volatile}


def test_every_gate_exemption_resolves_to_a_real_route(app):
    """【评审 P2-7】豁免集是硬编码路径串，与蓝图 url_prefix 是两份真相。

    失效方向是**变严**（`/api/me/password` 被自己拦住 = 死循环），而那种故障在人工
    测试里表现为「改密码按钮点了没反应」，极难定位。
    """
    adapter = app.url_map.bind("localhost")

    for method, path in sorted(_PASSWORD_GATE_EXEMPT):
        adapter.match(path, method=method)


def test_weak_root_admin_password_does_not_break_boot(file_app):
    """【R-14】破窗路径**不依赖任何口令策略**：告警，不阻断。"""
    make, _ = file_app
    app = make(seed=False, ROOT_ADMIN_BOOTSTRAP=True, ROOT_ADMIN_USERNAME="breakglass",
               ROOT_ADMIN_PASSWORD="pw")

    r = app.test_client().post("/api/auth/login",
                               json={"username": "breakglass", "password": "pw"})

    assert r.status_code == 200, r.get_json()
    assert r.get_json()["user"]["must_change_password"] is False


# ————————————————————— E. 站点治理审计出口 54–63/60′
# （login-hardening-and-audit-console §7.2 E 组）—————————————————————

def _audit(client, root_auth, qs=""):
    return client.get(f"/api/settings/audit{qs}", headers=root_auth)


def test_audit_root_returns_bare_array_with_total(client, root_auth):
    client.post("/api/settings/registration/rotate-code", headers=root_auth)
    r = _audit(client, root_auth)
    assert r.status_code == 200
    assert isinstance(r.get_json(), list)
    assert "X-Total-Count" in r.headers


def test_audit_forbidden_for_normal_admin(client, auth):
    """R-10：普通 admin（非 root）→ 403。"""
    assert _audit(client, auth("admin")).status_code == 403


def test_audit_defaults_to_both_entity_types(client, root_auth, data):
    client.patch(f"/api/users/{data['member_id']}", json={"role": "pm"}, headers=root_auth)
    client.patch("/api/settings/registration", json={"enabled": True}, headers=root_auth)
    rows = _audit(client, root_auth).get_json()
    kinds = {row["entity_type"] for row in rows}
    assert "user" in kinds
    assert "app_setting" in kinds


def test_audit_filter_app_setting_reads_rotate(client, root_auth):
    client.post("/api/settings/registration/rotate-code", headers=root_auth)
    rows = _audit(client, root_auth, "?entity_type=app_setting").get_json()
    assert rows
    assert all(row["entity_type"] == "app_setting" for row in rows)
    assert any(row["action"] == "invite_code_rotated" for row in rows)


def test_audit_filter_by_action(client, root_auth, data):
    client.patch(f"/api/users/{data['member_id']}", json={"role": "pm"}, headers=root_auth)
    rows = _audit(client, root_auth, "?action=role_changed").get_json()
    assert rows and all(row["action"] == "role_changed" for row in rows)
    assert _audit(client, root_auth, "?action=not-a-real-action").status_code == 400


def test_audit_filter_by_actor_and_since(client, root_auth, data):
    client.patch(f"/api/users/{data['member_id']}", json={"role": "pm"}, headers=root_auth)
    by_actor = _audit(client, root_auth, f"?actor_id={data['admin_id']}").get_json()
    assert by_actor and all(row["actor_id"] == data["admin_id"] for row in by_actor)
    # since 取一个未来时刻 → 空。
    future = "2999-01-01T00:00:00"
    assert _audit(client, root_auth, f"?since={future}").get_json() == []


def test_audit_since_garbage_is_400_not_500(client, root_auth):
    """60【评审 P0-3】?since=乱码 → 400（不是 500），detail.field/expected 就位。"""
    r = _audit(client, root_auth, "?since=not-a-date")
    assert r.status_code == 400
    detail = r.get_json()["detail"]
    assert detail["field"] == "since"
    assert detail["expected"] == "ISO 8601 datetime"


def test_audit_since_tolerates_trailing_z(client, root_auth, data):
    """60′：把响应里带 Z 的 created_at 原样贴回 ?since= → 200 且过滤生效。"""
    client.patch(f"/api/users/{data['member_id']}", json={"role": "pm"}, headers=root_auth)
    rows = _audit(client, root_auth).get_json()
    stamp = rows[0]["created_at"]                    # 形如 "...Z"
    assert stamp.endswith("Z")
    r = _audit(client, root_auth, f"?since={stamp}")
    assert r.status_code == 200


def test_audit_rows_carry_actor_and_target_blocks(client, app, root_auth, data):
    client.patch(f"/api/users/{data['member_id']}", json={"role": "pm"}, headers=root_auth)
    with app.app_context():
        # 一条 system 施动的锁定审计：actor 应为 null。
        member = db.session.get(User, data["member_id"])
        audit.log_user_event(member, "account_locked", None, to_value="locked",
                             message="连续失败被锁定")
        db.session.commit()
    rows = _audit(client, root_auth).get_json()
    role_row = next(r for r in rows if r["action"] == "role_changed")
    assert role_row["actor"]["id"] == data["admin_id"]
    assert role_row["target"]["id"] == data["member_id"]
    locked_row = next(r for r in rows if r["action"] == "account_locked")
    assert locked_row["actor"] is None               # system 事件
    settings_rows = [r for r in rows if r["entity_type"] == "app_setting"]
    for r in settings_rows:
        assert r["target"] is None                   # app_setting 单例无目标


def test_audit_renders_after_actor_deleted(client, app, root_auth):
    with app.app_context():
        ghost = User(username="ghostactor", role="admin", is_active=True)
        ghost.set_password("Aragon2026")
        db.session.add(ghost)
        db.session.flush()
        target = User(username="ghosttarget", role="member")
        target.set_password("Aragon2026")
        db.session.add(target)
        db.session.flush()
        audit.log_user_event(target, "role_changed", ghost, from_value="member",
                             to_value="pm", message="改角色")
        db.session.commit()
        db.session.delete(ghost)                     # 施动者被删
        db.session.commit()
    r = _audit(client, root_auth)
    assert r.status_code == 200                       # 不抛
    row = next(x for x in r.get_json() if x["action"] == "role_changed"
               and x.get("target") and x["target"]["name"] == "ghosttarget")
    assert row["actor"] is None                       # 降级为 null


def test_audit_page_resolves_actors_without_n_plus_one(client, app, root_auth, data):
    """63（R-9）：一页 50 行审计对 users 表的查询次数不随行数增长。"""
    from sqlalchemy import event

    with app.app_context():
        actors = []
        for i in range(5):
            u = User(username=f"actor{i}", role="admin")
            u.set_password("Aragon2026")
            db.session.add(u)
            actors.append(u)
        target = db.session.get(User, data["member_id"])
        db.session.flush()
        for i in range(50):
            audit.log_user_event(target, "role_changed", actors[i % 5],
                                 from_value="member", to_value="pm", message="x")
        db.session.commit()

    counts = {"users": 0, "batched": 0}

    def _before(conn, cursor, statement, parameters, context, executemany):
        if "FROM users" in statement:
            counts["users"] += 1
            if " IN (" in statement:
                counts["batched"] += 1

    engine = db.engine
    event.listen(engine, "before_cursor_execute", _before)
    try:
        r = client.get("/api/settings/audit?limit=50", headers=root_auth)
    finally:
        event.remove(engine, "before_cursor_execute", _before)
    assert r.status_code == 200
    # resolve_actors 必须**恰好一次**批量 IN 查询（不是逐行 get）。
    assert counts["batched"] == 1
    # 其余是 auth / loader 的常量次数；关键是总数不随行数增长。真正的 N+1 会是 ~50 次。
    assert counts["users"] < 10
