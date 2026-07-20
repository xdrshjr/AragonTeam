"""启动期 additive schema 同步（lifecycle-and-governance §2.3）。

`db.create_all()` 只建**不存在的表**，对已存在的表不加任何列。项目无 Alembic，
因此模型每新增一列，存量 aragon.db 上的每一次查询都会 `no such column` → 500。
本模块以最保守的方式补上这条缝：**只做加列**，幂等，可重复执行，且不依赖
任何新第三方依赖（inspect 来自 SQLAlchemy 本体）。

**能力边界（务必遵守）**：只支持 ADD COLUMN。改类型 / 改约束 / 删列 / 改表名 /
数据回填一律**不在**本机制内——它们需要真正的迁移工具（Alembic）与人工审阅，
擅自扩展本模块会制造「看起来有迁移、其实静默错数据」的更坏局面（见 spec §7 R-3）。
**何时必须换成 Alembic**：出现第一个「改类型 / 改约束 / 需要数据回填」的需求时。
"""
from sqlalchemy import inspect, text

# (表名, 列名, DDL 片段)。DDL 只允许使用 SQLite 与 PostgreSQL 双方言都接受的
# 保守类型 + 常量默认值：SQLite 的 ADD COLUMN 要求默认值是常量（非表达式）。
#
# 【硬约束】models/ 里每新增一列，必须在此登记一条，否则存量库全线 500（spec §7 R-2）。
ADDITIVE_COLUMNS: list[tuple[str, str, str]] = [
    ("users", "is_active", "BOOLEAN NOT NULL DEFAULT 1"),
    ("projects", "archived_at", "DATETIME"),
    # document-lifecycle-depth §5.1：文档软删除两列。默认 NULL，存量行零回填。
    # `deleted_by_id` 在模型侧同样**不建外键**——两条建表路径必须产出同一个 schema。
    ("documents", "deleted_at", "DATETIME"),
    ("documents", "deleted_by_id", "INTEGER"),
]


def sync_additive_columns(engine) -> list[str]:
    """补齐 ADDITIVE_COLUMNS 中缺失的列，返回实际执行的 "表.列" 列表（供日志）。

    - 表不存在 → 跳过（create_all 会建全新表，无需补列）。
    - 列已存在 → 跳过（幂等：正常启动恒返回 []）。
    - 每条 ALTER 各自执行；任一条失败**向上抛出**，绝不吞掉——一个补不上的列
      会让整个应用处于「模型与库不一致」的状态，宁可启动失败也不能带病运行
      （CLAUDE.md 五：错误显式传播）。

    Args:
        engine: SQLAlchemy Engine（通常是 `db.engine`）。

    Returns:
        本次实际执行了 ALTER 的 "表.列" 名列表；无需补列时为空列表。

    Raises:
        sqlalchemy.exc.SQLAlchemyError: 任一 ALTER 执行失败时原样抛出。
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    # 【实现要点】先把每张表的现有列集合一次性快照下来，循环里只读快照、改快照。
    # SQLAlchemy 的 Inspector 带 info_cache，DDL 之后同一实例的 get_columns 可能返回
    # 陈旧结果；且同一张表若在清单里有两列待补，第二次读也不该再打一次库。
    snapshot: dict[str, set[str]] = {
        t: {c["name"] for c in inspector.get_columns(t)} for t in existing_tables
    }
    applied: list[str] = []
    with engine.begin() as conn:
        for table, column, ddl in ADDITIVE_COLUMNS:
            if table not in snapshot or column in snapshot[table]:
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            snapshot[table].add(column)
            applied.append(f"{table}.{column}")
    return applied
