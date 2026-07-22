"""资源生命周期守卫（lifecycle-and-governance §2.2 / §2.4 / §2.6 / §2.7）。

本模块收敛本轮全部「破坏性动作的前置检查」与「取消指派」语义，路由层只做
「取参 → 调服务 → 渲染契约」。**禁止**在路由里内联第二份引用检查——那正是
`_next_position` 被内联成两份、必须「两处同步修改」的教训（agent_runner.py:68）。

三条统一契约：
- 引用完整性一律**前置检查**，绝不依赖数据库外键异常兜底（IntegrityError 会被
  errors.py 的兜底处理器变成 500，用户看到「internal server error」而不是
  「这个项目还有 12 张单」）。
- 冲突一律返回 **409**（请求本身合法，是系统状态不允许），且 detail 带可操作计数。
- 本轮新增的三种 409 **都不带 `allowed`**——前端看板拖拽的错误分流以 `err.allowed`
  是否存在为判据，不得被误伤（spec §4.3）。
"""
from flask import jsonify

from models.activity import Activity
from models.bug import Bug
from models.comment import Comment
from models.document_link import DocumentLink
from models.notification import Notification
from models.plan import Plan
from models.requirement import Requirement
from models.user import User
from models.version import Version
from services import notifications, workflow


# ————————————————————— 末任管理员不变量（§2.2）—————————————————————

def would_orphan_admins(target_user, *, new_role=None, new_active=None) -> bool:
    """本次变更是否会让系统里**有效管理员**（role=admin 且 is_active）数量归零。

    有效管理员 = 能真正调用 @require_role("admin") 端点的人。停用的 admin 不算数
    （其 token 已被 blocklist 拒绝，见 §2.5），故停用最后一个 admin 与降级最后一个
    admin 是同一个死锁，必须由同一个判据拦住。

    Args:
        target_user: 被改动的用户。
        new_role: 变更后的角色；None 表示本次不改角色。
        new_active: 变更后的启用状态；None 表示本次不改。

    Returns:
        True 表示该变更会造成治理死锁，调用方应返回 409。
    """
    still_admin = (new_role or target_user.role) == "admin"
    still_active = target_user.is_active if new_active is None else new_active
    if still_admin and still_active:
        return False                      # 目标本人变更后仍是有效管理员 → 不可能归零
    return active_admin_count(exclude_id=target_user.id) == 0


def active_admin_count(*, exclude_id=None) -> int:
    """当前有效管理员（admin 且 is_active）人数，可排除某个 id。"""
    q = User.query.filter(User.role == "admin", User.is_active.is_(True))
    if exclude_id is not None:
        q = q.filter(User.id != exclude_id)
    return q.count()


def conflict_last_admin():
    """末任管理员 409 契约体。稳定错误串，勿更名（对外错误契约，CLAUDE.md §五）。"""
    return jsonify({
        "error": "cannot remove the last administrator",
        "detail": {
            "reason": "at least one active admin must remain",
            "active_admins": active_admin_count(),
        },
    }), 409


# ————————————————— 根管理员保护（self-service-registration §2.1 A-4）—————————————————

def is_protected_root(user) -> bool:
    """该用户是否为受保护的根管理员。

    用 `getattr` 兜底而不是直接读属性：`purge` 工具与部分测试会传入轻量对象，
    多一层容忍不会掩盖任何真实缺陷（列不存在时 schema_sync 早已在启动期报错）。
    """
    return bool(getattr(user, "is_root", False))


def conflict_root_admin(reason: str):
    """根管理员受保护 409。稳定错误串，勿更名（对外错误契约，CLAUDE.md §五）。

    与本模块既有三种 409 一致：**不带 `allowed` 键**——前端看板拖拽以 `err.allowed`
    是否存在分流错误，不得误伤（spec §4.3）。

    Args:
        reason: 具体到哪一条保护规则被触发，直接呈现给管理员。
    """
    return jsonify({
        "error": "root administrator is protected",
        "detail": {
            "reason": reason,
            "hint": "change ROOT_ADMIN_* in the backend config and restart",
        },
    }), 409


# ————————————————————— 引用守卫（§2.6 / §2.7）—————————————————————

def project_references(project_id: int) -> dict:
    """该项目名下的工单与版本计数（任何状态都算——删项目会让它们失去归属）。

    【version-plan-hierarchy §3.5】追加 `versions`：`versions.project_id` 是**真外键**，
    删有版本的项目会触 IntegrityError → 兜底 500，用户看到「internal server error」而非
    「还有 N 个版本」。计划被版本传递覆盖（有计划必有版本），故只需数版本。
    """
    return {
        "requirements": Requirement.query.filter_by(project_id=project_id).count(),
        "bugs": Bug.query.filter_by(project_id=project_id).count(),
        "versions": Version.query.filter_by(project_id=project_id).count(),
    }


def conflict_project_has_tickets(refs: dict):
    """项目仍有工单 / 版本的 409 契约体（detail 带可操作计数与建议）。"""
    return jsonify({
        "error": "project still has tickets",
        "detail": {**refs,
                   "hint": "archive the project instead, or clear its versions and tickets"},
    }), 409


def version_references(version_id: int) -> dict:
    """该版本名下的计划计数（version-plan-hierarchy §3.5）。删版本前须为空。"""
    return {
        "plans": Plan.query.filter_by(version_id=version_id).count(),
    }


def conflict_version_has_plans(refs: dict):
    """版本仍有计划的 409 契约体（无 `allowed`，前端看板拖拽错误分流不得误伤）。"""
    return jsonify({
        "error": "version still has plans",
        "detail": {**refs, "hint": "delete or archive its plans first"},
    }), 409


def plan_references(plan_id: int) -> dict:
    """该计划名下的工单计数（version-plan-hierarchy §3.5）。

    计划与工单**无 DB 外键**，删计划不会触 IntegrityError，但仍前置守卫：避免留下指向
    已删计划的悬挂 `plan_id`（保持数据自洽）。
    """
    return {
        "requirements": Requirement.query.filter_by(plan_id=plan_id).count(),
        "bugs": Bug.query.filter_by(plan_id=plan_id).count(),
    }


def conflict_plan_has_tickets(refs: dict):
    """计划仍有工单的 409 契约体（无 `allowed`）。"""
    return jsonify({
        "error": "plan still has tickets",
        "detail": {**refs, "hint": "move its tickets to another plan or delete them first"},
    }), 409


def agent_open_workload(agent_id: int) -> dict:
    """该 Agent 名下**未终态**的在手工单计数（terminal 单不阻止删除）。

    「未终态」判据复用 workflow.is_terminal，**不得内联一份状态清单**——那是会
    随邻接表漂移的第二真相。
    """
    out = {}
    for entity, model in (("requirements", Requirement), ("bugs", Bug)):
        rows = model.query.filter_by(assignee_type="agent", assignee_id=agent_id).all()
        key = "requirement" if entity == "requirements" else "bug"
        out[entity] = sum(1 for r in rows if not workflow.is_terminal(key, r.status))
    return out


def conflict_agent_has_open_tickets(load: dict):
    """Agent 仍有在手工单的 409 契约体。"""
    return jsonify({
        "error": "agent still holds open tickets",
        "detail": {**load, "hint": "reassign or unassign them first"},
    }), 409


# ————————————————————— 工单级联清理（data-persistence §2.7）—————————————————————

def delete_ticket_cascade(entity: str, ticket) -> dict:
    """清理一张工单的全部引用，**但不删除工单本体**。

    此前 `routes/requirements.py::delete_requirement` 与 `routes/bugs.py::delete_bug`
    各内联了一份，`tools/purge_demo_data.py` 是第三个调用点——再复制一份就必然漂移，
    与本模块开篇「禁止在路由里内联第二份引用检查」的约定同源。

    Args:
        entity: "requirement" | "bug"。
        ticket: Requirement / Bug 实例（调用方保证非 None）。

    Returns:
        {"comments": int, "notifications": int, "activities": int, "document_links": int}
        —— 各表实际删除的行数。`document_links` 是 ticket-document-management 的**追加**键，
        既有键名与语义逐字不变（调用方 routes/* 与 purge_demo_data 均按键名读取）。

    契约（三条，逐条对应一个曾经踩过的坑）：
    1. **不 commit**，也**不 db.session.delete(ticket)**。工单本体由调用方删除——
       路由要在删除后返回 204，purge 要把几十张单放进同一个事务，两者对「何时删本体、
       何时提交」的诉求不同，服务层不替调用方决定。
    2. `Bug.related_requirement_id` 置空**只在 entity == "requirement" 时执行**。
       实测 `routes/bugs.py::delete_bug` **没有**这一步（BUG 不被别的 BUG 引用），
       无条件执行等于给 BUG 删除路径加了一次多余的全表 UPDATE —— 那就是行为漂移。
    3. 顺序逐字保留原路由：related 置空 → comments → notifications → activities。
       删审计不是可选项：SQLite 复用主键，残留审计会被下一张同 id 的单继承，造成
       时间线串档 + 已删单标题泄露。审计的价值绑定在「单还在」这一前提上。
    """
    ticket_id = ticket.id
    if entity == "requirement":
        # 删除前先把其转出 BUG 的 related_requirement_id 置空，避免悬挂外键（§5 删除策略）。
        Bug.query.filter_by(related_requirement_id=ticket_id).update(
            {"related_requirement_id": None})
    removed_comments = Comment.query.filter_by(
        entity_type=entity, entity_id=ticket_id).delete()
    removed_notifications = Notification.query.filter_by(
        entity_type=entity, entity_id=ticket_id).delete()
    removed_activities = Activity.query.filter_by(
        entity_type=entity, entity_id=ticket_id).delete()
    # 【ticket-document-management §2.8】只删**绑定关系**，**文档本体绝不删除**：
    # 它可能绑在别的单上；即使没有，它也是用户真实上传的数据，删掉一张单就静默销毁
    # 一份 PRD 是不可接受的。与 CLAUDE.md「comments/activities/notifications 永不按
    # 数量清理」是同一条价值观——**对用户真实数据的推定必须是保留**。
    removed_links = DocumentLink.query.filter_by(
        entity_type=entity, entity_id=ticket_id).delete()
    return {
        "comments": removed_comments,
        "notifications": removed_notifications,
        "activities": removed_activities,
        "document_links": removed_links,
    }


# ————————————————————— 取消指派（§2.4-B2）—————————————————————

_ENTITY_LABELS = {"requirement": "需求", "bug": "BUG"}


def unassign_ticket(ticket, entity: str, actor) -> bool:
    """把工单置为「未指派」（**不 commit**，由调用方事务统一提交）。

    语义（G1：绝不触碰 status 与 position）：工单停在 `assigned` 而无 assignee 是
    合法的中间态——它正是「等待重新分诊」，且 agent_autopilot.AGENT_CLAIMABLE 只认领
    `new`/`open`，不会误抢，故不制造新的认领竞争。

    Args:
        ticket: Requirement / Bug 实例。
        entity: "requirement" | "bug"。
        actor: 施动者 (type, id)，供审计与通知的「不给自己发」判定。

    Returns:
        True 表示确实解除了一次指派；False 表示本就未指派（幂等：不写审计、不发通知，
        避免时间线被无意义事件刷屏）。
    """
    if ticket.assignee_type is None and ticket.assignee_id is None:
        return False

    previous_type = ticket.assignee_type
    previous_id = ticket.assignee_id
    # 「未指派」以列为 NULL 表达，不引入 'null' 字面量（models/requirement.py:10）。
    ticket.assignee_type = None
    ticket.assignee_id = None

    status = ticket.status
    Activity.log(entity, ticket.id, "unassigned", actor=actor,
                 from_status=status, to_status=status, message="取消了指派")
    # 通知原**人类** assignee（原 assignee 是 Agent → 不发，与 notifications.py:82 一致）。
    if previous_type == "user" and previous_id is not None:
        label = _ENTITY_LABELS.get(entity, entity)
        title = notifications.short_text(getattr(ticket, "title", "") or "")
        notifications.notify(
            previous_id, "assigned",
            entity_type=entity, entity_id=ticket.id, actor=actor,
            message=f"你不再负责{label}「{title}」",
        )
    return True
