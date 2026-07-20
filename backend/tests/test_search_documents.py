"""发现用例（document-lifecycle-depth §7.2 支柱 A · A1~A10）。

覆盖：搜索文档桶、文件名命中、软删过滤、空信封、计数不放大，以及文档库的三个新参数
与详情 `links[]` 的 `entity_title` 富化。
"""
from sqlalchemy import event

from extensions import db
from test_documents import PNG, upload

MD = "# 支付方案\n\n内容。\n".encode("utf-8")


def upload_md(client, headers, *, title="支付方案", filename="payment-v2.md",
              kind="design", **fields):
    return upload(client, headers, filename=filename, payload=MD, title=title,
                  kind=kind, **fields)


def search(client, headers, keyword):
    return client.get(f"/api/search?q={keyword}", headers=headers)


def count_queries(app, fn):
    """执行 fn 并返回期间发出的 SQL 语句数（R-7 的 N+1 护栏用）。"""
    seen = []

    def _before(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    engine = db.engine
    event.listen(engine, "before_cursor_execute", _before)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", _before)
    return seen


# ————————————————————— A1 ~ A5 · 搜索 —————————————————————

def test_search_returns_documents_bucket(client, auth):
    upload_md(client, auth("pm"), title="支付网关方案")
    body = search(client, auth("member"), "支付").get_json()
    assert [d["title"] for d in body["documents"]] == ["支付网关方案"]
    assert body["counts"]["documents"] == 1
    assert body["documents"][0]["current_version"]["version_no"] == 1
    assert body["documents"][0]["link_count"] == 0


def test_search_matches_original_filename(client, auth):
    """用户记得住的常常是 `payment-v2.md` 这个文件名，而不是上传时随手写的标题。"""
    upload_md(client, auth("pm"), title="毫无关系的标题", filename="payment-v2.md")
    body = search(client, auth("member"), "payment-v2").get_json()
    assert body["counts"]["documents"] == 1
    assert body["documents"][0]["title"] == "毫无关系的标题"


def test_search_matches_description(client, auth):
    upload_md(client, auth("pm"), title="标题", filename="a.md",
              description="关于超时重试的说明")
    body = search(client, auth("member"), "超时").get_json()
    assert body["counts"]["documents"] == 1


def test_search_excludes_trashed_documents(client, auth):
    """【铁律】回收站里的文档绝不出现在搜索里——否则搜得到、点进去 404。"""
    doc = upload_md(client, auth("pm"), title="支付旧稿").get_json()
    assert search(client, auth("pm"), "支付").get_json()["counts"]["documents"] == 1
    client.delete(f"/api/documents/{doc['id']}", headers=auth("pm"))
    body = search(client, auth("pm"), "支付").get_json()
    assert body["documents"] == []
    assert body["counts"]["documents"] == 0


def test_empty_query_envelope_has_documents_key(client, auth):
    """【前端崩溃的唯一护栏】空信封必须与 `search_all` 同形状。"""
    body = client.get("/api/search?q=", headers=auth("member")).get_json()
    assert body["documents"] == []
    assert body["counts"] == {"requirements": 0, "bugs": 0, "documents": 0}
    assert set(body) == {"query", "requirements", "bugs", "documents", "counts"}


def test_search_counts_documents_once(client, auth):
    """outerjoin 固定到 `current_version_id`（一对一），`count()` 不放大。

    若将来把 join 改成关联 `document_versions.document_id`（一对多），一份有 3 个版本的
    文档会被数成 3 条——这条用例就是那条约束的护栏。
    """
    doc = upload_md(client, auth("pm"), title="支付多版本").get_json()
    for i in range(2):
        client.post(f"/api/documents/{doc['id']}/versions",
                    json={"content": f"# 支付方案 v{i + 2}\n"}, headers=auth("pm"))
    body = search(client, auth("pm"), "支付").get_json()
    assert body["counts"]["documents"] == 1
    assert len(body["documents"]) == 1


def test_search_still_returns_requirements_and_bugs(client, auth, make_requirement):
    """既有两个桶逐字节不变。"""
    make_requirement(title="支付需求")
    client.post("/api/bugs", json={"title": "支付 BUG"}, headers=auth("pm"))
    body = search(client, auth("pm"), "支付").get_json()
    assert body["counts"]["requirements"] == 1
    assert body["counts"]["bugs"] == 1
    assert body["counts"]["documents"] == 0


# ————————————————————— A6 ~ A8 · 文档库检索 —————————————————————

def test_list_sort_by_size_and_links(client, auth, app, make_requirement):
    small = upload(client, auth("pm"), title="小", filename="a.md",
                   payload=b"# a\n").get_json()
    big = upload(client, auth("pm"), title="大", filename="b.md",
                 payload=b"# b\n" + b"x" * 5000).get_json()
    req = make_requirement(title="绑定用")
    client.post(f"/api/requirements/{req['id']}/documents",
                json={"document_id": small["id"]}, headers=auth("pm"))

    by_size = client.get("/api/documents?sort=size", headers=auth("pm")).get_json()
    assert [d["id"] for d in by_size] == [big["id"], small["id"]]

    by_links = client.get("/api/documents?sort=links", headers=auth("pm")).get_json()
    assert by_links[0]["id"] == small["id"]

    by_title = client.get("/api/documents?sort=title", headers=auth("pm")).get_json()
    assert [d["title"] for d in by_title] == ["大", "小"]


def test_list_sort_by_links_stays_a_single_query(client, auth, app):
    """【R-7】`sort=links` 一律走 group_by 子查询 join，不得退化成逐行 count。"""
    for i in range(5):
        upload(client, auth("pm"), title=f"文档{i}", filename=f"f{i}.md",
               payload=f"# {i}\n".encode()).get_json()
    headers = auth("pm")
    with app.app_context():
        statements = count_queries(
            app, lambda: client.get("/api/documents?sort=links", headers=headers))
    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")
               and "documents" in s]
    # 列表页固定为「主查询 + 计数 + 批量 link_count + 批量版本」这一档，
    # 与文档条数无关；5 行绝不允许发出 5 次子查询。
    assert len(selects) <= 6, statements


def test_list_rejects_unknown_sort_with_400(client, auth):
    """非枚举值 400，**不静默回退**——与 `want_str(choices=...)` 同款态度。"""
    r = client.get("/api/documents?sort=whatever", headers=auth("pm"))
    assert r.status_code == 400
    assert r.get_json()["detail"]["field"] == "sort"


def test_default_sort_is_unchanged(client, auth):
    first = upload(client, auth("pm"), title="先", filename="a.md",
                   payload=b"a").get_json()
    second = upload(client, auth("pm"), title="后", filename="b.md",
                    payload=b"b").get_json()
    listed = client.get("/api/documents", headers=auth("pm")).get_json()
    assert [d["id"] for d in listed] == [second["id"], first["id"]]


def test_list_unlinked_filter(client, auth, make_requirement):
    bound = upload(client, auth("pm"), title="用上了", filename="a.md",
                   payload=b"a").get_json()
    orphan = upload(client, auth("pm"), title="传了没用", filename="b.md",
                    payload=b"b").get_json()
    req = make_requirement(title="单")
    client.post(f"/api/requirements/{req['id']}/documents",
                json={"document_id": bound["id"]}, headers=auth("pm"))
    listed = client.get("/api/documents?unlinked=1", headers=auth("pm")).get_json()
    assert [d["id"] for d in listed] == [orphan["id"]]


def test_list_uploader_filter_still_works(client, auth, data):
    """`uploader_id` 后端早已实现——本轮只是前端补 UI，不重复实现一遍后端。"""
    mine = upload(client, auth("member"), title="我的").get_json()
    upload(client, auth("pm"), title="别人的")
    listed = client.get(f"/api/documents?uploader_id={data['member_id']}",
                        headers=auth("pm")).get_json()
    assert [d["id"] for d in listed] == [mine["id"]]


# ————————————————————— A9 ~ A10 · 详情 links 富化 —————————————————————

def test_detail_links_carry_entity_title(client, auth, make_requirement):
    """「这份文档正被这几张单使用」是用户决定「能不能改这份 PRD」的第一个问题。"""
    doc = upload_md(client, auth("pm"), title="共用契约").get_json()
    req = make_requirement(title="需求甲")
    bug = client.post("/api/bugs", json={"title": "缺陷乙"},
                      headers=auth("pm")).get_json()
    client.post(f"/api/requirements/{req['id']}/documents",
                json={"document_id": doc["id"]}, headers=auth("pm"))
    client.post(f"/api/bugs/{bug['id']}/documents",
                json={"document_id": doc["id"]}, headers=auth("pm"))

    detail = client.get(f"/api/documents/{doc['id']}", headers=auth("member")).get_json()
    titles = {(l["entity_type"], l["entity_title"]) for l in detail["links"]}
    assert titles == {("requirement", "需求甲"), ("bug", "缺陷乙")}


def test_detail_link_titles_are_fetched_in_bulk(client, auth, app,
                                                make_requirement):
    """每种实体至多 1 次查询，**不得逐 link 查一次**（一份绑 60 张单就是 60 次往返）。"""
    doc = upload_md(client, auth("pm"), title="批量取").get_json()
    for i in range(5):
        req = make_requirement(title=f"单 {i}")
        client.post(f"/api/requirements/{req['id']}/documents",
                    json={"document_id": doc["id"]}, headers=auth("pm"))
    headers = auth("pm")
    with app.app_context():
        statements = count_queries(
            app, lambda: client.get(f"/api/documents/{doc['id']}", headers=headers))
    requirement_selects = [s for s in statements
                           if s.lstrip().upper().startswith("SELECT")
                           and "FROM requirements" in s]
    assert len(requirement_selects) == 1, requirement_selects


def test_detail_link_title_survives_deleted_ticket(client, auth, app,
                                                   make_requirement):
    """工单已被删（link 理论上已级联删除）→ 防御性路径返回占位而非 500。"""
    from models.document_link import DocumentLink

    doc = upload_md(client, auth("pm"), title="孤儿绑定").get_json()
    req = make_requirement(title="将被删")
    client.post(f"/api/requirements/{req['id']}/documents",
                json={"document_id": doc["id"]}, headers=auth("pm"))
    with app.app_context():
        link = DocumentLink.query.filter_by(document_id=doc["id"]).one()
        link.entity_id = 999999                       # 指向一张不存在的单
        db.session.commit()

    r = client.get(f"/api/documents/{doc['id']}", headers=auth("pm"))
    assert r.status_code == 200
    assert r.get_json()["links"][0]["entity_title"] is None
