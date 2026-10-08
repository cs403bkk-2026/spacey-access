from pathlib import Path

from app import create_app


def test_health_reports_ok_and_revision(monkeypatch):
    monkeypatch.setenv("APP_REVISION", "abc123")
    client = create_app().test_client()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "revision": "abc123"}


def test_health_is_503_when_the_database_is_unreachable():
    app = create_app()
    app.db.close()  # as if Postgres went away after start-up

    response = app.test_client().get("/health")

    assert response.status_code == 503
    assert response.get_json() == {"status": "error", "error": "database unreachable"}


def test_the_openapi_document_is_served_as_is():
    response = create_app().test_client().get("/openapi.yaml")

    assert response.status_code == 200
    assert response.mimetype == "application/yaml"
    assert response.get_data() == (Path(__file__).parent.parent / "openapi.yaml").read_bytes()
