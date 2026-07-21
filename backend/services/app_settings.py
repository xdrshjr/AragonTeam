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
from datetime import datetime, timezone
from typing import NamedTuple

from flask import current_app

from extensions import db, utcnow
from models.app_setting import AppSetting
from models.user import User
from services.validation import ValidationError

KEY_REGISTRATION_ENABLED = "registration.enabled"
KEY_REGISTRATION_INVITE_CODE = "registration.invite_code"
KEY_REGISTRATION_DEFAULT_ROLE = "registration.default_role"
# 【login-hardening-and-audit-console §1.1 A-1】邀请码的生命周期三键（零结构变更）。
KEY_INVITE_EXPIRES_AT = "registration.invite_expires_at"
KEY_INVITE_MAX_USES = "registration.invite_max_uses"
KEY_INVITE_ISSUED_AT = "registration.invite_issued_at"

REGISTRATION_KEYS = (
    KEY_REGISTRATION_ENABLED,
    KEY_REGISTRATION_INVITE_CODE,
    KEY_REGISTRATION_DEFAULT_ROLE,
    KEY_INVITE_EXPIRES_AT,
    KEY_INVITE_MAX_USES,
    KEY_INVITE_ISSUED_AT,
)

# max_uses 的上界不是安全约束，是防手滑：一个天文数字对后端无害，但会让前端用量进度条
# 渲染成一条永远为零的线。
INVITE_MAX_USES_CEIL = 10000

# 自助注册**永远**不能产出 admin：一个知道邀请码的人不该能直接成为管理员。
SIGNUP_ROLES = ("member", "pm")

INVITE_CODE_MIN, INVITE_CODE_MAX = 4, 64
# 人类可口述、可手抄：去掉 0/O/1/l/I 等易混字符。
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

# 【account-security-and-governance §2.4 D-2】内置保留用户名表（casefold 后比较）。
# 与 RESERVED_USERNAMES 配置项和 ROOT_ADMIN_USERNAME 取并集，见 reserved_usernames()。
_BUILTIN_RESERVED = ("admin", "administrator", "root", "system", "aragon",
                     "api", "support", "security", "me", "null", "undefined")

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


def _coerce_datetime(raw):
    """解释一个 ISO8601 naive UTC 串；无行 / 空串 / 脏值 → None（+ warning）。

    容忍尾部 `Z`（`to_dict` 输出恒补 Z）。带时区偏移的输入归一到 naive UTC，
    与 `extensions.utcnow()` 同一口径——否则 aware 与 naive 相比会 TypeError。
    **回落方向是 None（永不过期）**：一个拼错的失效时刻不该把全站注册闸死（A-6）。
    """
    if raw is None:
        return None
    value = str(raw).strip()
    if value == "":
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] if value.endswith("Z") else value)
    except ValueError:
        _warn("app_settings: unparsable datetime %r, falling back to None", raw)
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _coerce_expires_at(raw):
    """`registration.invite_expires_at` 的读侧解释；见 `_coerce_datetime`。"""
    return _coerce_datetime(raw)


def _coerce_max_uses(raw) -> int:
    """解释 `registration.invite_max_uses`；无行 / 脏值 / 负数 → 0（不限）+ warning。

    **回落方向是「不限制」**（A-6）：一个拼错的额度值不该把全站注册闸死。
    """
    if raw is None:
        return 0
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        _warn("app_settings: unparsable %s=%r, falling back to 0",
              KEY_INVITE_MAX_USES, raw)
        return 0
    if value < 0:
        _warn("app_settings: negative %s=%r, falling back to 0",
              KEY_INVITE_MAX_USES, raw)
        return 0
    return value


def _settings_from_rows(rows: dict) -> dict:
    """把一次取回的原始行 dict 解析成生效设置（5 键），**不再查库**。

    check_invite_code 与 get_registration_settings 共用它，让「每次请求打**一次**
    唯一索引查询」这条模块硬约定继续为真（§1.1 A-2 末段）。
    """
    return {
        "enabled": _coerce_enabled(rows.get(KEY_REGISTRATION_ENABLED)),
        "invite_code": _coerce_invite_code(rows.get(KEY_REGISTRATION_INVITE_CODE)),
        "default_role": _coerce_default_role(rows.get(KEY_REGISTRATION_DEFAULT_ROLE)),
        # 【login-hardening-and-audit-console §1.1 A-4】期限与额度**已解析成 Python 类型**，
        # 序列化侧必须逐个走 _iso()，禁止 {**settings} 直出 JSON（评审 P0-1）。
        "invite_expires_at": _coerce_expires_at(rows.get(KEY_INVITE_EXPIRES_AT)),
        "invite_max_uses": _coerce_max_uses(rows.get(KEY_INVITE_MAX_USES)),
    }


def get_registration_settings() -> dict:
    """返回生效的注册设置（5 键）。

    「无行 = 用配置默认」——与 notification_prefs 的「无行 = 启用」同一模式，存量库零回填。
    `default_role` 的白名单约束见模块 docstring 第 3 条；`invite_expires_at`（datetime|None）
    与 `invite_max_uses`（int, 0=不限）由 login-hardening-and-audit-console §1.1 A-4 引入。
    """
    return _settings_from_rows(_stored_values())


def invite_issued_at(rows: dict):
    """当前邀请码的生效时刻；None 表示「自古以来」（= 统计全部 signup 账号）。

    三级回落链，**不得有静默放行分支**（§1.1 A-3）：
    1. 显式键 `registration.invite_issued_at` 解析成功即用它；
    2. 存量库无该键 → 用码行的 `updated_at` 作锚点；
    3. 全新库连码行都没有 → None（最严格口径：统计全部 signup 账号）。

    `rows` 由调用方 `_stored_values()` 取一次后传入，避免热路径二次往返。
    """
    parsed = _coerce_datetime(rows.get(KEY_INVITE_ISSUED_AT))
    if parsed is not None:
        return parsed
    row = get_row(KEY_REGISTRATION_INVITE_CODE)
    if row is not None:
        return row.updated_at
    return None


def invite_uses(rows: dict) -> int:
    """当前这个邀请码已经注册出多少个**仍在库里**的账号（派生值，非计数器）。

    口径是「现存账号数」而非「历史使用次数」：一个注册后又被 purge 掉的账号会让额度
    「退回来」。这在本产品里可接受——purge 是需要人手动 `--apply` 的运维动作，
    不是用户可触发的路径（§7 R-5）。派生值天然规避了计数器的读-改-写竞态与
    与真实用户数漂移两个失败模式（§1.1 A-2）。

    Args:
        rows: `_stored_values()` 的返回，供 `invite_issued_at` 复用，避免二次往返。
    """
    issued = invite_issued_at(rows)
    q = User.query.filter(User.source == "signup")
    if issued is not None:
        q = q.filter(User.created_at >= issued)
    return q.count()


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


def _ensure_invite_anchor(actor_id) -> None:
    """额度/期限第一次被设置时补写生效锚点（**幂等**：已有行则不动；§1.1 A-5 步骤 ②）。

    没有这一步，「只设了额度、从没改过码」的库会一直依赖 `invite_issued_at` 的第 2 级
    回落，而回落读的那个 `updated_at` 不归本模块管——另一个根管理员把码原样再保存一次
    就会让它前移、额度静默归零（评审 P1-1）。
    """
    if get_row(KEY_INVITE_ISSUED_AT) is None:
        _upsert(KEY_INVITE_ISSUED_AT, utcnow().isoformat(), actor_id)


def _parse_expires_input(value: str):
    """把 PATCH 传入的失效时刻串解析成 naive UTC datetime；非法抛 ValueError。"""
    dt = datetime.fromisoformat(value[:-1] if value.endswith("Z") else value)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


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
        # 【login-hardening-and-audit-console §1.1 A-5 / 评审 P1-1】**值判等即整条短路**：
        # 值没变就不写 value、不写 updated_by_id，行根本不弄脏，onupdate 不动 updated_at。
        # 这比「加一个显式 issued_at 键」更根本——不弄脏行才是止血。值真的变了才写
        # issued_at（额度归零）与码行。
        if value != get_registration_settings()["invite_code"]:
            _upsert(KEY_INVITE_ISSUED_AT, utcnow().isoformat(), actor_id)
            _upsert(KEY_REGISTRATION_INVITE_CODE, value, actor_id)
            written[KEY_REGISTRATION_INVITE_CODE] = value
    if "default_role" in changes:
        value = str(changes["default_role"]).strip()
        if value not in SIGNUP_ROLES:
            raise ValidationError("default_role is invalid", field="default_role",
                                  expected=f"one of {sorted(SIGNUP_ROLES)}")
        _upsert(KEY_REGISTRATION_DEFAULT_ROLE, value, actor_id)
        written[KEY_REGISTRATION_DEFAULT_ROLE] = value
    if "expires_at" in changes:
        raw = changes["expires_at"]
        if raw is None or str(raw).strip() == "":
            stored = ""                              # 清除 = 永不过期
        else:
            try:
                parsed = _parse_expires_input(str(raw).strip())
            except ValueError:
                raise ValidationError("expires_at is not a valid datetime",
                                      field="expires_at", expected="ISO 8601 datetime")
            # 【§1.1 A-5】过去的时刻是 400 而不是「立刻失效」：98% 是时区搞错了，
            # 想立刻废码已有关开关 / rotate 两个更直白的入口。
            if parsed <= utcnow():
                raise ValidationError("expires_at must be in the future",
                                      field="expires_at", expected="a future datetime")
            stored = parsed.isoformat()
        _ensure_invite_anchor(actor_id)              # 额度语义诞生的那一刻补锚点
        _upsert(KEY_INVITE_EXPIRES_AT, stored, actor_id)
        written[KEY_INVITE_EXPIRES_AT] = stored
    if "max_uses" in changes:
        value = int(changes["max_uses"])
        if not 0 <= value <= INVITE_MAX_USES_CEIL:
            raise ValidationError("max_uses is out of range", field="max_uses",
                                  expected=f"0..{INVITE_MAX_USES_CEIL}")
        stored = str(value)
        _ensure_invite_anchor(actor_id)
        _upsert(KEY_INVITE_MAX_USES, stored, actor_id)
        written[KEY_INVITE_MAX_USES] = stored
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


class InviteCheck(NamedTuple):
    """`check_invite_code` 的结果。`reason` ∈ ok / mismatch / expired / exhausted。"""
    ok: bool
    reason: str


def check_invite_code(candidate: str) -> InviteCheck:
    """校验候选邀请码：定长比较 + 期限 + 额度（login-hardening-and-audit-console §1.1 A-4）。

    **判定顺序是契约的一部分**：mismatch → expired → exhausted。理由：expired / exhausted
    只在候选码与真码一致之后才可能返回——持码人本就知道码，告诉他「过期了」不泄露任何
    东西，反而是他唯一能据以行动的信息；不持码人恒得到 mismatch，可区分性为零。倒过来
    （先查过期）会让任何人都能探测出「这个站点的邀请码已经过期」，那才是泄露。

    两侧都先 `.encode("utf-8")` 再比：`compare_digest` 传 str 时**只接受 ASCII**，含非
    ASCII 字符直接抛 TypeError。本产品界面为中文，用户手打一个中文邀请码都会让这个公开
    端点 500——`/auth/signup` 的第一原则是「任何输入都不 500」。字节比较对 ASCII 输入的
    行为逐字节不变（上一轮 F-1 的回归约束，不得在重构中丢失）。

    输入先 `.strip()`（用户从 IM 里复制常带空格），但**大小写敏感**——邀请码是凭据
    不是标识符，宽松匹配等于缩小密钥空间。
    """
    rows = _stored_values()                 # 唯一一次 _stored_values() 往返
    settings = _settings_from_rows(rows)
    if not hmac.compare_digest((candidate or "").strip().encode("utf-8"),
                               settings["invite_code"].encode("utf-8")):
        return InviteCheck(False, "mismatch")
    expires = settings["invite_expires_at"]                 # datetime | None
    if expires is not None and utcnow() >= expires:
        return InviteCheck(False, "expired")
    max_uses = settings["invite_max_uses"]                  # int, 0 = 不限
    if max_uses > 0 and invite_uses(rows) >= max_uses:
        return InviteCheck(False, "exhausted")
    return InviteCheck(True, "ok")


def verify_invite_code(candidate: str) -> bool:
    """**保留的稳定别名**（CLAUDE.md §五：对外暴露的接口更名等同破坏性变更）。"""
    return check_invite_code(candidate).ok


def invite_status(settings: dict, uses: int) -> str:
    """邀请码的当前状态：disabled / expired / exhausted / active（§2.4）。

    由服务端算一次下发——让前端拿 `expires_at` 与本地时钟比会重蹈时钟漂移坑，而
    `exhausted` 的判据（要数用户）在前端根本拿不到。`disabled`（开关关闭）优先级最高。

    Args:
        settings: `get_registration_settings()` 的 5 键返回值。
        uses: `invite_uses()` 的结果。
    """
    if not settings["enabled"]:
        return "disabled"
    expires = settings["invite_expires_at"]
    if expires is not None and utcnow() >= expires:
        return "expired"
    max_uses = settings["invite_max_uses"]
    if max_uses > 0 and uses >= max_uses:
        return "exhausted"
    return "active"


def reserved_usernames() -> frozenset:
    """当前生效的保留名集合（全部 casefold 后比较）。

    = 内置表 ∪ `RESERVED_USERNAMES` 配置项 ∪ `{ROOT_ADMIN_USERNAME}`。
    空配置项、空白项一律忽略；空的 `ROOT_ADMIN_USERNAME` 不入集（与现状一致）。

    `me` / `null` / `undefined` 在内置表里，是因为它们是前端路由与 JSON 序列化里最典型的
    歧义源（`/api/users/me` 这类路径在未来一定会有人想加）。现在拦下的成本是零。

    Returns:
        casefold 后的保留名 frozenset。
    """
    names = set(_BUILTIN_RESERVED)
    extra = str(current_app.config.get("RESERVED_USERNAMES", "") or "")
    names.update(part.strip().casefold() for part in extra.split(",") if part.strip())
    root = str(current_app.config.get("ROOT_ADMIN_USERNAME", "")).strip()
    if root:
        names.add(root.casefold())
    return frozenset(names)


def is_reserved_username(username: str) -> bool:
    """该用户名是否被系统保留（account-security-and-governance §2.4 D-2）。

    三条建号路径（`POST /auth/signup`、`POST /api/users`、`POST /auth/register`）必须
    共用本判据，不得各写一份——否则堵住一条、漏掉另一条，抢注提权路径依然敞着
    （上一轮 register 就漏了这道守卫，本轮由 services/accounts.py 的合并动作补上）。

    比较用 `casefold()`：SQLite 的 username 唯一索引是大小写敏感的，`Admin` 能建出来，
    而 `ensure_root_admin` 按精确名查找不到它——但它在人眼里就是管理员，
    仍然是一次社工面上的风险。

    **只作用于「新建账号」这一刻**，不追溯任何存量行：一个叫 `system` 的既有账号继续
    正常登录、正常被改资料。
    """
    candidate = (username or "").strip().casefold()
    if not candidate:
        return False
    return candidate in reserved_usernames()
