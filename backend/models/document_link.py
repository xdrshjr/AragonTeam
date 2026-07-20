"""DocumentLink 模型（ticket-document-management §5.1）——文档 ↔ 工单的多对多绑定。

现实里文档与工单本就不是从属关系：一份 PRD 服务一簇需求，一份回归测试报告同时关掉
三个 BUG。把文档做成工单的私有附件，等于在第一天就把复用能力焊死。

**多态照旧不建 DB 外键**：`(entity_type, entity_id)` 与既有 comments / activities /
notifications 同策略——SQLite 无法为多态引用建约束，且真外键会让「删掉一张需求单」
这一合法操作被外键挡住。引用完整性由应用层前置检查保证（services/lifecycle.py 契约）。

`stage` 是**绑定当时的工单状态快照**，工单后续流转**绝不回写**它。于是时间线可以说出
「这份测试报告是在 testing 阶段交的」，而不只是「有个文件」。
"""
from extensions import db, utcnow

DOCUMENT_LINK_ENTITY_TYPES = ("requirement", "bug")


class DocumentLink(db.Model):
    __tablename__ = "document_links"

    id = db.Column(db.Integer, primary_key=True)
    # 真外键：文档被删时不允许留下悬挂绑定（单态引用，语义明确）。
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id"), nullable=False)
    entity_type = db.Column(db.String(16), nullable=False)  # requirement | bug（多态，无 FK）
    entity_id = db.Column(db.Integer, nullable=False)
    label = db.Column(db.String(64), nullable=True)
    # 绑定当时的工单状态快照，永不回写（见模块 docstring）。
    stage = db.Column(db.String(24), nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    __table_args__ = (
        db.Index("uq_doclink_doc_entity", "document_id", "entity_type", "entity_id",
                 unique=True),
        # document_count 批量计数与工单文档列表的支撑索引。
        db.Index("ix_doclink_entity", "entity_type", "entity_id"),
    )

    def resolve_created_by(self):
        if self.created_by_id is None:
            return None
        from .comment import _resolve_author

        return _resolve_author("user", self.created_by_id)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "label": self.label,
            "stage": self.stage,
            "created_by": self.resolve_created_by(),
            "created_at": _iso(self.created_at),
        }


def _iso(dt):
    return dt.isoformat() + "Z" if dt else None
