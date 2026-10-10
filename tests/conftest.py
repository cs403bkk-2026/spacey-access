"""Shared pytest fixtures for spacey-access tests."""
import pytest
from app import create_app


@pytest.fixture()
def app():
    """Create application for testing."""
    # create_app's argument is the database URL; the default reads DATABASE_URL.
    app = create_app()
    yield app


@pytest.fixture(autouse=True)
def service_token(monkeypatch):
    """The shared Purchase <-> Access token (ACC-08), set for every test."""
    monkeypatch.setenv("SERVICE_TOKEN", "test-token")
    return "test-token"


@pytest.fixture()
def auth(service_token):
    """Headers Purchase sends on create, remove and expire."""
    return {"Authorization": f"Bearer {service_token}"}


@pytest.fixture()
def client(app):
    """Test client for the app."""
    return app.test_client()


@pytest.fixture()
def check_schema():
    """
    Minimal contract check: verify a response matches the expected status code.
    Library choice: no external library — we keep it simple and check status + JSON shape.
    Extend to openapi-core once the spec stabilises.
    """
    def _check(response, expected_status):
        assert response.status_code == expected_status
        assert response.content_type == "application/json"
    return _check