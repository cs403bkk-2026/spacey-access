from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

from src.timeutil import iso, parse_time

# One line per refusal, never with the access code (docs/logging.md).
log = logging.getLogger("access")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://access:access@localhost:5434/access")


def get_connection(database_url: str = DATABASE_URL) -> psycopg.Connection:
    try:
        return psycopg.connect(database_url, row_factory=dict_row, autocommit=True)
    except psycopg.OperationalError:
        # A raw psycopg traceback is the first thing a new contributor sees
        # if Postgres isn't running yet - fail fast with a clear pointer.
        raise SystemExit(
            "Could not connect to the database. Check DATABASE_URL and database availability."
        ) from None


def ping(conn) -> bool:
    """True if the database answers. Used by GET /health."""
    try:
        conn.execute("SELECT 1")
        return True
    except psycopg.Error:
        return False


def _generate_access_code() -> str:
    return secrets.token_hex(4)  # 8 hex chars, e.g. "a3f9c21b"


# --- The 0.2.0 lifecycle (openapi.yaml, State x action table) -------------------
# Ported from src/mock_store.py (extract F2-F6): every function returns
# (body, status) like the mock, and tests/test_lifecycle_real.py runs the
# mock's whole lifecycle suite against this file.

RECORD = ("booking_id, access_code, status, expires_at, "
          "checked_in_at, checked_out_at, revoked_at, expired_at")
NOT_FOUND = ({"error": "access record not found"}, 404)


def _record(row):
    """The full AccessRecord, times in ISO 8601 (what every success returns)."""
    return {key: (iso(value) if isinstance(value, datetime) else value) for key, value in row.items()}


def _expire_if_overdue(conn, booking_id):
    """Time first: an available record past expires_at becomes expired."""
    conn.execute(
        "UPDATE access SET status = 'expired', expired_at = now() "
        "WHERE booking_id = %s AND status = 'available' AND expires_at <= now()",
        (booking_id,),
    )


def create_access(conn, booking_id, start_time, end_time):
    """Get-or-create: 201 with a new available record; 200 with the existing
    record unchanged (any status, even if the times differ)."""
    start, end = parse_time(start_time), parse_time(end_time)
    if start is None or end is None:
        return {"error": "start_time and end_time must be ISO 8601 with an offset"}, 400
    if end <= start:
        return {"error": "end_time must be after start_time"}, 400

    with conn.transaction():
        # ON CONFLICT DO NOTHING waits for a concurrent insert of the same
        # booking, so two creates at once give one record and one code.
        row = conn.execute(
            f"""
            INSERT INTO access (booking_id, access_code, status,
                                booked_start_time, booked_end_time, expires_at)
            VALUES (%s, %s, 'available', %s, %s, %s)
            ON CONFLICT (booking_id) DO NOTHING
            RETURNING {RECORD}
            """,
            (booking_id, _generate_access_code(), start, end, end),
        ).fetchone()
        if row is not None:
            return _record(row), 201
        row = conn.execute(f"SELECT {RECORD} FROM access WHERE booking_id = %s",
                           (booking_id,)).fetchone()
        return _record(row), 200


def read_access(conn, booking_id):
    with conn.transaction():
        _expire_if_overdue(conn, booking_id)
        row = conn.execute(f"SELECT {RECORD} FROM access WHERE booking_id = %s",
                           (booking_id,)).fetchone()
    return NOT_FOUND if row is None else (_record(row), 200)


def _locked(conn, booking_id):
    """The record, locked until the transaction ends (one change at a time)."""
    return conn.execute(f"SELECT {RECORD} FROM access WHERE booking_id = %s FOR UPDATE",
                        (booking_id,)).fetchone()


def _conflict(action, booking_id, row, message):
    """409: nothing changes, the body says the current status, one log line
    without the code (docs/logging.md)."""
    log.warning("access action=%s booking_id=%s outcome=conflict status=%s",
                action, booking_id, row["status"])
    return {"error": message, "status": row["status"]}, 409


def revoke_access(conn, booking_id):
    """available -> revoked; revoked again -> 200, same record; used or
    expired -> 409 (final states, SP-R12: never deleted)."""
    with conn.transaction():
        row = _locked(conn, booking_id)
        if row is None:
            return NOT_FOUND
        if row["status"] == "available":
            row = conn.execute(
                f"UPDATE access SET status = 'revoked', revoked_at = now() "
                f"WHERE booking_id = %s RETURNING {RECORD}", (booking_id,)).fetchone()
            return _record(row), 200
        if row["status"] == "revoked":
            return _record(row), 200
        if row["status"] == "used":
            return _conflict("revoke", booking_id, row, "access is used and cannot be revoked")
        return _conflict("revoke", booking_id, row, "access has expired and cannot be revoked")


def check_in(conn, booking_id, access_code):
    """Order: unknown 404 -> wrong code 403 (says nothing about the status) ->
    time check -> available -> used; used again -> 200 same; else 409."""
    with conn.transaction():
        row = _locked(conn, booking_id)
        if row is None:
            return NOT_FOUND
        if access_code != row["access_code"]:
            log.warning("access action=check_in booking_id=%s outcome=wrong_code", booking_id)
            return {"error": "wrong access code"}, 403
        _expire_if_overdue(conn, booking_id)
        row = _locked(conn, booking_id)
        if row["status"] == "available":
            row = conn.execute(
                f"UPDATE access SET status = 'used', checked_in_at = now() "
                f"WHERE booking_id = %s RETURNING {RECORD}", (booking_id,)).fetchone()
            return _record(row), 200
        if row["status"] == "used":
            return _record(row), 200
        if row["status"] == "expired":
            return _conflict("check_in", booking_id, row, "access has expired")
        return _conflict("check_in", booking_id, row, "access is revoked")


def check_out(conn, booking_id):
    """used -> stays used, checked_out_at recorded once (no re-entry);
    available/expired/revoked -> 409."""
    with conn.transaction():
        row = _locked(conn, booking_id)
        if row is None:
            return NOT_FOUND
        if row["status"] == "used":
            row = conn.execute(
                f"UPDATE access SET checked_out_at = coalesce(checked_out_at, now()) "
                f"WHERE booking_id = %s RETURNING {RECORD}", (booking_id,)).fetchone()
            return _record(row), 200
        if row["status"] == "available":
            return _conflict("check_out", booking_id, row, "not checked in")
        if row["status"] == "expired":
            return _conflict("check_out", booking_id, row, "access has expired")
        return _conflict("check_out", booking_id, row, "access is revoked")


def expire_access(conn, booking_id):
    """available -> expired; expired again (also after the time check) -> 200
    same; used/revoked -> 409."""
    with conn.transaction():
        row = _locked(conn, booking_id)
        if row is None:
            return NOT_FOUND
        _expire_if_overdue(conn, booking_id)
        row = _locked(conn, booking_id)
        if row["status"] == "available":
            row = conn.execute(
                f"UPDATE access SET status = 'expired', expired_at = now() "
                f"WHERE booking_id = %s RETURNING {RECORD}", (booking_id,)).fetchone()
            return _record(row), 200
        if row["status"] == "expired":
            return _record(row), 200
        if row["status"] == "used":
            return _conflict("expire", booking_id, row, "access is used and cannot expire")
        return _conflict("expire", booking_id, row, "access is revoked and cannot expire")
