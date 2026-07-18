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
