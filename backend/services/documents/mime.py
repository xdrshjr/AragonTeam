"""扩展名 → MIME / 魔数的静态映射（ticket-document-management §2.3 闸 3、闸 4）。

**为什么是独立的叶子模块**（spec §3.1 原本把这些表放在 service.py）：`models/document.py`
的 `is_text_editable` 需要 `TEXT_EXTENSIONS`，而 `service.py` 反过来 import 模型——
放在 service.py 会成环。本模块只依赖 stdlib，任何一层都可安全 import。

一条贯穿的原则：**`Content-Type` 请求头一律不信任**，MIME 只由扩展名经这里推导。
"""
import re

# 文本类扩展名：可在线预览与编辑的全集。本表之外的一律「二进制」，只能下载。
TEXT_EXTENSIONS = ("md", "txt", "log", "csv", "json", "yaml", "yml")

# 允许以 `Content-Disposition: inline` 回吐的 MIME 白名单（§4.1 下载响应头）。
# 前端构造预览用 Blob 时**必须**先经本白名单过滤（§2.6 / 评审 R6），
# 落选一律 application/octet-stream 并走下载。
# `text/html` 与 `image/svg+xml` 既不在这里也不在扩展名白名单——它们能在同源下
# 执行脚本，inline 渲染等于给自己开一个存储型 XSS。
INLINE_SAFE_MIMES = (
    "image/png", "image/jpeg", "image/gif", "image/webp",
    "application/pdf", "text/plain", "text/markdown",
)

_MIME_BY_EXT = {
    "md": "text/markdown",
    "txt": "text/plain",
    "log": "text/plain",
    "csv": "text/csv",
    "json": "application/json",
    "yaml": "application/yaml",
    "yml": "application/yaml",
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "zip": "application/zip",
}

# 魔数表：ext → 必须**全部**命中的 (offset, magic) 序列。
#
# **未登记的扩展名一律放行**，这是明确的兜底规则而非疏漏：纯文本类本就无签名，强行
# 猜只会误伤；`doc/xls/ppt` 是 OLE2 复合文档（\xd0\xcf\x11\xe0），与更早的其他格式
# 共用同一签名，判定价值低于误伤成本，故同样不登记。
#
# 这一闸的目的**不是**防杀毒，而是防「把 .html 改名成 .png 上传，再骗浏览器 inline 渲染」。
_SIGNATURES = {
    "png": ((0, b"\x89PNG"),),
    "jpg": ((0, b"\xff\xd8\xff"),),
    "jpeg": ((0, b"\xff\xd8\xff"),),
    "gif": ((0, b"GIF8"),),
    "pdf": ((0, b"%PDF-"),),
    "webp": ((0, b"RIFF"), (8, b"WEBP")),
    # zip 系共用同一签名（docx/xlsx/pptx 都是 zip 容器）。
    "zip": ((0, b"PK\x03\x04"),),
    "docx": ((0, b"PK\x03\x04"),),
    "xlsx": ((0, b"PK\x03\x04"),),
    "pptx": ((0, b"PK\x03\x04"),),
}

# 嗅探需要读取的字节数：覆盖上表最长的 (offset + len(magic)) = 8 + 4 = 12。
SNIFF_BYTES = 12

_EXT_RE = re.compile(r"^[A-Za-z0-9]{1,16}$")


def extension_of(filename: str) -> str:
    """取文件名的小写扩展名；无扩展名 / 形状异常返回空串。"""
    name = filename or ""
    if "." not in name:
        return ""
    ext = name.rsplit(".", 1)[-1].lower()
    return ext if _EXT_RE.match(ext) else ""


def mime_for(extension: str) -> str:
    """扩展名 → MIME。未登记的扩展名回落 `application/octet-stream`。"""
    return _MIME_BY_EXT.get((extension or "").lower(), "application/octet-stream")


def signature_matches(extension: str, head: bytes) -> bool:
    """魔数是否与扩展名相符。**未登记的扩展名恒返回 True**（见上方兜底规则）。

    零字节文件（读不满所需长度）视为无签名，放行——空文件不是攻击载荷。
    """
    expectations = _SIGNATURES.get((extension or "").lower())
    if not expectations:
        return True
    if not head:
        return True
    for offset, magic in expectations:
        segment = head[offset:offset + len(magic)]
        if len(segment) < len(magic):
            return True                     # 读不满：无从判定，放行
        if segment != magic:
            return False
    return True


def is_inline_safe(mime_type: str) -> bool:
    return (mime_type or "") in INLINE_SAFE_MIMES
