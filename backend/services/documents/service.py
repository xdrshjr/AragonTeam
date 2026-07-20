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
from services.documents import trash
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


def add_version_from_text(document, *, content, note, uploader, blob=None):
    """JSON 分支：以一段 UTF-8 正文产出下一个版本（**不 commit**）。

    正文被当作一次上传走**完全相同**的落盘链路（含去重与 mtime 触碰）。文件名与 MIME
    沿用当前版本——在线编辑改的是内容，不是文件身份。

    Args:
        blob: 已由 `persist_text` 落好盘的 `BlobInfo`。缺省时本函数自己落盘；
            Agent 归档必须传入——它的落盘早已在 SQLite 写锁窗口之外完成，此处不做磁盘 IO
            （§2.3 C-2 · 评审 V-03）。
    """
    current = document.current_version()
    if blob is None:
        payload = (content or "").encode("utf-8")
        blob = storage.digest_and_persist(io.BytesIO(payload))
    candidate = UploadCandidate(
        stream=None,
        original_filename=current.original_filename if current else "document.md",
        extension=mimetable.extension_of(current.original_filename) if current else "md",
        mime_type=current.mime_type if current else "text/markdown",
    )
    return _append_version(document, candidate, blob, note=note, uploader=uploader), blob


def add_version_from_existing(document, *, source_version, note, uploader):
    """把某个历史版本重新指定为最新版本（**不 commit**）。

    内容寻址的直接红利：新版本行与源版本行共享同一个 sha256，**磁盘上不写一个字节**，
    也不删任何历史行。回滚在这里是「加一行」，不是「退回去」——审计链完整可读：
    v1 → v2 → v3 → v4(= v1 的内容)。

    元数据（`original_filename` / `mime_type` / `size_bytes` / `sha256`）逐字段抄自源版本，
    因此回滚对**任意**文档可用（含二进制）——它不产生任何新内容，与「能不能当文本编辑」
    毫无关系（§2.2 B-3 / 评审 V-06）。

    Args:
        source_version: 已由调用方校验过归属与 blob 存在性的 `DocumentVersion`。

    Returns:
        新建的 `DocumentVersion`。
    """
    candidate = UploadCandidate(
        stream=None,                        # 无落盘：blob 已在磁盘上，共用同一摘要
        original_filename=source_version.original_filename,
        extension=mimetable.extension_of(source_version.original_filename),
        mime_type=source_version.mime_type,
    )
    blob = storage.BlobInfo(sha256=source_version.sha256,
                            size_bytes=source_version.size_bytes, deduped=True)
    return _append_version(
        document, candidate, blob,
        note=note or f"回滚到 v{source_version.version_no}", uploader=uploader)


def persist_text(content) -> tuple:
    """把一段文本落盘并返回 `(payload, blob)`——**纯磁盘 IO，不碰 `db.session`**。

    单独抽出来只为一个理由：Agent 归档必须把落盘做在 SQLite 写锁窗口**之外**
    （§2.3 C-2 · 评审 V-03），因此它需要「先落盘、稍后再写元数据」这两段能分开调用。
    模板新建没有这个约束，走 `create_text_document` 一次到位即可。

    Raises:
        ValidationError: 正文超过 `DOC_TEXT_EDIT_MAX_BYTES`（→ 全局 400）。
    """
    payload = (content or "").encode("utf-8")
    limit = int(current_app.config.get("DOC_TEXT_EDIT_MAX_BYTES", 524288))
    if len(payload) > limit:                # `create_text_document` 的不变量 3
        raise ValidationError(
            "generated document body is too large", field="content",
            expected=f"at most {limit} bytes")
    return payload, storage.digest_and_persist(io.BytesIO(payload))


def create_text_document(*, title, kind, content, project_id, uploader,
                         filename_stem="document", blob=None):
    """以**一段文本**从零建一份文档 + v1（**不 commit**）。

    【§2.3 C-1 · 评审 V-09】这是全仓库唯一一条**绕过 `_validate_upload` 四道闸**的落盘
    路径（存在性 / 文件名清洗 / 扩展名白名单 / 魔数嗅探）——「一段文本入库」天然走不了
    它们。`add_version_from_text` 之所以安全，是因为它**复用当前版本的文件名与 MIME**，
    文件身份是既定的、早已过闸的；本函数是**从零造身份**。故它自持以下四条不变量：

    1. **扩展名恒为 `md`，不接受调用方指定**（签名里没有 `extension` / `mime_type`
       参数）；MIME 由 `mimetable.mime_for("md")` 推导，与「`Content-Type` 请求头一律
       不信任」的既定原则一致。
    2. **启动期断言 `"md" in DOC_ALLOWED_EXTENSIONS`**（`doc_policy.assert_thresholds`
       并列注册）。运维把 md 摘出白名单却留着模板功能，应当**起不来**，而不是在用户点
       「用模板新建」时抛一个语义不明的 500。
    3. **正文长度上限 = `DOC_TEXT_EDIT_MAX_BYTES`**。模板正文只有几百字、Agent 归档正文
       受 `_MAX_BODY_CHARS` 约束，两者都远在限内；这条闸是为「将来第三个调用方」准备的。
    4. **落盘链路逐字复用 `storage.digest_and_persist`**（含去重与 mtime 触碰），
       `_append_version` 仍是 `current_version_id` 的唯一写入点。不新写一行落盘代码。

    Args:
        title: 文档标题（调用方已按 `want_str(max_len=200)` 校验）。
        kind: `DOCUMENT_KINDS` 之一。
        content: UTF-8 正文。
        project_id: 归属项目（调用方已做存在性前置校验）。
        uploader: 上传者 `User` 或 None（Agent 归档路径为 None）。
        filename_stem: 落盘展示用的**文件名主干**（不含扩展名，恒补 `.md`）。
            为什么它是参数而不是内部推导：文件名要携带工单编号
            （`test_plan-requirement-42.md`），而本模块不认识工单——把 `ticket` 传进
            叶子函数只为拼一个字符串，会给它凭空加一层领域依赖。
        blob: 已由 `persist_text` 落好盘的 `BlobInfo`。缺省时本函数自己落盘；
            Agent 归档必须传入（落盘早已在写锁窗口之外完成，此处一个字节都不写）。

    Returns:
        `(document, version, blob)`，与 `create_document` 同形状。

    Raises:
        ValidationError: 正文超过 `DOC_TEXT_EDIT_MAX_BYTES`（→ 全局 400）。
    """
    if blob is None:
        _, blob = persist_text(content)     # 不变量 3 + 4：同一条落盘链路

    # 不变量 1：扩展名恒为 md，MIME 由扩展名推导，调用方无从指定。
    extension = "md"
    stem = (filename_stem or "document").strip() or "document"
    candidate = UploadCandidate(
        stream=None,                        # 已落盘，无需再读流
        original_filename=f"{stem}.{extension}"[:255],
        extension=extension,
        mime_type=mimetable.mime_for(extension),
    )

    document = Document(
        title=title or candidate.original_filename,
        kind=kind,
        description=None,
        project_id=project_id,
        uploader_id=uploader.id if uploader else None,
    )
    db.session.add(document)
    db.session.flush()
    version = _append_version(document, candidate, blob, note=None, uploader=uploader)
    return document, version, blob


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


def bind_document(document, *, entity, ticket, label, actor, uploaded: bool,
                  stage=None, notify: bool = True):
    """建一条绑定并写时间线 + 通知（**不 commit**）。

    `stage` 取工单**当前**状态的快照，此后永不回写（§2.4）。

    Args:
        stage: 显式覆盖快照状态。Agent 归档要记的是**推进后的目标状态**，而调用发生在
            `ticket.status` 尚未改写之前——读 `ticket.status` 会记下旧阶段（§2.3 C-2）。
        notify: 是否推送 `document_added`。**只有 Agent 归档传 False**（§2.3 C-2 ·
            评审 V-10）：`run=all` 单次最多 6 步、`autorun-all` 跨多张单循环调用，
            默认开启的自动归档会在通知中心刷出一串与人工上传无法区分的 `document_added`。
            取向与 `doc_detached`「收敛性 / 自动性操作不发通知」同源——时间线上有留痕。
            **既有全部调用点行为逐字节不变。**
    """
    link = DocumentLink(
        document_id=document.id,
        entity_type=entity,
        entity_id=ticket.id,
        label=(label or None),
        stage=stage or ticket.status,
        created_by_id=actor[1] if actor and actor[0] == "user" else None,
    )
    db.session.add(link)
    db.session.flush()

    snapshot = stage or ticket.status
    title = notifications.short_text(document.title)
    if uploaded:
        message = f"在「{stage_label(entity, snapshot)}」阶段上传文档「{title}」"
    else:
        message = f"绑定了文档「{title}」"
    Activity.log(entity, ticket.id, "doc_attached", actor=actor,
                 to_status=snapshot, message=message)
    if notify:
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
    """该工单的文档列表查询（最新绑定在前），供 `paginate` 分页。

    【过滤点 3 · §2.4】漏掉 `trash.not_deleted()` 的后果：工单抽屉里仍然列着已删文档。
    """
    return (db.session.query(Document, DocumentLink)
            .join(DocumentLink, DocumentLink.document_id == Document.id)
            .filter(DocumentLink.entity_type == entity,
                    DocumentLink.entity_id == entity_id)
            .filter(trash.not_deleted())
            .order_by(DocumentLink.created_at.desc(), DocumentLink.id.desc()))


def bound_kinds(entity: str, entity_id: int) -> dict:
    """该工单当前绑定的全部文档，按 kind 聚合为 `{kind: [document_id, ...]}`。

    判定口径是**当前绑定的全部文档**，而不是「在这个阶段绑定的文档」：一份在
    `assigned` 阶段交的需求说明书，到了 `in_development` 依然满足要求；按阶段切分
    会逼用户为每个阶段重传同一份文件，把设计的初衷（复用）亲手废掉（§2.4）。

    【过滤点 4 · §2.4 —— 八处里最隐蔽也最危险的一处】它是阶段清单与门禁的**唯一**判据
    来源。漏掉 `trash.not_deleted()`，一份已被删除的文档**仍会把清单项点绿、仍会让门禁
    放行**，而且不会抛任何异常——数字与清单只是安静地说谎。
    `test_deleted_document_no_longer_satisfies_checklist` 守卫这一点。
    """
    rows = (db.session.query(Document.kind, Document.id)
            .join(DocumentLink, DocumentLink.document_id == Document.id)
            .filter(DocumentLink.entity_type == entity,
                    DocumentLink.entity_id == entity_id)
            .filter(trash.not_deleted())
            .all())
    out = {}
    for kind, document_id in rows:
        out.setdefault(kind, []).append(document_id)
    return out


# ————————————————————— 改版扇出 —————————————————————

def fanout_revision(document, version, actor, *, notify: bool = True,
                    action: str = "doc_revised", message: str = None) -> FanoutResult:
    """为该文档的绑定工单写改版时间线 + 通知（**不 commit**）。

    Args:
        notify: 是否推送 `document_added`。只有 Agent 归档传 False，理由与
            `bind_document` 的同名参数完全相同（§2.3 C-2 · 评审 V-10）。
        action: 时间线动作名。回滚传 `doc_rolled_back`——它**复用本函数的扇出与上限**，
            而不是另写一份循环（§2.2 B-3）。`Activity.entity_type` 只有
            requirement / bug 两个合法值，故回滚同样落在**绑定工单**的时间线上，
            不为文档另造一种实体类型。
        message: 覆盖默认文案（回滚要说的是「回滚到 v1」而不是「更新到 v4」）。

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
    message = message or f"将文档「{title}」更新到 v{version.version_no}"

    written = 0
    for link in links[:cap]:
        ticket = db.session.get(models.get(link.entity_type), link.entity_id) \
            if link.entity_type in models else None
        if ticket is None:
            continue                        # 单已被删（link 是孤儿）→ 跳过，不写空审计
        Activity.log(link.entity_type, link.entity_id, action, actor=actor,
                     to_status=ticket.status, message=message)
        if notify:
            notifications.notify_document(ticket, link.entity_type, document, actor,
                                          message=message)
        written += 1

    truncated = len(links) > cap
    if truncated and links:
        head = links[0]
        Activity.log(head.entity_type, head.entity_id, action, actor=actor,
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
