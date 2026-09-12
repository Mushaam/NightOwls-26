#!/usr/bin/env bash
# NightOwls — plug-and-play peer client.
#
# Usage:
#   ./client
#   ./client http://192.168.1.10:5000
#   ./scripts/start_client.sh http://100.x.y.z:5000 --port 6001

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"
nightowls_root

TRACKER_URL="${TRACKER_URL:-}"
PEER_PORT="${PEER_PORT:-6001}"
PEER_IP="${PEER_IP:-}"
PEER_HOST="${PEER_HOST:-0.0.0.0}"
PEER_DATA_DIR="${PEER_DATA_DIR:-${HOME}/NightOwls-data}"

usage() {
  cat <<EOF
NightOwls peer client

Usage: $(basename "$0") [TRACKER_URL] [options]

Arguments:
  TRACKER_URL           Tracker URL (default: http://127.0.0.1:5000)
                        Example: http://192.168.1.10:5000

Options:
  --port N              Peer listen port (default: 6001)
  --ip IP               Advertise this IP to the tracker
                        (default: Tailscale → LAN → 127.0.0.1)
  --data-dir DIR        Local storage (default: ~/NightOwls-data)
  -h, --help            Show this help

Environment overrides:
  TRACKER_URL  PEER_PORT  PEER_IP  PEER_HOST  PEER_DATA_DIR

Examples:
  ./client
  ./client http://192.168.1.10:5000
  ./client http://100.64.1.2:5000 --port 6002

Completed downloads:
  <data-dir>/complete/<file_id>/<filename>
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --port)
      PEER_PORT="${2:-}"
      [[ -n "$PEER_PORT" ]] || { echo "error: --port needs a value" >&2; exit 1; }
      shift 2
      ;;
    --ip)
      PEER_IP="${2:-}"
      [[ -n "$PEER_IP" ]] || { echo "error: --ip needs a value" >&2; exit 1; }
      shift 2
      ;;
    --data-dir)
      PEER_DATA_DIR="${2:-}"
      [[ -n "$PEER_DATA_DIR" ]] || { echo "error: --data-dir needs a value" >&2; exit 1; }
      shift 2
      ;;
    http://*|https://*)
      TRACKER_URL="$1"
      shift
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

TRACKER_URL="${TRACKER_URL:-http://127.0.0.1:5000}"
TRACKER_URL="${TRACKER_URL%/}"

if [[ -z "$PEER_IP" ]]; then
  PEER_IP="$(detect_advertise_ip)"
  if [[ "$PEER_IP" == "127.0.0.1" ]]; then
    echo "[client] advertising 127.0.0.1 (localhost only)"
  else
    echo "[client] advertising IP: ${PEER_IP}"
  fi
fi

ensure_venv "[client]"
mkdir -p "$PEER_DATA_DIR"
COMPLETE_DIR="${PEER_DATA_DIR}/complete"

echo
echo "=============================================="
echo " NightOwls peer client"
echo "----------------------------------------------"
echo " Tracker:     ${TRACKER_URL}"
echo " Peer IP:     ${PEER_IP}  (advertised to tracker)"
echo " Listen:      ${PEER_HOST}:${PEER_PORT}"
echo " Data dir:    ${PEER_DATA_DIR}"
echo " Downloads:   ${COMPLETE_DIR}/<file_id>/<filename>"
echo " UI:          http://${PEER_IP}:${PEER_PORT}/"
echo "              http://127.0.0.1:${PEER_PORT}/  (local)"
echo "----------------------------------------------"
echo " Press Ctrl+C to stop."
echo "=============================================="
echo

export TRACKER_URL PEER_IP PEER_PORT PEER_HOST PEER_DATA_DIR
exec "$PYTHON" -m peer.app
