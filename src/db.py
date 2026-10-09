from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

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


def create_access(conn, booking_id, start_time, end_time):
    code = _generate_access_code()
    row = conn.execute(
        """
        INSERT INTO access (booking_id, access_code, status, booked_start_time, booked_end_time, expires_at)
        VALUES (%s, %s, 'available', %s, %s, %s)
        RETURNING booking_id, access_code, status, expires_at
        """,
        (booking_id, code, start_time, end_time, end_time),
    ).fetchone()
    return dict(row)


def remove_access(conn, booking_id):
    row = conn.execute(
        """
        UPDATE access
        SET status = 'removed', removed_at = now()
        WHERE booking_id = %s
        RETURNING booking_id, status, removed_at
        """,
        (booking_id,),
    ).fetchone()
    return dict(row) if row else None


def expire_access(conn, booking_id):
    row = conn.execute(
        """
        UPDATE access
        SET status = 'expired'
        WHERE booking_id = %s
        RETURNING booking_id, status
        """,
        (booking_id,),
    ).fetchone()
    return dict(row) if row else None


def check_in(conn, booking_id, access_code):
    row = conn.execute(
        """
        UPDATE access
        SET status = 'used', checked_in_at = now()
        WHERE booking_id = %s AND access_code = %s AND status = 'available'
        RETURNING booking_id, status, checked_in_at
        """,
        (booking_id, access_code),
    ).fetchone()
    return dict(row) if row else None


def check_out(conn, booking_id):
    row = conn.execute(
        """
        UPDATE access
        SET status = 'available', checked_out_at = now()
        WHERE booking_id = %s AND status = 'used'
        RETURNING booking_id, status, checked_out_at
        """,
        (booking_id,),
    ).fetchone()
    return dict(row) if row else None