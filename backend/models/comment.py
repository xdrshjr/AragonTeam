"""Comment 模型（Phase-2 §5 comments 表）——工单讨论 / 人机混合评论。

多态作者：author_type ∈ {user, agent, system} + author_id（system 为 NULL）。
多态实体：entity_type ∈ {requirement, bug} + entity_id。
与既有 assignee 多态同策略：无 DB 级外键，to_dict 按类型 join 概要，
作者已删除时降级为占位而非抛异常。
"""
from extensions import db, utcnow

# 评论作者类型；system 为平台自动留痕（如未来自动化通知）。
COMMENT_AUTHOR_TYPES = ("user", "agent", "system")
# 评论所属实体类型，与 activities 一致。
COMMENT_ENTITY_TYPES = ("requirement", "bug")


class Comment(db.Model):
    __tablename__ = "comments"

    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(16), nullable=False)  # requirement | bug
    entity_id = db.Column(db.Integer, nullable=False)
    author_type = db.Column(db.String(16), nullable=False)  # user | agent | system
    author_id = db.Column(db.Integer, nullable=True)  # system 为 NULL
    body = db.Column(db.Text, nullable=False)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    # 复合索引：支撑「某工单的评论 / feed」查询。
    __table_args__ = (
        db.Index("ix_comments_entity", "entity_type", "entity_id"),
    )

    def resolve_author(self) -> dict:
        """按 author_type join 出作者概要；作者已删除时降级为占位，不抛异常。"""
        return _resolve_author(self.author_type, self.author_id)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "author_type": self.author_type,
            "author_id": self.author_id,
            "author": self.resolve_author(),
            "body": self.body,
            "created_at": _iso(self.created_at),
        }


def _resolve_author(author_type, author_id) -> dict:
    """多态作者概要解析，供 Comment 与 feed 共用。"""
    if author_type == "system":
        return {"type": "system", "name": "系统"}
    if author_type == "user":
        from .user import User

        u = db.session.get(User, author_id) if author_id is not None else None
        return u.summary() if u else {"type": "user", "id": author_id, "name": "(已删除)"}
    if author_type == "agent":
        from .agent import Agent

        a = db.session.get(Agent, author_id) if author_id is not None else None
        return a.summary() if a else {"type": "agent", "id": author_id, "name": "(已删除)"}
    # 未知类型兜底，保证 to_dict 永不抛。
    return {"type": author_type or "unknown", "id": author_id, "name": "(未知)"}


def _iso(dt):
    return dt.isoformat() + "Z" if dt else None
