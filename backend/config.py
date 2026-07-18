"""应用配置（§3.2 backend/config.py）。

MVP 阶段密钥直接内置默认值，便于开箱即用；生产环境应通过环境变量覆盖。
"""
import os


class Config:
    # —— 安全密钥 ——
    # 生产务必用环境变量覆盖；此处默认值仅用于本地开发的开箱即用。
    SECRET_KEY = os.environ.get("SECRET_KEY", "aragon-dev-secret-change-me")
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "aragon-dev-jwt-secret-change-me")

    # JWT 有效期（秒）——一天，方便本地开发。
    from datetime import timedelta
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(days=1)

    # —— 数据库 ——
    # SQLite 落库到 backend/ 目录下的 aragon.db。
    _basedir = os.path.abspath(os.path.dirname(__file__))
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(_basedir, "aragon.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # 缓解 SQLite 并发写锁：加大等待超时（§7 风险表）。
    SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"timeout": 15}}

    # —— CORS ——
    # 放行前端 dev origin；可用环境变量覆盖为逗号分隔的多 origin。
    CORS_ORIGINS = os.environ.get(
        "CORS_ORIGINS", "http://localhost:3000"
    ).split(",")
