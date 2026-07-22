"""状态机服务（§2.3 Workflow State Machine）。

【R-02｜迁移合法性的唯一事实来源】迁移是否合法**只由下面两张邻接表判定**，
不存在第二套「相邻 + 回退」启发式。看板拖拽 / convert 一律经 can_transition
查表裁决：命中 → 合法；未命中 → 非法（路由返回 409 + allowed 列表）。

两张表的「允许迁移到」集合逐字等于 spec §2.3 的表格，含终态回退目标：
requirement: done -> {reviewing}；bug: closed -> {verifying}。
"""

# —— 需求状态机（看板列，从左到右）——
REQUIREMENT_TRANSITIONS: dict[str, set[str]] = {
    "new":            {"assigned"},
    "assigned":       {"in_development", "new"},
    "in_development": {"testing", "assigned"},
    "testing":        {"reviewing", "bug_fixing", "in_development"},
    "reviewing":      {"done", "bug_fixing", "testing"},
    "bug_fixing":     {"testing", "in_development"},
    "done":           {"reviewing"},  # 准终态：仅允许回退到 reviewing 纠错
}

# 需求列的展示顺序与中文名（前端看板列定义的后端权威副本）。
REQUIREMENT_COLUMNS: list[tuple[str, str]] = [
    ("new", "新建"),
    ("assigned", "已指派"),
    ("in_development", "开发中"),
    ("testing", "测试中"),
    ("reviewing", "审批中"),
    ("bug_fixing", "修复中"),
    ("done", "已完成"),
]

# —— BUG 状态机（看板列）——
BUG_TRANSITIONS: dict[str, set[str]] = {
    "open":      {"assigned"},
    "assigned":  {"fixing", "open"},
    "fixing":    {"verifying", "assigned"},
    "verifying": {"closed", "fixing"},
    "closed":    {"verifying"},  # 准终态：仅允许回退到 verifying 纠错
}

BUG_COLUMNS: list[tuple[str, str]] = [
    ("open", "新建"),
    ("assigned", "已指派"),
    ("fixing", "修复中"),
    ("verifying", "验证中"),
    ("closed", "已关闭"),
]

# 终态集合：不再向前流出，仅保留纠错回退。
_TERMINAL = {
    "requirement": {"done"},
    "bug": {"closed"},
}

_TABLES = {
    "requirement": REQUIREMENT_TRANSITIONS,
    "bug": BUG_TRANSITIONS,
}

_COLUMNS = {
    "requirement": REQUIREMENT_COLUMNS,
    "bug": BUG_COLUMNS,
}


def _table(entity: str) -> dict[str, set[str]]:
    table = _TABLES.get(entity)
    if table is None:
        raise ValueError(f"unknown entity type: {entity!r}")
    return table


def is_valid_status(entity: str, status: str) -> bool:
    return status in _table(entity)


def can_transition(entity: str, frm: str, to: str) -> bool:
    """当且仅当 to ∈ 邻接表[frm] 时返回 True（唯一裁决规则）。"""
    table = _table(entity)
    if frm not in table or to not in table:
        return False
    return to in table[frm]


def next_states(entity: str, frm: str) -> list[str]:
    """供前端渲染「下一步」按钮：返回 frm 的合法后继（有序）。"""
    table = _table(entity)
    return sorted(table.get(frm, set()))


def is_terminal(entity: str, status: str) -> bool:
    return status in _TERMINAL.get(entity, set())


def terminal_statuses(entity: str) -> set:
    """该实体的终态集合（只读副本）。

    【version-plan-hierarchy §3.4】计划 / 版本的进度计数用 `status.in_(terminal_statuses(...))`
    统计「已完成」工单，须复用**这一份**终态清单而非内联第二份——后者会随邻接表漂移
    （同 lifecycle.agent_open_workload 复用 is_terminal 的理由）。返回 `set` 的拷贝，
    调用方误改也污染不到 `_TERMINAL`。

    Args:
        entity: "requirement" | "bug"。

    Returns:
        终态字符串集合（requirement→{"done"}、bug→{"closed"}）；未知实体返回空集。
    """
    return set(_TERMINAL.get(entity, set()))


def columns(entity: str) -> list[tuple[str, str]]:
    """返回 [(key, 中文列名), ...] 有序列表，供看板分组。"""
    cols = _COLUMNS.get(entity)
    if cols is None:
        raise ValueError(f"unknown entity type: {entity!r}")
    return cols


def column_keys(entity: str) -> list[str]:
    return [k for k, _ in columns(entity)]
