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
key and the shared Purchase/Access service token in its `service_token`
key. Neither secret may be passed as a job argument, committed, or copied into
GitHub. The Nomad job exposes the token to Access as `SERVICE_TOKEN`.

Purchase sends the same secret as a Bearer token on create, remove, and expire
calls. Provision it only through the platform's secret store;
Purchase's CI callers should use their CI secret store. Tests use a disposable
fixture token, not the deployed secret.

Before release, the platform owner checks:

- The namespace, scoped deployment token and job-owned variable exist.
- Traefik watches the namespace and its discovery policy permits reading it.
- DNS and TLS reach the course ingress for the approved hostname.
- Nomad clients can pull the image from GHCR, using public package visibility
  or separately provisioned registry authentication.
- The application node can reach the database and has capacity for the job.
- GitHub's `production` environment requires the designated release review.

Set repository variables `NOMAD_NAMESPACE`, `APP_HOSTNAME`, `RUNTIME_VARIABLE`
to the approved identifiers. Set `DEPLOY_ENABLED=true` only after setup and review.
Put `NOMAD_ADDR` and a fresh namespace-scoped `NOMAD_TOKEN` in the protected
`production` environment secrets. An expired or default-only token is unsuitable.

## Release and verification

After review and merge, the release owner manually runs the `release` workflow
from `main`. It runs the full test suite, builds an image, exercises that image
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

## SRE handoff

Amp checks the approved deployment workflow with her own access, reads
`nomad job status -namespace="$NOMAD_NAMESPACE" access`, and repeats the public
health check against the recorded revision. Record her actual result or blocker
in issue #5; platform verification alone does not establish her access.
