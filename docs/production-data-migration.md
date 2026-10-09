# Production data migration: copy access rows from `spacey`

A **one-time copy** of existing access codes from `spacey`'s production database into Access's
database, during the cutover ([migrate-from-spacey.md](migrate-from-spacey.md), step 3).
Script: [`scripts/migrate_from_spacey.py`](../scripts/migrate_from_spacey.py).

## What it copies

```mermaid
flowchart LR
    subgraph SRC["spacey database (read-only)"]
        SA["access<br/>booking_id · access_code · created_at"]
        SB["bookings<br/>id · space_id · start_time · end_time"]
    end
    subgraph TGT["Access database"]
        TA["access (11 columns)"]
    end
    SA --> J{{"LEFT JOIN on booking_id"}}
    SB --> J
    J -->|"INSERT … ON CONFLICT (booking_id) DO NOTHING"| TA
    SB -->|"booking ids still in spacey"| R{{"booking gone?"}}
    R -->|"available or used → removed"| TA
```

| Target column | Comes from |
|---|---|
| `booking_id`, `access_code`, `created_at` | `spacey` `access`, as is |
| `space_id`, `booked_start_time`, `booked_end_time` | `spacey` `bookings` (read **once**, here only) |
| `expires_at` | `booked_end_time` |
| `status` | `expired` if the booking has ended, otherwise `available`. Nobody has checked in yet: check-in is new |
| `checked_in_at`, `checked_out_at`, `removed_at` | empty: these events never happened in `spacey` |

### Cancellations

In `spacey`, cancelling a booking deletes its access row (`ON DELETE CASCADE`), so a cancelled booking
is never copied. But a booking can be cancelled **after** an earlier run has already copied it, for
example between steps 4 and 6 of the runbook. So every run also marks as `removed` each Access row
whose booking no longer exists in `spacey`'s **`bookings`** table.

- **Compared against `bookings`, never against `spacey`'s `access` table.** After the switch, new codes
  exist only in Access. Comparing against `spacey`'s `access` would remove all of them.
- Only `available` and `used` rows change. `expired` and `removed` rows are final (see
  [database.md](database.md)). `removed_at` is set once: a later run keeps the first one.
- The script stops, changing nothing, if `spacey` returns no bookings at all. That means a wrong
  database or user, and would otherwise remove every row.

## Safety

- **Dry run by default:** it prints what it would do and writes nothing. `--apply` writes.
- **The source is read-only:** the script reads `spacey` in a read-only transaction.
- **Safe to run again:** existing rows in Access are skipped, never overwritten.
- **One transaction on the target:** all rows or none, including the cancellations.
- **Known facts only:** no invented codes. A row without booking times keeps them empty.
- **It refuses** if both URLs are the same, or if the target has no `access` table yet.

## Runbook (cutover day)

| # | Step | Who |
|---|---|---|
| 1 | Snapshot both databases | SRE |
| 2 | Run `migrations/001_create_access_table.sql` on Access's database | Access |
| 3 | Dry run: `SOURCE_DATABASE_URL=<spacey, read-only user> TARGET_DATABASE_URL=<access> python scripts/migrate_from_spacey.py`. Check the counts | Access |
| 4 | `… --apply` | Access |
| 5 | Switch `spacey`'s `/unlock` to forward to Access (Purchase deploy) | Purchase |
| 6 | Run the script **again** with `--apply`, to pick up codes handed out between steps 4 and 5 | Access |
| 7 | Verify (below) | Access + SRE |

Steps 5–6 close the gap: a code handed out by `spacey` just before the switch is copied on the
second run, and existing codes are untouched.

## Verify

```sql
-- spacey (source)
SELECT count(*), count(DISTINCT access_code) FROM access;
-- Access (target): the same numbers, or more if Access granted new codes since
SELECT count(*), count(DISTINCT access_code) FROM access;
SELECT status, count(*) FROM access GROUP BY 1;   -- available / expired, plus removed for cancelled bookings
```

The script prints `cancelled in spacey, marked removed: N`. Cross-check it: the ids behind `N` must not
be in `spacey`'s `bookings`.

Then the journey: an **existing** booking's `/unlock` returns the **same** code as before the cutover.

## Tested (locally, 2026-10-08)

Against a stand-in for `spacey` `main`'s schema, with 3 rows (a future booking, a past booking, and a
booking without times):

| Run | Result |
|---|---|
| dry run | "inserted 3", nothing written |
| `--apply` | 3 rows: `available`, `expired`, and `available` with empty times |
| `--apply` again | inserted 0, already there 3 |
| same URL for both | refused, exit 1 |

And with cancellations (2026-10-09), stand-in `spacey` with 3 bookings, then booking 3 cancelled:

| Run | Result |
|---|---|
| `--apply` | 3 rows copied, `marked removed: 0` |
| booking 3 cancelled in `spacey`, dry run | `marked removed: 1`, nothing written |
| `--apply` | booking 3 is `removed` with `removed_at` set |
| `--apply` again | inserted 0, `marked removed: 0`, `removed_at` unchanged |

**Not tested against production data.** Run the dry run on a copy of production first (below).

## Dry run on a copy of production (ACC-11)

With the SRE: a **copy** of `spacey`'s production database as the source and an empty copy of Access's
database as the target. Never the live databases.

1. Run `migrations/001_create_access_table.sql` on the Access copy.
2. `SOURCE_DATABASE_URL=<spacey copy, read-only user> TARGET_DATABASE_URL=<access copy> python scripts/migrate_from_spacey.py`
3. `… --apply`, then run it a **second** time with `--apply`.
4. Run the queries under **Verify**.

Record the result in the ACC-11 issue:

| Check | Expected | Result |
|---|---|---|
| source rows | = `SELECT count(*) FROM access` on the copy of `spacey` | |
| target rows after first `--apply` | = source rows | |
| second `--apply` | `inserted 0`, `marked removed: 0` | |
| `marked removed` on first run | number of access rows without a booking (expected 0 on a clean copy) | |
| `count(DISTINCT access_code)` | same in source and target | |
