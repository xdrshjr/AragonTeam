"""计划路由（version-plan-hierarchy §6.2）——list / create(admin|pm) / get /
patch(admin|pm) / delete(admin|pm)。

计划挂在版本下（`version_id`），`project_id` 由版本推导写入（反范式，§3.3）。改挂版本
须同项目（§3.3 不变量 B），否则 400。删除前置引用检查：有工单 → 409（§3.5）。
"""
import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from extensions import db
from models.plan import Plan, PLAN_STATUSES
from models.version import Version
from services import hierarchy, lifecycle
from services.auth_helpers import require_role, current_user
from services.pagination import paginate, with_total_count
from services.scope import apply_project_filter, project_scope, want_query_int, want_query_str
from services.validation import json_body, want_date, want_int, want_str

bp = Blueprint("plans", __name__, url_prefix="/api/plans")

log = logging.getLogger("aragon.plans")

_ARCHIVED_INCLUDE = ("1", "true", "yes")


def _serialize_many(rows) -> list:
    """批量序列化 + 富化 {requirement_count, bug_count, done_count}（零 N+1，§6.2）。"""
    plans = list(rows)
    counts = hierarchy.plan_ticket_counts([p.id for p in plans])
    out = []
    for plan in plans:
        entry = counts.get(plan.id, {"requirements": 0, "bugs": 0, "done": 0})
        out.append({**plan.to_dict(),
                    "requirement_count": entry["requirements"],
                    "bug_count": entry["bugs"],
                    "done_count": entry["done"]})
    return out


def _serialize_one(plan) -> dict:
    return _serialize_many([plan])[0]


@bp.get("")
@jwt_required()
def list_plans():
    # 【§6.2】project 作用域 + 可选 version_id 过滤 + 可选 status + 默认隐藏 archived。
    q = apply_project_filter(Plan.query, Plan, project_scope())
    version_id = want_query_int("version_id")
    if version_id is not None:
        q = q.filter(Plan.version_id == version_id)
    status = want_query_str("status", choices=PLAN_STATUSES)
    if status:
        q = q.filter(Plan.status == status)
    elif request.args.get("include_archived") not in _ARCHIVED_INCLUDE:
        q = q.filter(Plan.status != "archived")
    q = q.order_by(Plan.position.asc(), Plan.id.asc())
    rows, total = paginate(q)
    resp = jsonify(_serialize_many(rows))
    return with_total_count(resp, total), 200


@bp.post("")
@require_role("admin", "pm")
def create_plan():
    data = json_body()
    name = want_str(data, "name", required=True, max_len=128)
    description = want_str(data, "description", required=False, strip=False) or None
    status = want_str(data, "status", default="planning", choices=PLAN_STATUSES)
    version_id = want_int(data, "version_id", required=True)
    version = db.session.get(Version, version_id)
    if version is None:
        return jsonify({"error": "version not found"}), 400
    start_date = want_date(data, "start_date")
    end_date = want_date(data, "end_date")

    plan = Plan(
        name=name, description=description, status=status,
        version_id=version_id,
        # 【§3.3】project_id 由版本推导（反范式落定，此后不因任何操作漂移）。
        project_id=version.project_id,
        start_date=start_date, end_date=end_date,
        position=hierarchy.next_sort_position(Plan, version_id=version_id),
    )
    db.session.add(plan)
    db.session.commit()
    actor = current_user()
    log.info("plan created: id=%s name=%s version=%s by=%s",
             plan.id, plan.name, version_id, actor.username if actor else "system")
    return jsonify(_serialize_one(plan)), 201


@bp.get("/<int:plan_id>")
@jwt_required()
def get_plan(plan_id):
    plan = db.session.get(Plan, plan_id)
    if plan is None:
        return jsonify({"error": "plan not found"}), 404
    return jsonify(_serialize_one(plan)), 200


@bp.patch("/<int:plan_id>")
@require_role("admin", "pm")
def patch_plan(plan_id):
    plan = db.session.get(Plan, plan_id)
    if plan is None:
        return jsonify({"error": "plan not found"}), 404
    data = json_body()

    changed = False
    if "name" in data:
        plan.name = want_str(data, "name", required=True, max_len=128)
        changed = True
    if "description" in data:
        plan.description = want_str(data, "description", required=False, strip=False) or None
        changed = True
    if "status" in data:
        plan.status = want_str(data, "status", required=True, choices=PLAN_STATUSES)
        changed = True
    if "start_date" in data:
        plan.start_date = want_date(data, "start_date")
        changed = True
    if "end_date" in data:
        plan.end_date = want_date(data, "end_date")
        changed = True
    if "version_id" in data:
        # 【§3.3 不变量 B】允许改挂版本，但新版本须与当前 project 同项目，否则 400；
        # 改挂后 project_id 不变（因为同项目），冗余不漂移。
        new_version_id = want_int(data, "version_id", required=True)
        new_version = db.session.get(Version, new_version_id)
        if new_version is None:
            return jsonify({"error": "version not found"}), 400
        if new_version.project_id != plan.project_id:
            return jsonify({
                "error": "plan and version must be in the same project",
                "detail": {"field": "version_id"},
            }), 400
        plan.version_id = new_version_id
        changed = True
    if "position" in data:
        plan.position = want_int(data, "position", required=True, minimum=0)
        changed = True

    if not changed:
        return jsonify({"error": "no updatable field"}), 400

    db.session.commit()
    return jsonify(_serialize_one(plan)), 200


@bp.delete("/<int:plan_id>")
@require_role("admin", "pm")
def delete_plan(plan_id):
    plan = db.session.get(Plan, plan_id)
    if plan is None:
        return jsonify({"error": "plan not found"}), 404
    # 【§3.5】有工单 → 409（无 allowed）。计划与工单无 DB 外键，前置守卫防悬挂 plan_id。
    refs = lifecycle.plan_references(plan_id)
    if refs["requirements"] or refs["bugs"]:
        return lifecycle.conflict_plan_has_tickets(refs)
    actor = current_user()
    log.info("plan deleted: id=%s name=%s by=%s",
             plan.id, plan.name, actor.username if actor else "system")
    db.session.delete(plan)
    db.session.commit()
    return "", 204
