"""存量演示数据清理工具回归（data-persistence-and-seed-slimming §6.1）。

本文件里 `test_apply_never_prunes_real_activities_and_comments` 是**最重要的一条**：
它是评审 P0-1 的护栏。若有人「顺手统一一下」，把「每类留一」重新套回
comments / activities / notifications，用户几个月的审计与讨论会被不可逆删除——
那一刻这条用例必须变红。按 §8 的落地要求，它先于实现被写下。
"""
import glob
import json
import os
import sqlite3
import subprocess
import sys

import pytest

from extensions import db
from models.activity import Activity
from models.agent import Agent
from models.bug import Bug
from models.comment import Comment
from models.notification import Notification
from models.project import Project
from models.requirement import Requirement
from models.seed_record import SeedRecord
from models.user import User
from tools import purge_demo_data as purge

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# v1 seed 的原样内容（指纹表就是照着它冻结的）。
_LEGACY_USERS = (("admin", "admin"), ("pm", "pm"), ("alice", "member"),
                 ("bob", "member"))
_LEGACY_REQUIREMENT_TITLES = purge.LEGACY_FINGERPRINT["requirement"]
_LEGACY_BUG_TITLES = purge.LEGACY_FINGERPRINT["bug"]


def _release(app):
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def _install_legacy_principals() -> dict:
    """写入 v1 风格的 4 用户 / 2 Agent / 1 项目，返回关键实体。"""
    users = {}
    for username, role in _LEGACY_USERS:
        user = User(username=username, role=role, display_name=username,
                    avatar_color="#C15F3C")
        user.set_password(f"{username}123")
        db.session.add(user)
        users[username] = user
    dev = Agent(name="dev-agent", kind="dev", status="idle", description="dev")
    qa = Agent(name="qa-agent", kind="qa", status="idle", description="qa")
    db.session.add_all([dev, qa])
    db.session.flush()
    project = Project(name="AragonTeam Platform", key="ARA",
                      owner_id=users["pm"].id)
    db.session.add(project)
    db.session.flush()
    return {"users": users, "dev": dev, "qa": qa, "project": project}


def _install_legacy_tickets(ctx: dict) -> dict:
    """写入 v1 的 7 条需求 / 5 个 BUG；qa-agent 名下留一张 fixing 的 BUG。"""
    reporter_id = ctx["users"]["pm"].id
    project_id = ctx["project"].id
    requirements = []
    for index, title in enumerate(_LEGACY_REQUIREMENT_TITLES):
        req = Requirement(title=title, status="new", priority="medium",
                          project_id=project_id, reporter_id=reporter_id,
                          position=index)
        db.session.add(req)
        requirements.append(req)
    bugs = []
    for index, title in enumerate(_LEGACY_BUG_TITLES):
        # 「看板列计数未实时刷新」在 v1 里就是 qa-agent 名下的 fixing 单（seed.py:92）。
        is_qa_bug = title == "看板列计数未实时刷新"
        bug = Bug(title=title, status="fixing" if is_qa_bug else "open",
                  severity="major", project_id=project_id,
                  reporter_id=reporter_id, position=index,
                  assignee_type="agent" if is_qa_bug else None,
                  assignee_id=ctx["qa"].id if is_qa_bug else None)
        db.session.add(bug)
        bugs.append(bug)
    db.session.flush()
    ctx["requirements"] = requirements
    ctx["bugs"] = bugs
    return ctx


def _install_legacy_soft_rows(ctx: dict) -> None:
    """v1 的示例评论 / 审计 / 通知——刻意挂在**会被删除**的那些工单上。"""
    doomed = ctx["requirements"][2]
    alice_id = ctx["users"]["alice"].id
    db.session.add(Comment(entity_type="requirement", entity_id=doomed.id,
                           author_type="user", author_id=alice_id,
                           body="v1 示例评论"))
    Activity.log("requirement", doomed.id, "moved", actor=("user", alice_id),
                 to_status="new", message="v1 示例审计")
    db.session.add(Notification(user_id=alice_id, type="assigned",
                                entity_type="requirement", entity_id=doomed.id,
                                actor_type="user", actor_id=alice_id,
                                message="v1 示例通知"))


def _install_real_rows(ctx: dict) -> dict:
    """混入**用户真实数据**：3 条需求、2 个 BUG，以及挂在**被保留**工单上的软表行。"""
    admin_id = ctx["users"]["admin"].id
    kept = ctx["requirements"][0]          # id 最小 → 「每类留一」必然保留它
    real_requirements = []
    for index in range(3):
        req = Requirement(title=f"我自己建的需求 {index}", status="new",
                          priority="high", project_id=ctx["project"].id,
                          reporter_id=admin_id, position=100 + index)
        db.session.add(req)
        real_requirements.append(req)
    for index in range(2):
        db.session.add(Bug(title=f"我自己建的缺陷 {index}", status="open",
                           severity="minor", project_id=ctx["project"].id,
                           reporter_id=admin_id, position=100 + index))
    for index in range(12):
        db.session.add(Comment(entity_type="requirement", entity_id=kept.id,
                               author_type="user", author_id=admin_id,
                               body=f"我的真实讨论 {index}"))
    for index in range(20):
        Activity.log("requirement", kept.id, "updated",
                     actor=("user", admin_id), to_status="new",
                     message=f"我的真实审计 {index}")
    for index in range(6):
        db.session.add(Notification(user_id=admin_id, type="commented",
                                    entity_type="requirement",
                                    entity_id=kept.id, actor_type="agent",
                                    actor_id=ctx["dev"].id,
                                    message=f"我的真实通知 {index}"))
    db.session.flush()
    ctx["real_requirement_ids"] = [r.id for r in real_requirements]
    ctx["kept_requirement_id"] = kept.id
    return ctx


@pytest.fixture
def legacy_db(file_app):
    """在 tmp_path 上造一个「v1 演示数据 + 用户真实数据」混合的存量库。

    Returns:
        `(db_path, url, ctx)`；`ctx` 里有 real_requirement_ids / kept_requirement_id。
    """
    make, db_path = file_app
    app = make(seed=False)
    with app.app_context():
        ctx = _install_legacy_principals()
        _install_legacy_tickets(ctx)
        _install_legacy_soft_rows(ctx)
        _install_real_rows(ctx)
        db.session.commit()
        ids = {"real_requirement_ids": ctx["real_requirement_ids"],
               "kept_requirement_id": ctx["kept_requirement_id"]}
    _release(app)                       # 放掉句柄，CLI 独占目标库
    return db_path, f"sqlite:///{db_path.as_posix()}", ids


def _run_cli(monkeypatch, url, *extra):
    """在本进程内跑一次 CLI。

    三个环境变量用 monkeypatch 预置，好让 `main()` 的直接赋值在用例结束后被还原
    （monkeypatch 只还原它自己记过的键）。
    """
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("SEED_ON_STARTUP", "false")
    monkeypatch.setenv("RELEASE_STALE_LOCKS_ON_STARTUP", "false")
    return purge.main(["--database-url", url, *extra])


def _counts(url_path):
    """直接用 sqlite3 读各表行数——不经 ORM，避免任何隐式写。"""
    conn = sqlite3.connect(str(url_path))
    try:
        tables = ("users", "agents", "projects", "requirements", "bugs",
                  "comments", "activities", "notifications", "seed_records")
        out = {}
        for table in tables:
            try:
                out[table] = conn.execute(
                    f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.OperationalError:
                out[table] = None       # 表尚不存在（dry-run 前的 seed_records）
        return out
    finally:
        conn.close()


# ————————————————————— P0-1 护栏（最重要的一条）—————————————————————

def test_apply_never_prunes_real_activities_and_comments(legacy_db, monkeypatch,
                                                         file_app, capsys):
    """真实评论 / 审计 / 通知一条不少——即便它们挂在**被保留**的那条工单上。

    若有人把「每类留一」改回这三类上，本用例必红（§2.6.2 / §7 R-12）。
    """
    db_path, url, ids = legacy_db
    assert _run_cli(monkeypatch, url, "--apply", "--no-backup") == 0
    capsys.readouterr()

    make, _ = file_app
    app = make(seed=False)
    with app.app_context():
        kept = ids["kept_requirement_id"]
        assert Comment.query.filter_by(entity_type="requirement",
                                       entity_id=kept).count() == 12
        assert Activity.query.filter_by(entity_type="requirement",
                                        entity_id=kept).count() == 20
        assert Notification.query.filter_by(entity_type="requirement",
                                            entity_id=kept).count() == 6


def test_apply_never_touches_real_rows(legacy_db, monkeypatch, file_app):
    db_path, url, ids = legacy_db
    _run_cli(monkeypatch, url, "--apply", "--no-backup")

    make, _ = file_app
    app = make(seed=False)
    with app.app_context():
        for req_id in ids["real_requirement_ids"]:
            assert db.session.get(Requirement, req_id) is not None
        assert Bug.query.filter(Bug.title.like("我自己建的缺陷%")).count() == 2


# ————————————————————— dry-run 契约 —————————————————————

def test_dry_run_writes_nothing(legacy_db, monkeypatch):
    """【评审 P1-8】不断言退出码；【评审 P0-2】允许 create_all 建出空 seed_records 表。"""
    db_path, url, _ids = legacy_db
    before = _counts(db_path)
    _run_cli(monkeypatch, url)
    after = _counts(db_path)
    for table, count in before.items():
        if count is None:               # seed_records 由 create_all 建出，空表
            assert after[table] == 0
        else:
            assert after[table] == count, table


def test_dry_run_and_apply_agree_on_exit_code(legacy_db, monkeypatch):
    """预演结果必须能预测真实结果（§4.2 评审 P1-8）。"""
    _db_path, url, _ids = legacy_db
    assert _run_cli(monkeypatch, url) == _run_cli(monkeypatch, url, "--apply",
                                                  "--no-backup")


def test_orphan_seed_records_are_reported_but_not_deleted_on_dry_run(
        legacy_db, monkeypatch, file_app):
    """【评审 P2-13】dry-run 下孤儿登记只统计不删。"""
    db_path, url, _ids = legacy_db
    make, _ = file_app
    app = make(seed=False)
    with app.app_context():
        db.session.add(SeedRecord(entity_type="requirement", entity_id=999999,
                                  seed_version="2"))
        db.session.commit()
    _release(app)

    before = _counts(db_path)["seed_records"]
    _run_cli(monkeypatch, url)
    assert _counts(db_path)["seed_records"] == before == 1


# ————————————————————— 五类各留一 —————————————————————

def test_apply_keeps_exactly_one_per_category(file_app, monkeypatch):
    """纯 v1 演示数据（不混真实数据）→ apply → 五类各只剩一条示例。

    users 的判据是「**启用中**的用户恰好 1 人」：被引用的 seed 用户按 §2.6.3 是
    **停用**而非删除（安全阀），它的行必然留在库里（见 spec §「实施过程发现的方案缺陷」）。
    """
    make, db_path = file_app
    app = make(seed=False)
    with app.app_context():
        ctx = _install_legacy_principals()
        _install_legacy_tickets(ctx)
        _install_legacy_soft_rows(ctx)
        db.session.commit()
    _release(app)

    url = f"sqlite:///{db_path.as_posix()}"
    _run_cli(monkeypatch, url, "--apply", "--no-backup")

    verify = make(seed=False)
    with verify.app_context():
        assert User.query.filter_by(is_active=True).count() == 1
        assert Agent.query.count() == 1
        assert Project.query.count() == 1
        assert Requirement.query.count() == 1
        assert Bug.query.count() == 1


def test_agent_with_only_deleted_open_tickets_is_removed(legacy_db, monkeypatch,
                                                         file_app):
    """【评审 P1-7】qa-agent 名下唯一的 fixing BUG 本身就在删除集 → 守卫放行。"""
    _db_path, url, _ids = legacy_db
    _run_cli(monkeypatch, url, "--apply", "--no-backup")

    make, _ = file_app
    app = make(seed=False)
    with app.app_context():
        assert [a.name for a in Agent.query.all()] == ["dev-agent"]


def test_referenced_seed_user_is_deactivated_not_deleted(legacy_db, monkeypatch,
                                                         file_app):
    _db_path, url, _ids = legacy_db
    _run_cli(monkeypatch, url, "--apply", "--no-backup")

    make, _ = file_app
    app = make(seed=False)
    with app.app_context():
        pm = User.query.filter_by(username="pm").one_or_none()
        assert pm is not None, "被引用的用户必须停用而非删除（审计不可销毁）"
        assert pm.is_active is False


def test_cascade_removes_orphan_comments_and_activities(legacy_db, monkeypatch,
                                                        file_app):
    _db_path, url, _ids = legacy_db
    _run_cli(monkeypatch, url, "--apply", "--no-backup")

    make, _ = file_app
    app = make(seed=False)
    with app.app_context():
        alive = {r.id for r in Requirement.query.all()}
        for model in (Comment, Activity, Notification):
            dangling = [row for row in model.query.all()
                        if row.entity_type == "requirement"
                        and row.entity_id not in alive]
            assert dangling == [], model.__tablename__


def test_apply_is_idempotent(legacy_db, monkeypatch, capsys):
    """重复执行 --apply：第二次全为 delete 0，且退出码与第一次一致（§6.3-9）。"""
    _db_path, url, _ids = legacy_db
    first = _run_cli(monkeypatch, url, "--apply", "--no-backup")
    capsys.readouterr()
    second = _run_cli(monkeypatch, url, "--apply", "--no-backup", "--json")
    report = json.loads(capsys.readouterr().out)
    assert first == second
    for category, entry in report["categories"].items():
        assert entry["deleted"] == [], category
        assert entry["deactivated"] == [], category
    for table, stat in report["soft_tables"].items():
        assert (stat["seeded"], stat["cascaded"], stat["orphan"]) == (0, 0, 0), table


# ————————————————————— 守卫与备份 —————————————————————

def test_purge_never_orphans_admins(file_app, monkeypatch):
    """唯一的 admin 恰好不是 id 最小的候选 → 落进删除集 → 被守卫跳过，退出码 2。"""
    make, db_path = file_app
    app = make(seed=False)
    with app.app_context():
        pm = User(username="pm", role="pm", display_name="pm")
        pm.set_password("pm123")
        admin = User(username="admin", role="admin", display_name="admin")
        admin.set_password("admin123")
        db.session.add_all([pm, admin])   # pm 先落 id=1 → 「留一」保留 pm
        db.session.commit()
    _release(app)

    url = f"sqlite:///{db_path.as_posix()}"
    assert _run_cli(monkeypatch, url, "--apply", "--no-backup") == 2

    verify = make(seed=False)
    with verify.app_context():
        survivor = User.query.filter_by(username="admin").one()
        assert survivor.is_active is True


def test_backup_file_created_before_apply(legacy_db, monkeypatch):
    db_path, url, _ids = legacy_db
    _run_cli(monkeypatch, url, "--apply")
    backups = glob.glob(f"{db_path}.bak-*")
    assert len(backups) == 1
    conn = sqlite3.connect(backups[0])   # 备份必须能独立打开并查得到表
    try:
        assert conn.execute("SELECT COUNT(*) FROM requirements").fetchone()[0] > 0
    finally:
        conn.close()


def test_missing_database_file_is_a_precondition_error(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'nope.db').as_posix()}"
    assert _run_cli(monkeypatch, url) == 1
    assert not (tmp_path / "nope.db").exists()   # 不替用户创建空库


def test_target_database_url_does_not_touch_default_db(legacy_db, tmp_path):
    """【评审 P0-2 / R-13】CLI 启动契约：绝不创建 / 播种非目标库。

    用**子进程**跑，才是对「import app 的时机」这一契约的真实检验：本进程里
    app 模块早已被 conftest import 过，提前 import 的危害在进程内不会显形。
    """
    db_path, url, _ids = legacy_db
    decoy = tmp_path / "decoy.db"
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite:///{decoy.as_posix()}"
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, "tools/purge_demo_data.py", "--database-url", url],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=180,
        encoding="utf-8", errors="replace")   # 子进程报告含中文，别让父进程按 GBK 解
    assert result.returncode in (0, 2), result.stderr
    assert not decoy.exists(), "工具顺手创建了非目标库——启动契约被破坏"
    assert db_path.exists()


# ————————————————————— 文档三表（ticket-document-management §2.8）—————————————————————

def test_purge_never_deletes_real_documents(file_app, monkeypatch, capsys):
    """用户上传的文档在 `--apply` 后一行不少，其上传者也不会被当成可删用户。

    seed **不写**任何文档行（§8 R-5：seed 维持 8 行一类一行），因此 documents /
    document_versions 里的每一行都必然是用户真实数据——推定方向只能是保留。
    """
    from models.document import Document, DocumentVersion
    from models.document_link import DocumentLink

    make, db_path = file_app
    app = make(seed=False)
    with app.app_context():
        ctx = _install_legacy_principals()
        _install_legacy_tickets(ctx)
        _install_legacy_soft_rows(ctx)
        _install_real_rows(ctx)
        uploader = ctx["users"]["alice"]          # 一个会被指纹命中的 v1 演示用户
        doc = Document(title="我上传的接口契约", kind="design",
                       uploader_id=uploader.id)
        db.session.add(doc)
        db.session.flush()
        version = DocumentVersion(document_id=doc.id, version_no=1,
                                  original_filename="api.md", mime_type="text/markdown",
                                  size_bytes=12, sha256="a" * 64,
                                  uploader_id=uploader.id)
        db.session.add(version)
        db.session.flush()
        doc.current_version_id = version.id
        db.session.add(DocumentLink(document_id=doc.id, entity_type="requirement",
                                    entity_id=ctx["kept_requirement_id"]))
        db.session.commit()
        doc_id, uploader_id = doc.id, uploader.id
    _release(app)

    url = f"sqlite:///{db_path.as_posix()}"
    assert _run_cli(monkeypatch, url, "--apply", "--no-backup") == 0
    capsys.readouterr()

    app = make(seed=False)
    with app.app_context():
        assert db.session.get(Document, doc_id) is not None
        assert DocumentVersion.query.filter_by(document_id=doc_id).count() == 1
        # 上传者被 documents.uploader_id 这条**真外键**保护，不会被误删。
        assert db.session.get(User, uploader_id) is not None


# —— self-service-registration §7 R-9：根管理员是治理锚点，清理工具永不碰它 ——

def test_apply_never_deletes_root_user(legacy_db, monkeypatch, file_app):
    """seed 出来的 `admin` 行既登记了 SeedRecord、又是根管理员——删掉它就是治理死锁。

    「清完演示数据后没有人能登录」在产品内无恢复路径，只剩改配置 + 重启。
    """
    db_path, url, _ids = legacy_db
    make, _ = file_app
    app = make(seed=False)
    with app.app_context():
        alice = User.query.filter_by(username="alice").one()
        alice.is_root = True                 # 模拟 ensure_root_admin 打过标的那一行
        db.session.commit()
        alice_id = alice.id
        db.session.remove()
        db.engine.dispose()

    # 退出码有意不断言：被跳过的行会让工具报「部分完成」，那正是本用例期望的结果。
    _run_cli(monkeypatch, url, "--apply", "--no-backup")

    app = make(seed=False)
    with app.app_context():
        survivor = db.session.get(User, alice_id)
        assert survivor is not None
        assert survivor.is_active is True     # 也不许被降级为「停用」
