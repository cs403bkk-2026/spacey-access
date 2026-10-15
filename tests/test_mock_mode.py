"""MOCK=1 (ARCH-01): Access runs with an in-memory store that follows the 0.2.0
contract (openapi.yaml, State x action table). spacey's tests are built against
this mock, so every answer here is also checked against openapi.yaml with the
same validator as tests/test_openapi.py. No database needed."""

import json
from pathlib import Path

import pytest
from openapi_core import OpenAPI
from openapi_core.testing import MockRequest, MockResponse

from app import create_app

CONTRACT = OpenAPI.from_file_path(str(Path(__file__).parent.parent / "openapi.yaml"))

FUTURE_START = "2030-01-01T10:00:00+00:00"
FUTURE_END = "2030-01-01T11:00:00+00:00"
PAST_START = "2020-01-01T10:00:00+00:00"
PAST_END = "2020-01-01T11:00:00+00:00"


@pytest.fixture()
def mock_app(monkeypatch):
    monkeypatch.setenv("MOCK", "1")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return create_app()


@pytest.fixture()
def call(mock_app, auth):
    """Call the mock with the token, check the answer against openapi.yaml,
    and return (status, body)."""
    client = mock_app.test_client()

    def _call(method, path, body=None):
        response = client.open(path, method=method, json=body, headers=auth)
        CONTRACT.validate_response(
            MockRequest(
                "http://localhost", method.lower(), path,
                headers=auth, data=None if body is None else json.dumps(body).encode(),
            ),
            MockResponse(response.get_data(), status_code=response.status_code,
                         content_type=response.content_type),
        )
        return response.status_code, response.get_json()

    return _call


def create(call, booking_id=42, start=FUTURE_START, end=FUTURE_END):
    return call("POST", f"/bookings/{booking_id}/access", {"start_time": start, "end_time": end})


def code_of(call, booking_id=42):
    return call("GET", f"/bookings/{booking_id}/access")[1]["access_code"]


def to_used(call, booking_id=42):
    create(call, booking_id)
    call("POST", f"/bookings/{booking_id}/check-in", {"access_code": code_of(call, booking_id)})


def to_revoked(call, booking_id=42):
    create(call, booking_id)
    call("POST", f"/bookings/{booking_id}/access/revoke")


def to_expired(call, booking_id=42):
    create(call, booking_id)
    call("POST", f"/bookings/{booking_id}/access/expire")


# --- Start-up, guard, health, reset ---------------------------------------------


def test_mock_mode_starts_without_a_database(mock_app):
    assert mock_app.config["MODE"] == "mock"


def test_health_says_mock(mock_app):
    body = mock_app.test_client().get("/health").get_json()

    assert body["status"] == "ok"
    assert body["mode"] == "mock"


def test_mock_refuses_to_start_when_a_database_url_is_set(monkeypatch):
    monkeypatch.setenv("MOCK", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example/access")

    with pytest.raises(SystemExit):
        create_app()


def test_reset_empties_the_store(mock_app, call, auth):
    create(call)

    assert mock_app.test_client().post("/_mock/reset", headers=auth).status_code == 200
    assert call("GET", "/bookings/42/access")[0] == 404


def test_reset_needs_the_token(mock_app):
    assert mock_app.test_client().post("/_mock/reset").status_code == 401


def test_the_6_functions_still_need_the_token(mock_app):
    client = mock_app.test_client()

    assert client.post("/bookings/42/access", json={"start_time": FUTURE_START, "end_time": FUTURE_END}).status_code == 401
    assert client.get("/bookings/42/access").status_code == 401
    assert client.post("/bookings/42/check-in", json={"access_code": "00000000"}).status_code == 401


# --- create ---------------------------------------------------------------------


def test_create_returns_201_with_the_full_available_record(call):
    status, body = create(call)

    assert status == 201
    assert body["booking_id"] == 42
    assert len(body["access_code"]) == 8
    assert body["status"] == "available"
    assert body["expires_at"] == FUTURE_END
    assert body["checked_in_at"] is None
    assert body["checked_out_at"] is None
    assert body["revoked_at"] is None
    assert body["expired_at"] is None


def test_create_again_returns_200_with_the_record_unchanged(call):
    first = create(call)[1]

    status, body = create(call, end="2031-01-01T11:00:00+00:00")  # other times are ignored

    assert status == 200
    assert body == first


def test_create_on_a_used_record_returns_it_unchanged(call):
    to_used(call)

    status, body = create(call)

    assert status == 200
    assert body["status"] == "used"


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2030-01-01T10:00:00", "2030-01-01T11:00:00"),  # no offset
        ("tomorrow", FUTURE_END),  # not ISO 8601
        (FUTURE_END, FUTURE_START),  # end before start
    ],
)
def test_create_with_bad_times_is_400(call, start, end):
    assert create(call, start=start, end=end)[0] == 400


# --- read -----------------------------------------------------------------------


def test_read_returns_the_full_record(call):
    created = create(call)[1]

    status, body = call("GET", "/bookings/42/access")

    assert status == 200
    assert body == created


def test_read_of_an_overdue_record_expires_it_first(call):
    create(call, start=PAST_START, end=PAST_END)

    status, body = call("GET", "/bookings/42/access")

    assert status == 200
    assert body["status"] == "expired"
    assert body["expired_at"] is not None


# --- check-in -------------------------------------------------------------------


def test_check_in_with_the_right_code_makes_it_used(call):
    create(call)

    status, body = call("POST", "/bookings/42/check-in", {"access_code": code_of(call)})

    assert status == 200
    assert body["status"] == "used"
    assert body["checked_in_at"] is not None


def test_check_in_again_returns_200_with_the_same_record(call):
    to_used(call)
    first = call("GET", "/bookings/42/access")[1]

    status, body = call("POST", "/bookings/42/check-in", {"access_code": first["access_code"]})

    assert status == 200
    assert body == first


def test_check_in_with_a_wrong_code_is_403_and_changes_nothing(call):
    create(call)

    status, body = call("POST", "/bookings/42/check-in", {"access_code": "00000000"})

    assert status == 403
    assert body == {"error": "wrong access code"}
    assert call("GET", "/bookings/42/access")[1]["status"] == "available"


def test_check_in_on_an_overdue_record_is_409_expired(call):
    create(call, start=PAST_START, end=PAST_END)
    code = call("GET", "/bookings/42/access")[1]["access_code"]

    status, body = call("POST", "/bookings/42/check-in", {"access_code": code})

    assert status == 409
    assert body["status"] == "expired"


@pytest.mark.parametrize(("setup", "status"), [(to_revoked, "revoked"), (to_expired, "expired")])
def test_check_in_on_a_final_record_is_409(call, setup, status):
    setup(call)

    answer, body = call("POST", "/bookings/42/check-in", {"access_code": code_of(call)})

    assert answer == 409
    assert body["status"] == status


# --- check-out ------------------------------------------------------------------


def test_check_out_keeps_used_and_records_the_time_once(call):
    to_used(call)

    first_status, first = call("POST", "/bookings/42/check-out")
    second_status, second = call("POST", "/bookings/42/check-out")

    assert first_status == 200
    assert first["status"] == "used"  # no re-entry
    assert first["checked_out_at"] is not None
    assert second_status == 200
    assert second == first  # repeat: same record, same time


def test_check_out_without_check_in_is_409(call):
    create(call)

    status, body = call("POST", "/bookings/42/check-out")

    assert status == 409
    assert body == {"error": "not checked in", "status": "available"}


@pytest.mark.parametrize(("setup", "status"), [(to_revoked, "revoked"), (to_expired, "expired")])
def test_check_out_on_a_final_record_is_409(call, setup, status):
    setup(call)

    answer, body = call("POST", "/bookings/42/check-out")

    assert answer == 409
    assert body["status"] == status


# --- revoke ---------------------------------------------------------------------


def test_revoke_makes_it_revoked(call):
    create(call)

    status, body = call("POST", "/bookings/42/access/revoke")

    assert status == 200
    assert body["status"] == "revoked"
    assert body["revoked_at"] is not None


def test_revoke_again_returns_200_with_the_same_record(call):
    to_revoked(call)
    first = call("GET", "/bookings/42/access")[1]

    status, body = call("POST", "/bookings/42/access/revoke")

    assert status == 200
    assert body == first


@pytest.mark.parametrize(("setup", "status"), [(to_used, "used"), (to_expired, "expired")])
def test_revoke_on_used_or_expired_is_409(call, setup, status):
    setup(call)

    answer, body = call("POST", "/bookings/42/access/revoke")

    assert answer == 409
    assert body["status"] == status


# --- expire ---------------------------------------------------------------------


def test_expire_makes_it_expired(call):
    create(call)

    status, body = call("POST", "/bookings/42/access/expire")

    assert status == 200
    assert body["status"] == "expired"
    assert body["expired_at"] is not None


def test_expire_again_returns_200_with_the_same_record(call):
    to_expired(call)
    first = call("GET", "/bookings/42/access")[1]

    status, body = call("POST", "/bookings/42/access/expire")

    assert status == 200
    assert body == first


@pytest.mark.parametrize(("setup", "status"), [(to_used, "used"), (to_revoked, "revoked")])
def test_expire_on_used_or_revoked_is_409(call, setup, status):
    setup(call)

    answer, body = call("POST", "/bookings/42/access/expire")

    assert answer == 409
    assert body["status"] == status


# --- unknown booking ------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/bookings/999/access", None),
        ("POST", "/bookings/999/access/revoke", None),
        ("POST", "/bookings/999/check-in", {"access_code": "00000000"}),
        ("POST", "/bookings/999/check-out", None),
        ("POST", "/bookings/999/access/expire", None),
    ],
)
def test_unknown_booking_is_404_for_every_action_but_create(call, method, path, body):
    status, answer = call(method, path, body)

    assert status == 404
    assert answer == {"error": "access record not found"}


# --- logging --------------------------------------------------------------------


def test_a_409_writes_one_log_line_without_the_code(call, caplog):
    create(call)
    code = code_of(call)

    with caplog.at_level("WARNING", logger="access"):
        call("POST", "/bookings/42/check-out")
        call("POST", "/bookings/42/check-in", {"access_code": "00000000"})

    assert len(caplog.records) == 2
    assert "outcome=conflict status=available" in caplog.records[0].getMessage()
    assert "outcome=wrong_code" in caplog.records[1].getMessage()
    assert code not in caplog.text
    assert "00000000" not in caplog.text
