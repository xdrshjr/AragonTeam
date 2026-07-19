"""仪表盘统计路由（§4.5）。

GET /api/stats → {requirements:{by_status}, bugs:{by_status}, agents:{idle,busy}, members}
另附 recent_activities，供仪表盘「最近活动」时间线。
"""
from datetime import timedelta

from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required
from sqlalchemy import func

from extensions import db, utcnow
from models.requirement import Requirement
from models.bug import Bug
from models.agent import Agent
from models.user import User
from models.activity import Activity
from services import workflow
from services.scope import apply_project_filter, project_scope

bp = Blueprint("stats", __name__, url_prefix="/api")


def _by_status(model, entity, scope):
    """按状态计数。以 SQL GROUP BY 聚合（此前逐行取回 Python 累加，单量上万即 O(N) 内存）。"""
    counts = {key: 0 for key in workflow.column_keys(entity)}
    q = apply_project_filter(
        db.session.query(model.status, func.count(model.id)), model, scope
    ).group_by(model.status)
    for status, n in q.all():
        # 列集合外的历史状态容错入表（与 board.py 的 setdefault 同策略）。
        counts[status] = counts.get(status, 0) + n
    return counts


@bp.get("/stats")
@jwt_required()
def stats():
    """仪表盘统计。可选 `?project_id=`（整数 / `none`）过滤 requirements 与 bugs。

    **有意保持全局、不随项目过滤**的字段：`agents.*`（Agent 是全局共享的执行者，不隶属项目）、
    `members`（全局账号）、`activities_this_week` 与 `recent_activities`（`activities` 表
    **没有 project_id 列**，按项目过滤需连表回查并分别处理两种 entity_type，属过度设计，
    见 spec §8-5）。前端须对这些字段显式标注「（全部项目）」，不得让用户误以为它们受作用域约束。
    """
    scope = project_scope()
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
            "total": apply_project_filter(Requirement.query, Requirement, scope).count(),
            "by_status": _by_status(Requirement, "requirement", scope),
        },
        "bugs": {
            "total": apply_project_filter(Bug.query, Bug, scope).count(),
            "by_status": _by_status(Bug, "bug", scope),
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
