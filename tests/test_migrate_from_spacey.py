"""Cancellations in the data copy (ACC-11): rows whose booking is gone from
spacey's `bookings` become `revoked`. Runs on the real test database inside a
transaction that is rolled back, so nothing is left behind."""

from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from scripts.migrate_from_spacey import mark_cancelled_revoked, target_ready
from src.db import DATABASE_URL

MIGRATIONS = Path(__file__).parent.parent / "migrations"
MIGRATION_001 = (MIGRATIONS / "001_create_access_table.sql").read_text()
MIGRATION_002 = (MIGRATIONS / "002_revoke_and_expiry.sql").read_text()


@pytest.fixture()
def cur():
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(MIGRATION_001)  # both safe to run again, rolled back below
            cur.execute(MIGRATION_002)
            cur.execute("DELETE FROM access")
            yield cur
        conn.rollback()


def add(cur, booking_id, status="available"):
    cur.execute(
        "INSERT INTO access (booking_id, access_code, status) VALUES (%s, %s, %s)",
        (booking_id, f"code{booking_id}", status),
    )


def row(cur, booking_id):
    cur.execute("SELECT status, revoked_at FROM access WHERE booking_id = %s", (booking_id,))
    return cur.fetchone()


def test_a_cancelled_booking_becomes_revoked(cur):
    add(cur, 1)
    add(cur, 2)

    revoked = mark_cancelled_revoked(cur, booking_ids=[2])  # booking 1 is gone

    assert revoked == 1
    assert row(cur, 1)["status"] == "revoked"
    assert row(cur, 1)["revoked_at"] is not None
    assert row(cur, 2)["status"] == "available"


def test_a_used_row_is_revoked_too(cur):
    add(cur, 1, status="used")

    mark_cancelled_revoked(cur, booking_ids=[2])

    assert row(cur, 1)["status"] == "revoked"


def test_a_row_whose_booking_exists_is_left_alone(cur):
    # Granted by Access after the switch: spacey's `access` table has no row
    # for booking 3, but the booking itself still exists in `bookings`.
    add(cur, 3)

    revoked = mark_cancelled_revoked(cur, booking_ids=[3])

    assert revoked == 0
    assert row(cur, 3)["status"] == "available"


def test_expired_rows_stay_expired(cur):
    add(cur, 1, status="expired")

    mark_cancelled_revoked(cur, booking_ids=[2])

    assert row(cur, 1)["status"] == "expired"
    assert row(cur, 1)["revoked_at"] is None


def test_a_second_run_changes_nothing_and_keeps_revoked_at(cur):
    add(cur, 1)
    mark_cancelled_revoked(cur, booking_ids=[2])
    first = row(cur, 1)["revoked_at"]

    revoked = mark_cancelled_revoked(cur, booking_ids=[2])

    assert revoked == 0
    assert row(cur, 1)["revoked_at"] == first


def test_no_bookings_at_all_is_refused(cur):
    add(cur, 1)

    with pytest.raises(SystemExit):
        mark_cancelled_revoked(cur, booking_ids=[])

    assert row(cur, 1)["status"] == "available"


def test_the_target_is_ready_after_001_and_002(cur):
    assert target_ready(cur)


def test_a_target_without_002_is_not_ready(cur):
    cur.execute("CREATE SCHEMA copy_target_test")
    cur.execute("SET LOCAL search_path TO copy_target_test")
    assert not target_ready(cur)  # no access table at all

    cur.execute(MIGRATION_001)

    assert not target_ready(cur)  # 001 only: no revoked_at yet
