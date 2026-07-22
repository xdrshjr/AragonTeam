"""SeedRecord 模型（data-persistence-and-seed-slimming §5.2 seed_records 表）。

本轮**唯一新增表**（additive，`db.create_all()` 首启自动建，零新增列 →
`services/schema_sync.py::ADDITIVE_COLUMNS` 无需登记，与 CLAUDE.md 的硬约束一致）。

存在的理由只有一个：**让每一条示例数据自带出身证明**。演示数据与用户真实数据在
库里此前没有任何可区分的标记，「清演示数据」这件事因此无法安全实现——清理工具只能
靠内容指纹去猜，猜错就是不可逆的误删。本表把「这一行是 seed 写的」登记下来，
`tools/purge_demo_data.py` 据此精确定位，而不必对没有登记的行做任何推定。

**不建真外键**（§5.2）：`entity_type` 是多态判别列，SQLite 无法为多态引用建约束；
且真外键会让「用户删掉示例需求」这一完全合法的操作被外键挡住。孤儿登记由 purge
工具顺带清理（幂等）。

**不暴露给任何 REST 端点**：内部出身元数据，没有任何 UI 需要它。
"""
from extensions import db, utcnow

# 当前 seed 契约版本。seed.py 每次改写入内容都应递增，便于日后按版本区分批次。
# 【version-plan-hierarchy §4.6 评审 P2-B】seed 新增 1 版本 + 1 计划 → 递增到 "3"。
SEED_VERSION = "3"

# 可登记的实体类别（与各表的多态命名保持单数一致）。
# 【version-plan-hierarchy §4.6 评审 P2-A】追加 version / plan：`SeedRecord.mark` 实测**不做**
# 白名单校验，故并非「不加会被拒绝」；追加的真实理由是让本白名单保持「可登记类别」的单一
# 真相，并与 tools/purge_demo_data.py::_entity_models 的登记**一一对应**——两处任缺其一，
# 版本 / 计划要么变新孤岛，要么被 purge 的 _prune_orphan_seed_records 误判为孤儿删掉登记。
SEED_ENTITY_TYPES = (
    "user", "agent", "project", "version", "plan", "requirement", "bug",
    "comment", "activity", "notification",
)


class SeedRecord(db.Model):
    __tablename__ = "seed_records"

    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(32), nullable=False, index=True)
    entity_id = db.Column(db.Integer, nullable=False)
    seed_version = db.Column(db.String(16), nullable=False, default=SEED_VERSION)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    # 同一实体只登记一次；purge 的孤儿清理与 seed 的重复写入都依赖此约束收敛。
    __table_args__ = (
        db.UniqueConstraint("entity_type", "entity_id", name="uq_seed_records_entity"),
    )

    @staticmethod
    def mark(entity_type: str, entity_id: int) -> "SeedRecord":
        """登记一条种子行的出身（**不 commit**，由调用方事务统一提交）。

        Args:
            entity_type: 实体类别，取值见 SEED_ENTITY_TYPES。
            entity_id: 实体主键；调用方须保证已 flush 拿到真实 id。

        Returns:
            新建的 SeedRecord 实例（已 add 进 session）。
        """
        record = SeedRecord(entity_type=entity_type, entity_id=entity_id,
                            seed_version=SEED_VERSION)
        db.session.add(record)
        return record

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "seed_version": self.seed_version,
        }
