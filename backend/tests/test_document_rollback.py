"""版本回滚用例（document-lifecycle-depth §7.2 支柱 B）。

覆盖：零字节写盘、历史不删、5 条失败路径、扇出上限，以及 **B8：二进制文档也能回滚**
（分流点必须在 `_reject_uneditable` 之前）。
"""
import io

from extensions import db
from models.document import DocumentVersion
from test_documents import PNG, upload

MD_V1 = "# 方案 v1\n\n第一版内容。\n".encode("utf-8")
MD_V2 = "# 方案 v2\n\n第二版内容。\n".encode("utf-8")


def upload_md(client, headers, *, title="方案", payload=MD_V1):
    return upload(client, headers, filename="plan.md", payload=payload,
                  title=title, kind="design")


def revise_text(client, headers, document_id, content):
    return client.post(f"/api/documents/{document_id}/versions",
                       json={"content": content}, headers=headers)


def rollback(client, headers, document_id, from_version_id, **extra):
    payload = {"from_version_id": from_version_id}
    payload.update(extra)
    return client.post(f"/api/documents/{document_id}/versions",
                       json=payload, headers=headers)


def blob_files(app):
    from services.documents import storage

    root = storage.upload_root()
    return sorted(p for p in root.rglob("*")
                  if p.is_file() and storage.TMP_DIRNAME not in p.parts)


# ————————————————————— B1 ~ B2 · 免费红利 —————————————————————

def test_rollback_creates_new_version_sharing_digest(client, auth, app):
    """新版本与源版本共享同一个 sha256，**磁盘文件数一个不多**。"""
    doc = upload_md(client, auth("pm")).get_json()
    v1 = doc["current_version"]
    revise_text(client, auth("pm"), doc["id"], "# 方案 v2\n\n第二版内容。\n")
    with app.app_context():
        files_before = blob_files(app)

    r = rollback(client, auth("pm"), doc["id"], v1["id"])
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert body["version"]["sha256"] == v1["sha256"]
    assert body["version"]["version_no"] == 3
    assert body["version"]["original_filename"] == v1["original_filename"]
    assert body["version"]["mime_type"] == v1["mime_type"]
    assert body["version"]["size_bytes"] == v1["size_bytes"]
    assert body["version"]["note"] == "回滚到 v1"
    assert body["document"]["current_version"]["id"] == body["version"]["id"]
    with app.app_context():
        assert blob_files(app) == files_before          # 零字节写盘


def test_rollback_keeps_history_intact(client, auth, app):
    """回滚是「加一行」而不是「退回去」——审计链完整可读。"""
    doc = upload_md(client, auth("pm")).get_json()
    v1_id = doc["current_version"]["id"]
    revise_text(client, auth("pm"), doc["id"], "v2")
    revise_text(client, auth("pm"), doc["id"], "v3")
    rollback(client, auth("pm"), doc["id"], v1_id)
    detail = client.get(f"/api/documents/{doc['id']}", headers=auth("pm")).get_json()
    assert [v["version_no"] for v in detail["versions"]] == [4, 3, 2, 1]
    with app.app_context():
        assert DocumentVersion.query.filter_by(document_id=doc["id"]).count() == 4


def test_rollback_content_is_actually_the_old_one(client, auth):
    doc = upload_md(client, auth("pm")).get_json()
    v1_id = doc["current_version"]["id"]
    revise_text(client, auth("pm"), doc["id"], "完全不同的内容")
    rollback(client, auth("pm"), doc["id"], v1_id)
    content = client.get(f"/api/documents/{doc['id']}/content",
                         headers=auth("pm")).get_json()
    assert content["content"] == MD_V1.decode("utf-8")


# ————————————————————— B3 ~ B6 · 失败路径 —————————————————————

def test_rollback_to_current_returns_409(client, auth):
    doc = upload_md(client, auth("pm")).get_json()
    r = rollback(client, auth("pm"), doc["id"], doc["current_version"]["id"])
    assert r.status_code == 409
    assert r.get_json()["detail"]["reason"] == "already_current"
    assert "allowed" not in r.get_json()["detail"]


def test_rollback_with_foreign_version_returns_404(client, auth):
    """跨文档的 version_id 一律视为不存在（现网 `find_version` 语义，直接复用）。"""
    first = upload_md(client, auth("pm"), title="甲").get_json()
    second = upload_md(client, auth("pm"), title="乙", payload=MD_V2).get_json()
    r = rollback(client, auth("pm"), first["id"], second["current_version"]["id"])
    assert r.status_code == 404


def test_rollback_with_unknown_version_returns_404(client, auth):
    doc = upload_md(client, auth("pm")).get_json()
    assert rollback(client, auth("pm"), doc["id"], 999999).status_code == 404


def test_rollback_with_missing_blob_returns_410(client, auth, app):
    """**不允许**建出一行指向空气的版本——那会让当前版本变成下载即 410 的空壳。"""
    doc = upload_md(client, auth("pm")).get_json()
    v1 = doc["current_version"]
    revise_text(client, auth("pm"), doc["id"], "v2 内容")
    with app.app_context():
        from services.documents import storage

        storage.blob_path(v1["sha256"]).unlink()
    r = rollback(client, auth("pm"), doc["id"], v1["id"])
    assert r.status_code == 410
    assert r.get_json()["detail"]["reason"] == "blob_missing"
    with app.app_context():
        assert DocumentVersion.query.filter_by(document_id=doc["id"]).count() == 2


def test_rollback_and_content_are_mutually_exclusive(client, auth):
    doc = upload_md(client, auth("pm")).get_json()
    v1_id = doc["current_version"]["id"]
    revise_text(client, auth("pm"), doc["id"], "v2")
    r = rollback(client, auth("pm"), doc["id"], v1_id, content="两个都传")
    assert r.status_code == 400
    assert r.get_json()["detail"]["reason"] == "ambiguous_source"


def test_rollback_requires_manage_permission(client, auth):
    doc = upload_md(client, auth("pm")).get_json()
    v1_id = doc["current_version"]["id"]
    revise_text(client, auth("pm"), doc["id"], "v2")
    assert rollback(client, auth("member"), doc["id"], v1_id).status_code == 403


def test_rollback_respects_optimistic_lock(client, auth):
    """并发下「我以为我在从 v3 回滚」而实际已是 v5，应当照样冲突。"""
    doc = upload_md(client, auth("pm")).get_json()
    v1_id = doc["current_version"]["id"]
    revise_text(client, auth("pm"), doc["id"], "v2")
    r = rollback(client, auth("pm"), doc["id"], v1_id, expected_version_id=v1_id)
    assert r.status_code == 409
    assert r.get_json()["detail"]["current_version_id"] != v1_id


# ————————————————————— B7 · 扇出 —————————————————————

def test_rollback_fanout_is_capped(client, auth, app, make_requirement):
    """复用 `DOC_FANOUT_MAX_LINKS` 并如实回传 `fanout_truncated`。"""
    app.config["DOC_FANOUT_MAX_LINKS"] = 1
    doc = upload_md(client, auth("pm")).get_json()
    v1_id = doc["current_version"]["id"]
    revise_text(client, auth("pm"), doc["id"], "v2")
    tickets = [make_requirement(title=f"单 {i}") for i in range(2)]
    for ticket in tickets:
        client.post(f"/api/requirements/{ticket['id']}/documents",
                    json={"document_id": doc["id"]}, headers=auth("pm"))

    body = rollback(client, auth("pm"), doc["id"], v1_id).get_json()
    assert body["link_count"] == 2
    assert body["fanout_written"] == 1
    assert body["fanout_truncated"] is True


def test_rollback_writes_doc_rolled_back_activity(client, auth, make_requirement):
    req = make_requirement(title="时间线")
    doc = upload_md(client, auth("pm")).get_json()
    v1_id = doc["current_version"]["id"]
    revise_text(client, auth("pm"), doc["id"], "v2")
    client.post(f"/api/requirements/{req['id']}/documents",
                json={"document_id": doc["id"]}, headers=auth("pm"))
    rollback(client, auth("pm"), doc["id"], v1_id)
    acts = client.get(f"/api/requirements/{req['id']}/activities",
                      headers=auth("pm")).get_json()
    rolled = [a for a in acts if a["action"] == "doc_rolled_back"]
    assert len(rolled) == 1
    assert "回滚到 v1" in rolled[0]["message"]


# ————————————————————— B8 · P1 护栏 —————————————————————

def test_rollback_works_on_binary_document(client, auth):
    """【B8 · 评审 V-06】对一份 `.png` 回滚必须 **201**，不得 409 `{"reason":"binary"}`。

    这条用例的存在本身就是那处顺序约束的护栏：`_reject_uneditable` 的四条判据是为
    「在线编辑文本」设的（它拦的是**数据损毁**），而回滚不产生任何新内容，只是把一个
    已经存在、字节完整的历史版本重新指为当前版本。分流写在闸之后，回滚任何二进制文档
    都会被判成「不支持文本编辑」——而 §4.2 的状态码表里根本没有这一档。
    """
    doc = upload(client, auth("pm"), title="截图", filename="shot.png").get_json()
    v1_id = doc["current_version"]["id"]
    other = PNG + b"different tail"
    r = client.post(f"/api/documents/{doc['id']}/versions",
                    data={"file": (io.BytesIO(other), "shot.png")},
                    headers=auth("pm"), content_type="multipart/form-data")
    assert r.status_code == 201

    # 先自证前提：这份文档确实**不可**在线编辑（走 content 分支会 409 binary）。
    blocked = client.post(f"/api/documents/{doc['id']}/versions",
                          json={"content": "改一个字"}, headers=auth("pm"))
    assert blocked.status_code == 409
    assert blocked.get_json()["detail"]["reason"] == "binary"

    rolled = rollback(client, auth("pm"), doc["id"], v1_id)
    assert rolled.status_code == 201, rolled.get_json()
    assert rolled.get_json()["version"]["sha256"] == doc["current_version"]["sha256"]


def test_rollback_of_trashed_document_is_404(client, auth):
    doc = upload_md(client, auth("pm")).get_json()
    v1_id = doc["current_version"]["id"]
    revise_text(client, auth("pm"), doc["id"], "v2")
    client.delete(f"/api/documents/{doc['id']}", headers=auth("pm"))
    assert rollback(client, auth("pm"), doc["id"], v1_id).status_code == 404
