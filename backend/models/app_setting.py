"""AppSetting 键值表（self-service-registration §2.2 B-1 / §5.1）——本轮唯一新增表。

【为什么是键值表而不是逐个加列】本轮只需要三个设置项，且未来一定还会有第四第五个
（SMTP、站点名、默认项目…）。逐个加列意味着每次都要动 `services/schema_sync.py`，
键值表把这类演进一次性压平。**代价**是失去列级类型约束，故类型收敛到
`services/app_settings.py` 的键注册表里——路由层永远不直接读本表。

`updated_by_id` **不建 DB 外键**：与 comments / activities / seed_records 的一贯做法一致，
删用户不应该被一行设置记录挡住；展示时按 id 软解析，解析不到就降级为占位。
"""
from extensions import db, utcnow


class AppSetting(db.Model):
    __tablename__ = "app_settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    # 一律存字符串，类型由服务层解释（脏值一律回落配置默认 + warning，绝不抛）。
    value = db.Column(db.Text, nullable=True)
    updated_by_id = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)
