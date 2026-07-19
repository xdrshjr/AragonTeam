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
# 【scale-and-project-scope §2.2④】generic 亦置空：它在 AGENT_FORWARD 里只有 assigned 一条边，
# 认领后必然在下一状态无动作，而 assignee_id 已非空 → 其他 Agent 也不会再认领，单永久泊死。
# generic 仍可被 pm **显式指派**并推进一步，随后由 maybe_handoff 转给对口 kind，能力不减。
AGENT_CLAIMABLE = {
    "dev": [("requirement", "new"), ("bug", "open")],
    "generic": [],
    "qa": [],
}


def _derive_kind_for_status() -> dict:
    """由 AGENT_FORWARD 键集派生「(entity, status) → 唯一能处理它的 agent kind」。

    单一真相：交接目标不另立一张会漂移的表，直接从推进表反推。
    某状态若有 **多种** kind 都能处理（如 assigned 兼容 dev / generic），映射为 None
    ——多解即不自动交接，避免抢走 generic 自己能干的活。

    Returns:
        {(entity, status): kind | None}
    """
    table: dict = {}
    for entity, kind, status in agent_runner.AGENT_FORWARD:
        key = (entity, status)
        if key in table and table[key] != kind:
            table[key] = None          # 多解 → 不交接
        else:
            table.setdefault(key, kind)
    return table


_KIND_FOR_STATUS = _derive_kind_for_status()


def maybe_handoff(entity, ticket):
    """当前 assignee 的 kind 与该状态所需 kind 不符时，重指派给一个可用的对口 Agent。

    **不 commit、不改状态**——只改多态 assignee（assignee_type='agent' + assignee_id）。
    状态迁移已由 advance_one 合法完成，本函数绝不触碰 status/position（不绕过状态机）。
    无对口 / 无可用 Agent / 已是对口 kind / 该状态多解 / **单在人类手里** → 一律 no-op 返回 None。

    Args:
        entity: "requirement" | "bug"。
        ticket: 已完成状态迁移的工单实例。

    Returns:
        被交接到的 Agent，或 None（未发生交接）。
    """
    need = _KIND_FOR_STATUS.get((entity, ticket.status))
    if need is None:
        return None
    # 【评审 R2 · 必须在最前】交接只在 Agent 之间发生，绝不从人手里抢单。守卫必须在
    # db.session.get(Agent, …) **之前**：assignee 是人类时 assignee_id 指向 users.id，
    # 若先去 Agent 表取，会取到一个同 id 的不相干 Agent，判据随即失真。
    if ticket.assignee_type != "agent" or ticket.assignee_id is None:
        return None
    cur = db.session.get(Agent, ticket.assignee_id)
    if cur is not None and cur.kind == need:
        return None
    # 取一个非 offline 的对口 Agent（优先 idle；busy 也可，下一轮会处理）。
    target = Agent.query.filter_by(kind=need).filter(Agent.status != "offline")\
        .order_by(Agent.id.asc()).first()
    if target is None:
        return None
    ticket.assignee_type = "agent"
    ticket.assignee_id = target.id
    Activity.log(
        entity, ticket.id, "assigned", actor=("agent", target.id),
        from_status=ticket.status, to_status=ticket.status,
        message=f"{target.name} 接手{_label(entity)}「{ticket.title}」继续处理",
    )
    # 【第 2 轮评审 R1，务必保留】通知源单 reporter（人类）：必须用 notify_claim
    # （收件人=reporter、type="assigned"）。**绝不**用 notify_assignment——它仅通知人类
    # assignee，而此刻 assignee 已是 Agent，会被 notifications.py 静默丢弃。
    notifications.notify_claim(ticket, entity, target)
    return target


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
        # 【§2.5】position 按「同项目同状态」编号，与看板可见集合同域。
        ticket.position = agent_runner._next_position(model, "assigned", ticket.project_id)
    Activity.log(
        entity, ticket.id, "assigned", actor=("agent", agent.id),
        from_status=frm, to_status=ticket.status,
        message=f"{agent.name} 自动认领了{_label(entity)}「{ticket.title}」",
    )
    return ticket


def claim_next(agent, entity=None):
    """认领一张（可选 entity 限定只认领某类）。返回 (entity, ticket) 或 (None, None)。不 commit。

    命中后扇出通知给该单 reporter（若人类）；Agent 不作收件人（notify 内已保证）。

    【§2.2④ · 评审 R10】`generic` 自本轮起**不参与自主认领**（AGENT_CLAIMABLE["generic"] = []），
    故对 generic Agent 恒返回 (None, None)，由路由的「无可认领」分支渲染 —— **响应码与体保持
    现网不变**（`{"claimed": null}` + 200）。generic 仍可被 pm 显式指派、推进一步，随后由
    maybe_handoff 转给对口 kind。
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
                    # 【评审 R2】存量卡在他人泳道状态的单也要交接，否则永远走不完。
                    handed = maybe_handoff(entity, ticket)
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
                # —— 按状态交接（闭合自主闭环）；交接只改 assignee，随本步事务一并提交 ——
                handed = maybe_handoff(entity, ticket)
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
