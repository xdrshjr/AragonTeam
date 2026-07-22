"""幂等 seed（§2.2 D / data-persistence-and-seed-slimming §2.5）——首次启动填充
**每类恰好一条**示例数据，让前端开箱有内容、又不至于让新用户第一眼全是假数据。

注意（real-agent-execution §0 M3）：这里是**演示用示例种子**（账号 / Agent / 工单），
由 `SEED_ON_STARTUP` 门控、测试环境已关闭，**并非业务 Mock**（唯一的业务 Mock 是
Agent 执行引擎，已由该迭代真实化）。

幂等策略：先判 `User.query.count() == 0` 再插（【§7 seed 非幂等风险】）。判据不改，
存量库不会被二次 seed。

**每写一行就登记一条 `SeedRecord`**（§5.2），在同一个事务里提交——这是
`tools/purge_demo_data.py` 日后精确识别演示数据的**唯一**依据。新增任何一行种子数据
都必须同步登记，否则它就变成了一条永远清不掉的「无出身」数据。
"""
from flask import current_app

from extensions import db
from models.user import User
from models.agent import Agent
from models.project import Project
from models.version import Version
from models.plan import Plan
from models.requirement import Requirement
from models.bug import Bug
from models.activity import Activity
from models.comment import Comment
from models.notification import Notification
from models.seed_record import SeedRecord
from services import avatars


def seed_if_empty():
    """若 users 表为空则填充示例种子数据（每类 1 条，共 10 行）；否则跳过（幂等）。

    Returns:
        True 表示本次确实写入了种子数据；False 表示库非空、已跳过。
    """
    if User.query.count() > 0:
        return False

    # —— 用户：只留 admin 一个账号 ——
    # 其余成员由管理台真实创建（POST /api/users 已具备）。「末任管理员不变量」
    # （lifecycle.would_orphan_admins）因此更关键——它已实现，本轮不动。
    # 【self-service-registration §2.1 A-3】用户名 / 口令改读 ROOT_ADMIN_* 配置：
    # 自定义了 ROOT_ADMIN_USERNAME=root 的部署，seed 直接建 root，随后 ensure_root_admin
    # 认领同一行——**不会出现两个管理员**。默认值与既有逐字相同，存量库不受影响。
    config = current_app.config
    root_username = config["ROOT_ADMIN_USERNAME"].strip()
    admin = User(username=root_username, role="admin",
                 display_name=config["ROOT_ADMIN_DISPLAY_NAME"],
                 email=config["ROOT_ADMIN_EMAIL"], source="seed",
                 # 底色沿用调色板首色（与迁移前逐字节相同），不改为 pick_color——
                 # 那会让存量演示账号的头像颜色无缘无故变一次。
                 avatar_color=avatars.PALETTE[0])
    admin.set_password(config["ROOT_ADMIN_PASSWORD"])
    db.session.add(admin)

    # —— Agent：只留 dev-agent ——
    # 不留 qa-agent 是「每类一条」的字面要求。演示 dev→qa 交接需要用户在 Agents 页
    # 点一下「新建 Agent」（该入口早已存在）；因为示例需求不指派、不进 testing，
    # 所以不会出现「推到 testing 后无人接手」的卡死。
    dev_agent = Agent(name="dev-agent", kind="dev", status="idle",
                      description="自动开发 Agent：认领需求、生成实现与提交。")
    db.session.add(dev_agent)

    db.session.flush()  # 拿到 admin / dev_agent 的 id

    # —— 默认项目 ——
    project = Project(name="AragonTeam Platform", key="ARA",
                      description="AI 时代的团队协作与研发管理平台自身。",
                      owner_id=admin.id)
    db.session.add(project)
    db.session.flush()

    # —— 示例版本 + 示例计划（version-plan-hierarchy §4.6，守住「每类一条」）——
    # 项目 → 版本 → 计划 → 需求/BUG 四层树的示例落点：让前端开箱即见完整层级。
    version = Version(name="v1.0 首个可用版本", project_id=project.id, status="active",
                      description="演示「版本 → 计划 → 需求/BUG」层级的首个版本。",
                      owner_id=admin.id, position=0)
    db.session.add(version)
    db.session.flush()
    plan = Plan(name="迭代 1：打通主流程", version_id=version.id, project_id=project.id,
                status="active", description="第一轮迭代：把需求流转与 BUG 流转主链路跑通。",
                position=0)
    db.session.add(plan)
    db.session.flush()

    # —— 示例需求 / 示例 BUG：一律初始状态且**未指派**，并归属到示例计划 ——
    # 原 seed 把需求预置在 testing、把 BUG 预置在 fixing 并指派给 Agent，历史上多次
    # 造成「泊死单」（feature-completeness 与 scale-and-project-scope 两轮的救火）。
    # 未指派的 new/open 单既能演示全流程，又不可能一启动就卡住。
    requirement = Requirement(
        title="示例需求：熟悉需求流转",
        description="这是一条示例需求，用于演示「新建 → 指派（人 / Agent）→ 开发 → 测试 →"
                    "审批 → 完成」的完整流转。可以直接拖动它，或删除后建自己的单。",
        status="new", priority="medium", project_id=project.id,
        plan_id=plan.id,
        assignee_type=None, assignee_id=None,
        reporter_id=admin.id, position=0,
    )
    db.session.add(requirement)

    bug = Bug(
        title="示例缺陷：熟悉 BUG 流转",
        description="这是一条示例缺陷，用于演示「新建 → 指派 → 修复中 → 验证中 → 关闭」"
                    "的完整流转。可以直接拖动它，或删除后建自己的单。",
        status="open", severity="major", project_id=project.id,
        plan_id=plan.id,
        assignee_type=None, assignee_id=None,
        related_requirement_id=None,
        reporter_id=admin.id, position=0,
    )
    db.session.add(bug)
    db.session.flush()

    # —— 示例评论：作者是 dev-agent（不是 admin）——
    # 只剩 admin 一个人类账号之后，让 admin 评论自己的单再给自己发通知，会撞上
    # services/notifications.py 的「不给自己发」不变量：走 notify() 发不出来，
    # 硬塞则等于让示例数据违反平台自己的规则。改由 Agent 发言，语义链自洽，
    # 且顺带演示了「Agent 会在工单里说话」这一核心卖点。
    comment = Comment(entity_type="requirement", entity_id=requirement.id,
                      author_type="agent", author_id=dev_agent.id,
                      body="我是 dev-agent。把这条需求指派给我，我就会按状态机推进它，"
                           "并在这里留下每一步的工作说明。")
    db.session.add(comment)

    # —— 示例审计：需求的创建事件，让时间线一启动就有内容 ——
    activity = Activity.log(
        "requirement", requirement.id, "created",
        actor=("user", admin.id), to_status="new",
        message="创建需求「示例需求：熟悉需求流转」")

    # —— 示例通知：dev-agent 评论了 admin 报的单 ——
    # 施动者是 Agent 而非人类，天然绕开「不给自己发」不变量（§2.5-4）。
    notification = Notification(
        user_id=admin.id, type="commented",
        entity_type="requirement", entity_id=requirement.id,
        actor_type="agent", actor_id=dev_agent.id, is_read=False,
        message="需求「示例需求：熟悉需求流转」有新评论：我是 dev-agent…")
    db.session.add(notification)

    # notification_preferences 有意 **0 条**：缺省全 true 由
    # services/notification_prefs.py 提供（「无行=启用」），无需落行。

    db.session.flush()  # 拿到 comment / activity / notification 的 id 再登记

    for entity_type, entity in (
        ("user", admin), ("agent", dev_agent), ("project", project),
        # 【version-plan-hierarchy §4.6】版本 / 计划各登记一条：与 SEED_ENTITY_TYPES 及
        # purge 的 _entity_models 一一对应，否则会变孤岛或被 purge 误判为孤儿删掉登记。
        ("version", version), ("plan", plan),
        ("requirement", requirement), ("bug", bug), ("comment", comment),
        ("activity", activity), ("notification", notification),
    ):
        SeedRecord.mark(entity_type, entity.id)

    db.session.commit()
    return True
