"""看板每列分页（lifecycle-and-governance §2.8 / §6.1）。

覆盖：每列上限生效、`total` 为真实总数、`truncated` 标志正确、`?column_limit` 钳制
与非法值 400、小库时 `truncated=false`，以及 `columns[].key/title/items` 的向后兼容。
"""
from services import board_page, workflow


def _columns(client, auth, query=""):
    r = client.get(f"/api/board/requirements{query}", headers=auth("pm"))
    assert r.status_code == 200, r.get_json()
    return {c["key"]: c for c in r.get_json()["columns"]}


def test_board_shape_is_backward_compatible(client, auth, make_requirement):
    make_requirement("一张单")

    r = client.get("/api/board/requirements", headers=auth("pm"))

    body = r.get_json()
    assert [c["key"] for c in body["columns"]] == workflow.column_keys("requirement")
    first = body["columns"][0]
    assert first["title"] == "新建"
    assert isinstance(first["items"], list)
    assert first["items"][0]["title"] == "一张单"


def test_small_board_reports_truncated_false(client, auth, make_requirement):
    make_requirement("小库")

    new_column = _columns(client, auth)["new"]

    assert new_column["truncated"] is False
    assert new_column["total"] == 1
    assert len(new_column["items"]) == 1


def test_column_is_capped_at_limit(client, auth, bulk_tickets):
    bulk_tickets(120)

    new_column = _columns(client, auth)["new"]

    assert len(new_column["items"]) == board_page.DEFAULT_COLUMN_LIMIT


def test_column_total_is_true_total(client, auth, bulk_tickets):
    bulk_tickets(120)

    new_column = _columns(client, auth)["new"]

    assert new_column["total"] == 120


def test_truncated_flag_is_accurate(client, auth, bulk_tickets):
    bulk_tickets(120)

    columns = _columns(client, auth)

    assert columns["new"]["truncated"] is True
    assert columns["assigned"]["truncated"] is False   # 空列不算被截断


def test_column_limit_query_param_is_honoured(client, auth, bulk_tickets):
    bulk_tickets(30)

    new_column = _columns(client, auth, "?column_limit=10")["new"]

    assert len(new_column["items"]) == 10
    assert new_column["total"] == 30
    assert new_column["truncated"] is True


def test_column_limit_query_param_is_clamped(client, auth, bulk_tickets):
    """上限型参数越界照钳不报错（与 ?limit= 既有语义一致）。"""
    bulk_tickets(5)

    new_column = _columns(client, auth, "?column_limit=99999")["new"]

    assert len(new_column["items"]) == 5


def test_invalid_column_limit_is_400(client, auth):
    r = client.get("/api/board/requirements?column_limit=abc", headers=auth("pm"))

    assert r.status_code == 400
    assert r.get_json()["detail"]["field"] == "column_limit"


def test_board_respects_project_scope(client, auth, data, bulk_tickets):
    bulk_tickets(3, project_id=data["project_id"])
    bulk_tickets(2)

    scoped = _columns(client, auth, f"?project_id={data['project_id']}")["new"]
    unassigned = _columns(client, auth, "?project_id=none")["new"]

    assert scoped["total"] == 3
    assert unassigned["total"] == 2


def test_bug_board_is_paginated_too(client, auth, make_bug):
    make_bug("缺陷一张")

    r = client.get("/api/board/bugs?column_limit=1", headers=auth("pm"))

    assert r.status_code == 200
    columns = {c["key"]: c for c in r.get_json()["columns"]}
    assert columns["open"]["total"] == 1
    assert columns["open"]["truncated"] is False
