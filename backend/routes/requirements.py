"""需求路由（§4.3 + Phase-2 + Phase-3）——CRUD + assign + move + convert-to-bug
+ activities + 评论/feed（见 routes/comments.py）+ **agent-advance**。

关键契约：
- 迁移合法性只认 workflow 邻接表（【R-02】），move / convert / agent-advance 一律经 can_transition。
- move 支持 position 精确插入索引（Phase-2 §2.6）；缺省落列尾（向后兼容）。
- 转 BUG 后源需求恒置 bug_fixing（【R-05】），关系由 bugs.related_requirement_id 反查（【R-07】）。
- **Phase-3 §2.4 行级 RBAC（收口 # TODO(rbac-row-level)）**：patch/move 需 can_manage_ticket；
  assign/convert/delete 需 pm/admin；agent-advance 需 pm/admin 或 can_manage_ticket〔R3-01〕。
- **Phase-3 §2.5 乐观并发守卫**：patch/move 接受可选 expected_updated_at，冲突返回 409（无 allowed）。
- **Phase-3 §2.6 列表过滤/检索**：q/status/priority/assignee_*/reporter_id，全部可选、AND 组合、向后兼容。
- **Phase-3 §2.3 通知扇出**：assign/move/convert 写路径末尾扇出通知（在既有事务 commit 前）。
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from sqlalchemy import or_

from extensions import db
from models.requirement import Requirement, PRIORITIES, ASSIGNEE_TYPES, _iso
from models.bug import Bug, SEVERITIES
from models.project import Project
from models.user import User
from models.agent import Agent
from models.activity import Activity
from models.comment import Comment
from models.notification import Notification
from services import workflow, agent_runner, notifications
from services.auth_helpers import (
    require_role, current_user, can_manage_ticket, forbidden,
)
from services import agent_autopilot
from services.pagination import paginate, with_total_count
from services.scope import (
    MAX_DB_INT, MIN_DB_INT, apply_project_filter, project_scope, want_query_int,
)
from services.search import escape_like
from services.validation import json_body, want_str, want_int

bp = Blueprint("requirements", __name__, url_prefix="/api/requirements")


# ————————————————————— 公共辅助 —————————————————————

def _next_position(model, status: str, project_id) -> int:
    """返回「同项目同状态」列的下一个 position（该列现有最大值 + 1；空列为 0）。

    position 的语义是**看板某一列内的相对次序**，而看板已按项目过滤（board.py），
    因此编号必须与看板可见集合同域，否则跨项目卡片会污染插入索引（§2.5）。

    Args:
        model: Requirement / Bug 模型类。
        status: 目标状态列。
        project_id: 工单所属项目 id，未归属传 None。**必填**（评审 R3：给默认值会让
            漏传的调用点静默把单编进「未归属」号段，错得无声无息）。
    """
    rows = model.query.filter_by(status=status, project_id=project_id).all()
    return max((r.position for r in rows), default=-1) + 1


def _coerce_index(value):
    """把 move 的 position 参数安全转为非负 int 插入索引；非法 → None（落列尾）。"""
    if value is None:
        return None
    try:
        idx = int(value)
    except (TypeError, ValueError):
        return None
    return idx if idx >= 0 else None


def _reindex_column(model, status: str, project_id, insert_id=None, insert_index=None):
    """把「同项目同状态」列内的卡按 (position,id) 排序后连续重编号 0..n-1（Phase-2 §2.6）。

    若给 insert_id + insert_index，则先把该卡移到目标索引处再统一重编号，
    实现「同列 / 跨列精确插入」。insert_index 越界时钳到列尾。

    Args:
        project_id: 同为**必填位置参数**（§2.5 / 评审 R3）；插在第三位不影响现网以关键字传
            insert_id / insert_index 的调用点。
    """
    rows = model.query.filter_by(status=status, project_id=project_id)\
        .order_by(model.position.asc(), model.id.asc()).all()
    if insert_id is not None:
        rows = [r for r in rows if r.id != insert_id]
        card = db.session.get(model, insert_id)
        if card is not None:
            idx = insert_index
            if idx is None or idx > len(rows):
                idx = len(rows)
            rows.insert(idx, card)
    for i, r in enumerate(rows):
        r.position = i


def _validate_assignee(assignee_type, assignee_id):
    """校验多态 assignee 目标存在。返回 (ok, error_response_or_None)。

    【§2.8-4】assignee_id 先 int() 兜底，避免非法类型直接进 db.session.get。
    【scale-and-project-scope §2.6①-B / 实施发现 F2】此处**不能**只靠 `want_int`：本路径
    有意保留 `_validate_assignee`（第 2 轮评审 R4：容忍数字串 "5"），因此 64 位硬界必须
    在这里独立复述一次，否则超界 assignee_id 会直接绑进 SQLite → OverflowError → 500。
    """
    if assignee_type not in ASSIGNEE_TYPES:
        return False, (jsonify({"error": "invalid assignee_type",
                                "detail": {"allowed": list(ASSIGNEE_TYPES)}}), 400)
    if assignee_id is None:
        return False, (jsonify({"error": "assignee_id is required"}), 400)
    try:
        numeric = int(assignee_id)
    except (TypeError, ValueError):
        return False, (jsonify({"error": "assignee_id must be an integer"}), 400)
    if numeric < MIN_DB_INT or numeric > MAX_DB_INT:
        return False, (jsonify({
            "error": "assignee_id is out of range",
            "detail": {"field": "assignee_id", "expected": "integer within 64-bit range"},
        }), 400)
    target = db.session.get(User if assignee_type == "user" else Agent, numeric)
    if target is None:
        return False, (jsonify({"error": f"{assignee_type} not found"}), 404)
    return True, None


def _actor():
    """当前操作者 (actor_type, actor_id)，用于写审计。"""
    u = current_user()
    return ("user", u.id) if u else ("system", None)


def _validate_project(project_id):
    """§2.8-1：传了 project_id 时校验其存在。返回 error_response 或 None。"""
    if project_id is not None and db.session.get(Project, project_id) is None:
        return jsonify({"error": "project not found"}), 400
    return None


def check_concurrency(ticket, data):
    """乐观并发守卫（Phase-3 §2.5）——requirement / bug 共用（bugs 蓝图导入本函数）。

    若请求带 `expected_updated_at` 且与当前**已提交** updated_at 不符 → 409（无 `allowed`，
    与状态机 409 区分）；**缺省该字段则不校验**（严格向后兼容 Phase-1/2 调用方）。
    比对为精确 ISO 串（微秒）相等——ticket 由调用方 `db.session.get()` 取得，其 updated_at
    在改字段前即当前已提交值〔R3-05 / 放行条件4〕。返回 409 响应或 None。
    """
    expected = data.get("expected_updated_at")
    if expected is None:
        return None
    current = _iso(ticket.updated_at)
    if expected != current:
        return jsonify({
            "error": "conflict, please reload",
            "detail": {"current_updated_at": current},
        }), 409
    return None


# ————————————————————— CRUD —————————————————————

@bp.get("")
@jwt_required()
def list_requirements():
    # 【§2.4】项目作用域：缺省=不过滤、整数=该项目、"none"=未归属；非法值经全局
    # QueryParamError 处理器统一 400（本函数不写 try/except，见 §2.4①'）。
    q = apply_project_filter(Requirement.query, Requirement, project_scope())
    status = request.args.get("status")
    assignee_type = request.args.get("assignee_type")
    # 【§2.9-G2 / 评审 R1】整数过滤参数一律走 want_query_int：畸形值不再被静默丢弃（→400），
    # 超界值不再绑进 SQLite（此前 OverflowError → 500）。
    assignee_id = want_query_int("assignee_id")
    # 【Phase-3 §2.6】过滤 / 检索（全部可选、AND 组合、向后兼容）。
    keyword = request.args.get("q")
    priority = request.args.get("priority")
    reporter_id = want_query_int("reporter_id")
    if status:
        q = q.filter_by(status=status)
    if assignee_type:
        q = q.filter_by(assignee_type=assignee_type)
    if assignee_id is not None:
        q = q.filter_by(assignee_id=assignee_id)
    if priority:
        q = q.filter_by(priority=priority)
    if reporter_id is not None:
        q = q.filter_by(reporter_id=reporter_id)
    if keyword:
        # 【§2.4-C1】转义 LIKE 元字符（% _ \），令用户输入的 % / _ 作字面量匹配，与 search 一致。
        like = f"%{escape_like(keyword)}%"
        q = q.filter(or_(Requirement.title.ilike(like, escape="\\"),
                         Requirement.description.ilike(like, escape="\\")))
    # 【Phase-2 §2.5-3】分页（非破坏）：响应体仍为裸数组，总数经 X-Total-Count 暴露。
    # 【§2.3】扁平列表按「最近更新」全局排序（与 /me/work 一致）；position 仅服务看板列内排序，
    # 用它排跨状态的扁平列表会交错各列、语义混乱。响应 shape 不变，仅默认顺序更合理。
    q = q.order_by(Requirement.updated_at.desc(), Requirement.id.desc())
    rows, total = paginate(q)
    resp = jsonify([r.to_dict() for r in rows])
    return with_total_count(resp, total), 200


@bp.post("")
@require_role("admin", "pm")
def create_requirement():
    # 【§2.2】非串 title → 400（此前 .strip() 500）；priority 走 choices 归一；
    # project_id 走 want_int（list/dict 主键此前进 db.session.get 触 500）。
    data = json_body()
    title = want_str(data, "title", required=True, max_len=200)
    priority = want_str(data, "priority", default="medium", choices=PRIORITIES)
    # 【§2.4-C3】非串 description（{"x":1}）绑到 Text 列 → commit 触 500；want_str 保证非串即 400。
    # strip=False 保留描述的换行/缩进（描述可为多行工作说明）；缺省/空 → None（与现状一致）。
    description = want_str(data, "description", required=False, strip=False) or None
    project_id = want_int(data, "project_id")
    # §2.8-1：project_id 存在性校验（此前接受任意值不校验）。
    perr = _validate_project(project_id)
    if perr:
        return perr

    reporter = current_user()
    req = Requirement(
        title=title,
        description=description,
        priority=priority,
        project_id=project_id,
        status="new",
        reporter_id=reporter.id if reporter else None,
        position=_next_position(Requirement, "new", project_id),
    )
    db.session.add(req)
    db.session.flush()  # 拿到 req.id 再写审计
    Activity.log("requirement", req.id, "created", actor=_actor(),
                 to_status="new", message=f"创建需求「{title}」")
    db.session.commit()
    return jsonify(req.to_dict()), 201


@bp.get("/<int:req_id>")
@jwt_required()
def get_requirement(req_id):
    req = db.session.get(Requirement, req_id)
    if req is None:
        return jsonify({"error": "requirement not found"}), 404
    return jsonify(req.to_dict()), 200


@bp.patch("/<int:req_id>")
@jwt_required()
def patch_requirement(req_id):
    req = db.session.get(Requirement, req_id)
    if req is None:
        return jsonify({"error": "requirement not found"}), 404
    # 【Phase-3 §2.4】行级 RBAC：仅 reporter / 人类 assignee / pm / admin 可编辑。
    if not can_manage_ticket(current_user(), req):
        return forbidden({"reason": "cannot edit this requirement"})
    data = json_body()
    # 【Phase-3 §2.5】乐观并发守卫（缺省不校验）。
    conflict = check_concurrency(req, data)
    if conflict:
        return conflict
    changed = False
    if "title" in data:
        # 非串 title → 400（此前 .strip() 500）；空串仍 400。
        req.title = want_str(data, "title", required=True, max_len=200)
        changed = True
    if "description" in data:
        # 【§2.4-C3】非串 description → 400（此前直接赋值，commit 触 500）；strip=False 保留正文格式。
        req.description = want_str(data, "description", required=False, strip=False) or None
        changed = True
    if "priority" in data:
        req.priority = want_str(data, "priority", required=True, choices=PRIORITIES)
        changed = True
    # §2.8-3：编辑也进时间线，让 feed 覆盖全生命周期。
    if changed:
        Activity.log("requirement", req.id, "updated", actor=_actor(),
                     to_status=req.status, message="更新了需求信息")
    db.session.commit()
    return jsonify(req.to_dict()), 200


@bp.delete("/<int:req_id>")
@require_role("admin", "pm")
def delete_requirement(req_id):
    req = db.session.get(Requirement, req_id)
    if req is None:
        return jsonify({"error": "requirement not found"}), 404
    # 删除前先把其转出 BUG 的 related_requirement_id 置空，避免悬挂外键（§5 删除策略）。
    Bug.query.filter_by(related_requirement_id=req_id).update(
        {"related_requirement_id": None})
    # §5：删单一并删其评论，避免悬挂多态记录。
    Comment.query.filter_by(entity_type="requirement", entity_id=req_id).delete()
    # 【Phase-3 §5】删单一并删其通知，避免点击直达到已删单。
    Notification.query.filter_by(entity_type="requirement", entity_id=req_id).delete()
    # 【§2.7】删单一并删审计：SQLite 复用主键，残留审计会被下一张同 id 的单继承，
    # 造成时间线串档 + 已删单标题泄露。审计的价值绑定在「单还在」这一前提上。
    # 有意**不再**写 "deleted" 审计——该单已不存在，其审计无查看入口，且会被同批清掉。
    Activity.query.filter_by(entity_type="requirement", entity_id=req_id).delete()
    db.session.delete(req)
    db.session.commit()
    return "", 204


# ————————————————————— assign / move / convert —————————————————————

@bp.patch("/<int:req_id>/assign")
@require_role("admin", "pm")  # 【Phase-3 §2.4】指派 / 改派仅 pm/admin。
def assign_requirement(req_id):
    req = db.session.get(Requirement, req_id)
    if req is None:
        return jsonify({"error": "requirement not found"}), 404
    # 【§2.2 / R4】仅体层加 json_body()（防非对象体 500）；assignee 保持既有
    # _validate_assignee（已做类型+存在性校验、有意容忍数字串 "5"→5，不回退为 want_int）。
    data = json_body()
    assignee_type = data.get("assignee_type")
    assignee_id = data.get("assignee_id")

    ok, err = _validate_assignee(assignee_type, assignee_id)
    if not ok:
        return err

    req.assignee_type = assignee_type
    req.assignee_id = int(assignee_id)  # §2.8-4：入库前统一 int。
    # new → assigned 自动迁移（经邻接表校验合法性；【T4】）。
    frm = req.status
    if req.status == "new" and workflow.can_transition("requirement", "new", "assigned"):
        req.status = "assigned"
        req.position = _next_position(Requirement, "assigned", req.project_id)

    target = db.session.get(User if assignee_type == "user" else Agent, req.assignee_id)
    name = getattr(target, "display_name", None) or getattr(target, "name", str(assignee_id))
    Activity.log("requirement", req.id, "assigned", actor=_actor(),
                 from_status=frm, to_status=req.status,
                 message=f"指派给{'成员' if assignee_type == 'user' else 'Agent'}「{name}」")
    # 【Phase-3 §2.3】扇出：通知新的人类 assignee（Agent 不发）。
    notifications.notify_assignment(req, "requirement", actor=_actor())
    db.session.commit()
    return jsonify(req.to_dict()), 200


@bp.patch("/<int:req_id>/move")
@jwt_required()
def move_requirement(req_id):
    req = db.session.get(Requirement, req_id)
    if req is None:
        return jsonify({"error": "requirement not found"}), 404
    # 【Phase-3 §2.4】行级 RBAC：仅 can_manage_ticket 可移动。
    if not can_manage_ticket(current_user(), req):
        return forbidden({"reason": "cannot move this requirement"})
    data = json_body()
    # 【§2.3-B1】status 必须先是字符串再进状态机：非空 list（{"status":["assigned"]}）此前
    # 是真值 → `status in _table`（dict）对不可哈希类型触 unhashable 500。want_str 保证非串即 400。
    to = want_str(data, "status", required=True)
    if not workflow.is_valid_status("requirement", to):
        return jsonify({"error": "invalid target status",
                        "detail": {"allowed": workflow.column_keys("requirement")}}), 400

    # 【Phase-3 §2.5】乐观并发守卫——同列早退分支也须**先过守卫**〔放行条件4〕。
    conflict = check_concurrency(req, data)
    if conflict:
        return conflict

    frm = req.status
    index = _coerce_index(data.get("position"))
    if frm == to:
        # 同列内拖动（Phase-2 §2.6）：带 position 则精确重排，否则落列尾。
        if index is not None:
            _reindex_column(Requirement, to, req.project_id,
                            insert_id=req.id, insert_index=index)
        else:
            req.position = _next_position(Requirement, to, req.project_id)
        db.session.commit()
        return jsonify(req.to_dict()), 200

    # 【R-02】唯一裁决：邻接表 can_transition。
    if not workflow.can_transition("requirement", frm, to):
        return jsonify({
            "error": "illegal transition",
            "detail": {"from": frm, "to": to},
            "allowed": workflow.next_states("requirement", frm),
        }), 409

    req.status = to
    # Phase-2 §2.6：带 position 精确插入并重编号目标列；否则落列尾（向后兼容）。
    if index is not None:
        _reindex_column(Requirement, to, req.project_id,
                        insert_id=req.id, insert_index=index)
    else:
        req.position = _next_position(Requirement, to, req.project_id)
    Activity.log("requirement", req.id, "moved", actor=_actor(),
                 from_status=frm, to_status=to,
                 message=f"状态 {frm} → {to}")
    # 【Phase-3 §2.3】扇出：人类推进 → status_changed 通知 reporter / 人类 assignee。
    notifications.notify_advance(req, "requirement", actor=_actor(),
                                 from_status=frm, to_status=to)
    db.session.commit()
    return jsonify(req.to_dict()), 200


@bp.post("/<int:req_id>/convert-to-bug")
@require_role("admin", "pm")  # 【Phase-3 §2.4】转 BUG 仅 pm/admin。
def convert_to_bug(req_id):
    req = db.session.get(Requirement, req_id)
    if req is None:
        return jsonify({"error": "requirement not found"}), 404

    # 【R-05】先校验：源需求须能迁移到 bug_fixing（当前态 ∈ {testing, reviewing}）。
    frm = req.status
    if not workflow.can_transition("requirement", frm, "bug_fixing"):
        return jsonify({
            "error": "illegal transition",
            "detail": {"from": frm, "to": "bug_fixing"},
            "allowed": workflow.next_states("requirement", frm),
        }), 409

    # 【§2.2】非串 title → 400（此前 .strip() 500）；severity 走 choices 归一。
    data = json_body()
    title = want_str(data, "title") or f"[缺陷] {req.title}"
    severity = want_str(data, "severity", default="major", choices=SEVERITIES) or "major"
    # 【§2.6②】非串 description（{"a":1}）绑到 Text 列 → autoflush 触 500；want_str 保证非串即 400。
    description = want_str(data, "description", required=False, strip=False) or None

    reporter = current_user()
    bug = Bug(
        title=title,
        description=description or f"由需求 #{req.id} 转入的缺陷单。",
        severity=severity,
        status="open",
        project_id=req.project_id,
        related_requirement_id=req.id,
        reporter_id=reporter.id if reporter else None,
        position=_next_position(Bug, "open", req.project_id),
    )
    db.session.add(bug)

    # 源需求恒迁移到 bug_fixing。
    req.status = "bug_fixing"
    req.position = _next_position(Requirement, "bug_fixing", req.project_id)

    db.session.flush()  # 拿 bug.id
    Activity.log("requirement", req.id, "converted", actor=_actor(),
                 from_status=frm, to_status="bug_fixing",
                 message=f"转为 BUG #{bug.id}")
    Activity.log("bug", bug.id, "created", actor=_actor(),
                 to_status="open", message=f"由需求 #{req.id} 转入")
    # 【Phase-3 §2.3】扇出：通知源需求 reporter / 人类 assignee。
    notifications.notify_convert(req, bug, actor=_actor())
    db.session.commit()
    return jsonify(bug.to_dict()), 201


# ————————————————————— Agent 协作运行时（Phase-2 支柱 A）—————————————————————

@bp.post("/<int:req_id>/agent-advance")
@jwt_required()  # 行级 RBAC 在 do_agent_advance 内联裁决〔R3-01〕。
def agent_advance_requirement(req_id):
    return do_agent_advance("requirement", Requirement, req_id)


def _no_action_409(exc):
    """「该 Agent 在此状态无动作」的 409 契约体。稳定错误串，勿更名（CLAUDE.md §五）。"""
    return jsonify({"error": "agent has no action for this state",
                    "detail": {"kind": exc.kind, "status": exc.status}}), 409


def _advance_with_handoff(entity, ticket, agent):
    """推进一步；本 Agent 无动作时先交接给对口 Agent 再重试**一次**（§2.2③，无循环）。

    这样存量卡死单（generic@in_development、seed 的 qa@fixing）一次点击即可复活。

    Args:
        entity: "requirement" | "bug"。
        ticket: 目标工单（状态迁移由 advance_one 经 workflow 裁决，本函数不碰状态机）。
        agent: 当前 assignee 对应的 Agent。

    Returns:
        (to, comment, agent, None)：推进成功，`agent` 是**实际执行本步**的 Agent（可能已易主）；
        (None, None, None, response)：仍无对口 Agent，`response` 为契约不变的 409。
    """
    try:
        to, comment, _activity = agent_runner.advance_one(entity, ticket, agent)
        return to, comment, agent, None
    except agent_runner.NoAgentAction as e:
        handed = agent_autopilot.maybe_handoff(entity, ticket)
        if handed is None:
            return None, None, None, _no_action_409(e)
    db.session.commit()              # 交接本身即为可持久化的进展
    try:
        to, comment, _activity = agent_runner.advance_one(entity, ticket, handed)
    except agent_runner.NoAgentAction as e2:
        # 交接已落库（净进展），但新 Agent 仍无动作 → 仍返 409，契约不变。
        return None, None, None, _no_action_409(e2)
    return to, comment, handed, None


def do_agent_advance(entity, model, ticket_id):
    """Agent 单步 / run=all 推进的共享编排（requirement / bug 同构，bugs 蓝图复用）。"""
    ticket = db.session.get(model, ticket_id)
    if ticket is None:
        return jsonify({"error": f"{entity} not found"}), 404
    # 【Phase-3 §2.4 / R3-01】**有意收紧**的行级 RBAC：pm/admin 或 can_manage_ticket。
    # 否则 member 可借 Agent 推进一张自己无权 move/patch 的单，形成 RBAC 旁路。
    if not can_manage_ticket(current_user(), ticket):
        return forbidden({"reason": "cannot advance this ticket"})
    # 前置校验：必须已指派给存在的 Agent。
    if ticket.assignee_type != "agent" or ticket.assignee_id is None:
        return jsonify({"error": "ticket is not assigned to an agent"}), 409
    agent = db.session.get(Agent, ticket.assignee_id)
    if agent is None:
        return jsonify({"error": "ticket is not assigned to an agent"}), 409

    if request.args.get("run") == "all":
        # 【§2.6-E2】run=all 有 busy 软锁窗口，须与 /autorun、/tick 一致地尊重 busy/offline，
        # 否则并发下会盲目置 busy、finally 归 idle，提前释放另一条 run 的锁。
        if agent.status in ("busy", "offline"):
            return jsonify({"error": "agent is busy or offline"}), 409
        return _agent_run_all(entity, ticket, agent)

    # —— 单步（【R-04】同步单事务，终态即 idle，不写不可观测的 busy）——
    frm = ticket.status
    to, comment, agent, err = _advance_with_handoff(entity, ticket, agent)
    if err is not None:
        return err
    db.session.commit()
    # 【Phase-3 §2.3】在 advance_one 外层扇出（不侵入其本体），通知 reporter / 人类 assignee。
    notifications.notify_advance(ticket, entity, actor=("agent", agent.id),
                                 from_status=frm, to_status=to)
    db.session.commit()
    # —— 推进成功后即时交接，使下一次点击由对口 Agent 接力（与 autopilot 同策略）——
    if agent_autopilot.maybe_handoff(entity, ticket) is not None:
        db.session.commit()
    return jsonify({
        "ticket": ticket.to_dict(),
        "comment": comment.to_dict(),
        "agent": agent.to_dict(),
    }), 200


def _agent_run_all(entity, ticket, agent):
    """连续推进至无动作 / 终态 / MAX_AGENT_STEPS 上限（Phase-2 §2.2.3 P1）。

    【R-04】唯有 run=all 逐步 commit，busy 才成为可观测窗口：先置 busy 并 commit，
    循环每步各自 commit，finally **恢复原状态** 并 commit（含异常路径，§2.6-E2 统一软锁语义）。
    """
    prev = agent.status
    agent.status = "busy"
    db.session.commit()
    steps = []
    try:
        for _ in range(agent_runner.MAX_AGENT_STEPS):
            frm = ticket.status
            try:
                to, comment, _activity = agent_runner.advance_one(entity, ticket, agent)
            except agent_runner.NoAgentAction:
                # 【§2.2③】卡住时先交接给对口 Agent（本次 run 到此为止，由下次调用接力）。
                if agent_autopilot.maybe_handoff(entity, ticket) is not None:
                    db.session.commit()
                break
            db.session.commit()
            steps.append({"to_status": to, "comment": comment.to_dict()})
            # 【Phase-3 §2.3】每步扇出推进通知（在 advance_one 外层）。
            notifications.notify_advance(ticket, entity, actor=("agent", agent.id),
                                         from_status=frm, to_status=to)
            db.session.commit()
            if workflow.is_terminal(entity, ticket.status):
                break
            # 【§2.2③】交接后必须 break：busy 软锁 prev 只锁住**原** Agent，finally 也只恢复它。
            # 若换人后继续跑，新 Agent 未被加锁，会与 /autorun 并发撞车。与 autopilot.autorun 一致。
            if agent_autopilot.maybe_handoff(entity, ticket) is not None:
                db.session.commit()
                break
    finally:
        # 【§2.9-G3】先回滚可能的半提交事务，否则 commit 自身抛 PendingRollbackError，
        # 软锁恢复丢失 → Agent 永久 busy（此后每次 autorun/tick/run=all 都 409）。
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover - 回滚失败仅可能掩盖原异常，不再抛出
            pass
        agent.status = prev
        db.session.commit()
    return jsonify({
        "ticket": ticket.to_dict(),
        "agent": agent.to_dict(),
        "steps": steps,
    }), 200


@bp.get("/<int:req_id>/activities")
@jwt_required()
def requirement_activities(req_id):
    req = db.session.get(Requirement, req_id)
    if req is None:
        return jsonify({"error": "requirement not found"}), 404
    acts = Activity.query.filter_by(entity_type="requirement", entity_id=req_id)\
        .order_by(Activity.created_at.desc(), Activity.id.desc()).all()
    return jsonify([a.to_dict() for a in acts]), 200
