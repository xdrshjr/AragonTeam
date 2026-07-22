"""Version 模型（version-plan-hierarchy §4.1 versions 表）。

层级树的第二层：`Project → Version → Plan → 需求/BUG`。版本挂在项目下（`project_id`
真外键，新表建表期可加），是**人工管理**的规划物，其 `status` 是自由枚举、不接入工单
状态机（`services/workflow.py`），与需求 / BUG 的邻接表状态机互不干涉（§1 / §2.2）。

`released_at` **服务端托管**：`status` 转入 `released` 时由路由 stamp `utcnow()`、转出时
清空，客户端不可写（§4.1 评审 P1-C，仿 `models/project.py` 的 `archived` 只暴露 bool、
不让客户端写时间戳）。
"""
from extensions import db, utcnow

# 版本生命周期状态（规划中 / 进行中 / 已发布 / 已归档）。自由枚举，无 can_transition 裁决。
VERSION_STATUSES = ("planning", "active", "released", "archived")


class Version(db.Model):
    __tablename__ = "versions"

    id = db.Column(db.Integer, primary_key=True)
    # 所属项目；创建后不可变（§3.3 不变量 A）。真外键 → 删项目前须先清空其版本
    # （lifecycle.project_references 计版本，§3.5）。
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"),
                           nullable=False, index=True)
    name = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(16), nullable=False, default="planning")
    target_date = db.Column(db.Date, nullable=True)
    # 实际发布时间；服务端托管（随 status 进出 released 由路由 stamp / 清空）。
    released_at = db.Column(db.DateTime, nullable=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    # 项目内手动排序（append 落尾，见 services/hierarchy.next_sort_position）。
    position = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "target_date": _iso_date(self.target_date),
            "released_at": _iso(self.released_at),
            "owner_id": self.owner_id,
            "position": self.position,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


def _iso(dt):
    return dt.isoformat() + "Z" if dt else None


def _iso_date(d):
    """DATE 列序列化为 `YYYY-MM-DD`（无时区、无 Z——它不是时刻）。"""
    return d.isoformat() if d else None
