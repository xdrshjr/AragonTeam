"""User 模型（§5 users 表）。"""
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db, utcnow

# 角色枚举：与 §2.4 RBAC 一致。
ROLES = ("admin", "pm", "member")

# 账号来源（self-service-registration §2.1 A-2）。**仅供治理展示，不参与任何鉴权判定**——
# 一旦有代码按 source 分配权限，它就从一条审计线索变成了第二套角色系统。
# seed：首次启动的示例账号；admin：管理员代建；signup：凭邀请码自助注册；root：启动期兜底建出的根管理员。
USER_SOURCES = ("seed", "admin", "signup", "root")


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(16), nullable=False, default="member")
    display_name = db.Column(db.String(128), nullable=True)
    # seed 时分配的头像底色（hex），前端渲染人类首字母头像用。
    avatar_color = db.Column(db.String(9), nullable=True)
    # 【lifecycle-and-governance §2.5】停用而非删除：users.id 被 requirements/bugs.reporter_id
    # 与 projects.owner_id 真外键引用，硬删会 IntegrityError；且删除等于销毁审计轨迹。
    # 停用保留全部历史，只切断「能登录」与「能被指派」两种**面向未来**的能力。
    # 新增列必须同时登记进 services/schema_sync.py::ADDITIVE_COLUMNS，否则存量库必炸。
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default="1")
    # 【self-service-registration §2.1 A-2】根管理员标记。全库**至多一行为真**，
    # 由 services/bootstrap.py::ensure_root_admin 维护——配置文件是它的唯一真相。
    is_root = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    # 账号来源，取值见 USER_SOURCES。默认 'admin'：存量行确实都是管理员建的。
    source = db.Column(db.String(16), nullable=False, default="admin",
                       server_default="admin")
    # 【account-security-and-governance §2.2 B-1】true = 该账号的口令是别人设的
    # （管理员建号 / 管理员重置），本人尚未改过。带此标记的人只能读「我是谁」和改密码，
    # 其余 /api/* 一律 403（services/auth_helpers.py::install_password_gate）。
    # 默认 False：存量行零回填即获得正确语义——他们的口令确实是自己在用的那个。
    must_change_password = db.Column(db.Boolean, nullable=False, default=False,
                                     server_default="0")

    # 【login-hardening-and-audit-console §1.2 B-1】登录闸门三列。默认值都是常量
    # （SQLite ADD COLUMN 的硬性要求），存量行零回填即语义正确：存量用户「从未记录过
    # 登录、没有失败、没有锁定」全部为真。三列必须同时登记进 schema_sync.ADDITIVE_COLUMNS。
    last_login_at = db.Column(db.DateTime, nullable=True)
    failed_login_count = db.Column(db.Integer, nullable=False, default=0,
                                   server_default="0")
    locked_until = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    def set_password(self, password: str) -> None:
        # 【R-06 修复】统一 pbkdf2:sha256，规避 werkzeug 3.x 默认 scrypt 在部分
        # OpenSSL 构建上不可用的问题（跨平台确定可用）。
        self.password_hash = generate_password_hash(password, method="pbkdf2:sha256")

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "role": self.role,
            "display_name": self.display_name or self.username,
            "avatar_color": self.avatar_color,
            # 【§2.5】additive：前端据此渲染「已停用」标记并从指派下拉里过滤。
            "is_active": bool(self.is_active),
            # 【self-service-registration §2.1 A-2】additive：团队页据此渲染
            # 「根管理员」/「自助注册」徽章并禁用危险操作。**summary() 有意不加这两项**：
            # 指派选择器与时间线不关心谁是根管理员，多传只会让 AssigneeSummary 变胖。
            "is_root": bool(self.is_root),
            "source": self.source or "admin",
            # 【account-security-and-governance §2.2 B-1】additive：前端据此把人跳到
            # /force-password。**summary() 同样有意不加**——指派选择器与时间线不关心
            # 这件事，多传只会让 AssigneeSummary 变胖。
            "must_change_password": bool(self.must_change_password),
            # 【login-hardening-and-audit-console §1.2 B-7】additive：团队页据此渲染
            # 「已锁定」徽章 + 「最后登录」列。**is_locked 由服务端判定**，前端不拿
            # locked_until 自己跟本地时钟比——用户机器时间可能偏几分钟，那会让已解锁的
            # 账号在界面上还显示着锁。**failed_login_count 有意不进 API**：GET /api/users 是
            # jwt_required() 而非 admin-only，全员可读，「某人错了 7 次」对已拿到低权限凭据
            # 的攻击者是有用的侦察信息。summary() 同样一个键都不加。
            "last_login_at": _iso(self.last_login_at),
            "locked_until": _iso(self.locked_until) if self.is_locked() else None,
            "is_locked": self.is_locked(),
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }

    def is_locked(self) -> bool:
        """此刻是否处于登录锁定期。None / 已过期 locked_until 均为未锁定。

        与 `services/login_guard.py::is_locked` 同一判据，内联在模型里避免
        `to_dict` 反向 import 服务层（models 不依赖 services）。
        """
        return self.locked_until is not None and self.locked_until > utcnow()

    def summary(self) -> dict:
        """指派/时间线渲染用的精简概要。"""
        return {
            "type": "user",
            "id": self.id,
            "name": self.display_name or self.username,
            "avatar_color": self.avatar_color,
            # 【§2.5】additive：一张单的 assignee 被停用后，抽屉与列表要显示灰色
            # 「已停用」而不是若无其事——否则 pm 不知道这张单其实已经没人管。
            "is_active": bool(self.is_active),
        }


def _iso(dt):
    return dt.isoformat() + "Z" if dt else None
