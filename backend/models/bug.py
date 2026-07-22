"""Bug 模型（§5 bugs 表）。

字段结构同 Requirement，差异：severity 枚举、status 默认 open、
related_requirement_id（由「需求转 BUG」写入，建索引供反查）。
"""
from extensions import db, utcnow
from .requirement import _resolve_assignee, _iso

SEVERITIES = ("trivial", "minor", "major", "critical")
ASSIGNEE_TYPES = ("user", "agent")


class Bug(db.Model):
    __tablename__ = "bugs"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    severity = db.Column(db.String(16), nullable=False, default="major")
    status = db.Column(db.String(24), nullable=False, default="open", index=True)

    assignee_type = db.Column(db.String(8), nullable=True)
    assignee_id = db.Column(db.Integer, nullable=True)

    reporter_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    # 转 BUG 时写入的源需求 id（一对多反查，建索引）。
    related_requirement_id = db.Column(
        db.Integer, db.ForeignKey("requirements.id"), nullable=True, index=True
    )
    # 【version-plan-hierarchy §3.1 / §4.3】归属计划；NULL = 未归属。无 DB 外键，理由同
    # requirements.plan_id（经 schema_sync 追加、只能 ADD COLUMN）。
    plan_id = db.Column(db.Integer, nullable=True, index=True)
    position = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    def resolve_assignee(self):
        return _resolve_assignee(self.assignee_type, self.assignee_id)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "title": self.title,
            "description": self.description,
            "severity": self.severity,
            "status": self.status,
            "assignee_type": self.assignee_type,
            "assignee_id": self.assignee_id,
            "assignee": self.resolve_assignee(),
            "reporter_id": self.reporter_id,
            "related_requirement_id": self.related_requirement_id,
            # 【version-plan-hierarchy §4.3】只输出 plan_id；`plan` 概要在序列化站点富化。
            "plan_id": self.plan_id,
            "position": self.position,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }
