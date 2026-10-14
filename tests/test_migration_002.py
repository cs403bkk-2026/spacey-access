"""Migration 002 (ARCH-02): status `removed` becomes `revoked`, `removed_at` becomes
`revoked_at`, and `expired_at` is added. Each test builds the 001 table in its own
schema, inside a transaction that is rolled back, so the test database is left as
it was, even one that already has 002 applied."""

from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from src.db import DATABASE_URL

MIGRATIONS = Path(__file__).parent.parent / "migrations"
MIGRATION_001 = (MIGRATIONS / "001_create_access_table.sql").read_text()
MIGRATION_002 = (MIGRATIONS / "002_revoke_and_expiry.sql").read_text()

REMOVED_AT = datetime(2030, 1, 1, 10, 30, tzinfo=timezone.utc)


@pytest.fixture()
def cur():
    """A cursor on a new 001 table: the schema before 0.2.0."""
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA migration_002_test")
            cur.execute("SET LOCAL search_path TO migration_002_test")
            cur.execute(MIGRATION_001)
            yield cur
        conn.rollback()


def add(cur, booking_id, status):
    cur.execute(
        "INSERT INTO access (booking_id, access_code, status) VALUES (%s, %s, %s)",
        (booking_id, f"code{booking_id}", status),
    )


def add_removed(cur, booking_id):
    """A row cancelled before 0.2.0, as remove_access or the data copy left it."""
    cur.execute(
        "INSERT INTO access (booking_id, access_code, status, removed_at) "
        "VALUES (%s, %s, 'removed', %s)",
        (booking_id, f"code{booking_id}", REMOVED_AT),
    )


def columns(cur):
    cur.execute(
        "SELECT attname FROM pg_attribute "
        "WHERE attrelid = 'access'::regclass AND attnum > 0 AND NOT attisdropped "
        "ORDER BY attnum"
    )
    return [row["attname"] for row in cur.fetchall()]


def checks(cur):
    cur.execute(
        "SELECT conname, pg_get_constraintdef(oid) AS definition FROM pg_constraint "
        "WHERE conrelid = 'access'::regclass AND contype = 'c'"
    )
    return cur.fetchall()


def rows(cur):
    cur.execute("SELECT * FROM access ORDER BY booking_id")
    return cur.fetchall()


def test_a_removed_row_becomes_revoked_and_keeps_its_time(cur):
    add_removed(cur, 1)

    cur.execute(MIGRATION_002)

    cur.execute("SELECT status, revoked_at, expired_at FROM access WHERE booking_id = 1")
    assert cur.fetchone() == {"status": "revoked", "revoked_at": REMOVED_AT, "expired_at": None}


def test_the_other_statuses_are_left_alone(cur):
    add(cur, 1, "available")
    add(cur, 2, "used")
    add(cur, 3, "expired")

    cur.execute(MIGRATION_002)

    assert [row["status"] for row in rows(cur)] == ["available", "used", "expired"]


def test_removed_at_becomes_revoked_at_and_expired_at_is_added(cur):
    cur.execute(MIGRATION_002)

    assert columns(cur) == [
        "booking_id", "access_code", "status", "booked_start_time", "booked_end_time",
        "space_id", "created_at", "expires_at", "checked_in_at", "checked_out_at",
        "revoked_at", "expired_at",
    ]


def test_the_new_check_allows_revoked_and_refuses_removed(cur):
    cur.execute(MIGRATION_002)

    add(cur, 1, "revoked")
    with pytest.raises(psycopg.errors.CheckViolation):
        with cur.connection.transaction():  # a savepoint, so the test can go on
            add(cur, 2, "removed")

    assert [check["conname"] for check in checks(cur)] == ["access_status_check"]
    assert "'revoked'" in checks(cur)[0]["definition"]


def test_running_002_twice_changes_nothing(cur):
    add_removed(cur, 1)
    add(cur, 2, "available")
    cur.execute(MIGRATION_002)
    first = columns(cur), checks(cur), rows(cur)

    cur.execute(MIGRATION_002)

    assert (columns(cur), checks(cur), rows(cur)) == first


def test_002_finishes_a_run_that_stopped_half_way(cur):
    # As if a run without --single-transaction had stopped after step 1.
    add_removed(cur, 1)
    cur.execute("ALTER TABLE access RENAME COLUMN removed_at TO revoked_at")

    cur.execute(MIGRATION_002)

    cur.execute("SELECT status, revoked_at FROM access WHERE booking_id = 1")
    assert cur.fetchone() == {"status": "revoked", "revoked_at": REMOVED_AT}
    assert "'revoked'" in checks(cur)[0]["definition"]
