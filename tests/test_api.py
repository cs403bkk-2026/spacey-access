from unittest.mock import patch

import pytest

"""The Access API: every endpoint answers as openapi.yaml says.
The functions behind it are DUMMY for now (fixed answers)."""

from src.purchase_client import notify_purchase_expired

START = "2030-01-01T10:00:00+00:00"
END = "2030-01-01T11:00:00+00:00"


# --- Purchase -> Access --------------------------------------------------------


def test_create_access_returns_201_with_an_available_code(client, auth):
    mock_result = {"booking_id": 42, "access_code": "a3f9c21b", "status": "available", "expires_at": END}
    with patch("src.api.db.create_access", return_value=mock_result):
        response = client.post("/bookings/42/access", json={"start_time": START, "end_time": END}, headers=auth)

    assert response.status_code == 201
    body = response.get_json()
    assert body["booking_id"] == 42
    assert body["access_code"]  # any non-empty string, not hardcoded
    assert body["status"] == "available"
    assert body["expires_at"] == END

def test_create_access_without_the_booking_times_is_400(client, auth):
    response = client.post("/bookings/42/access", json={"start_time": START}, headers=auth)

    assert response.status_code == 400
    assert "error" in response.get_json()


def test_remove_access_marks_it_removed(client, auth):
    mock_result = {"booking_id": 42, "status": "removed", "removed_at": "2030-01-01T10:30:00+00:00"}
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
    "/bookings/42/access",
    "/bookings/42/access/remove",
    "/bookings/42/access/expire",
]


@pytest.mark.parametrize("url", PURCHASE_ENDPOINTS)
def test_purchase_calls_without_a_token_are_401(client, url):
    response = client.post(url, json={"start_time": START, "end_time": END})

    assert response.status_code == 401
    assert "error" in response.get_json()


@pytest.mark.parametrize("url", PURCHASE_ENDPOINTS)
def test_purchase_calls_with_a_wrong_token_are_401(client, url):
    response = client.post(url, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


@pytest.mark.parametrize("url", PURCHASE_ENDPOINTS)
def test_purchase_calls_with_a_non_ascii_token_are_401_not_500(client, url):
    response = client.post(url, headers={"Authorization": "Bearer tëst"})

    assert response.status_code == 401


@pytest.mark.parametrize("url", PURCHASE_ENDPOINTS)
def test_the_token_is_checked_before_the_body(client, url):
    # No token and an empty body: 401, not the 400 for the missing times.
    response = client.post(url, json={})

    assert response.status_code == 401


@pytest.mark.parametrize("url", PURCHASE_ENDPOINTS)
def test_purchase_calls_are_refused_when_the_server_has_no_token(client, auth, monkeypatch, url):
    monkeypatch.delenv("SERVICE_TOKEN")

    response = client.post(url, json={"start_time": START, "end_time": END}, headers=auth)

    assert response.status_code == 401


def test_frontend_calls_do_not_need_a_token(client):
    with patch("src.api.db.check_out", return_value={"booking_id": 42, "status": "available", "checked_out_at": END}):
        response = client.post("/bookings/42/check-out")

    assert response.status_code == 200


# --- Frontend -> Access --------------------------------------------------------


def test_check_in_marks_it_used(client):
    mock_result = {"booking_id": 42, "status": "used", "checked_in_at": "2030-01-01T10:05:00+00:00"}
    with patch("src.api.db.check_in", return_value=mock_result):
        response = client.post("/bookings/42/check-in", json={"access_code": "a3f9c21b"})

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "used"
    assert body["checked_in_at"]

def test_check_in_returns_404_when_code_invalid_or_already_used(client):
    with patch("src.api.db.check_in", return_value=None):
        response = client.post("/bookings/42/check-in", json={"access_code": "wrongcode"})

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
    mock_result = {"booking_id": 42, "status": "available", "checked_out_at": "2030-01-01T11:00:00+00:00"}
    with patch("src.api.db.check_out", return_value=mock_result):
        response = client.post("/bookings/42/check-out")

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "available"
    assert body["checked_out_at"]


# --- Access -> Purchase --------------------------------------------------------


def test_notify_purchase_expired_describes_the_call_without_sending_it():
    call = notify_purchase_expired(42)

    assert call["method"] == "POST"
    assert call["url"].endswith("/bookings/42/access-expired")
    assert call["json"] == {"booking_id": 42, "status": "expired"}


def test_notify_purchase_expired_carries_the_service_token():
    call = notify_purchase_expired(42)

    assert call["headers"] == {"Authorization": "Bearer test-token"}
