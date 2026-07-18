"""仪表盘统计路由（§4.5）。

GET /api/stats → {requirements:{by_status}, bugs:{by_status}, agents:{idle,busy}, members}
另附 recent_activities，供仪表盘「最近活动」时间线。
"""
from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required

from extensions import db
from models.requirement import Requirement
from models.bug import Bug
from models.agent import Agent
from models.user import User
from models.activity import Activity
from services import workflow

bp = Blueprint("stats", __name__, url_prefix="/api")


def _by_status(model, entity):
    counts = {key: 0 for key in workflow.column_keys(entity)}
    for status, in db.session.query(model.status).all():
        counts[status] = counts.get(status, 0) + 1
    return counts


@bp.get("/stats")
@jwt_required()
def stats():
    agents = Agent.query.all()
    agent_counts = {"idle": 0, "busy": 0, "offline": 0}
    for a in agents:
        agent_counts[a.status] = agent_counts.get(a.status, 0) + 1

    recent = Activity.query.order_by(
        Activity.created_at.desc(), Activity.id.desc()).limit(10).all()

    return jsonify({
        "requirements": {
            "total": Requirement.query.count(),
            "by_status": _by_status(Requirement, "requirement"),
        },
        "bugs": {
            "total": Bug.query.count(),
            "by_status": _by_status(Bug, "bug"),
        },
        "agents": {
            "total": len(agents),
            "idle": agent_counts.get("idle", 0),
            "busy": agent_counts.get("busy", 0),
            "offline": agent_counts.get("offline", 0),
        },
        "members": User.query.count(),
        "recent_activities": [a.to_dict() for a in recent],
    }), 200
