"""工单文档路由（ticket-document-management §4.2）。

`/api/{requirements,bugs}/:id/documents` 与 `/document-checklist`。两个实体同构，
故收敛在**同一个蓝图**里由 `<entity>` 段分流——两份几乎一样的路由是本仓库反复消灭的
那类重复（对照 `routes/comments.py` 的同款做法）。

本轮的主题在这里落地：文档不是详情页角落里的一个附件列表，而是①在**每一个状态**上都能
被添加、②被添加时**记录当时所处的环节**、③每一次动作都写进协作时间线。
"""
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from extensions import db
from models.bug import Bug
from models.document import DOCUMENT_KINDS, Document
from models.requirement import Requirement
from services import doc_policy
from services.auth_helpers import can_manage_ticket, current_user, forbidden
from services.documents import service as documents
from services.pagination import MAX_LIMIT, paginate, with_total_count
from services.validation import json_body, want_int, want_str
from routes.documents import form_int
from routes.requirements import _actor

bp = Blueprint("ticket_documents", __name__, url_prefix="/api")

# URL 段 → (实体名, 模型)。新增实体只需在这里加一行。
_ENTITIES = {
    "requirements": ("requirement", Requirement),
    "bugs": ("bug", Bug),
}


def _resolve(entity_segment: str, ticket_id: int):
    """URL 段 + id → (entity, ticket, error_response)。未知段与不存在的单一律 404。"""
    mapped = _ENTITIES.get(entity_segment)
    if mapped is None:
        return None, None, (jsonify({"error": "not found"}), 404)
    entity, model = mapped
    ticket = db.session.get(model, ticket_id)
    if ticket is None:
        return entity, None, (jsonify({"error": f"{entity} not found"}), 404)
    return entity, ticket, None


@bp.get("/<any(requirements, bugs):entity_segment>/<int:ticket_id>/documents")
@jwt_required()
def list_ticket_documents(entity_segment, ticket_id):
    """该工单绑定的全部文档（最新绑定在前）。

    【评审 R15】走既有 `paginate(q, default_limit=MAX_LIMIT)`（与活动时间线同款）：
    上一轮的主题恰是「数据一多翻得到」，新增一个无分页端点是逆行。`paginate` 已自带
    limit 钳位与 offset 负值 400，不必自己写校验。
    """
    entity, ticket, err = _resolve(entity_segment, ticket_id)
    if err:
        return err
    query = documents.ticket_documents_query(entity, ticket.id)
    rows, total = paginate(query, default_limit=MAX_LIMIT)
    payload = []
    for document, link in rows:
        body = document.to_dict()
        body["link"] = link.to_dict()
        payload.append(body)
    return with_total_count(jsonify(payload), total), 200


@bp.post("/<any(requirements, bugs):entity_segment>/<int:ticket_id>/documents")
@jwt_required()
def attach_ticket_document(entity_segment, ticket_id):
    """上传并绑定（multipart），或绑定已有文档（`json{document_id, label}`）。"""
    entity, ticket, err = _resolve(entity_segment, ticket_id)
    if err:
        return err
    if not can_manage_ticket(current_user(), ticket):
        return forbidden({"reason": f"cannot attach documents to this {entity}"})

    uploaded = request.files.get("file")
    if uploaded is None:
        return _bind_existing(entity, ticket)
    return _upload_and_bind(entity, ticket, uploaded)


def _bind_existing(entity, ticket):
    """JSON 分支：把文档库里已有的一份文档绑到本单。"""
    data = json_body()
    document_id = want_int(data, "document_id", required=True)
    label = want_str(data, "label", max_len=64) or None
    # 【闸 0 · 评审 R3】不存在的 document_id 必须 404，绝不靠外键异常兜底（那是 500）。
    document = db.session.get(Document, document_id)
    if document is None:
        return jsonify({"error": "document not found"}), 404
    if documents.find_link(document.id, entity, ticket.id) is not None:
        return jsonify({
            "error": "document is already linked to this ticket",
            "detail": {"document_id": document.id, "entity_id": ticket.id},
        }), 409
    link = documents.bind_document(document, entity=entity, ticket=ticket,
                                   label=label, actor=_actor(), uploaded=False)
    db.session.commit()
    return jsonify({"document": document.to_dict(), "link": link.to_dict()}), 201


def _upload_and_bind(entity, ticket, uploaded):
    """multipart 分支：一次请求完成「上传到文档库 + 绑定到本单」。"""
    form = request.form
    title = want_str(form, "title", max_len=200) or None
    kind = want_str(form, "kind", default="other", choices=DOCUMENT_KINDS)
    description = want_str(form, "description", strip=False) or None
    label = want_str(form, "label", max_len=64) or None
    # 文档随工单落到同一个项目（工单未归属时同为 None），无需用户再选一次。
    project_id = form_int(form, "project_id")
    if project_id is None:
        project_id = ticket.project_id

    document, version, blob = documents.create_document(
        file_storage=uploaded, title=title, kind=kind, description=description,
        project_id=project_id, uploader=current_user(),
    )
    link = documents.bind_document(document, entity=entity, ticket=ticket,
                                   label=label, actor=_actor(), uploaded=True)
    db.session.commit()
    body = document.to_dict(link_count=1, version=version)
    body["deduped"] = blob.deduped
    return jsonify({"document": body, "link": link.to_dict()}), 201


@bp.delete("/<any(requirements, bugs):entity_segment>"
           "/<int:ticket_id>/documents/<int:document_id>")
@jwt_required()
def detach_ticket_document(entity_segment, ticket_id, document_id):
    """解除绑定。**幂等**：未绑定时同样返回 204，不写审计、不发通知。

    文档本体绝不删除——它可能绑在别的单上；即使没有，它也是用户真实上传的数据。
    """
    entity, ticket, err = _resolve(entity_segment, ticket_id)
    if err:
        return err
    if not can_manage_ticket(current_user(), ticket):
        return forbidden({"reason": f"cannot detach documents from this {entity}"})
    document = db.session.get(Document, document_id)
    if document is None:
        return "", 204                       # 幂等：目标已不存在即视作已解绑
    if documents.unbind_document(document, entity=entity, ticket=ticket, actor=_actor()):
        db.session.commit()
    return "", 204


@bp.get("/<any(requirements, bugs):entity_segment>/<int:ticket_id>/document-checklist")
@jwt_required()
def ticket_document_checklist(entity_segment, ticket_id):
    """本阶段的文档清单（建议性；`enforced` 如实回传门禁开关的真实值）。"""
    entity, ticket, err = _resolve(entity_segment, ticket_id)
    if err:
        return err
    return jsonify(doc_policy.checklist(entity, ticket)), 200
