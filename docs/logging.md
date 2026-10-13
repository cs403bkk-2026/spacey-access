# Logging standard

What Access logs, and what it never logs. One short rule set that Access follows and other
teams can copy. It follows the pattern Payments already uses in `spacey`
(`shared/logger.py`, `purchase/booking.py`, `payment/tests/test_payment_logging.py`).

**Status:** proposed (ACC-13.5, research and standard). The code does not log yet: the lines below
are added after ARCH-01 and ARCH-02 land, because they change the same files. Items marked
**to confirm** need an answer from the platform owner.

## The rule in one line

Every outcome that matters for running Access is **one log line** in a fixed `key=value` shape.
**No access code, token, connection string or request body ever appears in a log.**

## Never log

| Never | Why | Where it could sneak in |
|---|---|---|
| `access_code` (any value, even a wrong one) | It opens a door. Logs are readable by everyone with Grafana access | check-in body, create/read responses, a mock's debug output |
| `SERVICE_TOKEN` and the `Authorization` header | A leaked token lets anyone call the 6 functions | a request dump, a debug print of `request.headers` |
| `DATABASE_URL` and any connection string | Contains the password | the "could not connect" message, a startup banner |
| Request and response **bodies** | They carry the access code | a "log the request" shortcut |
| Raw **exception text** from psycopg or requests | A psycopg message can carry the SQL parameters, a requests error can carry the URL | `logger.exception(...)`, `str(error)`, `exc_info=True` |
| Free text from a request | Log injection (a newline fakes a second line) | an error message that echoes input |

Query strings are already removed from the gunicorn request line (`gunicorn.conf.py`), and the
check-in code travels in the JSON body, never in the path. Keep it that way: **never put a secret in a
path or query string.**

## One shape for every line

```text
<LEVEL> access action=<function> booking_id=<int> outcome=<word> [status=<current status>] [error_class=<ClassName>]
```

- **One logger** named `access`, from a small module copied from `spacey`'s `shared/logger.py`:
  `LOG_LEVEL` (default `INFO`), output to stderr, format `%(levelname)s %(message)s`. Same
  behaviour and variable as `spacey`, so nothing new to learn.
- **Values come from a fixed vocabulary** (below), never from the request. `booking_id` is safe
  because the route only accepts integers.
- **Exceptions:** log a fixed outcome plus the exception's **class name**, never its message and no
  traceback: `access action=create booking_id=42 outcome=db_error error_class=OperationalError`.
- **Spell it the same every time.** Grafana can only count what is written identically.

## Levels

| Level | Used for | Alert input (ACC-14) |
|---|---|---|
| `DEBUG` | a successful `read` (high volume) | none |
| `INFO` | success, or "already done" | rate of normal traffic |
| `WARNING` | a refusal: not found, wrong code, conflict, bad request, unauthorized | refusal rate; many `wrong_code` for one booking may mean guessing |
| `ERROR` | `db_error`, anything that is our fault | any `ERROR` is worth a look |

`DEBUG` is off in production. There is no per-request `INFO` beyond the gunicorn request line.

## Event vocabulary

Built from the State × action table of the contract (`openapi.yaml` 0.2.0).

| `action` | `outcome` | Level | Meaning |
|---|---|---|---|
| `create` | `created` | INFO | new record, `201` |
| `create` | `exists` | INFO | a record already existed, returned unchanged, `200` |
| `create` | `bad_request` | WARNING | missing, naive or inverted times, `400` |
| `read` | `found` | DEBUG | `200` |
| `read` | `not_found` | WARNING | `404` |
| `check_in` | `used` | INFO | `available` → `used` |
| `check_in` | `already_used` | INFO | repeat on a `used` record, `200` |
| `check_in` | `wrong_code` | WARNING | `403` (never log the code) |
| `check_in` | `conflict` + `status=` | WARNING | `409`, the current status |
| `check_out` | `checked_out` | INFO | `checked_out_at` recorded |
| `check_out` | `already_checked_out` | INFO | repeat, `200` |
| `check_out` | `conflict` + `status=` | WARNING | `409` |
| `revoke` | `revoked` | INFO | `available` → `revoked` |
| `revoke` | `already_revoked` | INFO | repeat, `200` |
| `revoke` | `conflict` + `status=` | WARNING | `409` |
| `expire` | `expired` | INFO | `available` → `expired` |
| `expire` | `already_expired` | INFO | repeat, `200` |
| `expire` | `conflict` + `status=` | WARNING | `409` |
| `expiry` | `expired_on_touch` | INFO | lazy expiry: found overdue on read or check-in and set to `expired` |
| any of the 6 | `not_found` | WARNING | `404` |
| any of the 6 | `unauthorized` | WARNING | `401`, missing or wrong token (never log the header) |
| any of the 6 | `db_error` | ERROR | database failure, plus `error_class` |
| `notify_purchase` | `sent` / `failed` | INFO / WARNING | the expiry notice to Purchase (ACC-12) |

Every `409` writes exactly one line, as the contract promises.

## Decisions to take

| Question | Proposal | Status |
|---|---|---|
| Text `key=value` or JSON lines? | **Keep `key=value`**, like Payments: one convention for both repos, and Loki can parse it with `logfmt` | proposed |
| Same logger module as `spacey`? | **Yes**, a copy named `access`, same `LOG_LEVEL` | proposed |
| Request correlation | `spacey` sends `X-Request-ID`, Access logs `request_id=<value>`. Accept only `[A-Za-z0-9-]{1,64}`, otherwise drop it (log injection) | open; needs agreement with the `spacey` side (ARCH-02 §B) |
| Is the gunicorn line enough for rate, errors, duration? | Yes for a start: it has method, path, status, bytes and duration. `booking_id` is in the path | proposed |
| Is `wrong_code` a `WARNING`? | Yes, and ACC-14 counts them per booking over a few minutes | proposed |
| Loki labels and the query to find Access logs | The label names depend on the platform's Loki setup | **to confirm** with the platform owner |
| How long does Loki keep logs, and who can read them? | Unknown. Until known, "never log a code" is the only defence | **to confirm** |

## How the tests prove it

Same style as `payment/tests/test_payment_logging.py`:

1. **Every outcome produces exactly one line** at the level in the table (`assertLogs`).
2. **Secrets never appear.** Feed a realistic access code, a token and a `DATABASE_URL` through every
   path (success, refusal, `409`, `401`) and assert that none of them is in the captured output.
3. **Error paths log no diagnostics.** A database error raised with the secrets inside its message
   logs only `outcome=db_error error_class=...`, with `exc_info` empty.
4. **Logging works without app configuration**, at the default and at `LOG_LEVEL=DEBUG`.

## Still to do (after ARCH-01 and ARCH-02)

- Add the logger module and the lines above to `src/api.py` and `src/db.py`.
- Add the tests in the previous section.
- Add the Loki query to this file once the labels are confirmed (input for ACC-14).
- Link this file from `docs/README.md`.
