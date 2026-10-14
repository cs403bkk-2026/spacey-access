# Runbook for Access

ACC-14 (#44). One section per alert in [alerts.md](alerts.md): what it means, what to
check first, how to stop the damage. Commands name **where** secrets live, never their
values. Never paste an access code, a token or a `DATABASE_URL` into a chat, an issue
or an incident report.

**Before you start:** say in the team channel that you are looking at it (that makes
you the Incident Commander until you hand over), and note the time.

Common checks used below:

```bash
# Is the job running, and since when?
nomad job status -namespace access access
# Recent allocation events (restarts, failed health checks, OOM)
nomad alloc status -namespace access <alloc-id>
# Is it up, and which revision?
curl -s https://access.cs403bkk26.space/health
# Recent request lines (gunicorn): status and duration per path
nomad alloc logs -namespace access <alloc-id> | tail -50
```

Your token needs `read-job` and `read-logs` on namespace `access`. A restart needs
`alloc-lifecycle`, and a redeploy needs `submit-job` (ask the platform owner if you
don't have them).

## Access down

**Means:** `/health` is failing, or Access isn't logging at all. SEV1: nobody can get
or use a code.

1. `curl -s https://access.cs403bkk26.space/health`:
   - **`503 {"error": "database unreachable"}`**: Access runs, the database doesn't
     answer. Check the `postgres` job (`nomad job status -namespace postgres postgres`)
     and tell the platform owner. Restarting Access won't help.
   - **No answer / 502 / 404**: the job, the allocation or the routing is down. Go on.
2. `nomad job status -namespace access access`: is the allocation `running`? Did a
   deployment just fail (then `auto_revert` may already be rolling back)?
3. Allocation events: `OOM killed`, image pull errors, a failed health check after a
   deploy?
4. **Mitigate:**
   - after a bad deploy: roll back (`deployment.md`, "Rollback runbook")
   - a stuck allocation: `nomad alloc restart -namespace access <alloc-id>`
   - a node problem: tell the platform owner (the job is pinned to `cs403bkk-nomad-1`)
5. Confirm `/health` is `200` with the expected `revision`, then tell Purchase and
   Frontend it's resolved.

## Server errors

**Means:** ≥ 5 responses were 5xx in 5 minutes. SEV2.

1. Which paths and statuses? Read the request lines in the logs.
2. **Did a deploy just happen?** Compare `/health`'s `revision` with the last release run.
   If yes, run the smoke checks; if they fail, roll back (Rollback runbook).
3. **Is the schema right?** A missing table or column gives 500s while `/health` stays
   green (this happened on 2026-10-14, see [incidents](incidents/)). Check in pgAdmin:
   `SELECT column_name FROM information_schema.columns WHERE table_name='access' ORDER BY ordinal_position;`
4. **Is it the known gap?** Repeated `POST /bookings/{id}/access` for the same booking
   returns 500 (Phase 2). If only that path fails on repeats, it's the known bug: note
   it, and push for the fix.
5. Once Access logs `outcome=db_error error_class=…` (ACC-13.5), the class name tells
   you the cause without exposing any value.

## Slow

**Means:** p95 above 1 s for 10 minutes, with real traffic. SEV3.

1. Which paths are slow (the duration is the last number before `ms` in each request
   line)?
2. Is the database slow for everyone? Check whether `spacey`'s requests are also slow.
3. Is the node busy? Ask the platform owner; Access has `cpu = 300`, `memory = 256`.
4. Record what you found; slow alone rarely needs a rollback.

## Restart loop

**Means:** ≥ 3 restarts in 15 minutes. SEV2.

1. Allocation events: the exit reason (crash, `OOM killed`, failed health check).
2. Logs of the **previous** run: `nomad alloc logs -namespace access <alloc-id>` right
   after a restart, to see the last lines before the crash.
3. Started after a deploy? Roll back. `OOM killed`? Ask for more memory in
   `deploy/access.nomad.hcl` through a PR.
4. Database down makes `/health` fail but **doesn't** need restarts; see "Access down".

## Code guessing

**Means:** many wrong codes for one booking in a short time. SEV3 (security).

1. Which `booking_id`? (The log line has it; it never has the code.)
2. Is it one member mistyping, or many attempts in seconds? Look at the timing.
3. If it looks like guessing: tell the architect and Purchase. Options are revoking that
   booking's access (`POST /bookings/{id}/access/revoke`, through `spacey`) and issuing
   a new one, or rate-limiting (a code change).
4. Never ask a member to send their code to check it.

## spacey can't reach Access

**Means:** `spacey` logged ≥ 3 `access_unavailable` in 5 minutes. SEV2.

1. Is Access up (`/health`)? If not, go to "Access down".
2. If Access is up: `spacey`'s `ACCESS_URL` or `SERVICE_TOKEN` is wrong or out of date.
   - `401` in Access's log means **the tokens differ**: compare the Nomad variables
     `nomad/jobs/access` and `nomad/jobs/spacey` (platform owner; don't print them).
   - No requests from `spacey` at all means the URL or the network is wrong.
3. **A leaked token:** if a token was seen in a log, chat or screenshot, ask the platform
   owner to set a new value in **both** variables, then restart both jobs so they read it.

## Expiry notice failing

**Means:** Access couldn't tell Purchase that a code expired, 3× in 15 minutes. SEV3.

1. Is `spacey` up? Is its `/bookings/{id}/access-expired` endpoint there?
2. Same token checks as above.
3. No member is blocked; the notices can be resent once Purchase answers. Record which
   bookings were affected (IDs only).

## After any SEV1 or SEV2

Write a report with [incident-report-template.md](incident-report-template.md) within two
working days, and link it from the issue.
