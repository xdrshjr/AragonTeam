"""pytest fixtures（Phase-2 §6.1）。

【R-02】app 用 TestConfig（内存库 + StaticPool），conftest 在同一 app fixture 的
app_context 内建表并注入最小 fixture，请求与建表共享同一条内存连接、表恒可见。
【R-03】限流存储随每个测试的独立 app 实例重建；另加 autouse reset 双保险，
保证失败登录计数不跨用例污染、429 断言确定。
"""
import pytest

from app import create_app
from config import TestConfig
from extensions import db
from models.user import User
from models.agent import Agent
from models.project import Project
from services import ratelimit

# 各角色 seed 账号（用户名, 密码）。
CREDENTIALS = {
    "admin": ("admin", "admin123"),
    "pm": ("pm", "pm123"),
    "member": ("member", "member123"),
}


def _install_fixtures() -> dict:
    """注入最小 fixture：admin/pm/member 各一、dev/qa Agent 各一、一个项目。"""
    admin = User(username="admin", role="admin", display_name="Ada", avatar_color="#C15F3C")
    admin.set_password("admin123")
    pm = User(username="pm", role="pm", display_name="Peter", avatar_color="#3B6EA5")
    pm.set_password("pm123")
    member = User(username="member", role="member", display_name="Mia", avatar_color="#6E8B3D")
    member.set_password("member123")
    db.session.add_all([admin, pm, member])

    dev = Agent(name="dev-agent", kind="dev", status="idle", description="dev agent")
    qa = Agent(name="qa-agent", kind="qa", status="idle", description="qa agent")
    db.session.add_all([dev, qa])
    db.session.flush()

    project = Project(name="Test Project", key="TST", owner_id=pm.id)
    db.session.add(project)
    db.session.commit()

    return {
        "admin_id": admin.id, "pm_id": pm.id, "member_id": member.id,
        "dev_agent_id": dev.id, "qa_agent_id": qa.id, "project_id": project.id,
    }


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        app.config["FIXTURE_IDS"] = _install_fixtures()
        yield app
        db.session.remove()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def data(app):
    """最小 fixture 的关键 id（admin_id/pm_id/member_id/dev_agent_id/qa_agent_id/project_id）。"""
    return app.config["FIXTURE_IDS"]


@pytest.fixture(autouse=True)
def _reset_ratelimit(app):
    # 【R-03】每用例前复位限流计数（app 已提供隔离，此为双保险）。
    with app.app_context():
        ratelimit.reset()
    yield


@pytest.fixture
def login(client):
    def _login(username, password):
        r = client.post("/api/auth/login", json={"username": username, "password": password})
        return r
    return _login


@pytest.fixture
def auth(client):
    """auth('admin'|'pm'|'member') -> {'Authorization': 'Bearer ...'}。"""
    def _auth(role):
        username, password = CREDENTIALS[role]
        r = client.post("/api/auth/login", json={"username": username, "password": password})
        assert r.status_code == 200, r.get_json()
        return {"Authorization": f"Bearer {r.get_json()['token']}"}
    return _auth


@pytest.fixture
def make_requirement(client, auth):
    """便捷：以 pm 建需求，可选指派，返回 requirement dict。"""
    def _make(title="需求", priority="medium", assignee=None):
        headers = auth("pm")
        r = client.post("/api/requirements", json={"title": title, "priority": priority},
                        headers=headers)
        assert r.status_code == 201, r.get_json()
        req = r.get_json()
        if assignee:
            atype, aid = assignee
            r2 = client.patch(f"/api/requirements/{req['id']}/assign",
                              json={"assignee_type": atype, "assignee_id": aid}, headers=headers)
            assert r2.status_code == 200, r2.get_json()
            req = r2.get_json()
        return req
    return _make


@pytest.fixture
def make_bug(client, auth):
    """便捷：以 pm 建 BUG，可选指派，返回 bug dict。"""
    def _make(title="缺陷", severity="major", assignee=None):
        headers = auth("pm")
        r = client.post("/api/bugs", json={"title": title, "severity": severity}, headers=headers)
        assert r.status_code == 201, r.get_json()
        bug = r.get_json()
        if assignee:
            atype, aid = assignee
            r2 = client.patch(f"/api/bugs/{bug['id']}/assign",
                              json={"assignee_type": atype, "assignee_id": aid}, headers=headers)
            assert r2.status_code == 200, r2.get_json()
            bug = r2.get_json()
        return bug
    return _make
