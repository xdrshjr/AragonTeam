"""P-T1 workflow 纯单元（Phase-2 §6.1）。

迁移合法性只由邻接表裁决——全矩阵、next_states 有序、终态仅回退。
本套件不触库，是最快的回归护栏。
"""
from services import workflow


def test_requirement_transitions_matrix():
    # 合法前进边。
    assert workflow.can_transition("requirement", "new", "assigned")
    assert workflow.can_transition("requirement", "assigned", "in_development")
    assert workflow.can_transition("requirement", "in_development", "testing")
    assert workflow.can_transition("requirement", "testing", "reviewing")
    assert workflow.can_transition("requirement", "reviewing", "done")
    assert workflow.can_transition("requirement", "testing", "bug_fixing")
    assert workflow.can_transition("requirement", "bug_fixing", "testing")
    # 非法跨越。
    assert not workflow.can_transition("requirement", "new", "done")
    assert not workflow.can_transition("requirement", "new", "in_development")
    assert not workflow.can_transition("requirement", "assigned", "testing")


def test_bug_transitions_matrix():
    assert workflow.can_transition("bug", "open", "assigned")
    assert workflow.can_transition("bug", "assigned", "fixing")
    assert workflow.can_transition("bug", "fixing", "verifying")
    assert workflow.can_transition("bug", "verifying", "closed")
    assert not workflow.can_transition("bug", "open", "closed")
    assert not workflow.can_transition("bug", "open", "fixing")


def test_next_states_sorted():
    ns = workflow.next_states("requirement", "testing")
    assert ns == sorted(ns)
    assert set(ns) == {"reviewing", "bug_fixing", "in_development"}


def test_terminal_only_allows_rollback():
    # done / closed 为准终态：不再前进，仅允许回退纠错。
    assert workflow.is_terminal("requirement", "done")
    assert workflow.is_terminal("bug", "closed")
    assert workflow.next_states("requirement", "done") == ["reviewing"]
    assert workflow.next_states("bug", "closed") == ["verifying"]
    assert not workflow.can_transition("requirement", "done", "assigned")


def test_invalid_status_and_entity():
    assert not workflow.is_valid_status("requirement", "nope")
    assert workflow.is_valid_status("requirement", "new")
    assert workflow.column_keys("bug") == ["open", "assigned", "fixing", "verifying", "closed"]


def test_terminal_statuses_is_single_source(app):
    """【version-plan-hierarchy §3.4】进度计数复用的终态单一真相。"""
    from services import workflow as wf
    assert wf.terminal_statuses("requirement") == {"done"}
    assert wf.terminal_statuses("bug") == {"closed"}
    assert wf.terminal_statuses("nope") == set()
    # 返回副本：调用方误改污染不到内部 _TERMINAL。
    borrowed = wf.terminal_statuses("requirement")
    borrowed.add("assigned")
    assert wf.terminal_statuses("requirement") == {"done"}
