"""批量计数（ticket-document-management §4.3 实现约束 / 评审 R8）。

`document_count` 的**唯一**来源。为什么必须是一个独立函数而不是写进 `to_dict`：

现网看板与两个列表页**都只调 `r.to_dict()`**（`models/requirement.py` 与 `models/bug.py`
是两份独立的字面量 dict，没有共享序列化器）。`to_dict` 是模型实例方法，**拿不到批量
预取的结果**——把计数塞进去只能退化成每行一次子查询，即 §2.1 点名要消灭的 N+1。

因此落地方式钉死为：**在序列化站点富化，不改任何 `to_dict`**——
`{**r.to_dict(), "document_count": counts.get(r.id, 0)}`。两个 `to_dict` 一行不动，
既有 21 个调用方零风险。

惯用法照抄现网 `routes/stats.py` 的 `func.count + group_by`。
"""
from sqlalchemy import func

from extensions import db
from models.document import Document, DocumentVersion
from models.document_link import DocumentLink
from services.documents import trash


def link_counts(entity: str, ids) -> dict:
    """一次 group-by 查出这批工单各自的绑定文档数。

    Args:
        entity: "requirement" | "bug"。
        ids: 工单 id 可迭代对象。**只含实际要序列化的行**（看板有 column_limit 截断）。

    Returns:
        `{entity_id: count}`，未绑定任何文档的工单**不出现在结果里**（调用方用
        `.get(id, 0)` 取值）。

    契约：`ids` 为空时**直接返回 {} 且不发查询**——SQLite 对空 `IN ()` 的行为不必去赌。
    看板一次返回 5~7 列，计数必须在**收集完全部列的 rows 之后**调一次，不是每列一次。

    【过滤点 5 · §2.4】必须 join `documents` 并过滤软删，否则看板与列表的回形针徽章
    数字虚高：显示 3、点进去只有 2 份。这一行错了不会抛异常，只会让数字安静地说谎。
    """
    id_list = list(ids)
    if not id_list:
        return {}
    rows = (db.session.query(DocumentLink.entity_id, func.count(DocumentLink.id))
            .join(Document, Document.id == DocumentLink.document_id)
            .filter(DocumentLink.entity_type == entity,
                    DocumentLink.entity_id.in_(id_list))
            .filter(trash.not_deleted())
            .group_by(DocumentLink.entity_id)
            .all())
    return {entity_id: total for entity_id, total in rows}


def with_document_counts(entity: str, rows) -> list:
    """把一批工单序列化为 dict 并富化 `document_count`（**恰好一次**计数查询）。

    这是列表页与详情页的统一入口。**不改任何 `to_dict`**——见模块 docstring。
    """
    tickets = list(rows)
    counts = link_counts(entity, [t.id for t in tickets])
    return [{**t.to_dict(), "document_count": counts.get(t.id, 0)} for t in tickets]


def with_document_count(entity: str, ticket) -> dict:
    """单张工单的同款富化（详情页 / 写路径的响应体）。"""
    counts = link_counts(entity, [ticket.id])
    return {**ticket.to_dict(), "document_count": counts.get(ticket.id, 0)}


def document_link_counts(document_ids) -> dict:
    """一次 group-by 查出这批文档各自被绑定的次数（文档库列表的 `link_count`）。"""
    id_list = list(document_ids)
    if not id_list:
        return {}
    rows = (db.session.query(DocumentLink.document_id, func.count(DocumentLink.id))
            .filter(DocumentLink.document_id.in_(id_list))
            .group_by(DocumentLink.document_id)
            .all())
    return {document_id: total for document_id, total in rows}


def versions_by_id(version_ids) -> dict:
    """一次 `IN` 查出这批版本行，供列表页免去「每行一次 current_version 子查询」。"""
    id_list = [v for v in version_ids if v is not None]
    if not id_list:
        return {}
    rows = DocumentVersion.query.filter(DocumentVersion.id.in_(id_list)).all()
    return {row.id: row for row in rows}


def serialize_documents(documents) -> list:
    """把一批 Document 序列化为 §4.1 的响应形状，**恰好三次**批量查询。

    列表端点一律走这里，不要逐行调 `doc.to_dict()`——那是 50 行 100 次往返。
    """
    docs = list(documents)
    if not docs:
        return []
    counts = document_link_counts([d.id for d in docs])
    versions = versions_by_id([d.current_version_id for d in docs])
    return [
        d.to_dict(link_count=counts.get(d.id, 0),
                  version=versions.get(d.current_version_id))
        for d in docs
    ]
