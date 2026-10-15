# Production Access ran without its `access` table

| | |
|---|---|
| **Date** | 2026-10-13 to 2026-10-14 |
| **Severity** | SEV3: every data call failed, but nothing called production Access yet, so no member was affected |
| **Status** | Resolved (two follow-ups open, see action items) |
| **Duration** | about 20.5 h, from the 478efb0 deploy (13 Oct 10:43 UTC) to the table being created (14 Oct, shortly before 07:21 UTC) |
| **Detected by** | the SRE, manually, after a local release rehearsal predicted it (no alert existed) |
| **Incident Commander** | Amp (SRE) |
| **Report author** | Amp (SRE) |

## Summary

The release workflow deployed Access with all its endpoints to production, but nothing
created the database table they need, so every data call would have returned 500.
`/health` stayed green throughout, because it only runs `SELECT 1`. The SRE found it,
reported it, and created the table by applying migrations `001` and `002` in one
transaction. Nobody was affected, because `spacey` doesn't call Access yet.

## Impact

- **Who:** nobody in practice. Production Access had no callers (`spacey` isn't wired
  to it yet), and no member journey used it.
- **What would have failed:** every create, read, check-in, check-out, revoke and expire
  call, with `500`.
- **For how long:** about 20.5 h with the 0.1 code (`478efb0`), plus about 20 minutes with
  the 0.2.0 code (`d8b72c9`, deployed 06:54 UTC) before the table existed.
- **Data:** none lost or exposed. The database was empty; there was nothing to lose.

## Timeline (UTC)

| Time | What happened |
|---|---|
| 13 Oct 08:48 | The release workflow starts deploying every push to `main` (#48, #49), without a separate production approval |
| 13 Oct 10:43 | Release `478efb0` deployed: all Access endpoints live on production. `/health` → `ok`. No step creates tables (decision D7: migrations are applied by hand) |
| 13–14 Oct | Local release rehearsal (ARCH-03) shows that on an empty database `/health` is `ok` while every create is `500 UndefinedTable` |
| 14 Oct, before 06:18 | SRE probes production with a harmless request (`POST /bookings/999999999/check-out`): `500` where `404` was expected. pgAdmin: `pg_tables` in `public` of the `access` database → **0 rows** |
| 14 Oct 06:16, 06:20 | Merges of #51 and #50 start release runs for `297cae7` and `d8b72c9` (contract 0.2.0, which also needs migration `002`) |
| 14 Oct 06:18 | Finding reported on #40, with a proposed fix |
| 14 Oct 06:34 | Product owner agrees the SRE applies the migrations as `team_access`. The architect asks not to release 0.2.0 before the table exists |
| 14 Oct 06:51 | ACC-19 (#55) opened |
| 14 Oct 06:54 | Release `d8b72c9` (0.2.0) finishes deploying: no approval gate, so it didn't wait for the table |
| 14 Oct ~07:00–07:20 | SRE checks access: no Nomad `alloc-exec`, so pgAdmin. Confirms `team_access` may create tables and that the app login `locks_user` is a member. Applies `001` + `002` from `main` @ `d8b72c9` in one transaction (`BEGIN; SET LOCAL ROLE team_access; … COMMIT;`) → `COMMIT` |
| 14 Oct ~07:20 | Verified: 12 columns, status check `available, used, expired, revoked`, owner `team_access`, 0 rows |
| 14 Oct 07:21 | Results posted on #55 and #40 |

## Root cause

**Code and schema are delivered separately, and nothing checks that they match.**

- Why did every data call fail? The `access` table didn't exist.
- Why didn't it exist? Migrations are applied by hand (D7), and no one applied `001`
  when Access first went live.
- Why didn't the release notice? The image didn't contain `migrations/`, the workflow
  has no migration step, and its only check after a deploy is `/health`, which runs
  `SELECT 1`. A database with no tables passes it.
- Why did the 0.2.0 release still go out before the table existed? Since #49, a push to
  `main` deploys without approval, so "don't release yet" couldn't be enforced.
- Why did no one find out sooner? There were no alerts, and no caller yet to fail.

## What went well

- The local rehearsal predicted exactly this failure, so it was recognised immediately.
- The fix was low-risk: idempotent migrations, applied in one transaction, so a failure
  would have changed nothing.
- It was found and fixed before `spacey` was wired to Access, so no member was affected.
- Before/after state was recorded on the issues.

## What went badly

- Production ran broken for about 20.5 h with a green health check.
- The 0.2.0 release deployed before its schema, despite a request to wait.
- The procedure in the ticket needed Nomad `alloc-exec`, which the SRE doesn't have.
- The table is owned by `team_access` rather than the app's own login (accepted risk,
  awaiting confirmation).

## Where we got lucky

- Nothing called production Access yet. With `spacey` wired up, this would have been a
  SEV1: no member could have received or used a code.

## Action items

| Action | Owner | Issue | Status |
|---|---|---|---|
| Record the production schema, and the rule "apply a migration before merging the release that needs it" | SRE | #55, PR #56 | In review |
| Ship `migrations/` in the image and apply them before the app starts (local test now; Nomad prestart task proposed) | SRE | #40, PR #54 | In review / proposed |
| Check more than `/health` after a deploy: a smoke test that runs a real query | SRE | #40, PR #54 (local); release workflow: to propose | In review |
| Alerts on 5xx and on `/health`, so the next one is noticed in minutes | SRE | #44 | Docs in review; rules need the platform |
| In-allocation read probe, and confirm or change the table owner | Architect / platform owner | #55 | Open |
| Fix the repeat create `500` before `spacey` calls Access | Developers | Phase 2 | Open |
