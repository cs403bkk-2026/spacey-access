from flask import Flask

from src.api import api
from src.db import DATABASE_URL, get_connection


def create_app(database_url: str = DATABASE_URL) -> Flask:
    app = Flask(__name__)
    app.db = get_connection(database_url)
    app.register_blueprint(api)
    return app