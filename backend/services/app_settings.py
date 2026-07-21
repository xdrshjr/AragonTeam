"""应用级键值设置（self-service-registration §2.2 B-1 / §5.3）。

本模块是 `app_settings` 表的**唯一**读写入口：路由层永远不直接查表。键值表用字符串
存一切，类型与业务约束（枚举 / 长度 / 字符集）全部收敛在这里，让「失去列级类型约束」
这个代价被限制在一个文件内。

三条硬约定：

1. **不缓存**。每次请求打一次唯一索引查询——本地 SQLite 下这是微秒级开销，而进程内
   缓存在 gunicorn 多 worker 下必然失效不同步（根管理员改了码，只有一个 worker 生效），
   是典型的「优化制造出的 bug」（§7 R-12）。
2. **脏值一律回落配置默认 + warning，绝不抛异常**。注册开关解析失败就让整个登录体系
   500，是把小故障放大成全站故障（§5.3）。
3. **`default_role` 无条件过 SIGNUP_ROLES 白名单**——库内脏值与**配置兜底值**一视同仁。
   少了这一步，`REGISTRATION_DEFAULT_ROLE=admin` 一个环境变量就能让任何拿到邀请码的人
   注册即为管理员：PATCH 端点的白名单只管住了「改设置」这条路径，管不住「全新库上
   app_settings 为空、直接走配置兜底」这条路径，而后者恰恰是每次全新部署的常态（§7 R-16）。

邀请码**明文存储**：根管理员必须能读回来才能发给同事，哈希存储会让「查看当前邀请码」
这个核心操作不可能实现。这是有意识的取舍，缓解手段见 §7 R-2（可随时 rotate、可关开关、
只有根管理员能读）。
"""
import hmac
import secrets

from flask import current_app

from extensions import db
from models.app_setting import AppSetting
from services.validation import ValidationError

KEY_REGISTRATION_ENABLED = "registration.enabled"
KEY_REGISTRATION_INVITE_CODE = "registration.invite_code"
KEY_REGISTRATION_DEFAULT_ROLE = "registration.default_role"

REGISTRATION_KEYS = (
    KEY_REGISTRATION_ENABLED,
    KEY_REGISTRATION_INVITE_CODE,
    KEY_REGISTRATION_DEFAULT_ROLE,
)

# 自助注册**永远**不能产出 admin：一个知道邀请码的人不该能直接成为管理员。
SIGNUP_ROLES = ("member", "pm")

INVITE_CODE_MIN, INVITE_CODE_MAX = 4, 64
# 人类可口述、可手抄：去掉 0/O/1/l/I 等易混字符。
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

_TRUE_LITERALS = ("true", "1", "yes", "on")
_FALSE_LITERALS = ("false", "0", "no", "off")


# ————————————————————— 底层读写 —————————————————————

def get_row(key: str):
    """取一行设置；不存在返回 None。"""
    return AppSetting.query.filter_by(key=key).first()


def _stored_values() -> dict:
    """一次取回注册相关的三行，避免逐键三次往返。"""
    rows = AppSetting.query.filter(AppSetting.key.in_(REGISTRATION_KEYS)).all()
    return {row.key: row.value for row in rows}


def _warn(message: str, *args) -> None:
    """脏值告警。用 current_app.logger 而非 print：运维需要它出现在结构化日志里。"""
    current_app.logger.warning(message, *args)


# ————————————————————— 值解释 —————————————————————

def _coerce_enabled(raw) -> bool:
    """解释 registration.enabled；无行 / 脏值回落配置默认。"""
    default = bool(current_app.config.get("REGISTRATION_ENABLED", True))
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in _TRUE_LITERALS:
        return True
    if value in _FALSE_LITERALS:
        return False
    _warn("app_settings: unparsable %s=%r, falling back to config default",
          KEY_REGISTRATION_ENABLED, raw)
    return default


def _coerce_invite_code(raw) -> str:
    """解释 registration.invite_code；无行 / 空值回落配置默认。"""
    default = str(current_app.config.get("REGISTRATION_INVITE_CODE", "aragon"))
    if raw is None:
        return default
    value = str(raw).strip()
    if not value:
        _warn("app_settings: empty %s, falling back to config default",
              KEY_REGISTRATION_INVITE_CODE)
        return default
    return value


def _coerce_default_role(raw) -> str:
    """解释 registration.default_role，**无条件**过 SIGNUP_ROLES 白名单（§7 R-16）。

    库内脏值与配置兜底值一视同仁：不在白名单内一律回落 "member" 并打 warning。
    """
    value = str(raw).strip() if raw is not None else \
        str(current_app.config.get("REGISTRATION_DEFAULT_ROLE", "member")).strip()
    if value in SIGNUP_ROLES:
        return value
    _warn("app_settings: %s=%r is not in the signup whitelist %s, falling back to 'member'",
          KEY_REGISTRATION_DEFAULT_ROLE, value, list(SIGNUP_ROLES))
    return "member"


def get_registration_settings() -> dict:
    """返回生效的注册设置 `{enabled, invite_code, default_role}`。

    「无行 = 用配置默认」——与 notification_prefs 的「无行 = 启用」同一模式，存量库零回填。
    `default_role` 的白名单约束见模块 docstring 第 3 条。
    """
    stored = _stored_values()
    return {
        "enabled": _coerce_enabled(stored.get(KEY_REGISTRATION_ENABLED)),
        "invite_code": _coerce_invite_code(stored.get(KEY_REGISTRATION_INVITE_CODE)),
        "default_role": _coerce_default_role(stored.get(KEY_REGISTRATION_DEFAULT_ROLE)),
    }


# ————————————————————— 写入 —————————————————————

def _validate_invite_code(code: str) -> str:
    """业务约束：长度 4~64、无空白字符。不满足抛 ValidationError（→ 400）。"""
    if any(ch.isspace() for ch in code):
        raise ValidationError("invite_code must not contain whitespace",
                              field="invite_code", expected="no whitespace")
    if not INVITE_CODE_MIN <= len(code) <= INVITE_CODE_MAX:
        raise ValidationError("invite_code length is out of range", field="invite_code",
                              expected=f"length {INVITE_CODE_MIN}..{INVITE_CODE_MAX}")
    return code


def _upsert(key: str, value: str, actor_id) -> None:
    """幂等 upsert 一行设置（**不 commit**，由路由统一提交）。"""
    row = get_row(key)
    if row is None:
        db.session.add(AppSetting(key=key, value=value, updated_by_id=actor_id))
    else:
        row.value = value
        row.updated_by_id = actor_id


def set_registration_settings(changes: dict, actor_id: int) -> dict:
    """按需 upsert 注册设置（**不 commit**）；返回实际写入的 {key: value}。

    仅识别注册表里的三个键。值的**类型**已由路由层的 `validation.want_*` 校验过，
    这里只做业务约束（枚举 / 长度 / 字符集）。

    Args:
        changes: 形如 `{"enabled": bool, "invite_code": str, "default_role": str}` 的部分更新。
        actor_id: 操作者 user id，写进 updated_by_id。

    Returns:
        实际写入的 `{存储键: 存储值}`；调用方据其是否为空判定 400 `no updatable field`。

    Raises:
        ValidationError: 邀请码越界 / 含空白，或 default_role 不在白名单内。
    """
    written = {}
    if "enabled" in changes:
        value = "true" if changes["enabled"] else "false"
        _upsert(KEY_REGISTRATION_ENABLED, value, actor_id)
        written[KEY_REGISTRATION_ENABLED] = value
    if "invite_code" in changes:
        value = _validate_invite_code(str(changes["invite_code"]).strip())
        _upsert(KEY_REGISTRATION_INVITE_CODE, value, actor_id)
        written[KEY_REGISTRATION_INVITE_CODE] = value
    if "default_role" in changes:
        value = str(changes["default_role"]).strip()
        if value not in SIGNUP_ROLES:
            raise ValidationError("default_role is invalid", field="default_role",
                                  expected=f"one of {sorted(SIGNUP_ROLES)}")
        _upsert(KEY_REGISTRATION_DEFAULT_ROLE, value, actor_id)
        written[KEY_REGISTRATION_DEFAULT_ROLE] = value
    return written


def generate_invite_code(length: int = 10) -> str:
    """用 CSPRNG 生成一个新邀请码，格式化为 `XXXXX-XXXXX`。

    **禁止 `random` 模块**：邀请码是凭据，可预测的凭据等于没有凭据。

    Args:
        length: 字符总数（不含分隔连字符）。

    Returns:
        大写字母 + 数字组成的码，长度恒 ∈ [INVITE_CODE_MIN, INVITE_CODE_MAX]。
    """
    raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))
    half = length // 2
    return f"{raw[:half]}-{raw[half:]}" if half else raw


def verify_invite_code(candidate: str) -> bool:
    """定长比较候选邀请码与当前生效值（`hmac.compare_digest`，规避计时侧信道）。

    输入先 `.strip()`（用户从 IM 里复制常带空格），但**大小写敏感**——邀请码是凭据
    不是标识符，宽松匹配等于缩小密钥空间。

    两侧都先 `.encode("utf-8")` 再比：`compare_digest` 传 str 时**只接受 ASCII**，
    含非 ASCII 字符直接抛 TypeError。本产品界面为中文，用户手打一个中文邀请码
    （或根管理员把邀请码设成中文）都会让这个公开端点 500——`/auth/signup` 的第一
    原则是「任何输入都不 500」。字节比较对 ASCII 输入的行为逐字节不变。
    """
    expected = get_registration_settings()["invite_code"]
    return hmac.compare_digest((candidate or "").strip().encode("utf-8"),
                               expected.encode("utf-8"))


def is_reserved_username(username: str) -> bool:
    """该用户名是否被系统保留（当前只有 `ROOT_ADMIN_USERNAME` 一个，§7 R-15）。

    两条注册路径（`POST /auth/signup` 与 `POST /api/users`）必须共用本判据，
    不得各写一份——否则堵住一条、漏掉另一条，抢注提权路径依然敞着。

    比较用 `casefold()`：SQLite 的 username 唯一索引是大小写敏感的，`Admin` 能建出来，
    而 `ensure_root_admin` 按精确名查找不到它——但它在人眼里就是管理员，
    仍然是一次社工面上的风险。
    """
    reserved = str(current_app.config.get("ROOT_ADMIN_USERNAME", "")).strip()
    if not reserved:
        return False
    return (username or "").strip().casefold() == reserved.casefold()
