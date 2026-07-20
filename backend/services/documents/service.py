"""文档编排服务（ticket-document-management §2.3 / §2.5 / §2.8）。

职责：上传校验（五道闸）、建文档、加版本、绑定 / 解绑、删除与孤儿摘要判定。
**不 commit**——事务边界由路由层掌握（与 `services/lifecycle.py` 同一约定）。

一条硬约束贯穿全模块：落盘（慢，无锁）在 `db.session` 的任何写入**之前**完成，
事务内只做元数据写入。这与 `agent_prompts` 把 LLM 调用挪出写锁窗口是同一手法（§8 R-7）。
"""
import io
import logging
import os
from typing import BinaryIO, NamedTuple, Optional

from flask import current_app
from sqlalchemy import func
from werkzeug.utils import secure_filename

from extensions import db, utcnow
from models.activity import Activity
from models.document import DOCUMENT_KIND_LABELS, Document, DocumentVersion
from models.document_link import DocumentLink
from services import notifications
from services.documents import mime as mimetable
from services.documents import storage
from services.validation import ValidationError

log = logging.getLogger("aragon.documents.service")

# 工单实体的中文名（与 services/notifications.py 的 _LABELS 同源语义）。
_ENTITY_LABELS = {"requirement": "需求", "bug": "BUG"}


class UploadCandidate(NamedTuple):
    """`_validate_upload` 的产物：一个**游标在 0** 的流 + 已推导好的展示元数据。"""

    stream: BinaryIO
    original_filename: str
    extension: str
    mime_type: str


class FanoutResult(NamedTuple):
    """`doc_revised` 扇出的如实汇报（§2.5 / 评审 R11）。"""

    written: int
    link_count: int
    truncated: bool


# ————————————————————— 闸 1~4：上传边界 —————————————————————

def _validate_upload(file_storage) -> UploadCandidate:
    """上传边界的四道闸，任一不过即 `ValidationError`（→ 全局 400，绝不 500）。

    （闸 0「引用前置校验」是路由层的职责——它要复用 `routes/requirements._validate_project`
    并直接渲染 400/404 响应体，见 §2.3。）

    **出口不变量（§2.3 · 评审 R1 / P0）：函数返回时 `file_storage.stream` 的游标恒为 0。**
    闸 4 会读走开头 12 字节，因此复位写在 `finally` 里，异常路径同样成立。这条不变量与
    `storage.digest_and_persist` 的入口断言互为对照——二者缺一，本轮就会以「测试全绿 +
    每个文件都损坏」的形式上线：落盘内容变成原文件 `[12:]`，而摘要基于残缺内容计算，
    于是去重、完整性校验、下载**全部自洽地正确**。

    Raises:
        ValidationError: 缺文件 / 扩展名不在白名单 / 魔数与扩展名冲突。
    """
    # —— 闸 1 · 存在性 ——
    filename = (getattr(file_storage, "filename", None) or "").strip()
    if file_storage is None or not filename:
        raise ValidationError("file is required", field="file",
                              expected="a non-empty file part named 'file'")

    # —— 闸 2 · 文件名清洗 ——
    # 清洗结果**只作为展示兜底**：落盘路径由摘要推导，与文件名结构性无关，故这里
    # 没有任何安全职责。原始文件名（含中文）原样保留，仅截断到列宽 255。
    # 扩展名必须取自**原始**文件名——`secure_filename("需求说明.md")` 会把非 ASCII
    # 整段剥掉、连同那个点，扩展名就没了。
    original_filename = os.path.basename(filename)[:255] or \
        (secure_filename(filename) or "upload")

    # —— 闸 3 · 扩展名白名单 ——
    extension = mimetable.extension_of(original_filename)
    allowed = tuple(current_app.config.get("DOC_ALLOWED_EXTENSIONS", ()))
    if extension not in allowed:
        raise ValidationError(
            "file extension is not allowed", field="file",
            expected=f"one of {sorted(allowed)}")
    mime_type = mimetable.mime_for(extension)

    # —— 闸 4 · 魔数嗅探 ——
    stream = file_storage.stream
    try:
        head = stream.read(mimetable.SNIFF_BYTES)
    finally:
        # 【出口不变量】读完立即复位，异常路径同样成立。
        stream.seek(0)
    if not mimetable.signature_matches(extension, head):
        raise ValidationError(
            "file content does not match its extension", field="file",
            expected=f"a real .{extension} file")

    return UploadCandidate(stream=stream, original_filename=original_filename,
                           extension=extension, mime_type=mime_type)


def allowed_extensions() -> list:
    """白名单的有序副本，供 400 响应体的 `detail.allowed` 直接回传给前端。"""
    return sorted(current_app.config.get("DOC_ALLOWED_EXTENSIONS", ()))


# ————————————————————— 文档与版本 —————————————————————

def create_document(*, file_storage, title, kind, description, project_id, uploader):
    """校验 → 落盘 → 建 Document + v1（**不 commit**）。

    Returns:
        `(document, version, blob_info)`；`blob_info.deduped` 供前端如实提示
        「该文件已在库中，已直接绑定」，而不是假装上传了一份。
    """
    candidate = _validate_upload(file_storage)
    blob = storage.digest_and_persist(candidate.stream)

    document = Document(
        title=title or candidate.original_filename,
        kind=kind,
        description=description,
        project_id=project_id,
        uploader_id=uploader.id if uploader else None,
    )
    db.session.add(document)
    db.session.flush()                      # 拿 document.id
    version = _append_version(document, candidate, blob, note=None, uploader=uploader)
    return document, version, blob


def add_version_from_file(document, *, file_storage, note, uploader):
    """multipart 分支：以一个新文件产出下一个版本（**不 commit**）。"""
    candidate = _validate_upload(file_storage)
    blob = storage.digest_and_persist(candidate.stream)
    return _append_version(document, candidate, blob, note=note, uploader=uploader), blob


def add_version_from_text(document, *, content, note, uploader):
    """JSON 分支：以一段 UTF-8 正文产出下一个版本（**不 commit**）。

    正文被当作一次上传走**完全相同**的落盘链路（含去重与 mtime 触碰）。文件名与 MIME
    沿用当前版本——在线编辑改的是内容，不是文件身份。
    """
    current = document.current_version()
    payload = (content or "").encode("utf-8")
    candidate = UploadCandidate(
        stream=io.BytesIO(payload),
        original_filename=current.original_filename if current else "document.md",
        extension=mimetable.extension_of(current.original_filename) if current else "md",
        mime_type=current.mime_type if current else "text/markdown",
    )
    blob = storage.digest_and_persist(candidate.stream)
    return _append_version(document, candidate, blob, note=note, uploader=uploader), blob


def _append_version(document, candidate: UploadCandidate, blob, *, note, uploader):
    """写一行 DocumentVersion 并把 `document.current_version_id` 指过去。

    **`current_version_id` 的唯一写入点**（models/document.py 模块 docstring）。
    """
    current_max = (db.session.query(func.max(DocumentVersion.version_no))
                   .filter_by(document_id=document.id).scalar())
    version = DocumentVersion(
        document_id=document.id,
        version_no=(current_max or 0) + 1,
        original_filename=candidate.original_filename,
        mime_type=candidate.mime_type,
        size_bytes=blob.size_bytes,
        sha256=blob.sha256,
        note=(note or None),
        uploader_id=uploader.id if uploader else None,
    )
    db.session.add(version)
    db.session.flush()                      # 拿 version.id
    document.current_version_id = version.id
    document.updated_at = utcnow()
    return version


def versions_of(document) -> list:
    """该文档的全部版本，最新在前。"""
    return (DocumentVersion.query.filter_by(document_id=document.id)
            .order_by(DocumentVersion.version_no.desc()).all())


def find_version(document, version_id: Optional[int]):
    """按 `?version_id=` 取版本；缺省取当前版本。**不属于本文档的 id 一律视为不存在**。"""
    if version_id is None:
        return document.current_version()
    version = db.session.get(DocumentVersion, version_id)
    if version is None or version.document_id != document.id:
        return None
    return version


# ————————————————————— 绑定 / 解绑 —————————————————————

def find_link(document_id: int, entity: str, entity_id: int):
    return DocumentLink.query.filter_by(
        document_id=document_id, entity_type=entity, entity_id=entity_id).first()


def bind_document(document, *, entity, ticket, label, actor, uploaded: bool):
    """建一条绑定并写时间线 + 通知（**不 commit**）。

    `stage` 取工单**当前**状态的快照，此后永不回写（§2.4）。
    """
    link = DocumentLink(
        document_id=document.id,
        entity_type=entity,
        entity_id=ticket.id,
        label=(label or None),
        stage=ticket.status,
        created_by_id=actor[1] if actor and actor[0] == "user" else None,
    )
    db.session.add(link)
    db.session.flush()

    title = notifications.short_text(document.title)
    if uploaded:
        message = f"在「{stage_label(entity, ticket.status)}」阶段上传文档「{title}」"
    else:
        message = f"绑定了文档「{title}」"
    Activity.log(entity, ticket.id, "doc_attached", actor=actor,
                 to_status=ticket.status, message=message)
    notifications.notify_document(ticket, entity, document, actor, message=message)
    return link


def unbind_document(document, *, entity, ticket, actor) -> bool:
    """解除绑定（**不 commit**）。

    Returns:
        True 表示确实解除了一次绑定；False 表示本就未绑定——**幂等：不写审计、
        不发通知**，避免时间线被无意义事件刷屏（与 `lifecycle.unassign_ticket` 同策略）。

    解除绑定**刻意不发通知**：它是一次收敛性操作（东西变少了），给所有人推一条通知
    只会制造噪音；时间线上有留痕，需要追责时查得到，这个强度是合适的。
    """
    link = find_link(document.id, entity, ticket.id)
    if link is None:
        return False
    db.session.delete(link)
    title = notifications.short_text(document.title)
    Activity.log(entity, ticket.id, "doc_detached", actor=actor,
                 to_status=ticket.status, message=f"解除了文档「{title}」的绑定")
    return True


def ticket_documents_query(entity: str, entity_id: int):
    """该工单的文档列表查询（最新绑定在前），供 `paginate` 分页。"""
    return (db.session.query(Document, DocumentLink)
            .join(DocumentLink, DocumentLink.document_id == Document.id)
            .filter(DocumentLink.entity_type == entity,
                    DocumentLink.entity_id == entity_id)
            .order_by(DocumentLink.created_at.desc(), DocumentLink.id.desc()))


def bound_kinds(entity: str, entity_id: int) -> dict:
    """该工单当前绑定的全部文档，按 kind 聚合为 `{kind: [document_id, ...]}`。

    判定口径是**当前绑定的全部文档**，而不是「在这个阶段绑定的文档」：一份在
    `assigned` 阶段交的需求说明书，到了 `in_development` 依然满足要求；按阶段切分
    会逼用户为每个阶段重传同一份文件，把设计的初衷（复用）亲手废掉（§2.4）。
    """
    rows = (db.session.query(Document.kind, Document.id)
            .join(DocumentLink, DocumentLink.document_id == Document.id)
            .filter(DocumentLink.entity_type == entity,
                    DocumentLink.entity_id == entity_id)
            .all())
    out = {}
    for kind, document_id in rows:
        out.setdefault(kind, []).append(document_id)
    return out


# ————————————————————— 改版扇出 —————————————————————

def fanout_revision(document, version, actor) -> FanoutResult:
    """为该文档的绑定工单写 `doc_revised` 时间线 + 通知（**不 commit**）。

    【§2.5 · 评审 R11】扇出必须有上限：文档复用正是本轮的立身之本，`link_count`
    天然可以很大——一份绑了 60 张单的接口契约改一版，就是 60 条 Activity + 最多
    120 条 Notification 写在**同一个事务**里，而 SQLite 是单写者。故按 `link.id` 升序
    取前 `DOC_FANOUT_MAX_LINKS` 张单，超出部分**不静默丢弃**：在文档自身写不下，
    就在**首张**单上写一条汇总 Activity，并由响应体如实回传 `fanout_truncated`。
    """
    from models.bug import Bug
    from models.requirement import Requirement

    models = {"requirement": Requirement, "bug": Bug}
    links = (DocumentLink.query.filter_by(document_id=document.id)
             .order_by(DocumentLink.id.asc()).all())
    cap = int(current_app.config.get("DOC_FANOUT_MAX_LINKS", 20))
    title = notifications.short_text(document.title)
    message = f"将文档「{title}」更新到 v{version.version_no}"

    written = 0
    for link in links[:cap]:
        ticket = db.session.get(models.get(link.entity_type), link.entity_id) \
            if link.entity_type in models else None
        if ticket is None:
            continue                        # 单已被删（link 是孤儿）→ 跳过，不写空审计
        Activity.log(link.entity_type, link.entity_id, "doc_revised", actor=actor,
                     to_status=ticket.status, message=message)
        notifications.notify_document(ticket, link.entity_type, document, actor,
                                      message=message)
        written += 1

    truncated = len(links) > cap
    if truncated and links:
        head = links[0]
        Activity.log(head.entity_type, head.entity_id, "doc_revised", actor=actor,
                     message=f"文档「{title}」共绑定 {len(links)} 张单，"
                             f"本次仅向前 {cap} 张写入提醒")
    return FanoutResult(written=written, link_count=len(links), truncated=truncated)


# ————————————————————— 删除与回收 —————————————————————

def detach_all_links(document, actor) -> int:
    """`?force=1` 删除文档时，先为每张受影响的单写一条 `doc_detached` 审计再删链接。"""
    from models.bug import Bug
    from models.requirement import Requirement

    models = {"requirement": Requirement, "bug": Bug}
    links = DocumentLink.query.filter_by(document_id=document.id).all()
    title = notifications.short_text(document.title)
    for link in links:
        ticket = db.session.get(models.get(link.entity_type), link.entity_id) \
            if link.entity_type in models else None
        if ticket is not None:
            Activity.log(link.entity_type, link.entity_id, "doc_detached", actor=actor,
                         to_status=ticket.status,
                         message=f"文档「{title}」已被删除，绑定自动解除")
        db.session.delete(link)
    return len(links)


def delete_document(document) -> set:
    """删除文档本体与其全部版本行（**不 commit**），返回**本次删除后无人引用**的摘要集合。

    调用方的义务（§2.2，顺序不可换）：先 `db.session.commit()`，**之后**才对返回的
    每个摘要调 `storage.delete_blob`。先删文件再回滚 → 数据库留下指向空气的版本记录；
    先提交再删文件失败 → 只留一个孤儿文件，可离线回收。**在两种失败模式之间永远选
    可修复的那个。**
    """
    digests = {v.sha256 for v in
               DocumentVersion.query.filter_by(document_id=document.id).all()}
    DocumentVersion.query.filter_by(document_id=document.id).delete()
    db.session.delete(document)
    db.session.flush()
    return unreferenced_digests(digests)


def unreferenced_digests(digests) -> set:
    """这批摘要里，`document_versions` 中已不再有任何行引用的那些。"""
    candidates = {d for d in digests if d}
    if not candidates:
        return set()
    still_used = {row[0] for row in
                  db.session.query(DocumentVersion.sha256)
                  .filter(DocumentVersion.sha256.in_(list(candidates)))
                  .distinct().all()}
    return candidates - still_used


def reap(digests) -> None:
    """commit **之后**调用：逐个尝试物理回收。失败与「尚在宽限期内」都只记日志。"""
    for digest in digests:
        storage.delete_blob(digest)


# ————————————————————— 展示辅助 —————————————————————

def stage_label(entity: str, status: str) -> str:
    """状态 → 中文名。**不另建映射**，直接取 workflow 的列标题——两处各写一份中文名，
    迟早会漂移（§2.4）。"""
    from services import workflow

    try:
        for key, title in workflow.columns(entity):
            if key == status:
                return title
    except ValueError:
        pass
    return status or ""


def kind_label(kind: str) -> str:
    return DOCUMENT_KIND_LABELS.get(kind, kind)


def entity_label(entity: str) -> str:
    return _ENTITY_LABELS.get(entity, entity)
