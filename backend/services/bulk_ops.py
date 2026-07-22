"""批量操作引擎（bulk-operations §2.2）——需求 / BUG 共用一条流水线。

【为什么要有这一层】「批量指派 / 批量流转 / 批量改级别 / 批量删除」四件事，若直接
写进路由，需求侧与 BUG 侧就是**八份**实现，而其中最容易写歪的恰恰是「哪些校验必须
逐项做、哪一类错误算整单失败」这条边界。本模块把它收敛成一条流水线：

    解析并校验请求级参数 → 逐项**先裁决后写入** → 一次 commit → 回三桶结果

四条契约，逐条对应一个真实风险：

1. **逐项裁决、整批部分成功**：一张不合法的单不该拖垮同批另外 49 张。由于全部裁决
   都是纯读检查（存在性 / 行级 RBAC / 状态机），被判失败的单**从未被写过**，因此
   不需要 SAVEPOINT，也就不存在「回滚了一半」的中间态。
2. **HTTP 状态码只表达「请求本身是否合法」**：请求格式正确 → 恒 200，成败逐项在
   响应体里讲清楚；`ids` 非法 / `action` 未知 / 超出批量上限 → 400；粗粒度角色不足
   → 403。若「有一项失败就 4xx」，前端只能整批重来，批量功能也就没有意义了。
3. **不新增状态机旁路**：流转合法性仍只认 `workflow.can_transition`（【R-02】），
   级联清理仍只认 `lifecycle.delete_ticket_cascade`，行级门禁仍只认
   `auth_helpers.can_manage_ticket`。本模块只负责编排，不复制任何一条规则。
4. **门禁与单条端点逐一对齐**：assign / unassign / delete 限 pm/admin（同
   `PATCH /:id/assign`、`DELETE /:id`）；move / priority / severity / plan 逐项走
   `can_manage_ticket`（同 `PATCH /:id/move`、`PATCH /:id`）。批量绝不能成为
   绕开 RBAC 的后门——那是本轮最需要防住的事。

响应体形状（稳定契约，勿更名字段）：

    {
      "entity": "requirement", "action": "move", "requested": 3,
      "succeeded": [1, 2],
      "skipped":   [{"id": 3, "reason": "already in target status"}],
      "failed":    [{"id": 9, "error": "...", "detail": {...}}],
      "counts":    {"requested": 3, "succeeded": 2, "skipped": 1, "failed": 0}
    }

注意 `failed[].detail.allowed`：单条 move 的 409 把 `allowed` 放在**响应体顶层**，
前端看板拖拽据 `err.allowed` 是否存在分流错误（lifecycle §4.3）。批量响应恒 200 且
顶层永不出现 `allowed`，故不会误伤那条判据。
"""
from flask import jsonify

from extensions import db
from models.activity import Activity
from models.agent import Agent
from models.bug import Bug, SEVERITIES
from models.plan import Plan
from models.requirement import Requirement, PRIORITIES, ASSIGNEE_TYPES
from models.user import User
from services import hierarchy, lifecycle, notifications, workflow
from services.auth_helpers import can_manage_ticket, forbidden
from services.positions import next_position
from services.scope import MAX_DB_INT
from services.validation import ValidationError, want_int, want_str

# 单次批量的 id 上限。取值与 `pagination.MAX_LIMIT` 一致：用户一屏最多能看到
# MAX_LIMIT 条，「全选可见项」就永远不会撞上这个上限；同时它也挡住了「一发请求写
# 几万行 + 扇出几万条通知」的放大攻击面。
MAX_BULK_IDS = 200

# entity → (模型类, 级别字段名, 级别合法取值, 级别中文名)。
# 「级别」是需求的 priority 与 BUG 的 severity 的统称——两者在批量语义上完全同构，
# 但**不共用一个 action 名**：`priority` 只对需求合法、`severity` 只对 BUG 合法，
# 错配即 400。这比一个多态的 "level" 更难用错。
_SPECS = {
    "requirement": (Requirement, "priority", PRIORITIES, "优先级"),
    "bug": (Bug, "severity", SEVERITIES, "严重度"),
}

# action → 粗粒度角色门禁；None 表示不做角色门禁，改由逐项 can_manage_ticket 裁决。
_ROLE_GATES = {
    "move": None,
    "assign": ("admin", "pm"),
    "unassign": ("admin", "pm"),
    "priority": None,
    "severity": None,
    # 【version-plan-console §3.8】归属计划：**必须**是 None（不做粗粒度角色门禁），
    # 因为 plan_id 的单条写路径是 `PATCH /api/{requirements,bugs}/<id>`，其门禁为行级
    # `can_manage_ticket`。plan 与 priority/severity 同型（都是「把工单某字段设成某值」），
    # 故同门禁——把它设成 ("admin","pm") 就会违反本模块 :20-23 那条「门禁与单条端点逐一
    # 对齐」的不变量，并造出「一张一张改得动、一次改多张就 403」的认知断裂。
    "plan": None,
    "delete": ("admin", "pm"),
}

ACTIONS = tuple(_ROLE_GATES)


def _fail(ticket_id: int, error: str, detail=None) -> dict:
    """一条逐项失败记录。`error` 串与单条端点的错误串保持一致，便于前端复用文案。"""
    row = {"id": ticket_id, "error": error}
    if detail is not None:
        row["detail"] = detail
    return row


def _skip(ticket_id: int, reason: str) -> dict:
    """一条逐项跳过记录（请求的目标状态本就成立，不算失败也不该重复写审计）。"""
    return {"id": ticket_id, "reason": reason}


def parse_ids(data: dict) -> list:
    """取 `ids` 并归一为「保序去重的正整数列表」；任何格式问题 → ValidationError（400）。

    保序：逐项结果按用户提交的顺序回报，才对得上界面里的行序。
    去重：同一个 id 提交两次不该被执行两次——那会写两条审计、发两条通知。

    Args:
        data: 已经过 `json_body()` 归一的请求体。

    Returns:
        去重后的 id 列表，长度 ∈ [1, MAX_BULK_IDS]。

    Raises:
        ValidationError: 非数组 / 空数组 / 超上限 / 元素非正整数 / 元素超 64 位。
    """
    raw = data.get("ids")
    if not isinstance(raw, list):
        raise ValidationError("ids is required", field="ids",
                              expected="array of integers")
    if not raw:
        raise ValidationError("ids must not be empty", field="ids",
                              expected="at least one id")
    if len(raw) > MAX_BULK_IDS:
        raise ValidationError("too many ids", field="ids",
                              expected=f"at most {MAX_BULK_IDS} ids")
    seen, ids = set(), []
    for item in raw:
        # bool 是 int 子类；与 want_int 同口径显式排除，免得 `true` 被当成 id=1。
        if isinstance(item, bool) or not isinstance(item, int):
            raise ValidationError("ids must be integers", field="ids",
                                  expected="array of integers")
        if item < 1 or item > MAX_DB_INT:
            raise ValidationError("id is out of range", field="ids",
                                  expected="positive integer within 64-bit range")
        if item not in seen:
            seen.add(item)
            ids.append(item)
    return ids


def _resolve_assignee(data: dict):
    """校验 assign 的**请求级**参数（指派目标只有一个，不必逐项重复查库）。

    Returns:
        (params, error_response_or_None)；params 形如
        `{"assignee_type": "agent", "assignee_id": 3, "assignee_name": "dev-agent"}`。
        名字在这里一并取出，逐项写审计时就不必每张单再查一次同一行。

    Raises:
        ValidationError: assignee_id 非整数 / 超界（经全局处理器 → 400）。
    """
    assignee_type = want_str(data, "assignee_type", required=True,
                             choices=ASSIGNEE_TYPES)
    raw_id = data.get("assignee_id")
    if isinstance(raw_id, bool) or not isinstance(raw_id, int):
        raise ValidationError("assignee_id must be an integer", field="assignee_id",
                              expected="integer")
    if raw_id < 1 or raw_id > MAX_DB_INT:
        raise ValidationError("assignee_id is out of range", field="assignee_id",
                              expected="positive integer within 64-bit range")
    target = db.session.get(User if assignee_type == "user" else Agent, raw_id)
    if target is None:
        # 与单条 /assign 一致：指派目标不存在是**整单**失败，不是逐项失败。
        return None, (jsonify({"error": f"{assignee_type} not found"}), 404)
    name = (getattr(target, "display_name", None) or getattr(target, "name", None)
            or str(raw_id))
    return {"assignee_type": assignee_type, "assignee_id": raw_id,
            "assignee_name": name}, None


class _Runner:
    """一次批量请求的执行器：持有请求级参数，逐项裁决并累积三桶结果。

    每个 `_do_*` 方法处理**一张**工单，返回 (bucket, payload)，其中 bucket ∈
    {"succeeded", "skipped", "failed"}。方法内只做「裁决 → 写入 session」，
    绝不 commit——提交由 `run` 在全部逐项处理完之后统一做一次。
    """

    def __init__(self, entity: str, action: str, params: dict, user, actor):
        self.entity = entity
        self.action = action
        self.params = params
        self.user = user
        self.actor = actor
        self.model, self.level_field, _choices, self.level_label = _SPECS[entity]

    # —— 逐项动作 ——

    def _do_move(self, ticket):
        to = self.params["status"]
        if not can_manage_ticket(self.user, ticket):
            return "failed", _fail(ticket.id, "forbidden",
                                   {"reason": f"cannot move this {self.entity}"})
        frm = ticket.status
        if frm == to:
            return "skipped", _skip(ticket.id, "already in target status")
        if not workflow.can_transition(self.entity, frm, to):
            return "failed", _fail(ticket.id, "illegal transition", {
                "from": frm, "to": to,
                "allowed": workflow.next_states(self.entity, frm),
            })
        ticket.status = to
        # 批量流转一律落列尾：批量没有「拖到第几张之前」的语义，精确插入索引是
        # 拖拽独有的（routes.requirements._reindex_column），此处不该借用。
        ticket.position = next_position(self.model, to, ticket.project_id)
        Activity.log(self.entity, ticket.id, "moved", actor=self.actor,
                     from_status=frm, to_status=to, message=f"状态 {frm} → {to}")
        notifications.notify_advance(ticket, self.entity, actor=self.actor,
                                     from_status=frm, to_status=to)
        return "succeeded", ticket.id

    def _do_assign(self, ticket):
        assignee_type, assignee_id = self.params["assignee_type"], self.params["assignee_id"]
        if ticket.assignee_type == assignee_type and ticket.assignee_id == assignee_id:
            return "skipped", _skip(ticket.id, "already assigned to this target")
        ticket.assignee_type = assignee_type
        ticket.assignee_id = assignee_id
        frm = ticket.status
        # 首列 → assigned 的自动迁移，与单条 /assign 同规则；首列 key 取自 workflow
        # 列定义（需求 new / BUG open），不在这里内联第二份状态清单。
        initial = workflow.column_keys(self.entity)[0]
        if frm == initial and workflow.can_transition(self.entity, initial, "assigned"):
            ticket.status = "assigned"
            ticket.position = next_position(self.model, "assigned", ticket.project_id)
        who = "成员" if assignee_type == "user" else "Agent"
        Activity.log(self.entity, ticket.id, "assigned", actor=self.actor,
                     from_status=frm, to_status=ticket.status,
                     message=f"指派给{who}「{self.params['assignee_name']}」")
        notifications.notify_assignment(ticket, self.entity, actor=self.actor)
        return "succeeded", ticket.id

    def _do_unassign(self, ticket):
        # 幂等语义（含「本就未指派 → 不写审计不发通知」）唯一真相在 lifecycle。
        if lifecycle.unassign_ticket(ticket, self.entity, self.actor):
            return "succeeded", ticket.id
        return "skipped", _skip(ticket.id, "already unassigned")

    def _do_level(self, ticket):
        value = self.params["value"]
        if not can_manage_ticket(self.user, ticket):
            return "failed", _fail(ticket.id, "forbidden",
                                   {"reason": f"cannot edit this {self.entity}"})
        if getattr(ticket, self.level_field) == value:
            return "skipped", _skip(ticket.id, f"already at this {self.level_field}")
        setattr(ticket, self.level_field, value)
        Activity.log(self.entity, ticket.id, "updated", actor=self.actor,
                     to_status=ticket.status,
                     message=f"{self.level_label}调整为 {value}")
        return "succeeded", ticket.id

    def _do_plan(self, ticket):
        """归属 / 解除归属到目标计划。跨项目是**逐项**失败（不同单可能属不同项目）。"""
        plan = self.params["plan"]
        target_id = plan.id if plan else None
        if not can_manage_ticket(self.user, ticket):
            return "failed", _fail(ticket.id, "forbidden",
                                   {"reason": f"cannot edit this {self.entity}"})
        if ticket.plan_id == target_id:
            return "skipped", _skip(ticket.id, "already in target plan")
        try:
            # 复用单条写路径的唯一判据（同项目不变量 / 无项目工单采纳计划项目），
            # 绝不在此内联第二份规则。ValidationError 在这里必须被**逐项**接住——
            # 让它冒到全局处理器会把整批变成一个 400，其余合法工单全被连坐。
            hierarchy.resolve_plan_for_ticket(ticket, {"plan_id": target_id})
        except ValidationError as exc:
            return "failed", _fail(ticket.id, exc.message,
                                   {"field": exc.field, "expected": exc.expected})
        Activity.log(self.entity, ticket.id, "updated", actor=self.actor,
                     to_status=ticket.status,
                     message=f"归属计划「{plan.name}」" if plan else "解除计划归属")
        return "succeeded", ticket.id

    def _do_delete(self, ticket):
        ticket_id = ticket.id
        lifecycle.delete_ticket_cascade(self.entity, ticket)
        db.session.delete(ticket)
        return "succeeded", ticket_id

    def _handler(self):
        return {
            "move": self._do_move,
            "assign": self._do_assign,
            "unassign": self._do_unassign,
            "priority": self._do_level,
            "severity": self._do_level,
            "plan": self._do_plan,
            "delete": self._do_delete,
        }[self.action]

    # —— 编排 ——

    def run(self, ids: list) -> dict:
        """按 `ids` 顺序逐项执行，最后统一 commit 一次，返回响应体 dict。"""
        found = {row.id: row for row in
                 self.model.query.filter(self.model.id.in_(ids)).all()}
        handler = self._handler()
        buckets = {"succeeded": [], "skipped": [], "failed": []}
        for ticket_id in ids:
            ticket = found.get(ticket_id)
            if ticket is None:
                buckets["failed"].append(_fail(ticket_id, f"{self.entity} not found"))
                continue
            bucket, payload = handler(ticket)
            buckets[bucket].append(payload)
        db.session.commit()
        return {
            "entity": self.entity,
            "action": self.action,
            "requested": len(ids),
            **buckets,
            "counts": {
                "requested": len(ids),
                **{name: len(rows) for name, rows in buckets.items()},
            },
        }


def _build_params(entity: str, action: str, data: dict):
    """把请求级参数校验一次性做完，返回 (params, error_response_or_None)。

    「请求级」= 整批共用且只有一个取值的参数（目标状态、指派目标、目标级别）。
    它们错了就是整单 400/404，不该被稀释成 200 里的 N 条逐项失败——用户改一次输入
    就能全部修好的东西，不值得让他去读一张失败清单。
    """
    _model, level_field, level_choices, _level_label = _SPECS[entity]
    if action == "move":
        status = want_str(data, "status", required=True)
        if not workflow.is_valid_status(entity, status):
            return None, (jsonify({"error": "invalid target status",
                                   "detail": {"allowed": workflow.column_keys(entity)}}), 400)
        return {"status": status}, None
    if action == "assign":
        return _resolve_assignee(data)
    if action in ("priority", "severity"):
        if action != level_field:
            # 例如对 BUG 发 action="priority"：BUG 没有优先级字段，这是调用方写错了。
            return None, (jsonify({
                "error": f"action {action} is not available for {entity}",
                "detail": {"expected": level_field},
            }), 400)
        return {"value": want_str(data, "value", required=True, choices=level_choices)}, None
    if action == "plan":
        # 请求级参数：整批共用一个目标计划。
        # 【version-plan-console §3.8】`plan_id` 键**必须显式存在**：缺键 → 400，
        # 而不是「当作解除归属」。理由有三：① 它复用的 hierarchy.resolve_plan_for_ticket
        # 的契约是「无该键 → 不改」，把缺键解释成「清空」会让本模块与它所复用的唯一
        # 判据打架；② 本模块既有先例是 assign / unassign **拆成两个 action**，破坏性
        # 语义从不做缺省值；③ 一个漏传字段的客户端不该静默清空整批工单的归属。
        # 显式 `"plan_id": null` 仍然是解除归属——那是用户明确表达过的意图。
        if "plan_id" not in data:
            return None, (jsonify({"error": "plan_id is required",
                                   "detail": {"field": "plan_id",
                                              "expected": "an existing plan id, "
                                                          "or null to detach"}}), 400)
        if data.get("plan_id") is None:
            return {"plan": None}, None
        plan = db.session.get(Plan, want_int(data, "plan_id"))
        if plan is None:
            return None, (jsonify({"error": "plan_id is invalid",
                                   "detail": {"field": "plan_id",
                                              "expected": "an existing plan"}}), 400)
        return {"plan": plan}, None
    return {}, None                      # unassign / delete 无请求级参数


def run(entity: str, data: dict, user, actor):
    """批量操作的唯一入口。返回 `(flask_response, status_code)`。

    Args:
        entity: "requirement" | "bug"。
        data: 已经过 `json_body()` 归一的请求体（含 ids / action / 动作参数）。
        user: 当前登录用户（`auth_helpers.current_user()` 的结果）。
        actor: 审计施动者二元组，形如 ("user", 7)。

    Raises:
        ValidationError: ids / 动作参数格式非法（经全局处理器统一 400）。
    """
    action = want_str(data, "action", required=True, choices=ACTIONS)
    ids = parse_ids(data)                # 先校验 action 再校验 ids：两者都错时先报 action
    gate = _ROLE_GATES[action]
    if gate is not None and (user is None or user.role not in gate):
        return forbidden({"required_roles": list(gate),
                          "your_role": getattr(user, "role", None),
                          "action": action})
    params, err = _build_params(entity, action, data)
    if err:
        return err
    return jsonify(_Runner(entity, action, params, user, actor).run(ids)), 200
