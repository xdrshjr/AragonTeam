"""Document / DocumentVersion 模型（ticket-document-management §5.1）。

**三分而非一表**：Document 是逻辑实体（标题 / 类型 / 归属），DocumentVersion 是物理
实体（一次落盘 = 一个版本）。一张 `attachments` 表意味着「同一份文件绑 5 张单」要存
5 行、5 份磁盘副本，改名要改 5 处——那正是本轮要消灭的问题本身；而「编辑」若不产生
新版本行，就只能覆盖原文件、历史直接消失。

`documents.current_version_id` 是**刻意的冗余**，让列表页一次查询拿到当前版本，避免
每行一次子查询。它由 `services/documents/service.py::add_version()` **单点维护**，
不允许任何其他代码路径写。它也**刻意不建外键**：documents ↔ document_versions 双向
外键在 SQLite 下会让「先插文档再插版本」这一必经顺序无法满足。
"""
from extensions import db, utcnow

# 文档类型枚举（§5.2）。走 want_str(..., choices=DOCUMENT_KINDS, default="other")。
DOCUMENT_KINDS = (
    "requirement_spec",  # 需求说明
    "design",            # 技术方案
    "test_plan",         # 测试计划
    "test_report",       # 测试 / 验收报告
    "bug_evidence",      # 复现材料（录屏 / 日志 / 截图）
    "release_note",      # 发布说明
    "reference",         # 参考资料
    "other",             # 其他
)

# 类型的中文名（阶段清单与前端徽章的后端权威副本，与 workflow 列名同策略）。
DOCUMENT_KIND_LABELS = {
    "requirement_spec": "需求说明",
    "design": "技术方案",
    "test_plan": "测试计划",
    "test_report": "测试报告",
    "bug_evidence": "复现材料",
    "release_note": "发布说明",
    "reference": "参考资料",
    "other": "其他",
}


class Document(db.Model):
    __tablename__ = "documents"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    kind = db.Column(db.String(32), nullable=False, default="other")
    description = db.Column(db.Text, nullable=True)
    # 真外键（单态，且语义上确实不允许悬挂）。**外键在 DB 层真实生效**
    # （extensions.py 对每条连接执行 PRAGMA foreign_keys=ON），故写接口必须
    # 前置校验存在性，绝不依赖 IntegrityError 兜底（否则 500，见 §2.3 闸 0）。
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True)
    uploader_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    # 无外键：与 document_versions 互相引用会成环（见模块 docstring）。
    current_version_id = db.Column(db.Integer, nullable=True)

    # —— 软删除（document-lifecycle-depth §5.1）——
    # 三条刻意的取舍，改动前请先读 §5.1：
    #   1. `deleted_by_id` **不建外键**——`create_all` 会为 ForeignKey 生成
    #      `REFERENCES users(id)`，而 `schema_sync` 的 ADD COLUMN 片段不会，于是全新库
    #      与存量库的约束不一致，而 `PRAGMA foreign_keys=ON` 在两种库上表现不同。
    #      宁可少一个约束，也不要两种库跑出两种行为（用户解析走 `_resolve_author`，
    #      本就不依赖外键）。
    #   2. **不加索引**：`schema_sync` 加不了索引，只写在模型里就是「新库有、存量库没有」。
    #   3. 默认 NULL、无 NOT NULL：存量行天然全部「未删除」，零回填。
    deleted_at = db.Column(db.DateTime, nullable=True)
    deleted_by_id = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        db.Index("ix_documents_project", "project_id"),
        db.Index("ix_documents_kind", "kind"),
    )

    @property
    def is_deleted(self) -> bool:
        """是否在回收站里。判据的**查询侧**唯一出处是 `services/documents/trash.py`。"""
        return self.deleted_at is not None

    def resolve_uploader(self):
        """上传者概要；已删除时降级为占位（复用 comment 的多态解析策略）。"""
        if self.uploader_id is None:
            return None
        from .comment import _resolve_author

        return _resolve_author("user", self.uploader_id)

    def resolve_deleted_by(self):
        """删除者概要；未删除返回 None（回收站列表要显示「谁删的」）。"""
        if self.deleted_by_id is None:
            return None
        from .comment import _resolve_author

        return _resolve_author("user", self.deleted_by_id)

    def current_version(self):
        """当前版本对象；`current_version_id` 为空或指向已删除行时返回 None。"""
        if self.current_version_id is None:
            return None
        return db.session.get(DocumentVersion, self.current_version_id)

    def to_dict(self, *, link_count: int = None, version=None) -> dict:
        """§4.1 的 `Document` 响应形状（列表与详情共用的基础块）。

        Args:
            link_count: 批量预取的绑定数。缺省则现算——列表端点**应当**传入批量结果
                （`services/documents/counts.py`），否则 50 行就是 50 次子查询。
            version: 批量预取的当前版本对象，同上。
        """
        current = version if version is not None else self.current_version()
        if link_count is None:
            from .document_link import DocumentLink

            link_count = DocumentLink.query.filter_by(document_id=self.id).count()
        return {
            "id": self.id,
            "title": self.title,
            "kind": self.kind,
            "description": self.description,
            "project_id": self.project_id,
            "uploader": self.resolve_uploader(),
            "current_version": current.to_dict() if current else None,
            "link_count": link_count,
            "editable": is_text_editable(current),
            # 非空即在回收站（§5.2）。前端据此渲染回收站行与「恢复」入口。
            "deleted_at": _iso(self.deleted_at),
            "deleted_by": self.resolve_deleted_by(),
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


class DocumentVersion(db.Model):
    __tablename__ = "document_versions"

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id"), nullable=False)
    version_no = db.Column(db.Integer, nullable=False)
    # 用户原始文件名（含中文），仅作展示与下载头；**落盘路径与它结构性无关**。
    original_filename = db.Column(db.String(255), nullable=False)
    # 由扩展名经 _MIME_BY_EXT 推导，**不信任** Content-Type 请求头。
    mime_type = db.Column(db.String(128), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    note = db.Column(db.String(255), nullable=True)
    uploader_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    __table_args__ = (
        db.Index("uq_docver_doc_no", "document_id", "version_no", unique=True),
        # 去重查询与 GC 扫描的支撑索引——没有它，GC 会退化成全表扫描。
        db.Index("ix_docver_sha", "sha256"),
    )

    def resolve_uploader(self):
        if self.uploader_id is None:
            return None
        from .comment import _resolve_author

        return _resolve_author("user", self.uploader_id)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "version_no": self.version_no,
            "original_filename": self.original_filename,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "note": self.note,
            "uploader": self.resolve_uploader(),
            "created_at": _iso(self.created_at),
        }


def is_text_editable(version) -> bool:
    """该版本是否**结构上**可在线编辑：文本扩展名 + 大小不超过编辑阈值。

    这是四条判据里**不需要读文件**的两条。另外两条（`not truncated` 与
    `encoding_confident`）由 `GET /documents/:id/content` 现读现判，并由
    `POST /documents/:id/versions` 的 JSON 分支独立复核（§2.6 / 评审 R5）。

    之所以这两条能在无 IO 的情况下省掉：配置层钉死
    `DOC_TEXT_PREVIEW_MAX_BYTES > DOC_TEXT_EDIT_MAX_BYTES`（doc_policy 启动期断言），
    因此「大小 ≤ 编辑阈值」的文件在结构上不可能被预览截断。
    """
    if version is None:
        return False
    from flask import current_app

    from services.documents.mime import TEXT_EXTENSIONS, extension_of

    if extension_of(version.original_filename) not in TEXT_EXTENSIONS:
        return False
    limit = current_app.config.get("DOC_TEXT_EDIT_MAX_BYTES", 524288)
    return (version.size_bytes or 0) <= limit


def _iso(dt):
    return dt.isoformat() + "Z" if dt else None
