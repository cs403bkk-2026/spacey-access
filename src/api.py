"""HTTP only: read the request, call src/db.py, answer as openapi.yaml says.
No SQL here (docs/architecture.md)."""

import os
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_file

from src import db

OPENAPI_PATH = Path(__file__).parent.parent / "openapi.yaml"

api = Blueprint("api", __name__)


def _body(*required):
    """The JSON body, or None if a required field is missing."""
    body = request.get_json(silent=True) or {}
    if any(body.get(field) in (None, "") for field in required):
        return None
    return body


def _missing(*fields):
    return jsonify(error=f"{', '.join(fields)} required"), 400


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


# --- Purchase -> Access --------------------------------------------------------


@api.post("/bookings/<int:booking_id>/access")
def purchase_create_access(booking_id):
    body = _body("start_time", "end_time")
    if body is None:
        return _missing("start_time", "end_time")
    return jsonify(db.create_access(current_app.db, booking_id, body["start_time"], body["end_time"])), 201


@api.post("/bookings/<int:booking_id>/access/remove")
def purchase_remove_access(booking_id):
    result = db.remove_access(current_app.db, booking_id)
    if result is None:
        return jsonify(error="access record not found"), 404
    return jsonify(result), 200


@api.post("/bookings/<int:booking_id>/access/expire")
def purchase_expire_access(booking_id):
    result = db.expire_access(current_app.db, booking_id)
    if result is None:
        return jsonify(error="access record not found"), 404
    return jsonify(result), 200


@api.post("/bookings/<int:booking_id>/check-in")
def frontend_check_in(booking_id):
    body = _body("access_code")
    if body is None:
        return _missing("access_code")
    result = db.check_in(current_app.db, booking_id, body["access_code"])
    if result is None:
        return jsonify(error="access record not found or code invalid"), 404
    return jsonify(result), 200


@api.post("/bookings/<int:booking_id>/check-out")
def frontend_check_out(booking_id):
    result = db.check_out(current_app.db, booking_id)
    if result is None:
        return jsonify(error="access record not found or not checked in"), 404
    return jsonify(result), 200