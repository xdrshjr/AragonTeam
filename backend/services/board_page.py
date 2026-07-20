"""看板每列分页（lifecycle-and-governance §2.8）。

`GET /api/board/*` 此前没有任何上限：300 张单就返 300 张卡（82 KB），一个团队跑三个月
就是几千个可拖拽 DOM 节点。本模块把「每列取前 N + 该列真实总数」收敛为一个函数，
路由层只负责取参与渲染契约。

响应 shape **additive**：既有 `key` / `title` / `items` 一字不改，新增 `total` 与
`truncated`——UI 据此在列头诚实地写出「显示 100 / 共 342」，绝不在用户不知情时少给数据。
"""
from services import workflow
from services.documents.counts import link_counts
from services.scope import apply_project_filter, want_query_int

DEFAULT_COLUMN_LIMIT = 100
MAX_COLUMN_LIMIT = 500


def wanted_column_limit() -> int:
    """从 `?column_limit=` 取每列上限，钳制到 [1, MAX_COLUMN_LIMIT]。

    走 services/scope.py::want_query_int（clamp=True），与既有三点式查询串收口一致
    ——不新写第四份整型解析。非整数值仍恒 400（经全局 QueryParamError 处理器）。
    """
    return want_query_int("column_limit", default=DEFAULT_COLUMN_LIMIT,
                          minimum=1, maximum=MAX_COLUMN_LIMIT, clamp=True)


def column_page(model, entity: str, scope, column_limit: int) -> dict:
    """按 workflow 列分组，每列最多取 column_limit 张卡，并给出该列真实总数。

    以「每列一次带 LIMIT 的查询 + 一次 COUNT」实现（列数固定为 5~7，查询次数有界），
    而不是取回全表再切片——后者的内存与序列化成本正是本模块要消灭的问题。

    Args:
        model: Requirement / Bug 模型类。
        entity: "requirement" | "bug"，决定列集合与顺序。
        scope: services/scope.py::project_scope() 的结果。
        column_limit: 每列最多返回多少张卡。

    Returns:
        {"columns": [{"key", "title", "items", "total", "truncated"}, ...]}，
        列顺序 = workflow.columns(entity) 顺序，列内按 position ASC, id ASC。
    """
    columns = []
    for key, title in workflow.columns(entity):
        q = apply_project_filter(model.query.filter(model.status == key), model, scope)
        total = q.order_by(None).count()
        rows = q.order_by(model.position.asc(), model.id.asc()).limit(column_limit).all()
        columns.append({
            "key": key,
            "title": title,
            "rows": rows,
            "total": total,
            "truncated": total > len(rows),
        })
    # 【ticket-document-management §4.3 / 评审 R8】`document_count` 的落点是**这里**，
    # 不是 routes/board.py（那只是个 32 行 shim）。计数必须在收集完**全部列**的 rows
    # 之后调**一次**——每列各调一次就是 7 次查询，而看板一次返回 7 列。
    # ids 只含实际返回的行（本模块有 column_limit 截断）。
    visible_ids = [row.id for column in columns for row in column["rows"]]
    counts = link_counts(entity, visible_ids)
    return {"columns": [{
        "key": column["key"],
        "title": column["title"],
        "items": [{**row.to_dict(), "document_count": counts.get(row.id, 0)}
                  for row in column["rows"]],
        "total": column["total"],
        "truncated": column["truncated"],
    } for column in columns]}
