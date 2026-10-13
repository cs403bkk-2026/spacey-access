#!/usr/bin/env bash
# Local staging for Access (stop-gap until the Nomad access-staging job).
#
#   scripts/staging.sh up [IMAGE]   deploy IMAGE, or build the current checkout
#   scripts/staging.sh smoke        health + create/repeat/check-in checks
#   scripts/staging.sh rollback     redeploy the previous image
#   scripts/staging.sh status       containers, deployed image, /health
#   scripts/staging.sh logs         app logs
#   scripts/staging.sh down         stop (keeps the database)
#   scripts/staging.sh reset        stop and delete the database
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
inspect() { ACCESS_IMAGE=- ACCESS_REVISION=- STAGING_SERVICE_TOKEN=- "${COMPOSE[@]}" "$@"; }

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
  if [ -n "$(git status --porcelain -- app.py gunicorn.conf.py openapi.yaml src requirements.txt Dockerfile)" ]; then
    sha="$sha-dirty"
  fi
  docker build -q -t "spacey-access:staging-$sha" . >/dev/null
  echo "spacey-access:staging-$sha"
}

deploy() {
  local image="$1" revision
  revision=$(revision_of "$image")
  echo "deploying $image"
  if ! ACCESS_IMAGE="$image" ACCESS_REVISION="$revision" STAGING_SERVICE_TOKEN="$(token)" \
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
check() { # name expected actual
  if [ "$2" = "$3" ]; then echo "  PASS  $1 ($3)"; PASS=$((PASS + 1))
  else echo "  FAIL  $1 (expected $2, got $3)"; FAIL=$((FAIL + 1)); fi
}

smoke() {
  local auth="Authorization: Bearer $(token)" id body status code
  id=$((900000 + RANDOM))
  body='{"start_time":"2026-12-01T10:00:00+00:00","end_time":"2026-12-01T12:00:00+00:00"}'
  echo "smoke test against $URL (booking $id)"

  check "health is ok" ok "$(curl -s "$URL/health" | jq -r .status)"

  status=$(curl -s -o "$STATE/resp" -w '%{http_code}' -X POST "$URL/bookings/$id/access" \
    -H "$auth" -H 'Content-Type: application/json' -d "$body")
  check "create access" 201 "$status"
  code=$(jq -r '.access_code // empty' "$STATE/resp" 2>/dev/null || true)

  status=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$URL/bookings/$id/access" \
    -H "$auth" -H 'Content-Type: application/json' -d "$body")
  check "repeat create is safe (contract: 200, same code)" 200 "$status"

  status=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$URL/bookings/$id/check-in" \
    -H "$auth" -H 'Content-Type: application/json' -d "{\"access_code\":\"$code\"}")
  check "check-in with the right code" 200 "$status"

  status=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$URL/bookings/$((id + 1))/access" \
    -H 'Content-Type: application/json' -d "$body")
  check "create without token is refused" 401 "$status"

  rm -f "$STATE/resp"
  echo "$PASS passed, $FAIL failed"
  [ "$FAIL" -eq 0 ]
}

case "${1:-}" in
  up)       deploy "${2:-$(build_checkout)}" ;;
  smoke)    smoke ;;
  rollback)
    [ -s "$STATE/previous" ] || { echo "no previous image to roll back to"; exit 1; }
    deploy "$(cat "$STATE/previous")" ;;
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
