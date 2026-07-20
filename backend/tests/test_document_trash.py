"""回收站用例（document-lifecycle-depth §7.2 支柱 D）。

覆盖：软删语义、八处过滤点、恢复、`?purge=1` 的 403/404/409、**带绑定的 purge 不 500**
（D16 · P0 护栏）、GC 与软删的相互作用、CLI dry-run 零副作用、存量库补列。
"""
import io
import os
import time

from extensions import db, utcnow
from models.document import Document, DocumentVersion
from models.document_link import DocumentLink
from test_documents import PNG, upload

MD = "# 测试报告\n\n全部通过。\n".encode("utf-8")


def upload_md(client, headers, *, title="报告", kind="test_report", body=MD):
    return upload(client, headers, filename="report.md", payload=body,
                  title=title, kind=kind)


def attach(client, headers, entity, ticket_id, *, kind="test_report",
           filename="report.md", payload=MD):
    data = {"file": (io.BytesIO(payload), filename), "kind": kind}
    return client.post(f"/api/{entity}/{ticket_id}/documents", data=data,
                       headers=headers, content_type="multipart/form-data")


def bind(client, headers, entity, ticket_id, document_id):
    return client.post(f"/api/{entity}/{ticket_id}/documents",
                       json={"document_id": document_id}, headers=headers)


def delete(client, headers, document_id, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"/api/documents/{document_id}" + (f"?{query}" if query else "")
    return client.delete(url, headers=headers)


def trash_keeping_links(app, document_id, actor_user_id=None):
    """把文档移进回收站但**保留全部绑定**——D 组过滤点用例的必要前提。

    【为什么不走 HTTP，以及为什么这不是偷懒】两条 HTTP 删除路径都到不了「在回收站里 +
    仍有绑定」这个状态：不带 `force` 对有绑定的文档返回 **409**（既有契约，§2.4 D-1
    明确保留），带 `force` 则先 `detach_all_links` 再软删。

    而过滤点 3 / 4 / 5（抽屉列表 / 阶段清单 / 徽章计数）守的**恰恰是这个状态**。若用
    `force` 造样本，抽屉、清单、徽章的下降是**解绑**造成的——八处过滤点一行不写，用例
    也照样全绿。那正是一条抓不到自己那类 bug 的用例，比没有用例更危险。
    （这条约束本身是实施期发现的方案缺陷，已记入 spec 的「实施过程发现的方案缺陷」。）
    """
    with app.app_context():
        from services.documents import trash

        document = db.session.get(Document, document_id)
        trash.soft_delete(document, ("user", actor_user_id))
        db.session.commit()


# ————————————————————— D1 ~ D2 · 软删本身 —————————————————————

def test_delete_soft_deletes_and_keeps_row(client, auth, app):
    doc = upload(client, auth("pm"), title="待删").get_json()
    assert delete(client, auth("pm"), doc["id"]).status_code == 204
    with app.app_context():
        row = db.session.get(Document, doc["id"])
        assert row is not None                       # 行还在
        assert row.deleted_at is not None            # 只是被置位
        assert row.deleted_by_id is not None
        assert DocumentVersion.query.filter_by(document_id=row.id).count() == 1


def test_deleted_document_is_404_everywhere(client, auth):
    """详情 / 下载 / content / 改版 / 元信息编辑——五个端点一律 404。"""
    doc = upload_md(client, auth("pm")).get_json()
    version_id = doc["current_version"]["id"]
    assert delete(client, auth("pm"), doc["id"]).status_code == 204
    headers = auth("pm")
    assert client.get(f"/api/documents/{doc['id']}", headers=headers).status_code == 404
    assert client.get(f"/api/documents/{doc['id']}/download",
                      headers=headers).status_code == 404
    assert client.get(f"/api/documents/{doc['id']}/content",
                      headers=headers).status_code == 404
    assert client.post(f"/api/documents/{doc['id']}/versions",
                       json={"content": "x"}, headers=headers).status_code == 404
    assert client.patch(f"/api/documents/{doc['id']}",
                        json={"title": "y"}, headers=headers).status_code == 404
    # 版本 id 仍在库里，但入口已被过滤——不存在「绕过文档拿版本」的路径。
    assert version_id


def test_deleted_document_leaves_the_library_list(client, auth):
    doc = upload(client, auth("pm"), title="消失吧").get_json()
    delete(client, auth("pm"), doc["id"])
    listed = client.get("/api/documents", headers=auth("member")).get_json()
    assert [d["id"] for d in listed] == []


# ————————————————————— D3 ~ D6 · 过滤点 —————————————————————

def test_deleted_document_leaves_ticket_panel(client, auth, app, make_requirement):
    """【过滤点 3】绑定**仍在**，抽屉里也必须看不见它。"""
    req = make_requirement(title="抽屉")
    body = attach(client, auth("pm"), "requirements", req["id"]).get_json()
    trash_keeping_links(app, body["document"]["id"])
    with app.app_context():
        assert DocumentLink.query.filter_by(
            document_id=body["document"]["id"]).count() == 1
    listed = client.get(f"/api/requirements/{req['id']}/documents",
                        headers=auth("pm")).get_json()
    assert listed == []


def test_deleted_document_no_longer_satisfies_checklist(client, auth, app, data,
                                                        make_requirement):
    """【过滤点 4 · 八处里最隐蔽的一处】阶段清单必须重新变红。

    `bound_kinds` 是清单与门禁的**唯一**判据来源。漏掉那一行 join 过滤不会抛任何异常，
    只会让一份已删文档继续把清单项点绿、继续让门禁放行。
    """
    req = make_requirement(title="清单", assignee=("user", data["pm_id"]))
    client.patch(f"/api/requirements/{req['id']}/move",
                 json={"status": "in_development"}, headers=auth("pm"))
    body = attach(client, auth("pm"), "requirements", req["id"],
                  kind="requirement_spec").get_json()

    before = client.get(f"/api/requirements/{req['id']}/document-checklist",
                        headers=auth("pm")).get_json()
    spec = [i for i in before["items"] if i["kind"] == "requirement_spec"][0]
    assert spec["satisfied"] is True

    trash_keeping_links(app, body["document"]["id"])   # 绑定仍在，只是文档进了回收站
    after = client.get(f"/api/requirements/{req['id']}/document-checklist",
                       headers=auth("pm")).get_json()
    spec = [i for i in after["items"] if i["kind"] == "requirement_spec"][0]
    assert spec["satisfied"] is False
    assert spec["document_ids"] == []


def test_deleted_document_drops_out_of_badge_count(client, auth, app,
                                                   make_requirement):
    """【过滤点 5】看板 / 列表的回形针徽章数字必须同步下降（绑定仍在的前提下）。"""
    req = make_requirement(title="徽章")
    first = attach(client, auth("pm"), "requirements", req["id"]).get_json()
    attach(client, auth("pm"), "requirements", req["id"],
           kind="design", payload=b"# design\n").get_json()
    detail = client.get(f"/api/requirements/{req['id']}", headers=auth("pm")).get_json()
    assert detail["document_count"] == 2

    trash_keeping_links(app, first["document"]["id"])
    detail = client.get(f"/api/requirements/{req['id']}", headers=auth("pm")).get_json()
    assert detail["document_count"] == 1
    listed = client.get("/api/requirements", headers=auth("pm")).get_json()
    assert [t for t in listed if t["id"] == req["id"]][0]["document_count"] == 1


def test_cannot_bind_deleted_document(client, auth, make_requirement):
    """【过滤点 7】否则回收站语义直接失效：删掉的文档又出现在别的单的抽屉里。"""
    req = make_requirement(title="重绑")
    doc = upload(client, auth("pm"), title="孤本").get_json()
    delete(client, auth("pm"), doc["id"])
    r = bind(client, auth("pm"), "requirements", req["id"], doc["id"])
    assert r.status_code == 404


# ————————————————————— D7 ~ D8 · 恢复 —————————————————————

def test_restore_brings_back_links_and_checklist(client, auth, app, data,
                                                 make_requirement):
    """恢复后 D3 / D4 / D5 全部逆转——绑定关系从未解除过，这是软删的全部价值。"""
    req = make_requirement(title="恢复", assignee=("user", data["pm_id"]))
    client.patch(f"/api/requirements/{req['id']}/move",
                 json={"status": "in_development"}, headers=auth("pm"))
    body = attach(client, auth("pm"), "requirements", req["id"],
                  kind="requirement_spec").get_json()
    document_id = body["document"]["id"]
    stage_before = body["link"]["stage"]

    trash_keeping_links(app, document_id)                   # 软删不动 links
    r = client.post(f"/api/documents/{document_id}/restore", headers=auth("pm"))
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["deleted_at"] is None

    listed = client.get(f"/api/requirements/{req['id']}/documents",
                        headers=auth("pm")).get_json()
    assert [d["id"] for d in listed] == [document_id]
    assert listed[0]["link"]["stage"] == stage_before       # 快照原样回来
    checklist = client.get(f"/api/requirements/{req['id']}/document-checklist",
                           headers=auth("pm")).get_json()
    assert [i for i in checklist["items"]
            if i["kind"] == "requirement_spec"][0]["satisfied"] is True
    detail = client.get(f"/api/requirements/{req['id']}", headers=auth("pm")).get_json()
    assert detail["document_count"] == 1


def test_force_deleted_document_restores_without_its_links(client, auth,
                                                           make_requirement):
    """§2.4 D-3 的**例外**：走 `?force=1` 的那些，links 已被解除，恢复只回本体。

    前端恢复确认框必须如实说明这一点——用户点「恢复」时以为绑定也会回来，是最容易
    发生的一次误解。
    """
    req = make_requirement(title="强删再恢复")
    body = attach(client, auth("pm"), "requirements", req["id"]).get_json()
    document_id = body["document"]["id"]
    assert delete(client, auth("pm"), document_id, force=1).status_code == 204
    assert client.post(f"/api/documents/{document_id}/restore",
                       headers=auth("pm")).status_code == 200
    listed = client.get(f"/api/requirements/{req['id']}/documents",
                        headers=auth("pm")).get_json()
    assert listed == []                                  # 绑定不会自动回来
    library = client.get("/api/documents", headers=auth("pm")).get_json()
    assert document_id in [d["id"] for d in library]     # 但本体回来了


def test_restore_of_live_document_returns_409(client, auth):
    doc = upload(client, auth("pm"), title="活的").get_json()
    r = client.post(f"/api/documents/{doc['id']}/restore", headers=auth("pm"))
    assert r.status_code == 409
    assert r.get_json()["detail"]["reason"] == "not_deleted"
    assert "allowed" not in r.get_json()["detail"]     # 409 一律不带 allowed 键


def test_restore_requires_manage_permission(client, auth):
    doc = upload(client, auth("pm"), title="别人的").get_json()
    delete(client, auth("pm"), doc["id"])
    r = client.post(f"/api/documents/{doc['id']}/restore", headers=auth("member"))
    assert r.status_code == 403


# ————————————————————— D9 ~ D11、D16 · 彻底删除 —————————————————————

def test_purge_requires_admin(client, auth):
    """pm 也不行——`?purge=1` 是全系统唯一不可逆的文档操作。"""
    doc = upload(client, auth("pm"), title="待清").get_json()
    delete(client, auth("pm"), doc["id"])
    assert delete(client, auth("pm"), doc["id"], purge=1).status_code == 403
    assert delete(client, auth("member"), doc["id"], purge=1).status_code == 403
    assert delete(client, auth("admin"), doc["id"], purge=1).status_code == 204


def test_purge_only_works_on_trashed(client, auth):
    doc = upload(client, auth("pm"), title="没删过").get_json()
    r = delete(client, auth("admin"), doc["id"], purge=1)
    assert r.status_code == 409
    assert r.get_json()["detail"]["reason"] == "not_deleted"


def test_purge_of_unknown_document_returns_404(client, auth):
    assert delete(client, auth("admin"), 999999, purge=1).status_code == 404


def test_purge_removes_rows_and_reaps_blob(client, auth, app):
    """行没了、摘要**进入回收判定集合**。

    【评审 V-18】断言的是「进入 `unreferenced_digests`」而不是「文件已从磁盘消失」：
    `storage.delete_blob` 带宽限窗口（`is_reapable` / `_grace_seconds`），刚落盘的 blob
    立刻 purge **不会**被物理删除——按后者写会得到一条随时间随机失败的用例。
    """
    doc = upload(client, auth("pm"), title="彻底删").get_json()
    digest = doc["current_version"]["sha256"]
    delete(client, auth("pm"), doc["id"])
    assert delete(client, auth("admin"), doc["id"], purge=1).status_code == 204
    with app.app_context():
        from services.documents import service

        assert db.session.get(Document, doc["id"]) is None
        assert DocumentVersion.query.filter_by(document_id=doc["id"]).count() == 0
        assert service.unreferenced_digests({digest}) == {digest}


def test_purge_document_that_still_has_links(client, auth, app, make_requirement):
    """【D16 · P0 护栏（评审 V-02）】一份**仍绑着 2 张单**的回收站文档被 purge。

    软删刻意不解绑，所以「回收站里的文档仍有绑定」是**常态**而非边界。
    `document_links.document_id` 是真外键且 `PRAGMA foreign_keys=ON` 每连接生效——
    若 `trash.purge` 不自包含地先解绑，这里就是 500 而不是 204。
    D11 拿的是无绑定文档，天生撞不到这个外键。
    """
    first = make_requirement(title="单一")
    second = make_requirement(title="单二")
    body = attach(client, auth("pm"), "requirements", first["id"]).get_json()
    document_id = body["document"]["id"]
    assert bind(client, auth("pm"), "requirements", second["id"],
                document_id).status_code == 201

    trash_keeping_links(app, document_id)      # 软删不动 links（见该 helper 的 docstring）
    with app.app_context():
        assert DocumentLink.query.filter_by(document_id=document_id).count() == 2

    r = delete(client, auth("admin"), document_id, purge=1)
    assert r.status_code == 204, r.get_json()          # ← 不是 500
    with app.app_context():
        assert DocumentLink.query.filter_by(document_id=document_id).count() == 0
        assert db.session.get(Document, document_id) is None

    for ticket in (first, second):
        acts = client.get(f"/api/requirements/{ticket['id']}/activities",
                          headers=auth("pm")).get_json()
        assert any(a["action"] == "doc_detached" for a in acts)


# ————————————————————— D12 ~ D13 · GC 与时间线 —————————————————————

def test_gc_keeps_blobs_of_soft_deleted_documents(client, auth, app):
    """软删期间 blob **绝不**被 GC 回收——恢复出空壳的唯一护栏。

    这条性质靠不变量成立（软删不删 `document_versions` 行，故摘要仍被引用），
    不需要任何新代码；但它极易被将来某次「优化」打破，因此必须钉死。
    """
    from tools import gc_orphan_blobs

    doc = upload(client, auth("pm"), title="别删我的字节").get_json()
    delete(client, auth("pm"), doc["id"])
    with app.app_context():
        from services.documents import storage

        path = storage.blob_path(doc["current_version"]["sha256"])
        old = time.time() - 7200                     # 调老到宽限窗口之外
        os.utime(path, (old, old))
        report = gc_orphan_blobs.scan()
        assert str(path) not in [p for p, _ in report["reapable"]]
        assert report["referenced"] == 1


def test_trash_writes_activity_on_each_link(client, auth, app, make_requirement):
    req = make_requirement(title="时间线")
    body = attach(client, auth("pm"), "requirements", req["id"]).get_json()
    trash_keeping_links(app, body["document"]["id"])
    acts = client.get(f"/api/requirements/{req['id']}/activities",
                      headers=auth("pm")).get_json()
    assert any(a["action"] == "doc_trashed" for a in acts)

    client.post(f"/api/documents/{body['document']['id']}/restore", headers=auth("pm"))
    acts = client.get(f"/api/requirements/{req['id']}/activities",
                      headers=auth("pm")).get_json()
    assert any(a["action"] == "doc_restored" for a in acts)


def test_trash_and_restore_send_no_notification(client, auth, make_requirement, app):
    """软删 / 恢复都是收敛性操作，与 `doc_detached` 同源取向：不占用注意力预算。"""
    from models.notification import Notification

    req = make_requirement(title="不打扰")
    body = attach(client, auth("pm"), "requirements", req["id"]).get_json()
    with app.app_context():
        before = Notification.query.count()
    trash_keeping_links(app, body["document"]["id"])
    client.post(f"/api/documents/{body['document']['id']}/restore", headers=auth("pm"))
    with app.app_context():
        assert Notification.query.count() == before


# ————————————————————— 回收站视图 —————————————————————

def test_trash_view_lists_only_deleted(client, auth):
    live = upload(client, auth("pm"), title="活的").get_json()
    gone = upload(client, auth("pm"), title="死的", kind="design").get_json()
    delete(client, auth("pm"), gone["id"])
    listed = client.get("/api/documents?deleted=1", headers=auth("pm")).get_json()
    assert [d["id"] for d in listed] == [gone["id"]]
    assert listed[0]["deleted_at"] is not None
    assert listed[0]["deleted_by"]["id"]
    assert live["id"] not in [d["id"] for d in listed]


def test_trash_view_scopes_non_privileged_users_to_their_own(client, auth):
    """【评审 V-12】非 pm/admin 自动附加 `uploader_id = me`；显式传别人的 id 不报错。"""
    mine = upload(client, auth("member"), title="我的").get_json()
    others = upload(client, auth("pm"), title="别人的").get_json()
    delete(client, auth("member"), mine["id"])
    delete(client, auth("pm"), others["id"])

    listed = client.get("/api/documents?deleted=1", headers=auth("member")).get_json()
    assert [d["id"] for d in listed] == [mine["id"]]
    # 显式传别人的 uploader_id：以自动值为准，**静默收紧，不 400**。
    listed = client.get("/api/documents?deleted=1&uploader_id=1",
                        headers=auth("member")).get_json()
    assert [d["id"] for d in listed] == [mine["id"]]

    listed = client.get("/api/documents?deleted=1", headers=auth("pm")).get_json()
    assert {d["id"] for d in listed} == {mine["id"], others["id"]}


def test_documents_meta_exposes_templates_and_retention(client, auth, app):
    body = client.get("/api/documents/meta", headers=auth("member")).get_json()
    assert body["trash_retention_days"] == app.config["DOC_TRASH_RETENTION_DAYS"]
    kinds = [t["kind"] for t in body["templates"]]
    assert "test_plan" in kinds and "bug_evidence" not in kinds
    assert all(t["label"] and t["summary"] for t in body["templates"])


# ————————————————————— D14 · CLI —————————————————————

def test_purge_trash_cli_dry_run_changes_nothing(client, auth, app):
    from services.documents import trash
    from tools import purge_trash

    doc = upload(client, auth("pm"), title="过期的").get_json()
    delete(client, auth("pm"), doc["id"])
    with app.app_context():
        row = db.session.get(Document, doc["id"])
        row.deleted_at = utcnow() - __import__("datetime").timedelta(days=90)
        db.session.commit()

        report = purge_trash.run(days=30, dry_run=True)
        assert report["expired"] == 1
        assert len(report["deleted"]) == 1
        assert report["blobs_reaped"] == 0
        db.session.expire_all()
        assert db.session.get(Document, doc["id"]) is not None   # 零副作用
        assert Document.query.filter(trash.is_deleted()).count() == 1


def test_purge_trash_cli_apply_deletes_expired_only(client, auth, app):
    import datetime

    from tools import purge_trash

    old = upload(client, auth("pm"), title="过期").get_json()
    fresh = upload(client, auth("pm"), title="新删的", kind="design").get_json()
    delete(client, auth("pm"), old["id"])
    delete(client, auth("pm"), fresh["id"])
    with app.app_context():
        db.session.get(Document, old["id"]).deleted_at = \
            utcnow() - datetime.timedelta(days=90)
        db.session.commit()

        report = purge_trash.run(days=30, dry_run=False)
        assert [d["id"] for d in report["deleted"]] == [old["id"]]
        assert report["skipped"] == []
        assert db.session.get(Document, old["id"]) is None
        assert db.session.get(Document, fresh["id"]) is not None


def test_purge_trash_cli_isolates_a_failing_document(client, auth, app, monkeypatch):
    """一份文档清理失败**绝不能**连累已经处理完的那些——尤其不能删掉它们的 blob。

    这是实施期复审发现的一个真实数据损毁路径：`db.session` 只有一个事务，若攒到循环
    之后再一次性 commit，那么中途任何一次 `rollback()` 都会把本批**已经处理过的全部
    文档**一起回滚；而它们的摘要早已并进待回收集合，随后的 `reap()` 会删掉这些「已经
    复活」的文档的物理文件——留下一批行还在、下载恒 410 的空壳，版本历史不可恢复。

    **dry-run 抓不到它**（全程回滚且从不 reap），只有 `--apply` 会踩到。
    """
    import datetime

    from services.documents import trash as trash_module
    from tools import purge_trash

    first = upload(client, auth("pm"), title="先处理的", payload=PNG).get_json()
    second = upload(client, auth("pm"), title="会失败的",
                    payload=PNG + b"other").get_json()
    for doc in (first, second):
        delete(client, auth("pm"), doc["id"])
    with app.app_context():
        for doc in (first, second):
            db.session.get(Document, doc["id"]).deleted_at = \
                utcnow() - datetime.timedelta(days=90)
        db.session.commit()

        original = trash_module.purge

        def _purge(document, actor):
            if document.id == second["id"]:
                raise RuntimeError("simulated failure on the second document")
            return original(document, actor)

        monkeypatch.setattr(purge_trash_target(), "purge", _purge)
        report = purge_trash.run(days=30, dry_run=False)

        assert [d["id"] for d in report["deleted"]] == [first["id"]]
        assert [s["id"] for s in report["skipped"]] == [second["id"]]
        # 第一份**确实**被删掉了（没有被第二份的 rollback 拖回来）……
        assert db.session.get(Document, first["id"]) is None
        # ……第二份**确实**还在（它自己的那次 purge 被回滚了）。
        survivor = db.session.get(Document, second["id"])
        assert survivor is not None
        assert survivor.deleted_at is not None
        # 关键断言：幸存者的 blob 绝不能被回收——它的行还在，文件必须还在。
        from services.documents import storage

        assert storage.blob_path(second["current_version"]["sha256"]).exists()


def purge_trash_target():
    """`tools.purge_trash.run` 在函数体内 import `trash`，故 monkeypatch 要打在源模块上。"""
    from services.documents import trash as trash_module

    return trash_module


def test_purge_trash_cli_survives_a_document_with_links(client, auth, app,
                                                        make_requirement):
    """CLI 与 `?purge=1` 共用 `trash.purge`，故带绑定的过期文档同样不能崩（评审 V-02）。"""
    import datetime

    from tools import purge_trash

    req = make_requirement(title="CLI")
    body = attach(client, auth("pm"), "requirements", req["id"]).get_json()
    trash_keeping_links(app, body["document"]["id"])
    with app.app_context():
        db.session.get(Document, body["document"]["id"]).deleted_at = \
            utcnow() - datetime.timedelta(days=90)
        db.session.commit()

        report = purge_trash.run(days=30, dry_run=False)
        assert len(report["deleted"]) == 1
        assert report["skipped"] == []
        assert DocumentLink.query.filter_by(
            document_id=body["document"]["id"]).count() == 0


# ————————————————————— D15 · 存量库补列 —————————————————————

def test_schema_sync_adds_document_trash_columns():
    """【CLAUDE.md 硬约束的直接护栏】漏登记则存量库每一次文档查询都 no such column。"""
    from services.schema_sync import ADDITIVE_COLUMNS

    registered = {(t, c) for t, c, _ in ADDITIVE_COLUMNS}
    assert ("documents", "deleted_at") in registered
    assert ("documents", "deleted_by_id") in registered


def test_schema_sync_backfills_columns_on_a_legacy_database(tmp_path):
    """在一张**缺列的存量 documents 表**上启动，补列必须真实发生。"""
    import sqlite3

    from config import Config
    from services.schema_sync import sync_additive_columns
    from sqlalchemy import create_engine

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, title TEXT)")
    conn.commit()
    conn.close()

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        applied = sync_additive_columns(engine)
        assert "documents.deleted_at" in applied
        assert "documents.deleted_by_id" in applied
        assert sync_additive_columns(engine) == []      # 幂等
    finally:
        engine.dispose()
    assert Config.DOC_TRASH_RETENTION_DAYS >= 1
