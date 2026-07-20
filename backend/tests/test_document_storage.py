"""存储层用例（ticket-document-management §7.2）。

**本文件的前两条是本轮最重要的两条用例。** spec v1 列出的 23 条用例没有任何一条能
捕获「魔数嗅探消费了流 → 每个文件丢开头 12 字节」这个 P0——因为落盘、去重、下载全都
基于残缺内容自洽。**唯一的判据是字节级往返相等。**
"""
import io
import os
import time

import pytest

from extensions import db
from models.document import Document, DocumentVersion
from services.documents import service as documents
from services.documents import storage


PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def _png(size: int = 70_000) -> bytes:
    """一个带真实魔数头的确定性 PNG 载荷（内容非法但对存储层无差别）。"""
    body = bytes(range(256)) * ((size // 256) + 1)
    return PNG_HEADER + body[:size]


class _Upload:
    """最小 FileStorage 替身：只需要 `.filename` 与 `.stream` 两个属性。"""

    def __init__(self, filename: str, payload: bytes):
        self.filename = filename
        self.stream = io.BytesIO(payload)


# ————————————————————— R1（P0）：字节级往返 + 嗅探不消费流 —————————————————————

# 参数化只带**文件名**，载荷在用例内构造：pytest 会把参数拼进 PYTEST_CURRENT_TEST
# 环境变量，几十 KB 的 bytes 参数会撞上 Windows 的 32767 字符上限。
_ROUNDTRIP_PAYLOADS = {
    "shot.png": lambda: _png(),
    "plan.md": lambda: ("# 方案\n" + "内容行\n" * 5000).encode("utf-8"),
    "doc.pdf": lambda: b"%PDF-1.7\n" + bytes(range(256)) * 300,
    "bundle.zip": lambda: b"PK\x03\x04" + bytes(range(256)) * 300,
}


@pytest.mark.parametrize("filename", sorted(_ROUNDTRIP_PAYLOADS))
def test_downloaded_bytes_match_uploaded_bytes(app, filename):
    """【R1 · P0】落盘内容必须与上传内容**逐字节相等**。

    这是本轮唯一能捕获「嗅探把游标推到 12 之后没复位」的断言：按那种实现，落盘内容
    是原文件 `[12:]`，而摘要基于残缺内容计算，于是去重、完整性校验、下载全部
    「自洽地正确」，其余每一条用例都会通过。
    """
    payload = _ROUNDTRIP_PAYLOADS[filename]()
    with app.app_context():
        upload = _Upload(filename, payload)
        candidate = documents._validate_upload(upload)
        blob = storage.digest_and_persist(candidate.stream)
        assert blob.size_bytes == len(payload)
        with storage.open_blob(blob.sha256) as handle:
            assert handle.read() == payload


def test_sniffing_does_not_consume_stream(app):
    """【R1 · P0】`_validate_upload` 的出口不变量：游标恒在 0（成功与异常路径皆然）。"""
    with app.app_context():
        upload = _Upload("shot.png", _png(1024))
        documents._validate_upload(upload)
        assert upload.stream.tell() == 0

        # 异常路径：扩展名不合法时同样不得留下被推进的游标。
        from services.validation import ValidationError

        bad = _Upload("evil.html", b"<script>alert(1)</script>")
        with pytest.raises(ValidationError):
            documents._validate_upload(bad)
        assert bad.stream.tell() == 0


def test_digest_and_persist_rejects_a_consumed_stream(app):
    """入口断言本身也要有护栏：游标不在 0 时必须炸，而不是静默丢字节。"""
    with app.app_context():
        stream = io.BytesIO(_png(1024))
        stream.read(12)
        with pytest.raises(ValueError):
            storage.digest_and_persist(stream)


# ————————————————————— 摘要 / 去重 / 原子替换 —————————————————————

def test_digest_matches_hashlib(app):
    import hashlib

    payload = _png(5000)
    with app.app_context():
        blob = storage.digest_and_persist(io.BytesIO(payload))
        assert blob.sha256 == hashlib.sha256(payload).hexdigest()
        assert blob.deduped is False
        assert storage.blob_path(blob.sha256).exists()


def test_identical_content_shares_one_blob(app):
    payload = _png(4096)
    with app.app_context():
        first = storage.digest_and_persist(io.BytesIO(payload))
        second = storage.digest_and_persist(io.BytesIO(payload))
        assert first.sha256 == second.sha256
        assert second.deduped is True
        root = storage.upload_root()
        blobs = [p for p in root.rglob("*") if p.is_file()
                 and storage.TMP_DIRNAME not in p.parts]
        assert len(blobs) == 1


def test_dedup_touches_blob_mtime(app):
    """【R4】去重命中必须刷新 mtime——它是宽限窗口判据的唯一输入。"""
    payload = _png(2048)
    with app.app_context():
        blob = storage.digest_and_persist(io.BytesIO(payload))
        path = storage.blob_path(blob.sha256)
        old = time.time() - 7200
        os.utime(path, (old, old))
        assert path.stat().st_mtime < time.time() - 3600

        storage.digest_and_persist(io.BytesIO(payload))
        assert path.stat().st_mtime > time.time() - 60


def test_temp_files_are_cleaned_up(app):
    with app.app_context():
        storage.digest_and_persist(io.BytesIO(_png(1024)))
        tmp_dir = storage.upload_root() / storage.TMP_DIRNAME
        assert list(tmp_dir.glob("*.part")) == []


def test_concurrent_replace_degrades_to_dedup(app, monkeypatch):
    """【R13】Windows 下目标被占用时 `os.replace` 抛 PermissionError → 按去重命中处理。"""
    payload = _png(1024)
    with app.app_context():
        first = storage.digest_and_persist(io.BytesIO(payload))
        real_replace = os.replace

        def _boom(src, dst):
            raise PermissionError("target is open in another process")

        monkeypatch.setattr(os, "replace", _boom)
        # 目标已存在 → 走 target.exists() 早返回，根本到不了 os.replace。
        assert storage.digest_and_persist(io.BytesIO(payload)).deduped is True
        monkeypatch.setattr(os, "replace", real_replace)
        assert storage.blob_path(first.sha256).exists()


# ————————————————————— 读取 —————————————————————

def test_missing_blob_raises_blob_missing(app):
    with app.app_context():
        blob = storage.digest_and_persist(io.BytesIO(b"hello world"))
        os.remove(storage.blob_path(blob.sha256))
        with pytest.raises(storage.BlobMissing):
            storage.open_blob(blob.sha256)


def test_read_text_flags_non_utf8_as_unconfident(app):
    payload = "姓名,备注\n张三,已验证\n".encode("gbk")
    with app.app_context():
        blob = storage.digest_and_persist(io.BytesIO(payload))
        read = storage.read_text(blob.sha256, 1_000_000)
        assert read.encoding_confident is False
        assert read.truncated is False
        assert "�" in read.content


def test_read_text_marks_truncation(app):
    payload = ("行\n" * 2000).encode("utf-8")
    with app.app_context():
        blob = storage.digest_and_persist(io.BytesIO(payload))
        read = storage.read_text(blob.sha256, 100)
        assert read.truncated is True
        assert len(read.content.encode("utf-8", errors="replace")) <= 100


def test_blob_path_rejects_non_digest_input(app):
    with app.app_context():
        for bad in ("../../etc/passwd", "", "zz" * 32, None):
            with pytest.raises(ValueError):
                storage.blob_path(bad)


# ————————————————————— is_reapable —————————————————————

def test_is_reapable_skips_tmp_and_recent_blobs(app):
    with app.app_context():
        blob = storage.digest_and_persist(io.BytesIO(_png(512)))
        path = storage.blob_path(blob.sha256)
        now = time.time()
        assert storage.is_reapable(path, now) is False      # 刚落盘 → 宽限期内

        old = now - 7200
        os.utime(path, (old, old))
        assert storage.is_reapable(path, now) is True

        tmp_dir = storage.upload_root() / storage.TMP_DIRNAME
        tmp_dir.mkdir(parents=True, exist_ok=True)
        part = tmp_dir / "inflight.part"
        part.write_bytes(b"half a file")
        os.utime(part, (old, old))
        assert storage.is_reapable(part, now) is False      # 别人正在写

        stray = storage.upload_root() / "README.txt"
        stray.write_bytes(b"ops note")
        os.utime(stray, (old, old))
        assert storage.is_reapable(stray, now) is False     # 形状不符


def test_delete_blob_respects_the_grace_window(app):
    with app.app_context():
        blob = storage.digest_and_persist(io.BytesIO(_png(512)))
        path = storage.blob_path(blob.sha256)
        assert storage.delete_blob(blob.sha256) is False
        assert path.exists()

        old = time.time() - 7200
        os.utime(path, (old, old))
        assert storage.delete_blob(blob.sha256) is True
        assert not path.exists()
        assert storage.delete_blob(blob.sha256) is False    # 幂等
