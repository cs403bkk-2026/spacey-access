"""Migration 002 (revoke and expiry) on a table that still has the old
vocabulary. Runs on the real test database inside a transaction that is rolled
back (DDL is transactional in Postgres), so nothing is left behind."""

from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from src.db import DATABASE_URL

MIGRATIONS = Path(__file__).parent.parent / "migrations"
M001 = (MIGRATIONS / "001_create_access_table.sql").read_text()
M002 = (MIGRATIONS / "002_revoke_and_expiry.sql").read_text()


@pytest.fixture()
def cur():
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS access")
            cur.execute(M001)  # the old shape: removed, removed_at
            yield cur
        conn.rollback()


def snapshot(cur):
    cur.execute(
        "SELECT booking_id, status, revoked_at, expired_at FROM access ORDER BY booking_id"
    )
    return cur.fetchall()


def test_a_removed_row_becomes_revoked_and_keeps_its_time(cur):
    cur.execute(
        "INSERT INTO access (booking_id, access_code, status, removed_at) "
        "VALUES (1, 'aaaa1111', 'removed', '2030-01-01T09:00:00+00:00'), "
        "       (2, 'bbbb2222', 'available', NULL)"
    )

    cur.execute(M002)

    first, second = snapshot(cur)
    assert first["status"] == "revoked"
    assert first["revoked_at"].isoformat() == "2030-01-01T09:00:00+00:00"
    assert second["status"] == "available"
    assert second["revoked_at"] is None
    assert second["expired_at"] is None


def test_running_migration_002_twice_changes_nothing(cur):
    cur.execute(
        "INSERT INTO access (booking_id, access_code, status, removed_at) "
        "VALUES (1, 'aaaa1111', 'removed', '2030-01-01T09:00:00+00:00')"
    )
    cur.execute(M002)
    after_first = snapshot(cur)

    cur.execute(M002)

    assert snapshot(cur) == after_first


def test_the_new_status_check_refuses_the_old_word(cur):
    cur.execute(M002)

    with pytest.raises(psycopg.errors.CheckViolation):
        cur.execute(
            "INSERT INTO access (booking_id, access_code, status) "
            "VALUES (1, 'aaaa1111', 'removed')"
        )
