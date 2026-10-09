"""The Access API: every endpoint answers as openapi.yaml says.
The functions behind it are DUMMY for now (fixed answers)."""

from unittest.mock import patch

import pytest

from src.purchase_client import notify_purchase_expired

START = "2030-01-01T10:00:00+00:00"
END = "2030-01-01T11:00:00+00:00"


# --- Purchase -> Access --------------------------------------------------------


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


def test_remove_access_marks_it_removed(client, auth):
    mock_result = {
        "booking_id": 42,
        "status": "removed",
        "removed_at": "2030-01-01T10:30:00+00:00",
    }
    with patch("src.api.db.remove_access", return_value=mock_result):
        response = client.post("/bookings/42/access/remove", headers=auth)

    assert response.status_code == 200
    body = response.get_json()
    assert body["booking_id"] == 42
    assert body["status"] == "removed"
    assert body["removed_at"]


def test_expire_access_marks_it_expired(client, auth):
    mock_result = {"booking_id": 42, "status": "expired"}
    with patch("src.api.db.expire_access", return_value=mock_result):
        response = client.post("/bookings/42/access/expire", headers=auth)

    assert response.status_code == 200
    assert response.get_json() == {"booking_id": 42, "status": "expired"}


# --- Service token (ACC-08) ----------------------------------------------------

PURCHASE_ENDPOINTS = [
    ("/bookings/42/access", "create_access"),
    ("/bookings/42/access/remove", "remove_access"),
    ("/bookings/42/access/expire", "expire_access"),
]


@pytest.mark.parametrize(("url", "db_function"), PURCHASE_ENDPOINTS)
@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer invalid-token"}, {"Authorization": "Bearer café"}],
)
def test_purchase_calls_reject_invalid_tokens_before_db(
    client, url, db_function, headers
):
    with patch(f"src.api.db.{db_function}") as mock_db:
        response = client.post(url, json={}, headers=headers)

    assert response.status_code == 401
    mock_db.assert_not_called()


@pytest.mark.parametrize(("url", "db_function"), PURCHASE_ENDPOINTS)
def test_purchase_calls_are_refused_when_server_has_no_token(
    client, auth, monkeypatch, url, db_function
):
    monkeypatch.delenv("SERVICE_TOKEN")
    with patch(f"src.api.db.{db_function}") as mock_db:
        response = client.post(url, json={}, headers=auth)

    assert response.status_code == 401
    mock_db.assert_not_called()


def test_frontend_calls_do_not_need_a_token(client):
    result = {
        "booking_id": 42,
        "status": "available",
        "checked_out_at": END,
    }
    with patch("src.api.db.check_out", return_value=result):
        response = client.post("/bookings/42/check-out")

    assert response.status_code == 200


# --- Frontend -> Access --------------------------------------------------------


def test_check_in_marks_it_used(client):
    mock_result = {
        "booking_id": 42,
        "status": "used",
        "checked_in_at": "2030-01-01T10:05:00+00:00",
    }
    with patch("src.api.db.check_in", return_value=mock_result):
        response = client.post(
            "/bookings/42/check-in", json={"access_code": "a3f9c21b"}
        )

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "used"
    assert body["checked_in_at"]


def test_check_in_returns_404_when_code_invalid_or_already_used(client):
    with patch("src.api.db.check_in", return_value=None):
        response = client.post(
            "/bookings/42/check-in", json={"access_code": "wrongcode"}
        )

    assert response.status_code == 404


def test_check_in_without_a_code_is_400(client):
    response = client.post("/bookings/42/check-in", json={})

    assert response.status_code == 400
    assert "error" in response.get_json()


def test_remove_access_returns_404_when_not_found(client, auth):
    with patch("src.api.db.remove_access", return_value=None):
        response = client.post("/bookings/99/access/remove", headers=auth)

    assert response.status_code == 404


def test_check_out_makes_it_available_again(client):
    mock_result = {
        "booking_id": 42,
        "status": "available",
        "checked_out_at": "2030-01-01T11:00:00+00:00",
    }
    with patch("src.api.db.check_out", return_value=mock_result):
        response = client.post("/bookings/42/check-out")

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "available"
    assert body["checked_out_at"]


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
