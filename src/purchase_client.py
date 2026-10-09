"""Calls Access makes to Purchase. The only module that talks to Purchase.

DUMMY: nothing is sent yet. Purchase doesn't have the receiving endpoint, so
each function returns the request it would make.
"""

import os

PURCHASE_URL = os.getenv("PURCHASE_URL", "http://localhost:8000")


def notify_purchase_expired(booking_id):
    """Access -> Purchase: the access expired by Access's clock."""
    service_token = os.getenv("SERVICE_TOKEN")
    if not service_token:
        raise RuntimeError("SERVICE_TOKEN must be configured")

    return {
        "method": "POST",
        "url": f"{PURCHASE_URL}/bookings/{booking_id}/access-expired",
        "headers": {"Authorization": f"Bearer {service_token}"},
        "json": {"booking_id": booking_id, "status": "expired"},
    }
