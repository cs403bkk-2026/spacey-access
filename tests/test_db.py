import re
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from src import db
from src.db import DATABASE_URL, get_connection

MIGRATIONS = Path(__file__).parent.parent / "migrations"
START = "2030-01-01T10:00:00+00:00"
END = "2030-01-01T11:00:00+00:00"


@pytest.fixture()
def conn():
    """The real SQL in src/db.py on the migrated table (001 + 002), rolled back after."""
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        conn.execute((MIGRATIONS / "001_create_access_table.sql").read_text())
        conn.execute((MIGRATIONS / "002_revoke_and_expiry.sql").read_text())
        conn.execute("DELETE FROM access")
        yield conn
        conn.rollback()


def test_connection_failure_does_not_disclose_credentials(monkeypatch):
    database_url = "postgresql://example:private-password@db/access"

    def fail_connection(*args, **kwargs):
        raise psycopg.OperationalError(f"Rejected connection: {database_url}")

    monkeypatch.setattr(psycopg, "connect", fail_connection)

    with pytest.raises(SystemExit) as failure:
        get_connection(database_url)

    assert "Could not connect to the database" in str(failure.value)
    assert database_url not in str(failure.value)
    assert "private-password" not in str(failure.value)
    assert failure.value.__suppress_context__


def test_read_access_returns_the_full_record(conn):
    db.create_access(conn, 42, START, END)

    record, status = db.read_access(conn, 42)

    assert status == 200
    assert set(record) == {
        "booking_id", "access_code", "status", "expires_at",
        "checked_in_at", "checked_out_at", "revoked_at", "expired_at",
    }
    assert record["status"] == "available"
    assert record["expires_at"] == "2030-01-01T11:00:00+00:00"  # ISO 8601, as the contract says
    well_formed = re.fullmatch("[0-9a-f]{8}", record["access_code"]) is not None
    assert well_formed, "access_code is not 8 lowercase hex characters"  # never print the code


def test_read_access_of_an_unknown_booking_is_404(conn):
    assert db.read_access(conn, 99) == ({"error": "access record not found"}, 404)


def test_create_is_get_or_create(conn):
    first, created = db.create_access(conn, 42, START, END)
    again, repeated = db.create_access(conn, 42, "2030-02-01T10:00:00+00:00", "2030-02-01T11:00:00+00:00")

    assert (created, repeated) == (201, 200)
    assert again == first  # unchanged, even though the times differ


@pytest.mark.parametrize(("start", "end"), [
    ("not a time", END), (START, None), ("2030-01-01T10:00:00", END), (END, START),
], ids=["unparseable", "missing", "naive", "end-before-start"])
def test_create_with_bad_times_is_400(conn, start, end):
    body, status = db.create_access(conn, 42, start, end)
    assert status == 400 and "error" in body


def test_read_of_an_overdue_record_expires_it_first(conn):
    db.create_access(conn, 42, "2020-01-01T10:00:00+00:00", "2020-01-01T11:00:00+00:00")

    record, status = db.read_access(conn, 42)

    assert status == 200
    assert record["status"] == "expired" and record["expired_at"] is not None


def test_revoke_makes_it_revoked_and_a_repeat_is_the_same_record(conn):
    db.create_access(conn, 42, START, END)

    first, status = db.revoke_access(conn, 42)
    again, repeat = db.revoke_access(conn, 42)

    assert (status, repeat) == (200, 200)
    assert first["status"] == "revoked" and first["revoked_at"] is not None
    assert again == first  # revoked_at kept from the first revoke
    assert db.read_access(conn, 42)[0]["status"] == "revoked"


@pytest.mark.parametrize("final", ["used", "expired"])
def test_revoke_on_a_final_state_is_409_and_changes_nothing(conn, final):
    db.create_access(conn, 42, START, END)
    conn.execute("UPDATE access SET status = %s WHERE booking_id = 42", (final,))

    body, status = db.revoke_access(conn, 42)

    assert status == 409 and body["status"] == final
    assert db.read_access(conn, 42)[0]["status"] == final


def test_revoke_unknown_is_404(conn):
    assert db.revoke_access(conn, 99) == ({"error": "access record not found"}, 404)


def test_concurrent_creates_give_one_record_and_one_code():
    """Two unlocks of the same booking at the same instant (separate connections,
    committed): one 201, one 200, the same code, one row."""
    from concurrent.futures import ThreadPoolExecutor

    setup = get_connection()
    setup.execute((MIGRATIONS / "001_create_access_table.sql").read_text())
    setup.execute((MIGRATIONS / "002_revoke_and_expiry.sql").read_text())
    setup.execute("DELETE FROM access WHERE booking_id = 4242")

    def create(_):
        with get_connection() as conn:
            return db.create_access(conn, 4242, START, END)

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(create, range(8)))
        statuses = sorted(status for _, status in results)
        assert statuses == [200] * 7 + [201]
        assert len({body["access_code"] for body, _ in results}) == 1
        assert setup.execute("SELECT count(*) AS n FROM access WHERE booking_id = 4242").fetchone()["n"] == 1
    finally:
        setup.execute("DELETE FROM access WHERE booking_id = 4242")
        setup.close()
