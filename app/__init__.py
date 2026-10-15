
from flask import Flask

from app.core.config import settings
from app.database import init_database


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)

    app.config["SECRET_KEY"] = settings.secret_key
    app.config["SQLALCHEMY_DATABASE_URI"] = (
        settings.database_url
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    if test_config:
        app.config.update(test_config)

    init_database(app)

    # Register all database models before create_all().
    from app.database import models  # noqa: F401
    from app.database import event_models  # noqa: F401

    with app.app_context():
        from app.database import db
        db.create_all()

    from app.dashboard import dashboard_bp
    from app.dashboard import routes  # noqa: F401

    app.register_blueprint(dashboard_bp)

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "service": "kaplumbik",
        }, 200

    return app
    
