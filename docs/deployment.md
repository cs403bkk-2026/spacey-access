# Deploying Access

Every push to `main` deploys to production (see "Release and verification"). A
successful `/health` check proves that this revision can reach its database; it
does not prove that the Access domain works. No migration or member-journey
cutover runs in this workflow: migrations are applied by hand, **before** the
release that needs them (see "Production schema").

## Platform setup

The platform owner must confirm the namespace, hostname and runtime variable path
before creating them. Proposed values are `access`, `access.cs403bkk26.space` and
`nomad/jobs/access`. The job ID is `access`; keep the variable under its job-owned
path so its workload identity can read it without broader variable permissions.

The runtime database is `access`, with login `locks_user`, membership role
`team_access`, and ownership limited to that database's `public` schema. The
platform owner stores the connection URL in the runtime variable's `database_url`
key and the shared spacey/Access service token in its `service_token`
key. Neither secret may be passed as a job argument, committed, or copied into
GitHub. The Nomad job exposes the token to Access as `SERVICE_TOKEN`.

`spacey` sends the same secret as a Bearer token on all 6 access calls. Provision
it only through the platform's secret store; `spacey`'s CI should use its CI
secret store. Tests use a disposable fixture token, not the deployed secret.

Before release, the platform owner checks:

- The namespace, scoped deployment token and job-owned variable exist.
- Traefik watches the namespace and its discovery policy permits reading it.
- DNS and TLS reach the course ingress for the approved hostname.
- Nomad clients can pull the image from GHCR, using public package visibility
  or separately provisioned registry authentication.
- The application node can reach the database and has capacity for the job.
- GitHub's `production` environment does not require a separate release approval.

Set repository variables `NOMAD_NAMESPACE`, `APP_HOSTNAME`, `RUNTIME_VARIABLE`
to the approved identifiers. Set `DEPLOY_ENABLED=true` only after setup and review.
Put `NOMAD_ADDR` and a fresh namespace-scoped `NOMAD_TOKEN` in the protected
`production` environment secrets. An expired or default-only token is unsuitable.

## Release and verification

Every push to `main` starts the `release` workflow. The release owner can also
retry it manually from `main`. With `DEPLOY_ENABLED=true`, deployment proceeds
automatically after the build checks pass, without a separate production approval.
The workflow runs the full test suite, builds an image, exercises that image
against disposable Postgres, and publishes that same image. Deployment uses its
registry digest, waits for Nomad's rollout, then requires `/health` to report both
`status: ok` and the exact source revision. A superseded main revision is rejected.

For an approved manual release, export the platform-provided `NOMAD_ADDR`,
`NOMAD_TOKEN`, `NOMAD_NAMESPACE`, `APP_HOSTNAME`, `RUNTIME_VARIABLE`, plus the
reviewed `REVISION` and immutable `IMAGE` reference, then run:

```bash
nomad job run -var="image=${IMAGE}" -var="revision=${REVISION}" \
  -var="namespace=${NOMAD_NAMESPACE}" -var="hostname=${APP_HOSTNAME}" \
  -var="runtime_variable=${RUNTIME_VARIABLE}" deploy/access.nomad.hcl
curl --fail --silent --show-error "https://${APP_HOSTNAME}/health" |
  jq -e --arg revision "${REVISION}" '.status == "ok" and .revision == $revision'
```

Record the URL, source SHA, image digest, workflow run, Nomad deployment ID and
health response in issue #5. No deployed revision is claimed by this document.

Nomad can revert an unhealthy update to a previous stable job; the initial
deployment has no previous stable version. Public routing failure can occur even
after a healthy allocation. In either case the release owner inspects the failed
deployment and either stops the initial job or redeploys the recorded previous
digest/revision, then verifies health again. This single-instance job does not
promise uninterrupted updates. The steps are in "Rollback runbook" below.

## Rollback runbook

**When:** a release is healthy but wrong: the smoke test fails, 5xx responses
appear, or behaviour is wrong. (An *unhealthy* release is already reverted by
Nomad's `auto_revert`.)

1. **Find the last good revision:** `nomad job history -namespace access access`
   (versions with their `revision` meta), or the previous successful `release` run
   in GitHub Actions (its image digest and SHA).
2. **Check the schema still fits the old code.** Migrations only move forward, so a
   rollback **across a migration** only works if that migration is
   backward-compatible with the older code. **`002` is not:** it renames
   `removed_at` to `revoked_at`, so `478efb0` (0.1) on the `002` schema is healthy
   but breaks (`/access/remove` → 500 `UndefinedColumn`). If the schema doesn't
   fit, fix forward instead of rolling back.
3. **Redeploy the old revision,** in one of two ways:
   - `nomad job revert -namespace access access <version>`, or
   - the manual `nomad job run` above, with the recorded `IMAGE` digest and `REVISION`.

   Re-running the `release` workflow doesn't work: it refuses a revision that is no
   longer `main`.
4. **Verify:** `/health` reports the old `revision`, then run the smoke checks.
5. **Fix forward on `main`** (revert the bad commit). The next push redeploys.
6. **Record** it in the incident report (ACC-14, #44): what broke, when, which
   revision, how long.

**First deploy:** there is nothing to revert to. Stop the job
(`nomad job stop -namespace access access`) and fix forward.

**Staging:** `scripts/staging.sh rollback` redeploys the previous image and only
reports success when `/health` shows its revision **and** the smoke test passes.
Practised twice on 2026-10-14:

- before `002` existed: `0a1b0ab` → `5d07ee8` → back to `0a1b0ab`, all healthy;
- with `002`: checkout (0.2.0) → `478efb0` (0.1) → `up` reports **"deployed but
  broken"** (`/health` ok; read → 405, revoke → 404) → `rollback` to the
  checkout → smoke passes. This is the case `/health` alone can't see.

## Staging (local, until the production deploy moves to Nomad)

**Decision:** staging runs with Docker Compose on the SRE's machine for now, and
moves to a Nomad `access-staging` job together with the next production deploy.
**Why:** deploying staging to Nomad needs a job-owned variable for its secrets,
and the SRE's token has no `variables` permission yet. Local staging still tests
what breaks releases most (the image, migrations on a fresh database, the API),
but not the Nomad job file, Traefik or TLS. For the move, `deploy/access.nomad.hcl`
needs an environment variable for its job ID, service name and Traefik router
(all hard-coded `access` today), so a staging copy doesn't collide with
production, and its secrets come from `nomad/jobs/access-staging`.

`compose.staging.yaml` runs a given image against its own database (port
`5444`, separate from the dev database on `5434`). A one-shot `migrate` service
applies the migrations **shipped in that same image** (`/app/migrations`, copied
in by the `Dockerfile`) in filename order before the app starts, so staging only
ever runs code/schema pairs that production would. This is the shape of the Nomad
prestart task later. Every file is idempotent, so it runs on every start. Images
built before `migrations/` was copied in apply nothing. The token is random per
machine and kept in `.staging/` (ignored by Git and Docker).

```bash
scripts/staging.sh up            # build the current checkout, deploy it, then smoke
scripts/staging.sh up <image>    # same for a released image, e.g. ghcr.io/cs403bkk-2026/spacey-access:<sha>
scripts/staging.sh smoke         # the API checks on their own
scripts/staging.sh rollback      # redeploy the previous image, then smoke
scripts/staging.sh status        # containers, current and previous image, /health
scripts/staging.sh down          # stop, keep the data (reset also deletes it)
```

`up` and `rollback` only succeed when `/health` reports the deployed revision
**and** the smoke test passes, because `/health` alone is green on a broken API.
The smoke test follows the 0.2.0 contract: read of an unknown booking (404, which
runs the full `SELECT`), create, read back, check-in, revoke, and refusal without
a token. A gap the team already tracks is reported as `KNOWN` and doesn't fail the
deploy (today: repeat create → 500, Phase 2). The smoke test never prints an
access code or the token.

**Found while rehearsing the first real release (2026-10-13/14):**

- `/health` is `ok` on a database with **no** `access` table: it runs `SELECT 1`
  only. It proves the connection, not the schema, so a deploy also needs the
  smoke test.
- Without the table, every create is a `500` (`UndefinedTable`). Nothing in the
  image or `release.yml` applies migrations, and the image doesn't contain
  `migrations/`. Production turned out to have no table either; fixed on
  2026-10-14 (see "Production schema").
- Applying `001` twice is safe (`already exists, skipping`). Staging applies `001`
  and `002` on every start.
- A repeat create for the same booking is a `500` (`UniqueViolation`), against
  the "safe to retry" contract. Still true on 0.2.0 (2026-10-14); the smoke test
  reports it as `KNOWN` until it is fixed.
- Rollback: see "Rollback runbook" (practised before and after `002`).

## Decisions (ARCH-03)

One line of why each. "Proposed" means it needs the team's agreement before it changes.

| Topic | Decision | Why |
|---|---|---|
| Staging | Docker Compose on the SRE's machine now (`scripts/staging.sh`); a Nomad `access-staging` job later | No Nomad `variables` permission for staging secrets yet; local staging still catches image, migration and API problems |
| Databases per environment | Production: database `access`. Staging: its own Postgres container. Never shared | Staging creates and resets data; production records are never deleted (SP-R12) |
| Secrets per environment | One token and database URL per environment: production in `nomad/jobs/access`, local staging in `.staging/` (random per machine), Nomad staging later in `nomad/jobs/access-staging` | A staging token must never open production |
| Release per environment | A push to `main` deploys to production. Staging runs **before** merging (`scripts/staging.sh up` + `smoke` on the PR branch) | The workflow has no staging step yet, so staging must happen before the merge |
| Migrations | The image ships `migrations/` (`Dockerfile`), and staging applies them from the deployed image. **Production today:** manual (D7), applied **before** merging the release that needs them. **Proposed:** a Nomad prestart task that runs the image's migrations, like staging's `migrate` service | Production ran without its table because nobody applied `001`. Running migrations from the image keeps code and schema paired; all files are idempotent |
| Rollback across a migration | Only if the migration is backward-compatible with the older code; `002` is not | Old code on a newer schema stays healthy but breaks (`478efb0` on `002`: revoke/remove fail) |
| Service-to-service routing | `spacey` reaches Access through the public hostname: `ACCESS_URL=https://access.cs403bkk26.space` | `spacey` (namespace `startup`) and Access (namespace `access`) are in different namespaces; Nomad's built-in service discovery only works within a namespace |
| Health | `/health` (`SELECT 1`) stays a liveness check for Nomad's routing and `auto_revert`. After a deploy, also run the smoke test | It proves the connection, not the schema or the API: it was green with no table |
| Restart on failed health | No `check_restart` on `/health` | A restart can't fix a database outage; it only adds noise |
| Restart policy | **Proposed:** `restart { attempts = 3, interval = "5m", mode = "fail" }`, like `spacey` | Access uses Nomad's defaults today, unlike `spacey`; a crash loop should stop and be visible |
| Logging | Follow `docs/logging.md` (ACC-13.5): `key=value` lines, never the access code, token or `DATABASE_URL` | One searchable format in Loki; secrets must not leak |
| Dashboards and alerts | Grafana dashboard and alert rules come from ACC-14 (#44) | Thresholds need the log signals from ACC-13.5 and a week of baseline |
| Rollback | See "Rollback runbook" | `auto_revert` only covers unhealthy releases, not "healthy but wrong" |
| Backups | **To verify:** a `pg-backup` batch job runs in namespace `postgres`. Check whether it includes the `access` database, and try one restore | Access records are never deleted (SP-R12); they are the audit trail |
| Mock in production | No production job sets `MOCK=1` (`deploy/access.nomad.hcl` doesn't). The ARCH-01 mock refuses to start when `DATABASE_URL` is set | A mock would hand out fake codes |
| Capacity and placement | Keep `count = 1`, pinned to `cs403bkk-nomad-1` | Simple, and enough for a course cluster; a node problem or a deploy means short downtime, accepted on purpose |

## SRE handoff

Amp checks the approved deployment workflow with her own access, reads
`nomad job status -namespace="$NOMAD_NAMESPACE" access`, and repeats the public
health check against the recorded revision. Record her actual result or blocker
in issue #5; platform verification alone does not establish her access.
