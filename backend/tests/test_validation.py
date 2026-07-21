"""reliability-hardening §6.1 —— JSON 输入边界校验（坏输入 400 不 500）。

硬指标：所有写接口在「非对象 JSON 体」「非串/非法类型字段」下**返回 400 且断言 != 500**；
公开 /login 是最刺眼缺陷，单列回归。正路仍 200/201（成功 shape 不变）。
另覆盖：move 非串 status（B1）、patch_agent 禁 busy（B3）、无效 JWT → 401（C2）。
"""
import pytest

from services.validation import (
    ValidationError, json_body, want_str, want_int, want_bool,
)


# ————————————————————— 公开 /login：最刺眼的可复现 500 —————————————————————

@pytest.mark.parametrize("raw", ["5", "[1]", '"x"', "true", "null"])
def test_login_non_object_body_returns_400_not_500(client, raw):
    """非对象 JSON 体（合法 JSON 但非 dict）此前 .get 触 500——现归一 400（公开接口）。"""
    r = client.post("/api/auth/login", data=raw, content_type="application/json")
    assert r.status_code == 400
    assert r.status_code != 500
    assert r.get_json()["error"]


def test_login_non_string_username_returns_400_not_500(client):
    """{"username":123} 此前 .strip() 触 500——现 400。"""
    r = client.post("/api/auth/login", json={"username": 123, "password": "x"})
    assert r.status_code == 400
    assert r.status_code != 500
    assert r.get_json()["detail"]["field"] == "username"


def test_login_valid_still_200(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200


# ————————————————————— 真正会 500 的字段（.strip / 主键 / 密码）—————————————————————

def test_register_non_string_display_name_400(client, auth):
    r = client.post("/api/auth/register",
                    json={"username": "x1", "password": "pw12345", "display_name": 9},
                    headers=auth("admin"))
    assert r.status_code == 400
    assert r.status_code != 500


def test_create_requirement_non_string_title_400(client, auth):
    r = client.post("/api/requirements", json={"title": 123}, headers=auth("pm"))
    assert r.status_code == 400
    assert r.status_code != 500
    assert r.get_json()["detail"]["field"] == "title"


def test_create_requirement_list_project_id_400(client, auth):
    """list 主键此前进 db.session.get 触 500——现 400。"""
    r = client.post("/api/requirements", json={"title": "ok", "project_id": [1]},
                    headers=auth("pm"))
    assert r.status_code == 400
    assert r.status_code != 500


def test_create_bug_non_string_title_400(client, auth):
    r = client.post("/api/bugs", json={"title": 123}, headers=auth("pm"))
    assert r.status_code == 400
    assert r.status_code != 500


def test_create_bug_list_related_requirement_id_400(client, auth):
    r = client.post("/api/bugs", json={"title": "ok", "related_requirement_id": [1]},
                    headers=auth("pm"))
    assert r.status_code == 400
    assert r.status_code != 500


def test_create_agent_non_string_name_400(client, auth):
    r = client.post("/api/agents", json={"name": 5}, headers=auth("pm"))
    assert r.status_code == 400
    assert r.status_code != 500


def test_create_project_non_string_name_400(client, auth):
    r = client.post("/api/projects", json={"name": 5, "key": "K"}, headers=auth("pm"))
    assert r.status_code == 400
    assert r.status_code != 500


def test_create_user_non_string_username_400(client, auth):
    r = client.post("/api/users", json={"username": 5, "password": "pw12345"},
                    headers=auth("admin"))
    assert r.status_code == 400
    assert r.status_code != 500


def test_comment_non_object_body_400(client, auth, make_requirement):
    req = make_requirement()
    r = client.post(f"/api/requirements/{req['id']}/comments", data="5",
                    content_type="application/json", headers=auth("pm"))
    assert r.status_code == 400
    assert r.status_code != 500


def test_comment_non_string_body_400(client, auth, make_requirement):
    req = make_requirement()
    r = client.post(f"/api/requirements/{req['id']}/comments", json={"body": 123},
                    headers=auth("pm"))
    assert r.status_code == 400
    assert r.status_code != 500


def test_me_password_non_string_400(client, auth):
    """非串密码此前进 check_password 触 500——现 400。"""
    r = client.post("/api/me/password", json={"current_password": 123, "new_password": 456},
                    headers=auth("member"))
    assert r.status_code == 400
    assert r.status_code != 500


def test_me_profile_non_object_body_400(client, auth):
    r = client.patch("/api/me/profile", data="5", content_type="application/json",
                     headers=auth("member"))
    # 非对象体归一为 {}，无白名单字段命中 → 无改动、200；关键是 != 500。
    assert r.status_code in (200, 400)
    assert r.status_code != 500


def test_me_profile_non_string_display_name_400(client, auth):
    r = client.patch("/api/me/profile", json={"display_name": 123}, headers=auth("member"))
    assert r.status_code == 400
    assert r.status_code != 500


# ————————————————————— 枚举 choices：归一回归（现状即 400，非「500→400」）—————————————————————

def test_create_requirement_invalid_priority_still_400(client, auth):
    r = client.post("/api/requirements", json={"title": "ok", "priority": "bogus"},
                    headers=auth("pm"))
    assert r.status_code == 400


def test_create_bug_invalid_severity_still_400(client, auth):
    r = client.post("/api/bugs", json={"title": "ok", "severity": "bogus"}, headers=auth("pm"))
    assert r.status_code == 400


# ————————————————————— 正路回归：合法体仍 201/200 —————————————————————

def test_valid_create_requirement_still_201(client, auth):
    r = client.post("/api/requirements", json={"title": "正常需求", "priority": "high"},
                    headers=auth("pm"))
    assert r.status_code == 201
    assert r.get_json()["title"] == "正常需求"


def test_valid_create_bug_still_201(client, auth):
    r = client.post("/api/bugs", json={"title": "正常缺陷", "severity": "critical"},
                    headers=auth("pm"))
    assert r.status_code == 201


# ————————————————————— B1：move 非串 status → 400（unhashable 500 回归）—————————————————————

def test_requirement_move_list_status_400_not_500(client, auth, make_requirement, data):
    req = make_requirement(assignee=("user", data["member_id"]))
    r = client.patch(f"/api/requirements/{req['id']}/move", json={"status": ["assigned"]},
                     headers=auth("pm"))
    assert r.status_code == 400
    assert r.status_code != 500


def test_bug_move_int_status_400_not_500(client, auth, make_bug, data):
    bug = make_bug(assignee=("user", data["member_id"]))
    r = client.patch(f"/api/bugs/{bug['id']}/move", json={"status": 42}, headers=auth("pm"))
    assert r.status_code == 400
    assert r.status_code != 500


# ————————————————————— B3：patch_agent 禁手动置 busy —————————————————————

def test_patch_agent_busy_rejected_400(client, auth, data):
    r = client.patch(f"/api/agents/{data['dev_agent_id']}", json={"status": "busy"},
                     headers=auth("pm"))
    assert r.status_code == 400
    assert "idle or offline" in r.get_json()["error"]


def test_patch_agent_idle_ok_200(client, auth, data):
    r = client.patch(f"/api/agents/{data['dev_agent_id']}", json={"status": "idle"},
                     headers=auth("pm"))
    assert r.status_code == 200
    assert r.get_json()["status"] == "idle"


def test_patch_agent_offline_ok_200(client, auth, data):
    r = client.patch(f"/api/agents/{data['dev_agent_id']}", json={"status": "offline"},
                     headers=auth("pm"))
    assert r.status_code == 200
    assert r.get_json()["status"] == "offline"


# ————————————————————— C2：无效 JWT → 401（此前 422，会卡死会话）—————————————————————

def test_invalid_jwt_returns_401(client):
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer not.a.valid.jwt"})
    assert r.status_code == 401
    assert r.status_code != 422


# ————————————————————— validation 模块单元 —————————————————————

def test_want_str_rejects_non_string(app):
    with app.test_request_context():
        with pytest.raises(ValidationError):
            want_str({"k": 1}, "k")


def test_want_str_required_empty_raises(app):
    with app.test_request_context():
        with pytest.raises(ValidationError):
            want_str({"k": "   "}, "k", required=True)


def test_want_str_choices_and_default(app):
    with app.test_request_context():
        assert want_str({}, "k", default="d") == "d"
        assert want_str({"k": "a"}, "k", choices=("a", "b")) == "a"
        with pytest.raises(ValidationError):
            want_str({"k": "z"}, "k", choices=("a", "b"))


def test_want_int_rejects_bool_and_non_int(app):
    with app.test_request_context():
        with pytest.raises(ValidationError):
            want_int({"k": True}, "k")   # bool 是 int 子类，须排除
        with pytest.raises(ValidationError):
            want_int({"k": "5"}, "k")    # 数字字符串不接受
        assert want_int({"k": 5}, "k") == 5
        assert want_int({}, "k") is None


def test_want_bool_rejects_non_bool(app):
    with app.test_request_context():
        with pytest.raises(ValidationError):
            want_bool({"k": "true"}, "k")
        assert want_bool({"k": True}, "k") is True
        assert want_bool({}, "k", default=True) is True


def test_json_body_non_object_returns_empty(app):
    with app.test_request_context(data="5", content_type="application/json"):
        assert json_body() == {}
    with app.test_request_context(json={"a": 1}):
        assert json_body() == {"a": 1}


# ————————————————————— §2.4：reliability-hardening 漏网的残余坏输入 500→400 —————————————————————

def test_tick_non_int_claim_count_400_not_500(client, auth, data):
    """【§2.4-C1】claim_count 非整此前经 int("x") 触 500——现 want_int → 400。"""
    r = client.post(f"/api/agents/{data['dev_agent_id']}/tick", json={"claim_count": "x"},
                    headers=auth("pm"))
    assert r.status_code == 400
    assert r.status_code != 500
    assert r.get_json()["detail"]["field"] == "claim_count"


def test_register_non_string_email_400_not_500(client, auth):
    """【§2.4-C2】非串 email 此前绑到 String 列 commit 触 InterfaceError 500——现 400。"""
    r = client.post("/api/auth/register",
                    json={"username": "e1", "password": "pw12345", "email": {"x": 1}},
                    headers=auth("admin"))
    assert r.status_code == 400
    assert r.status_code != 500
    assert r.get_json()["detail"]["field"] == "email"


def test_create_user_non_string_email_400_not_500(client, auth):
    r = client.post("/api/users",
                    json={"username": "e2", "password": "pw12345", "email": {"x": 1}},
                    headers=auth("admin"))
    assert r.status_code == 400
    assert r.status_code != 500


def test_patch_user_non_string_email_400_not_500(client, auth, data):
    r = client.patch(f"/api/users/{data['member_id']}", json={"email": {"x": 1}},
                     headers=auth("admin"))
    assert r.status_code == 400
    assert r.status_code != 500


def test_create_requirement_non_string_description_400_not_500(client, auth):
    """【§2.4-C3】非串 description 此前绑到 Text 列 commit 触 500——现 400。"""
    r = client.post("/api/requirements", json={"title": "t", "description": {"x": 1}},
                    headers=auth("pm"))
    assert r.status_code == 400
    assert r.status_code != 500
    assert r.get_json()["detail"]["field"] == "description"


def test_create_bug_non_string_description_400_not_500(client, auth):
    r = client.post("/api/bugs", json={"title": "t", "description": {"x": 1}},
                    headers=auth("pm"))
    assert r.status_code == 400
    assert r.status_code != 500


def test_patch_requirement_non_string_description_400_not_500(client, auth, make_requirement):
    req = make_requirement()
    r = client.patch(f"/api/requirements/{req['id']}", json={"description": {"x": 1}},
                     headers=auth("pm"))
    assert r.status_code == 400
    assert r.status_code != 500


def test_valid_multiline_description_preserved_still_201(client, auth):
    """strip=False 保留描述换行/缩进（描述可为多行工作说明）；正路仍 201。"""
    body = "第一行\n  缩进的第二行\n"
    r = client.post("/api/requirements", json={"title": "多行", "description": body},
                    headers=auth("pm"))
    assert r.status_code == 201
    assert r.get_json()["description"] == body


# ————————————————————— §2.5：want_str 枚举字段空串回退 default（不落库非法 ""）—————————————————————

def test_want_str_choices_empty_returns_default(app):
    """空串 + choices → 回退 default（不再绕过枚举、不落库 ""）。"""
    with app.test_request_context():
        assert want_str({"k": ""}, "k", default="medium", choices=("low", "medium")) == "medium"
        assert want_str({"k": "  "}, "k", default="medium", choices=("low", "medium")) == "medium"


def test_create_requirement_empty_priority_defaults_medium(client, auth):
    r = client.post("/api/requirements", json={"title": "t", "priority": ""}, headers=auth("pm"))
    assert r.status_code == 201
    assert r.get_json()["priority"] == "medium"


def test_create_bug_empty_severity_defaults_major(client, auth):
    r = client.post("/api/bugs", json={"title": "t", "severity": ""}, headers=auth("pm"))
    assert r.status_code == 201
    assert r.get_json()["severity"] == "major"


def test_create_agent_empty_kind_defaults_generic(client, auth):
    r = client.post("/api/agents", json={"name": "空类型 Agent", "kind": ""}, headers=auth("pm"))
    assert r.status_code == 201
    assert r.get_json()["kind"] == "generic"


def test_register_empty_role_defaults_member(client, auth):
    r = client.post("/api/auth/register",
                    json={"username": "r1", "password": "Pw123456", "role": ""},
                    headers=auth("admin"))
    assert r.status_code == 201
    assert r.get_json()["user"]["role"] == "member"


# —— lifecycle-and-governance：本轮新增字段的边界 ——

def test_patch_project_archived_must_be_boolean(client, auth, data):
    r = client.patch(f"/api/projects/{data['project_id']}", json={"archived": "yes"},
                     headers=auth("pm"))
    assert r.status_code == 400
    assert r.get_json()["detail"]["field"] == "archived"


def test_patch_project_archived_null_is_400(client, auth, data):
    """显式 null 不得静默取 default False（那会悄悄把一个归档项目取消归档）。"""
    r = client.patch(f"/api/projects/{data['project_id']}", json={"archived": None},
                     headers=auth("pm"))
    assert r.status_code == 400


def test_patch_project_owner_must_exist(client, auth, data):
    r = client.patch(f"/api/projects/{data['project_id']}", json={"owner_id": 99999},
                     headers=auth("pm"))
    assert r.status_code == 400
    assert r.get_json()["error"] == "owner not found"


def test_board_column_limit_out_of_range_is_clamped_not_500(client, auth):
    r = client.get("/api/board/requirements?column_limit=99999999999999999999",
                   headers=auth("pm"))
    assert r.status_code == 200


def test_board_project_id_still_400_on_garbage(client, auth):
    r = client.get("/api/board/requirements?project_id=abc", headers=auth("pm"))
    assert r.status_code == 400
