
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def init_database(app):
    app.config.setdefault(
        "SQLALCHEMY_TRACK_MODIFICATIONS", False
    )
    db.init_app(app)
    
