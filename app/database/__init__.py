
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def init_database(app):
    """Initialize the shared database for the bot dashboard."""

    app.config.setdefault(
        "SQLALCHEMY_TRACK_MODIFICATIONS", False
    )

    db.init_app(app)

    with app.app_context():
        db.create_all()
      
