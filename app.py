import os
from pathlib import Path

import psycopg
from flask import Flask, jsonify, send_file

from src.db import DATABASE_URL, get_connection

OPENAPI_PATH = Path(__file__).parent / "openapi.yaml"


def create_app(database_url: str = DATABASE_URL) -> Flask:
    app = Flask(__name__)
    app.db = get_connection(database_url)

    @app.get("/health")
    def health():
        try:
            with app.db.cursor() as cur:
                cur.execute("SELECT 1")
        except psycopg.Error:
            return jsonify(status="error", error="database unreachable"), 503

        return jsonify(
            status="ok",
            revision=os.getenv("APP_REVISION", "local"),
        )

    @app.get("/openapi.yaml")
    def openapi():
        # The contract lives beside the code; serve it so other teams can
        # read the one the running service actually promises.
        return send_file(OPENAPI_PATH, mimetype="application/yaml")

    return app
