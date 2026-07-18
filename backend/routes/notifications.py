"""通知蓝图（Phase-3 §2.3.2 / §4.2）。

- GET  /api/notifications?unread=<0|1>&limit=&offset=  当前用户通知（倒序 + X-Total-Count）
- GET  /api/notifications/unread-count                 未读数（供铃铛轮询，轻量）
- POST /api/notifications/:id/read                      单条已读（owner 校验，幂等）
- POST /api/notifications/read-all                      全部已读

收件人恒为当前登录用户；他人通知不可读（403）。
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from extensions import db
from models.notification import Notification
from services.auth_helpers import current_user
from services.pagination import paginate, with_total_count

bp = Blueprint("notifications", __name__, url_prefix="/api/notifications")


@bp.get("")
@jwt_required()
def list_notifications():
    user = current_user()
    if user is None:
        return jsonify({"error": "unauthorized"}), 401
    q = Notification.query.filter_by(user_id=user.id)
    if request.args.get("unread") == "1":
        q = q.filter_by(is_read=False)
    q = q.order_by(Notification.created_at.desc(), Notification.id.desc())
    rows, total = paginate(q)
    resp = jsonify([n.to_dict() for n in rows])
    return with_total_count(resp, total), 200


@bp.get("/unread-count")
@jwt_required()
def unread_count():
    user = current_user()
    if user is None:
        return jsonify({"error": "unauthorized"}), 401
    count = Notification.query.filter_by(user_id=user.id, is_read=False).count()
    return jsonify({"count": count}), 200


@bp.post("/<int:notif_id>/read")
@jwt_required()
def mark_read(notif_id):
    user = current_user()
    if user is None:
        return jsonify({"error": "unauthorized"}), 401
    n = db.session.get(Notification, notif_id)
    if n is None:
        return jsonify({"error": "notification not found"}), 404
    if n.user_id != user.id:
        return jsonify({"error": "forbidden"}), 403
    n.is_read = True  # 幂等：已读再置无副作用。
    db.session.commit()
    return jsonify({"notification": n.to_dict()}), 200


@bp.post("/read-all")
@jwt_required()
def mark_all_read():
    user = current_user()
    if user is None:
        return jsonify({"error": "unauthorized"}), 401
    updated = Notification.query.filter_by(user_id=user.id, is_read=False)\
        .update({"is_read": True}, synchronize_session=False)
    db.session.commit()
    return jsonify({"updated": updated}), 200
