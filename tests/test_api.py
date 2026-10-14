"""The Access API: each route calls its src/db.py function and answers with the
status openapi.yaml gives. src/db.py is patched here, so the SQL itself is not
exercised (ARCH-01 replaces these patches with a real/mock suite)."""

from unittest.mock import patch

import pytest

from src.purchase_client import notify_purchase_expired

START = "2030-01-01T10:00:00+00:00"
END = "2030-01-01T11:00:00+00:00"


# --- The 6 access functions ------------------------------------------------------


def test_create_access_returns_201_with_an_available_code(client, auth):
    mock_result = {"booking_id": 42, "access_code": "a3f9c21b", "status": "available", "expires_at": END}
    with patch("src.api.db.create_access", return_value=mock_result):
        response = client.post(
            "/bookings/42/access",
            json={"start_time": START, "end_time": END},
            headers=auth,
        )

    assert response.status_code == 201
    body = response.get_json()
    assert body["booking_id"] == 42
    assert body["access_code"]
    assert body["status"] == "available"
    assert body["expires_at"] == END


def test_create_access_without_the_booking_times_is_400(client, auth):
    response = client.post(
        "/bookings/42/access",
        json={"start_time": START},
        headers=auth,
    )

    assert response.status_code == 400
    assert "error" in response.get_json()


def test_read_access_returns_the_record(client, auth):
    mock_result = {
        "booking_id": 42,
        "access_code": "a3f9c21b",
        "status": "available",
        "expires_at": END,
        "checked_in_at": None,
        "checked_out_at": None,
        "revoked_at": None,
        "expired_at": None,
    }
    with patch("src.api.db.read_access", return_value=mock_result) as read:
        response = client.get("/bookings/42/access", headers=auth)

    assert response.status_code == 200
    assert response.get_json() == mock_result
    assert read.call_args.args[1] == 42


def test_read_access_returns_404_when_not_found(client, auth):
    with patch("src.api.db.read_access", return_value=None):
        response = client.get("/bookings/99/access", headers=auth)

    assert response.status_code == 404
    assert response.get_json() == {"error": "access record not found"}


def test_revoke_access_marks_it_revoked(client, auth):
    mock_result = {
        "booking_id": 42,
        "status": "revoked",
        "revoked_at": "2030-01-01T10:30:00+00:00",
    }
    with patch("src.api.db.revoke_access", return_value=mock_result):
        response = client.post("/bookings/42/access/revoke", headers=auth)

    assert response.status_code == 200
    body = response.get_json()
    assert body["booking_id"] == 42
    assert body["status"] == "revoked"
    assert body["revoked_at"]


def test_revoke_access_returns_404_when_not_found(client, auth):
    with patch("src.api.db.revoke_access", return_value=None):
        response = client.post("/bookings/99/access/revoke", headers=auth)

    assert response.status_code == 404


def test_check_in_marks_it_used(client, auth):
    mock_result = {
        "booking_id": 42,
        "status": "used",
        "checked_in_at": "2030-01-01T10:05:00+00:00",
    }
    with patch("src.api.db.check_in", return_value=mock_result):
        response = client.post(
            "/bookings/42/check-in", json={"access_code": "a3f9c21b"}, headers=auth
        )

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "used"
    assert body["checked_in_at"]


def test_check_in_returns_404_when_no_record_matches(client, auth):
    with patch("src.api.db.check_in", return_value=None):
        response = client.post(
            "/bookings/42/check-in", json={"access_code": "wrongcode"}, headers=auth
        )

    assert response.status_code == 404


def test_check_in_without_a_code_is_400(client, auth):
    response = client.post("/bookings/42/check-in", json={}, headers=auth)

    assert response.status_code == 400
    assert "error" in response.get_json()


def test_check_out_records_checked_out_at_and_stays_used(client, auth):
    mock_result = {
        "booking_id": 42,
        "status": "used",
        "checked_out_at": "2030-01-01T11:00:00+00:00",
    }
    with patch("src.api.db.check_out", return_value=mock_result):
        response = client.post("/bookings/42/check-out", headers=auth)

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "used"
    assert body["checked_out_at"]


def test_expire_access_marks_it_expired(client, auth):
    mock_result = {"booking_id": 42, "status": "expired"}
    with patch("src.api.db.expire_access", return_value=mock_result):
        response = client.post("/bookings/42/access/expire", headers=auth)

    assert response.status_code == 200
    assert response.get_json() == {"booking_id": 42, "status": "expired"}


@pytest.mark.parametrize("url", ["/bookings/42/unlock", "/bookings/42/access/remove"])
def test_the_old_routes_are_gone(client, auth, url):
    response = client.post(url, headers=auth)

    assert response.status_code == 404


# --- Service token (ACC-08), on all 6 since 0.2.0 -------------------------------

ACCESS_ENDPOINTS = [
    ("POST", "/bookings/42/access", "create_access"),
    ("GET", "/bookings/42/access", "read_access"),
    ("POST", "/bookings/42/access/revoke", "revoke_access"),
    ("POST", "/bookings/42/check-in", "check_in"),
    ("POST", "/bookings/42/check-out", "check_out"),
    ("POST", "/bookings/42/access/expire", "expire_access"),
]


@pytest.mark.parametrize(("method", "url", "db_function"), ACCESS_ENDPOINTS)
@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer invalid-token"}, {"Authorization": "Bearer café"}],
)
def test_access_calls_reject_invalid_tokens_before_db(
    client, method, url, db_function, headers
):
    with patch(f"src.api.db.{db_function}") as mock_db:
        response = client.open(url, method=method, json={}, headers=headers)

    assert response.status_code == 401
    assert response.get_json() == {"error": "invalid or missing service token"}
    mock_db.assert_not_called()


@pytest.mark.parametrize(("method", "url", "db_function"), ACCESS_ENDPOINTS)
def test_access_calls_are_refused_when_server_has_no_token(
    client, auth, monkeypatch, method, url, db_function
):
    monkeypatch.delenv("SERVICE_TOKEN")
    with patch(f"src.api.db.{db_function}") as mock_db:
        response = client.open(url, method=method, json={}, headers=auth)

    assert response.status_code == 401
    mock_db.assert_not_called()


# --- Access -> Purchase --------------------------------------------------------


def test_notify_purchase_expired_describes_the_call_without_sending_it(service_token):
    call = notify_purchase_expired(42)

    assert call["method"] == "POST"
    assert call["url"].endswith("/bookings/42/access-expired")
    assert call["json"] == {"booking_id": 42, "status": "expired"}
    assert call["headers"] == {"Authorization": f"Bearer {service_token}"}


def test_notify_purchase_expired_requires_the_shared_token(monkeypatch):
    monkeypatch.delenv("SERVICE_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="SERVICE_TOKEN"):
        notify_purchase_expired(42)
