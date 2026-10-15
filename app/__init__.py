
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

    # Import models so SQLAlchemy can register their tables.
    from app.database import models  # noqa: F401

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "service": "kaplumbik",
        }, 200

    return app
  
