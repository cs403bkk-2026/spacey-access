-- Migration 001: Create access table
-- Owned exclusively by the Access service.
-- No other service reads or writes this table.

CREATE TABLE IF NOT EXISTS access (
    booking_id          INTEGER      PRIMARY KEY,
    access_code         TEXT         NOT NULL,
    status              TEXT         NOT NULL DEFAULT 'available'
                                     CHECK (status IN ('available', 'used', 'expired', 'removed')),
    booked_start_time   TIMESTAMPTZ,
    booked_end_time     TIMESTAMPTZ,
    space_id            INTEGER,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    expires_at          TIMESTAMPTZ,
    checked_in_at       TIMESTAMPTZ,
    checked_out_at      TIMESTAMPTZ,
    removed_at          TIMESTAMPTZ
);

-- Note: no ON DELETE CASCADE —-records are never deleted (SP-R12)