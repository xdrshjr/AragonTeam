"""User 模型（§5 users 表）。"""
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db, utcnow

# 角色枚举：与 §2.4 RBAC 一致。
ROLES = ("admin", "pm", "member")


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
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }

    def summary(self) -> dict:
        """指派/时间线渲染用的精简概要。"""
        return {
            "type": "user",
            "id": self.id,
            "name": self.display_name or self.username,
            "avatar_color": self.avatar_color,
        }


def _iso(dt):
    return dt.isoformat() + "Z" if dt else None
