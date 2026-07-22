"""新 seed 契约回归（data-persistence-and-seed-slimming §6.1）。

「每一类示例数据只保留一个」是本轮需求的原话；这里把它变成可执行的断言。
"""
from extensions import db
from models.activity import Activity
from models.agent import Agent
from models.bug import Bug
from models.comment import Comment
from models.notification import Notification
from models.notification_preference import NotificationPreference
from models.plan import Plan
from models.project import Project
from models.requirement import Requirement
from models.seed_record import SeedRecord
from models.user import User
from models.version import Version

# (SeedRecord.entity_type, 模型) —— 登记类别与实体表的对应关系。
# 【version-plan-hierarchy §4.6】seed 追加 1 版本 + 1 计划 → 每类仍恰好一条。
_SEEDED = (
    ("user", User), ("agent", Agent), ("project", Project),
    ("version", Version), ("plan", Plan),
    ("requirement", Requirement), ("bug", Bug), ("comment", Comment),
    ("activity", Activity), ("notification", Notification),
)


def test_seed_writes_exactly_one_row_per_category(file_app):
    make, _ = file_app
    app = make()
    with app.app_context():
        for _entity_type, model in _SEEDED:
            assert model.query.count() == 1, model.__tablename__
        # 缺省「无行=启用」由 services/notification_prefs.py 提供，有意不落行。
        assert NotificationPreference.query.count() == 0


def test_seed_ticket_is_unassigned_and_initial(file_app):
    make, _ = file_app
    app = make()
    with app.app_context():
        req = Requirement.query.one()
        assert req.status == "new"
        assert req.assignee_type is None and req.assignee_id is None
        bug = Bug.query.one()
        assert bug.status == "open"
        assert bug.assignee_type is None and bug.assignee_id is None


def test_seed_ticket_belongs_to_seed_plan(file_app):
    """【version-plan-hierarchy §4.6】示例需求 / BUG 的 plan_id 指向示例计划。"""
    make, _ = file_app
    app = make()
    with app.app_context():
        version = Version.query.one()
        plan = Plan.query.one()
        assert plan.version_id == version.id
        assert plan.project_id == version.project_id     # 反范式一致
        assert Requirement.query.one().plan_id == plan.id
        assert Bug.query.one().plan_id == plan.id


def test_seed_registers_every_row(file_app):
    make, _ = file_app
    app = make()
    with app.app_context():
        assert SeedRecord.query.count() == 10
        for entity_type, model in _SEEDED:
            record = SeedRecord.query.filter_by(entity_type=entity_type).one()
            assert db.session.get(model, record.entity_id) is not None, entity_type


def test_seed_notification_actor_is_not_the_recipient(file_app):
    """【评审 P1-10】示例通知不得违反「不给自己发」不变量。"""
    make, _ = file_app
    app = make()
    with app.app_context():
        admin = User.query.filter_by(username="admin").one()
        dev_agent = Agent.query.filter_by(name="dev-agent").one()
        notif = Notification.query.one()
        assert notif.type == "commented"
        assert notif.user_id == admin.id
        assert notif.actor_type == "agent" and notif.actor_id == dev_agent.id
        # 评论作者同样是 Agent，语义链闭合：admin 报单 → dev-agent 留言 → admin 收到通知。
        comment = Comment.query.one()
        assert comment.author_type == "agent" and comment.author_id == dev_agent.id


def test_seed_keeps_only_admin_and_dev_agent(file_app):
    make, _ = file_app
    app = make()
    with app.app_context():
        assert [u.username for u in User.query.all()] == ["admin"]
        assert [a.name for a in Agent.query.all()] == ["dev-agent"]


def test_admin_can_login_with_seeded_credentials(file_app):
    make, _ = file_app
    resp = make().test_client().post(
        "/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["user"]["role"] == "admin"
