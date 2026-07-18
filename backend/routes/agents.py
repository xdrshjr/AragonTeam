"""Agent 路由（§4.2）。list / create(admin|pm) / patch。"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from extensions import db
from models.agent import Agent, AGENT_KINDS, AGENT_STATUSES
from services.auth_helpers import require_role

bp = Blueprint("agents", __name__, url_prefix="/api/agents")


@bp.get("")
@jwt_required()
def list_agents():
    agents = Agent.query.order_by(Agent.id.asc()).all()
    return jsonify([a.to_dict() for a in agents]), 200


@bp.post("")
@require_role("admin", "pm")
def create_agent():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    kind = data.get("kind") or "generic"
    description = data.get("description")

    if not name:
        return jsonify({"error": "name is required"}), 400
    if kind not in AGENT_KINDS:
        return jsonify({"error": "invalid kind", "detail": {"allowed": list(AGENT_KINDS)}}), 400
    if Agent.query.filter_by(name=name).first():
        return jsonify({"error": "agent name already exists"}), 409

    agent = Agent(name=name, kind=kind, description=description, status="idle")
    db.session.add(agent)
    db.session.commit()
    return jsonify(agent.to_dict()), 201


@bp.get("/<int:agent_id>")
@jwt_required()
def get_agent(agent_id):
    agent = db.session.get(Agent, agent_id)
    if agent is None:
        return jsonify({"error": "agent not found"}), 404
    return jsonify(agent.to_dict()), 200


@bp.patch("/<int:agent_id>")
@jwt_required()
def patch_agent(agent_id):
    agent = db.session.get(Agent, agent_id)
    if agent is None:
        return jsonify({"error": "agent not found"}), 404
    data = request.get_json(silent=True) or {}

    if "status" in data:
        if data["status"] not in AGENT_STATUSES:
            return jsonify({"error": "invalid status",
                            "detail": {"allowed": list(AGENT_STATUSES)}}), 400
        agent.status = data["status"]
    if "description" in data:
        agent.description = data["description"]

    db.session.commit()
    return jsonify(agent.to_dict()), 200
