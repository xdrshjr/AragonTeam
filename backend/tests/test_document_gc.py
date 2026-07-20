"""孤儿 blob 回收用例（ticket-document-management §7.2）：孤儿识别、跳过 `.tmp/` 与
宽限窗口内的 blob（R4）、dry-run 不删、`--apply` 删、退出码。
"""
import io
import os
import time

from tools import gc_orphan_blobs


def _age(path, seconds=7200):
    """把文件 mtime 调老到宽限窗口之外。"""
    old = time.time() - seconds
    os.utime(path, (old, old))


def _make_orphan(app, payload=b"orphan bytes"):
    """造一个磁盘上有、`document_versions` 里无人引用的 blob。"""
    from services.documents import storage

    blob = storage.digest_and_persist(io.BytesIO(payload))
    return storage.blob_path(blob.sha256)


def test_scan_identifies_orphans_only(app, client, auth):
    from test_documents import upload

    live = upload(client, auth("pm"), title="活的").get_json()
    with app.app_context():
        from services.documents import storage

        live_path = storage.blob_path(live["current_version"]["sha256"])
        orphan = _make_orphan(app)
        _age(orphan)
        report = gc_orphan_blobs.scan()
        reapable = [p for p, _ in report["reapable"]]
        assert str(orphan) in reapable
        assert str(live_path) not in reapable
        assert report["referenced"] == 1


def test_gc_skips_tmp_and_recent_blobs(app):
    """【R4】`.part` 与刚落盘的孤儿在 `--apply` 后仍在；调老 mtime 后才被回收。"""
    with app.app_context():
        from services.documents import storage

        fresh = _make_orphan(app, b"just uploaded")
        tmp_dir = storage.upload_root() / storage.TMP_DIRNAME
        tmp_dir.mkdir(parents=True, exist_ok=True)
        part = tmp_dir / "inflight.part"
        part.write_bytes(b"half a file")
        _age(part)                           # 就算它很老，也绝不能删——别人正在写

        report, code = gc_orphan_blobs._run(dry_run=False)
        assert code == gc_orphan_blobs.EXIT_OK
        assert fresh.exists(), "宽限窗口内的孤儿不得被回收"
        assert part.exists(), "正在写入的临时文件不得被回收"
        assert report["orphan_in_grace"] == 1
        assert report["temp_files_skipped"] == 1
        assert report["deleted"] == 0

        _age(fresh)
        report, _ = gc_orphan_blobs._run(dry_run=False)
        assert not fresh.exists()
        assert report["deleted"] == 1
        assert part.exists()


def test_dry_run_deletes_nothing(app):
    with app.app_context():
        orphan = _make_orphan(app, b"dry run subject")
        _age(orphan)
        report, code = gc_orphan_blobs._run(dry_run=True)
        assert code == gc_orphan_blobs.EXIT_OK
        assert report["mode"] == "dry-run"
        assert report["orphan_reapable"] == 1
        assert report["deleted"] == 0
        assert orphan.exists()


def test_unrecognised_files_are_never_touched(app):
    """运维手工放进去的文件、备份、README 都不该被工具删。"""
    with app.app_context():
        from services.documents import storage

        stray = storage.upload_root() / "README.txt"
        stray.parent.mkdir(parents=True, exist_ok=True)
        stray.write_bytes(b"ops note")
        _age(stray)
        report, _ = gc_orphan_blobs._run(dry_run=False)
        assert stray.exists()
        assert report["unrecognised_files_skipped"] == 1


def test_report_reveals_what_it_skipped(app):
    """一个只说自己删了多少、不说自己跳过了多少的清理工具，会让人误以为清干净了。"""
    with app.app_context():
        _make_orphan(app, b"in grace")
        report, _ = gc_orphan_blobs._run(dry_run=True)
        text = gc_orphan_blobs._render(report, as_json=False)
        assert "宽限窗口内" in text
        assert "临时文件" in text


def test_missing_upload_dir_is_a_precondition_failure(tmp_path):
    code = gc_orphan_blobs.main(["--upload-dir", str(tmp_path / "nope")])
    assert code == gc_orphan_blobs.EXIT_PRECONDITION
