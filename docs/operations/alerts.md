# Alerts for Access

ACC-14 (#44). What we measure, what we promise, and when someone is told. Every
alert is **actionable**: it links to a section of [runbook.md](runbook.md). Access
codes, tokens and connection strings never appear in an alert or its message.

**Status (2026-10-14):** the numbers below are **starting points**. They are not
yet loaded into Grafana (the rules live in the platform's `cs403bkk-cluster-jobs`,
which the Access team can't edit), and there is no staging environment to test
them in. **Review every threshold on 2026-10-21**, after a week of production data.

## What we measure (signals)

| Signal | Source | Available |
|---|---|---|
| Request rate, status, duration per path | gunicorn request log on stdout: `"<method> <path> <proto>" <status> <bytes> <ms>ms` (`gunicorn.conf.py`, no query string) | ✅ now |
| Liveness | Nomad's `/health` check every 10 s (2 s timeout), plus the public `https://access.cs403bkk26.space/health` | ✅ now |
| Restarts | Nomad allocation events | ⏳ needs Nomad metrics in Grafana (platform) |
| Outcomes (`wrong_code`, `db_error`, …) | Access's own log lines, [logging.md](../logging.md) | ⏳ after ACC-13.5's code |
| `spacey` can't reach Access | `spacey`'s `outcome=access_unavailable` lines | ⏳ after ARCH-02 §B |

**Low traffic matters.** Today almost nothing calls Access, so one error out of two
requests is "50 %". Rules below use **counts**, or require a minimum number of
requests before a *rate* is judged.

## SLIs and SLOs

| SLI (what we measure) | SLO (target) | Error budget | Why |
|---|---|---|---|
| **Availability:** share of requests to the 6 access endpoints that are **not 5xx** | **99 %** over 7 days | 1 % (e.g. 10 failures per 1,000 requests) | Members feel 5xx directly: no code, or a door that won't open. 99 % is modest for one instance on a course cluster |
| **Liveness:** share of minutes in which `/health` answers `200` | **99.5 %** over 7 days | about 50 min per week | A deploy or node problem means short downtime (single instance, accepted in `deployment.md`) |
| **Latency:** p95 duration of the 6 access endpoints | **< 500 ms** over 7 days, with ≥ 20 requests | – | A member waits at a door; half a second is noticeable, a second is not acceptable |

Known risk to the availability SLO: a **repeat create returns 500** (Phase 2 gap).
Once `spacey` retries creates, this alone can use the error budget. Fix it before
`spacey` is wired to Access.

## Severities

Defined in member terms.

| Severity | Meaning | Response |
|---|---|---|
| **SEV1** | Nobody can get or use an access code | Act now during class hours; tell the team channel and Purchase/Frontend |
| **SEV2** | Some requests fail, or the service is degraded | Act the same day |
| **SEV3** | Worth a look in working hours, or a risk with no member impact yet | Next working session |

**On-call:** best effort during class hours, as allowed for a course: the SRE
first, the architect as backup. This is a conscious choice, not a gap.

## Alerts

| Alert | Rule (starting point) | Severity | Why this number | Runbook |
|---|---|---|---|---|
| **Access down** | Public `/health` not `200` for **2 min**, or no `/health` request line in the log for 2 min | SEV1 | Nomad checks every 10 s, so 2 min is about 12 failed checks: not a blip, and short enough that members notice before us only rarely | [Access down](runbook.md#access-down) |
| **Server errors** | **≥ 5** responses with 5xx in **5 min** (count, not rate) | SEV2 | With low traffic a rate swings wildly; 5 real failures in 5 minutes is a pattern, 1 is not | [Server errors](runbook.md#server-errors) |
| **Slow** | p95 duration of the access endpoints **> 1 s** for **10 min**, only if **≥ 20** requests in the window | SEV3 | Twice the SLO target; the traffic guard keeps one slow request from firing it | [Slow](runbook.md#slow) |
| **Restart loop** | **≥ 3** allocation restarts in **15 min** | SEV2 | One restart can be a deploy; three in a quarter hour is a crash loop | [Restart loop](runbook.md#restart-loop) |
| **Code guessing** | **≥ 10** `outcome=wrong_code` for **one booking** in **10 min** | SEV3 (security) | A member mistypes a few times; ten in ten minutes looks like guessing | [Code guessing](runbook.md#code-guessing) |
| **`spacey` can't reach Access** | **≥ 3** `outcome=access_unavailable` in `spacey`'s log in **5 min** | SEV2 | The member journey breaks even when Access itself looks healthy | [spacey can't reach Access](runbook.md#spacey-cant-reach-access) |
| **Expiry notice failing** | `notify_purchase … outcome=failed` **3×** in **15 min** | SEV3 | Purchase isn't told a code expired; no member is blocked, but data drifts | [Expiry notice failing](runbook.md#expiry-notice-failing) |

The first two can be built **now** from the gunicorn log and the public URL. The
others wait for the signal in the table above.

**Hysteresis:** an alert resolves only after its condition has been clear for the
same duration it needed to fire, so it doesn't flap.

**Not alerted on:** CPU, memory and other causes. We alert on what members feel; causes
are what the runbook checks.

## Notification

**Proposed:** one Grafana contact point sending to the Access team's chat channel,
with SEV1 also mentioning the SRE and the architect. Each message carries the alert
name, severity, start time, current value and the runbook link, and nothing else.
To agree with the platform owner, who manages Grafana's contact points.

## Draft queries (to load into Grafana)

The Loki labels for Access's logs still need to be confirmed in Grafana → Explore
(the queries below assume `{namespace="access", job="access"}`).

```logql
# Server errors: 5xx responses in the last 5 minutes
sum(count_over_time({namespace="access", job="access"}
  | regexp `"(?P<method>\S+) (?P<path>\S+) \S+" (?P<status>\d{3}) \S+ (?P<ms>\d+)ms`
  | status =~ "5.." [5m]))

# Slow: p95 duration of the access endpoints over 10 minutes
quantile_over_time(0.95, {namespace="access", job="access"}
  | regexp `"(?P<method>\S+) (?P<path>/bookings/\S+) \S+" (?P<status>\d{3}) \S+ (?P<ms>\d+)ms`
  | unwrap ms [10m])

# Access down, log side: no /health lines for 2 minutes
absent_over_time({namespace="access", job="access"} |= "/health" [2m])
```

## Drill (to run once a staging environment exists)

Stop the Access job in staging → confirm "Access down" fires within about 2 min and
reaches the channel → follow the runbook → start the job → confirm the alert
resolves → write a report with [incident-report-template.md](incident-report-template.md).
Not on production, and not on a laptop: Grafana can't see a laptop.
