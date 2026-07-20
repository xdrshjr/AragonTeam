"""回收站过期清理 CLI（document-lifecycle-depth §4.8）。

用法（在 backend/ 目录下执行，PowerShell / cmd / bash 通用）::

    python tools/purge_trash.py                  # 默认 dry-run：只列出超期文档，不改任何东西
    python tools/purge_trash.py --days 7         # 覆盖 DOC_TRASH_RETENTION_DAYS
    python tools/purge_trash.py --apply          # 真删（行 + 释放的 blob）
    python tools/purge_trash.py --apply --json   # 机器可读报告

**为什么不自动调度**：本项目没有调度器；引入定时任务意味着引入一个能在无人值守时
**不可逆删除用户数据**的组件，那需要单独一轮来讨论它的可观测性与熔断，不该作为附赠品。
与 `gc_orphan_blobs.py` / `purge_demo_data.py` 一致：不可逆操作由人按下。

**逐个文档各自 try/except + 逐个 commit**：一份文档清理失败（例如 blob 权限问题、
或本工具跑在活动库上时撞到 `database is locked`）只记进 `skipped` 并继续，不让整批停摆。

> **为什么必须逐个 commit 而不是攒到最后**：`db.session` 只有一个事务，循环里任何一次
> `rollback()` 都会把**本批已经处理过的全部文档**一起回滚。若此时摘要已经并进待回收集合，
> 随后的 `reap()` 就会删掉这些「已经复活」的文档的物理文件——留下一批行还在、下载恒 410
> 的空壳，且版本历史不可恢复（这些 blob 按定义已过保留期，宽限窗口救不了）。
> 故：**摘要只在 commit 成功之后才并入 `orphans`**。这条在 dry-run 下看不出来
> （dry-run 全程回滚且从不 reap），只有 `--apply` 会踩到——
> `test_purge_trash_cli_isolates_a_failing_document` 钉死它。

**彻底删除走 `trash.purge(document, actor=("system", None))`**，与 HTTP 的 `?purge=1`
**完全同一个入口**：它自包含地先解绑再删行。回收站里的文档「仍有绑定」是常态（软删
刻意不解绑），把 detach 留在调用方就会在第一份带绑定的过期文档上撞外键（评审 V-02）。

退出码：`0` 正常 / `2` 前置条件失败（如 UPLOAD_DIR 不存在）。
"""
import argparse
import json
import os
import sys

EXIT_OK = 0
EXIT_PRECONDITION = 2


def _parse_args(argv=None):
    """解析命令行参数。**此时尚未 import app**（顺序不可换，见 main 的 docstring）。"""
    parser = argparse.ArgumentParser(
        prog="purge_trash",
        description="彻底删除回收站中超过保留期的文档（默认 dry-run）。")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只报告不删（默认行为）")
    mode.add_argument("--apply", action="store_true", help="真正删除")
    parser.add_argument("--days", type=int, default=None,
                        help="覆盖保留期天数；缺省取 DOC_TRASH_RETENTION_DAYS")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="报告输出为 JSON")
    parser.add_argument("--database-url", default=None,
                        help="指定库 URI；缺省取 DATABASE_URL 或 config 默认值")
    parser.add_argument("--upload-dir", default=None,
                        help="指定 blob 根目录；缺省取 UPLOAD_DIR 或 config 默认值")
    return parser.parse_args(argv)


def run(days: int, dry_run: bool) -> dict:
    """扫描并（在 `--apply` 时）清理。返回报告结构。

    Args:
        days: 保留天数。
        dry_run: 为真时**绝不写库**（整段最后 rollback），报告与实际会删的东西一致。

    Returns:
        `{mode, retention_days, scanned, expired, deleted, blobs_reaped, skipped}`。
    """
    from extensions import db
    from models.document import Document
    from services.documents import service, trash  # noqa: F401 —— Document 供 session.get

    report = {
        "mode": "dry-run" if dry_run else "apply",
        "retention_days": days,
        "scanned": Document.query.filter(trash.is_deleted()).count(),
        "expired": 0,
        "deleted": [],
        "blobs_reaped": 0,
        "skipped": [],
    }
    expired = trash.expired_query(days).all()
    report["expired"] = len(expired)
    # 先把展示标签取出来：`rollback()` 会让 ORM 实例过期，之后再读 `.title` 就是一次
    # 重新查询（对已删掉的行则直接炸）。
    targets = [(document.id, document.title) for document in expired]

    orphans: set = set()
    for document_id, title in targets:
        label = {"id": document_id, "title": title}
        try:
            document = db.session.get(Document, document_id)
            if document is None:            # 并发下别人已经删了它
                report["skipped"].append({**label, "reason": "already gone"})
                continue
            digests = trash.purge(document, ("system", None))
            if dry_run:
                db.session.rollback()       # 演练：立刻回滚，绝不写库
                report["deleted"].append(label)
                continue
            # 【逐个提交，不是批量提交——这一行是数据安全的关键】
            # 若攒到循环之后再一次性 commit，那么中途任何一次 `rollback()` 都会把**本批
            # 已经处理过的全部文档**一起回滚（session 只有一个事务），而它们的摘要早已
            # 并进 `orphans`——随后的 `reap()` 就会删掉这些「已经复活」的文档的物理文件，
            # 留下一批行还在、下载恒 410 的空壳。摘要**只在 commit 成功之后**才并入。
            db.session.commit()
            orphans |= digests
            report["deleted"].append(label)
        except Exception as exc:            # noqa: BLE001 —— 逐个隔离，一份失败不停批
            db.session.rollback()
            report["skipped"].append({**label, "reason": str(exc)})

    if dry_run:
        return report
    # 【§2.2】物理回收恒在 commit **之后**；`delete_blob` 自带宽限窗口判定，
    # 刚落盘的 blob 不会被立刻删掉——这是正确的，不是失败。
    report["blobs_reaped"] = len(orphans)
    service.reap(orphans)
    return report


def _render(report: dict, as_json: bool) -> str:
    if as_json:
        return json.dumps(report, ensure_ascii=False, indent=2)
    lines = [
        f"模式：{report['mode']}",
        f"保留期：{report['retention_days']} 天",
        f"回收站中的文档：{report['scanned']}",
        f"已超期：{report['expired']}",
    ]
    for row in report["deleted"]:
        lines.append(f"  - 彻底删除 #{row['id']} {row['title']}")
    for row in report["skipped"]:
        lines.append(f"  ! 跳过 #{row['id']} {row['title']}：{row['reason']}")
    if report["mode"] == "apply":
        lines.append(f"实际删除：{len(report['deleted'])} 份 / "
                     f"提交回收的 blob 摘要：{report['blobs_reaped']}"
                     f"（跳过 {len(report['skipped'])} 份）")
    else:
        lines.append("（dry-run：未删除任何东西。确认无误后加 --apply。）")
    return "\n".join(lines)


def main(argv=None) -> int:
    """CLI 入口。**启动序列顺序不可换**（与 gc_orphan_blobs 同理）。

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
    days = args.days if args.days is not None else Config.DOC_TRASH_RETENTION_DAYS
    if days < 0:
        print("--days 不能为负数", file=sys.stderr)
        return EXIT_PRECONDITION

    os.environ["DATABASE_URL"] = url                        # 保护模块级 create_app()
    os.environ["SEED_ON_STARTUP"] = "false"                 # 清理工具绝不顺手播种
    os.environ["RELEASE_STALE_LOCKS_ON_STARTUP"] = "false"  # 清理不夹带运维副作用
    from app import create_app                              # ← 必须在这之后 import

    purge_config = type("PurgeTrashConfig", (Config,), {
        "SQLALCHEMY_DATABASE_URI": url,
        "UPLOAD_DIR": upload_dir,
        "SEED_ON_STARTUP": False,
        "RELEASE_STALE_LOCKS_ON_STARTUP": False,
    })
    flask_app = create_app(purge_config)
    try:
        with flask_app.app_context():
            report = run(days, not args.apply)
            print(_render(report, args.as_json))
            return EXIT_OK
    finally:
        _release_engine(flask_app)


def _release_engine(flask_app) -> None:
    """释放连接池。Windows 上句柄不放会让调用方（含用例的 tmp_path）删不掉库文件。"""
    from extensions import db

    with flask_app.app_context():
        db.session.remove()
        db.engine.dispose()


if __name__ == "__main__":
    # 允许 `python tools/purge_trash.py`：把 backend/ 放进 sys.path。
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.exit(main())
