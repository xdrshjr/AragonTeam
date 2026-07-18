"""应用配置（§3.2 backend/config.py）。

Phase-2 §2.5-5 / R-07：全字段改 `os.environ.get`，库 URI **沿用既有
`DATABASE_URL`** 环境变量名（不另引 SQLALCHEMY_DATABASE_URI，避免两个冲突开关）。
新增 SEED_ON_STARTUP、LOGIN_MAX_ATTEMPTS，以及测试专用 TestConfig。
MVP 阶段密钥内置默认值便于开箱即用；生产环境应通过环境变量覆盖。
"""
import os
from datetime import timedelta

from sqlalchemy.pool import StaticPool


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


class Config:
    # —— 安全密钥（生产务必用环境变量覆盖）——
    SECRET_KEY = os.environ.get("SECRET_KEY", "aragon-dev-secret-change-me")
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "aragon-dev-jwt-secret-change-me")

    # JWT 有效期（秒）——默认一天，方便本地开发。
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(seconds=_env_int("JWT_ACCESS_TOKEN_EXPIRES", 86400))

    # —— 数据库（沿用既有 DATABASE_URL 名，R-07）——
    _basedir = os.path.abspath(os.path.dirname(__file__))
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(_basedir, "aragon.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # 缓解 SQLite 并发写锁：加大等待超时（§7 风险表）。
    SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"timeout": 15}}

    # —— CORS ——
    CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")

    # —— 登录限流阈值（§2.5-4）——
    LOGIN_MAX_ATTEMPTS = _env_int("LOGIN_MAX_ATTEMPTS", 10)

    # —— 启动时是否 seed（测试关闭并自建 fixture，§2.5-5）——
    SEED_ON_STARTUP = _env_bool("SEED_ON_STARTUP", True)


class TestConfig(Config):
    """pytest 专用（§2.5-5 / R-02）。内存库 + 固定连接池 + 关 seed + 快过期 + 低限流阈。"""

    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    # 【R-02】内存库必须显式固定连接池：整个进程共用同一条连接，
    # 让建表与请求共享连接、表恒可见，规避跨线程 / xdist 的 `no such table`。
    # 覆盖 base 的 connect_args={"timeout":15}（内存库无需 busy-timeout）。
    SQLALCHEMY_ENGINE_OPTIONS = {
        "connect_args": {"check_same_thread": False},
        "poolclass": StaticPool,
    }
    SEED_ON_STARTUP = False
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=30)
    # 阈值调小以便快测 429（【R-03】计数随 app 实例重建，见 services/ratelimit.py）。
    LOGIN_MAX_ATTEMPTS = 3
