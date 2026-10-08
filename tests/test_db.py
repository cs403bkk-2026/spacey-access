import psycopg
import pytest

from src.db import get_connection


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
