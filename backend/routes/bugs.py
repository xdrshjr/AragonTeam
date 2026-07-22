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
from services import workflow, bulk_ops, doc_policy, hierarchy, lifecycle, notifications
from services.documents import counts as document_counts
from services.auth_helpers import (
    require_role, current_user, can_manage_ticket, forbidden,
)
from services.pagination import MAX_LIMIT, paginate, with_total_count
from services.scope import apply_project_filter, project_scope, want_query_int
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
    # 【§2.4】项目作用域：缺省=不过滤、整数=该项目、"none"=未归属（非法值 → 全局 400）。
    q = apply_project_filter(Bug.query, Bug, project_scope())
    # 【version-plan-hierarchy §3.4】层级过滤：?version_id= / ?plan_id=（含 none 哨兵）。
    q = hierarchy.apply_ticket_hierarchy_filter(q, Bug)
    status = request.args.get("status")
    assignee_type = request.args.get("assignee_type")
    # 【§2.9-G2 / 评审 R1】整数过滤参数走 want_query_int：畸形值 400、超界值不再 500。
    assignee_id = want_query_int("assignee_id")
    # 【Phase-3 §2.6】过滤 / 检索（全部可选、AND 组合、向后兼容；BUG 侧含 severity）。
    keyword = request.args.get("q")
    severity = request.args.get("severity")
    reporter_id = want_query_int("reporter_id")
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
    # 【ticket-document-management §4.3】additive 富化 document_count（批量计数，
    # 在序列化站点完成，不改 to_dict）。
    # 【version-plan-hierarchy §3.4】再叠加只读 plan 概要（零 N+1）。
    resp = jsonify(hierarchy.attach_plan_context(
        document_counts.with_document_counts("bug", rows)))
    return with_total_count(resp, total), 200


@bp.post("/bulk")
@jwt_required()  # 粗粒度角色门禁按 action 分流，在 bulk_ops.run 内裁决。
def bulk_bugs():
    """批量操作入口（bulk-operations §2.3）：指派 / 取消指派 / 流转 / 改严重度 / 删除。

    与需求侧共用 `services/bulk_ops.py` 的同一条流水线；两侧的差别只有「级别字段」
    （需求 priority / BUG severity），由 bulk_ops 的 `_SPECS` 一处声明。
    """
    return bulk_ops.run("bug", json_body(), current_user(), _actor())


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
        position=_next_position(Bug, "open", project_id),
    )
    # 【version-plan-hierarchy §3.2】可选 plan_id：校验 + 同项目不变量（同需求侧）。
    hierarchy.resolve_plan_for_ticket(bug, data)
    db.session.add(bug)
    db.session.flush()
    Activity.log("bug", bug.id, "created", actor=_actor(),
                 to_status="open", message=f"创建 BUG「{title}」")
    db.session.commit()
    return jsonify(hierarchy.with_plan_context_one(bug)), 201


@bp.get("/<int:bug_id>")
@jwt_required()
def get_bug(bug_id):
    bug = db.session.get(Bug, bug_id)
    if bug is None:
        return jsonify({"error": "bug not found"}), 404
    return jsonify(hierarchy.attach_plan_context_one(
        document_counts.with_document_count("bug", bug))), 200


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
    # 【version-plan-hierarchy §3.2】改归属计划（int 改 / null 解除）。
    if "plan_id" in data:
        hierarchy.resolve_plan_for_ticket(bug, data)
        changed = True
    # §2.8-3：编辑进时间线。
    if changed:
        Activity.log("bug", bug.id, "updated", actor=_actor(),
                     to_status=bug.status, message="更新了 BUG 信息")
    db.session.commit()
    return jsonify(hierarchy.with_plan_context_one(bug)), 200


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

    # 【lifecycle-and-governance §2.4-B2】显式取消指派（与需求侧同构，共用 lifecycle 服务）。
    if assignee_type is None and "assignee_type" in data:
        lifecycle.unassign_ticket(bug, "bug", _actor())
        db.session.commit()
        return jsonify(bug.to_dict()), 200

    ok, err = _validate_assignee(assignee_type, assignee_id)
    if not ok:
        return err

    bug.assignee_type = assignee_type
    bug.assignee_id = int(assignee_id)  # §2.8-4：入库前统一 int。
    frm = bug.status
    if bug.status == "open" and workflow.can_transition("bug", "open", "assigned"):
        bug.status = "assigned"
        bug.position = _next_position(Bug, "assigned", bug.project_id)

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
            _reindex_column(Bug, to, bug.project_id,
                            insert_id=bug.id, insert_index=index)
        else:
            bug.position = _next_position(Bug, to, bug.project_id)
        db.session.commit()
        return jsonify(bug.to_dict()), 200

    if not workflow.can_transition("bug", frm, to):
        return jsonify({
            "error": "illegal transition",
            "detail": {"from": frm, "to": to},
            "allowed": workflow.next_states("bug", frm),
        }), 409

    # 【ticket-document-management §2.4】阶段文档门禁。**必须在这里单独挂一次**——
    # move_bug 的主体与 move_requirement 是各自独立的（bugs.py 只跨蓝图复用
    # check_concurrency 等助手）。位置同样严格在 can_transition 判 True 之后、写入之前。
    gated = doc_policy.gate_transition("bug", bug, to)
    if gated:
        return gated

    bug.status = to
    if index is not None:
        _reindex_column(Bug, to, bug.project_id,
                        insert_id=bug.id, insert_index=index)
    else:
        bug.position = _next_position(Bug, to, bug.project_id)
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
    # 【data-persistence §2.7】级联清理（评论 / 通知 / 审计）唯一真相在
    # services/lifecycle.py；本处只负责删本体并提交。行为逐字不变。
    # 有意**不再**写 "deleted" 审计（无查看入口且会被同批清掉）。
    lifecycle.delete_ticket_cascade("bug", bug)
    db.session.delete(bug)
    db.session.commit()
    return "", 204


@bp.get("/<int:bug_id>/activities")
@jwt_required()
def bug_activities(bug_id):
    """【§2.9-G4】与 requirements 侧对称的时间线端点（此前 BUG 侧缺失，纯路由不对称）。"""
    bug = db.session.get(Bug, bug_id)
    if bug is None:
        return jsonify({"error": "bug not found"}), 404
    # 【P2-1】接分页 + X-Total-Count（响应体仍是裸数组，契约不变），与需求侧同构。
    q = Activity.query.filter_by(entity_type="bug", entity_id=bug_id)\
        .order_by(Activity.created_at.desc(), Activity.id.desc())
    acts, total = paginate(q, default_limit=MAX_LIMIT)
    resp = jsonify([a.to_dict() for a in acts])
    return with_total_count(resp, total), 200
