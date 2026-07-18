"""BUG 路由（§4.4）。CRUD + assign + move。

与需求 move 共享同一套契约：迁移只认 workflow 邻接表，position 落列尾。
assign / move 仅 @jwt_required()（【R-08】）。# TODO(rbac-row-level)
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from extensions import db
from models.bug import Bug, SEVERITIES, ASSIGNEE_TYPES
from models.requirement import Requirement
from models.user import User
from models.agent import Agent
from models.activity import Activity
from services import workflow
from services.auth_helpers import require_role, current_user
from routes.requirements import _next_position, _validate_assignee, _actor

bp = Blueprint("bugs", __name__, url_prefix="/api/bugs")


@bp.get("")
@jwt_required()
def list_bugs():
    q = Bug.query
    project_id = request.args.get("project_id", type=int)
    status = request.args.get("status")
    assignee_id = request.args.get("assignee_id", type=int)
    if project_id is not None:
        q = q.filter_by(project_id=project_id)
    if status:
        q = q.filter_by(status=status)
    if assignee_id is not None:
        q = q.filter_by(assignee_id=assignee_id)
    rows = q.order_by(Bug.position.asc(), Bug.id.asc()).all()
    return jsonify([b.to_dict() for b in rows]), 200


@bp.post("")
@require_role("admin", "pm")
def create_bug():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title is required"}), 400
    severity = data.get("severity") or "major"
    if severity not in SEVERITIES:
        return jsonify({"error": "invalid severity", "detail": {"allowed": list(SEVERITIES)}}), 400

    related = data.get("related_requirement_id")
    if related is not None and db.session.get(Requirement, related) is None:
        return jsonify({"error": "related requirement not found"}), 404

    reporter = current_user()
    bug = Bug(
        title=title,
        description=data.get("description"),
        severity=severity,
        project_id=data.get("project_id"),
        related_requirement_id=related,
        status="open",
        reporter_id=reporter.id if reporter else None,
        position=_next_position(Bug, "open"),
    )
    db.session.add(bug)
    db.session.flush()
    Activity.log("bug", bug.id, "created", actor=_actor(),
                 to_status="open", message=f"创建 BUG「{title}」")
    db.session.commit()
    return jsonify(bug.to_dict()), 201


@bp.get("/<int:bug_id>")
@jwt_required()
def get_bug(bug_id):
    bug = db.session.get(Bug, bug_id)
    if bug is None:
        return jsonify({"error": "bug not found"}), 404
    return jsonify(bug.to_dict()), 200


@bp.patch("/<int:bug_id>")
@jwt_required()
def patch_bug(bug_id):
    bug = db.session.get(Bug, bug_id)
    if bug is None:
        return jsonify({"error": "bug not found"}), 404
    data = request.get_json(silent=True) or {}
    if "title" in data:
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify({"error": "title cannot be empty"}), 400
        bug.title = title
    if "description" in data:
        bug.description = data["description"]
    if "severity" in data:
        if data["severity"] not in SEVERITIES:
            return jsonify({"error": "invalid severity",
                            "detail": {"allowed": list(SEVERITIES)}}), 400
        bug.severity = data["severity"]
    db.session.commit()
    return jsonify(bug.to_dict()), 200


@bp.patch("/<int:bug_id>/assign")
@jwt_required()  # 【R-08】仅需登录。# TODO(rbac-row-level)
def assign_bug(bug_id):
    bug = db.session.get(Bug, bug_id)
    if bug is None:
        return jsonify({"error": "bug not found"}), 404
    data = request.get_json(silent=True) or {}
    assignee_type = data.get("assignee_type")
    assignee_id = data.get("assignee_id")

    ok, err = _validate_assignee(assignee_type, assignee_id)
    if not ok:
        return err

    bug.assignee_type = assignee_type
    bug.assignee_id = assignee_id
    frm = bug.status
    if bug.status == "open" and workflow.can_transition("bug", "open", "assigned"):
        bug.status = "assigned"
        bug.position = _next_position(Bug, "assigned")

    target = db.session.get(User if assignee_type == "user" else Agent, assignee_id)
    name = getattr(target, "display_name", None) or getattr(target, "name", str(assignee_id))
    Activity.log("bug", bug.id, "assigned", actor=_actor(),
                 from_status=frm, to_status=bug.status,
                 message=f"指派给{'成员' if assignee_type == 'user' else 'Agent'}「{name}」")
    db.session.commit()
    return jsonify(bug.to_dict()), 200


@bp.patch("/<int:bug_id>/move")
@jwt_required()  # 【R-08】仅需登录。# TODO(rbac-row-level)
def move_bug(bug_id):
    bug = db.session.get(Bug, bug_id)
    if bug is None:
        return jsonify({"error": "bug not found"}), 404
    data = request.get_json(silent=True) or {}
    to = data.get("status")
    if not to or not workflow.is_valid_status("bug", to):
        return jsonify({"error": "invalid target status",
                        "detail": {"allowed": workflow.column_keys("bug")}}), 400

    frm = bug.status
    if frm == to:
        bug.position = _next_position(Bug, to)
        db.session.commit()
        return jsonify(bug.to_dict()), 200

    if not workflow.can_transition("bug", frm, to):
        return jsonify({
            "error": "illegal transition",
            "detail": {"from": frm, "to": to},
            "allowed": workflow.next_states("bug", frm),
        }), 409

    bug.status = to
    bug.position = _next_position(Bug, to)  # 【R-09】# TODO(board-reorder)
    Activity.log("bug", bug.id, "moved", actor=_actor(),
                 from_status=frm, to_status=to, message=f"状态 {frm} → {to}")
    db.session.commit()
    return jsonify(bug.to_dict()), 200


@bp.delete("/<int:bug_id>")
@require_role("admin", "pm")
def delete_bug(bug_id):
    bug = db.session.get(Bug, bug_id)
    if bug is None:
        return jsonify({"error": "bug not found"}), 404
    db.session.delete(bug)
    db.session.commit()
    return "", 204
