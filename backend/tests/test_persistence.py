"""持久化回归（data-persistence-and-seed-slimming §6.1）。

本文件是全仓库**唯一**跑在真实文件库上的用例集。其余 300+ 用例都用
`sqlite:///:memory:`，「重启后数据还在吗」这个问题在此之前从未被 CI 回答过。
"""
import json

from extensions import db
from models.agent import Agent
from models.requirement import Requirement
from models.seed_record import SeedRecord
from services import persistence


def _pragma(app, name):
    from sqlalchemy import text

    with app.app_context():
        return db.session.execute(text(f"PRAGMA {name}")).scalar()


def test_written_row_survives_app_restart(file_app):
    make, db_path = file_app
    app = make()
    with app.app_context():
        db.session.add(Requirement(title="重启后我还在", status="new", position=99))
        db.session.commit()

    restarted = make()                     # 模拟进程重启：新 app、同一个库文件
    with restarted.app_context():
        survivor = Requirement.query.filter_by(title="重启后我还在").one_or_none()
        assert survivor is not None
        assert survivor.status == "new"
    assert db_path.exists()


def test_second_start_does_not_reseed(file_app):
    make, _ = file_app
    make()
    restarted = make()
    with restarted.app_context():
        # 幂等门是 User.query.count() > 0；第二次启动必须整体跳过。
        assert Requirement.query.count() == 1
        # 【version-plan-hierarchy §4.6】seed 现为 10 类（8 + 版本 + 计划），各登记一条。
        assert SeedRecord.query.count() == 10


def test_file_backed_db_enables_wal_and_foreign_keys(file_app):
    make, _ = file_app
    app = make()
    assert str(_pragma(app, "journal_mode")).lower() == "wal"
    assert _pragma(app, "foreign_keys") == 1


def test_memory_db_skips_wal_without_error(app):
    """内存库不该被设 WAL，更不该因此启动失败（§2.3）。"""
    assert str(_pragma(app, "journal_mode")).lower() != "wal"


def test_health_reports_persistent_storage(client, file_app):
    memory = client.get("/api/health").get_json()
    assert memory["db"] == "ok"
    assert memory["storage"]["persistent"] is False

    make, db_path = file_app
    file_client = make().test_client()
    resp = file_client.get("/api/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["storage"]["persistent"] is True
    assert body["storage"]["journal_mode"] == "wal"
    assert body["storage"]["foreign_keys"] is True
    # 【§2.2】/api/health 无需鉴权，响应体里**不得**出现任何服务器文件系统路径。
    raw = json.dumps(body, ensure_ascii=False)
    assert "aragon.db" not in raw
    assert db_path.as_posix() not in raw


def test_stale_busy_agent_is_released_on_startup(file_app):
    make, _ = file_app
    app = make()
    with app.app_context():
        agent = Agent.query.filter_by(name="dev-agent").one()
        agent.status = "busy"                     # 模拟被 Ctrl+C 杀死留下的软锁
        db.session.commit()

    restarted = make()
    with restarted.app_context():
        assert Agent.query.filter_by(name="dev-agent").one().status == "idle"


def test_stale_lock_release_can_be_disabled(file_app):
    """【评审 P1-5】用 config 子类属性覆盖开关，**不用** monkeypatch.setenv。"""
    make, _ = file_app
    app = make()
    with app.app_context():
        agent = Agent.query.filter_by(name="dev-agent").one()
        agent.status = "busy"
        db.session.commit()

    restarted = make(RELEASE_STALE_LOCKS_ON_STARTUP=False)
    with restarted.app_context():
        assert Agent.query.filter_by(name="dev-agent").one().status == "busy"


def test_health_storage_survives_pragma_failure(file_app, monkeypatch):
    """【评审 P1-4】自省失败绝不改变健康检查的成败判据。"""
    def boom(*_args, **_kwargs):
        raise RuntimeError("pragma unavailable on this mount")

    monkeypatch.setattr(persistence, "text", boom)
    make, _ = file_app
    resp = make().test_client().get("/api/health")
    assert resp.status_code == 200                # 探针不因「自省自己」而 500
    storage = resp.get_json()["storage"]
    assert storage["journal_mode"] == "unknown"
    assert storage["synchronous"] == "unknown"
    assert storage["foreign_keys"] is None
    assert storage["persistent"] is True          # 纯字符串判断，不依赖 PRAGMA


def test_describe_storage_classifies_uris():
    assert persistence.describe_storage("sqlite:///:memory:")["persistent"] is False
    assert persistence.describe_storage("")["persistent"] is False
    described = persistence.describe_storage("sqlite:////var/data/aragon.db")
    assert described["persistent"] is True
    assert described["path"].replace("\\", "/").endswith("/var/data/aragon.db")
