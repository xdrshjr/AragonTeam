"""文档库端点用例（ticket-document-management §7.2）：上传 / 闸 0~4 / 413 / 列表 /
详情 / PATCH 并发 / 删除 409 与 force。
"""
import io

from extensions import db
from models.document import Document


PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 8


def upload(client, headers, *, filename="shot.png", payload=PNG, **fields):
    data = {"file": (io.BytesIO(payload), filename)}
    data.update(fields)
    return client.post("/api/documents", data=data, headers=headers,
                       content_type="multipart/form-data")


# ————————————————————— 上传 —————————————————————

def test_upload_creates_document_and_version(client, auth, app):
    r = upload(client, auth("pm"), title="支付网关技术方案", kind="design")
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert body["title"] == "支付网关技术方案"
    assert body["kind"] == "design"
    assert body["current_version"]["version_no"] == 1
    assert body["link_count"] == 0
    assert body["deduped"] is False

    with app.app_context():
        doc = db.session.get(Document, body["id"])
        assert doc.current_version_id == body["current_version"]["id"]
        from services.documents import storage

        assert storage.blob_path(body["current_version"]["sha256"]).exists()


def test_upload_defaults_title_to_filename_and_kind_to_other(client, auth):
    body = upload(client, auth("member"), filename="复现录屏.png").get_json()
    assert body["title"] == "复现录屏.png"
    assert body["kind"] == "other"
    # 中文文件名原样保留（落盘路径由摘要推导，与文件名结构性无关）。
    assert body["current_version"]["original_filename"] == "复现录屏.png"


def test_identical_uploads_share_one_blob(client, auth, app):
    first = upload(client, auth("pm"), title="A").get_json()
    second = upload(client, auth("pm"), title="B").get_json()
    assert first["id"] != second["id"]
    assert first["current_version"]["sha256"] == second["current_version"]["sha256"]
    assert second["deduped"] is True
    with app.app_context():
        from services.documents import storage

        root = storage.upload_root()
        blobs = [p for p in root.rglob("*") if p.is_file()
                 and storage.TMP_DIRNAME not in p.parts]
        assert len(blobs) == 1


# ————————————————————— 闸 0~4 —————————————————————

def test_bad_project_id_returns_400_not_500(client, auth):
    """【R3】不存在的 project_id 必须 400，绝不靠外键异常兜底变成 500。"""
    r = upload(client, auth("pm"), project_id="999999")
    assert r.status_code == 400, r.get_json()
    assert r.get_json()["error"] != "internal server error"
    assert r.get_json()["error"] == "project not found"


def test_non_integer_project_id_returns_400(client, auth):
    r = upload(client, auth("pm"), project_id="abc")
    assert r.status_code == 400
    assert r.get_json()["detail"]["field"] == "project_id"


def test_rejects_disallowed_extension(client, auth):
    r = upload(client, auth("pm"), filename="evil.html",
               payload=b"<script>alert(document.cookie)</script>")
    assert r.status_code == 400
    body = r.get_json()
    assert "html" not in body["detail"]["expected"]
    assert "svg" not in body["detail"]["expected"]


def test_rejects_content_extension_mismatch(client, auth):
    """把 .html 内容改名成 .png 上传 → 400（防「骗浏览器 inline 渲染」）。"""
    r = upload(client, auth("pm"), filename="fake.png",
               payload=b"<html><script>alert(1)</script></html>")
    assert r.status_code == 400
    assert r.get_json()["error"] == "file content does not match its extension"


def test_missing_file_field_returns_400(client, auth):
    r = client.post("/api/documents", data={"title": "无文件"},
                    headers=auth("pm"), content_type="multipart/form-data")
    assert r.status_code == 400
    assert r.get_json()["error"] == "file is required"


def test_invalid_kind_returns_400(client, auth):
    r = upload(client, auth("pm"), kind="不存在的类型")
    assert r.status_code == 400
    assert r.get_json()["detail"]["field"] == "kind"


def test_rejects_oversize_upload(client, auth, app):
    """超 MAX_UPLOAD_MB → **413** 且响应体是 JSON 契约，不是 werkzeug 的 HTML。"""
    oversize = b"\x89PNG\r\n\x1a\n" + b"x" * (2 * 1024 * 1024)
    r = upload(client, auth("pm"), payload=oversize)
    assert r.status_code == 413
    body = r.get_json()
    assert body["error"] == "file too large"
    assert body["detail"]["max_mb"] == app.config["MAX_UPLOAD_MB"]


def test_zero_byte_file_is_accepted(client, auth):
    """零字节文件读不满魔数，视为无签名 → 放行（空文件不是攻击载荷）。"""
    r = upload(client, auth("pm"), filename="empty.log", payload=b"")
    assert r.status_code == 201
    assert r.get_json()["current_version"]["size_bytes"] == 0


# ————————————————————— 列表 / 详情 —————————————————————

def test_list_is_paginated_with_total_count(client, auth):
    for i in range(4):
        upload(client, auth("pm"), title=f"文档{i}",
               payload=PNG + bytes([i]), kind="design")
    r = client.get("/api/documents?limit=2", headers=auth("member"))
    assert r.status_code == 200
    assert isinstance(r.get_json(), list) and len(r.get_json()) == 2
    assert int(r.headers["X-Total-Count"]) == 4


def test_list_filters_by_kind_and_keyword(client, auth):
    upload(client, auth("pm"), title="支付方案", kind="design", payload=PNG + b"1")
    upload(client, auth("pm"), title="登录用例", kind="test_plan", payload=PNG + b"2")
    r = client.get("/api/documents?kind=design", headers=auth("member"))
    assert [d["title"] for d in r.get_json()] == ["支付方案"]
    r = client.get("/api/documents?q=登录", headers=auth("member"))
    assert [d["title"] for d in r.get_json()] == ["登录用例"]


def test_detail_carries_versions_and_links(client, auth):
    doc = upload(client, auth("pm"), title="契约").get_json()
    r = client.get(f"/api/documents/{doc['id']}", headers=auth("member"))
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["versions"]) == 1
    assert body["links"] == []


def test_detail_of_unknown_document_returns_404(client, auth):
    assert client.get("/api/documents/999999", headers=auth("pm")).status_code == 404


# ————————————————————— PATCH —————————————————————

def test_patch_updates_metadata(client, auth):
    doc = upload(client, auth("pm"), title="旧标题").get_json()
    r = client.patch(f"/api/documents/{doc['id']}",
                     json={"title": "新标题", "kind": "reference"}, headers=auth("pm"))
    assert r.status_code == 200
    assert r.get_json()["title"] == "新标题"
    assert r.get_json()["kind"] == "reference"


def test_patch_honours_expected_updated_at(client, auth):
    doc = upload(client, auth("pm"), title="并发").get_json()
    r = client.patch(f"/api/documents/{doc['id']}",
                     json={"title": "X", "expected_updated_at": "1999-01-01T00:00:00Z"},
                     headers=auth("pm"))
    assert r.status_code == 409
    assert "allowed" not in r.get_json()


def test_patch_requires_uploader_or_pm(client, auth):
    doc = upload(client, auth("member"), title="member 的文档").get_json()
    assert client.patch(f"/api/documents/{doc['id']}", json={"title": "X"},
                        headers=auth("member2")).status_code == 403
    assert client.patch(f"/api/documents/{doc['id']}", json={"title": "X"},
                        headers=auth("member")).status_code == 200
    assert client.patch(f"/api/documents/{doc['id']}", json={"title": "Y"},
                        headers=auth("admin")).status_code == 200


# ————————————————————— DELETE —————————————————————

def test_delete_unlinked_document(client, auth, app):
    doc = upload(client, auth("pm"), title="待删").get_json()
    assert client.delete(f"/api/documents/{doc['id']}",
                         headers=auth("pm")).status_code == 204
    assert client.get(f"/api/documents/{doc['id']}",
                      headers=auth("pm")).status_code == 404


def test_delete_unknown_document_returns_404(client, auth):
    assert client.delete("/api/documents/999999",
                         headers=auth("pm")).status_code == 404


def test_delete_requires_uploader_or_pm(client, auth):
    doc = upload(client, auth("member"), title="member 的").get_json()
    assert client.delete(f"/api/documents/{doc['id']}",
                         headers=auth("member2")).status_code == 403


def test_delete_linked_document_conflicts(client, auth, make_requirement):
    req = make_requirement(title="需要材料")
    doc = upload(client, auth("pm"), title="被绑定的").get_json()
    client.post(f"/api/requirements/{req['id']}/documents",
                json={"document_id": doc["id"]}, headers=auth("pm"))
    r = client.delete(f"/api/documents/{doc['id']}", headers=auth("pm"))
    assert r.status_code == 409
    body = r.get_json()
    assert body["detail"]["links"] == 1
    # 前端看板拖拽以 err.allowed 是否存在分流 409 —— 这里绝不能带上它。
    assert "allowed" not in body


def test_force_delete_removes_links(client, auth, make_requirement):
    req = make_requirement(title="强删")
    doc = upload(client, auth("pm"), title="强删文档").get_json()
    client.post(f"/api/requirements/{req['id']}/documents",
                json={"document_id": doc["id"]}, headers=auth("pm"))
    r = client.delete(f"/api/documents/{doc['id']}?force=1", headers=auth("pm"))
    assert r.status_code == 204
    listed = client.get(f"/api/requirements/{req['id']}/documents",
                        headers=auth("pm")).get_json()
    assert listed == []
    feed = client.get(f"/api/requirements/{req['id']}/activities",
                      headers=auth("pm")).get_json()
    assert any(a["action"] == "doc_detached" for a in feed)


# ————————————————————— 下载 —————————————————————

def test_download_sets_nosniff_and_disposition(client, auth):
    doc = upload(client, auth("pm"), title="图片").get_json()
    r = client.get(f"/api/documents/{doc['id']}/download", headers=auth("member"))
    assert r.status_code == 200
    assert r.data == PNG
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Content-Type"] == "image/png"
    assert r.headers["Content-Disposition"].startswith("inline;")


def test_download_of_non_inline_mime_is_attachment(client, auth):
    doc = upload(client, auth("pm"), filename="包.zip",
                 payload=b"PK\x03\x04" + b"data").get_json()
    r = client.get(f"/api/documents/{doc['id']}/download", headers=auth("pm"))
    assert r.headers["Content-Disposition"].startswith("attachment;")
    # 中文名以 RFC 5987 百分号编码给出，不会被截断成乱码。
    assert "filename*=UTF-8''" in r.headers["Content-Disposition"]


def test_download_of_missing_blob_returns_410(client, auth, app):
    doc = upload(client, auth("pm"), title="丢文件").get_json()
    with app.app_context():
        from services.documents import storage
        import os

        os.remove(storage.blob_path(doc["current_version"]["sha256"]))
    r = client.get(f"/api/documents/{doc['id']}/download", headers=auth("pm"))
    assert r.status_code == 410
    assert r.get_json()["error"] == "document content is gone"


def test_download_of_foreign_version_id_returns_404(client, auth):
    a = upload(client, auth("pm"), title="A", payload=PNG + b"a").get_json()
    b = upload(client, auth("pm"), title="B", payload=PNG + b"b").get_json()
    r = client.get(f"/api/documents/{a['id']}/download"
                   f"?version_id={b['current_version']['id']}", headers=auth("pm"))
    assert r.status_code == 404


# ————————————————————— 全局副作用（R-12）—————————————————————

def test_existing_endpoints_unaffected_by_max_content_length(client, auth,
                                                             make_requirement):
    """`MAX_CONTENT_LENGTH` 是全局的，普通 JSON 写端点行为必须逐字不变。"""
    req = make_requirement(title="普通需求")
    assert client.patch(f"/api/requirements/{req['id']}",
                        json={"title": "改过的标题"}, headers=auth("pm")).status_code == 200
    assert client.post(f"/api/requirements/{req['id']}/comments",
                       json={"body": "一条评论"}, headers=auth("pm")).status_code == 201
    assert client.post("/api/requirements", json={"title": "另一张单"},
                       headers=auth("pm")).status_code == 201
