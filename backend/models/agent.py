"""Agent 模型（§5 agents 表）。

Agent 是本平台的一等公民执行者：需求单与 BUG 单既可指派给人类成员，
也可指派给 AI Agent（dev-agent / qa-agent 等）。
"""
from extensions import db, utcnow

AGENT_KINDS = ("dev", "qa", "generic")
AGENT_STATUSES = ("idle", "busy", "offline")


class Agent(db.Model):
    __tablename__ = "agents"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False, index=True)
    kind = db.Column(db.String(16), nullable=False, default="generic")
    status = db.Column(db.String(16), nullable=False, default="idle")
    description = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "status": self.status,
            "description": self.description,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }

    def summary(self) -> dict:
        return {
            "type": "agent",
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
        }


def _iso(dt):
    return dt.isoformat() + "Z" if dt else None
