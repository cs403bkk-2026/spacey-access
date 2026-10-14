# Deploying the Access skeleton

Deployment is not yet enabled. A successful `/health` check proves that this
revision can reach its database; it does not prove that the Access domain works.
No migration or member-journey cutover runs in this workflow.

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
promise uninterrupted updates.

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
applies `migrations/*.sql` in filename order before the app starts, the way a
Nomad prestart task would; every file is idempotent, so it runs on every start.
The token is random per machine and kept in `.staging/` (ignored by Git).

```bash
scripts/staging.sh up            # build the current checkout and deploy it
scripts/staging.sh up <image>    # deploy a released image, e.g. ghcr.io/cs403bkk-2026/spacey-access:<sha>
scripts/staging.sh smoke         # /health, create, repeat create, check-in, no-token refusal
scripts/staging.sh rollback      # redeploy the previous image, then check /health shows its revision
scripts/staging.sh status        # containers, current and previous image, /health
scripts/staging.sh down          # stop, keep the data (reset also deletes it)
```

`up` only succeeds when `/health` reports the deployed revision. The smoke test
never prints an access code or the token.

**Found while rehearsing the first real release (2026-10-13/14):**

- `/health` is `ok` on a database with **no** `access` table: it runs `SELECT 1`
  only. It proves the connection, not the schema, so a deploy also needs the
  smoke test.
- Without the table, every create is a `500` (`UndefinedTable`). Nothing in the
  image or `release.yml` applies migrations, and the image doesn't contain
  `migrations/`. Production needs `001` applied before the next release.
- Applying `001` twice is safe (`already exists, skipping`).
- A repeat create for the same booking is a `500` (`UniqueViolation`), against
  the "safe to retry" contract. The smoke test keeps failing on this until it is
  fixed.
- Rollback practised: current checkout → `5d07ee8` release → `rollback`, with
  `/health` showing the expected revision after each step.

## SRE handoff

Amp checks the approved deployment workflow with her own access, reads
`nomad job status -namespace="$NOMAD_NAMESPACE" access`, and repeats the public
health check against the recorded revision. Record her actual result or blocker
in issue #5; platform verification alone does not establish her access.
