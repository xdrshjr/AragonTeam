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

    # 这份存量库缺 users 表的**全部** additive 列，故都应被补上
    # （self-service-registration §5.2 新增 is_root / source；
    #  account-security-and-governance §5.1 新增 must_change_password；
    #  login-hardening-and-audit-console §1.2 B-1 新增 last_login_at /
    #  failed_login_count / locked_until，追加在列表末尾故排在最后三位）。
    assert applied == ["users.is_active", "users.is_root", "users.source",
                       "users.must_change_password", "users.last_login_at",
                       "users.failed_login_count", "users.locked_until"]
    # `applied` 只是返回值；这一行才验证 DDL 真的落到了库上，故新列必须同时登记两处。
    assert {"is_active", "is_root", "source", "must_change_password",
            "last_login_at", "failed_login_count", "locked_until"} \
        <= _columns(engine, "users")


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
    # 正向：清单里写的列必须真实存在于模型上。
    # 反向由 test_every_model_column_is_creatable_or_registered 覆盖（见其 docstring）。
    for table_name, column_name in registered:
        table = db.metadata.tables[table_name]
        assert column_name in table.columns, f"{table_name}.{column_name} 不在模型里"


# 「create_all 基线列」= 各表在**引入 schema_sync 之前**就已存在的列集合。它是一份
# 有意冻结的快照：新加的列一律走 ADDITIVE_COLUMNS，故本清单**只减不增**——除非某张表
# 是本轮全新建的（全新表由 create_all 一次建全，存量库上也不存在，无需补列）。
_BASELINE_TABLES_CREATED_WHOLE = frozenset({
    "agents", "requirements", "bugs", "activities", "comments", "notifications",
    "notification_preferences", "seed_records", "documents", "document_versions",
    "document_links", "app_settings",
})
_BASELINE_COLUMNS = {
    "users": {"id", "username", "email", "password_hash", "role", "display_name",
              "avatar_color", "created_at", "updated_at"},
    "projects": {"id", "name", "key", "description", "owner_id",
                 "created_at", "updated_at"},
}


def test_every_model_column_is_creatable_or_registered(app):
    """§7 R-5 **反向**漂移守卫：模型列 ⊆ create_all 基线列 ∪ ADDITIVE_COLUMNS。

    上面那条守卫是单向的（只查「清单里写的列存在吗」），漏登记一列时它**不会红**——
    直到存量 aragon.db 上线后全线 `no such column` → 500。这条把缺口补上：给模型加了列
    却忘了登记进 ADDITIVE_COLUMNS 时，它先于线上事故失败。

    `documents.deleted_at` 这类「表虽在基线里、列却是后加的」情形同样被覆盖：
    整表建全的表不在 _BASELINE_COLUMNS 里，其列一律要求出现在 ADDITIVE_COLUMNS
    或——因为该表本身就是后来新建的——在 _BASELINE_TABLES_CREATED_WHOLE 里。
    """
    registered = {(table, column) for table, column, _ddl in schema_sync.ADDITIVE_COLUMNS}
    for table_name, table in db.metadata.tables.items():
        if table_name in _BASELINE_TABLES_CREATED_WHOLE:
            continue
        baseline = _BASELINE_COLUMNS.get(table_name)
        assert baseline is not None, (
            f"{table_name} 是新表：要么加进 _BASELINE_TABLES_CREATED_WHOLE（全新表，"
            f"create_all 一次建全），要么在 _BASELINE_COLUMNS 里冻结它的基线列")
        for column in table.columns:
            assert column.name in baseline or (table_name, column.name) in registered, (
                f"{table_name}.{column.name} 既不在 create_all 基线里，也没登记进 "
                f"ADDITIVE_COLUMNS —— 存量库上它会让每一次查询 no such column（CLAUDE.md 硬约束）")
