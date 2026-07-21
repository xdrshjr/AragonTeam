"""通知偏好服务（account-settings §5）。

对外仅三个纯函数：effective_map / is_enabled / set_preferences。缺省语义
「无行=启用」，故既有用户零回填、无人静音时 notify() 行为逐字节不变。
本模块**不 commit**——写随调用方（路由）事务提交，并发冲突处理由路由收口（§10 R10）。
"""
from extensions import db
from models.notification import NOTIFICATION_TYPES
from models.notification_preference import NotificationPreference


def effective_map(user_id: int) -> dict:
    """`NOTIFICATION_TYPES` 全部类型的有效开关：缺省 True，存量行覆盖。

    **不写死类型条数**：本函数从元组派生，每轮新增通知类型时它自动跟随；写死数字
    只会变成下一轮的僵尸注释（CLAUDE.md §四）。
    """
    stored = {p.type: p.enabled
              for p in NotificationPreference.query.filter_by(user_id=user_id).all()}
    return {t: stored.get(t, True) for t in NOTIFICATION_TYPES}


def is_enabled(user_id: int, ntype: str) -> bool:
    """扇出前置闸；未知类型默认放行。

    读包在 no_autoflush 内——notify() 处于写事务中（工单 / 评论已 add 未 flush），
    此 SELECT 不得触发 autoflush 提前刷未完成对象（§10 R2，复用同款写锁收敛）。
    """
    with db.session.no_autoflush:
        row = NotificationPreference.query.filter_by(user_id=user_id, type=ntype).first()
    return row.enabled if row is not None else True


def set_preferences(user_id: int, mapping: dict) -> None:
    """按 type->bool 逐项 upsert（不 commit，随路由事务提交）。

    并发注记〔§10 R10〕：本函数只做「查-改 / 增」，不 commit；唯一约束
    (uq_notif_pref_user_type) 的冲突处理由**路由收口**——服务器 threaded=True，
    同一 (user_id, type) 的两个重叠请求可能双双走 INSERT，路由须
    `except IntegrityError: rollback + 重跑一次本函数`（届时行已存在走 UPDATE，
    bool 幂等收敛）。故本函数保持纯粹、可被安全重跑。
    """
    for ntype, enabled in mapping.items():
        row = NotificationPreference.query.filter_by(user_id=user_id, type=ntype).first()
        if row is None:
            db.session.add(NotificationPreference(user_id=user_id, type=ntype, enabled=bool(enabled)))
        else:
            row.enabled = bool(enabled)
