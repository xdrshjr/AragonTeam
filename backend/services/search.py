"""全局统一搜索（跨需求 + BUG 的关键词命中聚合）。

只读服务：复用 Requirement / Bug 既有 to_dict；对用户关键词转义 LIKE 元字符
（% _ \\），避免通配泄漏（比 routes 内既有裸 ilike 更稳健）。排序按 updated_at
倒序（最近活跃优先，作为预览相关度近似）。空关键词由调用方处理，此处假定已 strip 非空。
"""
from sqlalchemy import or_

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


def search_all(keyword: str, limit: int = DEFAULT_LIMIT) -> dict:
    """跨需求 + BUG 聚合。keyword 须为已 strip 的非空串；limit 须已 clamp。"""
    reqs, req_total = search_entity(Requirement, keyword, limit)
    bugs, bug_total = search_entity(Bug, keyword, limit)
    return {
        "requirements": [r.to_dict() for r in reqs],
        "bugs": [b.to_dict() for b in bugs],
        "counts": {"requirements": req_total, "bugs": bug_total},
    }
