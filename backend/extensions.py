"""扩展实例化（§3.2 backend/extensions.py）。

在这里创建 SQLAlchemy 与 JWTManager 的单例，采用延迟 init_app 模式，
避免与 create_app 工厂之间产生循环 import。
"""
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()
jwt = JWTManager()


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """开启 SQLite 外键约束（Phase-2 §2.8-2）。

    让既有真实外键（reporter_id / owner_id / related_requirement_id / project_id）
    在 DB 层生效；多态 assignee / comment 仍靠应用层校验，语义不变。

    【R-05】监听须**限 SQLite 方言**：对非 SQLite 连接（未来 Postgres）发
    `PRAGMA foreign_keys` 会报错，故按 dbapi 模块判别，仅对 sqlite3 连接执行。
    """
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def utcnow() -> datetime:
    """返回不带 tzinfo 的 UTC 当前时间。

    统一时间来源：以 UTC 存储、去掉 tzinfo（SQLite DateTime 列存 naive），
    to_dict 输出时再补 'Z' 表示 UTC，避免各处 datetime.utcnow() 的弃用告警。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
