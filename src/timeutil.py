"""One way to write timestamps (ARCH-01): ISO 8601, UTC, e.g. 2026-10-13T08:30:00+00:00."""

from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
