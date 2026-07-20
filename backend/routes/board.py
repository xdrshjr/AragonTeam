"""看板路由（§4.5 + lifecycle-and-governance §2.8）。按 workflow 列分组返回卡片。

返回 shape：{columns:[{key, title, items:[...], total, truncated}]}，列顺序 =
workflow.columns 顺序，列内按 position ASC, id ASC 排序（【R-09】）。
每列上限由 `?column_limit=`（默认 100，钳制 [1,500]）控制，分页算法收敛在
services/board_page.py，本文件只做「取参 → 调服务 → 渲染契约」。
"""
from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required

from models.requirement import Requirement
from models.bug import Bug
from services import board_page
from services.scope import project_scope

bp = Blueprint("board", __name__, url_prefix="/api/board")


@bp.get("/requirements")
@jwt_required()
def board_requirements():
    # 非法 ?project_id= / ?column_limit= 由 errors.py 的 QueryParamError 全局处理器统一 400。
    return jsonify(board_page.column_page(
        Requirement, "requirement", project_scope(), board_page.wanted_column_limit())), 200


@bp.get("/bugs")
@jwt_required()
def board_bugs():
    return jsonify(board_page.column_page(
        Bug, "bug", project_scope(), board_page.wanted_column_limit())), 200
