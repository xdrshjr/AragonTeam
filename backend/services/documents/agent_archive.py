"""Agent 交付物归档（document-lifecycle-depth §2.3 C-2）。

系统里唯一全自动的那个环节，此前恰恰是唯一没有文档能力的环节：Agent 能写出一份完整的
测试报告，却只能把它埋进评论流——不能下载、不能改版、不能复用，也永远无法满足阶段清单。
本模块把「真实 LLM 产物」按目标阶段归档成对应类别的文档并绑定到工单。

━━━ 两条必须一起读的模块级约束 ━━━

**① 落盘在 SQLite 写锁窗口之外（评审 V-03）。** `service.py` 的模块 docstring 写着一条
贯穿全模块的硬约束：落盘（慢，无锁）在 `db.session` 的任何写入**之前**完成，事务内只做
元数据写入。因此归档拆成两段：`archive_prepare()` 在 `ticket.status` 改写**之前**完成
判定与落盘（此刻 session 无挂起写、不持有写锁），`archive_commit()` 在原位置只写元数据。
把两段合回一段，就是上一轮 R-7 那个坑的原样重演——SQLite 是单写者。

**② `begin_nested()` 在 pysqlite 上有一个未写下来就会消失的前置条件（评审 V-04）。**
SQLAlchemy 的 pysqlite 方言文档明确列出 SAVEPOINT **不能开箱工作**（pysqlite 的隐式
BEGIN 处理），需要 `isolation_level=None` + 手工 `BEGIN` 事件那套 workaround；本仓库
`extensions.py` **没有**做这个 workaround（只挂了 PRAGMA 监听）。它在本场景下能工作，
**唯一原因**是 `archive_commit` 的调用点之前已经有挂起 DML（`ticket.status` / `Comment` /
`Activity`），`begin_nested()` 的 flush 会先发出它们，事务因此已经打开，SAVEPOINT 落在
事务内。**任何把 `archive_commit` 挪到「session 尚无挂起写」位置的改动**，都会让
SAVEPOINT 在事务外发出、回滚不再隔离任何东西——而只断言「推进成功」的用例仍会绿。
若将来确实需要在无挂起写时 `begin_nested`，必须先给 `extensions.py` 补上 pysqlite
workaround，那是一次独立的、需要单独回归的改动。
"""
import logging
from typing import NamedTuple, Optional

from flask import current_app

from extensions import db
from models.document import Document
from models.document_link import DocumentLink
from services.documents import service
from services.documents import templates
from services.documents import trash

log = logging.getLogger("aragon.documents.agent_archive")

# (entity, agent_kind, to_status) → 该步骤的产物应归为哪一类文档。
#
# 【铁律 · 键必须含 agent_kind（评审 V-01）】**一个 Agent 只能产出自己职能范围内的
# 交付物**。少了 agent_kind 这一维，键就退化成「谁走到这一步都算数」，于是：
#   - ("requirement", "testing") 唯一由 **dev**-agent 到达（in_development→testing 与
#     bug_fixing→testing 两条边，见 agent_runner.AGENT_FORWARD），
#   - ("bug", "verifying")       唯一由 **dev**-agent 到达（fixing→verifying），
# 而这两个阶段的清单期望项分别是「测试计划」与「测试报告」——dev-agent 的一段
# 「我已提交修复」正文会被归档成 QA 的交付物，并把 QA 的清单项**点绿**。那是「制造材料
# 齐了的假象」，只是换成了真实 LLM 产物；而本轮的意义正是让 DOC_STAGE_GATE **有资格被
# 打开**——门禁一旦打开，它会放行一份没有任何 QA 参与过的「测试报告」。
# 这条错误比不归档坏得多，因为它**看起来**是合规的。
#
# 键的两条选择标准（缺一不可）：
#   1. 该类别恰好是**目标阶段**的清单期望项（doc_policy.STAGE_DOC_EXPECTATIONS）；
#   2. 该类别确实属于**这个 kind 的 Agent 的职能**。
# 两条由 test_agent_archive.py 的 C7（正向）与 C11（反向）双向守卫。
ARCHIVE_KIND: dict = {
    # dev-agent：产出的是实现侧材料。
    ("requirement", "dev", "in_development"): "design",        # 期望 (requirement_spec, design)
    ("bug",         "dev", "fixing"):         "bug_evidence",  # 期望 (bug_evidence,)
    # qa-agent：产出的是验证侧材料。
    ("requirement", "qa",  "reviewing"):      "test_report",   # 期望 (test_report,)
    ("bug",         "qa",  "closed"):         "test_report",   # 期望 (test_report,)
    # generic-agent：**故意不配**。它的两条边（requirement/assigned→in_development、
    # bug/assigned→fixing）产出的是泛化认领说明，归成任何一类都是硬套。
}

# 【被刻意删掉的两格，以及为什么删掉比配错好——不要好心把它们补回来】
#
#   ("requirement", "testing") → test_plan   ：唯一到达者是 **dev**-agent。测试计划是 QA
#       在进入测试**之前**写的；dev-agent 交完代码时写不出它。这一格**应当**红着，
#       直到 QA 或人补上。
#   ("bug", "verifying") → test_report       ：唯一到达者同样是 **dev**-agent，且更危险：
#       `verifying` 的整个语义就是「等着被别人验」，让提交修复的人自己出具验收报告，
#       等于取消这个状态。
#
# 同理，("requirement", "dev", "in_development") 归 design 而**不**补 requirement_spec——
# 需求说明书是人的输入，让 Agent 代写它是本末倒置；那一格清单应当保持红色直到有人上传。

# `DocumentLink.label` 的保留前缀：归档复用它来识别「这份文档是我上一轮产出的」，
# 从而追加版本而不是每次 tick 新建一份。人工绑定禁用该前缀（前后端各一道 400 校验）。
LABEL_PREFIX = "agent:"


class ArchivePlan(NamedTuple):
    """`archive_prepare` 的产物：已落盘的 blob + 元数据写入所需的全部决策。

    `existing_link` 非空表示「同一张单、同一个 agent kind 已经归过档」→ 追加版本；
    为空则新建文档 + 绑定。`target_stage` 由调用方显式传入的目标状态携带，
    **不读 `ticket.status`**——调用发生在状态改写之前，读它会记下旧阶段。
    """

    kind: str
    text: str
    blob: object
    existing_link: Optional[object]
    target_stage: str


def label_for(agent_kind: str) -> str:
    return f"{LABEL_PREFIX}{agent_kind}"


def archive_prepare(entity, ticket, agent, to_status, product) -> Optional[ArchivePlan]:
    """四条前置条件判定 + **落盘**。此刻 session 必须无挂起写（调用点保证）。

    四条前置条件（全部满足才归档，缺一即静默跳过，不写日志噪音）：

    1. `product.from_llm` 为真——**降级模板绝不归档**。一句「dev-agent 已认领需求」存成
       文档，只会往文档库里灌垃圾，还会把阶段清单点绿，制造「材料齐了」的假象。
       这条同时是**存量用例零影响的机制性保证**：`_llm_active()` 在 TESTING 下恒 False。
    2. `DOC_AGENT_ARCHIVE` 为真（默认 True，运维注记见 config.py）。
    3. `(entity, agent.kind, to_status) ∈ ARCHIVE_KIND`。
    4. 产物长度 ≥ `DOC_AGENT_ARCHIVE_MIN_CHARS`——两句话的产出不值得成为一份「交付物」。

    Returns:
        `ArchivePlan`；任一条件不满足、或落盘失败时 None。

    **失败绝不阻断 Agent 推进**：与 `archive_commit` 同一取向。本函数不碰 `db.session`
    的写路径，只做只读查询与磁盘 IO；落盘失败留下的至多是一个孤儿 blob，
    `tools/gc_orphan_blobs.py` 本就为此存在——在两种失败模式之间永远选可修复的那个。
    兜底写在这里而不是调用点，是为了让「归档失败不阻断推进」这条不变量不依赖于
    每一个未来的接线者都记得包一层 try。
    """
    try:
        return _plan(entity, ticket, agent, to_status, product)
    except Exception as exc:                # noqa: BLE001 —— 见上：附属动作绝不阻断主流程
        log.warning("agent_archive: failed to prepare archive for %s#%s (%s)",
                    entity, getattr(ticket, "id", None), exc)
        return None


def _plan(entity, ticket, agent, to_status, product) -> Optional[ArchivePlan]:
    """四条前置条件 + 落盘的纯逻辑（异常由 `archive_prepare` 收口）。"""
    if product is None or not getattr(product, "from_llm", False):
        return None
    if not current_app.config.get("DOC_AGENT_ARCHIVE", False):
        return None
    kind = ARCHIVE_KIND.get((entity, agent.kind, to_status))
    if kind is None:
        return None
    text = (product.text or "").strip()
    minimum = int(current_app.config.get("DOC_AGENT_ARCHIVE_MIN_CHARS", 200))
    if len(text) < minimum:
        return None

    # 只读查询：这张单上是否已有本 kind 的 Agent 产物。
    # **必须过滤软删**（§2.4 过滤点清单的同一课）：一份被移进回收站的旧产物若仍被认成
    # 「已有」，归档就会往回收站里的文档上追加版本——用户看不见它，清单也不会变绿。
    existing_link = (db.session.query(DocumentLink)
                     .join(Document, Document.id == DocumentLink.document_id)
                     .filter(DocumentLink.entity_type == entity,
                             DocumentLink.entity_id == ticket.id,
                             DocumentLink.label == label_for(agent.kind))
                     .filter(trash.not_deleted())
                     .order_by(DocumentLink.id.asc())
                     .first())
    _, blob = service.persist_text(text)     # ← 全部磁盘 IO 发生在这里，写锁窗口之外
    return ArchivePlan(kind=kind, text=text, blob=blob,
                       existing_link=existing_link, target_stage=to_status)


def archive_commit(plan: Optional[ArchivePlan], entity, ticket, agent) -> None:
    """把 plan 落成元数据行（**不 commit**）。全程无磁盘 IO，写锁窗口收敛到亚毫秒。

    在**独立的 SAVEPOINT** 中执行：失败时只回滚该嵌套事务，主推进事务不受影响。
    SAVEPOINT 的前置条件见模块 docstring ②——调用点之前必须已有挂起写。

    失败只 `log.warning`，**绝不阻断 Agent 推进**：取向与 `agent_executor` 对 LLM 的兜底
    完全一致——自动流水线不能因为一个附属动作失败而停摆。用户看到的是「推进成功、只是
    这一步没有产出文档」，而不是一个 500。
    """
    if plan is None:
        return
    # 【显式 flush，且**在 try 之外**】`begin_nested()` 本来就会先 flush 挂起写再发出
    # SAVEPOINT——那正是模块 docstring ② 依赖的前置条件。但若那次 flush 失败的是**主推进
    # 事务自己的写**（`ticket.status` / `Comment` / `Activity`），异常会在 SAVEPOINT 之外
    # 抛出、落进下面的兜底，被记成一条「归档失败」的 warning 然后**静默返回**——
    # 调用方随后 commit 时才炸出 `PendingRollbackError`，用户拿到一个 500，而唯一的日志
    # 线索指向一个跟它毫无关系的子系统。把 flush 提到 try 之外，两类失败就分得开：
    # 主事务的失败原样冒泡（带真实堆栈），归档自己的失败才走兜底。
    db.session.flush()
    try:
        with db.session.begin_nested():
            _write(plan, entity, ticket, agent)
    except Exception as exc:                # noqa: BLE001 —— 兜底：附属动作绝不阻断主流程
        log.warning("agent_archive: failed to archive %s#%s for agent %s (%s)",
                    entity, ticket.id, getattr(agent, "id", None), exc)


def _write(plan: ArchivePlan, entity, ticket, agent) -> None:
    """元数据写入的两条分支。`notify=False` 见 §2.3 C-2 · 评审 V-10。"""
    actor = ("agent", agent.id)
    stage_label = service.stage_label(entity, plan.target_stage)
    if plan.existing_link is not None:
        document = db.session.get(Document, plan.existing_link.document_id)
        if document is None:                # 防御性：link 是孤儿 → 当作没归过档
            log.warning("agent_archive: dangling link %s", plan.existing_link.id)
            return
        version, _ = service.add_version_from_text(
            document, content=plan.text,
            note=f"{agent.name} 在「{stage_label}」阶段更新", uploader=None,
            blob=plan.blob)                 # 复用已落盘的 blob：此处一个字节都不写
        service.fanout_revision(document, version, actor, notify=False)
        return

    document, _version, _blob = service.create_text_document(
        title=_title_for(plan.kind, entity, ticket, stage_label),
        kind=plan.kind, content=plan.text,
        project_id=ticket.project_id, uploader=None,
        filename_stem=templates.filename_stem(plan.kind, entity, ticket.id),
        blob=plan.blob,                     # 复用已落盘的 blob：此处一个字节都不写
    )
    service.bind_document(document, entity=entity, ticket=ticket,
                          label=label_for(agent.kind), actor=actor, uploaded=True,
                          stage=plan.target_stage, notify=False)


def _title_for(kind: str, entity: str, ticket, stage_label: str) -> str:
    code = templates.ticket_code(entity, ticket.id)
    label = service.kind_label(kind)
    return f"{code} {label}（{stage_label}）"[:200]
