"""One way to write timestamps (ARCH-01): ISO 8601, UTC, e.g. 2026-10-13T08:30:00+00:00."""

from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_time(value):
    """A datetime with an offset, or None if the text isn't ISO 8601 with one."""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else None


def iso(value):
    """A stored timestamp as the contract writes it (ISO 8601, UTC); None stays None."""
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")
