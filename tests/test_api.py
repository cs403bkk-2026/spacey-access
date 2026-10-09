"""The Access API: every endpoint answers as openapi.yaml says.
The functions behind it are DUMMY for now (fixed answers)."""

from src.purchase_client import notify_purchase_expired

START = "2030-01-01T10:00:00+00:00"
END = "2030-01-01T11:00:00+00:00"


# --- Purchase -> Access --------------------------------------------------------


def test_create_access_returns_201_with_an_available_code(client):
    response = client.post("/bookings/42/access", json={"start_time": START, "end_time": END})

    assert response.status_code == 201
    body = response.get_json()
    assert body["booking_id"] == 42
    assert body["access_code"]
    assert body["status"] == "available"
    assert body["expires_at"] == END


def test_create_access_without_the_booking_times_is_400(client):
    response = client.post("/bookings/42/access", json={"start_time": START})

    assert response.status_code == 400
    assert "error" in response.get_json()


def test_remove_access_marks_it_removed(client):
    response = client.post("/bookings/42/access/remove")

    assert response.status_code == 200
    body = response.get_json()
    assert body["booking_id"] == 42
    assert body["status"] == "removed"
    assert body["removed_at"]


def test_expire_access_marks_it_expired(client):
    response = client.post("/bookings/42/access/expire")

    assert response.status_code == 200
    assert response.get_json() == {"booking_id": 42, "status": "expired"}


# --- Frontend -> Access --------------------------------------------------------


def test_check_in_marks_it_used(client):
    response = client.post("/bookings/42/check-in", json={"access_code": "00000000"})

    assert response.status_code == 200
    body = response.get_json()
    assert body["booking_id"] == 42
    assert body["status"] == "used"
    assert body["checked_in_at"]


def test_check_in_without_a_code_is_400(client):
    response = client.post("/bookings/42/check-in", json={})

    assert response.status_code == 400
    assert "error" in response.get_json()


def test_check_out_makes_it_available_again(client):
    response = client.post("/bookings/42/check-out")

    assert response.status_code == 200
    body = response.get_json()
    assert body["booking_id"] == 42
    assert body["status"] == "available"
    assert body["checked_out_at"]


# --- Access -> Purchase --------------------------------------------------------


def test_notify_purchase_expired_describes_the_call_without_sending_it():
    call = notify_purchase_expired(42)

    assert call["method"] == "POST"
    assert call["url"].endswith("/bookings/42/access-expired")
    assert call["json"] == {"booking_id": 42, "status": "expired"}
