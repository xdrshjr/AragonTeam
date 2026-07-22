"""services/hierarchy 单元（version-plan-hierarchy §8.1）。

覆盖：resolve_plan_for_ticket 的同项目不变量与「无项目工单采纳计划项目」；
apply_ticket_hierarchy_filter 的 version_id / plan_id / none 各分支；with_plan_context
批量富化零 N+1（查询计数断言）。
"""
import pytest
from sqlalchemy import event

from extensions import db
from models.plan import Plan
from models.project import Project
from models.requirement import Requirement
from models.version import Version
from services import hierarchy
from services.validation import ValidationError


def _make_plan(project_id, name="p"):
    version = Version(name="v", project_id=project_id, status="active", position=0)
    db.session.add(version)
    db.session.flush()
    plan = Plan(name=name, version_id=version.id, project_id=project_id,
                status="active", position=0)
    db.session.add(plan)
    db.session.flush()
    return version, plan


# ————————————————————— resolve_plan_for_ticket —————————————————————

def test_resolve_plan_adopts_project_for_projectless_ticket(app, data):
    with app.app_context():
        _version, plan = _make_plan(data["project_id"])
        req = Requirement(title="t", status="new", project_id=None, position=0)
        db.session.add(req)
        db.session.flush()

        hierarchy.resolve_plan_for_ticket(req, {"plan_id": plan.id})

        assert req.plan_id == plan.id
        assert req.project_id == data["project_id"]      # 采纳计划的项目


def test_resolve_plan_rejects_cross_project(app, data):
    with app.app_context():
        _version, plan = _make_plan(data["project_id"])
        other = Project(name="o", key="OTH")
        db.session.add(other)
        db.session.flush()
        req = Requirement(title="t", status="new", project_id=other.id, position=0)
        db.session.add(req)
        db.session.flush()

        with pytest.raises(ValidationError):
            hierarchy.resolve_plan_for_ticket(req, {"plan_id": plan.id})


def test_resolve_plan_missing_plan_raises(app, data):
    with app.app_context():
        req = Requirement(title="t", status="new", project_id=data["project_id"], position=0)
        db.session.add(req)
        db.session.flush()

        with pytest.raises(ValidationError):
            hierarchy.resolve_plan_for_ticket(req, {"plan_id": 999999})


def test_resolve_plan_null_clears_assignment(app, data):
    with app.app_context():
        _version, plan = _make_plan(data["project_id"])
        req = Requirement(title="t", status="new", project_id=data["project_id"],
                          plan_id=plan.id, position=0)
        db.session.add(req)
        db.session.flush()

        hierarchy.resolve_plan_for_ticket(req, {"plan_id": None})
        assert req.plan_id is None


def test_resolve_plan_absent_key_is_noop(app, data):
    with app.app_context():
        _version, plan = _make_plan(data["project_id"])
        req = Requirement(title="t", status="new", project_id=data["project_id"],
                          plan_id=plan.id, position=0)
        db.session.add(req)
        db.session.flush()

        hierarchy.resolve_plan_for_ticket(req, {"title": "x"})    # 无 plan_id 键 → 不改
        assert req.plan_id == plan.id


# ————————————————————— apply_ticket_hierarchy_filter —————————————————————

def test_filter_plan_none_returns_only_unassigned(app, data):
    with app.app_context():
        _version, plan = _make_plan(data["project_id"])
        assigned = Requirement(title="w", status="new", project_id=data["project_id"],
                               plan_id=plan.id, position=0)
        free = Requirement(title="wo", status="new", project_id=data["project_id"], position=1)
        db.session.add_all([assigned, free])
        db.session.commit()
        assigned_id, free_id = assigned.id, free.id

        with app.test_request_context("/?plan_id=none"):
            q = hierarchy.apply_ticket_hierarchy_filter(Requirement.query, Requirement)
            ids = {r.id for r in q.all()}
        assert free_id in ids and assigned_id not in ids


def test_filter_plan_id_exact(app, data):
    with app.app_context():
        _version, plan = _make_plan(data["project_id"])
        member = Requirement(title="in", status="new", project_id=data["project_id"],
                             plan_id=plan.id, position=0)
        other = Requirement(title="out", status="new", project_id=data["project_id"], position=1)
        db.session.add_all([member, other])
        db.session.commit()
        member_id, other_id, pid = member.id, other.id, plan.id

        with app.test_request_context(f"/?plan_id={pid}"):
            q = hierarchy.apply_ticket_hierarchy_filter(Requirement.query, Requirement)
            ids = {r.id for r in q.all()}
        assert ids == {member_id}
        assert other_id not in ids


def test_filter_version_id_subquery(app, data):
    with app.app_context():
        version, plan = _make_plan(data["project_id"])
        member = Requirement(title="in", status="new", project_id=data["project_id"],
                             plan_id=plan.id, position=0)
        other = Requirement(title="out", status="new", project_id=data["project_id"], position=1)
        db.session.add_all([member, other])
        db.session.commit()
        member_id, other_id, vid = member.id, other.id, version.id

        with app.test_request_context(f"/?version_id={vid}"):
            q = hierarchy.apply_ticket_hierarchy_filter(Requirement.query, Requirement)
            ids = {r.id for r in q.all()}
        assert member_id in ids and other_id not in ids


# ————————————————————— with_plan_context 零 N+1 —————————————————————

def test_with_plan_context_is_batched(app, data):
    """富化 5 行工单的 plan 概要只发 2 条批量查询（plans IN + versions IN），零 N+1。"""
    with app.app_context():
        version, plan = _make_plan(data["project_id"])
        for i in range(5):
            db.session.add(Requirement(title=f"r{i}", status="new",
                                       project_id=data["project_id"], plan_id=plan.id, position=i))
        db.session.commit()
        rows = Requirement.query.all()

        counter = {"n": 0}

        def _count(conn, clauseelement, multiparams, params, execution_options):
            counter["n"] += 1

        event.listen(db.engine, "before_execute", _count)
        try:
            out = hierarchy.with_plan_context(rows)
        finally:
            event.remove(db.engine, "before_execute", _count)

        assert counter["n"] <= 2         # plans 一次 + versions 一次，与行数无关
        assert all(item["plan"]["name"] == plan.name for item in out)
        assert all(item["plan"]["version_id"] == version.id for item in out)
        assert all(item["plan"]["version_name"] == "v" for item in out)


def test_with_plan_context_deleted_plan_yields_null(app, data):
    """plan_id 指向已删除计划时 plan 置 null（§3.4 防御）。"""
    with app.app_context():
        _version, plan = _make_plan(data["project_id"])
        req = Requirement(title="orphan", status="new", project_id=data["project_id"],
                          plan_id=plan.id, position=0)
        db.session.add(req)
        db.session.commit()
        db.session.delete(plan)          # 直接删计划（绕过守卫，构造悬挂 plan_id）
        db.session.commit()

        out = hierarchy.with_plan_context_one(db.session.get(Requirement, req.id))
        assert out["plan_id"] == req.plan_id     # plan_id 仍在
        assert out["plan"] is None               # 但概要为 null，不说谎
