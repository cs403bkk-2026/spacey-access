import os

from flask import Flask

from src import db, mock_store
from src.api import api, mock_api
from src.db import DATABASE_URL, get_connection


def create_app(database_url: str = DATABASE_URL) -> Flask:
    app = Flask(__name__)

    if os.getenv("MOCK") == "1":
        # The mock must never sit next to a real database by accident.
        if os.getenv("DATABASE_URL"):
            raise SystemExit(
                "MOCK=1 and DATABASE_URL are both set: the mock never uses a database. "
                "Unset one of them."
            )
        # In-memory data lives in one process: run the mock with ONE gunicorn worker.
        app.config["MODE"] = "mock"
        app.store = mock_store
        app.db = mock_store.MockDB()
        app.register_blueprint(mock_api)
    else:
        app.config["MODE"] = "real"
        app.store = db
        app.db = get_connection(database_url)

    app.register_blueprint(api)
    return app
