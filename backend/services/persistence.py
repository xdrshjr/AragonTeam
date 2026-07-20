"""持久化自省与启动期自愈（data-persistence-and-seed-slimming §2.2 / §2.4 / §4.1）。

本模块回答三个此前在代码里无人回答的问题：

1. **数据到底存在哪、存不存得住**——`describe_storage` / `log_storage_summary`。
   库路径由 `config.py` 以 `os.path.dirname(__file__)` 解析为绝对路径，从仓库根还是
   `backend/` 启动都命中同一个文件；但这件事此前只存在于代码里，日志与 `/api/health`
   都不说，用户「数据莫名消失了」时无从自查。
2. **真实生效的 SQLite 落盘参数是什么**——`collect_storage_info`。WAL 在网络盘 /
   只读挂载上会**静默失败**，配置值不等于生效值，故一律 PRAGMA 读回真实值。
3. **崩溃残留的软锁怎么办**——`release_stale_agent_locks`。

【升级判据（§7 R-5），改部署形态前必读】`release_stale_agent_locks` 的正确性建立在
「单进程部署」这一前提上（`app.run(threaded=True)`，README 明示）：进程刚起来时不可能
有正在运行的 autopilot，因此此刻库里的每一个 `busy` 都必然是上次崩溃的残留。
**一旦换成 gunicorn / uwsgi 多 worker**，第二个 worker 启动会误解锁第一个 worker
正在跑的 Agent——届时必须把 `RELEASE_STALE_LOCKS_ON_STARTUP` 置 false，并把 `busy`
软锁改造成带心跳时间戳的租约锁。那是并发模型的改造，不在本模块的能力边界内。
"""
import logging
import os

from sqlalchemy import text

from models.agent import Agent

_logger = logging.getLogger(__name__)

# PRAGMA synchronous 返回**整数**，此表把它翻译回 SQLite 文档里的字面量（§4.1 评审 P1-4）。
_SYNCHRONOUS_LABELS = {0: "OFF", 1: "NORMAL", 2: "FULL", 3: "EXTRA"}

# 自省失败时的降级形状：字段齐全、类型稳定，前端 / 探针无需写分支。
_UNKNOWN_PRAGMAS = {"journal_mode": "unknown", "synchronous": "unknown", "foreign_keys": None}


def describe_storage(uri: str) -> dict:
    """解析数据库 URI，回答「这是什么库、重启后数据还在吗、文件在哪」。

    纯字符串判断，**不打库**——它要能在库不可用时依然给出答案。

    Args:
        uri: SQLAlchemy 数据库 URI，如 `sqlite:////abs/path/aragon.db`。

    Returns:
        `{"backend": "sqlite"|"other", "persistent": bool, "path": str|None}`。
        `persistent` 的判据：URI 以 `sqlite:` 开头，且解析出的文件名非空、不是 `:memory:`。
        非 sqlite 后端一律视为持久化（Postgres/MySQL 不存在内存库这一形态）。
    """
    raw = (uri or "").strip()
    if not raw.startswith("sqlite"):
        return {"backend": "other" if raw else "unknown", "persistent": bool(raw), "path": None}

    # sqlite:///rel.db（相对）/ sqlite:///M:/abs.db（盘符绝对）/ sqlite:////abs.db（POSIX 绝对）
    # / sqlite:///:memory: / sqlite://。POSIX 绝对路径的第四条斜杠是路径的一部分，
    # 不能和「URI 的三条斜杠」一起 strip 掉，否则 /tmp/x.db 会变成相对路径 tmp/x.db。
    body = raw.split("://", 1)[1] if "://" in raw else ""
    path = body[1:] if body.startswith("//") else body.lstrip("/")
    if not path or path == ":memory:":
        return {"backend": "sqlite", "persistent": False, "path": None}
    return {"backend": "sqlite", "persistent": True, "path": os.path.abspath(path)}


def log_storage_summary(app) -> dict:
    """把解析后的绝对库路径 / 是否已存在 / 文件大小写进启动日志。

    这是**唯一**会出现完整文件路径的地方——服务端日志，不经网络暴露；
    `/api/health` 的 storage 块有意不含 path（§2.2）。

    Args:
        app: Flask 应用实例（读 `SQLALCHEMY_DATABASE_URI`，用 `app.logger` 输出）。

    Returns:
        `describe_storage` 的结果，供调用方复用。
    """
    described = describe_storage(app.config.get("SQLALCHEMY_DATABASE_URI", ""))
    path = described["path"]
    if path is None:
        app.logger.info("storage: %s non-persistent (in-memory) —— 重启即失忆",
                        described["backend"])
        return described
    exists = os.path.exists(path)
    size = os.path.getsize(path) if exists else 0
    app.logger.info("storage: sqlite file=%s exists=%s size=%s", path, exists, size)
    return described


def collect_storage_info(app, session) -> dict:
    """读回 SQLite 真实生效的落盘参数，组装 `/api/health` 的 storage 块。

    在 `create_app` 的 app_context 内调用一次并缓存进 `app.config["STORAGE_INFO"]`
    （§4.1 评审 P2-12）：这些值在进程生命周期内不会变，没有理由让每一次探针心跳
    都多打三次库。

    Args:
        app: Flask 应用实例。
        session: 数据库会话（通常是 `db.session`）。

    Returns:
        `{"persistent": bool, "journal_mode": str, "synchronous": str, "foreign_keys": bool|None}`。
        任一 PRAGMA 抛错则整块降级为 `unknown`/`None` 并记 warning——**自省失败绝不
        改变健康检查的成败判据**，HTTP 状态码仍只由 `SELECT 1` 决定（§4.1）。
    """
    persistent = describe_storage(app.config.get("SQLALCHEMY_DATABASE_URI", ""))["persistent"]
    try:
        journal_mode = str(session.execute(text("PRAGMA journal_mode")).scalar()).lower()
        raw_sync = session.execute(text("PRAGMA synchronous")).scalar()
        raw_fk = session.execute(text("PRAGMA foreign_keys")).scalar()
    except Exception:  # noqa: BLE001 —— 自省失败必须降级而非把探针打成 500
        _logger.warning("storage introspection failed; reporting unknown pragmas", exc_info=True)
        return {"persistent": persistent, **_UNKNOWN_PRAGMAS}
    return {
        "persistent": persistent,
        "journal_mode": journal_mode,
        "synchronous": _SYNCHRONOUS_LABELS.get(raw_sync, str(raw_sync)),
        "foreign_keys": bool(raw_fk),
    }


def release_stale_agent_locks(session) -> list[str]:
    """把库里残留的 `busy` Agent 软锁解回 `idle`，返回被解锁的 Agent 名。

    `agents.status='busy'` 是一把**落库的软锁**：进程被 Ctrl+C 杀死时 autopilot 的
    `finally` 不会执行，锁永久留在库里，该 Agent 此后每一次调用都 409，而产品内
    没有任何解锁入口。启动期清一次是最小代价的自愈。

    安全前提与升级判据见模块 docstring——**换多 worker 部署前必须读**。

    Args:
        session: 数据库会话（通常是 `db.session`）；本函数自行 commit。

    Returns:
        被解锁的 Agent 名列表（供启动日志）；无残留时为空列表。
    """
    stale = Agent.query.filter(Agent.status == "busy").all()
    if not stale:
        return []
    names = []
    for agent in stale:
        agent.status = "idle"
        names.append(agent.name)
    session.commit()
    return names
