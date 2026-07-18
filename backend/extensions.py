"""扩展实例化（§3.2 backend/extensions.py）。

在这里创建 SQLAlchemy 与 JWTManager 的单例，采用延迟 init_app 模式，
避免与 create_app 工厂之间产生循环 import。
"""
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager

db = SQLAlchemy()
jwt = JWTManager()


def utcnow() -> datetime:
    """返回不带 tzinfo 的 UTC 当前时间。

    统一时间来源：以 UTC 存储、去掉 tzinfo（SQLite DateTime 列存 naive），
    to_dict 输出时再补 'Z' 表示 UTC，避免各处 datetime.utcnow() 的弃用告警。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
