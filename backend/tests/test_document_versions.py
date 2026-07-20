"""版本用例（ticket-document-management §7.2）：多版本递增、`current_version_id` 维护、
JSON 正文编辑、`expected_version_id` 409、截断 / 非 UTF-8 不可编辑（R5）、扇出上限（R11）。
"""
import io

from extensions import db
from models.activity import Activity
from models.document import Document
from models.document_link import DocumentLink
from test_documents import PNG, upload


def upload_text(client, headers, *, filename="plan.md", body="# v1\n初稿\n", **fields):
    data = {"file": (io.BytesIO(body.encode("utf-8")), filename)}
    data.update(fields)
    return client.post("/api/documents", data=data, headers=headers,
                       content_type="multipart/form-data")


# ————————————————————— 版本递增 —————————————————————

def test_text_edit_creates_new_version(client, auth, app):
    doc = upload_text(client, auth("pm"), title="方案").get_json()
    assert doc["editable"] is True
    v1 = doc["current_version"]

    r = client.post(f"/api/documents/{doc['id']}/versions",
                    json={"content": "# v2\n补充降级方案\n", "note": "补充降级方案",
                          "expected_version_id": v1["id"]}, headers=auth("pm"))
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert body["version"]["version_no"] == 2
    assert body["version"]["note"] == "补充降级方案"
    assert body["document"]["current_version"]["id"] == body["version"]["id"]

    # 旧版本仍可下载——「编辑」产生新版本，不覆盖历史。
    old = client.get(f"/api/documents/{doc['id']}/download?version_id={v1['id']}",
                     headers=auth("pm"))
    assert old.status_code == 200
    assert old.data.decode("utf-8") == "# v1\n初稿\n"

    with app.app_context():
        assert db.session.get(Document, doc["id"]).current_version_id == \
            body["version"]["id"]


def test_file_upload_creates_new_version(client, auth):
    doc = upload(client, auth("pm"), title="截图").get_json()
    r = client.post(f"/api/documents/{doc['id']}/versions",
                    data={"file": (io.BytesIO(PNG + b"v2"), "shot.png"),
                          "note": "重新截图"},
                    headers=auth("pm"), content_type="multipart/form-data")
    assert r.status_code == 201
    assert r.get_json()["version"]["version_no"] == 2


def test_stale_expected_version_id_conflicts(client, auth):
    doc = upload_text(client, auth("pm"), title="并发编辑").get_json()
    r = client.post(f"/api/documents/{doc['id']}/versions",
                    json={"content": "x", "expected_version_id": 999999},
                    headers=auth("pm"))
    assert r.status_code == 409
    assert r.get_json()["detail"]["current_version_id"] == doc["current_version"]["id"]
    assert "allowed" not in r.get_json()


def test_multipart_branch_honours_expected_version_id(client, auth):
    """【R5】两种 Content-Type 的并发语义必须完全一致。"""
    doc = upload(client, auth("pm"), title="图").get_json()
    r = client.post(f"/api/documents/{doc['id']}/versions",
                    data={"file": (io.BytesIO(PNG + b"z"), "shot.png"),
                          "expected_version_id": "999999"},
                    headers=auth("pm"), content_type="multipart/form-data")
    assert r.status_code == 409


def test_version_requires_uploader_or_pm(client, auth):
    doc = upload_text(client, auth("member"), title="member 的方案").get_json()
    r = client.post(f"/api/documents/{doc['id']}/versions",
                    json={"content": "x"}, headers=auth("member2"))
    assert r.status_code == 403


# ————————————————————— /content 与可编辑判据（R5）—————————————————————

def test_content_returns_text_and_editable_flags(client, auth):
    doc = upload_text(client, auth("pm"), title="正文").get_json()
    r = client.get(f"/api/documents/{doc['id']}/content", headers=auth("member"))
    assert r.status_code == 200
    body = r.get_json()
    assert body["content"] == "# v1\n初稿\n"
    assert body["truncated"] is False
    assert body["encoding_confident"] is True
    assert body["editable"] is True


def test_content_of_binary_returns_415(client, auth):
    """【R16】非文本是「类型不匹配」，不是「状态冲突」——415 而非 409。"""
    doc = upload(client, auth("pm"), title="图片").get_json()
    r = client.get(f"/api/documents/{doc['id']}/content", headers=auth("pm"))
    assert r.status_code == 415


def test_content_of_missing_blob_returns_410(client, auth, app):
    """/download 与 /content 在 blob 缺失时必须**一致**地返 410。"""
    doc = upload_text(client, auth("pm"), title="丢正文").get_json()
    with app.app_context():
        import os

        from services.documents import storage

        os.remove(storage.blob_path(doc["current_version"]["sha256"]))
    assert client.get(f"/api/documents/{doc['id']}/content",
                      headers=auth("pm")).status_code == 410


def test_truncated_text_is_never_editable(client, auth, app):
    """【R5】介于编辑阈值与预览阈值之间的文本：可预览、恒不可编辑，强行提交 409。"""
    app.config["DOC_TEXT_EDIT_MAX_BYTES"] = 200
    app.config["DOC_TEXT_PREVIEW_MAX_BYTES"] = 400
    doc = upload_text(client, auth("pm"), title="超长", body="行\n" * 500).get_json()
    r = client.get(f"/api/documents/{doc['id']}/content", headers=auth("pm"))
    assert r.get_json()["truncated"] is True
    assert r.get_json()["editable"] is False

    forced = client.post(f"/api/documents/{doc['id']}/versions",
                         json={"content": "只剩这一行"}, headers=auth("pm"))
    assert forced.status_code == 409
    # 判据顺序：先撞 too_large（size > 编辑阈值），这同样是「不可编辑」的正确理由。
    assert forced.get_json()["detail"]["reason"] in ("truncated", "too_large")


def test_editable_flag_is_false_above_the_edit_threshold(client, auth, app):
    app.config["DOC_TEXT_EDIT_MAX_BYTES"] = 100
    doc = upload_text(client, auth("pm"), title="600KB 级", body="行\n" * 200).get_json()
    assert doc["editable"] is False
    forced = client.post(f"/api/documents/{doc['id']}/versions",
                         json={"content": "x"}, headers=auth("pm"))
    assert forced.status_code == 409
    assert forced.get_json()["detail"]["reason"] == "too_large"


def test_non_utf8_text_previewable_not_editable(client, auth):
    """【R5】GBK 的 .csv 可预览（看不到内容对用户毫无价值），但恒不可编辑。"""
    payload = "姓名,备注\n张三,已验证\n".encode("gbk")
    doc = client.post("/api/documents",
                      data={"file": (io.BytesIO(payload), "结果.csv"), "title": "GBK"},
                      headers=auth("pm"),
                      content_type="multipart/form-data").get_json()
    r = client.get(f"/api/documents/{doc['id']}/content", headers=auth("pm"))
    assert r.status_code == 200
    assert r.get_json()["encoding_confident"] is False
    assert r.get_json()["editable"] is False

    forced = client.post(f"/api/documents/{doc['id']}/versions",
                         json={"content": "姓名,备注\n"}, headers=auth("pm"))
    assert forced.status_code == 409
    assert forced.get_json()["detail"]["reason"] == "encoding"


def test_binary_document_cannot_be_edited_as_text(client, auth):
    doc = upload(client, auth("pm"), title="二进制").get_json()
    r = client.post(f"/api/documents/{doc['id']}/versions",
                    json={"content": "x"}, headers=auth("pm"))
    assert r.status_code == 409
    assert r.get_json()["detail"]["reason"] == "binary"


def test_text_version_requires_a_string_content(client, auth):
    doc = upload_text(client, auth("pm"), title="坏输入").get_json()
    r = client.post(f"/api/documents/{doc['id']}/versions",
                    json={"content": 123}, headers=auth("pm"))
    assert r.status_code == 400


# ————————————————————— 扇出上限（R11）—————————————————————

def test_revise_fanout_is_capped(client, auth, app, data):
    """【R11】绑到 cap+5 张单后改版 → Activity 恰为上限值，响应体如实回传 truncated。"""
    cap = 3
    app.config["DOC_FANOUT_MAX_LINKS"] = cap
    doc = upload_text(client, auth("pm"), title="接口契约").get_json()

    ticket_ids = []
    with app.app_context():
        from models.requirement import Requirement

        for i in range(cap + 5):
            req = Requirement(title=f"复用需求 {i}", status="new",
                              reporter_id=data["pm_id"], position=i)
            db.session.add(req)
            db.session.flush()
            ticket_ids.append(req.id)
            db.session.add(DocumentLink(document_id=doc["id"],
                                        entity_type="requirement", entity_id=req.id))
        db.session.commit()

    r = client.post(f"/api/documents/{doc['id']}/versions",
                    json={"content": "# v2\n"}, headers=auth("pm"))
    assert r.status_code == 201
    body = r.get_json()
    assert body["link_count"] == cap + 5
    assert body["fanout_written"] == cap
    assert body["fanout_truncated"] is True

    with app.app_context():
        revised = Activity.query.filter_by(action="doc_revised").all()
        # cap 条逐单提醒 + 1 条汇总（写在首张单上，如实告知没有全发）。
        assert len(revised) == cap + 1


def test_revise_without_links_reports_no_truncation(client, auth):
    doc = upload_text(client, auth("pm"), title="孤立文档").get_json()
    body = client.post(f"/api/documents/{doc['id']}/versions",
                       json={"content": "x"}, headers=auth("pm")).get_json()
    assert body["link_count"] == 0
    assert body["fanout_written"] == 0
    assert body["fanout_truncated"] is False
