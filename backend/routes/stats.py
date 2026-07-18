"""仪表盘统计路由（§4.5）。

GET /api/stats → {requirements:{by_status}, bugs:{by_status}, agents:{idle,busy}, members}
另附 recent_activities，供仪表盘「最近活动」时间线。
"""
from datetime import timedelta

from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required

from extensions import db, utcnow
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

    # Phase-2 §2.7：本周（近 7 天）活动数，供仪表盘小计。
    week_ago = utcnow() - timedelta(days=7)
    activities_this_week = Activity.query.filter(
        Activity.created_at >= week_ago).count()

    total_agents = len(agents)
    busy = agent_counts.get("busy", 0)
    # Agent 利用率 = busy / total（0..1），无 Agent 时为 0。
    utilization = round(busy / total_agents, 4) if total_agents else 0.0

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
            "total": total_agents,
            "idle": agent_counts.get("idle", 0),
            "busy": busy,
            "offline": agent_counts.get("offline", 0),
            "utilization": utilization,
        },
        "members": User.query.count(),
        "activities_this_week": activities_this_week,
        "recent_activities": [a.to_dict() for a in recent],
    }), 200
