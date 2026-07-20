"""阶段策略用例（ticket-document-management §7.2）：清单判定、七态全覆盖含 bug_fixing
（R2）、门禁默认关闭、开启后 409 形状、回退迁移永不被挡（R2）、Agent 路径永不被挡、
`doc_missing_hint` 去重（R10）。
"""
import io

import pytest

from extensions import db
from models.activity import Activity
from services import doc_policy, workflow
from test_documents import upload


def attach(client, headers, req_id, kind):
    return client.post(f"/api/requirements/{req_id}/documents",
                       data={"file": (io.BytesIO(b"# report\n"), "r.md"), "kind": kind},
                       headers=headers, content_type="multipart/form-data")


def set_status(app, model_name, ticket_id, status):
    """直接改库摆状态：本文件测的是门禁，不是流转本身。"""
    with app.app_context():
        from models.bug import Bug
        from models.requirement import Requirement

        model = {"requirement": Requirement, "bug": Bug}[model_name]
        ticket = db.session.get(model, ticket_id)
        ticket.status = status
        db.session.commit()


# ————————————————————— 清单 —————————————————————

def test_checklist_covers_every_workflow_status(client, auth, app, make_requirement,
                                                make_bug):
    """遍历两个实体的**全部 12 个状态**，每个都能取到非 500 的清单。"""
    req = make_requirement(title="全状态")
    bug = make_bug(title="全状态 BUG")
    for entity, segment, ticket in (("requirement", "requirements", req),
                                    ("bug", "bugs", bug)):
        for status in workflow.column_keys(entity):
            set_status(app, entity, ticket["id"], status)
            r = client.get(f"/api/{segment}/{ticket['id']}/document-checklist",
                           headers=auth("pm"))
            assert r.status_code == 200, (entity, status, r.get_json())
            body = r.get_json()
            assert body["stage"] == status
            assert body["stage_label"]                    # 中文名不得为空
            assert isinstance(body["items"], list)


def test_bug_fixing_column_is_not_blank(client, auth, app, make_requirement):
    """【R2】v1 遗漏了 requirement 的第 7 态；落一个状态，前端该列就渲染成空白。"""
    assert doc_policy.expectations("requirement", "bug_fixing") == ("bug_evidence",)
    req = make_requirement(title="返工")
    set_status(app, "requirement", req["id"], "bug_fixing")
    body = client.get(f"/api/requirements/{req['id']}/document-checklist",
                      headers=auth("pm")).get_json()
    assert body["stage_label"] == "修复中"
    assert [i["kind"] for i in body["items"]] == ["bug_evidence"]


def test_checklist_reflects_bound_kinds(client, auth, app, make_requirement):
    req = make_requirement(title="清单翻真")
    set_status(app, "requirement", req["id"], "testing")
    before = client.get(f"/api/requirements/{req['id']}/document-checklist",
                        headers=auth("pm")).get_json()
    assert before["satisfied"] is False
    assert before["items"][0]["satisfied"] is False

    attach(client, auth("pm"), req["id"], "test_plan")
    after = client.get(f"/api/requirements/{req['id']}/document-checklist",
                       headers=auth("pm")).get_json()
    assert after["satisfied"] is True
    assert after["items"][0]["satisfied"] is True
    assert after["items"][0]["document_ids"]


def test_checklist_counts_documents_bound_at_any_stage(client, auth, app,
                                                       make_requirement):
    """口径是**当前绑定的全部文档**，不是「在这个阶段绑定的」——否则复用被亲手废掉。"""
    req = make_requirement(title="跨阶段复用")
    set_status(app, "requirement", req["id"], "assigned")
    attach(client, auth("pm"), req["id"], "requirement_spec")
    set_status(app, "requirement", req["id"], "in_development")
    body = client.get(f"/api/requirements/{req['id']}/document-checklist",
                      headers=auth("pm")).get_json()
    spec_item = next(i for i in body["items"] if i["kind"] == "requirement_spec")
    assert spec_item["satisfied"] is True


def test_checklist_exposes_the_real_switch_value(client, auth, app, make_requirement):
    """`enforced` 直接回传开关真实值——**前端绝不自己猜这个开关**。"""
    req = make_requirement(title="开关")
    body = client.get(f"/api/requirements/{req['id']}/document-checklist",
                      headers=auth("pm")).get_json()
    assert body["enforced"] is False
    app.config["DOC_STAGE_GATE"] = True
    body = client.get(f"/api/requirements/{req['id']}/document-checklist",
                      headers=auth("pm")).get_json()
    assert body["enforced"] is True


# ————————————————————— 门禁 —————————————————————

def test_gate_disabled_by_default(client, auth, app, make_requirement, data):
    """不设 DOC_STAGE_GATE → 缺材料照样能 move 到 done（默认行为逐字节不变）。"""
    assert app.config["DOC_STAGE_GATE"] is False
    req = make_requirement(title="默认放行", assignee=("user", data["pm_id"]))
    set_status(app, "requirement", req["id"], "reviewing")
    r = client.patch(f"/api/requirements/{req['id']}/move",
                     json={"status": "done"}, headers=auth("pm"))
    assert r.status_code == 200


def test_gate_blocks_human_move_when_enabled(client, auth, app, make_requirement, data):
    app.config["DOC_STAGE_GATE"] = True
    req = make_requirement(title="缺测试报告", assignee=("user", data["pm_id"]))
    set_status(app, "requirement", req["id"], "reviewing")
    r = client.patch(f"/api/requirements/{req['id']}/move",
                     json={"status": "done"}, headers=auth("pm"))
    assert r.status_code == 409
    body = r.get_json()
    assert body["error"] == "required documents are missing"
    assert body["detail"]["missing"] == ["test_report"]
    # 前端以 err.allowed 是否存在区分「状态机非法」与「其他冲突」。
    assert "allowed" not in body


def test_gate_passes_once_the_document_is_attached(client, auth, app,
                                                   make_requirement, data):
    app.config["DOC_STAGE_GATE"] = True
    req = make_requirement(title="补齐后放行", assignee=("user", data["pm_id"]))
    set_status(app, "requirement", req["id"], "reviewing")
    attach(client, auth("pm"), req["id"], "test_report")
    r = client.patch(f"/api/requirements/{req['id']}/move",
                     json={"status": "done"}, headers=auth("pm"))
    assert r.status_code == 200


def test_gate_never_blocks_backward_move(client, auth, app, make_requirement, data):
    """【R2】用户按下回退键的原因**恰恰是材料不合格**，门禁在这里生效就是死结。"""
    app.config["DOC_STAGE_GATE"] = True
    req = make_requirement(title="回退", assignee=("user", data["pm_id"]))
    for frm, to in (("done", "reviewing"), ("reviewing", "bug_fixing"),
                    ("testing", "in_development"), ("bug_fixing", "in_development")):
        set_status(app, "requirement", req["id"], frm)
        r = client.patch(f"/api/requirements/{req['id']}/move",
                         json={"status": to}, headers=auth("pm"))
        assert r.status_code == 200, (frm, to, r.get_json())


def test_gate_never_blocks_backward_bug_move(client, auth, app, make_bug, data):
    app.config["DOC_STAGE_GATE"] = True
    bug = make_bug(title="BUG 回退", assignee=("user", data["pm_id"]))
    set_status(app, "bug", bug["id"], "closed")
    r = client.patch(f"/api/bugs/{bug['id']}/move",
                     json={"status": "verifying"}, headers=auth("pm"))
    assert r.status_code == 200


def test_gate_blocks_forward_bug_move(client, auth, app, make_bug, data):
    """门禁必须在 bugs 蓝图里**单独挂一次**——move_bug 的主体是独立的。"""
    app.config["DOC_STAGE_GATE"] = True
    bug = make_bug(title="BUG 前进", assignee=("user", data["pm_id"]))
    set_status(app, "bug", bug["id"], "verifying")
    r = client.patch(f"/api/bugs/{bug['id']}/move",
                     json={"status": "closed"}, headers=auth("pm"))
    assert r.status_code == 409
    assert r.get_json()["detail"]["missing"] == ["test_report"]


def test_illegal_transition_still_wins_over_gate(client, auth, app, make_requirement,
                                                 data):
    """非法迁移在门禁开启时仍返回**带 allowed** 的状态机 409——状态机仍是唯一仲裁者。"""
    app.config["DOC_STAGE_GATE"] = True
    req = make_requirement(title="非法迁移", assignee=("user", data["pm_id"]))
    r = client.patch(f"/api/requirements/{req['id']}/move",
                     json={"status": "done"}, headers=auth("pm"))
    assert r.status_code == 409
    assert "allowed" in r.get_json()
    assert r.get_json()["error"] == "illegal transition"


def test_same_column_move_is_never_gated(client, auth, app, make_requirement, data):
    app.config["DOC_STAGE_GATE"] = True
    req = make_requirement(title="同列拖拽", assignee=("user", data["pm_id"]))
    set_status(app, "requirement", req["id"], "reviewing")
    r = client.patch(f"/api/requirements/{req['id']}/move",
                     json={"status": "reviewing", "position": 0}, headers=auth("pm"))
    assert r.status_code == 200


# ————————————————————— Agent 路径（R8 / R10）—————————————————————

def test_gate_never_blocks_agent_advance(client, auth, app, make_requirement, data):
    """Agent 被门禁挡住会表现为「自动流水线莫名其妙不动了」，且没人会收到那个 409。"""
    app.config["DOC_STAGE_GATE"] = True
    req = make_requirement(title="Agent 推进",
                           assignee=("agent", data["dev_agent_id"]))
    r = client.post(f"/api/requirements/{req['id']}/agent-advance", headers=auth("pm"))
    assert r.status_code == 200, r.get_json()


def test_doc_missing_hint_is_deduped(client, auth, app, make_requirement, data):
    """【R10】连续推进只多出 **1** 条提示；门禁关闭时 **0** 条。"""
    app.config["DOC_STAGE_GATE"] = True
    req = make_requirement(title="提示去重",
                           assignee=("agent", data["dev_agent_id"]))
    for _ in range(3):
        client.post(f"/api/requirements/{req['id']}/agent-advance", headers=auth("pm"))
        set_status(app, "requirement", req["id"], "assigned")
    with app.app_context():
        hints = Activity.query.filter_by(entity_type="requirement",
                                         entity_id=req["id"],
                                         action="doc_missing_hint").all()
        assert len(hints) == 1
        assert "通常需要" in hints[0].message


def test_no_hint_when_gate_is_disabled(client, auth, app, make_requirement, data):
    req = make_requirement(title="无提示", assignee=("agent", data["dev_agent_id"]))
    client.post(f"/api/requirements/{req['id']}/agent-advance", headers=auth("pm"))
    with app.app_context():
        assert Activity.query.filter_by(entity_id=req["id"],
                                        action="doc_missing_hint").count() == 0


# ————————————————————— 单元判据 —————————————————————

def test_is_forward_treats_bug_fixing_as_rework(app):
    """【实施发现 F1】`bug_fixing` 在看板列序里排在 reviewing **之后**，但语义上是返工态。"""
    with app.app_context():
        assert doc_policy.is_forward("requirement", "reviewing", "done") is True
        assert doc_policy.is_forward("requirement", "reviewing", "bug_fixing") is False
        assert doc_policy.is_forward("requirement", "testing", "in_development") is False
        assert doc_policy.is_forward("requirement", "bug_fixing", "testing") is True
        assert doc_policy.is_forward("bug", "verifying", "closed") is True
        assert doc_policy.is_forward("bug", "closed", "verifying") is False


def test_threshold_assertion_rejects_an_inverted_configuration():
    with pytest.raises(ValueError):
        doc_policy.assert_thresholds({"DOC_TEXT_PREVIEW_MAX_BYTES": 1000,
                                      "DOC_TEXT_EDIT_MAX_BYTES": 1000})
    doc_policy.assert_thresholds({"DOC_TEXT_PREVIEW_MAX_BYTES": 1001,
                                  "DOC_TEXT_EDIT_MAX_BYTES": 1000})
