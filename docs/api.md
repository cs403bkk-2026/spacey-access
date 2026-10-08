# API

The contract is [`openapi.yaml`](../openapi.yaml), served at `GET /openapi.yaml`. **Only the
first two rows exist today.** The rest are **proposed** and get added to `openapi.yaml` only once the
caller agrees them. For the Frontend endpoints, Access follows the spec Frontend agrees.

| Method | Path | Caller | Purpose | Success | Refusals | State |
|---|---|---|---|---|---|---|
| GET | `/health` | platform, anyone | Service and database health | `200 {status:"ok", revision}` | `503` database unreachable | ✅ live |
| GET | `/openapi.yaml` | anyone | The contract | `200` YAML | — | ✅ live |
| POST | `/bookings/{booking_id}/access` | **Purchase** | Grant access for a **paid** booking (Purchase checked); idempotent, returns the same code on repeat | `201` new / `200` existing: `{booking_id, access_code, status, expires_at}` | `400` bad body · `409` removed | proposed |
| GET | `/bookings/{booking_id}/access` | Frontend, Purchase | Read the status (**never** the code) | `200 {booking_id, status, checked_in_at, checked_out_at, expires_at}` | `404` no record | proposed |
| POST | `/bookings/{booking_id}/check-in` | **Frontend** | Present the code: available → used | `200 {booking_id, status:"used", checked_in_at}` | `400` no code · `403` code doesn't match · `404` no record · `409` used / removed / expired / too early | proposed (Frontend request) |
| POST | `/bookings/{booking_id}/check-out` | **Frontend** | used → available | `200 {booking_id, status:"available", checked_out_at}` | `404` · `409` not checked in | proposed (Frontend request) |
| POST | `/bookings/{booking_id}/access/remove` | **Purchase** | Cancellation: → removed, record kept; idempotent | `200 {booking_id, status:"removed", removed_at}` | `404` no record | proposed |
| PATCH | `/bookings/{booking_id}/access` | **Purchase** | The booking's interval changed: move the copy and the expiry | `200 {booking_id, booked_start_time, booked_end_time, expires_at, status}` | `400` · `404` · `409` removed | proposed |

## Conventions (same as `spacey`)

- JSON in and out. Errors are `{"error": "<message>"}`, and a `409` also carries `"status"`.
- Times are ISO 8601 with an offset.
- `booking_id` is `spacey`'s integer booking id: the only identifier shared between services.
- **Idempotent writes:** granting and removing can safely be retried.
- **No code in reads:** only the grant answer (to Purchase) carries `access_code`.

## Request bodies (proposed)

```jsonc
// POST /bookings/{booking_id}/access   (Purchase)
{ "space_id": 1, "start_time": "2026-10-09T09:00:00+07:00", "end_time": "2026-10-09T10:00:00+07:00" }

// POST /bookings/{booking_id}/check-in   (Frontend)
{ "access_code": "8754e726" }

// PATCH /bookings/{booking_id}/access   (Purchase)
{ "start_time": "...", "end_time": "...", "expires_at": "..." }   // expires_at optional, defaults to end_time
```

## Not decided

- D2: authentication (a token for Purchase; the session or nothing for the browser)
- D3: the base URL (a path on the same site, or Access's own host)
- the exact wording of each refusal: Frontend decides what it shows
