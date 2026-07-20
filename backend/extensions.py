"""扩展实例化（§3.2 backend/extensions.py）。

在这里创建 SQLAlchemy 与 JWTManager 的单例，采用延迟 init_app 模式，
避免与 create_app 工厂之间产生循环 import。
"""
import logging
import os
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()
jwt = JWTManager()

# 【data-persistence §2.3 评审 P1-3】模块级 logger，**不是** app.logger / current_app.logger：
# 下面的 connect 监听器挂在全局 Engine 上，触发时机（引擎首连 / 连接池补连 / 后台线程
# 取连接）**不保证**处在 Flask 应用上下文里，取 current_app 会直接抛 RuntimeError。
# 它会被 observability.init_observability 配置的 root handler 接住，输出格式与 app.logger 一致。
_logger = logging.getLogger(__name__)

# PRAGMA synchronous 的合法字面量。取值拼进 SQL，白名单校验不可省（否则即是注入面）。
_SYNCHRONOUS_ALLOWED = ("OFF", "NORMAL", "FULL", "EXTRA")

# 与 Config.SQLALCHEMY_ENGINE_OPTIONS 的 connect_args={"timeout": 15} 对齐（毫秒）。
_BUSY_TIMEOUT_MS = 15000


def _wanted_synchronous() -> str:
    """本进程期望的 `PRAGMA synchronous` 值。

    **只读 `os.environ`**：本函数在 Flask 之外运行，取不到 `app.config`。
    `config.Config.SQLITE_SYNCHRONOUS` 是文档性镜像，不是这里的读取源（§2.3）。
    非法值静默回落 NORMAL——一个拼错的环境变量不该让整个应用起不来。
    """
    raw = (os.environ.get("SQLITE_SYNCHRONOUS") or "NORMAL").strip().upper()
    return raw if raw in _SYNCHRONOUS_ALLOWED else "NORMAL"


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """每条新 SQLite 连接上设置外键与持久化相关 PRAGMA。

    - `foreign_keys=ON`（Phase-2 §2.8-2）：让既有真实外键（reporter_id / owner_id /
      related_requirement_id / project_id）在 DB 层生效；多态 assignee / comment 仍靠
      应用层校验，语义不变。
    - `journal_mode=WAL`（data-persistence §2.3）：崩溃安全 + 读不阻塞写。
    - `synchronous`（默认 NORMAL）：WAL + NORMAL 下进程崩溃不丢数据，仅极端断电可能
      丢最后一个事务；`SQLITE_SYNCHRONOUS=FULL` 可回到每次提交 fsync 的原语义。
    - `busy_timeout`：把「隐含在 connect_args 里」的等待显式化，读代码的人不必再猜。

    【R-05】监听须**限 SQLite 方言**：对非 SQLite 连接（未来 Postgres）发
    `PRAGMA foreign_keys` 会报错，故按 dbapi 模块判别，仅对 sqlite3 连接执行。
    """
    if not dbapi_connection.__class__.__module__.startswith("sqlite3"):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        # 内存库无文件、无 WAL 可言。判别方式**不猜 URI**，而是查连接自己的事实：
        # PRAGMA database_list 的 file 列对内存库是空串。
        row = cursor.execute("PRAGMA database_list").fetchone()
        is_file_backed = bool(row and row[2])
        if is_file_backed:
            # journal_mode 的 execute 会返回一行结果，**必须消费掉**，否则连接持有未读游标。
            applied = cursor.execute("PRAGMA journal_mode=WAL").fetchall()
            mode = str(applied[0][0]).lower() if applied and applied[0] else "unknown"
            if mode != "wal":
                # 网络盘 / 只读挂载上 WAL 会静默失败。降级但**不阻断**：拿不到 WAL
                # 不代表数据存不住，只是并发差一些（§7 R-1）。
                _logger.warning("sqlite journal_mode is %r (WAL unavailable); continuing", mode)
            cursor.execute(f"PRAGMA synchronous={_wanted_synchronous()}")
            cursor.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    finally:
        cursor.close()


def utcnow() -> datetime:
    """返回不带 tzinfo 的 UTC 当前时间。

    统一时间来源：以 UTC 存储、去掉 tzinfo（SQLite DateTime 列存 naive），
    to_dict 输出时再补 'Z' 表示 UTC，避免各处 datetime.utcnow() 的弃用告警。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
