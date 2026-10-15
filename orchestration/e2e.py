"""Extraction gate driver: act like spacey-frontend, then inspect what really
crossed the wire between spacey and spacey-access.

Run by orchestration/run.sh against the compose stack (local only, never CI):

    spacey   http://127.0.0.1:8024   (the hub; the frozen contract is its openapi.yaml)
    tap      http://127.0.0.1:8025   (records every call to spacey-access)
    access   db postgresql://access:access@127.0.0.1:5444/access   (read-only checks)
    spacey   db postgresql://spacey:spacey@127.0.0.1:5446/spacey   (read-only checks)

Each scenario checks three things (gate ④):
  1. the answer spacey gives the "browser" (status + frozen-contract shape),
  2. the calls the tap recorded (exactly which, with token and body),
  3. the state in Access's database.
Every recorded call is also validated against spacey-access/openapi.yaml.

Never prints an access code or the token: the report shows them as ***.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from itertools import count
from pathlib import Path

import psycopg
from openapi_core import OpenAPI
from openapi_core.testing import MockRequest, MockResponse
from openapi_spec_validator.readers import read_from_filename
from psycopg.rows import dict_row

SPACEY = "http://127.0.0.1:8024"
TAP = "http://127.0.0.1:8025"
ACCESS_DB = "postgresql://access:access@127.0.0.1:5444/access"
SPACEY_DB = "postgresql://spacey:spacey@127.0.0.1:5446/spacey"
CARD = {"card_number": "4242424242424242", "expiry": "12/30", "cvc": "123"}
LEVELS = ["F0", "F1", "F2", "F3", "F4", "F5", "F6"]

TOKEN = os.environ["LOCAL_SERVICE_TOKEN"]
CAPTURE = Path(os.environ["CAPTURE_DIR"]) / "flows.jsonl"
COMPOSE = os.environ["COMPOSE_CMD"].split()

_slot = count()


# --- plumbing -----------------------------------------------------------------


def http(method, url, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    try:
        return status, json.loads(raw) if raw else None
    except ValueError:
        return status, raw.decode(errors="replace")


def probe(method, path, body=None, token=True):
    """Host -> tap -> Access. Marked so it isn't mistaken for spacey's calls."""
    headers = {"X-Probe": "host"}
    if token:
        headers["Authorization"] = f"Bearer {TOKEN}"
    return http(method, TAP + path, body, headers)


def compose(*args, env=None):
    subprocess.run(COMPOSE + list(args), check=True, capture_output=True,
                   env={**os.environ, **(env or {})})


def wait_ok(url, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if http("GET", url, headers={"X-Probe": "host"})[0] == 200:
                return True
        except OSError:
            pass
        time.sleep(1)
    return False


def hdr(rec, name):
    """Header value, case-insensitive (urllib sends 'X-probe', mitmproxy keeps case)."""
    for key, value in rec.get("req_headers", {}).items():
        if key.lower() == name.lower():
            return value
    return ""


def is_host(rec):
    return hdr(rec, "X-Probe") == "host"


OPS = [  # (method, path regex, operation name)
    ("POST", r"^/bookings/\d+/access$", "create"),
    ("GET", r"^/bookings/\d+/access$", "read"),
    ("POST", r"^/bookings/\d+/access/revoke$", "revoke"),
    ("POST", r"^/bookings/\d+/access/expire$", "expire"),
    ("POST", r"^/bookings/\d+/check-in$", "check-in"),
    ("POST", r"^/bookings/\d+/check-out$", "check-out"),
]

# Contract gaps of the *real* spacey-access that a step hasn't fixed yet:
# reported as KNOWN, not failing. Each step removes what it fixes; F6 = none.
KNOWN_CONTRACT = {
    "F0": {"create", "read", "revoke", "expire", "check-in", "check-out"},
    "F1": {"create", "read", "revoke", "expire", "check-in", "check-out"},
    "F2": {"revoke", "expire", "check-in", "check-out"},
    "F3": {"expire", "check-in", "check-out"},  # revoke fixed in F3
    "F4": {"expire", "check-in", "check-out"},
    "F5": {"expire", "check-in", "check-out"},
    "F6": set(),
}


def op_of(method, path):
    import re
    for m, rx, name in OPS:
        if m == method and re.match(rx, path.split("?")[0]):
            return name
    return path


def captured():
    if not CAPTURE.exists():
        return []
    return [json.loads(line) for line in CAPTURE.read_text().splitlines() if line.strip()]


def db_row(dsn, sql, params=()):
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        return conn.execute(sql, params).fetchone()


def access_row(booking_id):
    return db_row(ACCESS_DB, "SELECT booking_id, access_code, status FROM access WHERE booking_id = %s",
                  (booking_id,))


# --- contracts ------------------------------------------------------------------


class Contract:
    def __init__(self, path, param):
        spec, _ = read_from_filename(str(path))
        self.api = OpenAPI.from_dict(spec)
        self.param = param

    def check(self, method, path, req_body, req_headers, status, resp_body, content_type):
        """None if the exchange matches the contract, else the reason."""
        request = MockRequest(
            "http://localhost", method.lower(), path.split("?")[0],
            headers={k: v for k, v in req_headers.items() if k.lower() == "authorization"},
            data=req_body.encode() if req_body else None,
        )
        response = MockResponse(
            (resp_body or "").encode(), status_code=status,
            content_type=(content_type or "application/json").split(";")[0],
        )
        try:
            self.api.validate_response(request, response)
        except Exception as e:  # noqa: BLE001 - any mismatch is a finding
            return f"{type(e).__name__}: {e}"[:200]
        return None


# --- the gate ---------------------------------------------------------------------


class Gate:
    def __init__(self, level, access_contract, spacey_contract):
        self.level = level
        self.access = access_contract
        self.spacey = spacey_contract
        self.results = []      # (scenario, ok, detail)
        self.calls = []        # (scenario, source, method, path, status, contract_issue)
        self.known = []        # (scenario, detail)

    # recording ---------------------------------------------------------------
    def scenario(self, name):
        gate = self

        class _S:
            def __enter__(s):
                s.mark = len(captured())
                s.name = name
                return s

            def __exit__(s, *exc):
                for rec in captured()[s.mark:]:
                    src = "host" if is_host(rec) else "spacey"
                    issue = None
                    if rec["status"]:
                        issue = gate.access.check(
                            rec["method"], rec["path"], rec.get("req_body"), rec["req_headers"],
                            rec["status"], rec.get("resp_body"),
                            rec.get("resp_headers", {}).get("content-type"))
                    if issue and op_of(rec["method"], rec["path"]) in KNOWN_CONTRACT[gate.level]:
                        gate.known.append((name, f"contract: {rec['method']} {rec['path']} -> {rec['status']}: {issue[:120]}"))
                        issue = "KNOWN"
                    gate.calls.append((name, src, rec["method"], rec["path"], rec["status"], issue,
                                       hdr(rec, "Authorization").startswith("Bearer ")))
                if exc[0] is not None:
                    gate.fail(name, f"crashed: {exc[0].__name__}: {exc[1]}")
                    return True
                return False

            def calls(s, source="spacey"):
                return [r for r in captured()[s.mark:] if is_host(r) == (source == "host")]

        return _S()

    def ok(self, scenario, detail):
        self.results.append((scenario, True, detail))

    def fail(self, scenario, detail):
        self.results.append((scenario, False, detail))

    def expect(self, scenario, cond, detail):
        (self.ok if cond else self.fail)(scenario, detail)

    def gap(self, scenario, cond, detail, why):
        """A tracked contract gap: reported, doesn't fail the gate."""
        if cond:
            self.ok(scenario, detail + " (known gap now fixed)")
        else:
            self.known.append((scenario, f"{detail}: {why}"))

    def frozen(self, scenario, method, path, status, body):
        """spacey's answer must match spacey's own openapi.yaml (the frozen contract)."""
        issue = self.spacey.check(method, path, None, {}, status, json.dumps(body), "application/json")
        self.expect(scenario, issue is None, f"{method} {path} -> {status} matches spacey openapi"
                    + ("" if issue is None else f" ({issue})"))

    # report ------------------------------------------------------------------
    def passed(self):
        contract_bad = [c for c in self.calls if c[5] and c[5] != "KNOWN"]
        return all(ok for _, ok, _ in self.results) and not contract_bad

    def report(self):
        lines = [f"# Gate {self.level}", ""]
        lines.append(f"**Result: {'GREEN' if self.passed() else 'RED'}**  ·  "
                     f"{sum(ok for _, ok, _ in self.results)}/{len(self.results)} checks · "
                     f"{len(self.calls)} recorded calls · {len(self.known)} known gaps")
        lines += ["", "## Checks", "", "| Scenario | Result | Detail |", "|---|---|---|"]
        for name, ok, detail in self.results:
            lines.append(f"| {name} | {'✅' if ok else '❌'} | {detail} |")
        if self.known:
            lines += ["", "## Known gaps (tracked, not failing)", ""]
            lines += [f"- {n}: {d}" for n, d in self.known]
        lines += ["", "## Recorded calls (tap, redacted)", "",
                  "| Scenario | From | Call | Status | Token | Contract |", "|---|---|---|---|---|---|"]
        for name, src, method, path, status, issue, bearer in self.calls:
            lines.append(f"| {name} | {src} | `{method} {path}` | {status or 'no answer'} | "
                         f"{'Bearer ***' if bearer else '—'} | {'✅' if not issue else ('⚠️ known' if issue == 'KNOWN' else '❌ ' + issue)} |")
        return "\n".join(lines) + "\n"


# --- helpers that act like spacey-frontend -----------------------------------------


def book(paid=True):
    """Guest booking on the seeded space 1, in a slot no other run uses."""
    n = next(_slot)
    day, hour = 1 + n // 10, 8 + n % 10
    start = f"2031-03-{day:02d}T{hour:02d}:00:00+00:00"
    end = f"2031-03-{day:02d}T{hour:02d}:30:00+00:00"
    status, body = http("POST", f"{SPACEY}/spaces/1/bookings",
                        {"member": "extract-e2e", "start_time": start, "end_time": end})
    assert status == 201, f"booking failed: {status} {body}"
    if paid:
        status, paid_body = http("POST", f"{SPACEY}/bookings/{body['id']}/pay", CARD)
        assert status == 200, f"pay failed: {status} {paid_body}"
    return body["id"], start, end


def unlock(booking_id):
    """Exactly what spacey-frontend's useUnlockBookingMutation sends."""
    return http("POST", f"{SPACEY}/bookings/{booking_id}/unlock")


# --- scenarios by level ---------------------------------------------------------------


def access_contract_smoke(g):
    """Host -> tap -> spacey-access: the service answers its own contract."""
    body = {"start_time": "2031-01-01T10:00:00+00:00", "end_time": "2031-01-01T12:00:00+00:00"}
    bid = 880000 + int(time.time()) % 10000
    with g.scenario("access: create/read/repeat/check-in/revoke/401"):
        st, created = probe("POST", f"/bookings/{bid}/access", body)
        g.expect("access: create", st == 201, f"create -> {st}")
        row = access_row(bid)
        g.expect("access: create stored", row is not None and created and row["access_code"] == created.get("access_code")
                 and row["status"] == "available", "db row has the returned code, status available")
        st, _ = probe("GET", f"/bookings/{bid}/access")
        g.expect("access: read", st == 200, f"read -> {st}")
        st, again = probe("POST", f"/bookings/{bid}/access", body)
        same = st == 200 and isinstance(again, dict) and again.get("access_code") == created.get("access_code")
        if g.level in ("F0", "F1"):
            g.gap("access: repeat create", same, f"repeat create -> {st}", "fixed in F2")
        else:
            g.expect("access: repeat create", same, f"repeat create -> {st}, same code: {same}")
        st, _ = probe("POST", f"/bookings/{bid}/check-in", {"access_code": created.get("access_code")})
        g.expect("access: check-in", st == 200, f"check-in -> {st}")
        st, _ = probe("POST", f"/bookings/{bid + 1}/access", body)
        st, _ = probe("POST", f"/bookings/{bid + 1}/access/revoke")
        g.expect("access: revoke", st == 200, f"revoke -> {st}")
        g.expect("access: revoked stored", (access_row(bid + 1) or {}).get("status") == "revoked", "db status revoked")
        st, _ = probe("POST", f"/bookings/{bid + 2}/access", body, token=False)
        g.expect("access: no token", st == 401, f"no token -> {st}")


def frozen_unlock(g, service):
    """The frozen contract: POST /bookings/{id}/unlock, as spacey:main promises."""
    with g.scenario("unlock: unknown booking") as s:
        st, body = unlock(2147480000)
        g.expect("unlock: unknown -> 404", st == 404, f"-> {st}")
        g.frozen("unlock: unknown -> 404", "POST", "/bookings/2147480000/unlock", st, body)
        g.expect("unlock: unknown makes no Access call", not s.calls(), f"{len(s.calls())} calls")

    bid, _, _ = book(paid=False)
    with g.scenario("unlock: unpaid booking") as s:
        st, body = unlock(bid)
        g.expect("unlock: unpaid -> 402", st == 402, f"-> {st}")
        g.frozen("unlock: unpaid -> 402", "POST", f"/bookings/{bid}/unlock", st, body)
        g.expect("unlock: unpaid makes no Access call", not s.calls(), f"{len(s.calls())} calls")

    bid, start, end = book()
    with g.scenario("unlock: paid booking") as s:
        st, first = unlock(bid)
        g.expect("unlock: paid -> 200", st == 200, f"-> {st}")
        g.frozen("unlock: paid -> 200", "POST", f"/bookings/{bid}/unlock", st, first)
        g.expect("unlock: exact shape", isinstance(first, dict) and set(first) == {"booking_id", "access_code"},
                 f"keys {sorted(first) if isinstance(first, dict) else first}")
        st2, second = unlock(bid)
        g.expect("unlock: repeat gives the same code", st2 == 200 and second == first, f"repeat -> {st2}, same: {second == first}")
        calls = s.calls()
        if service:
            creates = [c for c in calls if c["method"] == "POST" and c["path"] == f"/bookings/{bid}/access"]
            g.expect("unlock: one create per unlock", len(creates) == 2 and len(calls) == 2,
                     f"{len(creates)} creates, {len(calls)} calls for 2 unlocks")
            if creates:
                sent = json.loads(creates[0]["req_body"] or "{}")
                g.expect("unlock: create carries the booking times",
                         sent.get("start_time", "")[:16] == start[:16] and sent.get("end_time", "")[:16] == end[:16],
                         "start_time/end_time = the booking's")
                g.expect("unlock: create carries the token",
                         hdr(creates[0], "Authorization").startswith("Bearer "), "Bearer ***")
            row = access_row(bid)
            g.expect("unlock: Access db holds the code given to the browser",
                     row is not None and row["access_code"] == (first or {}).get("access_code") and row["status"] == "available",
                     "db code == returned code, status available")
        else:
            g.expect("unlock: local path makes no Access call", not calls, f"{len(calls)} calls")
    return bid


def run(level):
    root = Path(__file__).resolve().parent.parent
    g = Gate(level,
             Contract(root / "openapi.yaml", "booking_id"),
             Contract(Path(os.environ["SPACEY_DIR"]) / "openapi.yaml", "bookingId"))
    service = bool(os.environ.get("SPACEY_ACCESS_URL"))
    assert wait_ok(f"{SPACEY}/health") and wait_ok(f"{TAP}/health"), "stack not healthy"

    access_contract_smoke(g)
    frozen_unlock(g, service)

    # Each step keeps every earlier step's scenarios (cumulative gates).
    for lv in LEVELS[: LEVELS.index(level) + 1]:
        for extra in EXTRA.get(lv, []):
            extra(g)
    return g


# --- F1: spacey's access functions reach the real service -------------------------

IN_SPACEY = r"""
import json, sys
from access import client, functions as f
bid = int(sys.argv[1])
out = []
def run(name, *args):
    try:
        payload, status = getattr(f, name)(*args)
        out.append([name, status])
        return payload
    except client.AccessUnavailable as e:
        out.append([name, "AccessUnavailable"])
start, end = "2031-02-01T10:00:00+00:00", "2031-02-01T12:00:00+00:00"
rec = run("create_access", bid, start, end) or {}
run("read_access", bid)
run("check_in", bid, rec.get("access_code", ""))
run("check_out", bid)
run("create_access", bid + 1, start, end)
run("expire_access", bid + 1)
run("create_access", bid + 2, start, end)
run("revoke_access", bid + 2)
print(json.dumps(out))
"""


def exec_in_spacey(script, *args, env=None):
    cmd = COMPOSE + ["exec", "-T"]
    for k, v in (env or {}).items():
        cmd += ["-e", f"{k}={v}"]
    cmd += ["spacey", "python", "-c", script, *map(str, args)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()[-300:]


def f1_functions(g):
    bid = 870000 + int(time.time()) % 10000
    with g.scenario("F1: the 6 functions, from inside spacey") as s:
        rc, out, err = exec_in_spacey(IN_SPACEY, bid, env={"ACCESS_URL": "http://tap:8080"})
        g.expect("F1: functions ran", rc == 0, f"exit {rc} {err if rc else ''}")
        got = json.loads(out) if rc == 0 else []
        want = [["create_access", 201], ["read_access", 200], ["check_in", 200], ["check_out", 200],
                ["create_access", 201], ["expire_access", 200], ["create_access", 201], ["revoke_access", 200]]
        g.expect("F1: each function got its contract answer", got == want, f"{got}")
        calls = s.calls()
        g.expect("F1: one recorded call per function, all from spacey", len(calls) == 8, f"{len(calls)} calls")
        g.expect("F1: every call carries the token", all(hdr(c, "Authorization").startswith("Bearer ") for c in calls),
                 "Bearer *** on all")
        g.expect("F1: db state matches",
                 (access_row(bid) or {}).get("status") in ("used", "available")
                 and (access_row(bid + 2) or {}).get("status") == "revoked",
                 "used/available, revoked")

    with g.scenario("F1: failures become AccessUnavailable") as s:
        rc, out, err = exec_in_spacey(
            "import json; from access import client, functions as f\n"
            "try:\n f.read_access(1); print('answered')\n"
            "except client.AccessUnavailable: print('AccessUnavailable')",
            env={"ACCESS_URL": "http://tap:8080", "SERVICE_TOKEN": "wrong"})
        g.expect("F1: wrong token -> AccessUnavailable", out == "AccessUnavailable", out or err)
        rc, out, err = exec_in_spacey(
            "from access import client, functions as f\n"
            "try:\n f.read_access(1); print('answered')\n"
            "except client.AccessUnavailable: print('AccessUnavailable')",
            env={"ACCESS_URL": "http://nowhere.invalid:9"})
        g.expect("F1: unreachable -> AccessUnavailable", out == "AccessUnavailable", out or err)


# --- F2: /unlock served by spacey-access; Access down -> 503 ------------------------


def f2_access_down(g):
    if not os.environ.get("SPACEY_ACCESS_URL"):
        g.ok("F2: access-down scenario", "skipped in local mode (no service on the path)")
        return
    bid, _, _ = book()
    st, first = unlock(bid)
    g.expect("F2: unlock before the outage", st == 200, f"-> {st}")

    with g.scenario("F2: Access stopped (tap answers 502)") as s:
        compose("stop", "app")
        st, body = unlock(bid)
        g.expect("F2: Access down -> 503", st == 503, f"-> {st}")
        g.expect("F2: 503 body", body == {"error": "access unavailable"}, f"{body}")
        g.frozen("F2: 503 matches spacey openapi", "POST", f"/bookings/{bid}/unlock", st, body)
        failed = [c for c in s.calls() if c["path"] == f"/bookings/{bid}/access"]
        g.expect("F2: the failed call was recorded", len(failed) == 1 and failed[0]["status"] in (0, 502),
                 f"{[(c['method'], c['status']) for c in failed]}")
        compose("start", "app")
        wait_ok(f"{TAP}/health")

    with g.scenario("F2: tap stopped (connection refused)"):
        compose("stop", "tap")
        st, body = unlock(bid)
        g.expect("F2: unreachable -> 503", st == 503 and body == {"error": "access unavailable"}, f"-> {st} {body}")
        compose("start", "tap")
        wait_ok(f"{TAP}/health")

    with g.scenario("F2: after recovery") as s:
        st, again = unlock(bid)
        g.expect("F2: recovered, same code as before the outage", st == 200 and again == first,
                 f"-> {st}, same: {again == first}")
    paid_unknown = 2147480001
    with g.scenario("F2: hub never sends unknown bookings") as s:
        st, _ = unlock(paid_unknown)
        g.expect("F2: unknown -> 404, no call", st == 404 and not s.calls(), f"-> {st}, {len(s.calls())} calls")


# --- F3: cancel -> revoke -------------------------------------------------------------


def cancel(booking_id):
    return http("DELETE", f"{SPACEY}/bookings/{booking_id}")


def f3_cancel(g):
    service = bool(os.environ.get("SPACEY_ACCESS_URL"))

    bid, _, _ = book()
    unlock(bid)
    with g.scenario("F3: cancel an unlocked booking") as s:
        st, body = cancel(bid)
        g.expect("F3: cancel -> 200", st == 200, f"-> {st}")
        g.frozen("F3: cancel matches spacey openapi", "DELETE", f"/bookings/{bid}", st, body)
        revokes = [c for c in s.calls() if c["path"] == f"/bookings/{bid}/access/revoke"]
        if service:
            g.expect("F3: one revoke, answered 200", len(s.calls()) == 1 and len(revokes) == 1
                     and revokes[0]["status"] == 200, f"{[(c['path'], c['status']) for c in s.calls()]}")
            g.expect("F3: Access db says revoked", (access_row(bid) or {}).get("status") == "revoked", "revoked")
        else:
            g.expect("F3: local path makes no Access call", not s.calls(), f"{len(s.calls())} calls")

    if not service:
        return

    bid, _, _ = book()
    with g.scenario("F3: cancel a never-unlocked booking") as s:
        st, _ = cancel(bid)
        revokes = [c for c in s.calls() if c["path"] == f"/bookings/{bid}/access/revoke"]
        g.expect("F3: cancel -> 200, revoke answered 404", st == 200 and len(revokes) == 1
                 and revokes[0]["status"] == 404, f"-> {st}, {[c['status'] for c in revokes]}")

    bid, _, _ = book()
    _, first = unlock(bid)
    probe("POST", f"/bookings/{bid}/check-in", {"access_code": (first or {}).get("access_code")})
    with g.scenario("F3: cancel after check-in (used is final)") as s:
        st, _ = cancel(bid)
        revokes = [c for c in s.calls() if c["path"] == f"/bookings/{bid}/access/revoke"]
        g.expect("F3: cancel -> 200, revoke answered 409", st == 200 and len(revokes) == 1
                 and revokes[0]["status"] == 409, f"-> {st}, {[c['status'] for c in revokes]}")
        g.expect("F3: Access db still used", (access_row(bid) or {}).get("status") == "used", "used")

    bid, _, _ = book()
    unlock(bid)
    with g.scenario("F3: cancel while Access is down") as s:
        compose("stop", "app")
        st, _ = cancel(bid)
        g.expect("F3: cancel -> 200 anyway", st == 200, f"-> {st}")
        failed = [c for c in s.calls() if c["path"] == f"/bookings/{bid}/access/revoke"]
        g.expect("F3: the failed revoke was recorded", len(failed) == 1 and failed[0]["status"] in (0, 502),
                 f"{[c['status'] for c in failed]}")
        compose("start", "app")
        wait_ok(f"{TAP}/health")
        g.expect("F3: missed revoke left the record available (repaired by the copy rule, F4)",
                 (access_row(bid) or {}).get("status") == "available", (access_row(bid) or {}).get("status"))


# --- F4: copy the old path's codes, then switch -------------------------------------


def switch_spacey(access_url):
    """Recreate the spacey container with another ACCESS_URL (same image, same db)."""
    compose("up", "-d", "--no-deps", "spacey", env={"SPACEY_ACCESS_URL": access_url})
    os.environ["SPACEY_ACCESS_URL"] = access_url
    assert wait_ok(f"{SPACEY}/health"), "spacey not healthy after the switch"


def copy(apply=True):
    """scripts/migrate_from_spacey.py, spacey db -> access db (the real script)."""
    root = Path(__file__).resolve().parent.parent
    args = [sys.executable, str(root / "scripts" / "migrate_from_spacey.py")] + (["--apply"] if apply else [])
    r = subprocess.run(args, capture_output=True, text=True, cwd=root,
                       env={**os.environ, "SOURCE_DATABASE_URL": SPACEY_DB, "TARGET_DATABASE_URL": ACCESS_DB})
    return r.returncode, r.stdout.strip().replace("\n", " · ")


def access_count():
    return db_row(ACCESS_DB, "SELECT count(*) AS n FROM access")["n"]


def f4_copy_then_switch(g):
    if os.environ.get("SPACEY_ACCESS_URL"):
        g.ok("F4: copy rehearsal", "skipped: needs a stack that starts on the old path (run F4 local)")
        return
    # 1. Codes made by the old path (spacey's own access table).
    old = {}
    for name in ("A", "B", "C", "E"):
        bid, _, _ = book()
        st, body = unlock(bid)
        old[name] = (bid, body["access_code"])
    d_id, _, _ = book()  # paid, never unlocked
    g.expect("F4: old path issued 4 codes with no Access call",
             not any(not is_host(c) for c in captured()[-50:] if c["path"].startswith(tuple(
                 f"/bookings/{b}/" for b, _ in old.values()))), "0 calls")

    # 2. Dry run, then copy.
    before = access_count()
    rc, out = copy(apply=False)
    g.expect("F4: dry run writes nothing", rc == 0 and access_count() == before and "dry run" in out, out)
    rc, out = copy()
    g.expect("F4: copy applied", rc == 0 and "applied" in out, out)
    for name, (bid, code) in old.items():
        row = access_row(bid)
        g.expect(f"F4: {name} copied with its code", row is not None and row["access_code"] == code
                 and row["status"] == "available", (row or {}).get("status"))

    # 3. Cancel C on the old path, copy again: safe to repeat, C -> revoked.
    cancel(old["C"][0])
    rc, out = copy()
    g.expect("F4: second copy inserts nothing new", rc == 0 and "inserted 0" in out, out)
    g.expect("F4: C cancelled on the old path -> revoked", (access_row(old["C"][0]) or {}).get("status") == "revoked",
             (access_row(old["C"][0]) or {}).get("status"))

    # 4. Switch spacey to the service.
    switch_spacey("http://tap:8080")
    with g.scenario("F4: after the switch, old codes come back unchanged") as s:
        for name in ("A", "B"):
            bid, code = old[name]
            st, body = unlock(bid)
            g.expect(f"F4: {name} unlock -> same code", st == 200 and body == {"booking_id": bid, "access_code": code},
                     f"-> {st}, same: {isinstance(body, dict) and body.get('access_code') == code}")
        creates = [c for c in s.calls() if c["method"] == "POST" and c["path"].endswith("/access")]
        g.expect("F4: the service found them (create answered 200, not 201)",
                 len(creates) == 2 and all(c["status"] == 200 for c in creates), f"{[c['status'] for c in creates]}")
    with g.scenario("F4: after the switch, a never-unlocked booking gets a new code") as s:
        st, body = unlock(d_id)
        creates = [c for c in s.calls() if c["path"] == f"/bookings/{d_id}/access"]
        g.expect("F4: D unlock -> 201 from the service", st == 200 and len(creates) == 1 and creates[0]["status"] == 201,
                 f"-> {st}, {[c['status'] for c in creates]}")
    with g.scenario("F4: the cancelled booking stays gone") as s:
        st, _ = unlock(old["C"][0])
        g.expect("F4: C unlock -> 404, no call", st == 404 and not s.calls(), f"-> {st}, {len(s.calls())} calls")

    # 5. A revoke missed while Access was down is repaired by the next copy.
    compose("stop", "app")
    cancel(old["E"][0])
    compose("start", "app")
    wait_ok(f"{TAP}/health")
    g.expect("F4: E missed its revoke (Access was down)", (access_row(old["E"][0]) or {}).get("status") == "available",
             (access_row(old["E"][0]) or {}).get("status"))
    rc, out = copy()
    g.expect("F4: the next copy repairs it -> revoked", rc == 0 and (access_row(old["E"][0]) or {}).get("status") == "revoked",
             out)


# --- F5: cutover - service mode leaves spacey's table alone; rollback works ---------


def spacey_access_table():
    """(rows, checksum) of spacey's own access table."""
    return tuple(db_row(SPACEY_DB, "SELECT count(*) AS n, "
                        "coalesce(md5(string_agg(booking_id || ':' || access_code, ',' ORDER BY booking_id)), '') AS h "
                        "FROM access").values())


def f5_cutover_and_rollback(g):
    if not os.environ.get("SPACEY_ACCESS_URL"):
        switch_spacey("http://tap:8080")  # F4 normally leaves it switched; make sure

    # Service mode: unlocks (old and new bookings) never touch spacey's access table.
    pre_id, _, _ = book()
    switch_spacey("")
    _, pre_local = unlock(pre_id)           # issued on the old path, before the copy
    rc, out = copy()
    g.expect("F5: copy before the cutover", rc == 0, out)
    switch_spacey("http://tap:8080")
    before = spacey_access_table()
    with g.scenario("F5: service mode never writes spacey's access table") as s:
        post_id, _, _ = book()
        st1, post_service = unlock(post_id)
        st2, pre_service = unlock(pre_id)
        g.expect("F5: unlocks answered by the service", st1 == st2 == 200 and len(s.calls()) == 2,
                 f"-> {st1}, {st2}; {len(s.calls())} calls")
        g.expect("F5: pre-cutover booking keeps its old-path code", pre_service == pre_local,
                 f"same: {pre_service == pre_local}")
    g.expect("F5: spacey's access table unchanged (count + checksum)", spacey_access_table() == before,
             f"{before[0]} rows before and after")

    # Rollback: unset ACCESS_URL.
    switch_spacey("")
    with g.scenario("F5: rollback (ACCESS_URL unset)") as s:
        st, body = unlock(pre_id)
        g.expect("F5: rollback - pre-cutover booking: same code, old path", st == 200 and body == pre_local
                 and not s.calls(), f"-> {st}, same: {body == pre_local}, {len(s.calls())} calls")
        st, rolled = unlock(post_id)
        g.expect("F5: rollback - post-cutover booking still unlocks (200)", st == 200, f"-> {st}")
        g.expect("F5: rollback cost made visible - post-cutover booking gets a different local code",
                 rolled != post_service, "a code issued after the cutover isn't in spacey's table")

    # Forward again: the service's code wins (the copy never overwrites).
    rc, out = copy()
    switch_spacey("http://tap:8080")
    with g.scenario("F5: forward again") as s:
        st, again = unlock(post_id)
        g.expect("F5: forward again - the service's code comes back", st == 200 and again == post_service,
                 f"-> {st}, same as before rollback: {again == post_service}")


# --- F6: the refusals of the lifecycle, over the wire from inside spacey -------------

REFUSALS = r"""
import json, sys
from access import functions as f
b = int(sys.argv[1])
s, e = "2031-04-01T10:00:00+00:00", "2031-04-01T12:00:00+00:00"
out = {}
rec, _ = f.create_access(b, s, e)
out["wrong code"] = f.check_in(b, "00000000" if rec["access_code"] != "00000000" else "11111111")[1]
out["check-out before check-in"] = f.check_out(b)[1]
out["check-in"] = f.check_in(b, rec["access_code"])[1]
out["check-in again"] = f.check_in(b, rec["access_code"])[1]
out["expire a used code"] = f.expire_access(b)[1]
out["revoke a used code"] = f.revoke_access(b)[1]
out["check-out"] = f.check_out(b)[1]
f.create_access(b + 1, s, e); f.expire_access(b + 1)
out["revoke an expired code"] = f.revoke_access(b + 1)[1]
out["check-in an expired code"] = f.check_in(b + 1, "x")[1]
f.create_access(b + 2, "2020-01-01T10:00:00+00:00", "2020-01-01T11:00:00+00:00")
out["read an overdue code"] = f.read_access(b + 2)[0]["status"]
out["unknown booking"] = f.read_access(2147480002)[1]
print(json.dumps(out))
"""


def f6_refusals(g):
    bid = 860000 + int(time.time()) % 10000
    with g.scenario("F6: lifecycle refusals from inside spacey"):
        rc, out, err = exec_in_spacey(REFUSALS, bid, env={"ACCESS_URL": "http://tap:8080"})
        got = json.loads(out) if rc == 0 else {"error": err}
        want = {"wrong code": 403, "check-out before check-in": 409, "check-in": 200, "check-in again": 200,
                "expire a used code": 409, "revoke a used code": 409, "check-out": 200,
                "revoke an expired code": 409, "check-in an expired code": 403,
                "read an overdue code": "expired", "unknown booking": 404}
        for key, value in want.items():
            g.expect(f"F6: {key}", got.get(key) == value, f"-> {got.get(key)} (contract: {value})")


# Scenarios added by later steps (cumulative: a step runs every earlier step's too).
EXTRA = {"F1": [f1_functions], "F2": [f2_access_down], "F3": [f3_cancel], "F4": [f4_copy_then_switch],
         "F5": [f5_cutover_and_rollback], "F6": [f6_refusals]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("level", choices=LEVELS)
    p.add_argument("--report", required=True)
    a = p.parse_args()
    g = run(a.level)
    Path(a.report).write_text(g.report())
    print(g.report())
    sys.exit(0 if g.passed() else 1)


if __name__ == "__main__":
    main()
