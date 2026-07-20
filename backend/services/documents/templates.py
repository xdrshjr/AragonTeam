"""文档模板（document-lifecycle-depth §2.3 C-1）——阶段清单缺失项的第二条出路。

**叶子模块**：只依赖 stdlib 与 `models.document` 的常量表，任何一层都可安全 import
（与 `mime.py` 同款位置，见上一轮 F2 的循环 import 教训）。

一条贯穿全模块的铁律：**模板正文不含任何「待填写」以外的断言**。一份自称「全部通过」
的空测试报告比没有报告更危险——它会把阶段清单点绿、把门禁放行，而没有任何人验证过
任何东西。因此占位符只用**已知事实**填充（工单编号、标题、阶段、创建人、日期），
其余一律是空的章节骨架。
"""
from models.document import DOCUMENT_KIND_LABELS

# 提供模板的五类。八个 kind 里 `bug_evidence`（复现材料本质是录屏 / 日志，模板无意义）、
# `reference`、`other` **有意不提供**——前端对这三类只显示「上传文件」。
TEMPLATE_KINDS = ("requirement_spec", "design", "test_plan", "test_report", "release_note")

# kind → 该类别的章节骨架（一级列表，逐条渲染为 `## 标题`）。
_SECTIONS = {
    "requirement_spec": (
        "背景与目标",
        "用户与场景",
        "功能需求",
        "非功能需求（性能 / 安全 / 兼容）",
        "验收标准",
        "范围外（明确不做）",
    ),
    "design": (
        "方案概述",
        "关键设计决策与取舍",
        "接口 / 数据结构变更",
        "影响面与兼容性",
        "风险与回滚方案",
        "实施拆分",
    ),
    "test_plan": (
        "测试范围",
        "测试环境与数据",
        "用例设计（正常路径）",
        "用例设计（异常与边界）",
        "退出标准",
        "风险与不测项",
    ),
    "test_report": (
        "测试范围",
        "用例执行结果",
        "缺陷汇总",
        "结论与风险",
        "附件",
    ),
    "release_note": (
        "本次变更",
        "升级步骤",
        "配置变更",
        "回滚方式",
        "已知问题",
    ),
}

# kind → 一句话说明，随 `GET /api/documents/meta` 下发给前端（中文标题不在前端另写一份）。
_SUMMARIES = {
    "requirement_spec": "写清楚要做什么、给谁用、做到什么程度算完成。",
    "design": "记录实现方案与关键取舍，让评审者不必重新推导一遍。",
    "test_plan": "进入测试之前先约定测什么、怎么测、什么条件算通过。",
    "test_report": "如实记录执行结果与残留风险，是验收与放行的依据。",
    "release_note": "面向使用方：改了什么、怎么升、出问题怎么退。",
}

# 实体 → 工单编号前缀（与前端展示的 `REQ-42` / `BUG-7` 一致）。
_ENTITY_PREFIX = {"requirement": "REQ", "bug": "BUG"}


def catalog() -> list:
    """全部模板的下发形状：`[{kind, label, summary}]`（§4.6）。"""
    return [
        {"kind": kind,
         "label": DOCUMENT_KIND_LABELS.get(kind, kind),
         "summary": _SUMMARIES.get(kind, "")}
        for kind in TEMPLATE_KINDS
    ]


def is_template_kind(kind: str) -> bool:
    return kind in TEMPLATE_KINDS


def ticket_code(entity: str, ticket_id: int) -> str:
    """工单编号，如 `REQ-42` / `BUG-7`；未知实体退化为 `实体-id`。"""
    return f"{_ENTITY_PREFIX.get(entity, entity)}-{ticket_id}"


def filename_stem(kind: str, entity: str, ticket_id: int) -> str:
    """落盘展示文件名的主干（扩展名由 `create_text_document` 恒定为 `md`）。"""
    return f"{kind}-{entity}-{ticket_id}"


def default_title(kind: str, ticket_title: str) -> str:
    """缺省标题 `{工单标题} · {类别中文名}`，按列宽 200 截断。"""
    label = DOCUMENT_KIND_LABELS.get(kind, kind)
    return f"{ticket_title or ''} · {label}"[:200]


def render(kind: str, *, entity: str, ticket, author_name: str,
           stage_label: str, today: str) -> str:
    """产出一份 Markdown 骨架正文。占位符只用已知事实填充，**绝不编造内容**。

    Args:
        kind: `TEMPLATE_KINDS` 之一（调用方已校验）。
        entity: "requirement" | "bug"。
        ticket: 工单对象，只读 `id` / `title`。
        author_name: 创建人展示名。
        stage_label: 创建时所处环节的中文名。
        today: 日期字符串（`YYYY-MM-DD`）。调用方传入而非本模块自取——叶子模块
            不该自己去摸时钟，那会让渲染结果不可测。

    Returns:
        完整的 Markdown 正文（以换行结尾）。

    Raises:
        KeyError: `kind` 不在 `TEMPLATE_KINDS` 内（属于编程错误，调用方须先校验）。
    """
    sections = _SECTIONS[kind]
    label = DOCUMENT_KIND_LABELS.get(kind, kind)
    code = ticket_code(entity, ticket.id)
    lines = [
        f"# {label}：{getattr(ticket, 'title', '') or code}",
        "",
        "| 项 | 值 |",
        "| --- | --- |",
        f"| 关联工单 | {code} |",
        f"| 工单标题 | {getattr(ticket, 'title', '') or '—'} |",
        f"| 创建阶段 | {stage_label or '—'} |",
        f"| 创建人 | {author_name or '—'} |",
        f"| 创建日期 | {today} |",
        "",
        "> 本文由模板生成，以下章节均**待填写**。删掉用不上的章节比留着空标题更好。",
        "",
    ]
    for section in sections:
        lines.append(f"## {section}")
        lines.append("")
        lines.append("待填写。")
        lines.append("")
    return "\n".join(lines)
