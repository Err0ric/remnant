#!/bin/bash
# The demo install: synthetic logs for a fictional company, loaded into a throwaway server
# on http://127.0.0.1:8090 (loopback, no accounts). `make demo` runs this.
#
#   bash scripts/demo/run.sh            generate, start, load, keep serving (Ctrl+C stops)
#   DEMO_DETACH=1 bash scripts/demo/run.sh   leave the server running and return
#
# Everything lives in data/demo/ (gitignored) and is replaced on every run. Needs uv, and
# the frontend built once (cd frontend && pnpm install && pnpm build) for the web UI.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
DEMO="$ROOT/data/demo"
PORT=${DEMO_PORT:-8090}
URL="http://127.0.0.1:$PORT"

if curl -fsS "$URL/api/auth/state" >/dev/null 2>&1; then
  echo "something already answers on $URL; stop it or set DEMO_PORT" >&2
  exit 1
fi
rm -rf "$DEMO"
mkdir -p "$DEMO/state"
python3 "$ROOT/scripts/demo/generate.py" "$DEMO/logs"
[ -d "$ROOT/frontend/dist" ] || echo "note: frontend/dist is missing, so only the API is served" >&2

cd "$ROOT/backend"
export APP__SERVER__HOST=127.0.0.1 APP__SERVER__PORT=$PORT \
  APP__SERVER__STATIC_DIR="$ROOT/frontend/dist" \
  APP__PATHS__DATA_DIR="$DEMO/state" APP__PATHS__ALLOWED_ROOTS="$DEMO/logs" \
  APP__ENRICHMENT__PLACE_DOCUMENTATION_RANGES=true
uv run app-server >"$DEMO/server.log" 2>&1 &
SERVER=$!
echo "$SERVER" >"$DEMO/server.pid"
if ! uv run python "$ROOT/scripts/demo/load.py" --url "$URL" --logs "$DEMO/logs"; then
  kill "$SERVER" 2>/dev/null || true
  echo "load failed; server log: $DEMO/server.log" >&2
  exit 1
fi
echo "demo ready: $URL  (server log: $DEMO/server.log)"
if [ "${DEMO_DETACH:-0}" = 1 ]; then
  exit 0
fi
trap 'kill "$SERVER" 2>/dev/null || true' INT TERM EXIT
wait "$SERVER"
