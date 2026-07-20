"""孤儿 blob 离线回收 CLI（ticket-document-management §4.4）。

用法（在 backend/ 目录下执行，PowerShell / cmd / bash 通用）::

    python tools/gc_orphan_blobs.py                     # 默认 dry-run：只报告，不删文件
    python tools/gc_orphan_blobs.py --apply             # 真正删除
    python tools/gc_orphan_blobs.py --apply --json      # 机器可读报告
    python tools/gc_orphan_blobs.py --upload-dir D:/x/uploads

**为什么是离线 CLI 而不是 HTTP 端点**：与 `purge_demo_data.py` 同理——批量删文件
没有幂等语义、没有回滚入口，一个手滑的 curl 就能清掉整个文档库的磁盘副本。

**回收判据不是「磁盘上有、`document_versions` 里无人引用」这一条**（评审 R4）。
按那条字面判据，`UPLOAD_DIR/.tmp/<uuid>.part`——**其他进程正在写入的临时文件**——
恰好满足它，于是 `--apply` 会在并发上传时随机删掉别人写到一半的文件。本工具与在线
删除路径**共用同一个 `storage.is_reapable(path, now)`**，三条判据缺一不可：
不在 `.tmp/` 下、路径符合 `<2hex>/<2hex>/<64hex>` 的内容寻址形状、
mtime 早于 `now - BLOB_GRACE_SECONDS`。

报告中**必须**分别列出「无人引用但在宽限期内（本轮跳过）」与「本轮实际回收」两个
数字——一个只说自己删了多少、不说自己跳过了多少的清理工具，会让人误以为已经清干净了。

退出码沿用 purge_demo_data 约定：`0` 成功 / `1` 前置条件不满足 / `2` 跳过。
"""
import argparse
import json
import os
import sys
import time

EXIT_OK = 0
EXIT_PRECONDITION = 1
EXIT_SKIPPED = 2


def _parse_args(argv=None):
    """解析命令行参数。**此时尚未 import app**（顺序不可换，见 main 的 docstring）。"""
    parser = argparse.ArgumentParser(
        prog="gc_orphan_blobs",
        description="回收 UPLOAD_DIR 下已无版本记录引用的孤儿 blob（默认 dry-run）。")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只报告不删文件（默认行为）")
    mode.add_argument("--apply", action="store_true", help="真正删除")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="报告输出为 JSON")
    parser.add_argument("--database-url", default=None,
                        help="指定库 URI；缺省取 DATABASE_URL 或 config 默认值")
    parser.add_argument("--upload-dir", default=None,
                        help="指定 blob 根目录；缺省取 UPLOAD_DIR 或 config 默认值")
    return parser.parse_args(argv)


def _referenced_digests() -> set:
    """`document_versions` 中出现过的全部摘要（唯一的「仍被引用」判据）。

    走 `ix_docver_sha` 索引的 DISTINCT，不取回整行——一个只需要摘要集合的查询没有
    理由把 note / filename 一起搬回来。
    """
    from extensions import db
    from models.document import DocumentVersion

    rows = db.session.query(DocumentVersion.sha256).distinct().all()
    return {row[0] for row in rows if row[0]}


def scan(now: float = None) -> dict:
    """扫描 UPLOAD_DIR，把每个文件分到四个桶里之一。

    Returns:
        `{"referenced": n, "reapable": [(path, size)], "in_grace": [(path, size)],
          "skipped_shape": n, "tmp": n}`

    调用方（含用例）可以只做扫描不删除——这正是 dry-run 的实现方式，
    「报告」与「执行」共用同一次扫描，报告不可能与实际删除的东西不一致。
    """
    from services.documents import storage

    stamp = time.time() if now is None else now
    referenced = _referenced_digests()
    root = storage.upload_root()
    report = {"referenced": len(referenced), "reapable": [], "in_grace": [],
              "skipped_shape": 0, "tmp": 0, "root": str(root)}
    if not root.exists():
        return report

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            relative = path.resolve().relative_to(root.resolve())
        except (ValueError, OSError):        # pragma: no cover - 符号链接等异常路径
            continue
        if relative.parts and relative.parts[0] == storage.TMP_DIRNAME:
            report["tmp"] += 1
            continue
        digest = path.name
        if len(relative.parts) != 3 or len(digest) != 64:
            report["skipped_shape"] += 1
            continue
        if digest in referenced:
            continue                         # 仍被引用：不是孤儿
        try:
            size = path.stat().st_size
        except OSError:                      # pragma: no cover
            continue
        # 形状与 .tmp 已在上面判过，这里 is_reapable 只可能因宽限窗口而拒绝。
        bucket = "reapable" if storage.is_reapable(path, stamp) else "in_grace"
        report[bucket].append((str(path), size))
    return report


def _run(dry_run: bool) -> tuple:
    report = scan()
    reaped, freed, failed = 0, 0, 0
    if not dry_run:
        for path, size in report["reapable"]:
            try:
                os.remove(path)
                reaped += 1
                freed += size
            except OSError:
                failed += 1
    rendered = {
        "mode": "dry-run" if dry_run else "apply",
        "upload_dir": report["root"],
        "referenced_digests": report["referenced"],
        "orphan_reapable": len(report["reapable"]),
        "orphan_reapable_bytes": sum(size for _, size in report["reapable"]),
        # 【必须如实列出】只说删了多少、不说跳过了多少，会让人误以为已经清干净了。
        "orphan_in_grace": len(report["in_grace"]),
        "orphan_in_grace_bytes": sum(size for _, size in report["in_grace"]),
        "temp_files_skipped": report["tmp"],
        "unrecognised_files_skipped": report["skipped_shape"],
        "deleted": reaped,
        "freed_bytes": freed,
        "delete_failures": failed,
    }
    return rendered, EXIT_OK


def _render(report: dict, as_json: bool) -> str:
    if as_json:
        return json.dumps(report, ensure_ascii=False, indent=2)
    lines = [
        f"模式：{report['mode']}",
        f"blob 根目录：{report['upload_dir']}",
        f"仍被引用的摘要：{report['referenced_digests']}",
        f"可回收孤儿：{report['orphan_reapable']} 个 / "
        f"{report['orphan_reapable_bytes']} 字节",
        f"孤儿但仍在宽限窗口内（本轮跳过）：{report['orphan_in_grace']} 个 / "
        f"{report['orphan_in_grace_bytes']} 字节",
        f"正在写入的临时文件（跳过）：{report['temp_files_skipped']}",
        f"形状不符的文件（跳过，不属于本工具管辖）：{report['unrecognised_files_skipped']}",
    ]
    if report["mode"] == "apply":
        lines.append(f"实际删除：{report['deleted']} 个 / 释放 {report['freed_bytes']} 字节"
                     f"（失败 {report['delete_failures']} 个）")
    else:
        lines.append("（dry-run：未删除任何文件。确认无误后加 --apply。）")
    return "\n".join(lines)


def main(argv=None) -> int:
    """CLI 入口。**启动序列顺序不可换**（与 purge_demo_data 同理）。

    `backend/app.py` 有模块级 `app = create_app()`——只要 import 到它，Python 就会
    立刻对「默认 DATABASE_URL 指向的库」执行 create_all + seed。因此必须：
    先解析参数 → 把开关写进环境变量 → **此时才** import app。
    """
    args = _parse_args(argv)
    from config import Config

    url = args.database_url or os.environ.get("DATABASE_URL") \
        or Config.SQLALCHEMY_DATABASE_URI
    upload_dir = args.upload_dir or os.environ.get("UPLOAD_DIR") or Config.UPLOAD_DIR
    if not os.path.isdir(upload_dir):
        print(f"blob 根目录不存在：{upload_dir}", file=sys.stderr)
        return EXIT_PRECONDITION

    os.environ["DATABASE_URL"] = url                        # 保护模块级 create_app()
    os.environ["SEED_ON_STARTUP"] = "false"                 # 清理工具绝不顺手播种
    os.environ["RELEASE_STALE_LOCKS_ON_STARTUP"] = "false"  # 清理不夹带运维副作用
    from app import create_app                             # ← 必须在这之后 import

    gc_config = type("GcConfig", (Config,), {
        "SQLALCHEMY_DATABASE_URI": url,
        "UPLOAD_DIR": upload_dir,
        "SEED_ON_STARTUP": False,
        "RELEASE_STALE_LOCKS_ON_STARTUP": False,
    })
    flask_app = create_app(gc_config)
    try:
        with flask_app.app_context():
            report, code = _run(not args.apply)
            print(_render(report, args.as_json))
            return code
    finally:
        _release_engine(flask_app)


def _release_engine(flask_app) -> None:
    """释放连接池。Windows 上句柄不放会让调用方（含用例的 tmp_path）删不掉库文件。"""
    from extensions import db

    with flask_app.app_context():
        db.session.remove()
        db.engine.dispose()


if __name__ == "__main__":
    # 允许 `python tools/gc_orphan_blobs.py`：把 backend/ 放进 sys.path。
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.exit(main())
