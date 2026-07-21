"""根管理员 bootstrap 与保护规则（self-service-registration §8.2 用例 21–30b、44）。

分两半：前半用 `file_app`（真实文件库，反复 `make()` 即模拟「进程重启」）验证
`services/bootstrap.py::ensure_root_admin` 的幂等性与归位语义；后半用内存库 + `root_admin`
fixture 验证 `PATCH /api/users/:id` 上的四条保护规则。

顺序不变量（§7 R-4）由 `test_seed_runs_before_bootstrap_on_fresh_db` 钉死：bootstrap 若
跑在 seed 之前，全新库上 `User.query.count()` 恒非空，示例数据一行都不会写入。
"""
import logging
from contextlib import contextmanager

import pytest

from extensions import db
from models.requirement import Requirement
from models.user import User
from tools import purge_demo_data as purge


@contextmanager
def captured_warnings():
    """收集 `app` logger 上的 WARNING 文案。

    **不能用 pytest 的 caplog**：`observability.init_observability` 会执行
    `root.handlers = [handler]`（`observability.py:38`），把 caplog 挂在 root 上的
    捕获 handler 整个换掉——每次 `create_app` 都换一次。故直接挂到 `app` logger 上，
    它不被那行代码触及。
    """
    records = []

    class _Collect(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = _Collect(level=logging.WARNING)
    logger = logging.getLogger("app")
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)


# ————————————————————— bootstrap 语义 —————————————————————

def test_bootstrap_creates_root_when_absent(file_app):
    make, _ = file_app
    app = make(seed=False, ROOT_ADMIN_BOOTSTRAP=True)

    with app.app_context():
        user = User.query.filter_by(username="admin").one()
        assert user.role == "admin"
        assert user.is_root is True
        assert user.is_active is True
        assert user.source == "root"


def test_bootstrap_is_idempotent(file_app):
    make, _ = file_app
    make(seed=False, ROOT_ADMIN_BOOTSTRAP=True)
    app = make(seed=False, ROOT_ADMIN_BOOTSTRAP=True)      # 第二次「重启」

    with app.app_context():
        assert User.query.filter_by(username="admin").count() == 1


def test_bootstrap_promotes_existing_username(file_app):
    make, _ = file_app
    app = make(seed=False)
    with app.app_context():
        ordinary = User(username="admin", role="member", display_name="路人")
        ordinary.set_password("pw12345")
        db.session.add(ordinary)
        db.session.commit()

    app = make(seed=False, ROOT_ADMIN_BOOTSTRAP=True)

    with app.app_context():
        user = User.query.filter_by(username="admin").one()
        assert user.role == "admin" and user.is_root is True


def test_bootstrap_restores_demoted_or_deactivated_root(file_app):
    make, _ = file_app
    app = make(seed=False, ROOT_ADMIN_BOOTSTRAP=True)
    with app.app_context():
        user = User.query.filter_by(username="admin").one()
        user.role = "member"
        user.is_active = False
        user.is_root = False
        db.session.commit()

    app = make(seed=False, ROOT_ADMIN_BOOTSTRAP=True)

    with app.app_context():
        user = User.query.filter_by(username="admin").one()
        assert (user.role, user.is_active, user.is_root) == ("admin", True, True)


def test_bootstrap_enforces_single_root(file_app):
    """配置文件是唯一真相：手工标出来的第二个 is_root 必须在下次启动被清标。"""
    make, _ = file_app
    app = make(seed=False, ROOT_ADMIN_BOOTSTRAP=True)
    with app.app_context():
        impostor = User(username="impostor", role="admin", is_root=True)
        impostor.set_password("pw12345")
        db.session.add(impostor)
        db.session.commit()

    app = make(seed=False, ROOT_ADMIN_BOOTSTRAP=True)

    with app.app_context():
        assert [u.username for u in User.query.filter_by(is_root=True).all()] == ["admin"]


def test_bootstrap_does_not_reset_password_by_default(file_app):
    """默认不同步口令：否则「在设置页改了密码 → 重启被环境变量改回去」是静默数据丢失。"""
    make, _ = file_app
    app = make(seed=False, ROOT_ADMIN_BOOTSTRAP=True)
    with app.app_context():
        user = User.query.filter_by(username="admin").one()
        user.set_password("MyNewSecret2026")
        db.session.commit()

    app = make(seed=False, ROOT_ADMIN_BOOTSTRAP=True)

    with app.app_context():
        assert User.query.filter_by(username="admin").one().check_password("MyNewSecret2026")


def test_syncs_password_when_flag_on(file_app):
    make, _ = file_app
    app = make(seed=False, ROOT_ADMIN_BOOTSTRAP=True)
    with app.app_context():
        user = User.query.filter_by(username="admin").one()
        user.set_password("MyNewSecret2026")
        db.session.commit()

    app = make(seed=False, ROOT_ADMIN_BOOTSTRAP=True, ROOT_ADMIN_SYNC_PASSWORD=True)

    with app.app_context():
        assert User.query.filter_by(username="admin").one().check_password("admin123")


def test_seed_runs_before_bootstrap_on_fresh_db(file_app):
    """【R-4】全新库启动后示例数据仍在——bootstrap 若抢在 seed 之前，这里会一条都没有。"""
    make, _ = file_app
    app = make(seed=True, ROOT_ADMIN_BOOTSTRAP=True)

    with app.app_context():
        assert Requirement.query.count() == 1
        # 且不会出现两个管理员：seed 建出 admin，bootstrap 认领同一行。
        assert User.query.count() == 1
        user = User.query.one()
        assert user.is_root is True and user.source == "seed"


def test_bootstrap_warns_when_promoting_existing_account(file_app):
    """【R-15】提权是不可逆的授权变更，日志里必须能看到「是谁被提权了」。"""
    make, _ = file_app
    app = make(seed=False)
    with app.app_context():
        ordinary = User(username="admin", role="member")
        ordinary.set_password("pw12345")
        db.session.add(ordinary)
        db.session.commit()
        ordinary_id = ordinary.id

    with captured_warnings() as messages:
        make(seed=False, ROOT_ADMIN_BOOTSTRAP=True)
    promoted = [m for m in messages if "promoted existing account" in m]

    assert len(promoted) == 1
    assert f"id={ordinary_id}" in promoted[0]


def test_created_path_does_not_warn_about_promotion(file_app):
    make, _ = file_app

    with captured_warnings() as messages:
        make(seed=False, ROOT_ADMIN_BOOTSTRAP=True)

    assert not [m for m in messages if "promoted existing account" in m]


def test_sync_password_flag_warns_on_every_boot(file_app):
    """【P1-7】同步口令模式是临时恢复态，每次启动都必须喊——否则新密码会被静默吞掉。"""
    make, _ = file_app
    overrides = {"ROOT_ADMIN_BOOTSTRAP": True, "ROOT_ADMIN_SYNC_PASSWORD": True,
                 "TESTING": False}

    with captured_warnings() as messages:
        make(seed=False, **overrides)
        make(seed=False, **overrides)

    assert len([m for m in messages if "ROOT_ADMIN_SYNC_PASSWORD is ON" in m]) == 2


def test_empty_root_username_fails_fast(file_app):
    """配置写空 = 部署事故，应当起不来而不是静默跳过（没人会发现这根支柱没上线）。"""
    make, _ = file_app

    with pytest.raises(RuntimeError):
        make(seed=False, ROOT_ADMIN_BOOTSTRAP=True, ROOT_ADMIN_USERNAME="   ")


def test_cli_tools_do_not_create_root_admin(file_app, monkeypatch):
    """【P0-2】空库上跑 `purge_demo_data --dry-run`，users 行数必须**保持为 0**。

    这条同时守住两条约定：「dry-run 绝不写库」与「运维工具无用户表副作用」。
    """
    make, db_path = file_app
    app = make(seed=False)
    with app.app_context():
        assert User.query.count() == 0
        db.session.remove()
        db.engine.dispose()
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)

    purge.main(["--database-url", url, "--no-backup"])

    app = make(seed=False)
    with app.app_context():
        assert User.query.count() == 0


# ————————————————————— 保护规则（§2.1 A-4 拦截矩阵）—————————————————————

def _second_admin(app):
    with app.app_context():
        other = User(username="admin2", role="admin", display_name="A2")
        other.set_password("admin2123")
        db.session.add(other)
        db.session.commit()
        return other.id


def test_cannot_demote_root(client, auth, root_admin):
    r = client.patch(f"/api/users/{root_admin}", json={"role": "member"},
                     headers=auth("admin"))

    assert r.status_code == 409
    body = r.get_json()
    assert body["error"] == "root administrator is protected"
    # 前端看板拖拽以 err.allowed 是否存在分流错误，不得误伤（§4.3）。
    assert "allowed" not in body["detail"]


def test_cannot_deactivate_root(client, auth, root_admin):
    r = client.patch(f"/api/users/{root_admin}", json={"is_active": False},
                     headers=auth("admin"))

    assert r.status_code == 409
    assert "deactivated" in r.get_json()["detail"]["reason"]


def test_cannot_reset_root_password_as_other_admin(client, app, auth, root_admin):
    _second_admin(app)
    other = client.post("/api/auth/login",
                        json={"username": "admin2", "password": "admin2123"})
    headers = {"Authorization": f"Bearer {other.get_json()['token']}"}

    r = client.patch(f"/api/users/{root_admin}", json={"password": "Whatever2026"},
                     headers=headers)

    assert r.status_code == 409
    assert "allowed" not in r.get_json()["detail"]


def test_root_can_change_own_password_via_me(client, auth, root_admin):
    """【P1-2】自助改密是 **POST** /api/me/password，不是 PATCH。"""
    r = client.post("/api/me/password",
                    json={"current_password": "admin123", "new_password": "Aragon2026"},
                    headers=auth("admin"))

    assert r.status_code == 200


def test_root_display_name_and_email_are_editable(client, auth, root_admin):
    """改昵称邮箱不威胁治理，放行。"""
    r = client.patch(f"/api/users/{root_admin}",
                     json={"display_name": "Ada R.", "email": "ada@aragon.dev"},
                     headers=auth("admin"))

    assert r.status_code == 200
    assert r.get_json()["display_name"] == "Ada R."


def test_root_guard_precedes_last_admin_guard(client, auth, root_admin):
    """【R-7】两条守卫都会命中时，必须给出更具体、更可操作的那一条。"""
    r = client.patch(f"/api/users/{root_admin}", json={"role": "member"},
                     headers=auth("admin"))

    assert r.get_json()["error"] == "root administrator is protected"
