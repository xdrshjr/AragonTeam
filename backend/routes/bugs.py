"""BUG 路由（§4.4 + Phase-2）。CRUD + assign + move + **agent-advance**。

与需求 move 共享同一套契约：迁移只认 workflow 邻接表，move 支持 position 精确插入。
assign / move / agent-advance 仅 @jwt_required()（【R-08】）。# TODO(rbac-row-level)
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from extensions import db
from models.bug import Bug, SEVERITIES, ASSIGNEE_TYPES
from models.requirement import Requirement
from models.user import User
from models.agent import Agent
from models.activity import Activity
from models.comment import Comment
from services import workflow
from services.auth_helpers import require_role, current_user
from services.pagination import paginate, with_total_count
from routes.requirements import (
    _next_position, _validate_assignee, _validate_project, _actor,
    _coerce_index, _reindex_column, do_agent_advance,
)

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
    # 【Phase-2 §2.5-3】分页（非破坏）：裸数组 + X-Total-Count。
    q = q.order_by(Bug.position.asc(), Bug.id.asc())
    rows, total = paginate(q)
    resp = jsonify([b.to_dict() for b in rows])
    return with_total_count(resp, total), 200


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
    # §2.8-1：project_id 存在性校验。
    perr = _validate_project(data.get("project_id"))
    if perr:
        return perr

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
    changed = False
    if "title" in data:
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify({"error": "title cannot be empty"}), 400
        bug.title = title
        changed = True
    if "description" in data:
        bug.description = data["description"]
        changed = True
    if "severity" in data:
        if data["severity"] not in SEVERITIES:
            return jsonify({"error": "invalid severity",
                            "detail": {"allowed": list(SEVERITIES)}}), 400
        bug.severity = data["severity"]
        changed = True
    # §2.8-3：编辑进时间线。
    if changed:
        Activity.log("bug", bug.id, "updated", actor=_actor(),
                     to_status=bug.status, message="更新了 BUG 信息")
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
    bug.assignee_id = int(assignee_id)  # §2.8-4：入库前统一 int。
    frm = bug.status
    if bug.status == "open" and workflow.can_transition("bug", "open", "assigned"):
        bug.status = "assigned"
        bug.position = _next_position(Bug, "assigned")

    target = db.session.get(User if assignee_type == "user" else Agent, bug.assignee_id)
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
    index = _coerce_index(data.get("position"))
    if frm == to:
        # 同列内拖动（Phase-2 §2.6）。
        if index is not None:
            _reindex_column(Bug, to, insert_id=bug.id, insert_index=index)
        else:
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
    if index is not None:
        _reindex_column(Bug, to, insert_id=bug.id, insert_index=index)
    else:
        bug.position = _next_position(Bug, to)
    Activity.log("bug", bug.id, "moved", actor=_actor(),
                 from_status=frm, to_status=to, message=f"状态 {frm} → {to}")
    db.session.commit()
    return jsonify(bug.to_dict()), 200


@bp.post("/<int:bug_id>/agent-advance")
@jwt_required()  # 【R-08】仅需登录。# TODO(rbac-row-level)
def agent_advance_bug(bug_id):
    return do_agent_advance("bug", Bug, bug_id)


@bp.delete("/<int:bug_id>")
@require_role("admin", "pm")
def delete_bug(bug_id):
    bug = db.session.get(Bug, bug_id)
    if bug is None:
        return jsonify({"error": "bug not found"}), 404
    # §5：删单一并删其评论。
    Comment.query.filter_by(entity_type="bug", entity_id=bug_id).delete()
    # §2.8-3：删除进时间线。
    Activity.log("bug", bug_id, "deleted", actor=_actor(),
                 from_status=bug.status, message=f"删除 BUG「{bug.title}」")
    db.session.delete(bug)
    db.session.commit()
    return "", 204
