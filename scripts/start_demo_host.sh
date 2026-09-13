#!/usr/bin/env bash
# NightOwls — start host-side demo services (tracker + seeder peer).
# Then expose the tracker yourself with ngrok.
#
# Usage:
#   ./demo
#   ./scripts/start_demo_host.sh
#   ./scripts/start_demo_host.sh --no-seed

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"
nightowls_root

TRACKER_HOST="${TRACKER_HOST:-0.0.0.0}"
TRACKER_PORT="${TRACKER_PORT:-5000}"
TRACKER_DB="${TRACKER_DB:-${ROOT}/data/demo_tracker.db}"
PEER_PORT="${PEER_PORT:-6001}"
PEER_IP="${PEER_IP:-demo-host}"
PEER_HOST="${PEER_HOST:-0.0.0.0}"
RUN_DIR="${RUN_DIR:-/tmp/nightowls_demo_host}"
LOCAL_TRACKER_URL="http://127.0.0.1:${TRACKER_PORT}"
DO_SEED=1
FREE_PORTS=1
PIDS=()

usage() {
  cat <<EOF
NightOwls demo host — tracker + seeder peer (for ngrok demos)

Usage: $(basename "$0") [options]

Starts:
  1) Tracker on ${TRACKER_HOST}:${TRACKER_PORT}
  2) Seeder peer UI on http://127.0.0.1:${PEER_PORT}/
  3) Optional demo files on the seeder (default: on)

Then YOU run ngrok in another terminal:
  ngrok http ${TRACKER_PORT}

Copy the https://….ngrok… URL into config/nightowls.json → tracker_url
(and onto remote machines). Remote peers: ./client <ngrok-host>

Options:
  --no-seed         Do not pre-seed demo files
  --no-free-ports   Do not kill processes already using demo ports
  --port N          Tracker port (default: ${TRACKER_PORT})
  --peer-port N     Seeder peer port (default: ${PEER_PORT})
  --db PATH         Tracker SQLite path
  -h, --help        Show this help

Environment:
  TRACKER_HOST  TRACKER_PORT  TRACKER_DB
  PEER_IP  PEER_PORT  PEER_HOST  RUN_DIR
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --no-seed) DO_SEED=0; shift ;;
    --no-free-ports) FREE_PORTS=0; shift ;;
    --port)
      TRACKER_PORT="${2:-}"
      [[ -n "$TRACKER_PORT" ]] || { echo "error: --port needs a value" >&2; exit 1; }
      LOCAL_TRACKER_URL="http://127.0.0.1:${TRACKER_PORT}"
      shift 2
      ;;
    --peer-port)
      PEER_PORT="${2:-}"
      [[ -n "$PEER_PORT" ]] || { echo "error: --peer-port needs a value" >&2; exit 1; }
      shift 2
      ;;
    --db)
      TRACKER_DB="${2:-}"
      [[ -n "$TRACKER_DB" ]] || { echo "error: --db needs a value" >&2; exit 1; }
      shift 2
      ;;
    *)
      echo "error: unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

port_pids() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
  elif command -v fuser >/dev/null 2>&1; then
    fuser "${port}/tcp" 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+$' || true
  else
    ss -ltnp 2>/dev/null | awk -v p=":$port" '$4 ~ p {print}' | \
      sed -n 's/.*pid=\([0-9]\+\).*/\1/p' || true
  fi
}

free_port() {
  local port="$1"
  local pids
  pids="$(port_pids "$port")"
  if [[ -n "$pids" ]]; then
    echo "[demo] freeing port $port (pids: $pids)"
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 0.4
    pids="$(port_pids "$port")"
    if [[ -n "$pids" ]]; then
      # shellcheck disable=SC2086
      kill -9 $pids 2>/dev/null || true
      sleep 0.2
    fi
  fi
}

cleanup() {
  echo
  echo "[demo] shutting down..."
  local pid
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
  echo "[demo] stopped."
}

wait_http() {
  local url="$1"
  local label="$2"
  local i
  for i in $(seq 1 50); do
    if curl -sf "$url" >/dev/null 2>&1; then
      echo "[demo] $label is up"
      return 0
    fi
    sleep 0.25
  done
  echo "[demo] ERROR: $label did not become ready ($url)" >&2
  return 1
}

ensure_venv "[demo]"
# Wormhole is required for cross-network demos.
if ! "$PYTHON" -c "import wormhole, crochet" 2>/dev/null; then
  echo "[demo] installing magic-wormhole stack ..."
  "$PYTHON" -m pip install -r "${ROOT}/requirements.txt"
fi

mkdir -p "$RUN_DIR" "$(dirname "$TRACKER_DB")"
PEER_DATA_DIR="${RUN_DIR}/seeder"
mkdir -p "$PEER_DATA_DIR"

if [[ "$FREE_PORTS" -eq 1 ]]; then
  free_port "$TRACKER_PORT"
  free_port "$PEER_PORT"
fi

# Fresh demo DB each run (stable path under data/ otherwise accumulates jobs).
rm -f "$TRACKER_DB"

trap cleanup EXIT INT TERM

echo "[demo] starting tracker on ${TRACKER_HOST}:${TRACKER_PORT} ..."
TRACKER_DB="$TRACKER_DB" \
  "$PYTHON" -c "
from tracker.app import create_app, app
create_app()
app.run(host='${TRACKER_HOST}', port=${TRACKER_PORT}, debug=False, use_reloader=False)
" >"${RUN_DIR}/tracker.log" 2>&1 &
PIDS+=($!)
wait_http "${LOCAL_TRACKER_URL}/files" "tracker"

echo "[demo] starting seeder peer on :${PEER_PORT} (id ${PEER_IP}) ..."
# Local peer talks to tracker on loopback; remotes will use ngrok URL from config.
PEER_DATA_DIR="$PEER_DATA_DIR" \
PEER_PORT="$PEER_PORT" \
PEER_IP="$PEER_IP" \
PEER_HOST="$PEER_HOST" \
TRACKER_URL="$LOCAL_TRACKER_URL" \
  "$PYTHON" -m peer.app >"${RUN_DIR}/seeder.log" 2>&1 &
PIDS+=($!)
wait_http "http://127.0.0.1:${PEER_PORT}/health" "seeder peer"

if [[ "$DO_SEED" -eq 1 ]]; then
  echo "[demo] seeding demo files ..."
  seed_dir="${RUN_DIR}/seed_sources"
  mkdir -p "$seed_dir"
  "$PYTHON" - <<PY
from pathlib import Path
base = Path("${seed_dir}")
(base / "notes.txt").write_text("NightOwls demo notes\\n" * 8000, encoding="utf-8")
(base / "sample.bin").write_bytes((b"NightOwls-demo-chunk-" * 20000)[:400_000])
print("wrote", base / "notes.txt", "and", base / "sample.bin")
PY
  "$PYTHON" -m peer.swarm upload \
    --path "${seed_dir}/notes.txt" \
    --tracker "$LOCAL_TRACKER_URL" \
    --data-dir "$PEER_DATA_DIR" \
    --peer-ip "$PEER_IP" \
    --peer-port "$PEER_PORT" \
    --filename "notes.txt"
  "$PYTHON" -m peer.swarm upload \
    --path "${seed_dir}/sample.bin" \
    --tracker "$LOCAL_TRACKER_URL" \
    --data-dir "$PEER_DATA_DIR" \
    --peer-ip "$PEER_IP" \
    --peer-port "$PEER_PORT" \
    --filename "sample.bin"
  echo "[demo] seeded notes.txt + sample.bin"
fi

echo
echo "=============================================="
echo " NightOwls demo host is running"
echo "----------------------------------------------"
echo " Tracker (local):  ${LOCAL_TRACKER_URL}/portal"
echo " Seeder UI:        http://127.0.0.1:${PEER_PORT}/"
echo " Logs:             ${RUN_DIR}/"
echo "----------------------------------------------"
echo " NEXT — expose the tracker with ngrok:"
echo
echo "   ngrok http ${TRACKER_PORT}"
echo
echo " Then set tracker_url in config/nightowls.json to the"
echo " https://….ngrok-free.app URL ngrok prints."
echo " Give that same config (or TRACKER_URL) to remote peers."
echo
echo " Remote machine (same config/nightowls.json with that tracker_url):"
echo "   ./client"
echo "----------------------------------------------"
echo " Press Ctrl+C to stop tracker + seeder."
echo "=============================================="
echo

while true; do
  for pid in "${PIDS[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "[demo] process $pid exited — check logs in ${RUN_DIR}/" >&2
      exit 1
    fi
  done
  sleep 1
done
