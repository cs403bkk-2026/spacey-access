# API

The contract is [`openapi.yaml`](../openapi.yaml), served at `GET /openapi.yaml`. Every endpoint below
**exists**. The SQL in `src/db.py` is real; the lifecycle rules of the contract (`403`/`409` answers,
lazy expiry) arrive in Phase 2, without changing paths or shapes. Each network function in `src/api.py`
calls exactly one function in `src/db.py`.

| Method | Path | Caller | Network function → function | Success | Refusals | State |
|---|---|---|---|---|---|---|
| GET | `/health` | platform, anyone | `health` → `db.ping` | `200 {status:"ok", revision}` | `503` database unreachable | ✅ live |
| GET | `/openapi.yaml` | anyone | `openapi` | `200` YAML | — | ✅ live |
| POST | `/bookings/{booking_id}/access` | **spacey** (Purchase) | `purchase_create_access` → `db.create_access` | `201` the full record | `400` missing times; `401` missing/invalid token | real SQL |
| GET | `/bookings/{booking_id}/access` | **spacey** | `purchase_read_access` → `db.read_access` | `200` the full record | `401` missing/invalid token; `404` no record | real SQL |
| POST | `/bookings/{booking_id}/access/revoke` | **spacey** (Purchase) | `purchase_revoke_access` → `db.revoke_access` | `200` the full record, `status:"revoked"` | `401` missing/invalid token; `404` no record | real SQL |
| POST | `/bookings/{booking_id}/access/expire` | **spacey** (Purchase) | `purchase_expire_access` → `db.expire_access` | `200` the full record, `status:"expired"` | `401` missing/invalid token; `404` no record | real SQL |
| POST | `/bookings/{booking_id}/check-in` | **spacey** (Frontend) | `frontend_check_in` → `db.check_in` | `200` the full record, `status:"used"` | `400` missing code; `401` missing/invalid token; `404` no record or wrong code | real SQL |
| POST | `/bookings/{booking_id}/check-out` | **spacey** (Frontend) | `frontend_check_out` → `db.check_out` | `200` the full record, `checked_out_at` set, status stays `used` (target; see note) | `401` missing/invalid token; `404` not checked in | real SQL |

**Access → Purchase:** when access expires by Access's own clock, `notify_purchase_expired(booking_id)`
(`src/purchase_client.py`) calls `POST {PURCHASE_URL}/bookings/{booking_id}/access-expired`. Dummy:
nothing is sent until Purchase has that endpoint; the request descriptor includes the shared
`Authorization: Bearer <token>` header. Both sides can expire (Purchase's clock via
`/access/expire`, Access's clock via this call); expiring twice changes nothing.

The shared Purchase/Access token is supplied to Access as `SERVICE_TOKEN` and sent by
Purchase as a Bearer token. Provision it through platform and CI secret stores;
never commit it. All six access routes return `401` before validating a request body or
calling the database when the token is missing or invalid.

`403`, `404` and `409` (wrong code, no record, wrong state) arrive with the real logic.

**Lifecycle note:** `openapi.yaml` 0.2.0 is the target. Check-out in `db.py` still sets `available`
(re-entry) and wrong codes answer `404`, not `403`; those and the `409` answers are Phase 2. Don't rely
on them yet.

## Conventions (same as `spacey`)

- JSON in and out. Errors are `{"error": "<message>"}`, and a `409` also carries `"status"`.
- Times are ISO 8601 with an offset.
- `booking_id` is `spacey`'s integer booking id: the only identifier shared between services.
- **Idempotent writes:** create, revoke and expire can safely be retried.
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
