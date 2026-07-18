"""幂等 seed（§2.2 D）——首次启动填充 mock 数据，保证前端开箱即用。

幂等策略：先判 User.query.count() == 0 再插（【§7 seed 非幂等风险】）。
覆盖各状态列，便于看板一启动就有内容。
口令统一 pbkdf2:sha256（【R-06】）。
"""
from extensions import db
from models.user import User
from models.agent import Agent
from models.project import Project
from models.requirement import Requirement
from models.bug import Bug
from models.activity import Activity
from models.comment import Comment
from models.notification import Notification

# 头像底色（暖色系，与 auth._PALETTE 一致）。
_COLORS = ["#C15F3C", "#3B6EA5", "#6E8B3D", "#8A5A9B", "#C99A2E", "#4B8B8B"]


def seed_if_empty():
    """若 users 表为空则填充 mock 数据；否则跳过（幂等）。"""
    if User.query.count() > 0:
        return False

    # —— 用户：admin / pm / 两名 member ——
    users = {
        "admin": User(username="admin", role="admin", display_name="Ada（管理员）",
                      email="admin@aragon.dev", avatar_color=_COLORS[0]),
        "pm": User(username="pm", role="pm", display_name="Peter（项目经理）",
                   email="pm@aragon.dev", avatar_color=_COLORS[1]),
        "alice": User(username="alice", role="member", display_name="Alice",
                      email="alice@aragon.dev", avatar_color=_COLORS[2]),
        "bob": User(username="bob", role="member", display_name="Bob",
                    email="bob@aragon.dev", avatar_color=_COLORS[3]),
    }
    users["admin"].set_password("admin123")
    users["pm"].set_password("pm123")
    users["alice"].set_password("alice123")
    users["bob"].set_password("bob123")
    for u in users.values():
        db.session.add(u)

    # —— Agent：dev-agent / qa-agent ——
    dev_agent = Agent(name="dev-agent", kind="dev", status="idle",
                      description="自动开发 Agent：认领需求、生成实现与提交。")
    qa_agent = Agent(name="qa-agent", kind="qa", status="idle",
                     description="自动测试 Agent：执行测试用例、回归验证。")
    db.session.add_all([dev_agent, qa_agent])

    db.session.flush()  # 拿到各实体 id

    # —— 默认项目 ——
    project = Project(name="AragonTeam Platform", key="ARA",
                      description="AI 时代的团队协作与研发管理平台自身。",
                      owner_id=users["pm"].id)
    db.session.add(project)
    db.session.flush()

    # —— 示例需求：覆盖各状态列 ——
    # (title, status, priority, assignee) — assignee: (type, id) 或 None
    req_specs = [
        ("搭建 AragonTeam 项目骨架", "done", "high", ("user", users["pm"].id)),
        ("需求看板支持拖拽排序", "reviewing", "high", ("user", users["alice"].id)),
        ("接入 dev-agent 自动认领需求", "testing", "urgent", ("agent", dev_agent.id)),
        ("统一全局错误响应契约", "in_development", "medium", ("user", users["bob"].id)),
        ("BUG 看板与需求看板打通", "assigned", "medium", ("agent", dev_agent.id)),
        ("导出协作活动时间线报表", "new", "low", None),
        ("修复登录态刷新丢失问题", "bug_fixing", "high", ("user", users["alice"].id)),
    ]
    requirements = []
    for idx, (title, status, priority, assignee) in enumerate(req_specs):
        at, ai = (assignee if assignee else (None, None))
        r = Requirement(
            title=title, description=f"{title} —— seed 示例需求。",
            status=status, priority=priority, project_id=project.id,
            assignee_type=at, assignee_id=ai,
            reporter_id=users["pm"].id, position=idx,
        )
        requirements.append(r)
        db.session.add(r)
    db.session.flush()

    # —— 示例 BUG：覆盖各状态列 ——
    # (title, status, severity, assignee, related_req_index)
    bug_specs = [
        ("拖拽后偶发卡片位置错乱", "open", "major", None, None),
        ("Agent 指派后头像不显示", "assigned", "minor", ("user", users["bob"].id), None),
        ("看板列计数未实时刷新", "fixing", "major", ("agent", qa_agent.id), None),
        ("登录 token 过期未跳转", "verifying", "critical", ("user", users["alice"].id), 6),
        ("次要文案错别字", "closed", "trivial", ("user", users["bob"].id), None),
    ]
    for idx, (title, status, severity, assignee, rel) in enumerate(bug_specs):
        at, ai = (assignee if assignee else (None, None))
        b = Bug(
            title=title, description=f"{title} —— seed 示例缺陷。",
            status=status, severity=severity, project_id=project.id,
            assignee_type=at, assignee_id=ai,
            related_requirement_id=(requirements[rel].id if rel is not None else None),
            reporter_id=users["pm"].id, position=idx,
        )
        db.session.add(b)
    db.session.flush()

    # —— 若干审计活动（时间线 seed）——
    Activity.log("requirement", requirements[0].id, "created",
                 actor=("user", users["pm"].id), to_status="new",
                 message="创建需求「搭建 AragonTeam 项目骨架」")
    Activity.log("requirement", requirements[2].id, "assigned",
                 actor=("user", users["pm"].id), from_status="assigned",
                 to_status="assigned", message="指派给 Agent「dev-agent」")
    # Phase-2：一条 Agent 推进活动，让 agent_advanced 动作在 feed / 仪表盘一启动就可见。
    Activity.log("requirement", requirements[2].id, "agent_advanced",
                 actor=("agent", dev_agent.id), from_status="assigned",
                 to_status="in_development",
                 message="dev-agent 已认领需求，拆解任务、拉起开发分支。")
    Activity.log("requirement", requirements[1].id, "moved",
                 actor=("user", users["alice"].id), from_status="testing",
                 to_status="reviewing", message="状态 testing → reviewing")

    # —— Phase-2：示例评论（人 + Agent + 系统混合讨论），让工单详情 feed 开箱有料 ——
    demo_req = requirements[2]  # 「接入 dev-agent 自动认领需求」
    db.session.add_all([
        Comment(entity_type="requirement", entity_id=demo_req.id,
                author_type="user", author_id=users["pm"].id,
                body="这条需求交给 dev-agent 先跑起来，测试阶段再让 qa-agent 接手。"),
        Comment(entity_type="requirement", entity_id=demo_req.id,
                author_type="agent", author_id=dev_agent.id,
                body="dev-agent 已认领需求，拆解任务、拉起开发分支。"),
        Comment(entity_type="requirement", entity_id=demo_req.id,
                author_type="system", author_id=None,
                body="工单已从「已指派」流转至「开发中」。"),
        Comment(entity_type="requirement", entity_id=demo_req.id,
                author_type="user", author_id=users["alice"].id,
                body="记得同步一下接口契约，别改动 Phase-1 的返回结构。"),
    ])

    # —— Phase-3：示例通知（未读 / 已读混合），让通知铃铛开箱即有内容（§3.1）——
    # 收件人均为人类 member（alice / bob）；点击 entity 直达对应工单抽屉。
    db.session.add_all([
        Notification(user_id=users["alice"].id, type="assigned",
                     entity_type="requirement", entity_id=requirements[1].id,
                     actor_type="user", actor_id=users["pm"].id, is_read=False,
                     message="指派给你：需求「需求看板支持拖拽排序」"),
        Notification(user_id=users["alice"].id, type="agent_advanced",
                     entity_type="requirement", entity_id=demo_req.id,
                     actor_type="agent", actor_id=dev_agent.id, is_read=False,
                     message="dev-agent 把需求「接入 dev-agent 自动认领需求」推进：assigned → in_development"),
        Notification(user_id=users["bob"].id, type="assigned",
                     entity_type="requirement", entity_id=requirements[3].id,
                     actor_type="user", actor_id=users["pm"].id, is_read=False,
                     message="指派给你：需求「统一全局错误响应契约」"),
        Notification(user_id=users["bob"].id, type="commented",
                     entity_type="requirement", entity_id=demo_req.id,
                     actor_type="user", actor_id=users["alice"].id, is_read=True,
                     message="需求「接入 dev-agent 自动认领需求」有新评论：记得同步一下接口契约…"),
    ])

    db.session.commit()
    return True
