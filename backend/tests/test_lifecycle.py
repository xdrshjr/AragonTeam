"""资源生命周期与治理（lifecycle-and-governance §6.1）。

覆盖：末任管理员不变量（降级 / 停用 / 停用的 admin 不算数）、停用后的登录与既有 token、
取消指派（含幂等、审计、通知、坏输入仍 400）、项目与 Agent 的引用守卫与归档语义、
Agent 删除后 assignee 的诚实降级、已停用收件人不收通知。
"""
from extensions import db
from models.activity import Activity
from models.agent import Agent
from models.bug import Bug
from models.notification import Notification
from models.project import Project
from models.requirement import Requirement
from models.user import User


# ————————————————————— A. 末任管理员不变量（§2.2）—————————————————————

def test_rejects_demoting_the_last_admin(client, auth, app, data):
    r = client.patch(f"/api/users/{data['admin_id']}", json={"role": "member"},
                     headers=auth("admin"))

    assert r.status_code == 409, r.get_json()
    assert r.get_json()["error"] == "cannot remove the last administrator"
    with app.app_context():
        assert db.session.get(User, data["admin_id"]).role == "admin"


def test_rejects_deactivating_the_last_admin(client, auth, data):
    r = client.patch(f"/api/users/{data['admin_id']}", json={"is_active": False},
                     headers=auth("admin"))

    assert r.status_code == 409, r.get_json()
    assert r.get_json()["detail"]["active_admins"] == 1


def test_allows_demoting_when_another_active_admin_exists(client, auth, data):
    headers = auth("admin")
    created = client.post("/api/users", json={"username": "admin2", "password": "admin2123",
                                              "role": "admin"}, headers=headers)
    assert created.status_code == 201, created.get_json()

    r = client.patch(f"/api/users/{data['admin_id']}", json={"role": "member"}, headers=headers)

    assert r.status_code == 200, r.get_json()
    assert r.get_json()["role"] == "member"


def test_a_deactivated_admin_does_not_count_as_active(client, auth, app, data):
    """有 2 个 admin 但其一已停用时，降级另一个仍 409（最容易实现错的一条）。"""
    headers = auth("admin")
    created = client.post("/api/users", json={"username": "admin2", "password": "admin2123",
                                              "role": "admin"}, headers=headers)
    admin2_id = created.get_json()["id"]
    assert client.patch(f"/api/users/{admin2_id}", json={"is_active": False},
                        headers=headers).status_code == 200

    r = client.patch(f"/api/users/{data['admin_id']}", json={"role": "member"}, headers=headers)

    assert r.status_code == 409, r.get_json()
    with app.app_context():
        assert db.session.get(User, data["admin_id"]).role == "admin"


def test_patch_user_without_updatable_field_is_400(client, auth, data):
    """【P2-5】此前无字段被识别仍返 200 + 完整用户体，管理员以为改了。"""
    r = client.patch(f"/api/users/{data['member_id']}", json={"nonsense": 1},
                     headers=auth("admin"))

    assert r.status_code == 400
    assert r.get_json()["error"] == "no updatable field"


def test_is_active_must_be_boolean(client, auth, data):
    r = client.patch(f"/api/users/{data['member_id']}", json={"is_active": "yes"},
                     headers=auth("admin"))

    assert r.status_code == 400
    assert r.get_json()["detail"]["field"] == "is_active"


def test_want_bool_required_rejects_null(client, auth, data):
    """`{"is_active": null}` 必须 400，**不是**静默取 default False 把人停用。"""
    r = client.patch(f"/api/users/{data['member_id']}", json={"is_active": None},
                     headers=auth("admin"))

    assert r.status_code == 400, r.get_json()


# ————————————————————— B. 停用的效力（§2.5）—————————————————————

def test_disabled_user_cannot_login(client, disabled_user, login):
    r = login("member", "member123")

    assert r.status_code == 403
    assert "disabled" in r.get_json()["error"]


def test_disabled_login_does_not_count_towards_ratelimit(client, app, auth, data, login):
    """停用不是猜密码，不该把人推进 429（TestConfig 阈值为 3）。"""
    assert client.patch(f"/api/users/{data['member_id']}", json={"is_active": False},
                        headers=auth("admin")).status_code == 200

    for _ in range(5):
        r = login("member", "member123")
        assert r.status_code == 403, r.get_json()


def test_existing_token_of_disabled_user_is_rejected(client, auth, data):
    member_headers = auth("member")
    assert client.get("/api/auth/me", headers=member_headers).status_code == 200

    assert client.patch(f"/api/users/{data['member_id']}", json={"is_active": False},
                        headers=auth("admin")).status_code == 200

    r = client.get("/api/auth/me", headers=member_headers)
    assert r.status_code == 401
    assert r.get_json()["error"] == "account is disabled or removed"
    # 受保护端点全覆盖，公开端点零误伤。
    assert client.get("/api/requirements", headers=member_headers).status_code == 401
    assert client.get("/api/health").status_code == 200


def test_reactivated_user_can_login_again(client, auth, data, login):
    headers = auth("admin")
    client.patch(f"/api/users/{data['member_id']}", json={"is_active": False}, headers=headers)
    client.patch(f"/api/users/{data['member_id']}", json={"is_active": True}, headers=headers)

    assert login("member", "member123").status_code == 200


def test_notifications_skip_disabled_recipient(client, auth, app, data, make_requirement):
    """停用后不再往其信箱堆通知（他再也不会登录）。"""
    req = make_requirement("给停用者的单")
    assert client.patch(f"/api/users/{data['member_id']}", json={"is_active": False},
                        headers=auth("admin")).status_code == 200

    r = client.patch(f"/api/requirements/{req['id']}/assign",
                     json={"assignee_type": "user", "assignee_id": data["member_id"]},
                     headers=auth("pm"))

    assert r.status_code == 200, r.get_json()
    with app.app_context():
        assert Notification.query.filter_by(user_id=data["member_id"]).count() == 0


# ————————————————————— C. 取消指派（§2.4-B2）—————————————————————

def test_unassign_clears_polymorphic_assignee(client, auth, app, data, make_requirement):
    req = make_requirement("待撤回", assignee=("agent", data["dev_agent_id"]))
    assert req["status"] == "assigned"

    r = client.patch(f"/api/requirements/{req['id']}/assign",
                     json={"assignee_type": None, "assignee_id": None}, headers=auth("pm"))

    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["assignee_type"] is None
    assert body["assignee_id"] is None
    assert body["assignee"] is None
    # G1：状态与列内次序都不被触碰。
    assert body["status"] == "assigned"
    with app.app_context():
        assert db.session.get(Requirement, req["id"]).status == "assigned"


def test_unassign_writes_activity_and_notifies_previous_human_assignee(
        client, auth, app, data, make_requirement):
    req = make_requirement("原本归我", assignee=("user", data["member_id"]))

    r = client.patch(f"/api/requirements/{req['id']}/assign",
                     json={"assignee_type": None}, headers=auth("pm"))

    assert r.status_code == 200, r.get_json()
    with app.app_context():
        acts = Activity.query.filter_by(entity_type="requirement", entity_id=req["id"],
                                        action="unassigned").all()
        assert len(acts) == 1
        assert acts[0].message == "取消了指派"
        notes = Notification.query.filter_by(user_id=data["member_id"]).all()
        assert any("不再负责" in n.message for n in notes)


def test_unassign_is_idempotent_without_extra_activity(client, auth, app, make_requirement):
    req = make_requirement("从未指派")

    r = client.patch(f"/api/requirements/{req['id']}/assign",
                     json={"assignee_type": None}, headers=auth("pm"))

    assert r.status_code == 200
    with app.app_context():
        assert Activity.query.filter_by(entity_type="requirement", entity_id=req["id"],
                                        action="unassigned").count() == 0


def test_assign_with_empty_string_type_still_400(client, auth, make_requirement):
    """防把「取消」判据写成 falsy：空串是坏输入，语义与显式 null 不同。"""
    req = make_requirement("坏输入")

    r = client.patch(f"/api/requirements/{req['id']}/assign",
                     json={"assignee_type": "", "assignee_id": 1}, headers=auth("pm"))

    assert r.status_code == 400
    assert r.get_json()["error"] == "invalid assignee_type"


def test_unassign_bug_is_symmetric(client, auth, data, make_bug):
    bug = make_bug("撤回缺陷", assignee=("agent", data["dev_agent_id"]))

    r = client.patch(f"/api/bugs/{bug['id']}/assign",
                     json={"assignee_type": None}, headers=auth("pm"))

    assert r.status_code == 200, r.get_json()
    assert r.get_json()["assignee"] is None


def test_unassign_requires_pm_or_admin(client, auth, data, make_requirement):
    req = make_requirement("权限不放宽", assignee=("agent", data["dev_agent_id"]))

    r = client.patch(f"/api/requirements/{req['id']}/assign",
                     json={"assignee_type": None}, headers=auth("member"))

    assert r.status_code == 403


# ————————————————————— D. 项目生命周期（§2.6）—————————————————————

def test_patch_project_updates_fields(client, auth, data):
    r = client.patch(f"/api/projects/{data['project_id']}",
                     json={"name": "改过的名字", "key": "arg"}, headers=auth("pm"))

    assert r.status_code == 200, r.get_json()
    assert r.get_json()["name"] == "改过的名字"
    assert r.get_json()["key"] == "ARG"       # 与创建路径一致地 .upper()


def test_patch_project_key_conflict_409(client, auth, data):
    headers = auth("pm")
    other = client.post("/api/projects", json={"name": "另一个", "key": "OTH"}, headers=headers)
    assert other.status_code == 201

    r = client.patch(f"/api/projects/{data['project_id']}", json={"key": "OTH"}, headers=headers)

    assert r.status_code == 409
    assert r.get_json()["error"] == "project key already exists"


def test_patch_project_without_updatable_field_is_400(client, auth, data):
    r = client.patch(f"/api/projects/{data['project_id']}", json={}, headers=auth("pm"))

    assert r.status_code == 400


def test_archived_project_hidden_by_default_and_visible_with_flag(client, auth, data):
    headers = auth("pm")
    assert client.patch(f"/api/projects/{data['project_id']}", json={"archived": True},
                        headers=headers).status_code == 200

    default_ids = [p["id"] for p in client.get("/api/projects", headers=headers).get_json()]
    all_ids = [p["id"] for p in
               client.get("/api/projects?include_archived=1", headers=headers).get_json()]

    assert data["project_id"] not in default_ids
    assert data["project_id"] in all_ids


def test_archiving_does_not_touch_existing_tickets(client, auth, data, make_requirement):
    """归档只切断「未来把新东西放进去」，既有工单仍可查询、仍可流转。"""
    headers = auth("pm")
    r = client.post("/api/requirements", json={"title": "归档项目的单",
                                               "project_id": data["project_id"]}, headers=headers)
    req_id = r.get_json()["id"]
    client.patch(f"/api/projects/{data['project_id']}", json={"archived": True}, headers=headers)

    assert client.get(f"/api/requirements/{req_id}", headers=headers).status_code == 200
    moved = client.patch(f"/api/requirements/{req_id}/assign",
                         json={"assignee_type": "user", "assignee_id": data["member_id"]},
                         headers=headers)
    assert moved.status_code == 200, moved.get_json()


def test_unarchiving_restores_visibility(client, auth, data):
    headers = auth("pm")
    client.patch(f"/api/projects/{data['project_id']}", json={"archived": True}, headers=headers)
    client.patch(f"/api/projects/{data['project_id']}", json={"archived": False}, headers=headers)

    ids = [p["id"] for p in client.get("/api/projects", headers=headers).get_json()]
    assert data["project_id"] in ids


def test_delete_project_with_tickets_conflicts(client, auth, data):
    headers = auth("admin")
    client.post("/api/requirements", json={"title": "占着项目", "project_id": data["project_id"]},
                headers=auth("pm"))

    r = client.delete(f"/api/projects/{data['project_id']}", headers=headers)

    assert r.status_code == 409, r.get_json()
    detail = r.get_json()["detail"]
    assert detail["requirements"] == 1
    assert detail["bugs"] == 0
    assert "archive" in detail["hint"]


def test_delete_empty_project_succeeds(client, auth, data):
    headers = auth("admin")

    r = client.delete(f"/api/projects/{data['project_id']}", headers=headers)

    assert r.status_code == 204
    ids = [p["id"] for p in client.get("/api/projects", headers=headers).get_json()]
    assert data["project_id"] not in ids


def test_delete_project_requires_admin(client, auth, data):
    """DELETE 比 PATCH 更严：pm 可改不可删。"""
    assert client.delete(f"/api/projects/{data['project_id']}",
                         headers=auth("pm")).status_code == 403


def test_delete_missing_project_is_404(client, auth):
    assert client.delete("/api/projects/99999", headers=auth("admin")).status_code == 404


# ————————————————————— E. Agent 生命周期（§2.7）—————————————————————

def test_delete_agent_with_open_tickets_conflicts(client, auth, data, make_requirement, make_bug):
    make_requirement("在手需求", assignee=("agent", data["dev_agent_id"]))
    make_bug("在手缺陷", assignee=("agent", data["dev_agent_id"]))

    r = client.delete(f"/api/agents/{data['dev_agent_id']}", headers=auth("admin"))

    assert r.status_code == 409, r.get_json()
    assert r.get_json()["detail"] == {"requirements": 1, "bugs": 1,
                                      "hint": "reassign or unassign them first"}


def test_delete_agent_with_only_terminal_tickets_succeeds(client, auth, app, data, make_bug):
    bug = make_bug("已关闭", assignee=("agent", data["dev_agent_id"]))
    with app.app_context():
        db.session.get(Bug, bug["id"]).status = "closed"
        db.session.commit()

    r = client.delete(f"/api/agents/{data['dev_agent_id']}", headers=auth("admin"))

    assert r.status_code == 204, r.get_json()


def test_delete_idle_agent_succeeds(client, auth, data):
    assert client.delete(f"/api/agents/{data['qa_agent_id']}",
                         headers=auth("pm")).status_code == 204


def test_deleted_agent_assignee_degrades_to_placeholder(
        client, auth, app, data, make_requirement):
    """工单 assignee 指向已删 Agent 时必须是占位而**不是** null（否则 UI 说「未指派」）。"""
    req = make_requirement("交给会被删的 Agent", assignee=("agent", data["dev_agent_id"]))
    with app.app_context():
        db.session.delete(db.session.get(Agent, data["dev_agent_id"]))
        db.session.commit()

    body = client.get(f"/api/requirements/{req['id']}", headers=auth("pm")).get_json()

    assert body["assignee_id"] == data["dev_agent_id"]
    assert body["assignee"] is not None
    assert body["assignee"]["deleted"] is True
    assert body["assignee"]["name"] == "(已删除)"


def test_never_assigned_ticket_still_reports_null_assignee(client, auth, make_requirement):
    """真·未指派的语义不变——降级只作用于「指向已删除目标」。"""
    req = make_requirement("从未指派过")

    body = client.get(f"/api/requirements/{req['id']}", headers=auth("pm")).get_json()

    assert body["assignee"] is None


def test_delete_missing_agent_is_404(client, auth):
    assert client.delete("/api/agents/99999", headers=auth("admin")).status_code == 404


# ————————————————————— F. 删除工单的级联（§7 R-6）—————————————————————

def test_deleting_ticket_removes_its_notifications(
        client, auth, app, data, make_requirement):
    req = make_requirement("会被删掉", assignee=("user", data["member_id"]))
    with app.app_context():
        assert Notification.query.filter_by(entity_type="requirement",
                                            entity_id=req["id"]).count() >= 1

    assert client.delete(f"/api/requirements/{req['id']}",
                         headers=auth("pm")).status_code == 204

    with app.app_context():
        assert Notification.query.filter_by(entity_type="requirement",
                                            entity_id=req["id"]).count() == 0
        assert Activity.query.filter_by(entity_type="requirement",
                                        entity_id=req["id"]).count() == 0


def test_project_fixture_helpers_are_consistent(app, archived_project, disabled_user):
    """归档 / 停用两个 fixture 的落库效果（供其余用例信赖）。"""
    with app.app_context():
        assert db.session.get(Project, archived_project).archived_at is not None
        assert db.session.get(User, disabled_user).is_active is False
