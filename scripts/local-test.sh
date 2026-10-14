#!/usr/bin/env bash
# Local integration test for Access. Runs on a developer machine; not staging.
#
#   scripts/local-test.sh up [IMAGE]   deploy IMAGE (or build the checkout), then smoke
#   scripts/local-test.sh smoke        the 0.2.0 API checks on their own
#   scripts/local-test.sh rollback     redeploy the previous image, then smoke
#   scripts/local-test.sh status       containers, deployed image, /health
#   scripts/local-test.sh logs         app logs
#   scripts/local-test.sh down         stop (keeps the database)
#   scripts/local-test.sh reset        stop and delete the database
#
# Never prints an access code or the token.
set -euo pipefail

cd "$(dirname "$0")/.."
STATE=.local-test
URL=http://127.0.0.1:8023
COMPOSE=(docker compose -f compose.local.yaml)

mkdir -p "$STATE"
chmod 700 "$STATE"

# For commands that only look at or stop what is running; compose still wants
# the variables set, but their values don't matter there.
inspect() { ACCESS_IMAGE=- ACCESS_REVISION=- LOCAL_SERVICE_TOKEN=- "${COMPOSE[@]}" "$@"; }

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
  tag="${tag#local-}"
  if [[ "$tag" =~ ^[0-9a-f]{40}(-dirty)?$ ]]; then echo "$tag"; else echo "$1"; fi
}

build_checkout() {
  local sha
  sha=$(git rev-parse HEAD)
  if [ -n "$(git status --porcelain -- app.py gunicorn.conf.py openapi.yaml src migrations requirements.txt Dockerfile)" ]; then
    sha="$sha-dirty"
  fi
  docker build -q -t "spacey-access:local-$sha" . >/dev/null
  echo "spacey-access:local-$sha"
}

deploy() {
  local image="$1" revision
  revision=$(revision_of "$image")
  echo "deploying $image"
  if ! ACCESS_IMAGE="$image" ACCESS_REVISION="$revision" LOCAL_SERVICE_TOKEN="$(token)" \
    "${COMPOSE[@]}" up -d --wait --wait-timeout 120 >"$STATE/up.log" 2>&1; then
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
    curl -s "$URL/health" || echo "not reachable"; echo ;;
  logs)     inspect logs app ;;
  down)     inspect down ;;
  reset)    inspect down -v
            rm -f "$STATE/current" "$STATE/previous" ;;
  *)        sed -n '2,12p' "$0"; exit 1 ;;
esac
