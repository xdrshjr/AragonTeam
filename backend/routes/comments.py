"""评论与合并流路由（Phase-2 §2.3 / §4.2 支柱 B）。

- GET  /api/{requirements|bugs}/:id/comments   列评论（分页，X-Total-Count）
- POST /api/{requirements|bugs}/:id/comments    发评论（author = 当前用户）
- GET  /api/{requirements|bugs}/:id/feed        activity + comment 按时间升序合并流

把「合并复杂度」收在后端：前端只渲染 feed.items，无需二次拉取与合并。
"""
from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required

from extensions import db
from models.requirement import Requirement
from models.bug import Bug
from models.activity import Activity
from models.comment import Comment, _resolve_author
from services.auth_helpers import current_user
from services.pagination import paginate, with_total_count
from services.validation import json_body, want_str
from services import notifications

bp = Blueprint("comments", __name__, url_prefix="/api")

# feed 合并的兜底上限（§2.3.2 / §7 feed 性能），防单工单活动 / 评论过多拖慢详情。
FEED_MAX = 500

_MODELS = {"requirement": Requirement, "bug": Bug}


def _get_entity_or_404(entity: str, entity_id: int):
    """取工单对象；不存在返回 (None, error_response)。"""
    model = _MODELS[entity]
    obj = db.session.get(model, entity_id)
    if obj is None:
        return None, (jsonify({"error": f"{entity} not found"}), 404)
    return obj, None


# ————————————————————— 评论 —————————————————————

def _list_comments(entity: str, entity_id: int):
    obj, err = _get_entity_or_404(entity, entity_id)
    if err:
        return err
    q = Comment.query.filter_by(entity_type=entity, entity_id=entity_id)\
        .order_by(Comment.created_at.asc(), Comment.id.asc())
    rows, total = paginate(q)
    resp = jsonify([c.to_dict() for c in rows])
    return with_total_count(resp, total), 200


def _create_comment(entity: str, entity_id: int):
    obj, err = _get_entity_or_404(entity, entity_id)
    if err:
        return err
    # 【§2.2】非对象体 / 非串 body → 400（此前 .get/.strip/@提及正则 500）。
    data = json_body()
    body = want_str(data, "body")
    if not body:
        return jsonify({"error": "comment body is required"}), 400

    user = current_user()
    comment = Comment(
        entity_type=entity, entity_id=entity_id,
        author_type="user" if user else "system",
        author_id=user.id if user else None,
        body=body,
    )
    db.session.add(comment)
    # 【Phase-3 §2.3】扇出：评论通知参与者（排除作者本人 / Agent），并解析 @提及。
    actor = ("user", user.id) if user else ("system", None)
    notifications.notify_comment(obj, entity, comment, actor)
    notifications.notify_mentions(comment, actor, ticket=obj)
    db.session.commit()
    return jsonify(comment.to_dict()), 201


# ————————————————————— 合并 feed —————————————————————

# 同一时间戳下的次序：状态流转（activity）先于工作说明（comment），读感更自然。
_KIND_PRIORITY = {"activity": 0, "comment": 1}


def _feed(entity: str, entity_id: int):
    obj, err = _get_entity_or_404(entity, entity_id)
    if err:
        return err

    acts = Activity.query.filter_by(entity_type=entity, entity_id=entity_id)\
        .order_by(Activity.created_at.asc(), Activity.id.asc()).limit(FEED_MAX).all()
    comments = Comment.query.filter_by(entity_type=entity, entity_id=entity_id)\
        .order_by(Comment.created_at.asc(), Comment.id.asc()).limit(FEED_MAX).all()

    items = []
    for a in acts:
        items.append({
            "kind": "activity",
            "id": a.id,
            "action": a.action,
            "from_status": a.from_status,
            "to_status": a.to_status,
            "actor": _resolve_author(a.actor_type or "system", a.actor_id),
            "message": a.message,
            "created_at": _iso(a.created_at),
        })
    for c in comments:
        item = c.to_dict()
        item["kind"] = "comment"
        items.append(item)

    # 按 created_at 升序合并；同刻按 kind 优先级、再按 id 保持确定顺序。
    items.sort(key=lambda it: (it["created_at"] or "",
                               _KIND_PRIORITY.get(it["kind"], 9),
                               it["id"]))
    return jsonify({"items": items}), 200


def _iso(dt):
    return dt.isoformat() + "Z" if dt else None


# ————————————————————— 路由绑定（requirement / bug 同构）—————————————————————

@bp.get("/requirements/<int:entity_id>/comments")
@jwt_required()
def list_requirement_comments(entity_id):
    return _list_comments("requirement", entity_id)


@bp.post("/requirements/<int:entity_id>/comments")
@jwt_required()
def create_requirement_comment(entity_id):
    return _create_comment("requirement", entity_id)


@bp.get("/requirements/<int:entity_id>/feed")
@jwt_required()
def requirement_feed(entity_id):
    return _feed("requirement", entity_id)


@bp.get("/bugs/<int:entity_id>/comments")
@jwt_required()
def list_bug_comments(entity_id):
    return _list_comments("bug", entity_id)


@bp.post("/bugs/<int:entity_id>/comments")
@jwt_required()
def create_bug_comment(entity_id):
    return _create_comment("bug", entity_id)


@bp.get("/bugs/<int:entity_id>/feed")
@jwt_required()
def bug_feed(entity_id):
    return _feed("bug", entity_id)
