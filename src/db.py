import os

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


# --- Access operations (moved here from src/access.py, ACC-03) ------------

def issue_access_code(cur, booking_id, eligible: bool):
    # TODO: spacey-access#2
    # eligible flag comes from Purchase — do not read bookings table here
    raise NotImplementedError


def check_in(cur, booking_id, access_code):
    # TODO: spacey-access#1
    # SP-R15: code match → not removed → not expired → within interval → available
    raise NotImplementedError


def check_out(cur, booking_id, access_code):
    # TODO: spacey-access#1
    # SP-R16: used → available (re-entry allowed)
    raise NotImplementedError


def remove_access(cur, booking_id):
    # TODO: spacey-access#1
    # SP-R12: record is never deleted, only marked removed
    # SP-R13: does not affect payments
    raise NotImplementedError


def expire_access(cur, booking_id):
    # TODO: spacey-access#1
    # SP-R17: lazy expiry — called on touch, not on a schedule
    raise NotImplementedError
