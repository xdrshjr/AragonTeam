"""版本路由（version-plan-hierarchy §6.1）——list / create(admin|pm) / get /
patch(admin|pm) / delete(admin|pm)。

版本挂在项目下，是**人工管理**的规划物，不接入工单状态机（§2.2）。生命周期状态自由
切换；`released_at` **服务端托管**（随 `status` 进出 `released` 由本路由 stamp / 清空，
客户端不可写，§6.1 评审 P1-C）。删除前置引用检查：有计划 → 409（§3.5）。

版本 / 计划的变更走**结构化日志**（`log.info`），不写 `activities`（§2.2：避免撕开
`TICKET_ENTITY_TYPES` 隔离），与 `routes/projects.py` 删项目的既有先例一致。
"""
import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from extensions import db, utcnow
from models.project import Project
from models.user import User
from models.version import Version, VERSION_STATUSES
from services import hierarchy, lifecycle
from services.auth_helpers import require_role, current_user
from services.pagination import paginate, with_total_count
from services.scope import apply_project_filter, project_scope, want_query_str
from services.validation import json_body, want_date, want_int, want_str

bp = Blueprint("versions", __name__, url_prefix="/api/versions")

log = logging.getLogger("aragon.versions")

_ARCHIVED_INCLUDE = ("1", "true", "yes")


def _want_owner_id(data):
    """取一个可选 owner_id：null 即清空；整数须存在（仿 projects._want_owner_id）。"""
    owner_id = want_int(data, "owner_id")
    if owner_id is not None and db.session.get(User, owner_id) is None:
        return None, (jsonify({"error": "owner not found"}), 400)
    return owner_id, None


def _serialize_many(rows) -> list:
    """批量序列化 + 富化 plan_count / 聚合 total_count / done_count（零 N+1，§6.1）。"""
    versions = list(rows)
    ids = [v.id for v in versions]
    plan_counts = hierarchy.version_plan_counts(ids)
    ticket_counts = hierarchy.version_ticket_counts(ids)
    out = []
    for version in versions:
        counts = ticket_counts.get(version.id, {"total": 0, "done": 0})
        out.append({**version.to_dict(),
                    "plan_count": plan_counts.get(version.id, 0),
                    "total_count": counts["total"],
                    "done_count": counts["done"]})
    return out


def _serialize_one(version) -> dict:
    return _serialize_many([version])[0]


def _apply_released_stamp(version, new_status: str) -> None:
    """released_at 服务端托管：进入 released 时 stamp utcnow()、转出时清空（§6.1 P1-C）。"""
    if new_status == "released" and version.status != "released":
        version.released_at = utcnow()
    elif new_status != "released" and version.status == "released":
        version.released_at = None


@bp.get("")
@jwt_required()
def list_versions():
    # 【§6.1】project 作用域（缺省不过滤 / 整数 / none）+ 可选 status + 默认隐藏 archived。
    q = apply_project_filter(Version.query, Version, project_scope())
    status = want_query_str("status", choices=VERSION_STATUSES)
    if status:
        q = q.filter(Version.status == status)
    elif request.args.get("include_archived") not in _ARCHIVED_INCLUDE:
        # 默认隐藏 archived；显式 ?status=archived 仍可查出（归档 = 从默认列表收起）。
        q = q.filter(Version.status != "archived")
    q = q.order_by(Version.position.asc(), Version.id.asc())
    rows, total = paginate(q)
    resp = jsonify(_serialize_many(rows))
    return with_total_count(resp, total), 200


@bp.post("")
@require_role("admin", "pm")
def create_version():
    data = json_body()
    name = want_str(data, "name", required=True, max_len=128)
    description = want_str(data, "description", required=False, strip=False) or None
    status = want_str(data, "status", default="planning", choices=VERSION_STATUSES)
    project_id = want_int(data, "project_id", required=True)
    if db.session.get(Project, project_id) is None:
        return jsonify({"error": "project not found"}), 400
    owner_id, oerr = _want_owner_id(data)
    if oerr:
        return oerr
    target_date = want_date(data, "target_date")

    version = Version(
        name=name, description=description, status=status,
        project_id=project_id, owner_id=owner_id, target_date=target_date,
        position=hierarchy.next_sort_position(Version, project_id=project_id),
    )
    # released_at 服务端托管：初始态即 released 时直接 stamp（create 处 version.status 已是
    # 新值，_apply_released_stamp 的「转入」判据检测不到，故此处内联）。
    if status == "released":
        version.released_at = utcnow()
    db.session.add(version)
    db.session.commit()
    actor = current_user()
    log.info("version created: id=%s name=%s project=%s by=%s",
             version.id, version.name, project_id, actor.username if actor else "system")
    return jsonify(_serialize_one(version)), 201


@bp.get("/<int:version_id>")
@jwt_required()
def get_version(version_id):
    version = db.session.get(Version, version_id)
    if version is None:
        return jsonify({"error": "version not found"}), 404
    return jsonify(_serialize_one(version)), 200


@bp.patch("/<int:version_id>")
@require_role("admin", "pm")
def patch_version(version_id):
    version = db.session.get(Version, version_id)
    if version is None:
        return jsonify({"error": "version not found"}), 404
    data = json_body()

    changed = False
    if "name" in data:
        version.name = want_str(data, "name", required=True, max_len=128)
        changed = True
    if "description" in data:
        version.description = want_str(data, "description", required=False, strip=False) or None
        changed = True
    if "status" in data:
        new_status = want_str(data, "status", required=True, choices=VERSION_STATUSES)
        _apply_released_stamp(version, new_status)   # 先算 stamp（读的是**旧** status）
        version.status = new_status
        changed = True
    if "target_date" in data:
        version.target_date = want_date(data, "target_date")
        changed = True
    if "owner_id" in data:
        owner_id, oerr = _want_owner_id(data)
        if oerr:
            return oerr
        version.owner_id = owner_id
        changed = True
    if "position" in data:
        version.position = want_int(data, "position", required=True, minimum=0)
        changed = True
    # 【§3.3 不变量 A】project_id 创建后不可变：请求体带了也**忽略**（不计入 changed），
    # 版本永远锚定在同一个项目里。released_at 不接受客户端传值（服务端托管，见上）。

    if not changed:
        return jsonify({"error": "no updatable field"}), 400

    db.session.commit()
    return jsonify(_serialize_one(version)), 200


@bp.delete("/<int:version_id>")
@require_role("admin", "pm")
def delete_version(version_id):
    version = db.session.get(Version, version_id)
    if version is None:
        return jsonify({"error": "version not found"}), 404
    # 【§3.5】有计划 → 409（无 allowed）。绝不依赖外键异常兜底：那会变成 500。
    refs = lifecycle.version_references(version_id)
    if refs["plans"]:
        return lifecycle.conflict_version_has_plans(refs)
    actor = current_user()
    log.info("version deleted: id=%s name=%s by=%s",
             version.id, version.name, actor.username if actor else "system")
    db.session.delete(version)
    db.session.commit()
    return "", 204
