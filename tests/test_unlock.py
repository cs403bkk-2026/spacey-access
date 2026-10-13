"""POST /bookings/{id}/unlock (PR #32, src/access.py issue_access_code).

The unit tests swap the database for a small in-memory fake, so they test the
unlock logic itself: unknown -> 404, unpaid -> 402, paid -> a code, and the
same code on every later unlock.

The last test runs against the real Access test database and shows a known
problem: issue_access_code reads `bookings`, which only exists in spacey's
database, not in Access's. It is marked xfail until that is fixed (the paid
check belongs to Purchase in spacey, which then calls POST /bookings/{id}/access).
"""

import pytest


class FakeCursor:
    """Answers the two queries issue_access_code runs."""

    def __init__(self, db):
        self.db = db
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        booking_id = params[0]
        if sql.startswith("SELECT id, paid FROM bookings"):
            booking = self.db.bookings.get(booking_id)
            self.result = None if booking is None else {"id": booking_id, **booking}
        elif sql.startswith("INSERT INTO access"):
            # ON CONFLICT ... DO UPDATE SET access_code = access.access_code:
            # the first code is kept and returned on every later call.
            code = self.db.access.setdefault(booking_id, params[1])
            self.result = {"access_code": code}
        else:
            raise AssertionError(f"unexpected SQL: {sql}")

    def fetchone(self):
        return self.result


class FakeDB:
    def __init__(self, bookings):
        self.bookings = bookings  # {booking_id: {"paid": bool}}
        self.access = {}          # {booking_id: access_code}

    def cursor(self):
        return FakeCursor(self)


@pytest.fixture()
def fake_db(app):
    db = FakeDB(bookings={1: {"paid": True}, 2: {"paid": False}, 3: {"paid": True}})
    real_db, app.db = app.db, db
    yield db
    app.db = real_db


def test_unlock_an_unknown_booking_is_404(app, fake_db):
    response = app.test_client().post("/bookings/999/unlock")

    assert response.status_code == 404
    assert response.get_json() == {"error": "booking not found"}
    assert fake_db.access == {}


def test_unlock_an_unpaid_booking_is_402_and_creates_no_code(app, fake_db):
    response = app.test_client().post("/bookings/2/unlock")

    assert response.status_code == 402
    assert response.get_json() == {"error": "booking is not paid"}
    assert 2 not in fake_db.access


def test_unlock_a_paid_booking_returns_a_code(app, fake_db):
    response = app.test_client().post("/bookings/1/unlock")

    assert response.status_code == 200
    body = response.get_json()
    assert body["booking_id"] == 1
    assert len(body["access_code"]) == 8  # secrets.token_hex(4)
    assert fake_db.access[1] == body["access_code"]


def test_unlocking_twice_returns_the_same_code(app, fake_db):
    client = app.test_client()

    first = client.post("/bookings/1/unlock").get_json()["access_code"]
    second = client.post("/bookings/1/unlock").get_json()["access_code"]

    assert first == second


def test_two_bookings_get_their_own_codes(app, fake_db):
    client = app.test_client()

    one = client.post("/bookings/1/unlock").get_json()["access_code"]
    three = client.post("/bookings/3/unlock").get_json()["access_code"]

    assert one != three


@pytest.mark.xfail(
    strict=True,
    reason="issue_access_code reads `bookings`, which is spacey's table, not "
    "Access's: on the real Access database every unlock is a 500. Remove this "
    "mark once the paid check moves to Purchase (spacey).",
)
def test_unlock_works_on_the_real_access_database(client):
    response = client.post("/bookings/1/unlock")

    assert response.status_code != 500