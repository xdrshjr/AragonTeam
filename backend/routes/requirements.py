"""需求路由（§4.3 + Phase-2 + Phase-3）——CRUD + assign + move + convert-to-bug
+ activities + 评论/feed（见 routes/comments.py）+ **agent-advance**。

关键契约：
- 迁移合法性只认 workflow 邻接表（【R-02】），move / convert / agent-advance 一律经 can_transition。
- move 支持 position 精确插入索引（Phase-2 §2.6）；缺省落列尾（向后兼容）。
- 转 BUG 后源需求恒置 bug_fixing（【R-05】），关系由 bugs.related_requirement_id 反查（【R-07】）。
- **Phase-3 §2.4 行级 RBAC（收口 # TODO(rbac-row-level)）**：patch/move 需 can_manage_ticket；
  assign/convert/delete 需 pm/admin；agent-advance 需 pm/admin 或 can_manage_ticket〔R3-01〕。
- **Phase-3 §2.5 乐观并发守卫**：patch/move 接受可选 expected_updated_at，冲突返回 409（无 allowed）。
- **Phase-3 §2.6 列表过滤/检索**：q/status/priority/assignee_*/reporter_id，全部可选、AND 组合、向后兼容。
- **Phase-3 §2.3 通知扇出**：assign/move/convert 写路径末尾扇出通知（在既有事务 commit 前）。
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from sqlalchemy import or_

from extensions import db
from models.requirement import Requirement, PRIORITIES, ASSIGNEE_TYPES, _iso
from models.bug import Bug, SEVERITIES
from models.project import Project
from models.user import User
from models.agent import Agent
from models.activity import Activity
from models.comment import Comment
from models.notification import Notification
from services import workflow, agent_runner, notifications
from services.auth_helpers import (
    require_role, current_user, can_manage_ticket, forbidden,
)
from services.pagination import paginate, with_total_count

bp = Blueprint("requirements", __name__, url_prefix="/api/requirements")


# ————————————————————— 公共辅助 —————————————————————

def _next_position(model, status: str) -> int:
    """返回目标列的下一个 position（该列现有最大值 + 1；空列为 0）。"""
    rows = model.query.filter_by(status=status).all()
    return max((r.position for r in rows), default=-1) + 1


def _coerce_index(value):
    """把 move 的 position 参数安全转为非负 int 插入索引；非法 → None（落列尾）。"""
    if value is None:
        return None
    try:
        idx = int(value)
    except (TypeError, ValueError):
        return None
    return idx if idx >= 0 else None


def _reindex_column(model, status: str, insert_id=None, insert_index=None):
    """把目标列内的卡按 (position,id) 排序后连续重编号 0..n-1（Phase-2 §2.6）。

    若给 insert_id + insert_index，则先把该卡移到目标索引处再统一重编号，
    实现「同列 / 跨列精确插入」。insert_index 越界时钳到列尾。
    """
    rows = model.query.filter_by(status=status)\
        .order_by(model.position.asc(), model.id.asc()).all()
    if insert_id is not None:
        rows = [r for r in rows if r.id != insert_id]
        card = db.session.get(model, insert_id)
        if card is not None:
            idx = insert_index
            if idx is None or idx > len(rows):
                idx = len(rows)
            rows.insert(idx, card)
    for i, r in enumerate(rows):
        r.position = i


def _validate_assignee(assignee_type, assignee_id):
    """校验多态 assignee 目标存在。返回 (ok, error_response_or_None)。

    【§2.8-4】assignee_id 先 int() 兜底，避免非法类型直接进 db.session.get。
    """
    if assignee_type not in ASSIGNEE_TYPES:
        return False, (jsonify({"error": "invalid assignee_type",
                                "detail": {"allowed": list(ASSIGNEE_TYPES)}}), 400)
    if assignee_id is None:
        return False, (jsonify({"error": "assignee_id is required"}), 400)
    try:
        int(assignee_id)
    except (TypeError, ValueError):
        return False, (jsonify({"error": "assignee_id must be an integer"}), 400)
    target = db.session.get(User if assignee_type == "user" else Agent, int(assignee_id))
    if target is None:
        return False, (jsonify({"error": f"{assignee_type} not found"}), 404)
    return True, None


def _actor():
    """当前操作者 (actor_type, actor_id)，用于写审计。"""
    u = current_user()
    return ("user", u.id) if u else ("system", None)


def _validate_project(project_id):
    """§2.8-1：传了 project_id 时校验其存在。返回 error_response 或 None。"""
    if project_id is not None and db.session.get(Project, project_id) is None:
        return jsonify({"error": "project not found"}), 400
    return None


def check_concurrency(ticket, data):
    """乐观并发守卫（Phase-3 §2.5）——requirement / bug 共用（bugs 蓝图导入本函数）。

    若请求带 `expected_updated_at` 且与当前**已提交** updated_at 不符 → 409（无 `allowed`，
    与状态机 409 区分）；**缺省该字段则不校验**（严格向后兼容 Phase-1/2 调用方）。
    比对为精确 ISO 串（微秒）相等——ticket 由调用方 `db.session.get()` 取得，其 updated_at
    在改字段前即当前已提交值〔R3-05 / 放行条件4〕。返回 409 响应或 None。
    """
    expected = data.get("expected_updated_at")
    if expected is None:
        return None
    current = _iso(ticket.updated_at)
    if expected != current:
        return jsonify({
            "error": "conflict, please reload",
            "detail": {"current_updated_at": current},
        }), 409
    return None


# ————————————————————— CRUD —————————————————————

@bp.get("")
@jwt_required()
def list_requirements():
    q = Requirement.query
    project_id = request.args.get("project_id", type=int)
    status = request.args.get("status")
    assignee_type = request.args.get("assignee_type")
    assignee_id = request.args.get("assignee_id", type=int)
    # 【Phase-3 §2.6】过滤 / 检索（全部可选、AND 组合、向后兼容）。
    keyword = request.args.get("q")
    priority = request.args.get("priority")
    reporter_id = request.args.get("reporter_id", type=int)
    if project_id is not None:
        q = q.filter_by(project_id=project_id)
    if status:
        q = q.filter_by(status=status)
    if assignee_type:
        q = q.filter_by(assignee_type=assignee_type)
    if assignee_id is not None:
        q = q.filter_by(assignee_id=assignee_id)
    if priority:
        q = q.filter_by(priority=priority)
    if reporter_id is not None:
        q = q.filter_by(reporter_id=reporter_id)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(or_(Requirement.title.ilike(like),
                         Requirement.description.ilike(like)))
    # 【Phase-2 §2.5-3】分页（非破坏）：响应体仍为裸数组，总数经 X-Total-Count 暴露。
    q = q.order_by(Requirement.position.asc(), Requirement.id.asc())
    rows, total = paginate(q)
    resp = jsonify([r.to_dict() for r in rows])
    return with_total_count(resp, total), 200


@bp.post("")
@require_role("admin", "pm")
def create_requirement():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title is required"}), 400
    priority = data.get("priority") or "medium"
    if priority not in PRIORITIES:
        return jsonify({"error": "invalid priority", "detail": {"allowed": list(PRIORITIES)}}), 400
    # §2.8-1：project_id 存在性校验（此前接受任意值不校验）。
    perr = _validate_project(data.get("project_id"))
    if perr:
        return perr

    reporter = current_user()
    req = Requirement(
        title=title,
        description=data.get("description"),
        priority=priority,
        project_id=data.get("project_id"),
        status="new",
        reporter_id=reporter.id if reporter else None,
        position=_next_position(Requirement, "new"),
    )
    db.session.add(req)
    db.session.flush()  # 拿到 req.id 再写审计
    Activity.log("requirement", req.id, "created", actor=_actor(),
                 to_status="new", message=f"创建需求「{title}」")
    db.session.commit()
    return jsonify(req.to_dict()), 201


@bp.get("/<int:req_id>")
@jwt_required()
def get_requirement(req_id):
    req = db.session.get(Requirement, req_id)
    if req is None:
        return jsonify({"error": "requirement not found"}), 404
    return jsonify(req.to_dict()), 200


@bp.patch("/<int:req_id>")
@jwt_required()
def patch_requirement(req_id):
    req = db.session.get(Requirement, req_id)
    if req is None:
        return jsonify({"error": "requirement not found"}), 404
    # 【Phase-3 §2.4】行级 RBAC：仅 reporter / 人类 assignee / pm / admin 可编辑。
    if not can_manage_ticket(current_user(), req):
        return forbidden({"reason": "cannot edit this requirement"})
    data = request.get_json(silent=True) or {}
    # 【Phase-3 §2.5】乐观并发守卫（缺省不校验）。
    conflict = check_concurrency(req, data)
    if conflict:
        return conflict
    changed = False
    if "title" in data:
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify({"error": "title cannot be empty"}), 400
        req.title = title
        changed = True
    if "description" in data:
        req.description = data["description"]
        changed = True
    if "priority" in data:
        if data["priority"] not in PRIORITIES:
            return jsonify({"error": "invalid priority",
                            "detail": {"allowed": list(PRIORITIES)}}), 400
        req.priority = data["priority"]
        changed = True
    # §2.8-3：编辑也进时间线，让 feed 覆盖全生命周期。
    if changed:
        Activity.log("requirement", req.id, "updated", actor=_actor(),
                     to_status=req.status, message="更新了需求信息")
    db.session.commit()
    return jsonify(req.to_dict()), 200


@bp.delete("/<int:req_id>")
@require_role("admin", "pm")
def delete_requirement(req_id):
    req = db.session.get(Requirement, req_id)
    if req is None:
        return jsonify({"error": "requirement not found"}), 404
    # 删除前先把其转出 BUG 的 related_requirement_id 置空，避免悬挂外键（§5 删除策略）。
    Bug.query.filter_by(related_requirement_id=req_id).update(
        {"related_requirement_id": None})
    # §5：删单一并删其评论，避免悬挂多态记录。
    Comment.query.filter_by(entity_type="requirement", entity_id=req_id).delete()
    # 【Phase-3 §5】删单一并删其通知，避免点击直达到已删单。
    Notification.query.filter_by(entity_type="requirement", entity_id=req_id).delete()
    # §2.8-3：删除进时间线（entity_id 为普通整型，不受 FK 强制影响）。
    Activity.log("requirement", req_id, "deleted", actor=_actor(),
                 from_status=req.status, message=f"删除需求「{req.title}」")
    db.session.delete(req)
    db.session.commit()
    return "", 204


# ————————————————————— assign / move / convert —————————————————————

@bp.patch("/<int:req_id>/assign")
@require_role("admin", "pm")  # 【Phase-3 §2.4】指派 / 改派仅 pm/admin。
def assign_requirement(req_id):
    req = db.session.get(Requirement, req_id)
    if req is None:
        return jsonify({"error": "requirement not found"}), 404
    data = request.get_json(silent=True) or {}
    assignee_type = data.get("assignee_type")
    assignee_id = data.get("assignee_id")

    ok, err = _validate_assignee(assignee_type, assignee_id)
    if not ok:
        return err

    req.assignee_type = assignee_type
    req.assignee_id = int(assignee_id)  # §2.8-4：入库前统一 int。
    # new → assigned 自动迁移（经邻接表校验合法性；【T4】）。
    frm = req.status
    if req.status == "new" and workflow.can_transition("requirement", "new", "assigned"):
        req.status = "assigned"
        req.position = _next_position(Requirement, "assigned")

    target = db.session.get(User if assignee_type == "user" else Agent, req.assignee_id)
    name = getattr(target, "display_name", None) or getattr(target, "name", str(assignee_id))
    Activity.log("requirement", req.id, "assigned", actor=_actor(),
                 from_status=frm, to_status=req.status,
                 message=f"指派给{'成员' if assignee_type == 'user' else 'Agent'}「{name}」")
    # 【Phase-3 §2.3】扇出：通知新的人类 assignee（Agent 不发）。
    notifications.notify_assignment(req, "requirement", actor=_actor())
    db.session.commit()
    return jsonify(req.to_dict()), 200


@bp.patch("/<int:req_id>/move")
@jwt_required()
def move_requirement(req_id):
    req = db.session.get(Requirement, req_id)
    if req is None:
        return jsonify({"error": "requirement not found"}), 404
    # 【Phase-3 §2.4】行级 RBAC：仅 can_manage_ticket 可移动。
    if not can_manage_ticket(current_user(), req):
        return forbidden({"reason": "cannot move this requirement"})
    data = request.get_json(silent=True) or {}
    to = data.get("status")
    if not to or not workflow.is_valid_status("requirement", to):
        return jsonify({"error": "invalid target status",
                        "detail": {"allowed": workflow.column_keys("requirement")}}), 400

    # 【Phase-3 §2.5】乐观并发守卫——同列早退分支也须**先过守卫**〔放行条件4〕。
    conflict = check_concurrency(req, data)
    if conflict:
        return conflict

    frm = req.status
    index = _coerce_index(data.get("position"))
    if frm == to:
        # 同列内拖动（Phase-2 §2.6）：带 position 则精确重排，否则落列尾。
        if index is not None:
            _reindex_column(Requirement, to, insert_id=req.id, insert_index=index)
        else:
            req.position = _next_position(Requirement, to)
        db.session.commit()
        return jsonify(req.to_dict()), 200

    # 【R-02】唯一裁决：邻接表 can_transition。
    if not workflow.can_transition("requirement", frm, to):
        return jsonify({
            "error": "illegal transition",
            "detail": {"from": frm, "to": to},
            "allowed": workflow.next_states("requirement", frm),
        }), 409

    req.status = to
    # Phase-2 §2.6：带 position 精确插入并重编号目标列；否则落列尾（向后兼容）。
    if index is not None:
        _reindex_column(Requirement, to, insert_id=req.id, insert_index=index)
    else:
        req.position = _next_position(Requirement, to)
    Activity.log("requirement", req.id, "moved", actor=_actor(),
                 from_status=frm, to_status=to,
                 message=f"状态 {frm} → {to}")
    # 【Phase-3 §2.3】扇出：人类推进 → status_changed 通知 reporter / 人类 assignee。
    notifications.notify_advance(req, "requirement", actor=_actor(),
                                 from_status=frm, to_status=to)
    db.session.commit()
    return jsonify(req.to_dict()), 200


@bp.post("/<int:req_id>/convert-to-bug")
@require_role("admin", "pm")  # 【Phase-3 §2.4】转 BUG 仅 pm/admin。
def convert_to_bug(req_id):
    req = db.session.get(Requirement, req_id)
    if req is None:
        return jsonify({"error": "requirement not found"}), 404

    # 【R-05】先校验：源需求须能迁移到 bug_fixing（当前态 ∈ {testing, reviewing}）。
    frm = req.status
    if not workflow.can_transition("requirement", frm, "bug_fixing"):
        return jsonify({
            "error": "illegal transition",
            "detail": {"from": frm, "to": "bug_fixing"},
            "allowed": workflow.next_states("requirement", frm),
        }), 409

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or f"[缺陷] {req.title}").strip()
    severity = data.get("severity") or "major"
    # 与 create_bug / patch_bug 一致：拒绝枚举外 severity，避免脏值落库、前端无徽章色。
    if severity not in SEVERITIES:
        return jsonify({"error": "invalid severity",
                        "detail": {"allowed": list(SEVERITIES)}}), 400

    reporter = current_user()
    bug = Bug(
        title=title,
        description=data.get("description") or f"由需求 #{req.id} 转入的缺陷单。",
        severity=severity,
        status="open",
        project_id=req.project_id,
        related_requirement_id=req.id,
        reporter_id=reporter.id if reporter else None,
        position=_next_position(Bug, "open"),
    )
    db.session.add(bug)

    # 源需求恒迁移到 bug_fixing。
    req.status = "bug_fixing"
    req.position = _next_position(Requirement, "bug_fixing")

    db.session.flush()  # 拿 bug.id
    Activity.log("requirement", req.id, "converted", actor=_actor(),
                 from_status=frm, to_status="bug_fixing",
                 message=f"转为 BUG #{bug.id}")
    Activity.log("bug", bug.id, "created", actor=_actor(),
                 to_status="open", message=f"由需求 #{req.id} 转入")
    # 【Phase-3 §2.3】扇出：通知源需求 reporter / 人类 assignee。
    notifications.notify_convert(req, bug, actor=_actor())
    db.session.commit()
    return jsonify(bug.to_dict()), 201


# ————————————————————— Agent 协作运行时（Phase-2 支柱 A）—————————————————————

@bp.post("/<int:req_id>/agent-advance")
@jwt_required()  # 行级 RBAC 在 do_agent_advance 内联裁决〔R3-01〕。
def agent_advance_requirement(req_id):
    return do_agent_advance("requirement", Requirement, req_id)


def do_agent_advance(entity, model, ticket_id):
    """Agent 单步 / run=all 推进的共享编排（requirement / bug 同构，bugs 蓝图复用）。"""
    ticket = db.session.get(model, ticket_id)
    if ticket is None:
        return jsonify({"error": f"{entity} not found"}), 404
    # 【Phase-3 §2.4 / R3-01】**有意收紧**的行级 RBAC：pm/admin 或 can_manage_ticket。
    # 否则 member 可借 Agent 推进一张自己无权 move/patch 的单，形成 RBAC 旁路。
    if not can_manage_ticket(current_user(), ticket):
        return forbidden({"reason": "cannot advance this ticket"})
    # 前置校验：必须已指派给存在的 Agent。
    if ticket.assignee_type != "agent" or ticket.assignee_id is None:
        return jsonify({"error": "ticket is not assigned to an agent"}), 409
    agent = db.session.get(Agent, ticket.assignee_id)
    if agent is None:
        return jsonify({"error": "ticket is not assigned to an agent"}), 409

    if request.args.get("run") == "all":
        return _agent_run_all(entity, ticket, agent)

    # —— 单步（【R-04】同步单事务，终态即 idle，不写不可观测的 busy）——
    frm = ticket.status
    try:
        to, comment, activity = agent_runner.advance_one(entity, ticket, agent)
    except agent_runner.NoAgentAction as e:
        return jsonify({"error": "agent has no action for this state",
                        "detail": {"kind": e.kind, "status": e.status}}), 409
    db.session.commit()
    # 【Phase-3 §2.3】在 advance_one 外层扇出（不侵入其本体），通知 reporter / 人类 assignee。
    notifications.notify_advance(ticket, entity, actor=("agent", agent.id),
                                 from_status=frm, to_status=to)
    db.session.commit()
    return jsonify({
        "ticket": ticket.to_dict(),
        "comment": comment.to_dict(),
        "agent": agent.to_dict(),
    }), 200


def _agent_run_all(entity, ticket, agent):
    """连续推进至无动作 / 终态 / MAX_AGENT_STEPS 上限（Phase-2 §2.2.3 P1）。

    【R-04】唯有 run=all 逐步 commit，busy 才成为可观测窗口：先置 busy 并 commit，
    循环每步各自 commit，finally 归 idle 并 commit（含异常路径）。
    """
    agent.status = "busy"
    db.session.commit()
    steps = []
    try:
        for _ in range(agent_runner.MAX_AGENT_STEPS):
            frm = ticket.status
            try:
                to, comment, activity = agent_runner.advance_one(entity, ticket, agent)
            except agent_runner.NoAgentAction:
                break
            db.session.commit()
            steps.append({"to_status": to, "comment": comment.to_dict()})
            # 【Phase-3 §2.3】每步扇出推进通知（在 advance_one 外层）。
            notifications.notify_advance(ticket, entity, actor=("agent", agent.id),
                                         from_status=frm, to_status=to)
            db.session.commit()
            if workflow.is_terminal(entity, ticket.status):
                break
    finally:
        agent.status = "idle"
        db.session.commit()
    return jsonify({
        "ticket": ticket.to_dict(),
        "agent": agent.to_dict(),
        "steps": steps,
    }), 200


@bp.get("/<int:req_id>/activities")
@jwt_required()
def requirement_activities(req_id):
    req = db.session.get(Requirement, req_id)
    if req is None:
        return jsonify({"error": "requirement not found"}), 404
    acts = Activity.query.filter_by(entity_type="requirement", entity_id=req_id)\
        .order_by(Activity.created_at.desc(), Activity.id.desc()).all()
    return jsonify([a.to_dict() for a in acts]), 200
