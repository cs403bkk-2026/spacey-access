# API

The contract is [`openapi.yaml`](../openapi.yaml), served at `GET /openapi.yaml`. Every endpoint below
**exists**. The booking endpoints answer with **dummy** values for now (`src/db.py`); the real logic
replaces the function bodies without changing paths or shapes. Each network function in `src/api.py`
calls exactly one function in `src/db.py`.

| Method | Path | Caller | Network function → function | Success | Refusals | State |
|---|---|---|---|---|---|---|
| GET | `/health` | platform, anyone | `health` → `db.ping` | `200 {status:"ok", revision}` | `503` database unreachable | ✅ live |
| GET | `/openapi.yaml` | anyone | `openapi` | `200` YAML | — | ✅ live |
| POST | `/bookings/{booking_id}/access` | **Purchase** | `purchase_create_access` → `db.create_access` | `201 {booking_id, access_code, status:"available", expires_at}` | `400` missing times; `401` missing/invalid token | dummy |
| POST | `/bookings/{booking_id}/access/remove` | **Purchase** | `purchase_remove_access` → `db.remove_access` | `200 {booking_id, status:"removed", removed_at}` | `401` missing/invalid token | dummy |
| POST | `/bookings/{booking_id}/access/expire` | **Purchase** | `purchase_expire_access` → `db.expire_access` | `200 {booking_id, status:"expired"}` | `401` missing/invalid token | dummy |
| POST | `/bookings/{booking_id}/check-in` | **Frontend** | `frontend_check_in` → `db.check_in` | `200 {booking_id, status:"used", checked_in_at}` | `400` missing code | dummy |
| POST | `/bookings/{booking_id}/check-out` | **Frontend** | `frontend_check_out` → `db.check_out` | `200 {booking_id, status:"available", checked_out_at}` | — | dummy |

**Access → Purchase:** when access expires by Access's own clock, `notify_purchase_expired(booking_id)`
(`src/purchase_client.py`) calls `POST {PURCHASE_URL}/bookings/{booking_id}/access-expired`. Dummy:
nothing is sent until Purchase has that endpoint; the request descriptor includes the shared
`Authorization: Bearer <token>` header. Both sides can expire (Purchase's clock via
`/access/expire`, Access's clock via this call); expiring twice changes nothing.

The shared Purchase/Access token is supplied to Access as `SERVICE_TOKEN` and sent by
Purchase as a Bearer token. Provision it through platform and CI secret stores;
never commit it. The protected Purchase routes return `401` before validating a request body or
calling the database when the token is missing or invalid.

`403`, `404` and `409` (wrong code, no record, wrong state) arrive with the real logic.

**Dummy warning:** every booking gets the same code, and any check-in succeeds. Don't point Purchase
at a deployed Access until the real functions replace the dummies.

## Conventions (same as `spacey`)

- JSON in and out. Errors are `{"error": "<message>"}`, and a `409` also carries `"status"`.
- Times are ISO 8601 with an offset.
- `booking_id` is `spacey`'s integer booking id: the only identifier shared between services.
- **Idempotent writes:** create, remove and expire can safely be retried.
- **The code travels once:** only the create answer (to Purchase) carries `access_code`.

## Request bodies

```jsonc
// POST /bookings/{booking_id}/access   (Purchase)
{ "start_time": "2026-10-09T09:00:00+07:00", "end_time": "2026-10-09T10:00:00+07:00" }

// POST /bookings/{booking_id}/check-in   (Frontend)
{ "access_code": "00000000" }
```

## Settled

- D2: Purchase-to-Access uses the shared Bearer token; browser endpoints remain unchanged

## Not decided
- D3: the base URL (a path on the same site, or Access's own host)
- the exact wording of each refusal: Frontend decides what it shows
