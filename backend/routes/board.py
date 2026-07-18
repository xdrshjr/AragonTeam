"""看板路由（§4.5）。按 workflow 列分组返回卡片。

返回 shape：{columns:[{key, title, items:[...]}]}，列顺序 = workflow.columns 顺序，
列内按 position ASC, id ASC 排序（【R-09】）。
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from models.requirement import Requirement
from models.bug import Bug
from services import workflow

bp = Blueprint("board", __name__, url_prefix="/api/board")


def _grouped(model, entity, project_id):
    q = model.query
    if project_id is not None:
        q = q.filter_by(project_id=project_id)
    rows = q.order_by(model.position.asc(), model.id.asc()).all()
    buckets: dict[str, list] = {key: [] for key in workflow.column_keys(entity)}
    for r in rows:
        # setdefault 仅作防御：状态列由写入侧邻接表校验保证合法，正常不会命中；
        # 万一出现列集合外的异常状态，这里容错入桶避免 KeyError（该卡不会出现在任何标准列）。
        buckets.setdefault(r.status, []).append(r.to_dict())
    columns = []
    for key, title in workflow.columns(entity):
        columns.append({"key": key, "title": title, "items": buckets.get(key, [])})
    return {"columns": columns}


@bp.get("/requirements")
@jwt_required()
def board_requirements():
    project_id = request.args.get("project_id", type=int)
    return jsonify(_grouped(Requirement, "requirement", project_id)), 200


@bp.get("/bugs")
@jwt_required()
def board_bugs():
    project_id = request.args.get("project_id", type=int)
    return jsonify(_grouped(Bug, "bug", project_id)), 200
