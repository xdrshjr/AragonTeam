"""Agent 路由（§4.2 + Phase-3 §2.2 支柱 A）。

list / create(admin|pm) / patch，以及 Agent 自主协作编排（pm/admin）：
claim-next / autorun / tick / 顶层 autorun-all。自主编排以 agent.status="busy" 为
**软锁**（运行中再次触发 → 409），无论正常 / 异常 finally 归 idle（与 Phase-2 run=all 一致）。
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from extensions import db
from models.agent import Agent, AGENT_KINDS
from services.auth_helpers import require_role
from services.validation import json_body, want_str
from services import agent_autopilot

bp = Blueprint("agents", __name__, url_prefix="/api/agents")


def _run_with_lock(agent, fn):
    """busy 软锁（§2.2.1）：置 busy 并 commit（开锁 + 可观测）→ 执行 →
    finally 归 idle 并 commit（含异常路径），与 Phase-2 `_agent_run_all` 同策略。"""
    agent.status = "busy"
    db.session.commit()
    try:
        return fn()
    finally:
        agent.status = "idle"
        db.session.commit()


@bp.get("")
@jwt_required()
def list_agents():
    agents = Agent.query.order_by(Agent.id.asc()).all()
    return jsonify([a.to_dict() for a in agents]), 200


@bp.post("")
@require_role("admin", "pm")
def create_agent():
    # 【§2.2】非串 name → 400（此前 .strip() 500）；kind 走 choices 归一。
    data = json_body()
    name = want_str(data, "name")
    kind = want_str(data, "kind", default="generic", choices=AGENT_KINDS)
    description = data.get("description")

    if not name:
        return jsonify({"error": "name is required"}), 400
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
@require_role("admin", "pm")   # 收紧：原 @jwt_required() 任意成员可改共享 Agent → 与 POST 对齐（有意契约变更）
def patch_agent(agent_id):
    agent = db.session.get(Agent, agent_id)
    if agent is None:
        return jsonify({"error": "agent not found"}), 404
    data = json_body()

    if "name" in data:                                   # 新增：支持改名（编辑 Agent 的核心）
        name = want_str(data, "name")                    # 非串 name → 400（此前 .strip() 500）
        if not name:
            return jsonify({"error": "name is required"}), 400
        if Agent.query.filter(Agent.name == name, Agent.id != agent.id).first():
            return jsonify({"error": "agent name already exists"}), 409
        agent.name = name
    if "kind" in data:                                   # 新增：支持改类型
        agent.kind = want_str(data, "kind", required=True, choices=AGENT_KINDS)
    if "status" in data:
        # 【§2.3-B3】禁止手动置 busy：busy 是 autopilot 运行期软锁，被手动置入后
        # /autorun、/tick 恒 409 且无自动恢复，Agent 永久卡死。仅允许 idle/offline，
        # 保留 pm/admin 把误锁 Agent 手动置回 idle 的能力。
        status = want_str(data, "status")
        if status not in ("idle", "offline"):
            return jsonify({"error": "status must be idle or offline"}), 400
        agent.status = status
    if "description" in data:
        agent.description = data["description"]

    db.session.commit()
    return jsonify(agent.to_dict()), 200


# ————————————————————— Agent 自主协作编排（Phase-3 §2.2）—————————————————————

@bp.post("/autorun-all")
@require_role("admin", "pm")
def agents_autorun_all():
    """运行整支 AI 团队一轮（§2.2.3 D）：对所有 Agent（跳过 busy）各执行一次 tick。

    注意：本路由须在 `/<int:agent_id>/...` 之前无冲突（'autorun-all' 非 int，路由不歧义）。
    """
    data = json_body()
    claim = data.get("claim", True)
    run_all = request.args.get("run") == "all"
    runs = []
    for agent in Agent.query.order_by(Agent.id.asc()).all():
        if agent.status == "busy":
            runs.append({"agent": agent.to_dict(), "claimed": [], "advanced": [],
                         "skipped": [{"reason": "busy"}]})
            continue
        result = _run_with_lock(
            agent, lambda a=agent: agent_autopilot.tick(a, claim=claim, run_all=run_all))
        runs.append({
            "agent": agent.to_dict(),
            "claimed": result["claimed"],
            "advanced": result["advanced"],
            "skipped": result["skipped"],
        })
    return jsonify({"runs": runs}), 200


@bp.post("/<int:agent_id>/claim-next")
@require_role("admin", "pm")
def agent_claim_next(agent_id):
    agent = db.session.get(Agent, agent_id)
    if agent is None:
        return jsonify({"error": "agent not found"}), 404
    data = json_body()
    entity = data.get("entity")  # 可选：限定只认领某类
    _ent, ticket = agent_autopilot.claim_next(agent, entity=entity)
    db.session.commit()
    return jsonify({"claimed": ticket.to_dict() if ticket else None}), 200


@bp.post("/<int:agent_id>/autorun")
@require_role("admin", "pm")
def agent_autorun(agent_id):
    agent = db.session.get(Agent, agent_id)
    if agent is None:
        return jsonify({"error": "agent not found"}), 404
    if agent.status == "busy":
        return jsonify({"error": "agent is busy"}), 409  # 软锁
    run_all = request.args.get("run") == "all"
    result = _run_with_lock(agent, lambda: agent_autopilot.autorun(agent, run_all=run_all))
    return jsonify({
        "agent": agent.to_dict(),  # status == "idle"（已解锁）
        "advanced": result["advanced"],
        "skipped": result["skipped"],
    }), 200


@bp.post("/<int:agent_id>/tick")
@require_role("admin", "pm")
def agent_tick(agent_id):
    agent = db.session.get(Agent, agent_id)
    if agent is None:
        return jsonify({"error": "agent not found"}), 404
    if agent.status == "busy":
        return jsonify({"error": "agent is busy"}), 409  # 软锁
    data = json_body()
    claim = data.get("claim", True)
    claim_count = data.get("claim_count", 1)
    run_all = request.args.get("run") == "all"
    result = _run_with_lock(agent, lambda: agent_autopilot.tick(
        agent, claim=claim, claim_count=claim_count, run_all=run_all))
    return jsonify({
        "agent": agent.to_dict(),
        "claimed": result["claimed"],
        "advanced": result["advanced"],
        "skipped": result["skipped"],
    }), 200
