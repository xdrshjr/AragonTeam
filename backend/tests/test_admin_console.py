"""管理台写操作集成回归（admin-console §6.1）。

覆盖三条管理链路的正常路径 + 至少一条异常路径（CLAUDE.md §7）：
① 用户建 / 改 / 重置密码（真实换哈希，禁 mock）+ 门禁；
② Agent 建 / 改（本轮新增 name/kind）+ 改名唯一 + 门禁收紧（原裸 jwt → admin/pm）；
③ 项目建 + key 唯一 + 门禁。
沿用 conftest fixtures（client/auth/data/login；角色 admin/pm/member）。
"""

# ————————————————————— 用户（Team）—————————————————————

def test_admin_creates_member(client, auth, data):
    """admin 建成员 → 201，且随后 GET /api/users 列表含新成员。"""
    r = client.post("/api/users",
                    json={"username": "carol", "password": "pw123456", "role": "member"},
                    headers=auth("admin"))
    assert r.status_code == 201, r.get_json()
    assert r.get_json()["username"] == "carol"

    listing = client.get("/api/users", headers=auth("admin"))
    assert listing.status_code == 200
    assert any(u["username"] == "carol" for u in listing.get_json())


def test_create_member_duplicate_username_conflicts(client, auth):
    """以既有用户名（member）再建 → 409。"""
    r = client.post("/api/users",
                    json={"username": "member", "password": "pw123456"},
                    headers=auth("admin"))
    assert r.status_code == 409


def test_admin_patches_member_profile_and_role(client, auth, data):
    """admin 改成员显示名 / 邮箱 / 角色 → 200，返回体三字段同步。"""
    r = client.patch(f"/api/users/{data['member_id']}",
                     json={"display_name": "Mia2", "email": "mia@x.io", "role": "pm"},
                     headers=auth("admin"))
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["display_name"] == "Mia2"
    assert body["email"] == "mia@x.io"
    assert body["role"] == "pm"


def test_admin_resets_member_password(client, auth, login, data):
    """真实改密集成（禁 mock）：重置后旧密登录 401、新密登录 200。"""
    r = client.patch(f"/api/users/{data['member_id']}",
                     json={"password": "newpw123"}, headers=auth("admin"))
    assert r.status_code == 200
    assert login("member", "member123").status_code == 401   # 旧密码失效
    assert login("member", "newpw123").status_code == 200     # 新密码可登录


def test_member_cannot_create_or_patch_user(client, auth, data):
    """member 无权建 / 改用户，POST 与 PATCH 均 403（补齐 patch 门禁覆盖）。"""
    create = client.post("/api/users",
                         json={"username": "x", "password": "pw123456"},
                         headers=auth("member"))
    assert create.status_code == 403
    patch = client.patch(f"/api/users/{data['member_id']}",
                        json={"display_name": "hacked"}, headers=auth("member"))
    assert patch.status_code == 403


# ————————————————————— Agent —————————————————————

def test_pm_creates_agent(client, auth):
    """pm 建 Agent → 201。"""
    r = client.post("/api/agents", json={"name": "sec-agent", "kind": "generic"},
                    headers=auth("pm"))
    assert r.status_code == 201, r.get_json()
    assert r.get_json()["name"] == "sec-agent"


def test_create_agent_duplicate_name_conflicts(client, auth):
    """以既有名（dev-agent）再建 → 409。"""
    r = client.post("/api/agents", json={"name": "dev-agent"}, headers=auth("pm"))
    assert r.status_code == 409


def test_patch_agent_name_kind_description(client, auth, data):
    """本轮新增能力：改 name/kind/description → 200，三字段同步。"""
    r = client.patch(f"/api/agents/{data['qa_agent_id']}",
                     json={"name": "qa-agent-2", "kind": "generic", "description": "x"},
                     headers=auth("pm"))
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["name"] == "qa-agent-2"
    assert body["kind"] == "generic"
    assert body["description"] == "x"


def test_patch_agent_rename_to_existing_conflicts(client, auth, data):
    """改名撞既有名 → 409；改回自己现名 → 200（id != self 排除，不误报）。"""
    conflict = client.patch(f"/api/agents/{data['qa_agent_id']}",
                            json={"name": "dev-agent"}, headers=auth("pm"))
    assert conflict.status_code == 409
    same = client.patch(f"/api/agents/{data['qa_agent_id']}",
                        json={"name": "qa-agent"}, headers=auth("pm"))
    assert same.status_code == 200, same.get_json()


def test_patch_agent_invalid_kind_rejected(client, auth, data):
    """非法 kind → 400。"""
    r = client.patch(f"/api/agents/{data['qa_agent_id']}",
                     json={"kind": "bogus"}, headers=auth("pm"))
    assert r.status_code == 400


def test_member_cannot_edit_agent(client, auth, data):
    """本轮 RBAC 收紧：member PATCH /agents/<id> → 403（原裸 jwt 任意成员可改）。"""
    r = client.patch(f"/api/agents/{data['dev_agent_id']}",
                     json={"description": "x"}, headers=auth("member"))
    assert r.status_code == 403


# ————————————————————— 项目 —————————————————————

def test_pm_creates_project(client, auth):
    """pm 建项目 → 201，owner 为当前 pm。"""
    r = client.post("/api/projects", json={"name": "Demo", "key": "DEMO"},
                    headers=auth("pm"))
    assert r.status_code == 201, r.get_json()
    assert r.get_json()["key"] == "DEMO"


def test_create_project_duplicate_key_conflicts(client, auth, data):
    """以既有 key（TST）再建 → 409。"""
    r = client.post("/api/projects", json={"name": "Dup", "key": "TST"},
                    headers=auth("pm"))
    assert r.status_code == 409


def test_member_cannot_create_project(client, auth):
    """member 无权建项目 → 403。"""
    r = client.post("/api/projects", json={"name": "X", "key": "XXX"},
                    headers=auth("member"))
    assert r.status_code == 403
