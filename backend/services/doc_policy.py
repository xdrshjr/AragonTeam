"""阶段文档策略（ticket-document-management §2.4）——建议性清单 + 可选门禁。

**状态机是神圣的。** 本模块不给 `services/workflow.py` 增加任何一行：门禁是在
`can_transition` 判定为合法**之后、写入之前**的一次独立前置检查，它只会让一次合法
迁移被拒绝，永远不会让一次非法迁移被放行。状态机仍是唯一的迁移仲裁者。
"""
import logging

from flask import current_app, jsonify

from models.document import DOCUMENT_KIND_LABELS
from services import workflow
from services.documents import service as document_service

log = logging.getLogger("aragon.doc_policy")

# 每个（实体, 状态）「通常应该有哪几类文档」。
#
# 【评审 R2】键必须覆盖 workflow 的全部状态。现网需求是 **7 态**（含 bug_fixing），
# 不是 6 态；本表按 services/workflow.py 逐字对齐——落一个状态，前端该列的阶段清单
# 就会渲染成空白。`test_checklist_covers_every_workflow_status` 守卫这一点。
STAGE_DOC_EXPECTATIONS: dict = {
    ("requirement", "new"):            (),                       # 刚建单，不期望材料
    ("requirement", "assigned"):       ("requirement_spec",),
    ("requirement", "in_development"): ("requirement_spec", "design"),
    ("requirement", "testing"):        ("test_plan",),
    ("requirement", "bug_fixing"):     ("bug_evidence",),
    ("requirement", "reviewing"):      ("test_report",),
    ("requirement", "done"):           ("test_report",),
    ("bug", "open"):                   (),
    ("bug", "assigned"):               ("bug_evidence",),
    ("bug", "fixing"):                 ("bug_evidence",),
    ("bug", "verifying"):              ("test_report",),
    ("bug", "closed"):                 ("test_report",),
}

# 【实施发现 F1，见 spec「实施过程发现的方案缺陷」】**流程推进顺序**，与看板列的
# **展示顺序**有意分离。
#
# spec §2.4 铁律 4 原本要求「用 `column_keys()` 的顺序判定前进」，但现网
# `REQUIREMENT_COLUMNS` 把 `bug_fixing` 排在 `reviewing` **之后**（展示上它靠近尾部），
# 于是 `reviewing → bug_fixing` 按列序会被判成「前进」并被门禁拦下——而 spec 自己的
# 用例 `test_gate_never_blocks_backward_move` 恰恰要求这一条必须放行。二者不可兼得。
#
# 语义上正确的答案是：`bug_fixing` 是**返工态**，与 `in_development` 同档。因此这里
# 显式声明推进档位，`forward = order[to] > order[frm]`。改看板列的展示顺序不会再
# 意外改变门禁行为——那正是把两件事分开的理由。
_STAGE_ORDER: dict = {
    "requirement": {
        "new": 0, "assigned": 1, "in_development": 2, "bug_fixing": 2,
        "testing": 3, "reviewing": 4, "done": 5,
    },
    "bug": {"open": 0, "assigned": 1, "fixing": 2, "verifying": 3, "closed": 4},
}


def assert_thresholds(config) -> None:
    """启动期断言：预览上限**必须严格大于**编辑上限（§2.6 / 评审 R5）。

    否则「大小 ≤ 编辑阈值」的文件仍可能被预览截断，用户改一个字保存，**截断即成为
    新版本的全部内容**，原文尾部永久消失。配置改错了应当立刻起不来，而不是等着某天
    有人发现自己的文档被吃掉了半截。

    Raises:
        ValueError: 两个阈值的大小关系不成立。
    """
    preview = int(config.get("DOC_TEXT_PREVIEW_MAX_BYTES", 0))
    edit = int(config.get("DOC_TEXT_EDIT_MAX_BYTES", 0))
    if preview <= edit:
        raise ValueError(
            "DOC_TEXT_PREVIEW_MAX_BYTES must be strictly greater than "
            f"DOC_TEXT_EDIT_MAX_BYTES (got {preview} <= {edit}); otherwise an "
            "editable-sized file can be silently truncated and saved back"
        )


def assert_text_document_extension(config) -> None:
    """启动期断言：`md` **必须**在扩展名白名单内（document-lifecycle-depth §2.3 C-1）。

    模板新建与 Agent 归档都从零造文件身份，扩展名恒为 `md`
    （`service.create_text_document` 的不变量 1）。运维把 md 从白名单里摘掉却留着这两条
    路径，应当**起不来**，而不是在用户点「用模板新建」时抛一个语义不明的 500。

    与 `assert_thresholds` **并列注册**而不是塞进它内部：两者校验的是彼此无关的两件事，
    合并会让「阈值断言」的既有调用方（含用例）被迫连带提供扩展名白名单。

    Raises:
        ValueError: `md` 不在 `DOC_ALLOWED_EXTENSIONS` 内。
    """
    allowed = tuple(config.get("DOC_ALLOWED_EXTENSIONS", ()))
    if "md" not in allowed:
        raise ValueError(
            "DOC_ALLOWED_EXTENSIONS must contain 'md': document templates and agent "
            f"archiving both create .md files from scratch (got {sorted(allowed)})"
        )


def expectations(entity: str, status: str) -> tuple:
    """该（实体, 状态）期望的文档类型元组；未登记的组合返回空元组（不阻断、不报错）。"""
    return STAGE_DOC_EXPECTATIONS.get((entity, status), ())


def is_enforced() -> bool:
    """门禁总开关的真实值。前端由 `StageChecklist.enforced` 得知，**绝不自己猜**。"""
    return bool(current_app.config.get("DOC_STAGE_GATE", False))


def checklist(entity: str, ticket) -> dict:
    """§4.2 的 `StageChecklist` 响应形状。"""
    status = ticket.status
    kinds = document_service.bound_kinds(entity, ticket.id)
    items = []
    for kind in expectations(entity, status):
        document_ids = sorted(kinds.get(kind, []))
        items.append({
            "kind": kind,
            "label": DOCUMENT_KIND_LABELS.get(kind, kind),
            "satisfied": bool(document_ids),
            "document_ids": document_ids,
        })
    return {
        "entity": entity,
        "entity_id": ticket.id,
        "stage": status,
        "stage_label": document_service.stage_label(entity, status),
        "enforced": is_enforced(),
        "satisfied": all(item["satisfied"] for item in items),
        "items": items,
    }


def missing_kinds(entity: str, ticket, to_status: str) -> list:
    """推进到 `to_status` 时仍缺失的文档类型（有序，去重）。"""
    kinds = document_service.bound_kinds(entity, ticket.id)
    return [k for k in expectations(entity, to_status) if not kinds.get(k)]


def is_forward(entity: str, frm: str, to: str) -> bool:
    """`to` 是否**严格靠后于** `frm`（推进档位，不是看板列序；见 `_STAGE_ORDER`）。"""
    order = _STAGE_ORDER.get(entity, {})
    if frm not in order or to not in order:
        return False
    return order[to] > order[frm]


def gate_transition(entity: str, ticket, to_status: str):
    """人类推进的阶段文档门禁。返回 409 响应元组，或 None（放行）。

    四条铁律（§2.4）：

    1. **只在 `DOC_STAGE_GATE` 为真时生效**；默认 `False`，因此默认行为与本轮之前
       逐字节相同，存量库、存量测试零影响。
    2. **只作用于人类主动推进**（`PATCH /move`）。Agent 路径一律豁免——Agent 是后台
       循环，被门禁挡住会表现为「自动流水线莫名其妙不动了」，而没有任何一个人会收到
       这个 409。（本函数只在两个 `move` 路由里被调用，这一条由调用点保证。）
    3. 409 **不带 `allowed` 键**——前端看板拖拽以 `err.allowed` 是否存在区分「状态机
       非法」与「其他冲突」，带上会被误分流。
    4. **只作用于「前进」迁移**。用户按下回退键的原因**恰恰是材料不合格**；若门禁在
       回退时也生效，就会出现「因为缺测试报告，所以你不能把这张误标为已完成的单退回去
       补测试报告」这种死结。
    """
    if not is_enforced():
        return None
    if not is_forward(entity, ticket.status, to_status):
        return None
    missing = missing_kinds(entity, ticket, to_status)
    if not missing:
        return None
    return jsonify({
        "error": "required documents are missing",
        "detail": {
            "stage": to_status,
            "stage_label": document_service.stage_label(entity, to_status),
            "missing": missing,
            "missing_labels": [DOCUMENT_KIND_LABELS.get(k, k) for k in missing],
            "hint": "attach the required documents first",
        },
    }), 409


def agent_missing_hint(entity: str, ticket, to_status: str) -> bool:
    """Agent 路径的建议性提示：把材料缺口留在时间线上给人看（**不 commit**）。

    Returns:
        True 表示本次确实写了一条 `doc_missing_hint`。

    【§2.4 铁律 2 · 评审 R10】三条限定，否则它自己会变成新的噪音源：

    - **仅当 `DOC_STAGE_GATE=true` 时才写**。开关关闭时阶段清单是纯建议性的，
      没有任何理由往每一张单的时间线里塞一条「你少了个文件」。
    - **同一 (工单, 目标状态) 只写一次**：现网 `tick` / `autorun-all` 是**循环调用**，
      不去重就会每一轮写一条，几分钟内淹没时间线。
    - **落点唯一**为 `services/agent_runner.py::advance_one`（现网唯一一处为 Agent
      改写 `ticket.status` 的代码）。
    """
    if not is_enforced():
        return False
    missing = missing_kinds(entity, ticket, to_status)
    if not missing:
        return False

    from models.activity import Activity

    # 去重键是 (工单, 目标状态)：`to_status` 是 Activity 的既有列，无需另造 detail 字段。
    already = (Activity.query
               .filter_by(entity_type=entity, entity_id=ticket.id,
                          action="doc_missing_hint", to_status=to_status)
               .first())
    if already is not None:
        return False
    labels = "、".join(DOCUMENT_KIND_LABELS.get(k, k) for k in missing)
    Activity.log(entity, ticket.id, "doc_missing_hint", actor=("system", None),
                 from_status=ticket.status, to_status=to_status,
                 message=f"推进到「{document_service.stage_label(entity, to_status)}」"
                         f"通常需要：{labels}")
    return True
