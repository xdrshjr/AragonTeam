"""存量演示数据清理 CLI（data-persistence-and-seed-slimming §2.6）。

用法（在 backend/ 目录下执行，PowerShell / cmd / bash 通用）::

    python tools/purge_demo_data.py                 # 默认 dry-run：只报告，不写库
    python tools/purge_demo_data.py --apply         # 备份后真正执行
    python tools/purge_demo_data.py --apply --json  # 机器可读报告
    python tools/purge_demo_data.py --database-url sqlite:///D:/x/aragon.db

**为什么是离线 CLI 而不是 HTTP 端点**：批量破坏性清理没有幂等语义、没有回滚入口，
一个手滑的 curl 就能清掉演示环境。离线 CLI 天然要求人在服务器上，且能强制 dry-run。

**本工具的第一原则（§2.6.2，唯一一条写错就不可逆的规则）**：
`comments` / `activities` / `notifications` **永不按计数裁剪**。这三张表里绝大多数行
是用户真实产生的审计轨迹与讨论，且没有任何出身标记。**没有出身证明的行，一律推定
为真实数据**——这条推定方向不可反转。它们只删「已登记 ∪ 被级联 ∪ 孤儿」三类。
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

# 【冻结常量】v1 seed（2026-07 之前）写入的行的指纹。存量库里这些行没有 seed_records
# 登记，只能靠内容匹配。本表**只读、只增不改**：改了会让老库里的旧演示数据永远删不掉。
# 新 seed 一律靠 seed_records 识别，禁止再往这里加条目（§7 R-8）。
LEGACY_FINGERPRINT = {
    "user": ("admin", "pm", "alice", "bob"),
    "agent": ("dev-agent", "qa-agent"),
    "project_key": ("ARA",),
    "requirement": (
        "搭建 AragonTeam 项目骨架", "需求看板支持拖拽排序",
        "接入 dev-agent 自动认领需求", "统一全局错误响应契约",
        "BUG 看板与需求看板打通", "导出协作活动时间线报表",
        "修复登录态刷新丢失问题",
    ),
    "bug": (
        "拖拽后偶发卡片位置错乱", "Agent 指派后头像不显示",
        "看板列计数未实时刷新", "登录 token 过期未跳转", "次要文案错别字",
    ),
}

# 「有出身证明」的五类：只有它们适用「每类留一」（§2.6.1 步骤 4 / 评审 P0-1）。
PROVENANCE_CATEGORIES = ("users", "agents", "projects", "requirements", "bugs")

# 只清「登记 ∪ 级联 ∪ 孤儿」的三类软表（§2.6.2）。
SOFT_TABLES = ("comments", "activities", "notifications")

EXIT_OK = 0
EXIT_PRECONDITION = 1
EXIT_SKIPPED = 2


# ————————————————————— 参数与库定位（import app 之前）—————————————————————

def _parse_args(argv=None):
    """解析命令行参数。**此时尚未 import app**（§2.6.0，顺序不可换）。"""
    parser = argparse.ArgumentParser(
        prog="purge_demo_data",
        description="清理存量库里的演示数据，每类只保留一条示例（默认 dry-run）。")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="只报告不写库（默认行为）")
    mode.add_argument("--apply", action="store_true",
                      help="真正执行；执行前自动备份")
    parser.add_argument("--no-backup", action="store_true",
                        help="跳过备份（非 SQLite 库时必须显式给出）")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="报告输出为 JSON")
    parser.add_argument("--database-url", default=None,
                        help="指定库 URI；缺省取 DATABASE_URL 或 config 默认值")
    return parser.parse_args(argv)


def _default_url_from_config() -> str:
    """读 config 默认库 URI。

    **有意只 import config、不 import app**：`config.py` 是纯常量、无副作用，可以
    安全早读；而 `app.py` 有模块级 `app = create_app()`，import 即建库 + 播种。
    """
    from config import Config

    return Config.SQLALCHEMY_DATABASE_URI


def _sqlite_path(url: str):
    """URI → SQLite 文件绝对路径；非文件型 SQLite 或非 SQLite 后端返回 None。"""
    from services.persistence import describe_storage

    described = describe_storage(url)
    if described["backend"] != "sqlite":
        return None
    return described["path"]


def _backup_sqlite(path: str) -> str:
    """用 SQLite 在线备份 API 生成一致性副本，返回备份文件路径。

    **不能用 shutil.copy**：直接复制一个正在写的 SQLite（WAL 下尤甚）会得到撕裂副本
    （§7 R-4）。`Connection.backup()` 对 WAL 与并发写是安全的。

    Args:
        path: 源库绝对路径。

    Returns:
        备份文件路径 `<源库>.bak-YYYYmmddHHMMSS`（与源库同目录）。
    """
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = f"{path}.bak-{stamp}"
    source = sqlite3.connect(path)
    try:
        target = sqlite3.connect(backup_path)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    return backup_path


# ————————————————————— 删除集组装 —————————————————————

def _seeded_ids() -> dict:
    """seed_records 登记表 → `{entity_type: {id, ...}}`。"""
    from models.seed_record import SeedRecord

    seeded = {}
    for record in SeedRecord.query.all():
        seeded.setdefault(record.entity_type, set()).add(record.entity_id)
    return seeded


def _prune_orphan_seed_records() -> int:
    """删除指向已不存在实体的 seed_records 行，返回删除条数（幂等）。

    不给 seed_records 建真外键，正是为了让「用户删掉示例需求」这一合法操作不被挡；
    代价就是要在这里补一次孤儿清理（§7 R-9）。
    """
    from extensions import db
    from models.seed_record import SeedRecord

    models = _entity_models()
    removed = 0
    for record in SeedRecord.query.all():
        model = models.get(record.entity_type)
        if model is None or db.session.get(model, record.entity_id) is None:
            db.session.delete(record)
            removed += 1
    return removed


def _entity_models() -> dict:
    """SeedRecord.entity_type → 模型类。"""
    from models.activity import Activity
    from models.agent import Agent
    from models.bug import Bug
    from models.comment import Comment
    from models.notification import Notification
    from models.project import Project
    from models.requirement import Requirement
    from models.user import User

    return {
        "user": User, "agent": Agent, "project": Project,
        "requirement": Requirement, "bug": Bug, "comment": Comment,
        "activity": Activity, "notification": Notification,
    }


def _candidates(seeded: dict) -> dict:
    """组装五类「有出身证明」的候选行：`seed_records 登记 ∪ 历史指纹匹配`。

    指纹匹配用**精确相等**，不用 LIKE / 前缀——用户完全可能新建一张标题里含「拖拽」
    的真单，模糊匹配会误伤（§5.3）。

    Args:
        seeded: `_seeded_ids()` 的结果。

    Returns:
        `{类别复数名: [行, ...]}`，每个列表按 id 升序。
    """
    from sqlalchemy import or_

    from models.agent import Agent
    from models.bug import Bug
    from models.project import Project
    from models.requirement import Requirement
    from models.user import User

    specs = (
        ("users", User, User.username, LEGACY_FINGERPRINT["user"], "user"),
        ("agents", Agent, Agent.name, LEGACY_FINGERPRINT["agent"], "agent"),
        ("projects", Project, Project.key,
         LEGACY_FINGERPRINT["project_key"], "project"),
        ("requirements", Requirement, Requirement.title,
         LEGACY_FINGERPRINT["requirement"], "requirement"),
        ("bugs", Bug, Bug.title, LEGACY_FINGERPRINT["bug"], "bug"),
    )
    out = {}
    for plural, model, column, fingerprint, singular in specs:
        conditions = [column.in_(fingerprint)]
        registered = sorted(seeded.get(singular, set()))
        if registered:
            conditions.append(model.id.in_(registered))
        out[plural] = model.query.filter(or_(*conditions))\
            .order_by(model.id.asc()).all()
    return out


def _split_keep_delete(rows: list):
    """「每类留一」：按 id 升序保留第 1 条，其余进入删除集。

    只对**候选集**（有出身证明的演示行）生效——用户真实建的行根本不在候选集里，
    因此永远不会被裁剪掉。
    """
    if not rows:
        return None, []
    return rows[0], list(rows[1:])


# ————————————————————— 执行删除 —————————————————————

def _delete_tickets(entity: str, rows: list) -> dict:
    """删除工单及其级联引用，返回被级联删除的软表行数汇总。"""
    from extensions import db
    from services import lifecycle

    totals = {"comments": 0, "notifications": 0, "activities": 0}
    for ticket in rows:
        removed = lifecycle.delete_ticket_cascade(entity, ticket)
        for key in totals:
            totals[key] += removed[key]
        db.session.delete(ticket)
    return totals


def _purge_soft_tables(seeded: dict, cascaded: dict) -> dict:
    """清理三张软表里的「已登记」与「孤儿」行，**绝不按计数裁剪**（§2.6.2）。

    Args:
        seeded: `_seeded_ids()` 的结果。
        cascaded: `_delete_tickets` 汇总的级联删除条数（仅用于报告）。

    Returns:
        `{表名: {"seeded": n, "cascaded": n, "orphan": n, "kept": n}}`。
        `kept` 是清理后仍在库里的行数——即**用户的真实讨论与审计**。
    """
    from extensions import db
    from models.activity import Activity
    from models.comment import Comment
    from models.notification import Notification

    specs = (("comments", Comment, "comment"),
             ("activities", Activity, "activity"),
             ("notifications", Notification, "notification"))
    alive = _alive_ticket_ids()
    report = {}
    for table, model, singular in specs:
        registered = seeded.get(singular, set())
        removed_seeded = 0
        removed_orphan = 0
        for row in model.query.all():
            if row.id in registered:
                db.session.delete(row)
                removed_seeded += 1
            elif _is_orphan(row, alive):
                db.session.delete(row)
                removed_orphan += 1
        db.session.flush()
        report[table] = {
            "seeded": removed_seeded,
            "cascaded": cascaded.get(table, 0),
            "orphan": removed_orphan,
            "kept": model.query.count(),
        }
    return report


def _alive_ticket_ids() -> dict:
    """当前仍存在的工单 id 集合（调用前须 flush，否则看到的是删除前的世界）。"""
    from models.bug import Bug
    from models.requirement import Requirement

    return {
        "requirement": {r.id for r in Requirement.query.all()},
        "bug": {b.id for b in Bug.query.all()},
    }


def _is_orphan(row, alive: dict) -> bool:
    """该行的多态实体引用是否已指向不存在的工单。

    entity_type 为 NULL 的通知（如全局通知）**不是**孤儿，不得误删。
    """
    entity_type = getattr(row, "entity_type", None)
    entity_id = getattr(row, "entity_id", None)
    if entity_type not in alive or entity_id is None:
        return False
    return entity_id not in alive[entity_type]


def _purge_agents(rows: list) -> tuple:
    """删除候选 Agent；名下仍有**未终态**在手工单则跳过并说明理由。

    守卫必须在工单已删、且已 flush 之后求值（§2.6.1 评审 P1-7）：否则 legacy 库里
    名下挂着一张 `fixing` BUG 的 qa-agent 会被永远跳过——而那张 BUG 本身就在删除集里。
    """
    from extensions import db
    from services import lifecycle

    deleted, skipped = [], []
    for agent in rows:
        load = lifecycle.agent_open_workload(agent.id)
        if load["requirements"] or load["bugs"]:
            skipped.append({
                "name": agent.name, "id": agent.id,
                "reason": (f"仍有在手工单（需求 {load['requirements']} / "
                           f"BUG {load['bugs']}）"),
            })
            continue
        deleted.append({"name": agent.name, "id": agent.id})
        db.session.delete(agent)
    db.session.flush()
    return deleted, skipped


def _purge_projects(rows: list) -> tuple:
    """删除候选项目；名下仍有工单则跳过（与既有 DELETE /api/projects 语义一致）。

    实践中 `Project.key` 有 unique 约束、指纹只有一个 "ARA"，候选集恒为 1 条，
    「每类留一」必然保留它、`rows` 恒为空。这里的守卫是防御未来指纹扩张的兜底。
    """
    from extensions import db
    from services import lifecycle

    deleted, skipped = [], []
    for project in rows:
        refs = lifecycle.project_references(project.id)
        if refs["requirements"] or refs["bugs"]:
            skipped.append({
                "name": project.key, "id": project.id,
                "reason": (f"名下仍有工单（需求 {refs['requirements']} / "
                           f"BUG {refs['bugs']}）"),
            })
            continue
        deleted.append({"name": project.key, "id": project.id})
        db.session.delete(project)
    db.session.flush()
    return deleted, skipped


def _user_references(user_id: int) -> int:
    """该用户仍被多少行引用（reporter / owner / 作者 / 施动者 / 收件人）。

    `assignee_id` 是**软引用**（无外键），有意不计入——它与 Agent 的悬空指派同类，
    由报告里的 `dangling assignments` 一行单独告知（§2.6.3）。
    """
    from models.activity import Activity
    from models.bug import Bug
    from models.comment import Comment
    from models.document import Document
    from models.notification import Notification
    from models.project import Project
    from models.requirement import Requirement

    return (
        # 【ticket-document-management §2.8】documents.uploader_id 是**真外键**：
        # 漏计这一项，一个上传过文档的用户会被判定为可删，然后撞上外键错误 → 被兜底
        # 处理器变成 500，正是本模块开篇声明要避免的失败模式。
        Document.query.filter_by(uploader_id=user_id).count()
        + Requirement.query.filter_by(reporter_id=user_id).count()
        + Bug.query.filter_by(reporter_id=user_id).count()
        + Project.query.filter_by(owner_id=user_id).count()
        + Comment.query.filter_by(author_type="user", author_id=user_id).count()
        + Activity.query.filter_by(actor_type="user", actor_id=user_id).count()
        + Notification.query.filter_by(user_id=user_id).count()
        + Notification.query.filter_by(actor_type="user", actor_id=user_id).count()
    )


def _purge_users(rows: list) -> tuple:
    """用户的特殊处理（§2.6.3，本工具最重要的安全阀）。

    `users.id` 被 reporter_id / owner_id 真外键引用且 `PRAGMA foreign_keys=ON`，
    硬删必 IntegrityError；且删干净就等于销毁审计轨迹，与平台核心价值直接冲突。
    故：末任管理员守卫 → 仍被引用则**停用**而非删除 → 都不满足才真删。

    Returns:
        `(deleted, deactivated, skipped)` 三个列表，元素均为可 JSON 序列化的 dict。
    """
    from extensions import db
    from services import lifecycle

    deleted, deactivated, skipped = [], [], []
    for user in rows:
        if lifecycle.would_orphan_admins(user, new_active=False):
            skipped.append({"name": user.username, "id": user.id,
                            "reason": "会让有效管理员归零（末任管理员不变量）"})
            continue
        references = _user_references(user.id)
        if references:
            # 已经停用过的不再重复上报——重复执行 --apply 必须是一次干净的 no-op（§6.3-9）。
            if user.is_active:
                user.is_active = False
                deactivated.append({"name": user.username, "id": user.id,
                                    "reason": f"仍被 {references} 行引用"})
            continue
        deleted.append({"name": user.username, "id": user.id})
        db.session.delete(user)
    db.session.flush()
    return deleted, deactivated, skipped


def _dangling_assignments(principals: dict) -> dict:
    """统计指向「本次被删除的 Agent / 用户」的存活工单数（§2.6.3 / §7 R-14）。

    `assignee_type/assignee_id` 是多态**软引用**（无外键），删掉施动者不会被 DB 挡住，
    UI 会显示「(已删除)」。与既有 `DELETE /api/agents` 行为一致，本轮不改该语义，
    但 purge 是批量的、用户更难察觉，故必须在 `--apply` 之前把它打进报告。
    """
    from models.bug import Bug
    from models.requirement import Requirement

    out = {}
    for plural, model in (("requirements", Requirement), ("bugs", Bug)):
        total = 0
        for assignee_type, ids in principals.items():
            if not ids:
                continue
            total += model.query.filter(
                model.assignee_type == assignee_type,
                model.assignee_id.in_(ids)).count()
        out[plural] = total
    return out


# ————————————————————— 编排 —————————————————————

def _run(dry_run: bool, url: str, backup_path) -> tuple:
    """在应用上下文内完成全部统计与删除，返回 `(report, exit_code)`。

    删除顺序不可换（§2.6.1 步骤 5）：工单 → flush → 软表 → 项目 → Agent → 用户。
    """
    from extensions import db

    seeded = _seeded_ids()
    report = {"database_url": url, "dry_run": dry_run, "backup": backup_path,
              "orphan_seed_records": _prune_orphan_seed_records(),
              "categories": {}, "soft_tables": {}}
    candidates = _candidates(seeded)
    keeps, removals = {}, {}
    for category in PROVENANCE_CATEGORIES:
        keeps[category], removals[category] = _split_keep_delete(candidates[category])

    cascaded = {"comments": 0, "notifications": 0, "activities": 0}
    for entity, category in (("requirement", "requirements"), ("bug", "bugs")):
        counts = _delete_tickets(entity, removals[category])
        for key in cascaded:
            cascaded[key] += counts[key]
    db.session.flush()          # 【评审 P1-7】守卫必须看见「删除后的世界」

    report["soft_tables"] = _purge_soft_tables(seeded, cascaded)
    report["categories"] = _summarise_principals(keeps, removals)
    report["dangling_assignments"] = _dangling_assignments({
        "agent": [row["id"] for row in report["categories"]["agents"]["deleted"]],
        "user": [row["id"] for row in report["categories"]["users"]["deleted"]],
    })
    _prune_orphan_seed_records()   # 本次删除又制造了一批孤儿登记，顺带清掉（幂等）
    report["untouched"] = _untouched_counts()
    skipped = sum(len(c["skipped"]) for c in report["categories"].values())
    report["exit_code"] = EXIT_SKIPPED if skipped else EXIT_OK
    if dry_run:
        db.session.rollback()      # dry-run 绝不写库：整段在同一事务里回滚
    else:
        db.session.commit()
    return report, report["exit_code"]


def _summarise_principals(keeps: dict, removals: dict) -> dict:
    """执行五类主体的删除并汇总为报告结构。

    工单在 `_run` 里已删（必须先于守卫求值），这里只补 projects / agents / users。
    """
    summary = {}
    for category in ("requirements", "bugs"):
        summary[category] = _category_entry(
            keeps[category],
            [{"name": row.title, "id": row.id} for row in removals[category]])
    deleted, skipped = _purge_projects(removals["projects"])
    summary["projects"] = _category_entry(keeps["projects"], deleted, skipped=skipped)
    deleted, skipped = _purge_agents(removals["agents"])
    summary["agents"] = _category_entry(keeps["agents"], deleted, skipped=skipped)
    deleted, deactivated, skipped = _purge_users(removals["users"])
    summary["users"] = _category_entry(keeps["users"], deleted,
                                       deactivated=deactivated, skipped=skipped)
    return summary


def _category_entry(kept, deleted, deactivated=None, skipped=None) -> dict:
    """单个类别的报告条目（形状固定，`--json` 消费方无需写分支）。"""
    return {
        "kept": None if kept is None else {"name": _label(kept), "id": kept.id},
        "deleted": deleted,
        "deactivated": deactivated or [],
        "skipped": skipped or [],
    }


def _label(row) -> str:
    """行的人类可读标识：用户名 / 项目 key / Agent 名 / 工单标题。

    `key` 排在 `name` 之前是有意的：项目两者皆有，而报告里 `ARA` 比
    「AragonTeam Platform」更短也更贴近用户在切换器里看到的标识（§4.2 报告样例）。
    """
    for attr in ("username", "key", "name", "title"):
        value = getattr(row, attr, None)
        if value:
            return value
    return str(getattr(row, "id", "?"))


def _untouched_counts() -> dict:
    """清理后各表剩余行数——操作者据此核对「我自己建的单确实还在」。"""
    from models.activity import Activity
    from models.agent import Agent
    from models.bug import Bug
    from models.comment import Comment
    from models.document import Document, DocumentVersion
    from models.document_link import DocumentLink
    from models.notification import Notification
    from models.project import Project
    from models.requirement import Requirement
    from models.user import User

    # 文档三表**从不被本工具清理**（seed 不写文档行，故它们全部是用户真实数据）；
    # 列在这里是为了让操作者能核对「我传的文件确实还在」。
    models = (("users", User), ("agents", Agent), ("projects", Project),
              ("requirements", Requirement), ("bugs", Bug),
              ("comments", Comment), ("activities", Activity),
              ("notifications", Notification),
              ("documents", Document), ("document_versions", DocumentVersion),
              ("document_links", DocumentLink))
    counts = {name: model.query.count() for name, model in models}
    # 【document-lifecycle-depth §2.4 D-3】回收站里的那部分单列一行，与上面的文档三表
    # 并列。本工具**不**清理它——那是 tools/purge_trash.py 的职责，两个工具各自单一职责。
    from services.documents import trash

    counts["documents_in_trash"] = Document.query.filter(trash.is_deleted()).count()
    return counts


# ————————————————————— 报告渲染 —————————————————————

def _render(report: dict, as_json: bool) -> str:
    if as_json:
        return json.dumps(report, ensure_ascii=False, indent=2)
    return _render_text(report)


def _render_text(report: dict) -> str:
    prefix = "[DRY-RUN] " if report["dry_run"] else ""
    lines = [f"{prefix}AragonTeam demo-data purge — {report['database_url']}"]
    for category in PROVENANCE_CATEGORIES:
        lines.append(_render_category(category, report["categories"][category]))
    lines.append("  ——— 以下三类不做计数裁剪，只清「登记的 / 被级联的 / 孤儿」———")
    for table in SOFT_TABLES:
        stat = report["soft_tables"][table]
        lines.append(
            f"  {table:<14} seeded {stat['seeded']}  cascaded {stat['cascaded']}"
            f"  orphan {stat['orphan']}     kept(真实) {stat['kept']}")
    untouched = report["untouched"]
    lines.append("清理后剩余（含你自己建的全部真实数据）：" + ", ".join(
        f"{name} {count}" for name, count in untouched.items()))
    dangling = report["dangling_assignments"]
    lines.append("dangling assignments（指向被删 Agent / 用户的存活工单）："
                 f"requirements {dangling['requirements']}, bugs {dangling['bugs']}")
    if report["dry_run"]:
        lines.append("提示：加 --apply 执行；执行前会自动备份到 aragon.db.bak-<时间戳>")
    elif report["backup"]:
        lines.append(f"备份：{report['backup']}")
    return "\n".join(lines)


def _render_category(category: str, entry: dict) -> str:
    kept = entry["kept"]
    kept_text = f"keep {kept['name']}({kept['id']})" if kept else "keep -"
    line = (f"  {category:<14} {kept_text:<28} delete {len(entry['deleted'])}"
            f"    skip {len(entry['skipped'])}")
    if entry["deactivated"]:
        names = "/".join(row["name"] for row in entry["deactivated"])
        line += f"    deactivate {len(entry['deactivated'])} ({names}, 仍被引用)"
    for row in entry["skipped"]:
        line += f"\n      skip {row['name']}: {row['reason']}"
    return line


# ————————————————————— 入口 —————————————————————

def main(argv=None) -> int:
    """CLI 入口。**启动序列顺序不可换**，理由见 §2.6.0 / §7 R-13。

    `backend/app.py` 有模块级 `app = create_app()`——只要 import 到它，Python 就会
    立刻对「默认 DATABASE_URL 指向的库」执行 create_all + seed。因此必须：
    先解析参数 → 定位并备份目标库 → 把三个开关写进环境变量 → **此时才** import app。
    把 `from app import create_app` 提到文件顶部，会让 dry-run 也写库，并顺手
    创建 / 播种非目标库。
    """
    args = _parse_args(argv)
    url = (args.database_url or os.environ.get("DATABASE_URL")
           or _default_url_from_config())
    path = _sqlite_path(url)
    error = _precondition_error(url, path, args)
    if error:
        print(error, file=sys.stderr)
        return EXIT_PRECONDITION

    backup_path = None
    if args.apply and not args.no_backup and path:
        backup_path = _backup_sqlite(path)

    os.environ["DATABASE_URL"] = url                       # 保护模块级 create_app()
    os.environ["SEED_ON_STARTUP"] = "false"                # 清理工具绝不顺手播种
    os.environ["RELEASE_STALE_LOCKS_ON_STARTUP"] = "false"  # 清理不夹带运维副作用
    from app import create_app                            # ← 必须在这之后 import
    from config import Config

    purge_config = type("PurgeConfig", (Config,), {
        "SQLALCHEMY_DATABASE_URI": url,
        "SEED_ON_STARTUP": False,
        "RELEASE_STALE_LOCKS_ON_STARTUP": False,
    })
    flask_app = create_app(purge_config)
    try:
        with flask_app.app_context():
            report, code = _run(not args.apply, url, backup_path)
            print(_render(report, args.as_json))
            return code
    finally:
        _release_engine(flask_app)


def _precondition_error(url: str, path, args):
    """前置校验，返回错误文案；通过则返回 None（退出码 1 的全部理由）。"""
    if path is None and not args.no_backup:
        return (f"目标库不是文件型 SQLite（{url}），无法自动备份。"
                "确认已自行备份后请显式加 --no-backup。")
    if path is not None and not os.path.exists(path):
        # 几乎总是路径写错了；替他建一个空库只会掩盖问题（§2.6.0）。
        return f"库文件不存在：{path}"
    return None


def _release_engine(flask_app) -> None:
    """释放连接池。Windows 上句柄不放会让调用方（含用例的 tmp_path）删不掉库文件。"""
    from extensions import db

    with flask_app.app_context():
        db.session.remove()
        db.engine.dispose()


if __name__ == "__main__":
    # 允许 `python tools/purge_demo_data.py`：把 backend/ 放进 sys.path。
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.exit(main())
