"""Requirement 模型（§5 requirements 表）。

多态 assignee：`assignee_type`(nullable, 取值 {user, agent}) + `assignee_id`。
未指派时 assignee_type / assignee_id 均为 SQL NULL（【R-10】）。
需求 → 其转出 BUG 的关系统一由 bugs.related_requirement_id 反查（【R-07】）。
"""
from extensions import db, utcnow

PRIORITIES = ("low", "medium", "high", "urgent")
# 多态指派目标类型集合；「未指派」以列为 NULL 表达，而非枚举字面量 'null'（【R-10】）。
ASSIGNEE_TYPES = ("user", "agent")


class Requirement(db.Model):
    __tablename__ = "requirements"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    priority = db.Column(db.String(16), nullable=False, default="medium")
    status = db.Column(db.String(24), nullable=False, default="new", index=True)

    # 多态 assignee（无法建 DB 级外键，写接口需先校验目标存在）。
    assignee_type = db.Column(db.String(8), nullable=True)
    assignee_id = db.Column(db.Integer, nullable=True)

    reporter_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    # 列内排序：MVP 追加到列尾（position = 该列现有最大值 + 1，见 §2.2 B / R-09）。
    position = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    def resolve_assignee(self):
        """按 assignee_type join 出概要对象；未指派返回 None。"""
        return _resolve_assignee(self.assignee_type, self.assignee_id)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "status": self.status,
            "assignee_type": self.assignee_type,
            "assignee_id": self.assignee_id,
            "assignee": self.resolve_assignee(),
            "reporter_id": self.reporter_id,
            "position": self.position,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


def _resolve_assignee(assignee_type, assignee_id):
    """多态 assignee 概要解析，供 Requirement / Bug 共用。"""
    if not assignee_type or assignee_id is None:
        return None
    # 局部 import 规避模型间循环依赖。
    if assignee_type == "user":
        from .user import User

        u = db.session.get(User, assignee_id)
        return u.summary() if u else None
    if assignee_type == "agent":
        from .agent import Agent

        a = db.session.get(Agent, assignee_id)
        return a.summary() if a else None
    return None


def _iso(dt):
    return dt.isoformat() + "Z" if dt else None
