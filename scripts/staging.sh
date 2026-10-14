#!/usr/bin/env bash
# Local staging for Access (stop-gap until the Nomad access-staging job).
#
#   scripts/staging.sh up [IMAGE]   deploy IMAGE (or build the checkout), then smoke
#   scripts/staging.sh smoke        the 0.2.0 API checks, plus spacey -> Access
#   scripts/staging.sh rollback     redeploy the previous image, then smoke
#   scripts/staging.sh status       containers, deployed image, /health
#   scripts/staging.sh logs         app logs
#   scripts/staging.sh down         stop (keeps the database)
#   scripts/staging.sh reset        stop and delete the database
#
# spacey runs next to Access as its caller: SPACEY_IMAGE=<image> picks it,
# otherwise the image of spacey's current main is used.
#
# Never prints an access code or the token.
set -euo pipefail

cd "$(dirname "$0")/.."
STATE=.staging
URL=http://127.0.0.1:8023
COMPOSE=(docker compose -f compose.staging.yaml)

mkdir -p "$STATE"
chmod 700 "$STATE"

# For commands that only look at or stop what is running; compose still wants
# the variables set, but their values don't matter there.
inspect() {
  ACCESS_IMAGE=- ACCESS_REVISION=- SPACEY_IMAGE=- SPACEY_REVISION=- STAGING_SERVICE_TOKEN=- \
    "${COMPOSE[@]}" "$@"
}

# spacey's image: $SPACEY_IMAGE if given, else the published image of spacey's
# main (release images are tagged with the commit sha).
spacey_image() {
  if [ -n "${SPACEY_IMAGE:-}" ]; then echo "$SPACEY_IMAGE"; return; fi
  local sha image
  sha=$(git ls-remote https://github.com/cs403bkk-2026/spacey refs/heads/main | cut -f1)
  image="ghcr.io/cs403bkk-2026/spacey:$sha"
  if [ -z "$sha" ] || ! docker manifest inspect "$image" >/dev/null 2>&1; then
    echo "no published spacey image for main ($sha); set SPACEY_IMAGE=<image>" >&2
    return 1
  fi
  echo "$image"
}

token() {
  if [ ! -s "$STATE/token" ]; then
    (umask 077 && openssl rand -hex 32 > "$STATE/token")
  fi
  cat "$STATE/token"
}

# The revision /health should report for an image: the tag when it is a
# commit sha (release images are tagged that way), otherwise the whole ref.
revision_of() {
  local tag="${1##*:}"
  tag="${tag#staging-}"
  if [[ "$tag" =~ ^[0-9a-f]{40}(-dirty)?$ ]]; then echo "$tag"; else echo "$1"; fi
}

build_checkout() {
  local sha
  sha=$(git rev-parse HEAD)
  if [ -n "$(git status --porcelain -- app.py gunicorn.conf.py openapi.yaml src migrations requirements.txt Dockerfile)" ]; then
    sha="$sha-dirty"
  fi
  docker build -q -t "spacey-access:staging-$sha" . >/dev/null
  echo "spacey-access:staging-$sha"
}

deploy() {
  local image="$1" revision spacey
  revision=$(revision_of "$image")
  spacey=$(spacey_image) || return 1
  echo "deploying $image (spacey: ${spacey##*/})"
  if ! ACCESS_IMAGE="$image" ACCESS_REVISION="$revision" \
    SPACEY_IMAGE="$spacey" SPACEY_REVISION="$(revision_of "$spacey")" STAGING_SERVICE_TOKEN="$(token)" \
    "${COMPOSE[@]}" up -d --wait --wait-timeout 300 >"$STATE/up.log" 2>&1; then
    echo "deploy FAILED:"; tail -20 "$STATE/up.log"
    return 1
  fi

  if [ -s "$STATE/current" ] && [ "$(cat "$STATE/current")" != "$image" ]; then
    cp "$STATE/current" "$STATE/previous"
  fi
  echo "$image" > "$STATE/current"

  for _ in $(seq 1 30); do
    if curl -fs "$URL/health" | jq -e --arg r "$revision" '.status == "ok" and .revision == $r' >/dev/null; then
      echo "healthy: revision $revision at $URL"
      return 0
    fi
    sleep 1
  done
  echo "NOT healthy after 30s:"; curl -s "$URL/health" || true; echo
  return 1
}

PASS=0
FAIL=0
KNOWN=0
check() { # name expected actual
  if [ "$2" = "$3" ]; then echo "  PASS   $1 ($3)"; PASS=$((PASS + 1))
  else echo "  FAIL   $1 (expected $2, got $3)"; FAIL=$((FAIL + 1)); fi
}
# A contract gap the team already tracks: shown on every run, but doesn't fail
# the deploy. Once it passes, turn it into a normal check.
known() { # name expected actual issue
  if [ "$2" = "$3" ]; then echo "  PASS   $1 ($3) - known gap fixed, make it a normal check"; PASS=$((PASS + 1))
  else echo "  KNOWN  $1 (expected $2, got $3; $4)"; KNOWN=$((KNOWN + 1)); fi
}

# POST/GET helper: prints only the status code; the body goes to $STATE/resp.
call() { # method path [json]
  local args=(-s -o "$STATE/resp" -w '%{http_code}' -X "$1" "$URL$2" -H "Authorization: Bearer $(token)")
  [ $# -ge 3 ] && args+=(-H 'Content-Type: application/json' -d "$3")
  curl "${args[@]}"
}

# Runs inside the spacey container and calls ${ACCESS_URL}<path> with spacey's
# own SERVICE_TOKEN, so it proves spacey's settings, not the host's. Prints only
# the status code (000 = Access unreachable).
from_spacey() { # path
  inspect exec -T spacey python -c '
import os, sys, urllib.request, urllib.error
req = urllib.request.Request(os.environ["ACCESS_URL"] + sys.argv[1],
                             headers={"Authorization": "Bearer " + os.environ["SERVICE_TOKEN"]})
try: print(urllib.request.urlopen(req, timeout=3).status)
except urllib.error.HTTPError as e: print(e.code)
except Exception: print("000")' "$1" 2>/dev/null || echo "000"
}

# The 0.2.0 contract, so old code on a newer schema (or the reverse) fails here
# even when /health is green.
smoke() {
  local id body code
  id=$((900000 + RANDOM))
  body='{"start_time":"2026-12-01T10:00:00+00:00","end_time":"2026-12-01T12:00:00+00:00"}'
  echo "smoke test against $URL (bookings $id, $((id + 1)))"

  check "health is ok" ok "$(curl -s "$URL/health" | jq -r .status)"
  check "read unknown booking (full 0.2.0 SELECT)" 404 "$(call GET /bookings/2147480000/access)"
  check "create access" 201 "$(call POST "/bookings/$id/access" "$body")"
  code=$(jq -r '.access_code // empty' "$STATE/resp" 2>/dev/null || true)
  check "read it back" 200 "$(call GET "/bookings/$id/access")"
  known "repeat create is safe (200, same code)" 200 "$(call POST "/bookings/$id/access" "$body")" "Phase 2"
  check "check-in with the right code" 200 "$(call POST "/bookings/$id/check-in" "{\"access_code\":\"$code\"}")"
  check "create a second record" 201 "$(call POST "/bookings/$((id + 1))/access" "$body")"
  check "revoke it" 200 "$(call POST "/bookings/$((id + 1))/access/revoke")"
  check "create without token is refused" 401 \
    "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$URL/bookings/$((id + 2))/access" -H 'Content-Type: application/json' -d "$body")"

  # ARCH-03: spacey, with its ACCESS_URL and SERVICE_TOKEN, reaches Access.
  check "spacey reaches Access /health (from inside spacey)" 200 "$(from_spacey /health)"
  check "spacey's token is accepted (read unknown booking)" 404 "$(from_spacey /bookings/2147480000/access)"

  rm -f "$STATE/resp"
  echo "$PASS passed, $FAIL failed, $KNOWN known gaps"
  [ "$FAIL" -eq 0 ]
}

# A deploy only counts when /health shows the revision AND the API works.
deploy_and_smoke() {
  deploy "$1" || return 1
  if ! smoke; then
    echo "DEPLOYED BUT BROKEN: /health is ok, the API is not. Roll back or fix forward."
    return 1
  fi
}

case "${1:-}" in
  up)       deploy_and_smoke "${2:-$(build_checkout)}" ;;
  smoke)    smoke ;;
  rollback)
    [ -s "$STATE/previous" ] || { echo "no previous image to roll back to"; exit 1; }
    deploy_and_smoke "$(cat "$STATE/previous")" ;;
  status)
    inspect ps --format 'table {{.Service}}\t{{.State}}\t{{.Status}}'
    echo "current:  $(cat "$STATE/current" 2>/dev/null || echo none)"
    echo "previous: $(cat "$STATE/previous" 2>/dev/null || echo none)"
    echo -n "access: "; curl -s "$URL/health" || echo -n "not reachable"; echo
    echo -n "spacey: "; curl -s http://127.0.0.1:8024/health || echo -n "not reachable"; echo ;;
  logs)     inspect logs app ;;
  down)     inspect down ;;
  reset)    inspect down -v
            rm -f "$STATE/current" "$STATE/previous" ;;
  *)        sed -n '2,12p' "$0"; exit 1 ;;
esac
