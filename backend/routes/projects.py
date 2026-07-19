"""项目路由（§4.2）。list / create(admin|pm) / get。"""
from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required

from extensions import db
from models.project import Project
from services.auth_helpers import require_role, current_user
from services.pagination import paginate, with_total_count
from services.validation import json_body, want_str

bp = Blueprint("projects", __name__, url_prefix="/api/projects")


@bp.get("")
@jwt_required()
def list_projects():
    # 【§2.9-G1】补分页 + X-Total-Count（响应体仍是裸数组，契约不变）；消费方显式传 limit=200。
    q = Project.query.order_by(Project.id.asc())
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
