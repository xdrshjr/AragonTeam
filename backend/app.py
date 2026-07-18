"""Flask 应用工厂（§3.2 backend/app.py）。

create_app()：注册扩展 / CORS / 蓝图 / 全局错误处理器与 JWT 回调，
import 全部模型后 db.create_all() 并幂等 seed。
__main__ 起 5000 端口。
"""
from flask import Flask, jsonify
from flask_cors import CORS

from config import Config
from extensions import db, jwt
from errors import register_error_handlers


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
    )

    # —— 全局错误处理器 + JWT loaders（§2.6 / R-03）——
    register_error_handlers(app, jwt)

    # —— 蓝图 ——
    from routes import register_blueprints
    register_blueprints(app)

    # 健康检查（无需鉴权）。
    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok", "service": "aragonteam-backend"}), 200

    # —— 建表 + seed ——
    with app.app_context():
        # 必须先 import 全部模型，表才会注册到 metadata（【R-06】）。
        import models  # noqa: F401
        from seed import seed_if_empty
        db.create_all()
        seed_if_empty()

    return app


app = create_app()


if __name__ == "__main__":
    # 关闭 reloader 避免 seed / create_all 重复执行两次进程。
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
