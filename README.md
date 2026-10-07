# spacey-access

Access service for the Spacey booking platform.  
This module owns everything related to issuing and managing access codes for confirmed bookings.

## What this service does

- Issues one access code per booking (code is stored and reused on repeat requests)
- Manages the `access` table — no other service reads or writes it
- Handles check-in, check-out, expiry, and cancellation of access records
- Expiry is checked lazily (on touch), not via a scheduled job

**State machine:**
available → used (check-in)
used → available (check-out / re-entry)
available/used → expired (booking end time passed)
available/used → removed (booking cancelled by Purchase)

For the full business rules, see [spacey-business-rules](https://github.com/cs403bkk-2026/spacey-business-rules).

---

## Setup

### Prerequisites

- Python 3.12+
- PostgreSQL running locally (or via Docker)

### Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://spacey:spacey@localhost:5432/spacey` | Postgres connection string |

Set it in a `.env` file (never commit this file):
DATABASE_URL=postgresql://spacey:spacey@localhost:5432/spacey

### Run migrations

```bash
psql $DATABASE_URL -f migrations/001_create_access_table.sql
```

### Run tests

```bash
pytest
```

> **Important:** Tests run against a local disposable database only. Never point `DATABASE_URL` at production.

---

## Project structure
spacey-access/
├── access.py # Core logic: issue, check_in, check_out, expire, remove
├── migrations/
│ └── 001_create_access_table.sql
├── tests/
│ └── test_access.py
├── requirements.txt
└── README.md

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
