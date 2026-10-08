"""HTTP only: read the request, call src/db.py, answer as openapi.yaml says.
No SQL here (docs/architecture.md)."""

import os
from pathlib import Path

from flask import Blueprint, current_app, jsonify, send_file

from src import db

OPENAPI_PATH = Path(__file__).parent.parent / "openapi.yaml"

api = Blueprint("api", __name__)


@api.get("/health")
def health():
    if not db.ping(current_app.db):
        return jsonify(status="error", error="database unreachable"), 503

    return jsonify(
        status="ok",
        revision=os.getenv("APP_REVISION", "local"),
    )


@api.get("/openapi.yaml")
def openapi():
    # The contract lives beside the code; serve it so other teams can
    # read the one the running service actually promises.
    return send_file(OPENAPI_PATH, mimetype="application/yaml")