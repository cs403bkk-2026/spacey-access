"""In-memory stand-in for src/db.py, used when MOCK=1 (ARCH-01).

It follows the 0.2.0 contract in openapi.yaml exactly (the State x action
table), because spacey's tests are built against this mock. Real mode
(src/db.py) gets the same lifecycle in Phase 2.

Same function names and arguments as src/db.py, so src/api.py can call
either one. The difference: every function here returns (body, status),
because the contract has more answers than "found" / "not found"
(403 wrong code, 409 wrong state, 200 for a repeat).

Nothing is saved: a restart or POST /_mock/reset starts empty. The data
lives in one process, so the mock must run with a single gunicorn worker.
Never use it in production.
"""

import logging
import secrets
from datetime import datetime, timezone
from threading import Lock

from src.timeutil import now_iso

# One line per refusal, never with the access code (docs/logging.md).
log = logging.getLogger("access")

NOT_FOUND = ({"error": "access record not found"}, 404)

# The record fields the contract returns (AccessRecord), in its order.
RECORD_FIELDS = (
    "booking_id",
    "access_code",
    "status",
    "expires_at",
    "checked_in_at",
    "checked_out_at",
    "revoked_at",
    "expired_at",
)


class MockDB:
    """Holds the access records in a dict, keyed by booking_id."""

    def __init__(self):
        self.records = {}
        self.lock = Lock()  # gunicorn threads: one change at a time

    def reset(self):
        with self.lock:
            self.records.clear()


def ping(conn) -> bool:
    return True  # nothing to reach: the mock is always up


def _generate_access_code() -> str:
    return secrets.token_hex(4)  # 8 lowercase hex chars, like src/db.py


def _record(record):
    """The full AccessRecord, as every success returns it."""
    return {field: record[field] for field in RECORD_FIELDS}


def _ok(record):
    return _record(record), 200


def _conflict(action, booking_id, record, message):
    """409: nothing changes, the body says the current status, one log line."""
    log.warning(
        "access action=%s booking_id=%s outcome=conflict status=%s",
        action, booking_id, record["status"],
    )
    return {"error": message, "status": record["status"]}, 409


def _parse_time(value):
    """A datetime with an offset, or None if the text isn't ISO 8601 with one."""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else None


def _expire_if_overdue(record):
    """Time first: an available record past expires_at becomes expired."""
    if record["status"] != "available":
        return
    if _parse_time(record["expires_at"]) <= datetime.now(timezone.utc):
        record["status"] = "expired"
        record["expired_at"] = now_iso()


# --- The 6 access functions ---------------------------------------------------


def create_access(conn, booking_id, start_time, end_time):
    start, end = _parse_time(start_time), _parse_time(end_time)
    if start is None or end is None:
        return {"error": "start_time and end_time must be ISO 8601 with an offset"}, 400
    if end <= start:
        return {"error": "end_time must be after start_time"}, 400

    with conn.lock:
        existing = conn.records.get(booking_id)
        if existing is not None:
            return _ok(existing)  # any status, unchanged, even if the times differ

        record = {
            "booking_id": booking_id,
            "access_code": _generate_access_code(),
            "status": "available",
            "expires_at": end_time,
            "checked_in_at": None,
            "checked_out_at": None,
            "revoked_at": None,
            "expired_at": None,
        }
        conn.records[booking_id] = record
        return _record(record), 201


def read_access(conn, booking_id):
    with conn.lock:
        record = conn.records.get(booking_id)
        if record is None:
            return NOT_FOUND
        _expire_if_overdue(record)
        return _ok(record)


def revoke_access(conn, booking_id):
    with conn.lock:
        record = conn.records.get(booking_id)
        if record is None:
            return NOT_FOUND
        status = record["status"]
        if status == "available":
            record["status"] = "revoked"
            record["revoked_at"] = now_iso()
            return _ok(record)
        if status == "revoked":
            return _ok(record)  # repeat: same record
        if status == "used":
            return _conflict("revoke", booking_id, record, "access is used and cannot be revoked")
        return _conflict("revoke", booking_id, record, "access has expired and cannot be revoked")


def check_in(conn, booking_id, access_code):
    with conn.lock:
        record = conn.records.get(booking_id)
        if record is None:
            return NOT_FOUND
        if access_code != record["access_code"]:
            # Says nothing about the status; never log the code itself.
            log.warning("access action=check_in booking_id=%s outcome=wrong_code", booking_id)
            return {"error": "wrong access code"}, 403
        _expire_if_overdue(record)
        status = record["status"]
        if status == "available":
            record["status"] = "used"
            record["checked_in_at"] = now_iso()
            return _ok(record)
        if status == "used":
            return _ok(record)  # repeat: same record
        if status == "expired":
            return _conflict("check_in", booking_id, record, "access has expired")
        return _conflict("check_in", booking_id, record, "access is revoked")


def check_out(conn, booking_id):
    with conn.lock:
        record = conn.records.get(booking_id)
        if record is None:
            return NOT_FOUND
        status = record["status"]
        if status == "used":
            # Status stays used (no re-entry); the time is recorded once.
            if record["checked_out_at"] is None:
                record["checked_out_at"] = now_iso()
            return _ok(record)
        if status == "available":
            return _conflict("check_out", booking_id, record, "not checked in")
        if status == "expired":
            return _conflict("check_out", booking_id, record, "access has expired")
        return _conflict("check_out", booking_id, record, "access is revoked")


def expire_access(conn, booking_id):
    with conn.lock:
        record = conn.records.get(booking_id)
        if record is None:
            return NOT_FOUND
        _expire_if_overdue(record)
        status = record["status"]
        if status == "available":
            record["status"] = "expired"
            record["expired_at"] = now_iso()
            return _ok(record)
        if status == "expired":
            return _ok(record)  # repeat, also after Access's own time check
        if status == "used":
            return _conflict("expire", booking_id, record, "access is used and cannot expire")
        return _conflict("expire", booking_id, record, "access is revoked and cannot expire")
