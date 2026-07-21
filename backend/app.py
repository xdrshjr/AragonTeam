"""Flask 应用工厂（§3.2 backend/app.py + Phase-2）。

create_app()：注册扩展 / CORS（含 expose_headers）/ 可观测性 / 蓝图 /
全局错误处理器与 JWT 回调，import 全部模型后 db.create_all()，并按
SEED_ON_STARTUP 决定是否幂等 seed。__main__ 起 5000 端口。
"""
import os

from flask import Flask, jsonify
from flask_cors import CORS
from sqlalchemy import text
from werkzeug.routing import IntegerConverter

from config import Config
from extensions import db, jwt
from errors import register_error_handlers
from observability import init_observability
from services import doc_policy, llm


# SQLite / 多数 RDBMS 的 INTEGER 上限（64 位有符号）。超出即不可能命中任何主键。
MAX_DB_INT = 2 ** 63 - 1

# `/api/health` 的 storage 块在缓存缺失时的兜底形状（字段齐全、类型稳定，
# 前端与探针无需写分支）。正常启动恒被 create_app 覆盖为真实自省结果。
_UNKNOWN_STORAGE = {
    "persistent": False, "journal_mode": "unknown",
    "synchronous": "unknown", "foreign_keys": None,
}


class BoundedIntConverter(IntegerConverter):
    """给 `<int:…>` 加 64 位上界：超界值不匹配路由 → 404，
    而非进 db.session.get 触 OverflowError → 500（scale-and-project-scope §2.6①-A）。

    仅通过构造参数固定 max，无需覆写任何方法——越界判定由父类 NumberConverter 完成。
    """

    def __init__(self, url_map, *args, **kwargs):
        kwargs.setdefault("max", MAX_DB_INT)
        super().__init__(url_map, *args, **kwargs)


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # —— 扩展 ——
    db.init_app(app)
    jwt.init_app(app)
    CORS(
        app,
        resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}},
        supports_credentials=True,
        # 【R-01】暴露自定义响应头，跨域下浏览器 JS 方可读取。
        # 【ticket-document-management §3.2 / 评审 R17】这是**完整值**，不是「在别处追加」：
        # 若被实现成替换，前端 listFetcher 读不到 X-Total-Count，全站分页当场失效。
        expose_headers=["X-Total-Count", "X-Request-Id", "Content-Disposition"],
    )

    # —— 文档存储目录（ticket-document-management §3.2 / 评审 R14）——
    # 失败**只记 warning 不阻断启动**（与 extensions.py 处理 WAL 不可用时「降级但不阻断」
    # 的取向一致）：只读挂载不该让登录、看板、Agent 一起起不来；上传/下载端点届时返 503。
    upload_dir = app.config.get("UPLOAD_DIR")
    if upload_dir:
        try:
            os.makedirs(upload_dir, exist_ok=True)
        except OSError as exc:
            app.logger.warning("cannot create UPLOAD_DIR %s: %s", upload_dir, exc)
    # 阈值关系写错了应当立刻起不来，而不是等着某天有人发现文档被吃掉了半截（§2.6）。
    doc_policy.assert_thresholds(app.config)
    # 同理：把 md 从白名单里摘掉却留着模板 / Agent 归档，应当起不来而不是在用户点
    # 「用模板新建」时抛一个语义不明的 500（document-lifecycle-depth §2.3 C-1）。
    doc_policy.assert_text_document_extension(app.config)

    # —— 可观测性：结构化日志 + request-id + 访问日志（§2.5-1）——
    init_observability(app)

    # —— 全局错误处理器 + JWT loaders（§2.6 / R-03）——
    register_error_handlers(app, jwt)

    # 【§2.6①-A】覆盖全局 int 转换器，必须在注册蓝图**之前**——已编译的规则不会采用新转换器。
    app.url_map.converters["int"] = BoundedIntConverter

    # —— 蓝图 ——
    from routes import register_blueprints
    register_blueprints(app)

    # —— 全局闸门：带 must_change_password 标记的人在改掉口令之前寸步难行 ——
    # 【account-security-and-governance §2.2 B-3】这不是前端的善意提示，是服务端的硬约束。
    from services import auth_helpers
    auth_helpers.install_password_gate(app)

    # 健康检查（无需鉴权）。Phase-2 §2.5-6：附 DB 探活，供部署探针。
    @app.get("/api/health")
    def health():
        db_ok = True
        try:
            db.session.execute(text("SELECT 1"))
        except Exception:  # pragma: no cover - 探活失败路径
            db_ok = False
        payload = {
            "status": "ok" if db_ok else "error",
            "service": "aragonteam-backend",
            "db": "ok" if db_ok else "error",
            # real-agent-execution §5.1：只读 additive 块，反映 Agent 真实执行是否启用；
            # 从不回传密钥。未配置时 {enabled:false, provider:"none", model:null}。
            "llm": llm.describe(),
            # data-persistence §4.1：只读 additive 块，回答「数据存得住吗、真实生效的
            # 落盘参数是什么」。**有意不含 path**——本端点无需鉴权，回传服务器文件
            # 系统路径是无谓的信息泄露。值在启动期读一次并缓存，请求路径零额外 PRAGMA。
            "storage": app.config.get("STORAGE_INFO", _UNKNOWN_STORAGE),
        }
        return jsonify(payload), 200 if db_ok else 503

    # —— 建表 + （可选）seed ——
    with app.app_context():
        # 必须先 import 全部模型，表才会注册到 metadata（【R-06】）。
        import models  # noqa: F401
        from seed import seed_if_empty
        from services import persistence, schema_sync
        db.create_all()
        # 【lifecycle-and-governance §2.3】create_all 不给已存在的表加列；存量
        # aragon.db 缺少本轮新增的列时，每一次查询都会 no such column → 500。
        applied = schema_sync.sync_additive_columns(db.engine)
        if applied:
            app.logger.info("schema_sync applied: %s", ", ".join(applied))
        # 【data-persistence §2.1】顺序不可换：先把库的事实写进日志与缓存，再自愈软锁，
        # 最后才 seed——seed 依赖前两步已把库结构与 Agent 状态摆正。
        persistence.log_storage_summary(app)
        app.config["STORAGE_INFO"] = persistence.collect_storage_info(app, db.session)
        if app.config.get("RELEASE_STALE_LOCKS_ON_STARTUP", True):
            released = persistence.release_stale_agent_locks(db.session)
            if released:
                app.logger.info("released stale agent locks: %s", ", ".join(released))
        if app.config.get("SEED_ON_STARTUP", True):
            seed_if_empty()
        # 【self-service-registration §2.1 A-3】**必须排在 seed 之后**：seed 的幂等判据是
        # `User.query.count() == 0`，先建根管理员会让全新库上 users 恒非空，示例项目 /
        # 需求 / BUG / 评论一行都不写入，「首次启动开箱有内容」当场失效（§7 R-4）。
        # 放在 seed 之后，全新库的时序是：seed 建出 admin → bootstrap 认领同名账号 →
        # 只打 is_root 标 → 默认配置下与本轮之前的行为逐字相同。
        if app.config.get("ROOT_ADMIN_BOOTSTRAP", True):
            from services import bootstrap

            result = bootstrap.ensure_root_admin(app)
            app.logger.info("root admin ensured: %s (%s)",
                            result["username"], result["action"])

    return app


app = create_app()


if __name__ == "__main__":
    # 关闭 reloader 避免 seed / create_all 重复执行两次进程。
    # threaded=True：单个（可能较慢的）LLM 请求阻塞期间不拖垮健康探针 / 并发请求
    # （real-agent-execution §3.8）；配合「改状态前调 LLM」的写锁收敛，并发写不再被阻塞。
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False, threaded=True)
