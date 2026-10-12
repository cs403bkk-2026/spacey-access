import secrets

from flask import current_app as app


def issue_access_code(booking_id):
    """Shared by the JSON API and the Unlock button.
    Returns (payload, status)."""
    with app.db.cursor() as cur:
        cur.execute(
            "SELECT id, paid FROM bookings WHERE id = %s", (booking_id,)
        )
        booking = cur.fetchone()

    if booking is None:
        return {"error": "booking not found"}, 404
    if not booking["paid"]:
        return {"error": "booking is not paid"}, 402

    # One code per booking: the first unlock stores one, every later unlock
    # gets that same code back. ON CONFLICT ... DO UPDATE (rather than DO
    # NOTHING) so the existing row is still returned.
    with app.db.cursor() as cur:
        cur.execute(
            "INSERT INTO access (booking_id, access_code) VALUES (%s, %s) "
            "ON CONFLICT (booking_id) DO UPDATE "
            "SET access_code = access.access_code "
            "RETURNING access_code",
            (booking_id, secrets.token_hex(4)),  # mocked lock integration
        )
        access_code = cur.fetchone()["access_code"]

    return {"booking_id": booking_id, "access_code": access_code}, 200
