"""Agent 协作运行时（Phase-2 §2.2 支柱 A · 核心）。

让「Agent 参与协作」从静态字段变成可交互、可追溯、可测试的真实机制：
一张被指派给 Agent 的工单，可被推进一步——每一步都

  1) 严格走 workflow 邻接表（**绝不绕过状态机**，是本产品可信度的地基）；
  2) 以 Agent 身份留一条工作说明评论；
  3) 写一条 actor_type=agent 的审计记录。

**确定性离线模拟**：不依赖外部 LLM（可单测、无网络抖动），未来接真实 Agent
只需替换本模块 `advance_one` 内部的动作生成，接口 / 数据模型 / 前端均不变。

【R-04】单步推进为同步单事务，Agent 已提交终态恒为 idle；`busy` 只在
`run=all`（逐步 commit）下才产生可观测窗口，故本模块不在单步内切 busy。
"""
from extensions import db
from models.comment import Comment
from models.activity import Activity
from services import workflow

# run=all 连续推进的硬上限，防死循环（§7 风险表）。
MAX_AGENT_STEPS = 6

# 「Agent 前进路径」映射：(entity, agent.kind, current_status) → (目标态, 工作说明模板)。
# 语义：该 kind 的 Agent 在此状态下会把工单推进到哪一步。
# 每条目标边**均为 workflow 邻接表内的合法前进边**（advance_one 仍会防御性复核）。
AGENT_FORWARD: dict[tuple[str, str, str], tuple[str, str]] = {
    # —— 需求（requirement）——
    ("requirement", "dev", "assigned"):
        ("in_development", "dev-agent 已认领需求，拆解任务、拉起开发分支。"),
    ("requirement", "dev", "in_development"):
        ("testing", "dev-agent 完成实现与自测，提交变更，转入测试。"),
    ("requirement", "dev", "bug_fixing"):
        ("testing", "dev-agent 已定位并修复缺陷，回归自测通过，转回测试。"),
    ("requirement", "qa", "testing"):
        ("reviewing", "qa-agent 执行测试用例通过，转入审批。"),
    ("requirement", "generic", "assigned"):
        ("in_development", "agent 已认领需求并开始处理。"),
    # —— BUG（bug）——
    ("bug", "dev", "assigned"):
        ("fixing", "dev-agent 已认领缺陷，开始定位根因。"),
    ("bug", "dev", "fixing"):
        ("verifying", "dev-agent 提交修复，转入验证。"),
    ("bug", "qa", "verifying"):
        ("closed", "qa-agent 验证修复通过，关闭缺陷。"),
    ("bug", "generic", "assigned"):
        ("fixing", "agent 已认领缺陷并开始处理。"),
}


class NoAgentAction(Exception):
    """该 kind 在该状态下无预置动作（越界请求）——路由据此返回 409，不改库。"""

    def __init__(self, kind: str, status: str):
        super().__init__(f"agent kind={kind} has no action for status={status}")
        self.kind = kind
        self.status = status


def plan(entity: str, kind: str, status: str):
    """查前进表；未命中返回 None。"""
    return AGENT_FORWARD.get((entity, kind, status))


def _next_position(model, status: str) -> int:
    """目标列下一个 position（该列现有最大值 + 1；空列为 0）。

    与 routes.requirements._next_position 同语义；此处内联以避免 service→routes 依赖。
    """
    rows = model.query.filter_by(status=status).all()
    return max((r.position for r in rows), default=-1) + 1


def advance_one(entity: str, ticket, agent):
    """推进工单一步（**不 commit**，由调用方事务统一提交）。

    返回 (to_status, comment, activity)。
    - 未命中前进表 → 抛 NoAgentAction（推进前抛出，session 未被改动）。
    - 表配置出非法边（理论不应发生）→ 抛 RuntimeError（路由记日志并 500）。
    """
    planned = plan(entity, agent.kind, ticket.status)
    if planned is None:
        raise NoAgentAction(agent.kind, ticket.status)
    to, message = planned

    # 防御性复核：目标必须 ∈ 邻接表允许集，绝不绕过状态机。
    if not workflow.can_transition(entity, ticket.status, to):
        raise RuntimeError(
            f"AGENT_FORWARD 配置了非法前进边：{entity} {ticket.status} -> {to}"
        )

    frm = ticket.status
    ticket.status = to
    ticket.position = _next_position(type(ticket), to)

    comment = Comment(
        entity_type=entity, entity_id=ticket.id,
        author_type="agent", author_id=agent.id, body=message,
    )
    db.session.add(comment)

    activity = Activity.log(
        entity, ticket.id, "agent_advanced", actor=("agent", agent.id),
        from_status=frm, to_status=to, message=message,
    )
    return to, comment, activity
