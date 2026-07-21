"""Activity 模型（§5 activities 表）——审计 / 时间线。

记录人类与 Agent 混合协作的完整流转轨迹，是本平台核心价值主张
（人 / Agent 混合协作可追溯）的数据落点。
"""
from extensions import db, utcnow

# 【account-security-and-governance §2.3 C-1】实体维度扩到账号与站点设置。
# 工单实体**单独成组**：`GET /api/stats` 与所有面向全员的时间线查询都只认这一组，
# 治理事件绝不能漏进仪表盘「最近动态」（那是一次实打实的信息泄露）。
TICKET_ENTITY_TYPES = ("requirement", "bug")
ENTITY_TYPES = TICKET_ENTITY_TYPES + ("user", "app_setting")
ACTOR_TYPES = ("user", "agent", "system")

# app_setting 是站点级单例，没有自然主键；用 0 作哨兵 entity_id（该列 nullable=False）。
APP_SETTING_ENTITY_ID = 0


class Activity(db.Model):
    __tablename__ = "activities"

    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(16), nullable=False)  # requirement | bug
    entity_id = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(32), nullable=False)  # created | assigned | moved | converted ...
    # 【account-security-and-governance §2.3 C-1】这两列**同时**承载账号治理的取值迁移
    # （「角色 A → 角色 B」「active → disabled」）。算不算语义滥用？算一点。但替代方案是
    # 为一个纯展示用途在一张已上线的表上再加两列（from_value/to_value）——schema_sync 登记 +
    # 存量库 ALTER + 两条永远二选一的空列，代价明显高于收益。
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
        # 【§2.4-C3】截断到列宽 VARCHAR(255)（含工单标题的审计文案在 Postgres/MySQL 会溢出报错）。
        # 保 None：该列 nullable，合法的 message=None 不得被强转为 ""（改变时间线语义）。
        if isinstance(message, str):
            message = message[:255]
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
