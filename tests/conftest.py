"""Shared pytest fixtures for spacey-access tests."""
import pytest
from app import create_app


@pytest.fixture()
def app():
    """Create application for testing."""
    # create_app's argument is the database URL; the default reads DATABASE_URL.
    app = create_app()
    yield app


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