"""Notification 模型（Phase-3 §5 notifications 表）——协作感知 / 通知中心。

本 Phase **唯一新增表**（additive，create_all 自动建，无既有列变更、无迁移风险）。
收件人**仅人类** User（user_id）；多态来源 (entity_type, entity_id) + 多态施动者
(actor_type, actor_id)。与 comments / activities 一致：无 DB 级外键，to_dict 按
actor_type join 概要，施动者已删除时降级为占位而非抛异常。
"""
from extensions import db, utcnow

# 通知类型集合（§4.2）。
NOTIFICATION_TYPES = (
    "assigned",        # 指派 / 自主认领
    "commented",       # 有人在工单上评论
    "mentioned",       # @提及
    "status_changed",  # 人类推进 / 流转
    "agent_advanced",  # Agent 自主推进
    "converted",       # 需求转 BUG
    # 【ticket-document-management §2.5】文档被上传 / 绑定 / 改版。因 NotificationPreference
    # 采用「无行 = 开启」，存量用户**零回填**即自动收到该类通知。
    # 下游 services/notification_prefs.py 与 routes/me.py 都**从本元组派生**，无需改动；
    # 唯一需要手改的是前端镜像 components/settings/NotificationPrefsCard.tsx。
    "document_added",
)


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    # 收件人：仅人类 User.id；Agent / system 不作收件人（§5）。
    user_id = db.Column(db.Integer, nullable=False, index=True)
    type = db.Column(db.String(32), nullable=False)
    # 多态来源工单（点击直达）。
    entity_type = db.Column(db.String(16), nullable=True)  # requirement | bug
    entity_id = db.Column(db.Integer, nullable=True)
    # 多态施动者。
    actor_type = db.Column(db.String(16), nullable=True)  # user | agent | system
    actor_id = db.Column(db.Integer, nullable=True)  # system 为 NULL
    message = db.Column(db.String(255), nullable=False)
    is_read = db.Column(db.Boolean, nullable=False, default=False, index=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    # 复合索引：支撑「我的未读」查询；created_at 索引支撑倒序分页。
    __table_args__ = (
        db.Index("ix_notifications_user_read", "user_id", "is_read"),
    )

    def resolve_actor(self):
        """多态施动者概要；无施动者返回 None，已删除降级占位（复用 comment 策略）。"""
        if self.actor_type is None:
            return None
        # 局部 import 规避模型间循环依赖，并复用统一的多态解析逻辑。
        from .comment import _resolve_author

        return _resolve_author(self.actor_type, self.actor_id)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "actor": self.resolve_actor(),
            "message": self.message,
            "is_read": self.is_read,
            "created_at": _iso(self.created_at),
        }


def _iso(dt):
    return dt.isoformat() + "Z" if dt else None
