"""需求路由（§4.3）——核心：CRUD + assign + move + convert-to-bug + activities。

关键契约：
- 迁移合法性只认 workflow 邻接表（【R-02】），move / convert 一律经 can_transition。
- position 落列尾（该列现有最大值 + 1，【R-09】）。
- 转 BUG 后源需求恒置 bug_fixing（【R-05】），关系由 bugs.related_requirement_id 反查（【R-07】）。
- assign / move / convert 仅 @jwt_required()；行级权限本期不做（【R-08】）。
  # TODO(rbac-row-level): 后续迭代限制成员仅能操作与自己相关的单。
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from extensions import db
from models.requirement import Requirement, PRIORITIES, ASSIGNEE_TYPES
from models.bug import Bug, SEVERITIES
from models.user import User
from models.agent import Agent
from models.activity import Activity
from services import workflow
from services.auth_helpers import require_role, current_user

bp = Blueprint("requirements", __name__, url_prefix="/api/requirements")


# ————————————————————— 公共辅助 —————————————————————

def _next_position(model, status: str) -> int:
    """返回目标列的下一个 position（该列现有最大值 + 1；空列为 0）。"""
    rows = model.query.filter_by(status=status).all()
    return max((r.position for r in rows), default=-1) + 1


def _validate_assignee(assignee_type, assignee_id):
    """校验多态 assignee 目标存在。返回 (ok, error_response_or_None)。"""
    if assignee_type not in ASSIGNEE_TYPES:
        return False, (jsonify({"error": "invalid assignee_type",
                                "detail": {"allowed": list(ASSIGNEE_TYPES)}}), 400)
    if assignee_id is None:
        return False, (jsonify({"error": "assignee_id is required"}), 400)
    target = db.session.get(User if assignee_type == "user" else Agent, assignee_id)
    if target is None:
        return False, (jsonify({"error": f"{assignee_type} not found"}), 404)
    return True, None


def _actor():
    """当前操作者 (actor_type, actor_id)，用于写审计。"""
    u = current_user()
    return ("user", u.id) if u else ("system", None)


# ————————————————————— CRUD —————————————————————

@bp.get("")
@jwt_required()
def list_requirements():
    q = Requirement.query
    project_id = request.args.get("project_id", type=int)
    status = request.args.get("status")
    assignee_type = request.args.get("assignee_type")
    assignee_id = request.args.get("assignee_id", type=int)
    if project_id is not None:
        q = q.filter_by(project_id=project_id)
    if status:
        q = q.filter_by(status=status)
    if assignee_type:
        q = q.filter_by(assignee_type=assignee_type)
    if assignee_id is not None:
        q = q.filter_by(assignee_id=assignee_id)
    rows = q.order_by(Requirement.position.asc(), Requirement.id.asc()).all()
    return jsonify([r.to_dict() for r in rows]), 200


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
    data = request.get_json(silent=True) or {}
    if "title" in data:
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify({"error": "title cannot be empty"}), 400
        req.title = title
    if "description" in data:
        req.description = data["description"]
    if "priority" in data:
        if data["priority"] not in PRIORITIES:
            return jsonify({"error": "invalid priority",
                            "detail": {"allowed": list(PRIORITIES)}}), 400
        req.priority = data["priority"]
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
    db.session.delete(req)
    db.session.commit()
    return "", 204


# ————————————————————— assign / move / convert —————————————————————

@bp.patch("/<int:req_id>/assign")
@jwt_required()  # 【R-08】行级权限本期不做，仅需登录。# TODO(rbac-row-level)
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
    req.assignee_id = assignee_id
    # new → assigned 自动迁移（经邻接表校验合法性；【T4】）。
    frm = req.status
    if req.status == "new" and workflow.can_transition("requirement", "new", "assigned"):
        req.status = "assigned"
        req.position = _next_position(Requirement, "assigned")

    target = db.session.get(User if assignee_type == "user" else Agent, assignee_id)
    name = getattr(target, "display_name", None) or getattr(target, "name", str(assignee_id))
    Activity.log("requirement", req.id, "assigned", actor=_actor(),
                 from_status=frm, to_status=req.status,
                 message=f"指派给{'成员' if assignee_type == 'user' else 'Agent'}「{name}」")
    db.session.commit()
    return jsonify(req.to_dict()), 200


@bp.patch("/<int:req_id>/move")
@jwt_required()  # 【R-08】仅需登录。# TODO(rbac-row-level)
def move_requirement(req_id):
    req = db.session.get(Requirement, req_id)
    if req is None:
        return jsonify({"error": "requirement not found"}), 404
    data = request.get_json(silent=True) or {}
    to = data.get("status")
    if not to or not workflow.is_valid_status("requirement", to):
        return jsonify({"error": "invalid target status",
                        "detail": {"allowed": workflow.column_keys("requirement")}}), 400

    frm = req.status
    if frm == to:
        # 同列内拖动：MVP 不重排，直接落列尾。
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
    # 【R-09】position 落目标列尾，不整列重排。# TODO(board-reorder)
    req.position = _next_position(Requirement, to)
    Activity.log("requirement", req.id, "moved", actor=_actor(),
                 from_status=frm, to_status=to,
                 message=f"状态 {frm} → {to}")
    db.session.commit()
    return jsonify(req.to_dict()), 200


@bp.post("/<int:req_id>/convert-to-bug")
@jwt_required()  # 【R-08】仅需登录。# TODO(rbac-row-level)
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
    db.session.commit()
    return jsonify(bug.to_dict()), 201


@bp.get("/<int:req_id>/activities")
@jwt_required()
def requirement_activities(req_id):
    req = db.session.get(Requirement, req_id)
    if req is None:
        return jsonify({"error": "requirement not found"}), 404
    acts = Activity.query.filter_by(entity_type="requirement", entity_id=req_id)\
        .order_by(Activity.created_at.desc(), Activity.id.desc()).all()
    return jsonify([a.to_dict() for a in acts]), 200
