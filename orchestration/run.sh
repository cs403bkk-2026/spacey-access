#!/usr/bin/env bash
# Extraction gate: build spacey-access (this checkout) and spacey (../spacey or
# $SPACEY_DIR) from their extract branches, run them with both databases, the
# migrations and a recording tap, act like spacey-frontend, inspect every call.
#
#   orchestration/run.sh <F0..F6> [service|local]     KEEP=1 leaves the stack up
#
# Local only. Never in CI: no workflow references this directory.
# Captures and reports go to $OUT (default /tmp/overnight/captures/<level>);
# they contain access codes and the token, so they never go into a repo.
set -euo pipefail
cd "$(dirname "$0")/.."

LEVEL=${1:?level F0..F6}
MODE=${2:-local}
SPACEY_DIR=$(cd "${SPACEY_DIR:-../spacey}" && pwd)
OUT=${OUT:-/tmp/overnight/captures/$LEVEL-$MODE}
STATE=${STATE:-/tmp/overnight/state}
PY=${PY:-/tmp/overnight/venv-access/bin/python}

mkdir -p "$STATE" && chmod 700 "$STATE"
rm -rf "$OUT" && mkdir -p "$OUT" && chmod 700 "$OUT"
[ -s "$STATE/token" ] || (umask 077 && openssl rand -hex 32 > "$STATE/token")

access_sha=$(git rev-parse --short HEAD)$( [ -n "$(git status --porcelain)" ] && echo -dirty || true)
spacey_sha=$(git -C "$SPACEY_DIR" rev-parse --short HEAD)$( [ -n "$(git -C "$SPACEY_DIR" status --porcelain)" ] && echo -dirty || true)

echo "== $LEVEL ($MODE): spacey-access $access_sha, spacey $spacey_sha"
docker build -q -t "extract/spacey-access:$access_sha" . >/dev/null
docker build -q -t "extract/spacey:$spacey_sha" "$SPACEY_DIR" >/dev/null

export ACCESS_IMAGE="extract/spacey-access:$access_sha" ACCESS_REVISION="$access_sha"
export SPACEY_IMAGE="extract/spacey:$spacey_sha" SPACEY_REVISION="$spacey_sha"
export LOCAL_SERVICE_TOKEN; LOCAL_SERVICE_TOKEN=$(cat "$STATE/token")
export CAPTURE_DIR="$OUT" SPACEY_DIR
export SPACEY_ACCESS_URL=""; [ "$MODE" = service ] && SPACEY_ACCESS_URL="http://tap:8080"
export COMPOSE_CMD="docker compose -p extract-e2e -f compose.local.yaml -f orchestration/compose.extract.yaml"

$COMPOSE_CMD down -v --remove-orphans >/dev/null 2>&1 || true
if ! $COMPOSE_CMD up -d --wait --wait-timeout 300 >"$OUT/up.log" 2>&1; then
  echo "stack FAILED to start:"; tail -30 "$OUT/up.log"; exit 1
fi

rc=0
"$PY" orchestration/e2e.py "$LEVEL" --report "$OUT/report.md" || rc=$?
$COMPOSE_CMD logs --no-color >"$OUT/compose.log" 2>&1 || true
[ "${KEEP:-0}" = 1 ] || $COMPOSE_CMD down -v --remove-orphans >/dev/null 2>&1 || true
echo "== $LEVEL ($MODE): $([ $rc = 0 ] && echo GREEN || echo RED) · report $OUT/report.md"
exit $rc
