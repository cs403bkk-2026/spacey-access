# ACC 0002: Access gets its own database and API, and moves out of `spacey`

Date: 2026-10-08

Status: Proposed by the Access team. Not started: only the working skeleton exists (ACC 0001).
Needs agreement from Purchase, Frontend and the SRE (see "Needs agreement").

**Decision:** on top of the skeleton, Access becomes the `spacey-access` service with **its own
database** (one `access` table) and **its own HTTP API**. Frontend and Purchase call it; Access's
only outgoing call is the expiry notice to Purchase. It moves out of `spacey` in four steps, with a one-time copy of the existing codes.

## Why not the alternatives

| Alternative | Why not |
|---|---|
| Stay inside `spacey` | No independent deployment (the course's goal); the `access` table is created in Purchase's `purchase/schema.py` |
| Share `spacey`'s database | Every schema change and release would be coupled to `spacey`'s |
| Move in one step | Riskier. Doing it in steps keeps `/unlock` working, and each step can be rolled back |
| Frontend calls Access for `/unlock` directly | Needs a Frontend change and new routing; forwarding through `spacey` changes nothing for Frontend |
| Generate OpenAPI from code | Extra dependencies; a hand-written file lets callers agree the contract **before** we build |

## What it looks like

| Part | Decision | Detail |
|---|---|---|
| Code | Refactor the skeleton to `app.py` → **`src/api.py`** (HTTP only) → **`src/db.py`** (every operation as SQL, the only file talking to Postgres) → Postgres | [architecture.md](../architecture.md) |
| Data | Own database; `access` table, 11 columns, states `available / used / expired / removed`; never delete a row; `booking_id` is a value, not a foreign key | [database.md](../database.md) |
| API | Create, remove, expire (Purchase); check-in, check-out (Frontend); an expiry notice to Purchase. Defined and running as dummies, next to `/health` and `/openapi.yaml` | [api.md](../api.md) |
| Callers | Purchase: create (after its own paid check), remove, expire. Frontend: check-in, check-out | [for-other-teams.md](../for-other-teams.md) |
| Move | 1 `access/` package inside `spacey` → 2 `spacey-access` ready → 3 cutover → 4 clean up | [migrate-from-spacey.md](../migrate-from-spacey.md) |
| Data copy | Script: dry run first, safe to run again, read-only on `spacey` | [production-data-migration.md](../production-data-migration.md) |

## API conventions

- **JSON over HTTP, REST-style**, under `/bookings/{booking_id}/…`. `spacey`'s integer `booking_id` is the only identifier shared with other services.
- **Contract first:** every endpoint is added to `openapi.yaml` and agreed with its caller before it's built. For check-in and check-out, Access follows the spec Frontend agrees.
- **Same conventions as `spacey`:** errors are `{"error": "…"}` with a meaningful status (a `409` also carries `"status"`); times are ISO 8601 with an offset.
- **Writes are safe to retry** (create, remove, expire); **only the create answer carries the access code**.
- **Access reads no other team's data.** Anything it needs is passed in. Its only outgoing call is the expiry notice to Purchase (`src/purchase_client.py`).
- **Tests check every response against `openapi.yaml`**, so the hand-written contract can't drift silently.

## Consequences

Expected, not measured:

- Access owns its code, schema and data, and deploys on its own.
- **Unlock now depends on a network call to Access.** What it answers when Access is down is still open.
- **No foreign key or transaction across databases.** Access trusts the `booking_id` and facts Purchase sends.
- **Copied booking times can go stale** if Purchase changes a booking without calling Access.
- **Rollback after the cutover can lose** codes granted in Access in the meantime, so the window must be short.

## Needs agreement

| Who | What |
|---|---|
| Purchase | Forwarding in `/unlock`, calling `remove` on cancel, owning the paid check |
| Frontend | The check-in/check-out API (we follow their spec) |
| SRE / platform | Access's database, Nomad job, routing and rollback |
| Access team | Authentication (Purchase → Access, browser → Access), API versioning, and D1–D7 in [docs/README.md](../README.md) |

## References

- [ACC 0001](0001-working-skeleton.md): the working skeleton this builds on
- [spacey-business-rules](https://github.com/cs403bkk-2026/spacey-business-rules): SP-T12–T21, SP-R08–R17
