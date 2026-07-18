"""me 蓝图（Phase-3 §4.3 / 〔R3-02 修复〕）。

`GET /api/me/work`「我的工作」聚合：当前用户为**人类 assignee** 的单 + 其 **reporter**
的单，各按更新时间倒序、limit 兜底。

**必须**承载于本蓝图（url_prefix="/api/me"）——不得挂进 users 蓝图（/api/users），
否则真实路径会变成 /api/users/work，与 §4.3 契约不符（Flask 蓝图路由无法逃逸 url_prefix）。
"""
from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required

from models.requirement import Requirement
from models.bug import Bug
from services.auth_helpers import current_user

bp = Blueprint("me", __name__, url_prefix="/api/me")

# 「我的工作」各分区兜底上限，防单人海量单撑爆响应（MVP 单机量级足够）。
WORK_LIMIT = 100


def _assigned(model, user_id):
    return model.query.filter_by(assignee_type="user", assignee_id=user_id)\
        .order_by(model.updated_at.desc(), model.id.desc()).limit(WORK_LIMIT).all()


def _reported(model, user_id):
    return model.query.filter_by(reporter_id=user_id)\
        .order_by(model.updated_at.desc(), model.id.desc()).limit(WORK_LIMIT).all()


@bp.get("/work")
@jwt_required()
def my_work():
    user = current_user()
    if user is None:
        return jsonify({"error": "unauthorized"}), 401
    return jsonify({
        "assigned": {
            "requirements": [r.to_dict() for r in _assigned(Requirement, user.id)],
            "bugs": [b.to_dict() for b in _assigned(Bug, user.id)],
        },
        "reported": {
            "requirements": [r.to_dict() for r in _reported(Requirement, user.id)],
            "bugs": [b.to_dict() for b in _reported(Bug, user.id)],
        },
    }), 200
