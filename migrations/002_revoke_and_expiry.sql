-- Idempotent: safe to run more than once.

-- 1. Rename removed_at → revoked_at (only if removed_at still exists)
DO $$ BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='access' AND column_name='removed_at'
  ) THEN
    ALTER TABLE access RENAME COLUMN removed_at TO revoked_at;
  END IF;
END $$;

-- 2. Add expired_at column if not already there
ALTER TABLE access ADD COLUMN IF NOT EXISTS expired_at TIMESTAMPTZ;

-- 3. Drop old CHECK, migrate 'removed' rows, add new CHECK
ALTER TABLE access DROP CONSTRAINT IF EXISTS access_status_check;
UPDATE access SET status = 'revoked', revoked_at = COALESCE(revoked_at, now())
  WHERE status = 'removed';
ALTER TABLE access ADD CONSTRAINT access_status_check
  CHECK (status IN ('available', 'used', 'expired', 'revoked'));