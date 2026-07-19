"""Agent 提示词与上下文构建（real-agent-execution §3.4）。

`build_context(entity, ticket, agent, to_status) -> (system, user)`：装配
「Agent 人格 + 平台背景 + 输出规范 + 硬约束」的 system，以及「工单标题/描述/
优先级或严重度/流转方向 + 最近讨论 + 本步交付物说明」的 user。

`ACTION_BRIEF` 的键与 `agent_runner.AGENT_FORWARD` **逐字一致**——`(entity, kind,
current_status)`，1:1 覆盖全部 9 条前进边（含 generic）；缺键回落 `DEFAULT_BRIEF`，
绝不把 None/空指引注入 prompt（P1-3）。
"""
from extensions import db
from models.comment import Comment

# 最近讨论上下文：取该工单最近 N 条评论；单条截断到约 _SNIPPET_MAX 字，防 prompt 膨胀。
_FEED_LIMIT = 6
_SNIPPET_MAX = 500

# 缺省交付物说明：任何未显式配置的前进边都回落到此，保证 prompt 永不含空指引（P1-3）。
DEFAULT_BRIEF = "针对本步目标态，作为该角色 Agent 给出简洁、聚焦、可交接的工作产物。"

# (entity, agent.kind, current_status) → 该步骤的交付物说明。键与 AGENT_FORWARD 逐字一致。
ACTION_BRIEF: dict[tuple[str, str, str], str] = {
    ("requirement", "dev", "assigned"):
        "作为高级工程师，认领并给出实现方案：任务拆解、关键模块与接口、数据结构、"
        "边界与风险，说明本步已做什么、下一步交接给谁。",
    ("requirement", "dev", "in_development"):
        "给出实现与自测结论、变更要点、遗留风险，说明可转测试的依据。",
    ("requirement", "dev", "bug_fixing"):
        "针对测试打回的缺陷：给出根因、修复要点、回归自测结论。",
    ("requirement", "qa", "testing"):
        "作为 QA，给出测试计划与用例（正常路径 + 至少一条异常路径）、执行结论与是否放行。",
    ("bug", "dev", "assigned"):
        "认领缺陷，给出复现步骤与根因定位方向。",
    ("bug", "dev", "fixing"):
        "给出根因定位、修复要点、回归自测结论。",
    ("bug", "qa", "verifying"):
        "作为 QA，给出验证用例与结论、是否可关闭。",
    ("requirement", "generic", "assigned"):
        "作为通用 Agent，认领并给出本步的处理说明与产物。",
    ("bug", "generic", "assigned"):
        "作为通用 Agent，认领并给出本步的处理说明与产物。",
}

# Agent 人格（按 kind）；未知 kind 回落 generic。
_PERSONA = {
    "dev": "你是一名资深研发工程师（dev-agent）",
    "qa": "你是一名资深测试工程师（qa-agent）",
    "generic": "你是一名通用协作 Agent",
}


def brief_for(entity: str, kind: str, status: str) -> str:
    """取该前进边的交付物说明；缺键回落 `DEFAULT_BRIEF`（绝不返回空，P1-3）。"""
    return ACTION_BRIEF.get((entity, kind, status), DEFAULT_BRIEF)


def build_context(entity, ticket, agent, to_status):
    """装配 (system, user) 提示词二元组，供 `agent_executor` 调用真实 LLM。"""
    return _build_system(agent.kind), _build_user(entity, ticket, agent, to_status)


def _build_system(kind: str) -> str:
    persona = _PERSONA.get(kind, _PERSONA["generic"])
    return (
        f"{persona}，在 AragonTeam（AI 时代的团队协作与研发管理平台）中协作。"
        "你的产出会作为一条评论进入该工单的协作时间线，供人类与其他 Agent 查阅。\n"
        "输出规范：简体中文；Markdown；克制精炼、聚焦本步产物，不寒暄、不复述全文。\n"
        "硬约束：不得声称自己已改变工单状态（状态由平台状态机裁决）；不得编造外部系统、"
        "链接或不存在的接口；只产出书面工作产物，不触发任何真实副作用。"
    )


def _build_user(entity, ticket, agent, to_status) -> str:
    frm = ticket.status  # §3.2：本调用置于改状态之前，frm 即当前态。
    lines = [
        f"工单类型：{'需求' if entity == 'requirement' else 'BUG'}",
        f"标题：{ticket.title}",
        f"描述：{ticket.description or '（无描述）'}",
        _grade_line(entity, ticket),
        f"当前流转：{frm} → {to_status}",
        f"本步交付物要求：{brief_for(entity, agent.kind, frm)}",
    ]
    discussion = _recent_discussion(entity, ticket.id)
    if discussion:
        lines.append("最近讨论（旧→新）：\n" + discussion)
    lines.append("请据此产出本步的工作产物。")
    return "\n".join(lines)


def _grade_line(entity, ticket) -> str:
    if entity == "bug":
        return f"严重度：{getattr(ticket, 'severity', '') or '未定级'}"
    return f"优先级：{getattr(ticket, 'priority', '') or '未定级'}"


def _recent_discussion(entity, ticket_id) -> str:
    """取最近 _FEED_LIMIT 条评论、按时间升序拼接；单条截断防膨胀。

    置于 `db.session.no_autoflush` 内：即便调用方 session 有挂起写，此查询也不触发
    autoflush，从根上杜绝「LLM 调用前因查询 autoflush 而取 SQLite 写锁」（§3.8 P1-1 / C1）。
    """
    with db.session.no_autoflush:
        rows = Comment.query.filter_by(entity_type=entity, entity_id=ticket_id)\
            .order_by(Comment.created_at.desc(), Comment.id.desc())\
            .limit(_FEED_LIMIT).all()
    snippets = []
    for c in reversed(rows):
        body = (c.body or "").strip().replace("\n", " ")
        if len(body) > _SNIPPET_MAX:
            body = body[:_SNIPPET_MAX] + "…"
        snippets.append(f"- [{c.author_type}] {body}")
    return "\n".join(snippets)
