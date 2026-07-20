"""全局统一搜索（跨需求 + BUG + **文档**的关键词命中聚合）。

只读服务：复用 Requirement / Bug 既有 to_dict；对用户关键词转义 LIKE 元字符
（% _ \\），避免通配泄漏（比 routes 内既有裸 ilike 更稳健）。排序按 updated_at
倒序（最近活跃优先，作为预览相关度近似）。空关键词由调用方处理，此处假定已 strip 非空。

【document-lifecycle-depth §2.1 A-1】新增 documents 桶。**复用是三表分离的全部理由，
而发现是复用的前提**——一份 PRD 传进来三周后想再用它，此前只能去 /documents 一页页翻。
"""
from sqlalchemy import or_

from models.document import Document, DocumentVersion
from models.requirement import Requirement
from models.bug import Bug

DEFAULT_LIMIT = 5
MAX_LIMIT = 20


def escape_like(s: str) -> str:
    """转义 LIKE 元字符（% _ \\），供检索与列表过滤复用（§2.4-C1）。

    转义后须搭配 `ilike(..., escape="\\")` 使用，令用户输入的 `%`/`_` 作字面量匹配。
    """
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _like_clause(model, keyword: str):
    """构造 title/description 的大小写不敏感 LIKE 子句，转义 LIKE 元字符。"""
    like = f"%{escape_like(keyword)}%"
    return or_(model.title.ilike(like, escape="\\"),
               model.description.ilike(like, escape="\\"))


def search_entity(model, keyword: str, limit: int):
    """单实体检索：返回 (前 limit 条命中, 总命中数)，按 updated_at 倒序。"""
    q = model.query.filter(_like_clause(model, keyword))
    total = q.count()
    rows = q.order_by(model.updated_at.desc(), model.id.desc()).limit(limit).all()
    return rows, total


def _document_like_clause(keyword: str):
    """文档命中面：标题 / 描述 / **当前版本的原始文件名**。

    第三项是刻意的：用户记得住的常常是 `payment-v2.md` 这个文件名，而不是上传时随手写的
    标题。它需要 outerjoin document_versions，故不能复用 `_like_clause`。
    """
    like = f"%{escape_like(keyword)}%"
    return or_(
        Document.title.ilike(like, escape="\\"),
        Document.description.ilike(like, escape="\\"),
        DocumentVersion.original_filename.ilike(like, escape="\\"),
    )


def search_documents(keyword: str, limit: int):
    """文档检索：返回 (前 limit 条命中, 总命中数)。

    **join 固定到 `current_version_id`（一对一）**，因此 `count()` 在没有版本的文档上
    仍然只算一次，不会放大计数。若将来改成关联 `document_versions.document_id`
    （一对多），`count()` 会**重复计数**——`test_search_counts_documents_once` 钉死这一点。
    """
    from services.documents import trash

    q = (Document.query
         .outerjoin(DocumentVersion,
                    DocumentVersion.id == Document.current_version_id)
         .filter(trash.not_deleted())        # 【铁律】回收站里的文档绝不出现在搜索里
         .filter(_document_like_clause(keyword)))
    total = q.count()
    rows = (q.order_by(Document.updated_at.desc(), Document.id.desc())
            .limit(limit).all())
    return rows, total


def search_all(keyword: str, limit: int = DEFAULT_LIMIT) -> dict:
    """跨需求 + BUG + 文档聚合。keyword 须为已 strip 的非空串；limit 须已 clamp。"""
    from services.documents import counts as document_counts

    reqs, req_total = search_entity(Requirement, keyword, limit)
    bugs, bug_total = search_entity(Bug, keyword, limit)
    docs, doc_total = search_documents(keyword, limit)
    return {
        "requirements": [r.to_dict() for r in reqs],
        "bugs": [b.to_dict() for b in bugs],
        # **必须**走批量序列化：搜索下拉一次最多 20 行，逐行 to_dict() 就是 40 次子查询。
        "documents": document_counts.serialize_documents(docs),
        "counts": {"requirements": req_total, "bugs": bug_total,
                   "documents": doc_total},
    }
