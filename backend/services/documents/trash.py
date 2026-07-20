"""文档回收站（document-lifecycle-depth §2.4 支柱 D）——软删 / 恢复 / 彻底删除。

**不 commit**：事务边界仍由路由层与 CLI 掌握（与 `services/documents/service.py` 同约定）。

两个谓词 `not_deleted()` / `is_deleted()` 是「软删的判据是什么」在全仓库的**唯一出处**。
八处过滤点一律引用它们而不是各自写一遍 `Document.deleted_at.is_(None)`——将来若改成
`deleted_by_id IS NOT NULL` 或加第三态，只改这两行。漏掉任何一处过滤点的后果不是报错，
而是**幽灵文档**：在抽屉里看不见，却仍在替工单满足阶段清单、仍让徽章数字虚高（§2.4 的
八处清单与各自的漏判后果）。

**本模块刻意不在模块级 import `service`**：`service.py` 需要 `trash.not_deleted()` 过滤
它自己的两个查询，模块级互相 import 会成环。故三个写函数在函数体内 lazy import，
与 `service.fanout_revision` 对模型的处理同款。
"""
import logging

from flask import current_app

from extensions import db, utcnow
from models.activity import Activity
from models.document import Document
from models.document_link import DocumentLink

log = logging.getLogger("aragon.documents.trash")


# ————————————————————— 过滤谓词（唯一出处） —————————————————————

def not_deleted():
    """`Document.deleted_at.is_(None)` 的唯一出处。所有列表 / 查找 / 计数一律引用它。"""
    return Document.deleted_at.is_(None)


def is_deleted():
    """`Document.deleted_at.isnot(None)`——回收站视图与 purge / restore 的唯一出处。"""
    return Document.deleted_at.isnot(None)


# ————————————————————— 软删 / 恢复 —————————————————————

def soft_delete(document, actor) -> int:
    """把文档移入回收站（**不 commit**），返回写了几条 `doc_trashed` 时间线。

    **绑定关系刻意不解除**：那正是软删相对「删了再传一遍」的全部价值——恢复之后
    工单抽屉里的位置与 `link.stage` 快照全部原样回来。它的直接推论是
    「回收站里的文档仍有绑定」是**常态**，`purge` 必须自己解绑（见该函数）。

    Args:
        actor: `("user", uid)` | `("system", None)`。

    Raises:
        ValueError: 文档已在回收站（调用方的判定漏了，属于编程错误，不吞）。
    """
    if document.deleted_at is not None:
        raise ValueError(f"document {document.id} is already in trash")
    document.deleted_at = utcnow()
    document.deleted_by_id = actor[1] if actor and actor[0] == "user" else None
    db.session.flush()
    return _fanout(document, "doc_trashed", actor,
                   suffix="已移入回收站")


def restore(document, actor) -> int:
    """把文档移出回收站（**不 commit**），返回写了几条 `doc_restored` 时间线。

    Raises:
        ValueError: 文档不在回收站（调用方的判定漏了）。
    """
    if document.deleted_at is None:
        raise ValueError(f"document {document.id} is not in trash")
    document.deleted_at = None
    document.deleted_by_id = None
    db.session.flush()
    return _fanout(document, "doc_restored", actor, suffix="已从回收站恢复")


def purge(document, actor) -> set:
    """把一份**回收站中**的文档彻底删除（**不 commit**），返回可回收的摘要集合。

    **自包含**：先解绑（逐单写 `doc_detached`，受 `DOC_FANOUT_MAX_LINKS` 约束）再删行。
    **绝不假设调用方已经解过绑**——软删默认保留全部绑定，「还有 link」才是常态；
    `document_links.document_id` 是**真外键**且 `PRAGMA foreign_keys=ON` 每连接生效，
    把 detach 留在路由里，CLI 路径就会在第一份带绑定的过期文档上撞外键 →
    IntegrityError → 500 / 崩溃（评审 V-02）。

    Args:
        actor: HTTP 路径为 `("user", uid)`；CLI 路径恒为 `("system", None)`。

    Returns:
        本次删除后**已无人引用**的摘要集合，供调用方在 commit 之后 `reap()`。

    Raises:
        ValueError: 该文档不在回收站（调用方的判定漏了，属于编程错误，不吞）。
    """
    from services.documents import service

    if document.deleted_at is None:
        raise ValueError(f"document {document.id} is not in trash")
    service.detach_all_links(document, actor)
    return service.delete_document(document)


def expired_query(days: int):
    """回收站中**已超过保留期**的文档查询（最早删除的在前），供 CLI 扫描。

    Args:
        days: 保留天数。`<= 0` 表示「全部立即过期」，仅供人工指定 `--days 0` 时使用。
    """
    from datetime import timedelta

    cutoff = utcnow() - timedelta(days=max(int(days), 0))
    return (Document.query
            .filter(is_deleted())
            .filter(Document.deleted_at <= cutoff)
            .order_by(Document.deleted_at.asc(), Document.id.asc()))


def retention_days() -> int:
    """回收站保留期。前端**不得硬编码**，统一由 `GET /api/documents/meta` 下发（R-11）。"""
    return int(current_app.config.get("DOC_TRASH_RETENTION_DAYS", 30))


# ————————————————————— 内部 —————————————————————

def _fanout(document, action: str, actor, *, suffix: str) -> int:
    """为该文档的绑定工单逐条写一条时间线（**不发通知**）。

    与 `service.fanout_revision` 同款上限与理由（SQLite 单写者，一份绑了 60 张单的
    文档不能在一个事务里写 60 条 Activity + 120 条 Notification）。

    **不发通知**是刻意的：软删 / 恢复都是收敛性操作，与现网 `doc_detached` 同源取向——
    时间线上有留痕，需要追责时查得到，这个强度是合适的。
    """
    from models.bug import Bug
    from models.requirement import Requirement
    from services import notifications

    models = {"requirement": Requirement, "bug": Bug}
    links = (DocumentLink.query.filter_by(document_id=document.id)
             .order_by(DocumentLink.id.asc()).all())
    cap = int(current_app.config.get("DOC_FANOUT_MAX_LINKS", 20))
    title = notifications.short_text(document.title)
    written = 0
    for link in links[:cap]:
        model = models.get(link.entity_type)
        ticket = db.session.get(model, link.entity_id) if model else None
        if ticket is None:
            continue                        # 单已被删（link 是孤儿）→ 不写空审计
        Activity.log(link.entity_type, link.entity_id, action, actor=actor,
                     to_status=ticket.status, message=f"文档「{title}」{suffix}")
        written += 1
    return written
