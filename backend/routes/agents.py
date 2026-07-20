"""Agent 路由（§4.2 + Phase-3 §2.2 支柱 A）。

list / create(admin|pm) / patch，以及 Agent 自主协作编排（pm/admin）：
claim-next / autorun / tick / 顶层 autorun-all。自主编排以 agent.status="busy" 为
**软锁**（运行中再次触发 → 409），无论正常 / 异常 finally 归 idle（与 Phase-2 run=all 一致）。
"""
import logging

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from extensions import db
from models.agent import Agent, AGENT_KINDS
from services.auth_helpers import require_role, current_user
from services.pagination import paginate, with_total_count
from services.validation import json_body, want_str, want_int
from services import agent_autopilot, lifecycle

bp = Blueprint("agents", __name__, url_prefix="/api/agents")

log = logging.getLogger("aragon.agents")


def _run_with_lock(agent, fn):
    """busy 软锁（§2.2.1）：置 busy 并 commit（开锁 + 可观测）→ 执行 →
    finally **恢复原状态** 并 commit（含异常路径），与 Phase-2 `_agent_run_all` 同策略。

    【§2.6-E1】记录并恢复 prev（此时 prev 恒为 idle——offline/busy 已被入口门禁挡在外——
    但显式恢复更正确、防未来回归，避免把 offline agent 跑完清成 idle。"""
    prev = agent.status
    agent.status = "busy"
    db.session.commit()
    try:
        return fn()
    finally:
        # 【§2.9-G3】先回滚可能的半提交事务：若 fn() 抛 DB 级异常，这里的 commit 自身会抛
        # PendingRollbackError，软锁恢复丢失 → Agent 永久 busy，此后每次 autorun/tick 都 409，
        # 只能靠管理员手动 PATCH 复位。
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover - 回滚失败不应掩盖原异常
            pass
        agent.status = prev
        db.session.commit()


@bp.get("")
@jwt_required()
def list_agents():
    # 【§2.9-G1】补分页 + X-Total-Count（响应体仍是裸数组，契约不变）；消费方显式传 limit=200。
    q = Agent.query.order_by(Agent.id.asc())
    rows, total = paginate(q)
    resp = jsonify([a.to_dict() for a in rows])
    return with_total_count(resp, total), 200


@bp.post("")
@require_role("admin", "pm")
def create_agent():
    # 【§2.2】非串 name → 400（此前 .strip() 500）；kind 走 choices 归一。
    data = json_body()
    # 【§2.6③】max_len 对齐 models/agent.py 的 String(64)：超长此前 201 落库，换 PG/MySQL 即 500。
    name = want_str(data, "name", max_len=64)
    kind = want_str(data, "kind", default="generic", choices=AGENT_KINDS)
    # 【§2.6②】非串 description → 400（此前绑到 Text 列 commit 触 500）。
    description = want_str(data, "description", required=False, strip=False) or None

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
        name = want_str(data, "name", max_len=64)        # 非串 name → 400；超长 → 400（§2.6③）
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
        # 【§2.6②】非串 description → 400（此前直接赋值，commit 触 500）。
        agent.description = want_str(data, "description", required=False, strip=False) or None

    db.session.commit()
    return jsonify(agent.to_dict()), 200


@bp.delete("/<int:agent_id>")
@require_role("admin", "pm")   # 与 create/patch 同级。
def delete_agent(agent_id):
    """删除 Agent；名下仍有**未终态**工单则 409（lifecycle-and-governance §2.7）。

    终态单不阻止删除——它们已经完成，其历史由评论 / 时间线承载，而
    comment._resolve_author 与 requirement._resolve_assignee 都会优雅降级为
    「(已删除)」占位，可读性不受影响。
    """
    agent = db.session.get(Agent, agent_id)
    if agent is None:
        return jsonify({"error": "agent not found"}), 404
    load = lifecycle.agent_open_workload(agent_id)
    if load["requirements"] or load["bugs"]:
        return lifecycle.conflict_agent_has_open_tickets(load)
    # 【G3③】破坏性动作必须可回溯；Activity 只承载 requirement/bug，故走结构化日志。
    actor = current_user()
    log.info("agent deleted: id=%s name=%s by=%s",
             agent.id, agent.name, actor.username if actor else "system")
    db.session.delete(agent)
    db.session.commit()
    return "", 204


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
        # 【§2.6-E1】跳过 busy（运行中软锁）与 offline（管理员显式停用）；reason 精确到状态，
        # 且**不**经 _run_with_lock，故 offline agent 状态不被清成 idle。
        if agent.status in ("busy", "offline"):
            runs.append({"agent": agent.to_dict(), "claimed": [], "advanced": [],
                         "skipped": [{"reason": agent.status}]})
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
    """让 Agent 自主认领一张新单。

    【§2.2⑤】busy/offline 门禁：此前 offline Agent 可认领成功（200），紧接着 /autorun 却 409
    ——「吞了又不干」的纯陷阱态。与 /autorun、/tick、run=all 对齐。
    **有意不改**：单步 agent-advance 仍不设 offline 门禁——那是 pm/admin 的手动操作，
    人已经知道自己在做什么（第 2 轮评审 R5 的显式裁定），二者不矛盾。

    【§2.2④】`generic` 自本轮起不参与自主认领（AGENT_CLAIMABLE["generic"] = []），
    故对 generic Agent 恒返回 `{"claimed": null}` + 200（响应契约不变）。
    """
    agent = db.session.get(Agent, agent_id)
    if agent is None:
        return jsonify({"error": "agent not found"}), 404
    if agent.status in ("busy", "offline"):
        return jsonify({"error": "agent is busy or offline"}), 409
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
    if agent.status in ("busy", "offline"):
        # 【§2.6-E1】busy=运行中软锁；offline=管理员显式停用，autopilot 尊重之。
        return jsonify({"error": "agent is busy or offline"}), 409
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
    if agent.status in ("busy", "offline"):
        # 【§2.6-E1】busy=运行中软锁；offline=管理员显式停用，autopilot 尊重之。
        return jsonify({"error": "agent is busy or offline"}), 409
    data = json_body()
    claim = data.get("claim", True)
    # 【§2.4-C1】非整 claim_count（"x"）此前经 int("x") 触 500；want_int 保证非整即 400，上限 20 防滥用。
    claim_count = want_int(data, "claim_count", default=1, minimum=0, maximum=20)
    run_all = request.args.get("run") == "all"
    result = _run_with_lock(agent, lambda: agent_autopilot.tick(
        agent, claim=claim, claim_count=claim_count, run_all=run_all))
    return jsonify({
        "agent": agent.to_dict(),
        "claimed": result["claimed"],
        "advanced": result["advanced"],
        "skipped": result["skipped"],
    }), 200
