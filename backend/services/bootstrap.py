"""根管理员保障（self-service-registration §2.1 A-3）。

配置文件是根管理员的**唯一真相**：`ensure_root_admin(app)` 在每次启动时幂等地保证
`ROOT_ADMIN_USERNAME` 这个账号存在、是 admin、是启用状态、`is_root=True`，并保证
全库至多一行 `is_root`。它是「所有管理员都进不来」时唯一的破窗入口——改环境变量 + 重启。

**调用时机不可调换**：必须排在 `seed_if_empty()` **之后**（app.py）。seed 的幂等判据是
`User.query.count() == 0`，若先建根管理员，全新库上 users 恒非空，示例项目 / 示例需求 /
示例 BUG / 示例评论一行都不会写入，「首次启动开箱有内容」这条既有承诺当场失效（§7 R-4）。

本模块**绝不打印密码**。
"""
from extensions import db
from models.user import User
from services import avatars

# 内置默认口令。生产上仍在用它必须刺眼——它随仓库公开，等于没有口令。
_BUILTIN_DEFAULT_PASSWORD = "admin123"


def ensure_root_admin(app) -> dict:
    """幂等地保证根管理员存在且归位；返回供日志使用的动作描述。

    Args:
        app: Flask 应用（读 config、写 logger）。必须已进入 app_context。

    Returns:
        `{"action": "created"|"promoted"|"password_synced"|"unchanged", "username": str}`。

    Raises:
        RuntimeError: `ROOT_ADMIN_USERNAME` 配置为空——那是部署事故，应当起不来
            而不是静默跳过（静默跳过意味着这根支柱等于没上线，且没人会发现）。
    """
    username = str(app.config.get("ROOT_ADMIN_USERNAME", "")).strip()
    if not username:
        raise RuntimeError("ROOT_ADMIN_USERNAME must not be empty")

    user = User.query.filter_by(username=username).first()
    if user is None:
        _create_root(app, username)
        action = "created"
    else:
        action = _restore_root(app, user, username)

    # 单根不变量：配置文件是唯一真相，其余 is_root 行一律清标。
    demoted = User.query.filter(User.username != username,
                                User.is_root.is_(True)).update(
        {"is_root": False}, synchronize_session=False)
    if demoted:
        app.logger.warning("ensure_root_admin cleared %s stray is_root row(s)", demoted)
    db.session.commit()

    _warn_about_weak_setup(app)
    return {"action": action, "username": username}


def _create_root(app, username: str) -> None:
    """建出根管理员（不 commit，由调用方统一提交）。"""
    user = User(
        username=username, role="admin", is_active=True, is_root=True, source="root",
        display_name=app.config.get("ROOT_ADMIN_DISPLAY_NAME") or username,
        email=app.config.get("ROOT_ADMIN_EMAIL"),
        avatar_color=avatars.pick_color(username),
    )
    user.set_password(app.config["ROOT_ADMIN_PASSWORD"])
    db.session.add(user)


def _restore_root(app, user, username: str) -> str:
    """把一个既有同名账号强制归位为根管理员；返回动作名。

    把一个既有账号提成**不可降级**的根管理员是一次不可逆的授权变更，绝不允许它静默
    发生——运维必须能在启动日志里看到「是谁被提权了」（§7 R-15）。
    """
    was_ordinary = (user.role != "admin") or (not user.is_root)
    changed = was_ordinary or (not user.is_active)
    user.role = "admin"
    user.is_active = True
    user.is_root = True

    if app.config.get("ROOT_ADMIN_SYNC_PASSWORD"):
        user.set_password(app.config["ROOT_ADMIN_PASSWORD"])
        action = "password_synced"
    else:
        action = "promoted" if changed else "unchanged"

    if was_ordinary:
        app.logger.warning(
            "ensure_root_admin promoted existing account to root: id=%s username=%s",
            user.id, username)
    return action


def _warn_about_weak_setup(app) -> None:
    """两条启动期告警：默认口令未改、同步口令模式忘了关。

    测试环境（TESTING）静音——否则每个用例都刷两行 warning，真正的告警会被淹没。
    """
    if app.config.get("TESTING"):
        return
    if app.config.get("ROOT_ADMIN_PASSWORD") == _BUILTIN_DEFAULT_PASSWORD and not app.debug:
        app.logger.warning(
            "ROOT_ADMIN_PASSWORD is still the built-in default — change it")
    # 同步口令模式是一个**临时恢复态**，不是稳态。每次启动都喊一遍，让「登录完忘了关」
    # 这件事在下一次重启时就被发现，而不是等新密码被静默吞掉（§2.1 A-1 的四步流程）。
    if app.config.get("ROOT_ADMIN_SYNC_PASSWORD"):
        app.logger.warning(
            "ROOT_ADMIN_SYNC_PASSWORD is ON — the root password is being reset from "
            "config on every boot; turn it off and restart before changing the password")
