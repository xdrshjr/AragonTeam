"""文档库路由（ticket-document-management §4.1）——CRUD / 版本 / 下载 / 正文。

统一契约：全部 `@jwt_required()`；错误体恒为 `{error, detail?}`；列表端点响应体为
**裸数组**，总数走 `X-Total-Count`（既有契约，不为文档破例）。

读权限对所有已认证用户开放，是与既有 `GET /api/requirements/:id` **对齐**的结果：
工单正文本就人人可读，如果文档比工单更严，用户会立刻发现「我看得到这张单，却看不到
它的附件」——那是更糟的体验不一致。要收紧就该连工单一起收紧，那是另一轮的题目。
"""
from urllib.parse import quote

from flask import Blueprint, current_app, jsonify, make_response, request
from flask_jwt_extended import jwt_required
from sqlalchemy import or_

from extensions import db
from models.document import DOCUMENT_KINDS, Document, is_text_editable
from models.document_link import DocumentLink
from services.auth_helpers import can_manage_document, current_user, forbidden
from services.documents import counts as document_counts
from services.documents import mime as mimetable
from services.documents import service as documents
from services.documents import storage
from services.pagination import paginate, with_total_count
from services.scope import MAX_DB_INT, MIN_DB_INT, want_query_int
from services.search import escape_like
from services.validation import ValidationError, json_body, want_str
from routes.requirements import _actor, _validate_project, check_concurrency

bp = Blueprint("documents", __name__, url_prefix="/api/documents")


# ————————————————————— 公共辅助 —————————————————————

def form_int(form, field: str):
    """从 **multipart 表单**取一个整数字段；非法 / 超界一律 400（绝不 500）。

    既有的三条整型边界（`validation.want_int` 管 JSON 体、`scope.want_query_int` 管
    查询串、`BoundedIntConverter` 管 URL 路径）都不覆盖表单字段——multipart 是本轮
    引入的第四条输入路径，故在这里补上同一套判据（含 64 位硬界）。
    """
    raw = (form.get(field) or "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be an integer", field=field,
                              expected="integer")
    if value < MIN_DB_INT or value > MAX_DB_INT:
        raise ValidationError(f"{field} is out of range", field=field,
                              expected="integer within 64-bit range")
    return value


def _get_document_or_404(document_id):
    document = db.session.get(Document, document_id)
    if document is None:
        return None, (jsonify({"error": "document not found"}), 404)
    return document, None


def _wanted_version(document):
    """解析 `?version_id=`（闸 0）：不属于本文档或不存在一律 404。"""
    version = documents.find_version(document, want_query_int("version_id"))
    if version is None:
        return None, (jsonify({"error": "document version not found"}), 404)
    return version, None


def _content_disposition(version) -> str:
    """RFC 5987 百分号编码的文件名头。

    MIME ∈ `INLINE_SAFE_MIMES` 时为 `inline`，**其余一律 `attachment`**（§4.1）。
    中文名以 `filename*=UTF-8''…` 给出才不会被截断成乱码。
    """
    kind = "inline" if mimetable.is_inline_safe(version.mime_type) else "attachment"
    encoded = quote(version.original_filename or "download", safe="")
    return f"{kind}; filename*=UTF-8''{encoded}"


# ————————————————————— CRUD —————————————————————

@bp.post("")
@jwt_required()
def create_document():
    """上传一份新文档到文档库（multipart）。"""
    form = request.form
    # 【闸 0 · 评审 R3】project_id 是**真外键**且 PRAGMA foreign_keys=ON 真实生效；
    # 少了这一闸，不存在的 id 会触发 IntegrityError → 兜底处理器渲染成 500，
    # 直接违反 services/lifecycle.py 的既定契约与「坏输入零 500」硬门槛。
    project_id = form_int(form, "project_id")
    perr = _validate_project(project_id)
    if perr:
        return perr

    title = want_str(form, "title", max_len=200) or None
    kind = want_str(form, "kind", default="other", choices=DOCUMENT_KINDS)
    description = want_str(form, "description", strip=False) or None

    document, version, blob = documents.create_document(
        file_storage=request.files.get("file"),
        title=title, kind=kind, description=description,
        project_id=project_id, uploader=current_user(),
    )
    db.session.commit()
    body = document.to_dict(link_count=0, version=version)
    body["deduped"] = blob.deduped
    return jsonify(body), 201


@bp.get("")
@jwt_required()
def list_documents():
    query = Document.query
    keyword = request.args.get("q")
    kind = request.args.get("kind")
    project_id = want_query_int("project_id")
    uploader_id = want_query_int("uploader_id")
    if keyword:
        # 转义 LIKE 元字符（% _ \），与 search / 两个工单列表一致。
        like = f"%{escape_like(keyword)}%"
        query = query.filter(or_(Document.title.ilike(like, escape="\\"),
                                 Document.description.ilike(like, escape="\\")))
    if kind:
        query = query.filter_by(kind=kind)
    if project_id is not None:
        query = query.filter_by(project_id=project_id)
    if uploader_id is not None:
        query = query.filter_by(uploader_id=uploader_id)
    query = query.order_by(Document.updated_at.desc(), Document.id.desc())
    rows, total = paginate(query)
    # 走批量序列化：逐行 to_dict 在 50 行的页面上就是 100 次额外往返。
    resp = jsonify(document_counts.serialize_documents(rows))
    return with_total_count(resp, total), 200


@bp.get("/<int:document_id>")
@jwt_required()
def get_document(document_id):
    document, err = _get_document_or_404(document_id)
    if err:
        return err
    links = (DocumentLink.query.filter_by(document_id=document.id)
             .order_by(DocumentLink.id.asc()).all())
    body = document.to_dict(link_count=len(links))
    body["versions"] = [v.to_dict() for v in documents.versions_of(document)]
    body["links"] = [link.to_dict() for link in links]
    return jsonify(body), 200


@bp.patch("/<int:document_id>")
@jwt_required()
def patch_document(document_id):
    document, err = _get_document_or_404(document_id)
    if err:
        return err
    if not can_manage_document(current_user(), document):
        return forbidden({"reason": "cannot edit this document"})
    data = json_body()
    # 乐观并发守卫直接复用工单那一份（它只依赖 obj.updated_at，与模型无关）。
    conflict = check_concurrency(document, data)
    if conflict:
        return conflict
    if "title" in data:
        document.title = want_str(data, "title", required=True, max_len=200)
    if "kind" in data:
        document.kind = want_str(data, "kind", required=True, choices=DOCUMENT_KINDS)
    if "description" in data:
        document.description = want_str(data, "description", strip=False) or None
    db.session.commit()
    return jsonify(document.to_dict()), 200


@bp.delete("/<int:document_id>")
@jwt_required()
def delete_document(document_id):
    document, err = _get_document_or_404(document_id)
    if err:
        return err
    user = current_user()
    if not can_manage_document(user, document):
        return forbidden({"reason": "cannot delete this document"})
    force = request.args.get("force") == "1"
    link_count = DocumentLink.query.filter_by(document_id=document.id).count()
    if link_count and not force:
        return jsonify({
            "error": "document is still linked",
            "detail": {"links": link_count,
                       "hint": "unbind it from the tickets first"},
        }), 409
    if link_count:
        if user is None or user.role not in ("admin", "pm"):
            return forbidden({"reason": "only pm/admin can force-delete a linked document"})
        documents.detach_all_links(document, _actor())
    orphans = documents.delete_document(document)
    db.session.commit()
    # 【§2.2】物理回收恒在 commit **之后**，且只做判定不硬删（宽限窗口交给离线 GC）。
    documents.reap(orphans)
    return "", 204


# ————————————————————— 版本 —————————————————————

@bp.post("/<int:document_id>/versions")
@jwt_required()
def create_version(document_id):
    """产出下一个版本。

    同一端点吃两种 `Content-Type` 是刻意的（§2.6）：`multipart/form-data` 传新文件、
    `application/json` 传新正文，两者产出的东西**完全相同**（一个新版本行 + 一个 blob），
    拆成两个端点会得到两份几乎一样的编排代码，正是本仓库反复消灭的那类重复。
    """
    document, err = _get_document_or_404(document_id)
    if err:
        return err
    if not can_manage_document(current_user(), document):
        return forbidden({"reason": "cannot revise this document"})

    uploaded = request.files.get("file")
    is_text_branch = uploaded is None
    # 【评审 R5】两个分支的并发语义**完全一致**：multipart 分支同样接受该字段。
    if is_text_branch:
        data = json_body()
        note = want_str(data, "note", max_len=255) or None
        from services.validation import want_int

        expected = want_int(data, "expected_version_id")
    else:
        note = want_str(request.form, "note", max_len=255) or None
        expected = form_int(request.form, "expected_version_id")
    if expected is not None and expected != document.current_version_id:
        return jsonify({
            "error": "document was revised by someone else",
            "detail": {"current_version_id": document.current_version_id},
        }), 409

    if is_text_branch:
        blocked = _reject_uneditable(document)
        if blocked:
            return blocked
        if not isinstance(data.get("content"), str):
            raise ValidationError("content is required", field="content",
                                  expected="string")
        version, blob = documents.add_version_from_text(
            document, content=data["content"], note=note, uploader=current_user())
    else:
        version, blob = documents.add_version_from_file(
            document, file_storage=uploaded, note=note, uploader=current_user())

    fanout = documents.fanout_revision(document, version, _actor())
    db.session.commit()
    return jsonify({
        "document": document.to_dict(link_count=fanout.link_count, version=version),
        "version": version.to_dict(),
        "deduped": blob.deduped,
        "fanout_written": fanout.written,
        "fanout_truncated": fanout.truncated,
        "link_count": fanout.link_count,
    }), 201


def _reject_uneditable(document):
    """在线编辑的**后端独立复核**（§2.6 / 评审 R5）。前端隐藏按钮只是收敛，不是防线。

    四条判据缺一不可：文本扩展名 / 不超编辑阈值 / 未被截断 / 严格 UTF-8。少任何一条，
    用户「编辑一下」就会永久毁掉文件内容——截断即成为新版本的全部内容，或者每个不可
    解码字节被写成 U+FFFD。
    """
    version = document.current_version()
    if version is None:
        return _uneditable("binary")
    if mimetable.extension_of(version.original_filename) not in mimetable.TEXT_EXTENSIONS:
        return _uneditable("binary")
    if (version.size_bytes or 0) > int(current_app.config["DOC_TEXT_EDIT_MAX_BYTES"]):
        return _uneditable("too_large")
    read = storage.read_text(version.sha256,
                             int(current_app.config["DOC_TEXT_PREVIEW_MAX_BYTES"]))
    if read.truncated:
        return _uneditable("truncated")
    if not read.encoding_confident:
        return _uneditable("encoding")
    return None


def _uneditable(reason: str):
    return jsonify({"error": "this document is not editable as text",
                    "detail": {"reason": reason}}), 409


# ————————————————————— 下载 / 正文 —————————————————————

@bp.get("/<int:document_id>/download")
@jwt_required()
def download_document(document_id):
    """原文件下载。三条响应头缺一不可（§4.1）。

    注意：②`Content-Disposition` 与 ③`nosniff` 只对**直接导航到本 URL** 的场景有效，
    而本端点需要 `Authorization` 头，浏览器直接导航根本取不到内容——因此它们在实际
    用户路径上近乎摆设。预览路径上真正生效的是扩展名白名单（闸 3）与前端的
    `objectURL` 硬规则（§2.6 / 评审 R6），实施与评审时不要把余量记多了。
    """
    document, err = _get_document_or_404(document_id)
    if err:
        return err
    version, verr = _wanted_version(document)
    if verr:
        return verr
    # blob 缺失 → BlobMissing → 全局处理器 410 Gone（与 /content 对齐，§8 R-9）。
    with storage.open_blob(version.sha256) as handle:
        payload = handle.read()
    response = make_response(payload)
    response.headers["Content-Type"] = version.mime_type
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Disposition"] = _content_disposition(version)
    response.headers["Content-Length"] = str(len(payload))
    return response


@bp.get("/<int:document_id>/content")
@jwt_required()
def document_content(document_id):
    """文本正文（预览与在线编辑的数据源）。非文本类型返回 **415**，不是 409（评审 R16）。

    409 在本仓库是「系统状态冲突」的专用码，且前端以「有无 `allowed`」分流 409；
    「这个文件根本不是文本」是请求与资源类型不匹配，混用会污染既有分流逻辑。
    """
    document, err = _get_document_or_404(document_id)
    if err:
        return err
    version, verr = _wanted_version(document)
    if verr:
        return verr
    if mimetable.extension_of(version.original_filename) not in mimetable.TEXT_EXTENSIONS:
        return jsonify({
            "error": "this document is not previewable as text",
            "detail": {"mime_type": version.mime_type, "hint": "download it instead"},
        }), 415
    read = storage.read_text(version.sha256,
                             int(current_app.config["DOC_TEXT_PREVIEW_MAX_BYTES"]))
    # 【评审 R5】四条判据缺一不可，且 `truncated == true` ⇒ `editable == false`。
    editable = (is_text_editable(version) and not read.truncated
                and read.encoding_confident)
    return jsonify({
        "content": read.content,
        "document_id": document.id,
        "version_id": version.id,
        "version_no": version.version_no,
        "mime_type": version.mime_type,
        "truncated": read.truncated,
        "encoding_confident": read.encoding_confident,
        "editable": editable,
    }), 200
