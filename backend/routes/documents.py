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
from sqlalchemy import func, or_

from extensions import db
from models.document import DOCUMENT_KINDS, Document, DocumentVersion, is_text_editable
from models.document_link import DocumentLink
from services.auth_helpers import can_manage_document, current_user, forbidden
from services.documents import counts as document_counts
from services.documents import mime as mimetable
from services.documents import service as documents
from services.documents import storage
from services.documents import templates as document_templates
from services.documents import trash
from services.pagination import paginate, with_total_count
from services.scope import MAX_DB_INT, MIN_DB_INT, want_query_int
from services.search import escape_like
from services.validation import ValidationError, json_body, want_int, want_str
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


def _get_document_or_404(document_id, *, mode: str = "live"):
    """按 id 取文档。

    Args:
        mode: `"live"`（默认，**只**取未删的——全部读写端点走这一档）
            | `"trashed"`（**只**取回收站里的——`?purge=1` 与 restore 走这一档）。

    为什么不做 `"any"` 档：一个「两边都能取到」的入口迟早会被某个新端点默认用上，
    而它恰恰是软删全部风险的来源（幽灵文档）。**宁可两个调用方各写一次 mode，
    也不留一个默认放行的口子。**

    实现注记（评审 V-07）：现网这里是 `db.session.get(Document, id)`，`session.get`
    按主键直取（还会命中 identity map），**加不了 filter**——故本函数是一次结构改动，
    不是「加一个 filter」。
    """
    query = Document.query.filter(Document.id == document_id)
    query = query.filter(trash.not_deleted() if mode == "live" else trash.is_deleted())
    document = query.first()
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


# `sort` 的白名单。非枚举值一律 400（**不静默回退**，与 `want_str(choices=...)` 同款态度）。
_SORTS = ("recent", "title", "size", "links")


def _link_count_subquery():
    """`{document_id: 绑定数}` 的 group-by 子查询，供 `sort=links` / `unlinked=1` join。

    【§8 R-7】必须是**一次** join，不得退化为「先取 50 行再逐行 count」——那正是上一轮
    R8 的坑。子查询本身也过滤软删文档（它是按 document_id 聚合的，不受影响，但保持
    与 counts.link_counts 同一口径便于日后核对）。
    """
    return (db.session.query(DocumentLink.document_id.label("document_id"),
                             func.count(DocumentLink.id).label("total"))
            .group_by(DocumentLink.document_id)
            .subquery())


def _apply_sort(query, sort: str, deleted_view: bool):
    """按 `sort` 追加 join 与 order_by。返回新的 query。

    `recent` 与现网逐字一致（`updated_at DESC, id DESC`），因此默认行为不变。
    回收站视图恒按 `deleted_at DESC` 排——按删除时间看才有意义。
    """
    if deleted_view:
        return query.order_by(Document.deleted_at.desc(), Document.id.desc())
    if sort == "title":
        return query.order_by(Document.title.asc(), Document.id.asc())
    if sort == "size":
        query = query.outerjoin(
            DocumentVersion, DocumentVersion.id == Document.current_version_id)
        # SQLite 把 NULL 视为最小值，故 DESC 天然把「没有版本的文档」排在最后，
        # 无需 NULLS LAST（那需要 SQLite >= 3.30，没有理由为一个排序引入版本依赖）。
        return query.order_by(DocumentVersion.size_bytes.desc(), Document.id.desc())
    if sort == "links":
        counts = _link_count_subquery()
        query = query.outerjoin(counts, counts.c.document_id == Document.id)
        return query.order_by(func.coalesce(counts.c.total, 0).desc(),
                              Document.id.desc())
    return query.order_by(Document.updated_at.desc(), Document.id.desc())


@bp.get("")
@jwt_required()
def list_documents():
    query = Document.query
    keyword = request.args.get("q")
    kind = request.args.get("kind")
    project_id = want_query_int("project_id")
    uploader_id = want_query_int("uploader_id")
    sort = want_str(request.args, "sort", default="recent", choices=_SORTS)
    unlinked = request.args.get("unlinked") == "1"
    deleted_view = request.args.get("deleted") == "1"

    if deleted_view:
        query = query.filter(trash.is_deleted())
        user = current_user()
        if user is None or user.role not in ("admin", "pm"):
            # 【§2.6 / 评审 V-12】非 pm/admin 只能看**自己可管理的**那些。这是一道
            # **权限收紧**，不是用户的检索意图：用户显式传了别人的 uploader_id 时
            # 以自动值为准、**不报错**——把一次越权检索渲染成 400 只会告诉攻击者
            # 「这里有东西」，而静默收紧的结果（看到自己的那些）恰好就是正确答案。
            uploader_id = user.id if user else -1
    else:
        # 【过滤点 2 · §2.4】漏掉这一行，文档库里仍然列着已删文档。
        query = query.filter(trash.not_deleted())

    if keyword:
        # 转义 LIKE 元字符（% _ \），与 search / 两个工单列表一致。
        like = f"%{escape_like(keyword)}%"
        query = query.filter(or_(Document.title.ilike(like, escape="\\"),
                                 Document.description.ilike(like, escape="\\")))
    # 【必须是 `filter(Document.x == ...)`，不能用 `filter_by`】`filter_by` 绑定的是
    # **最后一次 join 进来的实体**，而下面 `unlinked` 与 `_apply_sort` 都会 outerjoin
    # （`document_versions` 或计数子查询）。今天它们恰好写在 join 之前所以是对的，
    # 但那是**语句顺序**在兜底：将来任何一次「顺手把新筛选加在后面」都会静默地去筛错表——
    # 在 `deleted=1` 那条路上，那意味着上传人收紧直接失效。写成显式列引用，顺序就不再重要。
    if kind:
        query = query.filter(Document.kind == kind)
    if project_id is not None:
        query = query.filter(Document.project_id == project_id)
    if uploader_id is not None:
        query = query.filter(Document.uploader_id == uploader_id)
    if unlinked:
        counts = _link_count_subquery()
        query = (query.outerjoin(counts, counts.c.document_id == Document.id)
                 .filter(counts.c.total.is_(None)))
        sort = "recent" if sort == "links" else sort   # links 排序在此已无意义

    query = _apply_sort(query, sort, deleted_view)
    rows, total = paginate(query)
    # 走批量序列化：逐行 to_dict 在 50 行的页面上就是 100 次额外往返。
    resp = jsonify(document_counts.serialize_documents(rows))
    return with_total_count(resp, total), 200


@bp.get("/meta")
@jwt_required()
def documents_meta():
    """只读配置端点（§4.6）：模板清单 + 回收站保留期。

    **前端不得硬编码保留期**（R-11）：前端说「还剩 3 天」而后端配置是 7 天，用户就会
    按错误信息做决定。中文标题同样由后端下发，避免在前端再写一份（与 `stage_label`
    不另建映射同一条原则）。

    路由冲突核验：本蓝图的详情路由是 `/<int:document_id>`（整型转换器），`meta` 是
    字符串段，**不会**被它捕获。
    """
    return jsonify({
        "templates": document_templates.catalog(),
        "trash_retention_days": trash.retention_days(),
        # 预览截断阈值同样由后端下发：前端的「已截断显示前 N」横幅若硬编码 1 MB，
        # 运维把它调成 256 KB 之后那句提示就是一个 4 倍错的数字（R-11 的同一课）。
        "text_preview_max_bytes": int(
            current_app.config["DOC_TEXT_PREVIEW_MAX_BYTES"]),
    }), 200


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
    body["links"] = _links_with_titles(links)
    return jsonify(body), 200


def _links_with_titles(links) -> list:
    """`links[]` 富化 `entity_title`（§2.1 A-4①）。

    「这份文档正被这几张单使用」是用户决定「能不能改这份 PRD」时的第一个问题，而现网
    `DocumentLink.to_dict()` 只有 `entity_type` / `entity_id`，前端只能显示一个数字。

    **标题必须批量取**：`requirement` / `bug` 各**一次**查询，不得逐 link 查一次
    （一份绑了 60 张单的接口契约就是 60 次往返）。工单已被删时回落占位而非 500——
    link 理论上已随工单级联删除，但防御性路径仍需给出一个可渲染的值。
    """
    from models.bug import Bug
    from models.requirement import Requirement

    models = {"requirement": Requirement, "bug": Bug}
    wanted: dict = {}
    for link in links:
        wanted.setdefault(link.entity_type, set()).add(link.entity_id)

    titles: dict = {}
    for entity, ids in wanted.items():
        model = models.get(entity)
        if model is None or not ids:
            continue
        rows = (db.session.query(model.id, model.title)
                .filter(model.id.in_(sorted(ids))).all())
        for row_id, title in rows:
            titles[(entity, row_id)] = title

    payload = []
    for link in links:
        body = link.to_dict()
        body["entity_title"] = titles.get((link.entity_type, link.entity_id))
        payload.append(body)
    return payload


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
    """删除文档。

    **外部契约不变**（仍 204 / 409 / 403 / 404），只是内部由「删行 + reap」改为
    「置位 `deleted_at`」——删除从此是可撤销的（§2.4 D-1）。`?purge=1` 是本轮新增的
    彻底删除，它是全系统唯一不可逆的文档操作，故收口到 admin。
    """
    if request.args.get("purge") == "1":
        return _purge_document(document_id)
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
    trash.soft_delete(document, _actor())
    db.session.commit()
    # **无 reap**：行还在、版本行还在，blob 必须留着——否则恢复出来的是一个空壳。
    return "", 204


def _purge_document(document_id):
    """`?purge=1`：把一份**回收站中**的文档彻底删除。判定顺序不可换（§2.4 D-2）。"""
    # 第 1 步「探两次」是刻意的：把「你删错对象了」（404）与「你得先删一次」（409）
    # 分开，是 §4.4 状态码表的直接要求，而单次查询给不出这个区分。两次都走主键。
    document, _err = _get_document_or_404(document_id, mode="trashed")
    if document is None:
        live, _ = _get_document_or_404(document_id, mode="live")
        if live is not None:
            return jsonify({
                "error": "document is not in trash",
                "detail": {"reason": "not_deleted",
                           "hint": "delete it first, then purge it from the trash"},
            }), 409
        return jsonify({"error": "document not found"}), 404
    user = current_user()
    if user is None or user.role != "admin":
        return forbidden({"reason": "only admin can permanently delete a document"})
    # `trash.purge` 是**自包含**的：内部先 detach_all_links 再删行。回收站里的文档
    # 「仍有绑定」是常态（软删刻意不解绑），把 detach 留在这里，CLI 路径就会在第一份
    # 带绑定的过期文档上撞 document_links 的真外键 → IntegrityError → 500（评审 V-02）。
    orphans = trash.purge(document, _actor())
    db.session.commit()
    # 【§2.2】物理回收恒在 commit **之后**，且只做判定不硬删（宽限窗口交给离线 GC）。
    documents.reap(orphans)
    return "", 204


@bp.post("/<int:document_id>/restore")
@jwt_required()
def restore_document(document_id):
    """把文档移出回收站（§4.3）。

    绑定关系**从未解除过**（软删不动 links），因此恢复后工单抽屉里的位置、`link.stage`
    快照全部原样回来——这正是软删相对「删了再传一遍」的全部价值。
    **例外**：走 `?force=1` 软删的那些，links 已被解除且写了 `doc_detached`，恢复只能
    恢复文档本体，绑定不会自动回来。前端恢复确认框必须如实说明这一点。
    """
    document, err = _get_document_or_404(document_id, mode="trashed")
    if document is None:
        live, _ = _get_document_or_404(document_id, mode="live")
        if live is not None:
            if not can_manage_document(current_user(), live):
                return forbidden({"reason": "cannot restore this document"})
            return jsonify({
                "error": "document is not in trash",
                "detail": {"reason": "not_deleted"},
            }), 409
        return err
    if not can_manage_document(current_user(), document):
        return forbidden({"reason": "cannot restore this document"})
    trash.restore(document, _actor())
    db.session.commit()
    link_count = DocumentLink.query.filter_by(document_id=document.id).count()
    return jsonify(document.to_dict(link_count=link_count)), 200


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
        # 【§2.2 B-3 · 评审 V-06】**回滚分支必须在 `_reject_uneditable` 之前分流并完全
        # 绕过它。** 那道闸的四条判据（文本扩展名 / 不超编辑阈值 / 未被截断 / 严格
        # UTF-8）是为「在线编辑文本」设的：用户改一个字保存，截断即成为新版本的全部
        # 内容——它拦的是**数据损毁**。而回滚**不产生任何新内容**，只是把一个已经存在、
        # 字节完整的历史版本重新指为当前版本；一份 .png / .docx / .pdf 的回滚与「能不能
        # 当文本编辑」毫无关系。写在闸之后，回滚任何二进制文档都会拿到
        # 409 {"reason": "binary"}——而 §4.2 的状态码表里根本没有这一档。
        from_version_id = want_int(data, "from_version_id")
        if from_version_id is not None:
            if isinstance(data.get("content"), str):
                return jsonify({
                    "error": "content and from_version_id are mutually exclusive",
                    "detail": {"reason": "ambiguous_source"},
                }), 400
            return _rollback(document, from_version_id, note)

        blocked = _reject_uneditable(document)      # ← 只管在线编辑那条路
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
    return _revision_body(document, version, fanout, blob.deduped)


def _rollback(document, from_version_id: int, note):
    """把一个历史版本重新指定为当前版本（§2.5 时序 C，判定顺序不可换）。

    内容寻址的免费红利：新版本行与源版本行共享同一个 sha256，**磁盘上不写一个字节**，
    历史一行不删。回滚在这里是「加一行」，不是「退回去」。
    """
    source = documents.find_version(document, from_version_id)
    if source is None:                      # 跨文档的 id 一律视为不存在（现网语义）
        return jsonify({"error": "document version not found"}), 404
    if source.id == document.current_version_id:
        # 回滚到当前版本是一次无意义的写，静默接受只会在版本列表里制造一行噪音。
        return jsonify({
            "error": "this version is already the current one",
            "detail": {"reason": "already_current",
                       "current_version_id": document.current_version_id},
        }), 409
    if not storage.blob_exists(source.sha256):
        # **不允许**建出一行指向空气的版本——用户点一次回滚就会把「当前版本」变成
        # 一个下载即 410 的空壳。与 /download 的 410 对齐。
        return jsonify({
            "error": "the source version's file is missing",
            "detail": {"reason": "blob_missing", "version_id": source.id},
        }), 410

    version = documents.add_version_from_existing(
        document, source_version=source, note=note, uploader=current_user())
    title = document.title
    fanout = documents.fanout_revision(
        document, version, _actor(), action="doc_rolled_back",
        message=f"将文档「{title[:40]}」回滚到 v{source.version_no}"
                f"（新版本 v{version.version_no}）")
    db.session.commit()
    # 响应体形状与 content 分支**完全一致**，前端无需为回滚写第二套解析。
    return _revision_body(document, version, fanout, deduped=True)


def _revision_body(document, version, fanout, deduped: bool):
    return jsonify({
        "document": document.to_dict(link_count=fanout.link_count, version=version),
        "version": version.to_dict(),
        "deduped": deduped,
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
