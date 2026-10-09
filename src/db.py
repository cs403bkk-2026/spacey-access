import os
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://access:access@localhost:5434/access"
)


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
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        return True
    except psycopg.Error:
        return False


# --- Access operations -----------------------------------------------------
# Each function is called by exactly one network function in src/api.py.
# DUMMY: they return fixed answers shaped as openapi.yaml says and don't touch
# the database yet. The real SQL (ACC-07 to ACC-09) replaces the bodies only.

DUMMY_ACCESS_CODE = "00000000"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_access(conn, booking_id, start_time, end_time):
    """Purchase -> Access: new access record for a paid booking."""
    return {
        "booking_id": booking_id,
        "access_code": DUMMY_ACCESS_CODE,
        "status": "available",
        "expires_at": end_time,
    }


def remove_access(conn, booking_id):
    """Purchase -> Access: the booking was cancelled. The record is kept (SP-R12)."""
    return {"booking_id": booking_id, "status": "removed", "removed_at": _now()}


def expire_access(conn, booking_id):
    """Purchase -> Access: the booking has ended by Purchase's clock."""
    return {"booking_id": booking_id, "status": "expired"}


def check_in(conn, booking_id, access_code):
    """Frontend -> Access: the member presents the access code."""
    return {"booking_id": booking_id, "status": "used", "checked_in_at": _now()}


def check_out(conn, booking_id):
    """Frontend -> Access: the member leaves; they may check in again until expiry."""
    return {"booking_id": booking_id, "status": "available", "checked_out_at": _now()}
