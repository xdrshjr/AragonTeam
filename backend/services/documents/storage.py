"""文档 blob 存储层（ticket-document-management §2.2）——**唯一**接触文件系统的模块。

内容寻址（content-addressed storage）：文件按 SHA-256 摘要落盘到
`UPLOAD_DIR/<ab>/<cd>/<digest>`，元数据全部进数据库。一刀切在这里同时拿下三件事：

- **去重**：同一份文件被不同人传 10 次只占一份磁盘；
- **防路径穿越**：落盘路径由摘要推导，与用户提供的文件名**结构性无关**——
  路径穿越在本设计里是不可能，而不是靠某个清洗函数守住的；
- **可校验**：摘要即完整性签名。

对外只暴露六个函数（窄接口是为未来切换到对象存储预留的唯一替换面，§8 R-11）：
`digest_and_persist` / `blob_path` / `open_blob` / `read_text` / `delete_blob` / `is_reapable`。

UPLOAD_DIR 不可写时一律抛 `StorageUnavailable`，路由层映射为 **503** 而非 500——
这是运维问题不是代码缺陷，用户与告警系统都应该看到二者的区别（§2.2 / 评审 R14）。
"""
import hashlib
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import BinaryIO, NamedTuple, Optional

from flask import current_app

log = logging.getLogger("aragon.documents.storage")

# 分块大小。**绝不 stream.read() 一次读进内存**——20 MB 上限乘以并发就是 OOM。
CHUNK_SIZE = 64 * 1024

# 临时目录名。`.part` 文件是**别的进程正在写**的半成品，天然满足「磁盘上有、
# document_versions 里无人引用」，必须显式排除在回收判据之外（§2.2 / 评审 R4）。
TMP_DIRNAME = ".tmp"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
# 内容寻址的路径形状。形状不符的一律不碰（运维手工放进去的文件、备份、README
# 都不该被工具删）。
_BLOB_SHAPE_RE = re.compile(r"^[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{64}$")

_DEFAULT_GRACE_SECONDS = 3600


class StorageUnavailable(RuntimeError):
    """UPLOAD_DIR 不可读写 → 路由层 503。稳定异常类，勿更名（对外错误契约）。"""


class BlobMissing(LookupError):
    """DB 里有版本记录、磁盘上没有文件 → 路由层 410 Gone（§8 R-9）。"""


class BlobInfo(NamedTuple):
    """`digest_and_persist` 的返回值。`deduped` 为真表示本次未写盘（命中既有 blob）。"""

    sha256: str
    size_bytes: int
    deduped: bool


class TextRead(NamedTuple):
    """`read_text` 的返回值。

    `truncated`: 原文超过 max_bytes，只取回了前 max_bytes 字节。
    `encoding_confident`: 严格 UTF-8 解码成功。为假时内容里含 U+FFFD 替换字符，
        **可预览但恒不可编辑**——保存会把每个不可解码字节写成 U+FFFD，
        原文件不可逆损毁（§2.6 / 评审 R5）。
    """

    content: str
    truncated: bool
    encoding_confident: bool


# ————————————————————— 路径 —————————————————————

def upload_root() -> Path:
    """blob 根目录。唯一读取源是 `app.config["UPLOAD_DIR"]`（测试逐用例注入 tmp_path）。"""
    return Path(current_app.config["UPLOAD_DIR"])


def blob_path(sha256: str) -> Path:
    """摘要 → 绝对路径。非摘要形状的输入直接 ValueError（绝不拼进路径）。"""
    digest = (sha256 or "").lower()
    if not _SHA256_RE.match(digest):
        raise ValueError(f"not a sha256 digest: {sha256!r}")
    return upload_root() / digest[0:2] / digest[2:4] / digest


def _tmp_dir() -> Path:
    return upload_root() / TMP_DIRNAME


def _ensure_dir(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StorageUnavailable(f"cannot create directory {path}: {exc}") from exc


def _grace_seconds(override: Optional[float] = None) -> float:
    if override is not None:
        return override
    try:
        return float(current_app.config.get("BLOB_GRACE_SECONDS", _DEFAULT_GRACE_SECONDS))
    except RuntimeError:  # pragma: no cover - 无应用上下文时的兜底
        return _DEFAULT_GRACE_SECONDS


# ————————————————————— 落盘 —————————————————————

def digest_and_persist(stream: BinaryIO) -> BlobInfo:
    """把 stream 的**全部内容**落盘并返回 (sha256, size_bytes, deduped)。

    Args:
        stream: 任意可读二进制流。**入口契约：游标必须在 0**，见下。

    Returns:
        BlobInfo。`deduped=True` 表示目标 blob 已存在、本次未写盘。

    Raises:
        ValueError: 入口断言失败（游标不在 0）。
        StorageUnavailable: UPLOAD_DIR 不可写。

    【§2.2 步骤 0 · 评审 R1（P0）｜这个断言不得以「理论上不会发生」为由省略】
    上游 `service._validate_upload` 的魔数嗅探会读走开头 12 字节。一旦它忘记复位，
    本函数会**从第 13 字节开始**读，落盘内容 = 原文件 `[12:]`，而摘要基于残缺内容
    计算 —— 于是去重、完整性校验、下载**全部自洽地正确**，没有任何一条既有断言会
    失败。那是一条静默的、全量的数据损坏，只会在上线之后由用户发现「下载下来的
    PNG 打不开」。本断言与 `_validate_upload` 的出口不变量互为对照，二者缺一，
    本轮就会以「测试全绿 + 每个文件都损坏」的形式上线。
    """
    try:
        position = stream.tell()
    except (AttributeError, OSError):
        position = None                     # 不可 tell 的流（如管道）无法断言，放行
    if position not in (None, 0):
        raise ValueError(
            "digest_and_persist requires a stream positioned at 0, "
            f"got tell()=={position}; the caller consumed part of the file "
            "(see services/documents/service._validate_upload)"
        )

    _ensure_dir(_tmp_dir())
    tmp = _tmp_dir() / f"{uuid.uuid4().hex}.part"
    digest = hashlib.sha256()
    size = 0
    try:
        try:
            with open(tmp, "wb") as handle:
                while True:
                    chunk = stream.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    handle.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
        except OSError as exc:
            raise StorageUnavailable(f"cannot write to {tmp}: {exc}") from exc

        sha256 = digest.hexdigest()
        target = blob_path(sha256)
        if target.exists():
            return _dedup_hit(sha256, size)

        _ensure_dir(target.parent)
        try:
            # 同一文件系统内 os.replace 是原子的，因此永远不存在「半个文件被别的
            # 请求读到」的窗口。
            os.replace(tmp, target)
        except OSError as exc:
            # 【评审 R13】两个并发请求首次上传相同内容时会双双走到这一步；Windows 下
            # 若目标此刻正被另一进程打开读取，os.replace 抛 PermissionError。
            # 内容寻址下「目标已存在」与「我刚写成功」在语义上完全等价 → 按去重命中处理。
            if target.exists():
                return _dedup_hit(sha256, size)
            raise StorageUnavailable(f"cannot place blob at {target}: {exc}") from exc
        return BlobInfo(sha256, size, False)
    finally:
        # 任何异常路径都清理 .part（成功路径下 os.replace 已把它搬走，这里是 no-op）。
        try:
            if tmp.exists():
                os.remove(tmp)
        except OSError:  # pragma: no cover - 清理失败只留一个临时文件，交给 GC
            log.warning("failed to clean up temp blob %s", tmp)


def _dedup_hit(sha256: str, size: int) -> BlobInfo:
    """去重命中：触碰目标 mtime 后返回。

    【§2.2 步骤 3 · 评审 R4】这一次 `os.utime` **不是**可有可无的整洁动作，它是
    宽限窗口判据（`is_reapable`）的唯一输入：去重命中时不写盘，若不触碰 mtime，
    一个「很久以前落盘、刚刚被复用」的 blob 在 GC 眼里与「很久以前落盘、早已无人
    引用」完全一样，下一轮 GC 就会把用户刚上传的文件删掉。
    """
    try:
        os.utime(blob_path(sha256), None)
    except OSError:  # pragma: no cover - 触碰失败只缩短宽限窗口，不影响正确性
        log.warning("failed to touch deduped blob %s", sha256)
    return BlobInfo(sha256, size, True)


# ————————————————————— 读取 —————————————————————

def open_blob(sha256: str) -> BinaryIO:
    """按摘要打开只读句柄；文件缺失抛 `BlobMissing`（→ 410），IO 故障抛 `StorageUnavailable`。"""
    path = blob_path(sha256)
    try:
        return open(path, "rb")
    except FileNotFoundError as exc:
        raise BlobMissing(sha256) from exc
    except OSError as exc:
        raise StorageUnavailable(f"cannot read blob {sha256}: {exc}") from exc


def blob_exists(sha256: str) -> bool:
    """该摘要的 blob 是否真的躺在磁盘上。

    版本回滚的前置校验（§2.2 B-3）：**绝不允许**建出一行指向空气的版本——那会让用户
    点一次回滚就把「当前版本」变成一个下载即 410 的空壳。畸形摘要一律视为不存在
    （与 `blob_path` 的 ValueError 语义一致，但调用方要的是一个布尔而不是一个异常）。

    路径推导仍只有 `blob_path` 一处，本函数不自己拼路径。
    """
    try:
        return blob_path(sha256).exists()
    except (ValueError, OSError):
        return False


def read_text(sha256: str, max_bytes: int) -> TextRead:
    """读取最多 max_bytes 字节并解码为文本。

    先尝试**严格** UTF-8；失败则以 `errors="replace"` 解码并置 `encoding_confident=False`
    ——可预览（看不到内容对用户毫无价值），但恒不可编辑（§2.6 / 评审 R5）。

    注：截断可能恰好切断一个多字节字符，从而让 `encoding_confident` 为假。这不会
    造成误判——`truncated == True` 已经蕴含「不可编辑」，两个条件同向。
    """
    with open_blob(sha256) as handle:
        raw = handle.read(max_bytes + 1)
    truncated = len(raw) > max_bytes
    if truncated:
        raw = raw[:max_bytes]
    try:
        return TextRead(raw.decode("utf-8"), truncated, True)
    except UnicodeDecodeError:
        return TextRead(raw.decode("utf-8", errors="replace"), truncated, False)


# ————————————————————— 回收 —————————————————————

def is_reapable(path, now: float, *, grace_seconds: Optional[float] = None) -> bool:
    """该磁盘文件是否可以被物理回收（三条判据缺一不可）。

    **在线删除路径与 `tools/gc_orphan_blobs.py` 共用本函数，不允许两处各写一份**
    （§2.2 / §4.4 / 评审 R4）：

    1. 路径**不在** `UPLOAD_DIR/.tmp/` 下 —— `.part` 是别的进程正在写的临时文件；
    2. 路径**符合** `<2hex>/<2hex>/<64hex>` 的内容寻址形状；
    3. `now - mtime >= BLOB_GRACE_SECONDS` —— 与去重命中时的 `os.utime` 配对，
       把「删除↔去重」竞态窗口从毫秒级不可控变成小时级且可配。

    本函数**只回答「能不能删」，不回答「该不该删」**（是否仍被引用由调用方判定）。
    """
    candidate = Path(path)
    try:
        relative = candidate.resolve().relative_to(upload_root().resolve())
    except (ValueError, OSError, RuntimeError):
        return False                        # 不在 UPLOAD_DIR 下 / 路径不可解析
    if relative.parts and relative.parts[0] == TMP_DIRNAME:
        return False
    if not _BLOB_SHAPE_RE.match(relative.as_posix()):
        return False
    try:
        mtime = candidate.stat().st_mtime
    except OSError:
        return False
    return (now - mtime) >= _grace_seconds(grace_seconds)


def delete_blob(sha256: str) -> bool:
    """物理删除一个 blob，幂等；不满足 `is_reapable` 时**不删**并返回 False。

    【§2.2 · 评审 R4】在线删除路径**只做引用判定，物理删除统一交给宽限窗口**：
    请求 A 删掉最后一个引用摘要 X 的版本并提交后、真正 unlink 之前，请求 B 可能
    上传了内容恰好为 X 的文件 —— **去重命中不写盘**，只插一行版本记录 —— 此时
    A 的 unlink 会让 B 的文件永久指向空气。文档复用正是本轮的立身之本，重复内容
    是预期高频行为，这不是理论窗口。

    失败（含判定不通过）**只记 warning，绝不向上抛**：文件系统的临时故障不该让一次
    已经成功提交的删除对用户显示为失败；漏删的代价只是磁盘多占几 MB，下一轮 GC 会收走。
    """
    try:
        path = blob_path(sha256)
    except ValueError:
        log.warning("delete_blob got a malformed digest: %r", sha256)
        return False
    try:
        if not path.exists():
            return False
        if not is_reapable(path, time.time()):
            log.info("blob %s is within the grace window; leaving it to the offline GC",
                     sha256)
            return False
        os.remove(path)
        return True
    except OSError as exc:
        log.warning("failed to delete blob %s: %s", sha256, exc)
        return False
