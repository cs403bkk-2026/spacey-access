# spacey-access

Access service for the Spacey booking platform.  
This module owns everything related to issuing and managing access codes for confirmed bookings.

## What this service does

- Issues one access code per booking (code is stored and reused on repeat requests)
- Manages the `access` table — no other service reads or writes it
- Offers 6 access functions: create, read, revoke (cancellation or refund), check-in, check-out and expire
- Has exactly one caller, `spacey`: Frontend and Purchase go through `spacey`'s access functions, and all 6 need the service token
- Expiry is checked lazily (on touch), not via a scheduled job

**State machine** (contract [`openapi.yaml`](openapi.yaml) 0.2.0):

```text
available → used      (check-in)
used → used           (check-out: records checked_out_at; no re-entry)
available → expired   (expire by Purchase, or the time check once expires_at has passed)
available → revoked   (revoke: booking cancelled or refunded by Purchase)
used, expired and revoked are final; any other move is a 409
```

For the full business rules, see [spacey-business-rules](https://github.com/cs403bkk-2026/spacey-business-rules).

---

## Setup

Status: **Phase 1**. The service runs, connects to its database, and serves `/health`, its OpenAPI document and the 6 access endpoints of contract 0.2.0, with real SQL. The full lifecycle (`409`s, the time check, create answering `200` on a repeat) is Phase 2; [docs/api.md](docs/api.md) lists the gaps.

### Quick start (Docker)

Requires Docker. Ports **8003** (app) and **5434** (Postgres) must be free.

```bash
docker compose up -d --build --wait
curl http://127.0.0.1:8003/health
# {"revision":"compose","status":"ok"}
docker compose down        # add -v to also wipe the database
```

### Endpoints

| Method | Path | What it does |
|--------|------|--------------|
| GET | `/health` | `200 {"status": "ok", "revision": ...}`, or `503 {"status": "error", "error": "database unreachable"}` if Postgres is down |
| GET | `/openapi.yaml` | The API contract ([openapi.yaml](openapi.yaml)), OpenAPI 3.0.3 |
| POST | `/bookings/{booking_id}/access` | Create the access record (token) |
| GET | `/bookings/{booking_id}/access` | Read the access record (token) |
| POST | `/bookings/{booking_id}/access/revoke` | Revoke it: the booking was cancelled or refunded (token) |
| POST | `/bookings/{booking_id}/check-in` | Check in with the access code (token) |
| POST | `/bookings/{booking_id}/check-out` | Check out (token) |
| POST | `/bookings/{booking_id}/access/expire` | Expire it: the booking ended by Purchase's clock (token) |

Who calls what, every answer and the real-mode gaps: [docs/api.md](docs/api.md).

### Run without Docker (for development)

Requires Python 3.12. Postgres still runs in Docker:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
docker compose up db -d
flask --app app run --port 8003 --debug
```

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://access:access@localhost:5434/access` | Postgres connection string. The app exits at start with a clear message if it can't connect |
| `SERVICE_TOKEN` | *(none)* | Shared secret between `spacey` and Access. `spacey` sends it as `Authorization: Bearer <token>` on all 6 access calls; without it they get `401`. In production it comes from the Nomad variable (key `service_token`), never from Git |
| `APP_REVISION` | `local` | Shown by `/health`, so a deployment can confirm which commit is live |

The Nomad runtime variable at the configured `RUNTIME_VARIABLE` path stores the
secret under `service_token`; the job exposes it as `SERVICE_TOKEN`.
`spacey` sends it as a Bearer token on every access call.
Keep the value in platform and CI secret stores only. Never commit a `.env` file
or real credentials. The values in `compose.yaml` are local placeholders.

### Ports

| Service | Host port | Container port |
|---------|-----------|----------------|
| app (gunicorn) | 8003 | 8000 |
| db (Postgres 16) | 5434 | 5432 |

### Migrations

Migrations run manually with `psql` (decision D7, [ACC-01](https://github.com/cs403bkk-2026/spacey-access/issues/7)). Apply them in filename order before starting the app for the first time, or after adding a new migration file. Each file runs as one transaction and stops at the first error:

```bash
psql postgresql://access:access@localhost:5434/access -v ON_ERROR_STOP=1 --single-transaction -f migrations/001_create_access_table.sql
psql postgresql://access:access@localhost:5434/access -v ON_ERROR_STOP=1 --single-transaction -f migrations/002_revoke_and_expiry.sql
```

Every migration is safe to run twice and then changes nothing: 001 uses `CREATE TABLE IF NOT EXISTS`, and 002 (contract 0.2.0: `revoked`, `revoked_at`, `expired_at`) checks before each step. The tests apply both files themselves, inside transactions they roll back; CI has no migration step.

### Run tests

Tests need the local database (`docker compose up db -d`):

```bash
pytest
```

CI (`.github/workflows/ci.yml`) runs the same tests against Postgres 16 on every pull request, then builds the Docker image (no push, no deploy).

The manual [release workflow](.github/workflows/release.yml) tests, publishes and deploys a reviewed main revision when explicitly enabled. See [deployment setup and SRE checks](docs/deployment.md).

> **Important:** Tests run against a local disposable database only. Never point `DATABASE_URL` at production.

---

## Project structure

```text
spacey-access/
├── app.py                 # Entry point: create_app() connects to the database, registers src/api.py
├── src/
│   ├── api.py             # HTTP only: routes, service token, status codes
│   ├── db.py              # SQL only: connection (fail fast) and one function per access operation
│   └── purchase_client.py # Access -> spacey expiry notice (nothing sent yet)
├── openapi.yaml           # The API contract (0.2.0), served at /openapi.yaml
├── migrations/
│   ├── 001_create_access_table.sql
│   └── 002_revoke_and_expiry.sql
├── scripts/
│   └── migrate_from_spacey.py  # One-time copy of access rows from spacey
├── tests/                 # pytest: contract, API and database tests (tests/README.md)
├── docs/                  # Architecture, database, API, migration; ACC decision records
├── Dockerfile, compose.yaml, gunicorn.conf.py
├── requirements.txt
└── README.md
```

---

## Current work

| Issue | Description | Priority | Status |
|-------|-------------|----------|--------|
| [spacey-access#1](https://github.com/cs403bkk-2026/spacey-access/issues/1) | check-in, check-out, expiry, cancellation | P0 | To Do |
| [spacey-access#2](https://github.com/cs403bkk-2026/spacey-access/issues/2) | Remove cross-table read of `bookings.paid` | P3 | To Do |
| [spacey #200](https://github.com/cs403bkk-2026/spacey/issues/200) | Isolate authorised issuance | — | Open |

**Blocked on:** Agreement with Purchase team on eligibility signal (see [business-rules PR #20, Q9](https://github.com/cs403bkk-2026/spacey-business-rules/pull/20)).

---

## Team

| Name | GitHub | Role |
|------|--------|------|
| Flurina Baumbach | flurinasophie | Product Owner |
| Gregory Werne | gregoryvw | Developer |
| Annabel Morgenstern| abibvm | Developer |
| Jeeranan (Amp) | AmpJee | SRE |
| Ing | QuantumTacoNinja | Architect |
| Pun | VoidDev-Uni-Work | Developer |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

**Team notes:** [Access team document (Google Docs)](https://docs.google.com/document/d/1xZHmVhBWWa1D5uDfRjvZlovhoP5y1Y06YUV-Y4uFfw0/edit?usp=sharing)
