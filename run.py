
import os

from app import create_app
from app.database import db
from app.database import models  # noqa: F401

app = create_app()


def initialize_database():
    with app.app_context():
        db.create_all()


if __name__ == "__main__":
    initialize_database()

    debug = os.getenv("APP_ENV", "development") == "development"

    app.run(
        host="127.0.0.1" if debug else "0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=debug,
    )
  
