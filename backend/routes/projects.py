"""项目路由（§4.2 + lifecycle-and-governance §2.6）。

list / create(admin|pm) / get / **patch(admin|pm)** / **delete(admin)**。
归档优于删除：项目一旦有工单挂靠，删除意味着要么违反外键、要么把工单的 project_id
悄悄置 NULL（错数据 + 丢归属），故 DELETE 前置引用检查 → 409，并建议改用归档。
"""
import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from extensions import db, utcnow
from models.project import Project
from models.user import User
from services import lifecycle
from services.auth_helpers import require_role, current_user
from services.pagination import paginate, with_total_count
from services.validation import json_body, want_bool, want_int, want_str

bp = Blueprint("projects", __name__, url_prefix="/api/projects")

log = logging.getLogger("aragon.projects")


def _want_owner_id(data):
    """取一个可选 owner_id：null 即清空；整数须存在。返回 (owner_id, error_response)。"""
    owner_id = want_int(data, "owner_id")
    if owner_id is not None and db.session.get(User, owner_id) is None:
        return None, (jsonify({"error": "owner not found"}), 400)
    return owner_id, None


@bp.get("")
@jwt_required()
def list_projects():
    # 【§2.9-G1】补分页 + X-Total-Count（响应体仍是裸数组，契约不变）；消费方显式传 limit=200。
    # 【lifecycle-and-governance §2.6】默认只返回未归档；?include_archived=1 才全返。
    # 这是本轮**唯一**的默认结果集语义变更（spec §4.2 已登记）：归档的意义就是
    # 「不再出现在建单表单与全局切换器里」，靠这一条自然达成，前端零特判。
    q = Project.query
    if request.args.get("include_archived") not in ("1", "true", "yes"):
        q = q.filter(Project.archived_at.is_(None))
    q = q.order_by(Project.id.asc())
    rows, total = paginate(q)
    resp = jsonify([p.to_dict() for p in rows])
    return with_total_count(resp, total), 200


@bp.post("")
@require_role("admin", "pm")
def create_project():
    # 【§2.2】非串 name/key → 400（此前 .strip() 500）。
    # 【§2.6③】max_len 对齐 models/project.py 列宽（key String(16) / name String(128)）：
    # 超长此前 201 落库，SQLite 不强制长度所以不炸，换 PG/MySQL 即硬 500。
    data = json_body()
    name = want_str(data, "name", max_len=128)
    key = want_str(data, "key", max_len=16).upper()
    # 【§2.6②】非串 description → 400（此前绑到 Text 列 commit 触 500）。
    description = want_str(data, "description", required=False, strip=False) or None

    if not name or not key:
        return jsonify({"error": "name and key are required"}), 400
    if Project.query.filter_by(key=key).first():
        return jsonify({"error": "project key already exists"}), 409

    owner = current_user()
    project = Project(name=name, key=key, description=description,
                      owner_id=owner.id if owner else None)
    db.session.add(project)
    db.session.commit()
    return jsonify(project.to_dict()), 201


@bp.get("/<int:project_id>")
@jwt_required()
def get_project(project_id):
    project = db.session.get(Project, project_id)
    if project is None:
        return jsonify({"error": "project not found"}), 404
    return jsonify(project.to_dict()), 200


@bp.patch("/<int:project_id>")
@require_role("admin", "pm")
def patch_project(project_id):
    """改名 / 改 key / 改 owner / 归档与取消归档（§2.6）。

    key 改动做唯一性检查（排除自身），冲突 409，与 create_project 同契约；
    key 统一 .upper()，与创建路径一致。archived 是 bool 语义参数，映射到 archived_at
    ——对外只暴露 bool，不让客户端写时间戳。
    """
    project = db.session.get(Project, project_id)
    if project is None:
        return jsonify({"error": "project not found"}), 404
    data = json_body()

    changed = False
    if "name" in data:
        name = want_str(data, "name", required=True, max_len=128)
        project.name = name
        changed = True
    if "key" in data:
        key = want_str(data, "key", required=True, max_len=16).upper()
        if Project.query.filter(Project.key == key, Project.id != project.id).first():
            return jsonify({"error": "project key already exists"}), 409
        project.key = key
        changed = True
    if "description" in data:
        # 【§2.6②】非串 description → 400；空 → None（与创建路径同款写法）。
        project.description = want_str(data, "description", required=False, strip=False) or None
        changed = True
    if "owner_id" in data:
        # 传 null 即清空；传整数须经 want_int + 存在性校验（不写第四份手搓校验）。
        owner_id, oerr = _want_owner_id(data)
        if oerr:
            return oerr
        project.owner_id = owner_id
        changed = True
    if "archived" in data:
        archived = want_bool(data, "archived", required=True)
        project.archived_at = utcnow() if archived else None
        changed = True

    # 【P2-5 同型】无任何可更新字段 → 400，不返回「看起来改成功了」的 200。
    if not changed:
        return jsonify({"error": "no updatable field"}), 400

    db.session.commit()
    return jsonify(project.to_dict()), 200


@bp.delete("/<int:project_id>")
@require_role("admin")   # 比 PATCH 更严：删项目是比建项目危险得多的动作。
def delete_project(project_id):
    """删除空项目；仍有工单则 409（§2.6）。

    **绝不依赖外键异常兜底**：IntegrityError 会被 errors.py 的兜底处理器变成 500，
    用户看到「internal server error」而不是「这个项目还有 12 张单」。前置检查是唯一
    能给出可操作信息的做法（CLAUDE.md 五：错误信息必须包含定位线索）。
    """
    project = db.session.get(Project, project_id)
    if project is None:
        return jsonify({"error": "project not found"}), 404
    refs = lifecycle.project_references(project_id)
    # 【version-plan-hierarchy §3.5】版本非空同样 409：versions.project_id 是真外键，
    # 硬删会触 IntegrityError → 兜底 500，而非可操作的「还有 N 个版本」。
    if refs["requirements"] or refs["bugs"] or refs["versions"]:
        return lifecycle.conflict_project_has_tickets(refs)
    # 【G3③】破坏性动作必须可回溯。Activity 现已承载 user / app_setting
    # （account-security-and-governance §2.3 C-1），但**项目 / Agent 的删除有意仍走
    # 结构化日志**：它们不是账号治理，给它们建实体维度会让 entity_type 从「有语义的
    # 实体维度」退化成一个什么都装的垃圾桶（该轮 §10 明确的非目标）。
    actor = current_user()
    log.info("project deleted: id=%s key=%s by=%s",
             project.id, project.key, actor.username if actor else "system")
    db.session.delete(project)
    db.session.commit()
    return "", 204
