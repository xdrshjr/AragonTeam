"""版本 / 计划的读写辅助（version-plan-hierarchy §3.6，叶子模块）。

把「版本 / 计划的读写辅助」收敛到一个可单测的叶子模块，避免让已逼近尺寸红线的
`routes/requirements.py` 继续膨胀（CLAUDE.md 二）。本模块**不碰 Flask 响应**——校验
失败抛 `ValidationError`（由 errors.py 统一渲染 400），只提供纯函数。

依赖方向（无环）：`services/hierarchy` → `models/{version,plan,requirement,bug}`
+ `services/{scope,validation,workflow}`；`routes/{versions,plans,requirements,bugs}`
→ `services/hierarchy`。
"""
from flask import request
from sqlalchemy import case, func, select

from extensions import db
from models.bug import Bug
from models.plan import Plan
from models.requirement import Requirement
from models.version import Version
from services import workflow
from services.scope import UNASSIGNED, want_query_int
from services.validation import ValidationError, want_int


# ————————————————————— 排序位分配 —————————————————————

def next_sort_position(model, **filter_by) -> int:
    """按父分组取 `max(position)+1`；**空父（首个子）时 `func.max` 返回 NULL**，须归 0。

    版本 / 计划的排序是「按父分组落尾」，与看板列内 position（services/positions.py）
    不同域，故单独一份。评审 P2-E：不 COALESCE 会把首行 position 置 None → 违反 NOT NULL。

    Args:
        model: Version / Plan 模型类。
        **filter_by: 父分组条件（版本用 project_id=、计划用 version_id=）。

    Returns:
        该父下一个可用 position（空父为 0）。
    """
    current_max = db.session.query(func.max(model.position)).filter_by(**filter_by).scalar()
    return (current_max if current_max is not None else -1) + 1


# ————————————————————— 查询串作用域 —————————————————————

def version_scope():
    """解析 `?version_id=`。返回 None（不过滤）/ UNASSIGNED / int。非法值抛 QueryParamError。"""
    if request.args.get("version_id") == UNASSIGNED:
        return UNASSIGNED
    return want_query_int("version_id")


def plan_scope():
    """解析 `?plan_id=`。返回 None（不过滤）/ UNASSIGNED / int。非法值抛 QueryParamError。"""
    if request.args.get("plan_id") == UNASSIGNED:
        return UNASSIGNED
    return want_query_int("plan_id")


def apply_ticket_hierarchy_filter(query, model):
    """把 version / plan 过滤套到工单查询（requirement / bug 复用）。

    - `?plan_id=<int>` → `plan_id == n`；`?plan_id=none` → `plan_id IS NULL`。
    - `?version_id=<int>` → `plan_id IN (select plans.id where version_id=n)`（plan→version 单跳）；
      `?version_id=none` → `plan_id IS NULL`（无计划 ⟺ 无版本）。
    - 两者同传则 AND 叠加（不一致则自然空集，语义正确）。

    Args:
        query: 工单查询（已可带其他过滤）。
        model: Requirement / Bug 模型类。

    Returns:
        追加了层级过滤的 query。
    """
    plan = plan_scope()
    if plan == UNASSIGNED:
        query = query.filter(model.plan_id.is_(None))
    elif plan is not None:
        query = query.filter(model.plan_id == plan)

    version = version_scope()
    if version == UNASSIGNED:
        query = query.filter(model.plan_id.is_(None))
    elif version is not None:
        query = query.filter(
            model.plan_id.in_(select(Plan.id).where(Plan.version_id == version)))
    return query


# ————————————————————— 写路径：归属计划 —————————————————————

def resolve_plan_for_ticket(ticket, data) -> None:
    """校验并就地应用 `plan_id`（create / patch / convert 三条写路径共享，§3.2）。

    - 请求体**无** `plan_id` 键 → 不改（create 时保持默认 NULL，patch 时保持原值）。
    - `plan_id` 为 JSON `null` → 解除归属（`plan_id=NULL`），不校验。
    - `plan_id` 为整数 → 查计划存在，否则 400；再校验**同项目不变量**：工单已有 project_id
      且 `!= plan.project_id` → 400；工单 project_id 为 NULL → **采纳**计划的项目。

    Args:
        ticket: Requirement / Bug 实例（尚未 commit 皆可）。
        data: 已经过 json_body() 归一的 dict。

    Raises:
        ValidationError: plan_id 非整数 / 超界（want_int）；计划不存在；计划与工单跨项目。
    """
    if "plan_id" not in data:
        return
    if data.get("plan_id") is None:
        ticket.plan_id = None                 # 显式解除归属
        return
    plan_id = want_int(data, "plan_id")       # 非整数 / 超界 → ValidationError（400）
    plan = db.session.get(Plan, plan_id)
    if plan is None:
        raise ValidationError("plan_id is invalid", field="plan_id",
                              expected="an existing plan")
    if ticket.project_id is not None and ticket.project_id != plan.project_id:
        raise ValidationError("plan and ticket must be in the same project",
                              field="plan_id", expected="a plan in the ticket's project")
    if ticket.project_id is None:
        # 无项目工单采纳计划的项目，使其自然落入正确的项目作用域（§3.2）。
        ticket.project_id = plan.project_id
    ticket.plan_id = plan.id


# ————————————————————— 读路径：序列化富化 —————————————————————

def _plan_context_map(plan_ids) -> dict:
    """收集这批 plan_id 的只读概要 `{plan_id: {id, name, version_id, version_name}}`。

    工单→计划一次 `IN`、计划→版本一次 `IN`，零 N+1（复刻 document_counts 做法）。
    指向已删除计划的 plan_id 不在结果里，调用方以 `.get()` 落到 `null`（§3.4 防御）。
    """
    ids = {pid for pid in plan_ids if pid is not None}
    if not ids:
        return {}
    plans = Plan.query.filter(Plan.id.in_(ids)).all()
    version_ids = {p.version_id for p in plans}
    version_names = {}
    if version_ids:
        version_names = {v.id: v.name for v in
                         Version.query.filter(Version.id.in_(version_ids)).all()}
    return {p.id: {"id": p.id, "name": p.name, "version_id": p.version_id,
                   "version_name": version_names.get(p.version_id)} for p in plans}


def with_plan_context(rows) -> list:
    """把一批工单序列化为 dict 并富化只读 `plan` 概要（**恰好两次**批量查询）。

    列表页与看板的统一入口。**不改任何 `to_dict`**（同 document_counts 的理由）。
    """
    tickets = list(rows)
    context = _plan_context_map([t.plan_id for t in tickets])
    return [{**t.to_dict(), "plan": context.get(t.plan_id)} for t in tickets]


def with_plan_context_one(row) -> dict:
    """单张工单的同款富化（详情页 / 写路径的响应体）。"""
    context = _plan_context_map([row.plan_id])
    return {**row.to_dict(), "plan": context.get(row.plan_id)}


def attach_plan_context(dicts) -> list:
    """给一批**已序列化**的工单 dict 就地追加只读 `plan` 概要（读它们自带的 `plan_id`）。

    与 `document_counts.with_document_counts` 的富化**叠加**用：工单列表 / 看板都已在
    序列化站点补过 `document_count`，本函数在其结果上再补 `plan`，两次富化各一批查询、
    互不冲突，仍是零 N+1。就地改并返回同一列表（调用方拿到的就是最终响应体）。
    """
    items = list(dicts)
    context = _plan_context_map([item.get("plan_id") for item in items])
    for item in items:
        item["plan"] = context.get(item.get("plan_id"))
    return items


def attach_plan_context_one(one) -> dict:
    """单张已序列化工单 dict 的同款叠加富化（详情页 / 写路径响应体）。"""
    return attach_plan_context([one])[0]


# ————————————————————— 批量计数（进度条）—————————————————————

def version_plan_counts(ids) -> dict:
    """版本卡的计划数：`{version_id: plan_count}`（一次 GROUP BY version_id）。"""
    id_list = list(ids)
    if not id_list:
        return {}
    rows = (db.session.query(Plan.version_id, func.count(Plan.id))
            .filter(Plan.version_id.in_(id_list))
            .group_by(Plan.version_id).all())
    return {version_id: total for version_id, total in rows}


def version_ticket_counts(ids) -> dict:
    """版本聚合进度（评审 P1-B）：`{version_id: {total, done}}`。

    工单→计划→版本两跳，一次 `GROUP BY versions.id` 聚合（零 N+1）。`done` 用
    `workflow.terminal_statuses` 判定终态（需求 done + BUG closed），**不内联**第二份终态清单。
    这是版本聚合进度的**唯一**数据路径——前端不得对分页 plans 列表客户端求和（会漏算）。
    """
    id_list = list(ids)
    if not id_list:
        return {}
    out = {version_id: {"total": 0, "done": 0} for version_id in id_list}
    for model, entity in ((Requirement, "requirement"), (Bug, "bug")):
        terminal = workflow.terminal_statuses(entity)
        rows = (db.session.query(
                    Plan.version_id,
                    func.count(model.id),
                    func.sum(case((model.status.in_(terminal), 1), else_=0)))
                .join(Plan, Plan.id == model.plan_id)
                .filter(Plan.version_id.in_(id_list))
                .group_by(Plan.version_id).all())
        for version_id, total, done in rows:
            out[version_id]["total"] += total or 0
            out[version_id]["done"] += int(done or 0)
    return out


def plan_ticket_counts(ids) -> dict:
    """计划卡的工单计数：`{plan_id: {requirements, bugs, done}}`（各一次 GROUP BY，零 N+1）。

    `done` 统计终态工单（需求 done + BUG closed），判据复用 `workflow.terminal_statuses`。
    """
    id_list = list(ids)
    if not id_list:
        return {}
    out = {plan_id: {"requirements": 0, "bugs": 0, "done": 0} for plan_id in id_list}
    for model, entity, key in ((Requirement, "requirement", "requirements"),
                               (Bug, "bug", "bugs")):
        terminal = workflow.terminal_statuses(entity)
        rows = (db.session.query(
                    model.plan_id,
                    func.count(model.id),
                    func.sum(case((model.status.in_(terminal), 1), else_=0)))
                .filter(model.plan_id.in_(id_list))
                .group_by(model.plan_id).all())
        for plan_id, total, done in rows:
            out[plan_id][key] += total or 0
            out[plan_id]["done"] += int(done or 0)
    return out
