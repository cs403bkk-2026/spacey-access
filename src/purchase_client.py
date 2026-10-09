"""Calls Access makes to Purchase. The only module that talks to Purchase.

DUMMY: nothing is sent yet. Purchase doesn't have the receiving endpoint, so
each function returns the request it would make.
"""

import os

PURCHASE_URL = os.getenv("PURCHASE_URL", "http://localhost:8000")


def notify_purchase_expired(booking_id):
    """Access -> Purchase: the access expired by Access's clock."""
    return {
        "method": "POST",
        "url": f"{PURCHASE_URL}/bookings/{booking_id}/access-expired",
        # The same shared token Purchase sends to us (ACC-08); never hardcoded.
        "headers": {"Authorization": f"Bearer {os.getenv('SERVICE_TOKEN', '')}"},
        "json": {"booking_id": booking_id, "status": "expired"},
    }
