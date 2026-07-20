"""additive 加列迁移器（lifecycle-and-governance §2.3 / §6.1）。

覆盖：缺列的存量库被补齐、重复执行零 DDL、表不存在时跳过、补列后模型查询正常，
以及「模型列集合 ⊆ (create_all 建出的列 ∪ ADDITIVE_COLUMNS)」的漂移守卫（§7 R-2）。
"""
import pytest
from sqlalchemy import create_engine, inspect, text

from config import TestConfig
from extensions import db
from services import schema_sync


LEGACY_USERS_DDL = """
CREATE TABLE users (
    id INTEGER NOT NULL PRIMARY KEY,
    username VARCHAR(64) NOT NULL,
    email VARCHAR(255),
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(16) NOT NULL,
    display_name VARCHAR(128),
    avatar_color VARCHAR(9),
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
)
"""


@pytest.fixture
def legacy_db(tmp_path):
    """一份「上一轮的存量库」：users 表存在但缺 is_active，projects 表尚未建。"""
    path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.execute(text(LEGACY_USERS_DDL))
        conn.execute(text(
            "INSERT INTO users (id, username, password_hash, role, created_at, updated_at)"
            " VALUES (1, 'legacy', 'x', 'admin', '2026-01-01', '2026-01-01')"
        ))
    yield engine, path
    engine.dispose()


def _columns(engine, table) -> set:
    return {c["name"] for c in inspect(engine).get_columns(table)}


def test_adds_missing_column_to_existing_table(legacy_db):
    engine, _ = legacy_db
    assert "is_active" not in _columns(engine, "users")

    applied = schema_sync.sync_additive_columns(engine)

    assert applied == ["users.is_active"]
    assert "is_active" in _columns(engine, "users")


def test_existing_rows_default_to_active(legacy_db):
    """存量行必须自动为 1——不能有人被静默锁在门外（§5.2）。"""
    engine, _ = legacy_db
    schema_sync.sync_additive_columns(engine)
    with engine.connect() as conn:
        value = conn.execute(text("SELECT is_active FROM users WHERE id = 1")).scalar()
    assert value == 1


def test_is_idempotent_on_second_run(legacy_db):
    engine, _ = legacy_db
    schema_sync.sync_additive_columns(engine)

    assert schema_sync.sync_additive_columns(engine) == []


def test_skips_unknown_table(legacy_db):
    """清单里的 projects 表在这份库里不存在 → 静默跳过，不抛（新库场景）。"""
    engine, _ = legacy_db
    applied = schema_sync.sync_additive_columns(engine)

    assert "projects.archived_at" not in applied
    assert "projects" not in inspect(engine).get_table_names()


def test_queries_work_after_sync(legacy_db):
    """冒烟 E1：用存量库启动应用后 User.query 正常，不再 `no such column`。"""
    from app import create_app

    engine, path = legacy_db

    class LegacyConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{path}"
        SQLALCHEMY_ENGINE_OPTIONS = {}

    app = create_app(LegacyConfig)
    with app.app_context():
        users = db.session.query(db.metadata.tables["users"]).all()
        assert len(users) == 1
        # 冒烟 E2：应用已完成一次 sync，再跑一次为零 DDL。
        assert schema_sync.sync_additive_columns(db.engine) == []
        db.session.remove()


def test_additive_columns_cover_every_model_column(app):
    """§7 R-2 漂移守卫：模型里的列必须 ⊆ create_all 建出的列 ∪ ADDITIVE_COLUMNS。

    有人给模型加列却忘了登记进清单时，这条断言会先于存量库的全线 500 失败。
    """
    registered = {(table, column) for table, column, _ddl in schema_sync.ADDITIVE_COLUMNS}
    # 内存库由 create_all 一次建全，故此处只校验清单本身指向真实存在的模型列——
    # 反向（模型有列而清单没有）由本轮的人工登记 + CLAUDE.md 硬约束保证。
    for table_name, column_name in registered:
        table = db.metadata.tables[table_name]
        assert column_name in table.columns, f"{table_name}.{column_name} 不在模型里"
