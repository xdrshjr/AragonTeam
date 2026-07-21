"""蓝图注册（§3.2 backend/routes/__init__.py）。"""
from routes.auth import bp as auth_bp
from routes.users import bp as users_bp
from routes.agents import bp as agents_bp
from routes.projects import bp as projects_bp
from routes.requirements import bp as requirements_bp
from routes.bugs import bp as bugs_bp
from routes.board import bp as board_bp
from routes.stats import bp as stats_bp
from routes.comments import bp as comments_bp
from routes.notifications import bp as notifications_bp
from routes.me import bp as me_bp
from routes.search import bp as search_bp
from routes.documents import bp as documents_bp
from routes.ticket_documents import bp as ticket_documents_bp
from routes.settings import admin_settings_bp


def register_blueprints(app):
    app.register_blueprint(auth_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(agents_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(requirements_bp)
    app.register_blueprint(bugs_bp)
    app.register_blueprint(board_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(comments_bp)
    # —— Phase-3：通知中心 + 「我的工作」〔R3-02：me 蓝图独立前缀 /api/me〕——
    app.register_blueprint(notifications_bp)
    app.register_blueprint(me_bp)
    # —— global-search（Iter3）：跨需求+BUG 聚合搜索，独立前缀 /api/search ——
    app.register_blueprint(search_bp)
    # —— ticket-document-management：文档库 + 工单文档（全流程文档管理）——
    app.register_blueprint(documents_bp)
    app.register_blueprint(ticket_documents_bp)
    # —— self-service-registration：站点级设置（注册开关 / 邀请码 / 默认角色），全部 require_root ——
    app.register_blueprint(admin_settings_bp)
