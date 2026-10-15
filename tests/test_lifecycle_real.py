"""The 0.2.0 lifecycle (openapi.yaml, State x action table) on the REAL database.

Same tests as tests/test_mock_mode.py, run against src/db.py instead of the
in-memory mock (extract F6): the mock and the real service now promise exactly
the same thing, and every answer is checked against openapi.yaml.
Needs the local test database (DATABASE_URL), like tests/test_db.py."""

import json
from pathlib import Path

import pytest
from openapi_core.testing import MockRequest, MockResponse

from app import create_app
from tests import test_mock_mode as lifecycle
from tests.test_mock_mode import CONTRACT

MIGRATIONS = Path(__file__).parent.parent / "migrations"


@pytest.fixture()
def call(monkeypatch, auth):
    monkeypatch.delenv("MOCK", raising=False)
    app = create_app()
    for name in ("001_create_access_table.sql", "002_revoke_and_expiry.sql"):
        app.db.execute((MIGRATIONS / name).read_text())
    app.db.execute("DELETE FROM access")
    client = app.test_client()

    def _call(method, path, body=None):
        response = client.open(path, method=method, json=body, headers=auth)
        CONTRACT.validate_response(
            MockRequest("http://localhost", method.lower(), path, headers=auth,
                        data=None if body is None else json.dumps(body).encode()),
            MockResponse(response.get_data(), status_code=response.status_code,
                         content_type=response.content_type),
        )
        return response.status_code, response.get_json()

    yield _call
    app.db.execute("DELETE FROM access")


# Every lifecycle test of the mock suite, collected again here with the real `call`.
for _name in dir(lifecycle):
    if _name.startswith("test_") and _name not in {
        "test_mock_mode_starts_without_a_database", "test_health_says_mock",
        "test_mock_refuses_to_start_when_a_database_url_is_set", "test_reset_empties_the_store",
        "test_reset_needs_the_token", "test_the_6_functions_still_need_the_token",
    }:
        globals()[_name] = getattr(lifecycle, _name)
