"""NotificationPreference 模型（account-settings §5）——逐类通知开关。

本轮**唯一新增表**（additive，create_all 首启自动建，无既有列变更、无迁移风险；
同 Phase-3 引入 notifications 表时验证过的向后兼容策略）。每 (user_id, type) 至多一行，
唯一约束收敛。**缺省语义「无行=启用」**——既有用户零回填，无人静音时 notify() 行为不变。
"""
from extensions import db, utcnow
from models.notification import NOTIFICATION_TYPES  # 逐字复用 6 类枚举，闸判无需映射。


class NotificationPreference(db.Model):
    __tablename__ = "notification_preferences"

    id = db.Column(db.Integer, primary_key=True)
    # 收件人 = 人类 User.id（与 notifications.user_id 语义一致）。
    user_id = db.Column(db.Integer, nullable=False, index=True)
    type = db.Column(db.String(32), nullable=False)  # ∈ NOTIFICATION_TYPES
    enabled = db.Column(db.Boolean, nullable=False, default=True)  # False = 静音该类型

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    # 每人每类型至多一行；服务层 upsert 依赖此约束收敛并发（§10 R10）。
    __table_args__ = (
        db.UniqueConstraint("user_id", "type", name="uq_notif_pref_user_type"),
    )

    def to_dict(self) -> dict:
        return {"type": self.type, "enabled": self.enabled}
