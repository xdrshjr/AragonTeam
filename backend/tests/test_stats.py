"""/api/stats 契约与项目过滤（scale-and-project-scope §2.4③）。

覆盖点（对应 spec §3.2）：
① 顶层键集与现网一致（契约回归）；② `?project_id=` 下 total/by_status 只计该项目；
③ agents / members / activities_this_week **不随** project_id 变化；
④ by_status 覆盖全部 column_keys 且缺省 0；⑤ `?project_id=abc` → 400。
"""
from extensions import db
from models.project import Project
from services import workflow

TOP_LEVEL_KEYS = {
    "requirements", "bugs", "agents", "members",
    "activities_this_week", "recent_activities",
}


def _new_project(app, key="S2", name="统计项目"):
    with app.app_context():
        p = Project(name=name, key=key)
        db.session.add(p)
        db.session.commit()
        return p.id


def test_stats_top_level_keys_unchanged(client, auth):
    """① 响应键集是对外契约，前端 lib/types.ts::Stats 依赖之。"""
    r = client.get("/api/stats", headers=auth("pm"))
    assert r.status_code == 200
    assert set(r.get_json().keys()) == TOP_LEVEL_KEYS


def test_by_status_covers_all_columns_with_zero_default(client, auth):
    """④ by_status 恒覆盖全部列 key，无单的列为 0（前端分布条据此渲染）。"""
    body = client.get("/api/stats", headers=auth("pm")).get_json()
    assert set(body["requirements"]["by_status"]) >= set(workflow.column_keys("requirement"))
    assert set(body["bugs"]["by_status"]) >= set(workflow.column_keys("bug"))
    assert body["requirements"]["by_status"]["done"] == 0


def test_stats_filters_by_project(client, auth, data, app):
    """② total 与 by_status 只计该项目。"""
    headers = auth("pm")
    other = _new_project(app)
    client.post("/api/requirements",
                json={"title": "TST-1", "project_id": data["project_id"]}, headers=headers)
    client.post("/api/requirements",
                json={"title": "TST-2", "project_id": data["project_id"]}, headers=headers)
    client.post("/api/requirements", json={"title": "OTHER", "project_id": other},
                headers=headers)
    client.post("/api/requirements", json={"title": "未归属"}, headers=headers)

    scoped = client.get(f"/api/stats?project_id={data['project_id']}",
                        headers=headers).get_json()
    assert scoped["requirements"]["total"] == 2
    assert scoped["requirements"]["by_status"]["new"] == 2

    unassigned = client.get("/api/stats?project_id=none", headers=headers).get_json()
    assert unassigned["requirements"]["total"] == 1

    everything = client.get("/api/stats", headers=headers).get_json()
    assert everything["requirements"]["total"] == 4


def test_global_fields_do_not_follow_project_scope(client, auth, data):
    """③ Agent / 成员 / 本周活动是全局维度，**有意**不随项目过滤（前端须显式标注）。"""
    headers = auth("pm")
    client.post("/api/requirements",
                json={"title": "X", "project_id": data["project_id"]}, headers=headers)
    everything = client.get("/api/stats", headers=headers).get_json()
    scoped = client.get(f"/api/stats?project_id={data['project_id']}",
                        headers=headers).get_json()
    assert scoped["agents"] == everything["agents"]
    assert scoped["members"] == everything["members"]
    assert scoped["activities_this_week"] == everything["activities_this_week"]
    assert scoped["recent_activities"] == everything["recent_activities"]


def test_stats_rejects_malformed_project_id(client, auth):
    """⑤ 坏输入一律 400（与前两轮契约一致），绝不 500、也不静默忽略。"""
    r = client.get("/api/stats?project_id=abc", headers=auth("pm"))
    assert r.status_code == 400
    assert r.get_json()["detail"]["field"] == "project_id"


def test_deleting_ticket_lowers_activities_this_week(client, auth):
    """§2.7 副作用：删单一并删审计 → 本周活动数相应下降（统计不含已不存在实体的活动）。"""
    headers = auth("pm")
    before = client.get("/api/stats", headers=headers).get_json()["activities_this_week"]
    r = client.post("/api/requirements", json={"title": "待删"}, headers=headers)
    created = r.get_json()
    after_create = client.get("/api/stats", headers=headers).get_json()["activities_this_week"]
    assert after_create == before + 1

    assert client.delete(f"/api/requirements/{created['id']}",
                         headers=headers).status_code == 204
    after_delete = client.get("/api/stats", headers=headers).get_json()["activities_this_week"]
    assert after_delete == before
