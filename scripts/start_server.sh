#!/usr/bin/env bash
# NightOwls — plug-and-play tracker (server).
#
# Usage:
#   ./server
#   ./scripts/start_server.sh
#   ./scripts/start_server.sh --port 5000 --host 0.0.0.0

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"
nightowls_root

TRACKER_HOST="${TRACKER_HOST:-0.0.0.0}"
TRACKER_PORT="${TRACKER_PORT:-5000}"
TRACKER_DB="${TRACKER_DB:-${ROOT}/data/tracker.db}"

usage() {
  cat <<EOF
NightOwls tracker (server)

Usage: $(basename "$0") [options]

Options:
  --host ADDR     Bind address (default: 0.0.0.0 — reachable on LAN)
  --port N        Port (default: 5000)
  --db PATH       SQLite database path (default: ./data/tracker.db)
  -h, --help      Show this help

Environment overrides:
  TRACKER_HOST  TRACKER_PORT  TRACKER_DB

Examples:
  ./server
  ./server --port 5000
  TRACKER_DB=/tmp/tracker.db ./server

Then on other machines:
  ./client http://<this-machine-ip>:${TRACKER_PORT}
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --host)
      TRACKER_HOST="${2:-}"
      [[ -n "$TRACKER_HOST" ]] || { echo "error: --host needs a value" >&2; exit 1; }
      shift 2
      ;;
    --port)
      TRACKER_PORT="${2:-}"
      [[ -n "$TRACKER_PORT" ]] || { echo "error: --port needs a value" >&2; exit 1; }
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

ensure_venv "[server]"
mkdir -p "$(dirname "$TRACKER_DB")"

ADVERTISE_IP="$(detect_advertise_ip)"
PUBLIC_URL="http://${ADVERTISE_IP}:${TRACKER_PORT}"

echo
echo "=============================================="
echo " NightOwls tracker (server)"
echo "----------------------------------------------"
echo " Listening:  ${TRACKER_HOST}:${TRACKER_PORT}"
echo " Database:   ${TRACKER_DB}"
echo " Local:      http://127.0.0.1:${TRACKER_PORT}/files"
echo " Share this: ${PUBLIC_URL}"
echo "----------------------------------------------"
echo " On other machines / terminals:"
echo "   ./client ${ADVERTISE_IP}"
echo "   ./client ${ADVERTISE_IP}:${TRACKER_PORT}"
echo "----------------------------------------------"
echo " Press Ctrl+C to stop."
echo "=============================================="
echo

export TRACKER_DB TRACKER_HOST TRACKER_PORT
exec "$PYTHON" -c "
from tracker.app import create_app, app
create_app()
app.run(host='${TRACKER_HOST}', port=${TRACKER_PORT}, debug=False, use_reloader=False)
"
