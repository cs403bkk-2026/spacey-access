"""HTTP only: read the request, call src/db.py, answer as openapi.yaml says.
No SQL here (docs/architecture.md)."""

import hmac
import os
from functools import wraps
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_file

from src import db

OPENAPI_PATH = Path(__file__).parent.parent / "openapi.yaml"

api = Blueprint("api", __name__)
# Only registered when MOCK=1 (see app.py): routes that exist for testing only.
mock_api = Blueprint("mock_api", __name__)


def require_service_token(view):
    """All 6 access calls must carry `Authorization: Bearer <SERVICE_TOKEN>`:
    spacey is their only caller (Frontend and Purchase go through it).
    Checked before anything else, so a bad token is 401 even on a bad body.
    If SERVICE_TOKEN is not set the call is refused, never let through."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        expected = os.getenv("SERVICE_TOKEN", "")
        sent = request.headers.get("Authorization", "").removeprefix("Bearer ")
        # Bytes, because compare_digest raises on non-ASCII str: a header like
        # "Bearer tëst" must be a 401, not a 500.
        if not expected or not hmac.compare_digest(sent.encode(), expected.encode()):
            return jsonify(error="invalid or missing service token"), 401
        return view(*args, **kwargs)

    return wrapper


def _body(*required):
    """The JSON body, or None if a required field is missing."""
    body = request.get_json(silent=True) or {}
    if any(body.get(field) in (None, "") for field in required):
        return None
    return body


def _missing(*fields):
    return jsonify(error=f"{', '.join(fields)} required"), 400


def _answer(result, not_found, success=200):
    """Turn what the store returned into a response.

    src/db.py returns a record, or None when nothing matched (-> 404).
    src/mock_store.py (MOCK=1) already returns (body, status), because it
    follows the full 0.2.0 lifecycle: 403, 409 and repeats as 200.
    """
    if isinstance(result, tuple):
        body, status = result
        return jsonify(body), status
    if result is None:
        return jsonify(error=not_found), 404
    return jsonify(result), success


@api.get("/health")
def health():
    if not current_app.store.ping(current_app.db):
        return jsonify(status="error", error="database unreachable"), 503

    return jsonify(
        status="ok",
        mode=current_app.config["MODE"],
        revision=os.getenv("APP_REVISION", "local"),
    )


@api.get("/openapi.yaml")
def openapi():
    # The contract lives beside the code; serve it so other teams can
    # read the one the running service actually promises.
    return send_file(OPENAPI_PATH, mimetype="application/yaml")


# --- The 6 access functions: spacey -> Access, each with the service token -----


@api.post("/bookings/<int:booking_id>/access")
@require_service_token
def create_access(booking_id):
    body = _body("start_time", "end_time")
    if body is None:
        return _missing("start_time", "end_time")
    result = current_app.store.create_access(current_app.db, booking_id, body["start_time"], body["end_time"])
    return _answer(result, "access record not found", success=201)


@api.get("/bookings/<int:booking_id>/access")
@require_service_token
def read_access(booking_id):
    result = current_app.store.read_access(current_app.db, booking_id)
    return _answer(result, "access record not found")


@api.post("/bookings/<int:booking_id>/access/revoke")
@require_service_token
def revoke_access(booking_id):
    result = current_app.store.revoke_access(current_app.db, booking_id)
    return _answer(result, "access record not found")


@api.post("/bookings/<int:booking_id>/check-in")
@require_service_token
def check_in(booking_id):
    body = _body("access_code")
    if body is None:
        return _missing("access_code")
    result = current_app.store.check_in(current_app.db, booking_id, body["access_code"])
    return _answer(result, "access record not found or code invalid")


@api.post("/bookings/<int:booking_id>/check-out")
@require_service_token
def check_out(booking_id):
    result = current_app.store.check_out(current_app.db, booking_id)
    return _answer(result, "access record not found or not checked in")


@api.post("/bookings/<int:booking_id>/access/expire")
@require_service_token
def expire_access(booking_id):
    result = current_app.store.expire_access(current_app.db, booking_id)
    return _answer(result, "access record not found")


# --- Mock only (MOCK=1) ---------------------------------------------------------


@mock_api.post("/_mock/reset")
@require_service_token
def mock_reset():
    """Empty the in-memory store, so each test or demo starts clean."""
    current_app.db.reset()
    return jsonify(status="reset"), 200
