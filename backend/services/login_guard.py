"""账号级登录锁定（login-hardening-and-audit-console §1.2）。

与 `LOGIN_MAX_ATTEMPTS`（`services/ratelimit.py` 的内存 IP 限流）是**两道正交的闸**：
前者按 `(ip, username)` 计、重启即失忆；本模块按**账号**计、落库、跨重启有效。
慢速分布式撞库（每次换 IP）只有后者挡得住。

判据是「**连续**失败」而不是「窗口内失败」：任何一次成功登录清零计数，因此不需要
第四列 `last_failed_login_at`。纯累加计数器会让一个用了半年、零星敲错几次的账号被
莫名锁住——那是把安全机制变成 bug。

所有写操作**不 commit**（沿用 `audit` / `notifications` 的既有约定），由调用方事务统一提交。
"""
from datetime import timedelta

from flask import jsonify

from extensions import db, utcnow
from models.activity import Activity
from services import audit, notifications
from services.config_knobs import clamped_int

# 钳位物理止挡（见 config.py 的同一段注释）。
_THRESHOLD_FLOOR, _THRESHOLD_CEIL = 3, 100
_MINUTES_FLOOR, _MINUTES_CEIL = 1, 1440
_COOLDOWN_FLOOR, _COOLDOWN_CEIL = 0, 10080


def lock_policy() -> dict:
    """`{"threshold": int, "minutes": int, "notify_cooldown": int}`，已钳位。

    唯一读这三个配置的地方（`services/passwords.py::policy()` 的同款收口）。

    - `threshold` 钳到 [3, 100]：下界 3 是因为「敲错两次就锁」在真实办公场景里是骚扰。
    - `minutes` 钳到 [1, 1440]：上界 24 小时——更长的锁定应由人按「停用」，那是一个
      有审计、可解释的动作，不该由配置项静默产生。
    - `notify_cooldown` 钳到 [0, 10080]：0 = 每次锁定都通知（给「小团队宁可吵也要知情」
      的部署留一条出路）。
    """
    return {
        "threshold": clamped_int("LOGIN_LOCK_THRESHOLD", 8,
                                 _THRESHOLD_FLOOR, _THRESHOLD_CEIL, source="login_guard"),
        "minutes": clamped_int("LOGIN_LOCK_MINUTES", 15,
                               _MINUTES_FLOOR, _MINUTES_CEIL, source="login_guard"),
        "notify_cooldown": clamped_int("LOGIN_LOCK_NOTIFY_COOLDOWN_MINUTES", 1440,
                                       _COOLDOWN_FLOOR, _COOLDOWN_CEIL, source="login_guard"),
    }


def is_locked(user) -> bool:
    """该账号此刻是否处于锁定期。None / 无 locked_until / 已过期 → False。"""
    return user is not None and user.locked_until is not None \
        and user.locked_until > utcnow()


def retry_after_seconds(user) -> int:
    """距解锁还有多少秒（向上取整，最小 1）；未锁定返回 0。"""
    if not is_locked(user):
        return 0
    delta = (user.locked_until - utcnow()).total_seconds()
    return max(1, int(delta) + (1 if delta > int(delta) else 0))


def note_failed_login(user) -> bool:
    """记一次失败登录（**不 commit**）。返回 True 表示本次刚好触发了锁定。"""
    # ① 根管理员**永不锁定**。它是「所有管理员都进不来」时唯一的破窗入口，把它锁上
    #    等于亲手拆掉那条恢复路径。IP 限流仍然作用于它。
    if user.is_root:
        return False
    # ② 已锁定就不再累加：否则攻击者可在锁定期内继续打，把本函数当成一个「每请求一次
    #    UPDATE 一行」的写放大器（SQLite 单写者，这是真实的可用性风险）。
    if is_locked(user):
        return False
    user.failed_login_count = (user.failed_login_count or 0) + 1
    policy = lock_policy()
    if user.failed_login_count < policy["threshold"]:
        return False
    user.locked_until = utcnow() + timedelta(minutes=policy["minutes"])
    # ③ 归零而不是保留：解锁之后重新起算，否则解锁后再错一次就立刻又锁上。
    user.failed_login_count = 0
    # ⑤ 通知冷却判据必须在写本条审计**之前**查（§1.2 B-3 ⑤ / 评审 P1-3）：否则
    #    _should_notify_lock 的 .exists() 会 autoflush 掉刚 add 的这条 account_locked，
    #    于是第一次锁定就「看见自己」而被静默压掉——通知永远发不出去。
    should_notify = _should_notify_lock(user, policy["notify_cooldown"])
    # ④ actor=None → system。锁定不是任何人做的，是规则做的。
    audit.log_user_event(user, "account_locked", None, to_value="locked",
                         message=f"连续 {policy['threshold']} 次登录失败，"
                                 f"已临时锁定 {policy['minutes']} 分钟")
    # 通知有冷却，审计没有。
    if should_notify:
        notifications.notify_account_locked(user)
    return True


def note_successful_login(user) -> None:
    """记一次成功登录：写 last_login_at、清零计数与锁（**不 commit**）。"""
    user.last_login_at = utcnow()
    user.failed_login_count = 0
    user.locked_until = None


def unlock(user, actor) -> bool:
    """解除锁定（**不 commit**）。返回 False 表示本来就没锁（幂等，不写审计）。"""
    if not is_locked(user):
        return False
    user.locked_until = None
    user.failed_login_count = 0
    audit.log_user_event(user, "account_unlocked", actor, from_value="locked",
                         message="解除了该账号的登录锁定")
    return True


def locked_response(user):
    """锁定态的 **403** 契约体（§1.2 B-5）。稳定错误串，勿更名。

    选 403 而非 423/429：429 已被 IP 限流占用，423 是 WebDAV 扩展码在 errors.py 无先例，
    403 与紧邻的「账号已停用」分支同形（同一语义类、同一状态码，靠稳定 error 串区分）。
    """
    return jsonify({
        "error": "account is temporarily locked",
        "detail": {
            "reason": "too many failed sign-in attempts",
            "retry_after_seconds": retry_after_seconds(user),
            "unlock_hint": "wait it out, or ask an administrator to unlock the account",
        },
    }), 403


def _should_notify_lock(user, cooldown_minutes: int) -> bool:
    """同一账号在冷却窗口内是否已经通知过（评审 P1-3）。

    判据直接查最近一条 `account_locked` 审计，不新增列、不新增表——审计行本来就在
    那一刻写，拿它当去重锚点是零成本的。cooldown=0 时恒 True（每次都通知）。

    调用发生在**已经确定要锁定**的那一刻，即每个锁定周期至多一次；正常登录路径
    （成功 / 单次失败 / 已锁定短路）一次都不会触发它，不构成热路径开销。
    """
    if cooldown_minutes <= 0:
        return True
    since = utcnow() - timedelta(minutes=cooldown_minutes)
    return not db.session.query(
        Activity.query.filter(Activity.entity_type == "user",
                              Activity.entity_id == user.id,
                              Activity.action == "account_locked",
                              Activity.created_at >= since).exists()).scalar()
