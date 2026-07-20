"""Agent 协作运行时（Phase-2 §2.2 支柱 A · 核心）。

让「Agent 参与协作」从静态字段变成可交互、可追溯、可测试的真实机制：
一张被指派给 Agent 的工单，可被推进一步——每一步都

  1) 严格走 workflow 邻接表（**绝不绕过状态机**，是本产品可信度的地基）；
  2) 以 Agent 身份留一条工作说明评论；
  3) 写一条 actor_type=agent 的审计记录。

**确定性回退 + 可选真实 LLM**（real-agent-execution）：评论正文由
`agent_executor.generate_work` 提供——配置了模型凭据时调用真实 LLM 产出实质工作产物；
未配置 / 测试 / 调用失败一律优雅降级到下方 `AGENT_FORWARD` 的确定性模板文案。
**状态迁移目标仍完全由 `AGENT_FORWARD` + `workflow` 裁决，LLM 只产内容、绝不决定流转**；
接口 / 数据模型 / 前端 / 审计短句均不变。

【R-04】单步推进为同步单事务，Agent 已提交终态恒为 idle；`busy` 只在
`run=all`（逐步 commit）下才产生可观测窗口，故本模块不在单步内切 busy。

【document-lifecycle-depth §2.3 C-2】`advance_one` 里的**两处**归档接线是有顺序约束的：
`archive_prepare` 必须在 `ticket.status` 改写**之前**（落盘在 SQLite 写锁窗口之外），
`archive_commit` 必须在 `Activity.log` **之后**（pysqlite 的 SAVEPOINT 需要事务已打开）。
两者都是「错了不会报错、只会安静地错」的位置，理由逐条写在
`services/documents/agent_archive.py` 的模块 docstring 里，改动前请先读它。
"""
from extensions import db
from models.comment import Comment
from models.activity import Activity
from services import workflow, agent_executor, doc_policy, positions
from services.documents import agent_archive

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


def _next_position(model, status: str, project_id) -> int:
    """列内下一个 position。唯一实现在 `services/positions.py`（bulk-operations §2.2）。

    此前这里内联着一份与 `routes.requirements._next_position` 逐字相同的实现，并注明
    「两处必须同步修改」——批量流转是第三个调用点，与其抄第三遍，不如把它提到叶子模块。
    保留同名薄转发只为不惊动既有调用点与测试。
    """
    return positions.next_position(model, status, project_id)


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

    # 【P1-1 / 放行条件 C1】先产出正文：generate_work_product 只读 feed + 可选 LLM。此刻
    # session 无挂起写，feed 查询不会 autoflush 出任何 UPDATE，故 LLM 全程不持有 SQLite
    # 写锁；LLM 未启用 / 失败 / 空返回一律降级回 message（模板），恒返回非空正文。
    product = agent_executor.generate_work_product(
        entity, ticket, agent, to, fallback_message=message)
    body = product.text

    # 【document-lifecycle-depth §2.3 C-2 · 评审 V-03】归档是**两段式**，两处接线的
    # 位置本身就是约束：
    #   ① archive_prepare 在 ticket.status 改写**之前**——此刻 session 无挂起写、不持有
    #      SQLite 写锁，全部磁盘 IO（落盘）发生在这里。挪到下面去，就是把磁盘 IO 塞进
    #      写锁窗口，上一轮 R-7 那个坑的原样重演。
    #   ② archive_commit 在 Activity.log **之后**——它用 SAVEPOINT 隔离失败，而
    #      pysqlite 的 SAVEPOINT 依赖「调用点之前已有挂起写」这个前置条件才真实生效
    #      （见 services/documents/agent_archive.py 模块 docstring ②）。
    # 目标阶段显式传 `to`，**不**读 ticket.status——此刻它还是旧状态。
    # 变量名**不能**叫 `plan`：模块级已有一个同名函数（本函数第一行就在调它），
    # 局部赋值会把它变成局部名并让那次调用抛 UnboundLocalError。
    archive_plan = agent_archive.archive_prepare(entity, ticket, agent, to, product)

    # 【ticket-document-management §2.4 铁律 2】Agent 路径**永不被文档门禁挡住**——
    # 它是后台循环，被挡住会表现为「自动流水线莫名其妙不动了」，而没有任何一个人会
    # 收到那个 409。改为把材料缺口留在时间线上给人看。本调用是该提示的**唯一落点**
    # （现网唯一一处为 Agent 改写 ticket.status 的代码），且自带「仅门禁开启时写」
    # 与「同一 (工单, 目标状态) 只写一次」两条限定——tick / autorun-all 是循环调用，
    # 不去重就会每一轮写一条，几分钟内淹没时间线。
    doc_policy.agent_missing_hint(entity, ticket, to)

    # 产出完成后再改状态、建评论——写事务窗口收敛到 commit 前的亚毫秒区间。
    ticket.status = to
    ticket.position = _next_position(type(ticket), to, ticket.project_id)

    comment = Comment(
        entity_type=entity, entity_id=ticket.id,
        author_type="agent", author_id=agent.id, body=body,
    )
    db.session.add(comment)

    # 审计仍记简短动作短句（保持时间线可断言、审计干净），丰富内容进入评论正文。
    activity = Activity.log(
        entity, ticket.id, "agent_advanced", actor=("agent", agent.id),
        from_status=frm, to_status=to, message=message,
    )

    # ② 元数据写入：无磁盘 IO；SAVEPOINT 的前置条件（已有挂起写）由上面四行保证。
    agent_archive.archive_commit(archive_plan, entity, ticket, agent)
    return to, comment, activity
