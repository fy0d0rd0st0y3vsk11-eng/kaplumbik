
import secrets
from pathlib import Path

from flask import Flask

from app.core.config import settings
from app.database import init_database


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)

    if settings.app_env.lower() == "production" and not settings.secret_key:
        raise RuntimeError("Production ortamında SECRET_KEY zorunludur.")

    app.config["SECRET_KEY"] = settings.secret_key or secrets.token_hex(32)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = settings.app_env.lower() == "production"
    app.config["SQLALCHEMY_DATABASE_URI"] = (
        settings.database_url
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # SQLite URLs use Flask's instance directory for relative paths.
    # Ensure it exists on fresh deployments before opening the database.
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    if test_config:
        app.config.update(test_config)

    init_database(app)

    # Register all database models before create_all().
    from app.database import models  # noqa: F401
    from app.database import event_models  # noqa: F401
    from app.database import advanced_models  # noqa: F401
    from app.seri import models as streak_models  # noqa: F401
    from app.database import community_models  # noqa: F401

    with app.app_context():
        from app.database import db
        db.create_all()

    from app.dashboard import dashboard_bp
    from app.dashboard import routes as dashboard_routes
    from app.dashboard import advanced_routes  # noqa: F401

    dashboard_routes.oauth.init_app(app)
    app.register_blueprint(dashboard_bp)

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "service": "kaplumbik",
        }, 200

    return app
    
