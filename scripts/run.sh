#!/usr/bin/env bash
# NightOwls-26 — start tracker + N peer UIs in one shot.
# Usage: ./scripts/run.sh [--seed] [--peers N] [--no-free-ports] [--help]

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${ROOT}/.venv/bin/python"
PIP="${ROOT}/.venv/bin/pip"

TRACKER_PORT="${TRACKER_PORT:-5000}"
TRACKER_HOST="${TRACKER_HOST:-127.0.0.1}"
TRACKER_DB="${TRACKER_DB:-/tmp/nightowls_tracker.db}"
TRACKER_URL="http://${TRACKER_HOST}:${TRACKER_PORT}"

PEER_COUNT=3
DO_SEED=0
FREE_PORTS=1
RUN_DIR="${RUN_DIR:-/tmp/nightowls_run}"
BASE_PEER_PORT="${BASE_PEER_PORT:-6001}"
PEER_IP="${PEER_IP:-127.0.0.1}"

PIDS=()

usage() {
  cat <<EOF
NightOwls demo launcher

Usage: $(basename "$0") [options]

Options:
  --seed            Seed 2 demo files onto peer 1 after startup
  --peers N         Number of peer nodes to start (default: 3, max: 8)
  --no-free-ports   Do not kill processes already using demo ports
  -h, --help        Show this help

Environment overrides:
  TRACKER_PORT   TRACKER_HOST   TRACKER_DB
  PEER_IP        BASE_PEER_PORT RUN_DIR

Examples:
  ./scripts/run.sh
  ./scripts/run.sh --seed
  ./scripts/run.sh --peers 2 --seed
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --seed) DO_SEED=1; shift ;;
    --peers)
      PEER_COUNT="${2:-}"
      if [[ -z "$PEER_COUNT" || ! "$PEER_COUNT" =~ ^[0-9]+$ ]]; then
        echo "error: --peers requires a number" >&2
        exit 1
      fi
      shift 2
      ;;
    --no-free-ports) FREE_PORTS=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "error: unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ "$PEER_COUNT" -lt 1 || "$PEER_COUNT" -gt 8 ]]; then
  echo "error: --peers must be between 1 and 8" >&2
  exit 1
fi

ensure_venv() {
  if [[ ! -x "$PYTHON" ]]; then
    echo "[run] creating virtualenv at .venv ..."
    python3 -m venv "${ROOT}/.venv"
  fi
  if ! "$PYTHON" -c "import flask" 2>/dev/null; then
    echo "[run] installing requirements ..."
    "$PIP" install -r "${ROOT}/requirements.txt"
  fi
}

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
    echo "[run] freeing port $port (pids: $pids)"
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
  echo "[run] shutting down..."
  local pid
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
  echo "[run] stopped."
}

wait_http() {
  local url="$1"
  local label="$2"
  local i
  for i in $(seq 1 40); do
    if curl -sf "$url" >/dev/null 2>&1; then
      echo "[run] $label is up"
      return 0
    fi
    sleep 0.25
  done
  echo "[run] ERROR: $label did not become ready ($url)" >&2
  return 1
}

ensure_venv
mkdir -p "$RUN_DIR"

if [[ "$FREE_PORTS" -eq 1 ]]; then
  free_port "$TRACKER_PORT"
  local_i=0
  while [[ "$local_i" -lt "$PEER_COUNT" ]]; do
    free_port $((BASE_PEER_PORT + local_i))
    local_i=$((local_i + 1))
  done
fi

rm -f "$TRACKER_DB"
trap cleanup EXIT INT TERM

echo "[run] starting tracker on ${TRACKER_HOST}:${TRACKER_PORT} ..."
TRACKER_DB="$TRACKER_DB" \
  "$PYTHON" -c "
from tracker.app import create_app, app
create_app()
app.run(host='${TRACKER_HOST}', port=${TRACKER_PORT}, debug=False, use_reloader=False)
" >"${RUN_DIR}/tracker.log" 2>&1 &
PIDS+=($!)

wait_http "${TRACKER_URL}/files" "tracker"

i=0
while [[ "$i" -lt "$PEER_COUNT" ]]; do
  port=$((BASE_PEER_PORT + i))
  data_dir="${RUN_DIR}/peer_${port}"
  mkdir -p "$data_dir"
  echo "[run] starting peer on ${PEER_IP}:${port} (data: ${data_dir}) ..."
  PEER_DATA_DIR="$data_dir" \
  PEER_PORT="$port" \
  PEER_IP="$PEER_IP" \
  PEER_HOST=0.0.0.0 \
  TRACKER_URL="$TRACKER_URL" \
    "$PYTHON" -m peer.app >"${RUN_DIR}/peer_${port}.log" 2>&1 &
  PIDS+=($!)
  wait_http "http://127.0.0.1:${port}/health" "peer :${port}"
  i=$((i + 1))
done

if [[ "$DO_SEED" -eq 1 ]]; then
  echo "[run] seeding demo files onto peer ${BASE_PEER_PORT} ..."
  seed_dir="${RUN_DIR}/seed_sources"
  mkdir -p "$seed_dir"
  "$PYTHON" - <<PY
from pathlib import Path
base = Path("${seed_dir}")
(base / "notes.txt").write_text(
    "NightOwls demo notes\\n" * 8000, encoding="utf-8"
)
(base / "sample.bin").write_bytes((b"NightOwls-demo-chunk-" * 20000)[:400_000])
print("wrote", base / "notes.txt", "and", base / "sample.bin")
PY
  "$PYTHON" -m peer.swarm upload \
    --path "${seed_dir}/notes.txt" \
    --tracker "$TRACKER_URL" \
    --data-dir "${RUN_DIR}/peer_${BASE_PEER_PORT}" \
    --peer-ip "$PEER_IP" \
    --peer-port "$BASE_PEER_PORT" \
    --filename "notes.txt"
  "$PYTHON" -m peer.swarm upload \
    --path "${seed_dir}/sample.bin" \
    --tracker "$TRACKER_URL" \
    --data-dir "${RUN_DIR}/peer_${BASE_PEER_PORT}" \
    --peer-ip "$PEER_IP" \
    --peer-port "$BASE_PEER_PORT" \
    --filename "sample.bin"
  echo "[run] demo files registered on tracker"
fi

echo
echo "=============================================="
echo " NightOwls is running"
echo "----------------------------------------------"
echo " Tracker:  ${TRACKER_URL}/files"
i=0
while [[ "$i" -lt "$PEER_COUNT" ]]; do
  port=$((BASE_PEER_PORT + i))
  echo " Peer $((i + 1)): http://127.0.0.1:${port}/"
  i=$((i + 1))
done
echo " Logs:     ${RUN_DIR}/"
echo "----------------------------------------------"
echo " Open a peer URL → Upload on one → Download on another."
if [[ "$DO_SEED" -eq 1 ]]; then
  echo " Demo files already seeded on peer 1 (notes.txt, sample.bin)."
fi
echo " Press Ctrl+C to stop all processes."
echo "=============================================="
echo

# Wait until interrupted or a child exits
while true; do
  for pid in "${PIDS[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "[run] process $pid exited — check logs in ${RUN_DIR}/" >&2
      exit 1
    fi
  done
  sleep 1
done
