# spacey-access

Access service for the Spacey booking platform.  
This module owns everything related to issuing and managing access codes for confirmed bookings.

## What this service does

- Issues one access code per booking (code is stored and reused on repeat requests)
- Manages the `access` table — no other service reads or writes it
- Handles check-in, check-out, expiry, and cancellation of access records
- Expiry is checked lazily (on touch), not via a scheduled job

**State machine:**

```text
available → used          (check-in)
used → available          (check-out / re-entry)
available/used → expired  (booking end time passed)
available/used → removed  (booking cancelled by Purchase)
```

For the full business rules, see [spacey-business-rules](https://github.com/cs403bkk-2026/spacey-business-rules).

---

## Setup

Status: **working skeleton**. The service runs, connects to its database, and serves `/health` and its OpenAPI document. Access logic (check-in, check-out, expiry, cancellation) is not implemented yet.

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
| `APP_REVISION` | `local` | Shown by `/health`, so a deployment can confirm which commit is live |

Never commit a `.env` file or real credentials. The values in `compose.yaml` are local placeholders.

### Ports

| Service | Host port | Container port |
|---------|-----------|----------------|
| app (gunicorn) | 8003 | 8000 |
| db (Postgres 16) | 5434 | 5432 |

### Migrations

Not run automatically yet; how migrations run is still to be decided. To create the table by hand on the local database:

```bash
psql postgresql://access:access@localhost:5434/access -f migrations/001_create_access_table.sql
```

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
├── app.py                 # Entry point: create_app(), routes (/health, /openapi.yaml)
├── src/
│   ├── db.py              # Database connection (DATABASE_URL, fail fast)
│   └── access.py          # Core logic: issue, check_in, check_out, expire, remove
├── openapi.yaml           # The API contract, served at /openapi.yaml
├── migrations/
│   └── 001_create_access_table.sql
├── tests/
│   ├── test_health.py
│   └── test_access.py
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
