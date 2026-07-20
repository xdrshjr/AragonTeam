"""绑定用例（ticket-document-management §7.2）：绑定 / 重复绑定 / 绑定不存在的文档 →
404（R3）/ 解绑幂等 / stage 快照 / RBAC / 删单级联 / `document_count` 单查询（R8）。
"""
import io

from sqlalchemy import event

from extensions import db
from models.document import Document
from models.document_link import DocumentLink
from test_documents import PNG, upload


def attach_file(client, headers, entity, ticket_id, *, filename="report.md",
                payload=b"# \xe6\xb5\x8b\xe8\xaf\x95\xe6\x8a\xa5\xe5\x91\x8a\n",
                **fields):
    data = {"file": (io.BytesIO(payload), filename)}
    data.update(fields)
    return client.post(f"/api/{entity}/{ticket_id}/documents", data=data,
                       headers=headers, content_type="multipart/form-data")


def move(client, headers, req_id, status):
    return client.patch(f"/api/requirements/{req_id}/move",
                        json={"status": status}, headers=headers)


# ————————————————————— 上传并绑定 —————————————————————

def test_upload_and_bind_in_one_request(client, auth, make_requirement):
    req = make_requirement(title="支付网关")
    r = attach_file(client, auth("pm"), "requirements", req["id"],
                    title="测试报告", kind="test_report", label="验收报告")
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert body["document"]["kind"] == "test_report"
    assert body["link"]["label"] == "验收报告"
    assert body["link"]["stage"] == "new"

    listed = client.get(f"/api/requirements/{req['id']}/documents",
                        headers=auth("member")).get_json()
    assert len(listed) == 1
    assert listed[0]["link"]["id"] == body["link"]["id"]


def test_bind_records_stage_snapshot(client, auth, make_requirement, data):
    """stage 是**历史事实的快照**，工单后续流转绝不回写它。"""
    req = make_requirement(title="快照", assignee=("user", data["pm_id"]))
    move(client, auth("pm"), req["id"], "in_development")
    move(client, auth("pm"), req["id"], "testing")
    body = attach_file(client, auth("pm"), "requirements", req["id"],
                       kind="test_report").get_json()
    assert body["link"]["stage"] == "testing"

    move(client, auth("pm"), req["id"], "reviewing")
    listed = client.get(f"/api/requirements/{req['id']}/documents",
                        headers=auth("pm")).get_json()
    assert listed[0]["link"]["stage"] == "testing"        # 仍是 testing，未被回写


def test_attach_writes_activity_and_notification(client, auth, make_requirement, data,
                                                 app):
    req = make_requirement(title="通知", assignee=("user", data["member_id"]))
    attach_file(client, auth("pm"), "requirements", req["id"], title="方案")
    feed = client.get(f"/api/requirements/{req['id']}/activities",
                      headers=auth("pm")).get_json()
    attached = [a for a in feed if a["action"] == "doc_attached"]
    assert len(attached) == 1
    assert "阶段上传文档" in attached[0]["message"]

    unread = client.get("/api/notifications?unread=1", headers=auth("member")).get_json()
    assert any(n["type"] == "document_added" for n in unread)


# ————————————————————— 绑定已有 —————————————————————

def test_bind_existing_document(client, auth, make_requirement):
    req = make_requirement(title="复用")
    doc = upload(client, auth("pm"), title="共用 PRD").get_json()
    r = client.post(f"/api/requirements/{req['id']}/documents",
                    json={"document_id": doc["id"], "label": "PRD"}, headers=auth("pm"))
    assert r.status_code == 201
    assert r.get_json()["link"]["label"] == "PRD"


def test_bind_unknown_document_returns_404(client, auth, make_requirement):
    """【R3】不存在的 document_id 必须 404，绝不靠外键异常兜底变成 500。"""
    req = make_requirement(title="坏引用")
    r = client.post(f"/api/requirements/{req['id']}/documents",
                    json={"document_id": 999999}, headers=auth("pm"))
    assert r.status_code == 404
    assert r.get_json()["error"] == "document not found"


def test_duplicate_bind_returns_409(client, auth, make_requirement):
    req = make_requirement(title="重复绑定")
    doc = upload(client, auth("pm"), title="唯一").get_json()
    payload = {"document_id": doc["id"]}
    assert client.post(f"/api/requirements/{req['id']}/documents",
                       json=payload, headers=auth("pm")).status_code == 201
    r = client.post(f"/api/requirements/{req['id']}/documents",
                    json=payload, headers=auth("pm"))
    assert r.status_code == 409
    assert "allowed" not in r.get_json()


def test_one_document_serves_many_tickets(client, auth, make_requirement, make_bug):
    doc = upload(client, auth("pm"), title="一份 PRD").get_json()
    for _ in range(3):
        req = make_requirement(title="需求")
        client.post(f"/api/requirements/{req['id']}/documents",
                    json={"document_id": doc["id"]}, headers=auth("pm"))
    bug = make_bug(title="缺陷")
    client.post(f"/api/bugs/{bug['id']}/documents",
                json={"document_id": doc["id"]}, headers=auth("pm"))
    detail = client.get(f"/api/documents/{doc['id']}", headers=auth("pm")).get_json()
    assert detail["link_count"] == 4


# ————————————————————— 解绑 —————————————————————

def test_unbind_is_idempotent(client, auth, make_requirement, app):
    """未绑定时 DELETE 同样 204，且不写审计、不发通知。"""
    req = make_requirement(title="幂等解绑")
    doc = upload(client, auth("pm"), title="未绑定").get_json()
    r = client.delete(f"/api/requirements/{req['id']}/documents/{doc['id']}",
                      headers=auth("pm"))
    assert r.status_code == 204
    feed = client.get(f"/api/requirements/{req['id']}/activities",
                      headers=auth("pm")).get_json()
    assert not any(a["action"] == "doc_detached" for a in feed)


def test_unbind_removes_link_and_writes_activity(client, auth, make_requirement):
    req = make_requirement(title="解绑")
    body = attach_file(client, auth("pm"), "requirements", req["id"],
                       title="材料").get_json()
    doc_id = body["document"]["id"]
    assert client.delete(f"/api/requirements/{req['id']}/documents/{doc_id}",
                         headers=auth("pm")).status_code == 204
    assert client.get(f"/api/requirements/{req['id']}/documents",
                      headers=auth("pm")).get_json() == []
    # 文档本体仍在文档库里——解绑绝不删文档。
    assert client.get(f"/api/documents/{doc_id}", headers=auth("pm")).status_code == 200
    feed = client.get(f"/api/requirements/{req['id']}/activities",
                      headers=auth("pm")).get_json()
    assert any(a["action"] == "doc_detached" for a in feed)


# ————————————————————— RBAC —————————————————————

def test_bind_requires_can_manage_ticket(client, auth, make_requirement):
    req = make_requirement(title="他人的单")
    doc = upload(client, auth("pm"), title="材料").get_json()
    r = client.post(f"/api/requirements/{req['id']}/documents",
                    json={"document_id": doc["id"]}, headers=auth("member"))
    assert r.status_code == 403


def test_reading_ticket_documents_is_open_to_any_authenticated_user(
        client, auth, make_requirement):
    req = make_requirement(title="人人可读")
    attach_file(client, auth("pm"), "requirements", req["id"], title="材料")
    assert client.get(f"/api/requirements/{req['id']}/documents",
                      headers=auth("member")).status_code == 200


def test_unknown_ticket_returns_404(client, auth):
    assert client.get("/api/requirements/999999/documents",
                      headers=auth("pm")).status_code == 404
    assert client.get("/api/bugs/999999/documents", headers=auth("pm")).status_code == 404


# ————————————————————— 级联 —————————————————————

def test_delete_ticket_unbinds_but_keeps_documents(client, auth, make_requirement, app):
    """删单后 link 为 0，**Document 行仍在**，磁盘文件仍在。

    对用户真实数据的推定必须是保留：删掉一张单就静默销毁一份 PRD 是不可接受的。
    """
    req = make_requirement(title="待删单")
    body = attach_file(client, auth("pm"), "requirements", req["id"],
                       title="要保留的文档").get_json()
    doc_id = body["document"]["id"]
    sha = body["document"]["current_version"]["sha256"]

    assert client.delete(f"/api/requirements/{req['id']}",
                         headers=auth("pm")).status_code == 204
    with app.app_context():
        assert DocumentLink.query.filter_by(entity_type="requirement",
                                            entity_id=req["id"]).count() == 0
        assert db.session.get(Document, doc_id) is not None
        from services.documents import storage

        assert storage.blob_path(sha).exists()


def test_cascade_report_includes_document_links(app, auth, client, make_requirement):
    req = make_requirement(title="级联返回值")
    attach_file(client, auth("pm"), "requirements", req["id"], title="材料")
    with app.app_context():
        from models.requirement import Requirement
        from services import lifecycle

        ticket = db.session.get(Requirement, req["id"])
        removed = lifecycle.delete_ticket_cascade("requirement", ticket)
        # 既有三个键逐字不变，`document_links` 是**追加**键。
        assert set(removed) == {"comments", "notifications", "activities",
                                "document_links"}
        assert removed["document_links"] == 1
        db.session.rollback()


# ————————————————————— document_count（R8）—————————————————————

def test_document_count_appears_on_ticket_payloads(client, auth, make_requirement):
    req = make_requirement(title="带徽章")
    assert client.get(f"/api/requirements/{req['id']}",
                      headers=auth("pm")).get_json()["document_count"] == 0
    attach_file(client, auth("pm"), "requirements", req["id"], title="材料")
    assert client.get(f"/api/requirements/{req['id']}",
                      headers=auth("pm")).get_json()["document_count"] == 1
    listed = client.get("/api/requirements", headers=auth("pm")).get_json()
    assert next(r for r in listed if r["id"] == req["id"])["document_count"] == 1
    board = client.get("/api/board/requirements", headers=auth("pm")).get_json()
    cards = [c for col in board["columns"] for c in col["items"]]
    assert next(c for c in cards if c["id"] == req["id"])["document_count"] == 1


def test_document_count_is_single_query(client, auth, app, bulk_tickets):
    """【R8】列表 50 行 → 计数查询恰 1 次；**整块看板（7 列）也恰 1 次**。"""
    bulk_tickets(50, status="new")
    seen = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        if "document_links" in statement and "count" in statement.lower():
            seen.append(statement)

    engine = db.engine
    event.listen(engine, "before_cursor_execute", _record)
    try:
        client.get("/api/requirements?limit=50", headers=auth("pm"))
        assert len(seen) == 1, seen
        seen.clear()
        client.get("/api/board/requirements", headers=auth("pm"))
        assert len(seen) == 1, seen
    finally:
        event.remove(engine, "before_cursor_execute", _record)


def test_empty_id_list_issues_no_count_query(app):
    with app.app_context():
        from services.documents import counts

        assert counts.link_counts("requirement", []) == {}
        assert counts.document_link_counts([]) == {}
