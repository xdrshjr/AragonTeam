"""Agent 自主协作编排（Phase-3 §2.2 支柱 A · 核心）。

在 Phase-2 `agent_runner.advance_one`（推进原子操作，内建防御性 can_transition 复核、
写 Agent 评论、写 actor=agent 审计）之上新增**编排层**：认领哪些单、按什么顺序推、推几步、
如何提交、如何扇出通知。确定性、可单测、无外部依赖：
- 认领按 (created_at ASC, id ASC) 取该泳道内最久未指派者；
- 推进复用 Phase-2 已被单测覆盖的 AGENT_FORWARD。

**不新增任何绕过状态机的路径**——推进永远经 advance_one → workflow.can_transition。
未来接真实 Agent 仍只需替换 advance_one 内部动作生成，本编排层 / 接口 / 数据模型 / 前端不变。

软锁（busy）与 commit 节奏由 routes/agents.py 编排（与 Phase-2 run=all 的 busy 语义一致）；
本模块专注「推进哪些单、推几步、扇出通知」，认领 / 每步各自可提交。
"""
import time

from extensions import db
from models.requirement import Requirement
from models.bug import Bug
from models.agent import Agent
from models.activity import Activity
from services import workflow, agent_runner, notifications, agent_executor

# 单个 Agent 一次 autorun 的全局步数兜底（防长循环，§7 风险表）。
MAX_AUTOPILOT_STEPS = 24

_MODELS = {"requirement": Requirement, "bug": Bug}

# (agent.kind) → 可主动认领的 [(entity, claimable_status), ...]；仅认领 assignee_id IS NULL 的单。
# qa 处理的是已在流程中（testing/verifying）的**已指派**单，不主动认领「新」单（避免抢占分诊）。
AGENT_CLAIMABLE = {
    "dev": [("requirement", "new"), ("bug", "open")],
    "generic": [("requirement", "new"), ("bug", "open")],
    "qa": [],
}

# 推进到该「(entity)->status」即进入 qa 职责区，需交接给 qa-agent 继续（§2.2 核心 P1）。
_QA_HANDOFF_STATUS = {"requirement": "testing", "bug": "verifying"}


def _maybe_handoff_to_qa(entity, ticket):
    """dev/generic 把单推进到 qa 泳道状态后，重指派给一个可用 qa-agent（**不 commit、不改状态**）。

    只改多态 assignee（assignee_type='agent' + assignee_id=qa.id）——状态迁移已由 advance_one
    合法完成，本函数**绝不**触碰 status/position（不绕过状态机）。无可用 qa-agent → no-op。
    返回被交接到的 qa-agent 或 None。
    """
    if ticket.status != _QA_HANDOFF_STATUS.get(entity):
        return None
    # 已是 qa-agent 名下 → 无需交接。
    if ticket.assignee_type == "agent" and ticket.assignee_id is not None:
        cur = db.session.get(Agent, ticket.assignee_id)
        if cur is not None and cur.kind == "qa":
            return None
    # 取一个非 offline 的 qa-agent（优先 idle；busy 也可，下一轮会处理）。
    qa = Agent.query.filter_by(kind="qa").filter(Agent.status != "offline")\
        .order_by(Agent.id.asc()).first()
    if qa is None:
        return None
    ticket.assignee_type = "agent"
    ticket.assignee_id = qa.id
    Activity.log(
        entity, ticket.id, "assigned", actor=("agent", qa.id),
        from_status=ticket.status, to_status=ticket.status,
        message=f"{qa.name} 接手{_label(entity)}「{ticket.title}」进入测试/验证",
    )
    # 【评审 R1】通知源单 reporter（人类）qa 已接手：复用 notify_claim（收件人=reporter、
    # type="assigned"）。**绝不**用 notify_assignment——它仅通知**人类 assignee**，而此刻
    # assignee 已是 qa-agent（Agent），会在 notifications.py 对非 user assignee 直接 return、
    # 静默不发，使「reporter 收到交接通知」的验收断言落空。reporter 缺省（None）→ notify 自跳过。
    notifications.notify_claim(ticket, entity, qa)
    return qa


def _claim_from_lane(agent, entity, claimable_status):
    """在某泳道内取最久未指派、状态匹配的一张并认领之（**不 commit**）。返回 ticket 或 None。

    认领 = 复用 assign 语义：设 assignee=agent + new/open→assigned（经 can_transition）
    + position 落列尾 + 写 assigned 审计。此逻辑与 routes.requirements.assign_requirement /
    routes.bugs.assign_bug 对齐——如需改动指派语义，两处须同步〔R3-06 交叉引用保持对齐〕。
    """
    model = _MODELS[entity]
    ticket = model.query.filter_by(status=claimable_status, assignee_id=None)\
        .order_by(model.created_at.asc(), model.id.asc()).first()
    if ticket is None:
        return None

    frm = ticket.status
    ticket.assignee_type = "agent"
    ticket.assignee_id = agent.id
    # new→assigned / open→assigned 均为 workflow 合法边，仍经 can_transition 裁决。
    if workflow.can_transition(entity, frm, "assigned"):
        ticket.status = "assigned"
        ticket.position = agent_runner._next_position(model, "assigned")
    Activity.log(
        entity, ticket.id, "assigned", actor=("agent", agent.id),
        from_status=frm, to_status=ticket.status,
        message=f"{agent.name} 自动认领了{_label(entity)}「{ticket.title}」",
    )
    return ticket


def claim_next(agent, entity=None):
    """认领一张（可选 entity 限定只认领某类）。返回 (entity, ticket) 或 (None, None)。不 commit。

    命中后扇出通知给该单 reporter（若人类）；Agent 不作收件人（notify 内已保证）。
    """
    lanes = AGENT_CLAIMABLE.get(agent.kind, [])
    for ent, status in lanes:
        if entity and ent != entity:
            continue
        ticket = _claim_from_lane(agent, ent, status)
        if ticket is not None:
            notifications.notify_claim(ticket, ent, agent)
            return ent, ticket
    return None, None


def autorun(agent, run_all=False):
    """扫描并推进 agent 名下所有可推进工单。返回 {advanced, skipped}。

    默认每单一步；run_all 时每单连续推进至「无预置动作 / 终态 / 单工单 MAX_AGENT_STEPS」。
    **每一步各自 commit**（复用 advance_one）。命中 NoAgentAction / 终态 → 记 skipped（不改库）。
    全局步数 MAX_AUTOPILOT_STEPS 兜底防长循环。busy 软锁 / 最终归 idle 由路由层负责。
    """
    advanced = []
    skipped = []
    total_steps = 0
    # 【P2-1】LLM 活跃时的墙钟预算：累计 LLM 墙钟超预算 → 其余单以 reason="budget" 跳过。
    # 离线 / 测试 / 未配置恒 None（预算永不触发），故本判定对既有行为逐字节不变。
    budget = agent_executor.wall_budget_seconds()
    started = time.monotonic()

    for entity in ("requirement", "bug"):
        model = _MODELS[entity]
        tickets = model.query.filter_by(assignee_type="agent", assignee_id=agent.id)\
            .order_by(model.id.asc()).all()
        for ticket in tickets:
            if _over_budget(budget, started):
                skipped.append({"entity": entity, "id": ticket.id, "reason": "budget"})
                continue
            steps_this = 0
            while True:
                if total_steps >= MAX_AUTOPILOT_STEPS:
                    if steps_this == 0:
                        skipped.append({"entity": entity, "id": ticket.id, "reason": "cap"})
                    break
                if workflow.is_terminal(entity, ticket.status):
                    if steps_this == 0:
                        skipped.append({"entity": entity, "id": ticket.id, "reason": "terminal"})
                    break
                frm = ticket.status
                try:
                    to, comment, _activity = agent_runner.advance_one(entity, ticket, agent)
                except agent_runner.NoAgentAction:
                    # 【评审 R2】存量卡在 qa 泳道状态的非-qa 单也要交接，否则永远走不完。
                    handed = _maybe_handoff_to_qa(entity, ticket)
                    if handed is not None:
                        db.session.commit()
                        break   # 已易主，交 qa-agent 接力（本轮后续 / 下一轮）
                    if steps_this == 0:
                        skipped.append({"entity": entity, "id": ticket.id, "reason": "no-action"})
                    break
                db.session.commit()
                total_steps += 1
                steps_this += 1
                advanced.append({
                    "entity": entity, "id": ticket.id,
                    "from": frm, "to": to, "message": comment.body,
                })
                # 扇出推进通知给 reporter / 人类 assignee（Agent 自主推进，排除 agent 自身）。
                notifications.notify_advance(
                    ticket, entity, actor=("agent", agent.id),
                    from_status=frm, to_status=to,
                )
                db.session.commit()
                # —— dev→qa 交接（闭合自主闭环）；交接只改 assignee，随本步事务一并提交 ——
                handed = _maybe_handoff_to_qa(entity, ticket)
                if handed is not None:
                    db.session.commit()
                    break   # 本 agent 不再推进此单（已易主），交由 qa-agent 下一轮/本轮处理
                if not run_all:
                    break
                if steps_this >= agent_runner.MAX_AGENT_STEPS:
                    break
    return {"advanced": advanced, "skipped": skipped}


def tick(agent, claim=True, claim_count=1, run_all=False):
    """一次自主循环 = 认领 claim_count 次（各自事务）+ 一次 autorun。

    返回 {claimed, advanced, skipped}。busy 软锁由路由层管理。
    """
    claimed = []
    if claim:
        for _ in range(max(0, int(claim_count or 0))):
            ent, ticket = claim_next(agent)
            if ticket is None:
                break
            db.session.commit()  # 认领各自事务（§2.2.3 C）
            claimed.append({"entity": ent, "id": ticket.id, "status": ticket.status})
    run = autorun(agent, run_all=run_all)
    return {"claimed": claimed, "advanced": run["advanced"], "skipped": run["skipped"]}


_LABELS = {"requirement": "需求", "bug": "BUG"}


def _label(entity: str) -> str:
    return _LABELS.get(entity, entity)


def _over_budget(budget, started) -> bool:
    """墙钟预算是否已耗尽（`budget=None` 恒 False，离线 / 未启用不受影响，§3.8 P2-1）。"""
    return budget is not None and (time.monotonic() - started) >= budget
