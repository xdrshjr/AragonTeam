"""BUG 路由（§4.4 + Phase-2 + Phase-3）。CRUD + assign + move + **agent-advance**。

与需求 move 共享同一套契约：迁移只认 workflow 邻接表，move 支持 position 精确插入。
Phase-3：patch/move 加行级 RBAC（can_manage_ticket）+ 乐观并发守卫；assign 限 pm/admin；
list 加过滤/检索（含 severity）；写路径接入通知扇出（复用 requirements 蓝图的共享 helper）。
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from sqlalchemy import or_

from extensions import db
from models.bug import Bug, SEVERITIES, ASSIGNEE_TYPES
from models.requirement import Requirement
from models.user import User
from models.agent import Agent
from models.activity import Activity
from models.comment import Comment
from models.notification import Notification
from services import workflow, notifications
from services.auth_helpers import (
    require_role, current_user, can_manage_ticket, forbidden,
)
from services.pagination import paginate, with_total_count
from services.search import escape_like
from services.validation import json_body, want_str, want_int
from routes.requirements import (
    _next_position, _validate_assignee, _validate_project, _actor,
    _coerce_index, _reindex_column, do_agent_advance, check_concurrency,
)

bp = Blueprint("bugs", __name__, url_prefix="/api/bugs")


@bp.get("")
@jwt_required()
def list_bugs():
    q = Bug.query
    project_id = request.args.get("project_id", type=int)
    status = request.args.get("status")
    assignee_type = request.args.get("assignee_type")
    assignee_id = request.args.get("assignee_id", type=int)
    # 【Phase-3 §2.6】过滤 / 检索（全部可选、AND 组合、向后兼容；BUG 侧含 severity）。
    keyword = request.args.get("q")
    severity = request.args.get("severity")
    reporter_id = request.args.get("reporter_id", type=int)
    if project_id is not None:
        q = q.filter_by(project_id=project_id)
    if status:
        q = q.filter_by(status=status)
    if assignee_type:
        q = q.filter_by(assignee_type=assignee_type)
    if assignee_id is not None:
        q = q.filter_by(assignee_id=assignee_id)
    if severity:
        q = q.filter_by(severity=severity)
    if reporter_id is not None:
        q = q.filter_by(reporter_id=reporter_id)
    if keyword:
        # 【§2.4-C1】转义 LIKE 元字符（% _ \），与 search 一致，避免通配过度匹配。
        like = f"%{escape_like(keyword)}%"
        q = q.filter(or_(Bug.title.ilike(like, escape="\\"),
                         Bug.description.ilike(like, escape="\\")))
    # 【Phase-2 §2.5-3】分页（非破坏）：裸数组 + X-Total-Count。
    # 【§2.3】扁平列表按「最近更新」全局排序（与需求侧、/me/work 一致）；position 仅服务看板列内排序。
    q = q.order_by(Bug.updated_at.desc(), Bug.id.desc())
    rows, total = paginate(q)
    resp = jsonify([b.to_dict() for b in rows])
    return with_total_count(resp, total), 200


@bp.post("")
@require_role("admin", "pm")
def create_bug():
    # 【§2.2】非串 title → 400（此前 .strip() 500）；severity 走 choices 归一；
    # project_id / related_requirement_id 走 want_int（list/dict 主键此前进 db.session.get 触 500）。
    data = json_body()
    title = want_str(data, "title", required=True, max_len=200)
    severity = want_str(data, "severity", default="major", choices=SEVERITIES)
    # 【§2.4-C3】非串 description → 400（此前绑到 Text 列 commit 触 500）；strip=False 保留正文格式。
    description = want_str(data, "description", required=False, strip=False) or None
    project_id = want_int(data, "project_id")
    # §2.8-1：project_id 存在性校验。
    perr = _validate_project(project_id)
    if perr:
        return perr

    related = want_int(data, "related_requirement_id")
    if related is not None and db.session.get(Requirement, related) is None:
        return jsonify({"error": "related requirement not found"}), 404

    reporter = current_user()
    bug = Bug(
        title=title,
        description=description,
        severity=severity,
        project_id=project_id,
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
    # 【Phase-3 §2.4】行级 RBAC。
    if not can_manage_ticket(current_user(), bug):
        return forbidden({"reason": "cannot edit this bug"})
    data = json_body()
    # 【Phase-3 §2.5】乐观并发守卫（缺省不校验）。
    conflict = check_concurrency(bug, data)
    if conflict:
        return conflict
    changed = False
    if "title" in data:
        # 非串 title → 400（此前 .strip() 500）；空串仍 400。
        bug.title = want_str(data, "title", required=True, max_len=200)
        changed = True
    if "description" in data:
        # 【§2.4-C3】非串 description → 400（此前直接赋值，commit 触 500）；strip=False 保留正文格式。
        bug.description = want_str(data, "description", required=False, strip=False) or None
        changed = True
    if "severity" in data:
        bug.severity = want_str(data, "severity", required=True, choices=SEVERITIES)
        changed = True
    # §2.8-3：编辑进时间线。
    if changed:
        Activity.log("bug", bug.id, "updated", actor=_actor(),
                     to_status=bug.status, message="更新了 BUG 信息")
    db.session.commit()
    return jsonify(bug.to_dict()), 200


@bp.patch("/<int:bug_id>/assign")
@require_role("admin", "pm")  # 【Phase-3 §2.4】指派 / 改派仅 pm/admin。
def assign_bug(bug_id):
    bug = db.session.get(Bug, bug_id)
    if bug is None:
        return jsonify({"error": "bug not found"}), 404
    # 【§2.2 / R4】仅体层加 json_body()；assignee 保持既有 _validate_assignee（容忍数字串）。
    data = json_body()
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
    # 【Phase-3 §2.3】扇出：通知新的人类 assignee（Agent 不发）。
    notifications.notify_assignment(bug, "bug", actor=_actor())
    db.session.commit()
    return jsonify(bug.to_dict()), 200


@bp.patch("/<int:bug_id>/move")
@jwt_required()
def move_bug(bug_id):
    bug = db.session.get(Bug, bug_id)
    if bug is None:
        return jsonify({"error": "bug not found"}), 404
    # 【Phase-3 §2.4】行级 RBAC。
    if not can_manage_ticket(current_user(), bug):
        return forbidden({"reason": "cannot move this bug"})
    data = json_body()
    # 【§2.3-B1】status 必须先是字符串再进状态机（非空 list → unhashable 500）。
    to = want_str(data, "status", required=True)
    if not workflow.is_valid_status("bug", to):
        return jsonify({"error": "invalid target status",
                        "detail": {"allowed": workflow.column_keys("bug")}}), 400

    # 【Phase-3 §2.5】乐观并发守卫——同列早退分支也须先过守卫〔放行条件4〕。
    conflict = check_concurrency(bug, data)
    if conflict:
        return conflict

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
    # 【Phase-3 §2.3】扇出：人类推进 → status_changed 通知。
    notifications.notify_advance(bug, "bug", actor=_actor(),
                                 from_status=frm, to_status=to)
    db.session.commit()
    return jsonify(bug.to_dict()), 200


@bp.post("/<int:bug_id>/agent-advance")
@jwt_required()  # 行级 RBAC 在 do_agent_advance 内联裁决〔R3-01〕。
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
    # 【Phase-3 §5】删单一并删其通知。
    Notification.query.filter_by(entity_type="bug", entity_id=bug_id).delete()
    # §2.8-3：删除进时间线。
    Activity.log("bug", bug_id, "deleted", actor=_actor(),
                 from_status=bug.status, message=f"删除 BUG「{bug.title}」")
    db.session.delete(bug)
    db.session.commit()
    return "", 204
