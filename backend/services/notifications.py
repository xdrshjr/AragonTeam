"""通知扇出服务（Phase-3 §2.3 支柱 B）。

底层 notify() 写一条 Notification（**不 commit**，随调用方事务提交）；事件级
helper 在各写路径末尾调用，向**相关的人类用户**扇出通知——不给自己发、不给 Agent 发。
去重：一次事件对同一 user_id 只发一条（helper 内用 set 收敛收件人）。

接入点均为在既有事务 commit 前追加，不改既有返回 shape；不侵入 agent_runner.advance_one
本体（保持其契约纯净），notify_advance 由其调用方在外层调用。
"""
import re

from extensions import db
from models.notification import Notification
from models.user import User
from models.comment import Comment

# @提及正则（§2.3.1 notify_mentions）。
_MENTION_RE = re.compile(r"@([A-Za-z0-9_]+)")

# entity → 人类可读名。
_LABELS = {"requirement": "需求", "bug": "BUG"}


def _label(entity: str) -> str:
    return _LABELS.get(entity, entity)


def _short(text, limit: int = 40) -> str:
    """把标题 / 正文截断到安全长度，避免撑破 message VARCHAR(255)。"""
    s = (text or "").strip().replace("\n", " ")
    return s if len(s) <= limit else s[:limit] + "…"


def _clip(message: str, limit: int = 255) -> str:
    return message if len(message) <= limit else message[: limit - 1] + "…"


def notify(user_id, type, *, entity_type=None, entity_id=None, actor=None, message=None):
    """写一条通知（**不 commit**）。

    跳过条件：user_id 为空；或收件人即施动者本人（actor==("user", user_id)，不给自己发）。
    """
    if user_id is None:
        return None
    actor_type, actor_id = (actor if actor else (None, None))
    if actor_type == "user" and actor_id == user_id:
        return None
    n = Notification(
        user_id=user_id,
        type=type,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_type=actor_type,
        actor_id=actor_id,
        message=_clip(message or ""),
    )
    db.session.add(n)
    return n


def _ticket_humans(ticket) -> set:
    """工单相关的人类 user id 集合：reporter + 人类 assignee（Agent 不入集）。"""
    ids = set()
    if getattr(ticket, "reporter_id", None) is not None:
        ids.add(ticket.reporter_id)
    if ticket.assignee_type == "user" and ticket.assignee_id is not None:
        ids.add(ticket.assignee_id)
    return ids


# ————————————————————— 事件级 helper —————————————————————

def notify_assignment(ticket, entity, actor):
    """指派后 → 通知**新的人类 assignee**（Agent 不发；notify 自动跳过自己）。"""
    if ticket.assignee_type != "user" or ticket.assignee_id is None:
        return
    notify(
        ticket.assignee_id, "assigned",
        entity_type=entity, entity_id=ticket.id, actor=actor,
        message=f"指派给你：{_label(entity)}「{_short(ticket.title)}」",
    )


def notify_claim(ticket, entity, agent):
    """自主认领后 → 通知源工单 **reporter**（若人类）；施动者为 agent，reporter 必收。"""
    notify(
        getattr(ticket, "reporter_id", None), "assigned",
        entity_type=entity, entity_id=ticket.id, actor=("agent", agent.id),
        message=f"{agent.name} 认领了你的{_label(entity)}「{_short(ticket.title)}」",
    )


def notify_comment(ticket, entity, comment, actor):
    """评论后 → 通知 reporter + 当前人类 assignee + 历史人类评论人（去重、排除作者本人）。"""
    recipients = _ticket_humans(ticket)
    prior = Comment.query.filter_by(
        entity_type=entity, entity_id=ticket.id, author_type="user"
    ).all()
    for c in prior:
        if c.author_id is not None:
            recipients.add(c.author_id)
    snippet = _short(comment.body, 30)
    for uid in recipients:
        notify(
            uid, "commented",
            entity_type=entity, entity_id=ticket.id, actor=actor,
            message=f"{_label(entity)}「{_short(ticket.title)}」有新评论：{snippet}",
        )


def notify_advance(ticket, entity, actor, from_status, to_status):
    """状态推进后（人类 move 或 Agent 自主推进）→ 通知 reporter + 人类 assignee（排除 actor）。

    施动者为 agent → 类型 `agent_advanced`；为人类 → `status_changed`。
    """
    actor_type = actor[0] if actor else None
    ntype = "agent_advanced" if actor_type == "agent" else "status_changed"
    who = ""
    if actor_type == "agent" and actor[1] is not None:
        from models.agent import Agent

        a = db.session.get(Agent, actor[1])
        who = f"{a.name} " if a else ""
    for uid in _ticket_humans(ticket):
        notify(
            uid, ntype,
            entity_type=entity, entity_id=ticket.id, actor=actor,
            message=f"{who}把{_label(entity)}「{_short(ticket.title)}」推进：{from_status} → {to_status}",
        )


def notify_convert(src_req, new_bug, actor):
    """需求转 BUG 后 → 通知源需求 reporter / 人类 assignee。"""
    for uid in _ticket_humans(src_req):
        notify(
            uid, "converted",
            entity_type="requirement", entity_id=src_req.id, actor=actor,
            message=f"需求「{_short(src_req.title)}」已转为 BUG #{new_bug.id}",
        )


def notify_mentions(comment, actor):
    """解析评论 body 中的 @username，向存在的用户各发一条 mentioned 通知（去重、排除自己）。"""
    names = set(_MENTION_RE.findall(comment.body or ""))
    if not names:
        return
    users = User.query.filter(User.username.in_(names)).all()
    for u in users:
        notify(
            u.id, "mentioned",
            entity_type=comment.entity_type, entity_id=comment.entity_id, actor=actor,
            message=f"你在{_label(comment.entity_type)} #{comment.entity_id} 的评论中被提及",
        )
