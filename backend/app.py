"""Flask 应用工厂（§3.2 backend/app.py + Phase-2）。

create_app()：注册扩展 / CORS（含 expose_headers）/ 可观测性 / 蓝图 /
全局错误处理器与 JWT 回调，import 全部模型后 db.create_all()，并按
SEED_ON_STARTUP 决定是否幂等 seed。__main__ 起 5000 端口。
"""
from flask import Flask, jsonify
from flask_cors import CORS
from sqlalchemy import text

from config import Config
from extensions import db, jwt
from errors import register_error_handlers
from observability import init_observability
from services import llm


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
        # 【R-01】暴露 Phase-2 新增自定义响应头，跨域下浏览器 JS 方可读取。
        expose_headers=["X-Total-Count", "X-Request-Id"],
    )

    # —— 可观测性：结构化日志 + request-id + 访问日志（§2.5-1）——
    init_observability(app)

    # —— 全局错误处理器 + JWT loaders（§2.6 / R-03）——
    register_error_handlers(app, jwt)

    # —— 蓝图 ——
    from routes import register_blueprints
    register_blueprints(app)

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
        }
        return jsonify(payload), 200 if db_ok else 503

    # —— 建表 + （可选）seed ——
    with app.app_context():
        # 必须先 import 全部模型，表才会注册到 metadata（【R-06】）。
        import models  # noqa: F401
        from seed import seed_if_empty
        db.create_all()
        if app.config.get("SEED_ON_STARTUP", True):
            seed_if_empty()

    return app


app = create_app()


if __name__ == "__main__":
    # 关闭 reloader 避免 seed / create_all 重复执行两次进程。
    # threaded=True：单个（可能较慢的）LLM 请求阻塞期间不拖垮健康探针 / 并发请求
    # （real-agent-execution §3.8）；配合「改状态前调 LLM」的写锁收敛，并发写不再被阻塞。
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False, threaded=True)
