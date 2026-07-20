"""Agent 交付物归档用例（document-lifecycle-depth §7.2 支柱 C · C4~C13）。

本文件里最重要的两条是 **C11**（dev-agent 不得产出 QA 交付物）与 **C12**（落盘发生在
状态写入之前）——它们守的都不是「功能对不对」，而是「**别的守卫为什么抓不到那个 bug**」。
"""
import pytest

from extensions import db
from models.document import Document, DocumentVersion
from models.document_link import DocumentLink
from models.notification import Notification
from services import agent_executor
from services.agent_runner import AGENT_FORWARD
from services.documents import agent_archive
from services.llm import LLMResult

# 足够长、能过 DOC_AGENT_ARCHIVE_MIN_CHARS 的假 LLM 产物。
LONG_PRODUCT = "## 测试范围\n\n" + ("本次覆盖支付链路的超时与重试。" * 30)
SHORT_PRODUCT = "干完了。"

_LLM_ENV = (
    "AGENT_LLM_PROVIDER", "AGENT_LLM_API_KEY", "AGENT_LLM_MODEL", "AGENT_LLM_BASE_URL",
    "AGENT_LLM_WALL_BUDGET", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
)


@pytest.fixture(autouse=True)
def _clean_llm_env(monkeypatch):
    for name in _LLM_ENV:
        monkeypatch.delenv(name, raising=False)
    yield


def activate_llm(monkeypatch, text=LONG_PRODUCT):
    """强制启用真实 LLM 路径（绕过 TESTING 门），并注入假 complete。绝不触网。"""
    monkeypatch.setattr(agent_executor, "_llm_active", lambda: True)
    monkeypatch.setattr(agent_executor.llm, "complete",
                        lambda s, u, **kw: LLMResult(text=text, model="m",
                                                     provider="anthropic",
                                                     latency_ms=1, usage=None))


def enable_archive(app):
    app.config["DOC_AGENT_ARCHIVE"] = True


def advance(client, auth, entity, ticket_id, role="pm"):
    return client.post(f"/api/{entity}/{ticket_id}/agent-advance", json={},
                       headers=auth(role))


def move(client, auth, req_id, status, role="pm"):
    return client.patch(f"/api/requirements/{req_id}/move", json={"status": status},
                        headers=auth(role))


def qa_requirement(client, auth, data, make_requirement, title="待归档"):
    """造一张停在 `testing` 且指派给 qa-agent 的需求单（qa 的归档边就在这里）。"""
    req = make_requirement(title=title, assignee=("user", data["pm_id"]))
    for status in ("in_development", "testing"):
        assert move(client, auth, req["id"], status).status_code == 200
    r = client.patch(f"/api/requirements/{req['id']}/assign",
                     json={"assignee_type": "agent", "assignee_id": data["qa_agent_id"]},
                     headers=auth("pm"))
    assert r.status_code == 200, r.get_json()
    return req


# ————————————————————— C4 · 降级产物绝不归档 —————————————————————

def test_archive_skips_when_product_is_fallback(client, auth, app, data,
                                                make_requirement):
    """降级模板绝不归档——这条同时是**存量用例零影响的机制性保证**。

    `_llm_active()` 在 TESTING 下恒 False ⇒ `from_llm` 恒假 ⇒ 归档在整套存量用例上
    一次也不会触发。一句「dev-agent 已认领需求」存成文档，只会往库里灌垃圾，
    还会把阶段清单点绿，制造「材料齐了」的假象。
    """
    enable_archive(app)                              # 开关开着，但产物是降级模板
    req = qa_requirement(client, auth, data, make_requirement)
    assert advance(client, auth, "requirements", req["id"]).status_code == 200
    with app.app_context():
        assert Document.query.count() == 0


def test_archive_is_off_by_default_in_tests(client, auth, app, data,
                                            make_requirement, monkeypatch):
    """配置层的第二道钉：即使有人放宽了 `_llm_active()`，测试环境仍不归档。"""
    activate_llm(monkeypatch)
    assert app.config["DOC_AGENT_ARCHIVE"] is False
    req = qa_requirement(client, auth, data, make_requirement)
    advance(client, auth, "requirements", req["id"])
    with app.app_context():
        assert Document.query.count() == 0


# ————————————————————— C5 ~ C6 · 建 / 追加 —————————————————————

def test_archive_creates_document_on_llm_product(client, auth, app, data,
                                                 make_requirement, monkeypatch):
    enable_archive(app)
    activate_llm(monkeypatch)
    req = qa_requirement(client, auth, data, make_requirement, title="支付回归")
    assert advance(client, auth, "requirements", req["id"]).status_code == 200

    with app.app_context():
        doc = Document.query.one()
        assert doc.kind == "test_report"          # ARCHIVE_KIND[(requirement, qa, reviewing)]
        assert doc.uploader_id is None            # Agent 不是 User
        link = DocumentLink.query.one()
        assert link.label == "agent:qa"
        assert link.stage == "reviewing"          # **推进后**的目标状态，不是旧状态
        version = db.session.get(DocumentVersion, doc.current_version_id)
        assert version.original_filename.endswith(".md")

    listed = client.get(f"/api/requirements/{req['id']}/documents",
                        headers=auth("pm")).get_json()
    assert len(listed) == 1
    acts = client.get(f"/api/requirements/{req['id']}/activities",
                      headers=auth("pm")).get_json()
    assert any(a["action"] == "doc_attached" and a["actor_type"] == "agent"
               for a in acts)


def test_archived_document_satisfies_the_stage_checklist(client, auth, app, data,
                                                         make_requirement,
                                                         monkeypatch):
    """这正是本轮让 `DOC_STAGE_GATE` **有资格被打开**的那件事。"""
    enable_archive(app)
    activate_llm(monkeypatch)
    req = qa_requirement(client, auth, data, make_requirement)
    advance(client, auth, "requirements", req["id"])
    checklist = client.get(f"/api/requirements/{req['id']}/document-checklist",
                           headers=auth("pm")).get_json()
    assert checklist["stage"] == "reviewing"
    assert checklist["satisfied"] is True


def test_archive_appends_version_on_second_pass(client, auth, app, data,
                                                make_requirement, monkeypatch):
    """同一单同一 kind 第二次推进 → **版本 +1，文档数不变**（不每次 tick 灌一份新的）。"""
    enable_archive(app)
    activate_llm(monkeypatch)
    req = qa_requirement(client, auth, data, make_requirement)
    advance(client, auth, "requirements", req["id"])          # testing → reviewing
    with app.app_context():
        assert Document.query.count() == 1
        document_id = Document.query.one().id

    # 退回 testing 再推一次：同一个 (单, agent kind) 组合。
    move(client, auth, req["id"], "testing")
    activate_llm(monkeypatch, text=LONG_PRODUCT + "\n\n补充：新增两条边界用例。")
    advance(client, auth, "requirements", req["id"])
    with app.app_context():
        assert Document.query.count() == 1
        assert DocumentLink.query.count() == 1
        versions = DocumentVersion.query.filter_by(document_id=document_id).all()
        assert len(versions) == 2
        assert "阶段更新" in versions[-1].note


# ————————————————————— C7 / C11 · 归类正确性双向守卫 —————————————————————

def test_archive_kind_matches_stage_expectations():
    """C7（正向）：每个值 ∈ 对应阶段的清单期望项，**且每个键在 `AGENT_FORWARD` 里真实可达**。

    后半句是评审 V-01 补的：出错的那两格恰恰**满足**前半句，只有前半句的守卫会给
    bug 盖章通过。
    """
    from services.doc_policy import STAGE_DOC_EXPECTATIONS

    reachable = {(entity, kind, to)
                 for (entity, kind, _frm), (to, _msg) in AGENT_FORWARD.items()}
    for (entity, agent_kind, to_status), kind in agent_archive.ARCHIVE_KIND.items():
        assert (entity, agent_kind, to_status) in reachable, \
            f"{(entity, agent_kind, to_status)} 在 AGENT_FORWARD 里不可达"
        expected = STAGE_DOC_EXPECTATIONS.get((entity, to_status), ())
        assert kind in expected, \
            f"{kind} 不是 {(entity, to_status)} 的清单期望项 {expected}"


def test_dev_agent_never_produces_qa_artifacts():
    """【C11 · 反向守卫（评审 V-01 · P0）——本轮最重要的一条用例】

    遍历 `AGENT_FORWARD`，对每条 `kind == "dev"` 的边断言 `ARCHIVE_KIND` 要么没有该键、
    要么其值 ∉ ("test_plan", "test_report")。

    它挡住的是「dev-agent 自己出具验收报告、把门禁点绿」这一类**静默的信任崩塌**：
    `("requirement","testing")` 与 `("bug","verifying")` 唯一由 dev-agent 到达，而这两个
    阶段的期望项恰是「测试计划」与「测试报告」——少了 `agent_kind` 这一维，dev-agent 的
    一段「我已提交修复」正文就会被归档成 QA 的交付物。C7 结构上抓不到它（那两格**满足**
    C7 的断言）。
    """
    qa_artifacts = ("test_plan", "test_report")
    for (entity, agent_kind, _frm), (to, _msg) in AGENT_FORWARD.items():
        if agent_kind != "dev":
            continue
        kind = agent_archive.ARCHIVE_KIND.get((entity, agent_kind, to))
        assert kind not in qa_artifacts, (
            f"dev-agent 在 {entity} {to} 这一步被配置成产出 {kind}——"
            "验证侧材料必须由 qa-agent 或人产出"
        )


def test_generic_agent_has_no_archive_mapping():
    """generic 的两条边产出的是泛化认领说明，归成任何一类都是硬套——**故意不配**。"""
    generic_keys = [(entity, kind, to)
                    for (entity, kind, _frm), (to, _msg) in AGENT_FORWARD.items()
                    if kind == "generic"]
    assert generic_keys
    for key in generic_keys:
        assert key not in agent_archive.ARCHIVE_KIND


def test_dev_agent_advance_produces_no_document(client, auth, app, data,
                                                make_requirement, monkeypatch):
    """C11 的运行时对照面：dev-agent 走 `bug: fixing → verifying` 不产生任何文档。"""
    enable_archive(app)
    activate_llm(monkeypatch)
    bug = client.post("/api/bugs", json={"title": "登录 500"},
                      headers=auth("pm")).get_json()
    client.patch(f"/api/bugs/{bug['id']}/assign",
                 json={"assignee_type": "agent", "assignee_id": data["dev_agent_id"]},
                 headers=auth("pm"))
    assert advance(client, auth, "bugs", bug["id"]).status_code == 200   # → fixing
    with app.app_context():
        # fixing 这一步是 dev 的职能（bug_evidence），归档正常发生。
        assert Document.query.count() == 1
        assert Document.query.one().kind == "bug_evidence"

    assert advance(client, auth, "bugs", bug["id"]).status_code == 200   # → verifying
    with app.app_context():
        # verifying 期望的是「测试报告」，而唯一到达者是 dev-agent → **不归档**。
        assert Document.query.count() == 1
        assert Document.query.filter_by(kind="test_report").count() == 0
    checklist = client.get(f"/api/bugs/{bug['id']}/document-checklist",
                           headers=auth("pm")).get_json()
    assert checklist["stage"] == "verifying"
    assert checklist["satisfied"] is False              # 这一格**应当**红着


# ————————————————————— C8 · 失败不阻断（加强版） —————————————————————

def test_archive_failure_does_not_block_advance(client, auth, app, data,
                                                make_requirement, monkeypatch):
    """归档写入抛异常 → 推进仍 200，**且 commit 之后重新查库确认零残留**。

    【评审 V-04】只断言「推进成功」的话，SAVEPOINT 即使完全失效用例也照绿——
    而 pysqlite 的 SAVEPOINT 是有前置条件的。故必须在 commit **之后**重新查库。
    """
    enable_archive(app)
    activate_llm(monkeypatch)

    def _boom(*args, **kwargs):
        raise RuntimeError("archive exploded")

    monkeypatch.setattr(agent_archive, "_write", _boom)
    req = qa_requirement(client, auth, data, make_requirement)
    r = advance(client, auth, "requirements", req["id"])
    assert r.status_code == 200, r.get_json()

    with app.app_context():
        from models.activity import Activity
        from models.comment import Comment
        from models.requirement import Requirement

        db.session.expire_all()
        ticket = db.session.get(Requirement, req["id"])
        assert ticket.status == "reviewing"                       # 推进已落库
        assert Comment.query.filter_by(entity_type="requirement",
                                       entity_id=req["id"]).count() >= 1
        assert Activity.query.filter_by(entity_type="requirement",
                                        entity_id=req["id"],
                                        action="agent_advanced").count() >= 1
        # **没有半份文档行 / 版本行 / link 残留**
        assert Document.query.count() == 0
        assert DocumentVersion.query.count() == 0
        assert DocumentLink.query.count() == 0


def test_archive_prepare_failure_does_not_block_advance(client, auth, app, data,
                                                        make_requirement,
                                                        monkeypatch):
    """落盘失败同样只留一个可回收的孤儿，绝不阻断推进。"""
    enable_archive(app)
    activate_llm(monkeypatch)

    def _boom(*args, **kwargs):
        raise OSError("disk on fire")

    monkeypatch.setattr(agent_archive.service, "persist_text", _boom)
    req = qa_requirement(client, auth, data, make_requirement)
    assert advance(client, auth, "requirements", req["id"]).status_code == 200
    with app.app_context():
        assert Document.query.count() == 0


# ————————————————————— C12 · 落盘在状态写入之前 —————————————————————

def test_archive_persists_blob_before_status_write(client, auth, app, data,
                                                   make_requirement, monkeypatch):
    """【C12 · 评审 V-03】把「磁盘 IO 不在 SQLite 写锁窗口内」这条口头约束变成可执行断言。

    在 `digest_and_persist` 里就地断言：此刻工单状态仍是**旧**值，且 session 的
    new / dirty 里不含 Comment——即归档的落盘确实发生在 `ticket.status = to` 之前。
    """
    enable_archive(app)
    activate_llm(monkeypatch)
    req = qa_requirement(client, auth, data, make_requirement)
    seen = {}

    from services.documents import storage as storage_module
    original = storage_module.digest_and_persist

    def _spy(stream):
        from models.comment import Comment
        from models.requirement import Requirement

        ticket = db.session.get(Requirement, req["id"])
        seen["status"] = ticket.status
        pending = list(db.session.new) + list(db.session.dirty)
        seen["has_pending_comment"] = any(isinstance(o, Comment) for o in pending)
        return original(stream)

    monkeypatch.setattr(agent_archive.service.storage, "digest_and_persist", _spy)
    assert advance(client, auth, "requirements", req["id"]).status_code == 200
    assert seen["status"] == "testing", "落盘发生在状态改写之后 → 磁盘 IO 落进了写锁窗口"
    assert seen["has_pending_comment"] is False


# ————————————————————— C13 · 归档不发通知 —————————————————————

def test_archive_writes_activity_but_no_notification(client, auth, app, data,
                                                     make_requirement, monkeypatch):
    """【评审 V-10】`run=all` 最多 6 步、autorun 跨多张单循环——归档不该占注意力预算。"""
    enable_archive(app)
    activate_llm(monkeypatch)
    req = qa_requirement(client, auth, data, make_requirement)
    with app.app_context():
        # 只数 `document_added`：推进本身会发一条状态变更通知，那是既有行为。
        before = Notification.query.filter_by(type="document_added").count()

    advance(client, auth, "requirements", req["id"])
    with app.app_context():
        assert Notification.query.filter_by(
            type="document_added").count() == before          # 零新增
    acts = client.get(f"/api/requirements/{req['id']}/activities",
                      headers=auth("pm")).get_json()
    assert any(a["action"] == "doc_attached" for a in acts)


def test_archive_revision_sends_no_notification_either(client, auth, app, data,
                                                       make_requirement, monkeypatch):
    enable_archive(app)
    activate_llm(monkeypatch)
    req = qa_requirement(client, auth, data, make_requirement)
    advance(client, auth, "requirements", req["id"])
    with app.app_context():
        before = Notification.query.filter_by(type="document_added").count()
    move(client, auth, req["id"], "testing")
    advance(client, auth, "requirements", req["id"])
    with app.app_context():
        assert Notification.query.filter_by(type="document_added").count() == before
    acts = client.get(f"/api/requirements/{req['id']}/activities",
                      headers=auth("pm")).get_json()
    assert any(a["action"] == "doc_revised" for a in acts)


# ————————————————————— C9 ~ C10 · 阈值与零破坏 —————————————————————

def test_archive_respects_min_chars(client, auth, app, data, make_requirement,
                                    monkeypatch):
    """两句话的产出不值得成为一份「交付物」。"""
    enable_archive(app)
    activate_llm(monkeypatch, text=SHORT_PRODUCT)
    req = qa_requirement(client, auth, data, make_requirement)
    advance(client, auth, "requirements", req["id"])
    with app.app_context():
        assert Document.query.count() == 0


def test_archive_switch_off_restores_previous_behaviour(client, auth, app, data,
                                                        make_requirement,
                                                        monkeypatch):
    app.config["DOC_AGENT_ARCHIVE"] = False
    activate_llm(monkeypatch)
    req = qa_requirement(client, auth, data, make_requirement)
    advance(client, auth, "requirements", req["id"])
    with app.app_context():
        assert Document.query.count() == 0


def test_generate_work_signature_unchanged(app, data, monkeypatch,
                                           make_requirement):
    """薄包装仍返回 `str`（`real-agent-execution` 一轮契约的零破坏护栏）。"""
    from models.agent import Agent
    from models.requirement import Requirement

    with app.app_context():
        agent = db.session.get(Agent, data["dev_agent_id"])
        ticket = Requirement(title="签名", reporter_id=data["pm_id"])
        db.session.add(ticket)
        db.session.commit()

        text = agent_executor.generate_work("requirement", ticket, agent,
                                            "in_development",
                                            fallback_message="模板")
        assert isinstance(text, str) and text == "模板"

        product = agent_executor.generate_work_product(
            "requirement", ticket, agent, "in_development", fallback_message="模板")
        assert isinstance(product, agent_executor.WorkProduct)
        assert product.text == "模板"
        assert product.from_llm is False
