-- Migration 002: contract 0.2.0 (ARCH-02). Status `removed` becomes `revoked`,
-- and expiry gets its own timestamp.
-- Safe to run twice: each step checks first, so a second run changes nothing.
-- No BEGIN/COMMIT here, so tests can run it inside a transaction they roll back.
-- Apply it as one transaction: psql ... -v ON_ERROR_STOP=1 --single-transaction -f

-- 1. removed_at -> revoked_at, only if removed_at still exists.
--    'access'::regclass is the table the ALTER below changes (same search_path).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_attribute
        WHERE attrelid = 'access'::regclass AND attname = 'removed_at' AND NOT attisdropped
    ) THEN
        ALTER TABLE access RENAME COLUMN removed_at TO revoked_at;
    END IF;
END $$;

-- 2. When the record expired. Set once, like revoked_at.
ALTER TABLE access ADD COLUMN IF NOT EXISTS expired_at TIMESTAMPTZ;

-- 3. Drop the old CHECK, convert the rows, then add the new CHECK. In this order,
--    so no row ever violates the constraint. revoked_at keeps the old removed_at.
ALTER TABLE access DROP CONSTRAINT IF EXISTS access_status_check;
UPDATE access SET status = 'revoked' WHERE status = 'removed';
ALTER TABLE access ADD CONSTRAINT access_status_check
    CHECK (status IN ('available', 'used', 'expired', 'revoked'));
