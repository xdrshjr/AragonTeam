"""Plan 模型（version-plan-hierarchy §4.2 plans 表）。

层级树的第三层：计划挂在版本下（`version_id` 真外键）。`project_id` 是**反范式冗余**，
恒等于 `version.project_id`（§3.3）——目的是让计划列表直接复用 `scope.apply_project_filter`
按项目作用域过滤而不必 join versions。两条不变量消灭漂移：版本 project 不可变（A）、
计划改挂版本须同项目（B），故冗余安全。

计划同样是人工管理的规划物，`status` 自由枚举、不接工单状态机（§2.2）。
"""
from extensions import db, utcnow

# 计划生命周期状态（规划中 / 进行中 / 已完成 / 已归档）。
PLAN_STATUSES = ("planning", "active", "completed", "archived")


class Plan(db.Model):
    __tablename__ = "plans"

    id = db.Column(db.Integer, primary_key=True)
    version_id = db.Column(db.Integer, db.ForeignKey("versions.id"),
                           nullable=False, index=True)
    # 反范式 = version.project_id（§3.3）；建计划时由版本推导写入，此后不因任何操作漂移。
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"),
                           nullable=False, index=True)
    name = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(16), nullable=False, default="planning")
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    # 版本内手动排序（append 落尾）。
    position = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "version_id": self.version_id,
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "start_date": _iso_date(self.start_date),
            "end_date": _iso_date(self.end_date),
            "position": self.position,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


def _iso(dt):
    return dt.isoformat() + "Z" if dt else None


def _iso_date(d):
    return d.isoformat() if d else None
