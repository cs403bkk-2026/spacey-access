"""Cancellations in the data copy (ACC-11): rows whose booking is gone from
spacey's `bookings` become `removed`. Runs on the real test database inside a
transaction that is rolled back, so nothing is left behind."""

from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from scripts.migrate_from_spacey import mark_cancelled_removed
from src.db import DATABASE_URL

MIGRATION = Path(__file__).parent.parent / "migrations" / "001_create_access_table.sql"


@pytest.fixture()
def cur():
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(MIGRATION.read_text())  # IF NOT EXISTS, rolled back below
            cur.execute("DELETE FROM access")
            yield cur
        conn.rollback()


def add(cur, booking_id, status="available"):
    cur.execute(
        "INSERT INTO access (booking_id, access_code, status) VALUES (%s, %s, %s)",
        (booking_id, f"code{booking_id}", status),
    )


def row(cur, booking_id):
    cur.execute("SELECT status, removed_at FROM access WHERE booking_id = %s", (booking_id,))
    return cur.fetchone()


def test_a_cancelled_booking_becomes_removed(cur):
    add(cur, 1)
    add(cur, 2)

    removed = mark_cancelled_removed(cur, booking_ids=[2])  # booking 1 is gone

    assert removed == 1
    assert row(cur, 1)["status"] == "removed"
    assert row(cur, 1)["removed_at"] is not None
    assert row(cur, 2)["status"] == "available"


def test_a_used_row_is_removed_too(cur):
    add(cur, 1, status="used")

    mark_cancelled_removed(cur, booking_ids=[2])

    assert row(cur, 1)["status"] == "removed"


def test_a_row_whose_booking_exists_is_left_alone(cur):
    # Granted by Access after the switch: spacey's `access` table has no row
    # for booking 3, but the booking itself still exists in `bookings`.
    add(cur, 3)

    removed = mark_cancelled_removed(cur, booking_ids=[3])

    assert removed == 0
    assert row(cur, 3)["status"] == "available"


def test_expired_rows_stay_expired(cur):
    add(cur, 1, status="expired")

    mark_cancelled_removed(cur, booking_ids=[2])

    assert row(cur, 1)["status"] == "expired"
    assert row(cur, 1)["removed_at"] is None


def test_a_second_run_changes_nothing_and_keeps_removed_at(cur):
    add(cur, 1)
    mark_cancelled_removed(cur, booking_ids=[2])
    first = row(cur, 1)["removed_at"]

    removed = mark_cancelled_removed(cur, booking_ids=[2])

    assert removed == 0
    assert row(cur, 1)["removed_at"] == first


def test_no_bookings_at_all_is_refused(cur):
    add(cur, 1)

    with pytest.raises(SystemExit):
        mark_cancelled_removed(cur, booking_ids=[])

    assert row(cur, 1)["status"] == "available"
