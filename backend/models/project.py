"""Project 模型（§5 projects 表）。"""
from extensions import db, utcnow


class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    key = db.Column(db.String(16), unique=True, nullable=False)  # 短标识，如 ARA
    description = db.Column(db.Text, nullable=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    # 【lifecycle-and-governance §2.6】归档优于删除：项目一旦有工单挂靠，删除意味着要么
    # 违反外键、要么把工单的 project_id 悄悄置 NULL（错数据 + 丢归属）。非空 = 已归档：
    # 不出现在项目列表默认结果与全局切换器；既有工单完全不受影响。
    # 新增列必须同时登记进 services/schema_sync.py::ADDITIVE_COLUMNS，否则存量库必炸。
    archived_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "key": self.key,
            "description": self.description,
            "owner_id": self.owner_id,
            # 【§2.6】写入侧只接受 `archived` 这个 bool（PATCH 不收时间戳），读出侧
            # 额外给出只读的 archived_at 供 UI 显示「何时归档的」。
            "archived": self.archived_at is not None,
            "archived_at": _iso(self.archived_at),
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


def _iso(dt):
    return dt.isoformat() + "Z" if dt else None
