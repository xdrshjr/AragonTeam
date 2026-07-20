"""批量操作（bulk-operations §6.1）。

覆盖：三桶结果（succeeded / skipped / failed）的语义、部分失败不回滚成功项、
逐项行级 RBAC 不被批量旁路、粗粒度角色门禁与单条端点对齐、请求级参数错误仍是整单
4xx、ids 边界（缺失 / 空 / 非整数 / 超上限 / 重复）、以及「顶层永不出现 allowed」
这条前端看板拖拽依赖的不变量。
"""
from extensions import db
from models.activity import Activity
from models.bug import Bug
from models.comment import Comment
from models.notification import Notification
from models.requirement import Requirement
from services.bulk_ops import MAX_BULK_IDS


def _bulk(client, headers, entity="requirements", **payload):
    return client.post(f"/api/{entity}/bulk", json=payload, headers=headers)


# ————————————————————— A. 批量流转 —————————————————————

def test_bulk_move_reports_succeeded_skipped_and_missing_separately(
        client, auth, make_requirement, data):
    """一次请求里三种结局各归各桶，且整体仍是 200（部分成功是批量的常态）。"""
    fresh = make_requirement(title="待流转")
    already = make_requirement(title="已在目标态", assignee=("user", data["member_id"]))

    r = _bulk(client, auth("pm"), ids=[fresh["id"], already["id"], 999999],
              action="move", status="assigned")

    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["succeeded"] == [fresh["id"]]
    assert body["skipped"] == [{"id": already["id"], "reason": "already in target status"}]
    assert body["failed"] == [{"id": 999999, "error": "requirement not found"}]
    assert body["counts"] == {"requested": 3, "succeeded": 1, "skipped": 1, "failed": 1}


def test_bulk_move_rejects_illegal_transition_per_ticket(client, auth, make_requirement):
    """非法迁移是**逐项**失败，detail 带 allowed 供前端提示下一步。"""
    req = make_requirement()

    r = _bulk(client, auth("pm"), ids=[req["id"]], action="move", status="done")

    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["succeeded"] == []
    failed = body["failed"][0]
    assert failed["error"] == "illegal transition"
    assert failed["detail"] == {"from": "new", "to": "done", "allowed": ["assigned"]}


def test_bulk_response_never_exposes_allowed_at_top_level(client, auth, make_requirement):
    """看板拖拽以 `err.allowed` 是否存在分流错误（lifecycle §4.3）——批量恒 200 且
    顶层无 allowed，绝不能误伤那条判据。"""
    req = make_requirement()

    r = _bulk(client, auth("pm"), ids=[req["id"]], action="move", status="done")

    assert "allowed" not in r.get_json()


def test_bulk_move_partial_failure_does_not_roll_back_successes(
        client, auth, app, make_requirement):
    """整批里混进一个不存在的 id，不该把已成功的那张单一起回滚。"""
    req = make_requirement()

    _bulk(client, auth("pm"), ids=[req["id"], 999999], action="move", status="assigned")

    with app.app_context():
        assert db.session.get(Requirement, req["id"]).status == "assigned"


def test_bulk_move_writes_one_activity_per_changed_ticket(
        client, auth, app, make_requirement, data):
    """跳过项不写审计——否则「批量点一下」就会给时间线灌一堆无变化事件。"""
    changed = make_requirement()
    skipped = make_requirement(assignee=("user", data["member_id"]))

    _bulk(client, auth("pm"), ids=[changed["id"], skipped["id"]],
          action="move", status="assigned")

    with app.app_context():
        assert Activity.query.filter_by(entity_type="requirement",
                                        entity_id=changed["id"], action="moved").count() == 1
        assert Activity.query.filter_by(entity_type="requirement",
                                        entity_id=skipped["id"], action="moved").count() == 0


def test_bulk_move_enforces_row_level_rbac_per_ticket(
        client, auth, app, make_requirement, data):
    """member 只能批量推进自己有权管的单；无权的那张是**逐项 403**，不是整单 403。"""
    mine = make_requirement(title="我的", assignee=("user", data["member_id"]))
    others = make_requirement(title="别人的", assignee=("user", data["member2_id"]))

    r = _bulk(client, auth("member"), ids=[mine["id"], others["id"]],
              action="move", status="in_development")

    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["succeeded"] == [mine["id"]]
    assert body["failed"][0]["id"] == others["id"]
    assert body["failed"][0]["error"] == "forbidden"
    with app.app_context():
        assert db.session.get(Requirement, others["id"]).status == "assigned"


def test_bulk_move_rejects_unknown_target_status(client, auth, make_requirement):
    """目标状态是**请求级**参数，错了就是整单 400——改一次输入就能全修好的东西，
    不该被稀释成一张逐项失败清单。"""
    req = make_requirement()

    r = _bulk(client, auth("pm"), ids=[req["id"]], action="move", status="nope")

    assert r.status_code == 400
    assert r.get_json()["error"] == "invalid target status"


# ————————————————————— B. 批量指派 / 取消指派 —————————————————————

def test_bulk_assign_advances_first_column_and_notifies(
        client, auth, app, make_requirement, data):
    a, b = make_requirement(title="A"), make_requirement(title="B")

    r = _bulk(client, auth("pm"), ids=[a["id"], b["id"]], action="assign",
              assignee_type="user", assignee_id=data["member_id"])

    assert r.status_code == 200, r.get_json()
    assert r.get_json()["counts"]["succeeded"] == 2
    with app.app_context():
        for ticket_id in (a["id"], b["id"]):
            row = db.session.get(Requirement, ticket_id)
            assert (row.assignee_type, row.assignee_id) == ("user", data["member_id"])
            assert row.status == "assigned"          # new → assigned 自动迁移
        assert Notification.query.filter_by(user_id=data["member_id"],
                                            type="assigned").count() == 2


def test_bulk_assign_skips_tickets_already_on_that_target(
        client, auth, make_requirement, data):
    req = make_requirement(assignee=("agent", data["dev_agent_id"]))

    r = _bulk(client, auth("pm"), ids=[req["id"]], action="assign",
              assignee_type="agent", assignee_id=data["dev_agent_id"])

    assert r.get_json()["skipped"] == [
        {"id": req["id"], "reason": "already assigned to this target"}]


def test_bulk_assign_is_forbidden_for_member(client, auth, app, make_requirement, data):
    """与单条 `PATCH /:id/assign` 的门禁逐字对齐：批量不能成为 RBAC 后门。"""
    req = make_requirement()

    r = _bulk(client, auth("member"), ids=[req["id"]], action="assign",
              assignee_type="user", assignee_id=data["member_id"])

    assert r.status_code == 403, r.get_json()
    assert r.get_json()["detail"]["required_roles"] == ["admin", "pm"]
    with app.app_context():
        assert db.session.get(Requirement, req["id"]).assignee_id is None


def test_bulk_assign_to_missing_target_is_404(client, auth, make_requirement):
    req = make_requirement()

    r = _bulk(client, auth("pm"), ids=[req["id"]], action="assign",
              assignee_type="user", assignee_id=999999)

    assert r.status_code == 404
    assert r.get_json()["error"] == "user not found"


def test_bulk_assign_rejects_non_integer_assignee_id(client, auth, make_requirement):
    req = make_requirement()

    r = _bulk(client, auth("pm"), ids=[req["id"]], action="assign",
              assignee_type="user", assignee_id="7")

    assert r.status_code == 400
    assert r.get_json()["detail"]["field"] == "assignee_id"


def test_bulk_unassign_is_idempotent(client, auth, app, make_requirement, data):
    assigned = make_requirement(assignee=("user", data["member_id"]))
    never = make_requirement()

    r = _bulk(client, auth("pm"), ids=[assigned["id"], never["id"]], action="unassign")

    body = r.get_json()
    assert body["succeeded"] == [assigned["id"]]
    assert body["skipped"] == [{"id": never["id"], "reason": "already unassigned"}]
    with app.app_context():
        row = db.session.get(Requirement, assigned["id"])
        assert row.assignee_type is None and row.assignee_id is None
        assert row.status == "assigned"              # 取消指派绝不触碰 status（§2.4-B2）


# ————————————————————— C. 批量改级别 —————————————————————

def test_bulk_priority_updates_requirements(client, auth, app, make_requirement):
    a, b = make_requirement(priority="low"), make_requirement(priority="high")

    r = _bulk(client, auth("pm"), ids=[a["id"], b["id"]], action="priority", value="urgent")

    assert r.get_json()["counts"]["succeeded"] == 2
    with app.app_context():
        assert db.session.get(Requirement, a["id"]).priority == "urgent"
        assert db.session.get(Requirement, b["id"]).priority == "urgent"


def test_bulk_severity_updates_bugs(client, auth, app, make_bug):
    bug = make_bug(severity="minor")

    r = _bulk(client, auth("pm"), entity="bugs", ids=[bug["id"]],
              action="severity", value="critical")

    assert r.status_code == 200, r.get_json()
    with app.app_context():
        assert db.session.get(Bug, bug["id"]).severity == "critical"


def test_bulk_severity_on_requirements_is_400(client, auth, make_requirement):
    """需求没有严重度；错配的 action 是调用方写错了，整单 400 并回报期望字段。"""
    req = make_requirement()

    r = _bulk(client, auth("pm"), ids=[req["id"]], action="severity", value="major")

    assert r.status_code == 400
    assert r.get_json()["detail"]["expected"] == "priority"


def test_bulk_priority_on_bugs_is_400(client, auth, make_bug):
    bug = make_bug()

    r = _bulk(client, auth("pm"), entity="bugs", ids=[bug["id"]],
              action="priority", value="high")

    assert r.status_code == 400
    assert r.get_json()["detail"]["expected"] == "severity"


def test_bulk_priority_rejects_value_outside_enum(client, auth, make_requirement):
    req = make_requirement()

    r = _bulk(client, auth("pm"), ids=[req["id"]], action="priority", value="blocker")

    assert r.status_code == 400
    assert r.get_json()["detail"]["field"] == "value"


def test_bulk_priority_skips_tickets_already_at_that_value(client, auth, make_requirement):
    req = make_requirement(priority="high")

    r = _bulk(client, auth("pm"), ids=[req["id"]], action="priority", value="high")

    assert r.get_json()["skipped"] == [{"id": req["id"], "reason": "already at this priority"}]


# ————————————————————— D. 批量删除 —————————————————————

def test_bulk_delete_removes_tickets_and_cascades_their_traces(
        client, auth, app, make_requirement):
    """级联清理复用 lifecycle.delete_ticket_cascade：评论 / 通知 / 审计随单一起走。"""
    req = make_requirement()
    with app.app_context():
        db.session.add(Comment(entity_type="requirement", entity_id=req["id"],
                               author_type="system", body="批量删除前的评论"))
        db.session.commit()

    r = _bulk(client, auth("pm"), ids=[req["id"]], action="delete")

    assert r.status_code == 200, r.get_json()
    assert r.get_json()["succeeded"] == [req["id"]]
    with app.app_context():
        assert db.session.get(Requirement, req["id"]) is None
        assert Comment.query.filter_by(entity_type="requirement",
                                       entity_id=req["id"]).count() == 0
        assert Activity.query.filter_by(entity_type="requirement",
                                        entity_id=req["id"]).count() == 0


def test_bulk_delete_clears_related_requirement_on_converted_bugs(
        client, auth, app, make_requirement, data):
    """删需求时把转出 BUG 的 related_requirement_id 置空——悬挂外键正是 lifecycle
    这一步存在的理由，批量路径不能漏掉它。"""
    req = make_requirement(assignee=("user", data["member_id"]))
    with app.app_context():
        db.session.add(Bug(title="转出的缺陷", severity="major", status="open",
                           related_requirement_id=req["id"], position=0))
        db.session.commit()

    _bulk(client, auth("pm"), ids=[req["id"]], action="delete")

    with app.app_context():
        assert Bug.query.filter_by(related_requirement_id=req["id"]).count() == 0


def test_bulk_delete_is_forbidden_for_member(client, auth, app, make_requirement, data):
    req = make_requirement(assignee=("user", data["member_id"]))

    r = _bulk(client, auth("member"), ids=[req["id"]], action="delete")

    assert r.status_code == 403, r.get_json()
    with app.app_context():
        assert db.session.get(Requirement, req["id"]) is not None


# ————————————————————— E. 输入边界 —————————————————————

def test_bulk_rejects_unknown_action(client, auth, make_requirement):
    req = make_requirement()

    r = _bulk(client, auth("pm"), ids=[req["id"]], action="nuke")

    assert r.status_code == 400
    assert r.get_json()["detail"]["field"] == "action"


def test_bulk_rejects_missing_ids(client, auth):
    r = _bulk(client, auth("pm"), action="unassign")

    assert r.status_code == 400
    assert r.get_json()["detail"]["field"] == "ids"


def test_bulk_rejects_empty_ids(client, auth):
    r = _bulk(client, auth("pm"), ids=[], action="unassign")

    assert r.status_code == 400
    assert r.get_json()["error"] == "ids must not be empty"


def test_bulk_rejects_non_integer_ids(client, auth):
    r = _bulk(client, auth("pm"), ids=["3"], action="unassign")

    assert r.status_code == 400
    assert r.get_json()["error"] == "ids must be integers"


def test_bulk_rejects_boolean_ids(client, auth):
    """bool 是 int 子类；不显式排除的话 `true` 会被当成 id=1 悄悄执行。"""
    r = _bulk(client, auth("pm"), ids=[True], action="unassign")

    assert r.status_code == 400
    assert r.get_json()["error"] == "ids must be integers"


def test_bulk_rejects_out_of_range_ids(client, auth):
    """超 64 位的 id 若绑进 SQLite 会 OverflowError → 500（scale-and-project-scope §2.6①-B）。"""
    r = _bulk(client, auth("pm"), ids=[2 ** 63], action="unassign")

    assert r.status_code == 400
    assert r.get_json()["error"] == "id is out of range"


def test_bulk_rejects_more_ids_than_the_cap(client, auth):
    r = _bulk(client, auth("pm"), ids=list(range(1, MAX_BULK_IDS + 2)), action="unassign")

    assert r.status_code == 400
    assert r.get_json()["error"] == "too many ids"


def test_bulk_accepts_exactly_the_cap(client, auth):
    """上限是「含」而非「不含」——差一错在批量上限里最常见。"""
    r = _bulk(client, auth("pm"), ids=list(range(1, MAX_BULK_IDS + 1)), action="unassign")

    assert r.status_code == 200, r.get_json()
    assert r.get_json()["requested"] == MAX_BULK_IDS


def test_bulk_deduplicates_repeated_ids(client, auth, app, make_requirement, data):
    """同一个 id 提交两次只执行一次，否则会写两条审计、发两条通知。"""
    req = make_requirement()

    r = _bulk(client, auth("pm"), ids=[req["id"], req["id"]], action="assign",
              assignee_type="user", assignee_id=data["member_id"])

    assert r.get_json()["requested"] == 1
    with app.app_context():
        assert Activity.query.filter_by(entity_type="requirement", entity_id=req["id"],
                                        action="assigned").count() == 1


def test_bulk_requires_authentication(client, make_requirement):
    req = make_requirement()

    r = client.post("/api/requirements/bulk",
                    json={"ids": [req["id"]], "action": "unassign"})

    assert r.status_code == 401


def test_bulk_bugs_move_shares_the_same_contract(client, auth, app, make_bug):
    """BUG 侧与需求侧共用一条流水线；这里只钉住「确实接通了」这一点。"""
    bug = make_bug()

    r = _bulk(client, auth("pm"), entity="bugs", ids=[bug["id"], 999999],
              action="move", status="assigned")

    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["entity"] == "bug"
    assert body["succeeded"] == [bug["id"]]
    assert body["failed"] == [{"id": 999999, "error": "bug not found"}]
    with app.app_context():
        assert db.session.get(Bug, bug["id"]).status == "assigned"
