"""文档模板用例（document-lifecycle-depth §7.2 支柱 C · C1~C3）。

覆盖：`template_kind` 三态分支、清单闭环、400 与 `detail.allowed`、
`create_text_document` 的四条自持不变量、`agent:` 保留前缀的 400 前置校验。
"""
import pytest

from extensions import db
from models.document import Document
from services.documents import templates


def create_from_template(client, headers, entity, ticket_id, kind, **extra):
    payload = {"template_kind": kind}
    payload.update(extra)
    return client.post(f"/api/{entity}/{ticket_id}/documents", json=payload,
                       headers=headers)


# ————————————————————— C1 ~ C3 · 端点三态 —————————————————————

def test_template_kind_creates_and_binds_document(client, auth, make_requirement):
    req = make_requirement(title="支付网关")
    r = create_from_template(client, auth("pm"), "requirements", req["id"], "test_plan")
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert body["document"]["kind"] == "test_plan"
    assert body["document"]["title"] == "支付网关 · 测试计划"
    assert body["document"]["current_version"]["version_no"] == 1
    assert body["document"]["current_version"]["original_filename"] == \
        f"test_plan-requirement-{req['id']}.md"
    assert body["document"]["current_version"]["mime_type"] == "text/markdown"
    assert body["link"]["stage"] == "new"          # 工单当前状态的快照

    listed = client.get(f"/api/requirements/{req['id']}/documents",
                        headers=auth("pm")).get_json()
    assert [d["id"] for d in listed] == [body["document"]["id"]]


def test_template_body_carries_known_facts_only(client, auth, make_requirement):
    """占位符只用已知事实填充，**绝不编造内容**——自称「全部通过」的空报告更危险。"""
    req = make_requirement(title="登录超时")
    body = create_from_template(client, auth("pm"), "requirements", req["id"],
                                "test_report").get_json()
    content = client.get(f"/api/documents/{body['document']['id']}/content",
                         headers=auth("pm")).get_json()["content"]
    assert f"REQ-{req['id']}" in content
    assert "登录超时" in content
    assert "## 用例执行结果" in content
    assert content.count("待填写") >= 4
    assert "通过" not in content.replace("全部通过", "")   # 不含任何结论性断言


def test_template_document_satisfies_stage_checklist(client, auth, data,
                                                     make_requirement):
    """【闭环的证据】建完之后清单对应项立刻变绿。"""
    req = make_requirement(title="闭环", assignee=("user", data["pm_id"]))
    client.patch(f"/api/requirements/{req['id']}/move",
                 json={"status": "assigned"}, headers=auth("pm"))
    before = client.get(f"/api/requirements/{req['id']}/document-checklist",
                        headers=auth("pm")).get_json()
    assert before["satisfied"] is False

    create_from_template(client, auth("pm"), "requirements", req["id"],
                         "requirement_spec")
    after = client.get(f"/api/requirements/{req['id']}/document-checklist",
                       headers=auth("pm")).get_json()
    assert after["satisfied"] is True
    assert [i for i in after["items"]
            if i["kind"] == "requirement_spec"][0]["document_ids"]


def test_unknown_template_kind_returns_400_with_allowed(client, auth,
                                                        make_requirement):
    req = make_requirement(title="错的类别")
    r = create_from_template(client, auth("pm"), "requirements", req["id"],
                             "bug_evidence")
    assert r.status_code == 400
    assert set(r.get_json()["detail"]["allowed"]) == set(templates.TEMPLATE_KINDS)
    assert "bug_evidence" not in r.get_json()["detail"]["allowed"]


def test_template_title_over_200_returns_400(client, auth, make_requirement):
    req = make_requirement(title="超长")
    r = create_from_template(client, auth("pm"), "requirements", req["id"],
                             "design", title="x" * 201)
    assert r.status_code == 400
    assert r.get_json()["detail"]["field"] == "title"


def test_template_requires_manage_ticket(client, auth, make_requirement):
    req = make_requirement(title="别人的单")
    assert create_from_template(client, auth("member2"), "requirements", req["id"],
                                "design").status_code == 403


def test_template_works_for_bugs_too(client, auth):
    created = client.post("/api/bugs", json={"title": "登录 500"},
                          headers=auth("pm")).get_json()
    body = create_from_template(client, auth("pm"), "bugs", created["id"],
                                "test_report").get_json()
    content = client.get(f"/api/documents/{body['document']['id']}/content",
                         headers=auth("pm")).get_json()["content"]
    assert f"BUG-{created['id']}" in content


def test_bind_existing_branch_is_untouched(client, auth, make_requirement):
    """三态里的第一态（绑定已有）逐字节不变。"""
    from test_documents import upload

    req = make_requirement(title="绑已有")
    doc = upload(client, auth("pm"), title="现成的").get_json()
    r = client.post(f"/api/requirements/{req['id']}/documents",
                    json={"document_id": doc["id"]}, headers=auth("pm"))
    assert r.status_code == 201
    assert r.get_json()["document"]["id"] == doc["id"]


def test_json_without_document_id_or_template_kind_still_400(client, auth,
                                                             make_requirement):
    req = make_requirement(title="第三态")
    r = client.post(f"/api/requirements/{req['id']}/documents", json={"nope": 1},
                    headers=auth("pm"))
    assert r.status_code == 400


# ————————————————————— 保留前缀（评审 V-17） —————————————————————

def test_reserved_agent_label_is_rejected(client, auth, make_requirement):
    """`agent:` 前缀为 Agent 归档保留：人工写得出它，归档下一轮就会往它上面追加版本。"""
    from test_documents import upload

    req = make_requirement(title="保留前缀")
    doc = upload(client, auth("pm"), title="人工的").get_json()
    r = client.post(f"/api/requirements/{req['id']}/documents",
                    json={"document_id": doc["id"], "label": "agent:qa"},
                    headers=auth("pm"))
    assert r.status_code == 400
    assert r.get_json()["detail"]["reason"] == "reserved_label"
    # 正常 label 不受影响。
    assert client.post(f"/api/requirements/{req['id']}/documents",
                       json={"document_id": doc["id"], "label": "验收报告"},
                       headers=auth("pm")).status_code == 201


# ————————————————————— create_text_document 的四条自持不变量 —————————————————————

def test_create_text_document_forces_md_extension(app, data):
    """不变量 1：扩展名恒为 md，MIME 由扩展名推导，调用方无从指定。"""
    from services.documents import service

    with app.app_context():
        doc, version, _blob = service.create_text_document(
            title="强制 md", kind="design", content="# hi\n",
            project_id=None, uploader=None, filename_stem="anything.exe")
        db.session.commit()
        assert version.original_filename.endswith(".md")
        assert version.mime_type == "text/markdown"
        assert doc.current_version_id == version.id


def test_create_text_document_rejects_oversized_body(app):
    """不变量 3：正文上限 = DOC_TEXT_EDIT_MAX_BYTES，超限 400 而非静默截断。"""
    from services.documents import service
    from services.validation import ValidationError

    with app.app_context():
        limit = app.config["DOC_TEXT_EDIT_MAX_BYTES"]
        with pytest.raises(ValidationError):
            service.create_text_document(
                title="太大", kind="other", content="x" * (limit + 1),
                project_id=None, uploader=None)


def test_startup_asserts_md_is_allowed():
    """不变量 2：把 md 从白名单里摘掉却留着模板功能，应当**起不来**。"""
    from services import doc_policy

    with pytest.raises(ValueError, match="md"):
        doc_policy.assert_text_document_extension({"DOC_ALLOWED_EXTENSIONS": ("txt", "png")})
    # 白名单含 md 时放行；且它与阈值断言**并列**，互不牵连。
    doc_policy.assert_text_document_extension({"DOC_ALLOWED_EXTENSIONS": ("md", "txt")})


def test_create_text_document_reuses_the_content_addressed_chain(app):
    """不变量 4：同样的正文只占一份磁盘（复用 `digest_and_persist` 的去重）。"""
    from services.documents import service, storage

    with app.app_context():
        service.create_text_document(title="甲", kind="other", content="同一段正文",
                                     project_id=None, uploader=None)
        service.create_text_document(title="乙", kind="other", content="同一段正文",
                                     project_id=None, uploader=None)
        db.session.commit()
        root = storage.upload_root()
        blobs = [p for p in root.rglob("*")
                 if p.is_file() and storage.TMP_DIRNAME not in p.parts]
        assert len(blobs) == 1
        assert Document.query.count() == 2


# ————————————————————— 模板目录 —————————————————————

def test_catalog_excludes_the_three_kinds_without_templates():
    kinds = [t["kind"] for t in templates.catalog()]
    assert kinds == list(templates.TEMPLATE_KINDS)
    for excluded in ("bug_evidence", "reference", "other"):
        assert excluded not in kinds


def test_render_is_deterministic_given_the_same_inputs(app, make_requirement):
    class _Ticket:
        id = 7
        title = "确定性"

    with app.app_context():
        first = templates.render("design", entity="requirement", ticket=_Ticket(),
                                 author_name="Ada", stage_label="开发中",
                                 today="2026-07-20")
        second = templates.render("design", entity="requirement", ticket=_Ticket(),
                                  author_name="Ada", stage_label="开发中",
                                  today="2026-07-20")
        assert first == second
        assert "REQ-7" in first and "开发中" in first and "2026-07-20" in first
