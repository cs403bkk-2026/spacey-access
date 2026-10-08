"""Copy existing access rows from spacey's database into Access's database, once.

Reads spacey (read-only transaction): access(booking_id, access_code, created_at)
joined to bookings for the space and interval. Writes Access's `access` table.

- Dry run by default; pass --apply to write.
- Safe to run again: a booking that already has a row in Access is skipped,
  never overwritten (rows granted by Access after cutover stay as they are).
- Known facts only: no codes are invented. A row whose booking has no
  start/end keeps those columns empty.

Usage:
    SOURCE_DATABASE_URL=... TARGET_DATABASE_URL=... python scripts/migrate_from_spacey.py [--apply]

See docs/ACC/production-data-migration.md.
"""
import argparse
import os
import sys
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

SOURCE_QUERY = """
    SELECT a.booking_id, a.access_code, a.created_at,
           b.space_id, b.start_time, b.end_time
    FROM access a
    LEFT JOIN bookings b ON b.id = a.booking_id
    ORDER BY a.booking_id
"""

INSERT = """
    INSERT INTO access (booking_id, access_code, status, created_at,
                        booked_start_time, booked_end_time, space_id, expires_at)
    VALUES (%(booking_id)s, %(access_code)s, %(status)s, %(created_at)s,
            %(start_time)s, %(end_time)s, %(space_id)s, %(end_time)s)
    ON CONFLICT (booking_id) DO NOTHING
"""


def env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        sys.exit(f"{name} is required")
    return value


def read_source(url: str) -> list[dict]:
    with psycopg.connect(url, row_factory=dict_row) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(SOURCE_QUERY)
            return cur.fetchall()


def status_for(row: dict, now: datetime) -> str:
    # Every spacey row exists because the code was handed out; nobody has
    # checked in yet (check-in is new). Past bookings are already expired.
    if row["end_time"] is not None and row["end_time"] <= now:
        return "expired"
    return "available"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="write to the target (default: dry run)")
    args = parser.parse_args()

    source_url, target_url = env("SOURCE_DATABASE_URL"), env("TARGET_DATABASE_URL")
    if source_url == target_url:
        sys.exit("SOURCE_DATABASE_URL and TARGET_DATABASE_URL must differ")

    now = datetime.now(timezone.utc)
    rows = read_source(source_url)
    for row in rows:
        row["status"] = status_for(row, now)

    no_booking = sum(1 for r in rows if r["start_time"] is None)
    expired = sum(1 for r in rows if r["status"] == "expired")
    print(f"source rows: {len(rows)}  (expired: {expired}, without a booking interval: {no_booking})")

    with psycopg.connect(target_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('access') IS NOT NULL")
            if not cur.fetchone()[0]:
                sys.exit("target has no access table: run migrations/001_create_access_table.sql first")
            cur.execute("SELECT count(*) FROM access")
            before = cur.fetchone()[0]

            inserted = 0
            for row in rows:
                cur.execute(INSERT, row)
                inserted += cur.rowcount

            cur.execute("SELECT count(*) FROM access")
            after = cur.fetchone()[0]

            print(f"target rows: before {before}, after {after}  "
                  f"(inserted {inserted}, already there {len(rows) - inserted})")

            if args.apply:
                conn.commit()
                print("applied")
            else:
                conn.rollback()
                print("dry run: nothing written (pass --apply to write)")


if __name__ == "__main__":
    main()
