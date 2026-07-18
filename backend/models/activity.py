"""Activity 模型（§5 activities 表）——审计 / 时间线。

记录人类与 Agent 混合协作的完整流转轨迹，是本平台核心价值主张
（人 / Agent 混合协作可追溯）的数据落点。
"""
from extensions import db, utcnow

ENTITY_TYPES = ("requirement", "bug")
ACTOR_TYPES = ("user", "agent", "system")


class Activity(db.Model):
    __tablename__ = "activities"

    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(16), nullable=False)  # requirement | bug
    entity_id = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(32), nullable=False)  # created | assigned | moved | converted ...
    from_status = db.Column(db.String(24), nullable=True)
    to_status = db.Column(db.String(24), nullable=True)
    actor_type = db.Column(db.String(16), nullable=True)  # user | agent | system
    actor_id = db.Column(db.Integer, nullable=True)
    # 人类可读的一句话说明（可选），前端时间线直接展示。
    message = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    # 复合索引：支撑「某实体的时间线」查询。
    __table_args__ = (
        db.Index("ix_activities_entity", "entity_type", "entity_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "action": self.action,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "message": self.message,
            "created_at": _iso(self.created_at),
        }

    @staticmethod
    def log(entity_type, entity_id, action, actor=None, from_status=None,
            to_status=None, message=None):
        """便捷写审计记录；不 commit（由调用方事务统一提交）。

        actor: (actor_type, actor_id) 元组或 None（None 记为 system）。
        """
        actor_type, actor_id = ("system", None)
        if actor:
            actor_type, actor_id = actor
        act = Activity(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            from_status=from_status,
            to_status=to_status,
            actor_type=actor_type,
            actor_id=actor_id,
            message=message,
        )
        db.session.add(act)
        return act


def _iso(dt):
    return dt.isoformat() + "Z" if dt else None
