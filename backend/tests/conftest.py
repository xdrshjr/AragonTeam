"""pytest fixtures（Phase-2 §6.1）。

【R-02】app 用 TestConfig（内存库 + StaticPool），conftest 在同一 app fixture 的
app_context 内建表并注入最小 fixture，请求与建表共享同一条内存连接、表恒可见。
【R-03】限流存储随每个测试的独立 app 实例重建；另加 autouse reset 双保险，
保证失败登录计数不跨用例污染、429 断言确定。
"""
import pytest

from app import create_app
from config import Config, TestConfig
from extensions import db, utcnow
from models.user import User
from models.agent import Agent
from models.project import Project
from models.requirement import Requirement
from services import ratelimit

# 各角色 seed 账号（用户名, 密码）。Phase-3 增 member2 供跨用户 RBAC / 通知测试。
CREDENTIALS = {
    "admin": ("admin", "admin123"),
    "pm": ("pm", "pm123"),
    "member": ("member", "member123"),
    "member2": ("member2", "member2123"),
}


def _install_fixtures() -> dict:
    """注入最小 fixture：admin/pm/member/member2、dev/qa Agent 各一、一个项目。"""
    admin = User(username="admin", role="admin", display_name="Ada", avatar_color="#C15F3C")
    admin.set_password("admin123")
    pm = User(username="pm", role="pm", display_name="Peter", avatar_color="#3B6EA5")
    pm.set_password("pm123")
    member = User(username="member", role="member", display_name="Mia", avatar_color="#6E8B3D")
    member.set_password("member123")
    # Phase-3：第二名 member，供「跨用户」RBAC / 通知场景（如 member2 评论 member 的单）。
    member2 = User(username="member2", role="member", display_name="Max", avatar_color="#8A5A9B")
    member2.set_password("member2123")
    db.session.add_all([admin, pm, member, member2])

    dev = Agent(name="dev-agent", kind="dev", status="idle", description="dev agent")
    qa = Agent(name="qa-agent", kind="qa", status="idle", description="qa agent")
    db.session.add_all([dev, qa])
    db.session.flush()

    project = Project(name="Test Project", key="TST", owner_id=pm.id)
    db.session.add(project)
    db.session.commit()

    return {
        "admin_id": admin.id, "pm_id": pm.id, "member_id": member.id,
        "member2_id": member2.id,
        "dev_agent_id": dev.id, "qa_agent_id": qa.id, "project_id": project.id,
    }


@pytest.fixture
def app(tmp_path):
    app = create_app(TestConfig)
    # 【ticket-document-management §5.3】UPLOAD_DIR **逐用例注入**，绝不写进 TestConfig：
    # 那是类级常量，全套用例共享一份，写死就等于所有用例共用一个目录——而且测试
    # 绝不允许写进真实的 backend/var/uploads。tmp_path 由 pytest 自动清理。
    app.config["UPLOAD_DIR"] = str(tmp_path / "uploads")
    with app.app_context():
        app.config["FIXTURE_IDS"] = _install_fixtures()
        yield app
        db.session.remove()


@pytest.fixture
def file_app(tmp_path):
    """真实**文件**库上的 app 工厂：反复调用即模拟「进程重启」，库文件跨次保留。

    全部既有用例都跑在 `sqlite:///:memory:` 上，「重启后数据还在吗」这个问题在 CI 里
    从未被回答过（data-persistence §1）。本 fixture 就是那个回答。

    用法：`make, db_path = file_app`；`make()` 返回一个新的 app（默认开 seed）。

    【评审 P1-5】开关一律用 **config 子类属性覆盖**（不是 `monkeypatch.setenv`）——
    Config 的字段在 import 时求值一次，用例里改环境变量对已导入的类无效，写了也是假绿。
    【评审 P2-15】每次重建前 dispose 上一个引擎：Windows 上 SQLite 文件句柄未释放会让
    tmp_path 清理抛 PermissionError（本项目主力平台是 Windows，这不是理论风险）。
    """
    db_path = tmp_path / "aragon.db"
    made = []

    def _release(app):
        with app.app_context():
            db.session.remove()
            db.engine.dispose()

    def _make(seed=True, **overrides):
        if made:                                  # 上一个 app 先彻底放掉连接，再模拟重启
            _release(made[-1])
        attrs = {
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path.as_posix()}",
            "SEED_ON_STARTUP": seed,
            "TESTING": True,
            # 同上：真实文件库的 app 也绝不允许写进 backend/var/uploads。
            "UPLOAD_DIR": str(tmp_path / "uploads"),
            **overrides,                          # 如 RELEASE_STALE_LOCKS_ON_STARTUP=False
        }
        FileConfig = type("FileConfig", (Config,), attrs)
        app = create_app(FileConfig)
        made.append(app)
        return app

    yield _make, db_path

    for app in made:                              # teardown：确保没有句柄留在 tmp_path 上
        _release(app)


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
def disabled_user(app, data):
    """把 member 停用并返回其 id（lifecycle-and-governance §2.5）。

    直接改库而不走 PATCH：本 fixture 服务于「停用之后会发生什么」的用例，
    停用动作本身的门禁另有专门用例覆盖。
    """
    with app.app_context():
        user = db.session.get(User, data["member_id"])
        user.is_active = False
        db.session.commit()
        return user.id


@pytest.fixture
def archived_project(app, data):
    """把 fixture 项目归档并返回其 id（§2.6）。"""
    with app.app_context():
        project = db.session.get(Project, data["project_id"])
        project.archived_at = utcnow()
        db.session.commit()
        return project.id


@pytest.fixture
def bulk_tickets(app):
    """bulk_tickets(n, status='new') → 直接落库 n 张需求单，供看板分页用例灌数据。

    走模型而非 HTTP：n 可能是几百，逐个走 REST 会让用例慢到没法跑。
    """
    def _bulk(n, status="new", project_id=None):
        with app.app_context():
            for i in range(n):
                db.session.add(Requirement(
                    title=f"批量需求 {i}", status=status,
                    project_id=project_id, position=i,
                ))
            db.session.commit()
    return _bulk


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
