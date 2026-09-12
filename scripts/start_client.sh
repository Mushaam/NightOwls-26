#!/usr/bin/env bash
# NightOwls — start one peer client on a Tailscale / LAN network.
#
# Usage:
#   ./scripts/start_client.sh http://100.x.y.z:5000
#   ./scripts/start_client.sh http://100.x.y.z:5000 --port 6001
#   TRACKER_URL=http://100.x.y.z:5000 ./scripts/start_client.sh
#
# Prerequisites:
#   - Tailscale connected (or set PEER_IP to your reachable LAN IP)
#   - Tracker already running and reachable at TRACKER_URL

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${ROOT}/.venv/bin/python"
PIP="${ROOT}/.venv/bin/pip"

TRACKER_URL="${TRACKER_URL:-}"
PEER_PORT="${PEER_PORT:-6001}"
PEER_IP="${PEER_IP:-}"
PEER_HOST="${PEER_HOST:-0.0.0.0}"
PEER_DATA_DIR="${PEER_DATA_DIR:-${HOME}/NightOwls-data}"

usage() {
  cat <<EOF
NightOwls Tailscale / LAN peer client

Usage: $(basename "$0") [TRACKER_URL] [options]

Arguments:
  TRACKER_URL           Tracker base URL, e.g. http://100.64.1.2:5000
                        (or set env TRACKER_URL)

Options:
  --port N              Peer listen port (default: 6001)
  --ip IP               Advertise this IP to the tracker (default: Tailscale IPv4)
  --data-dir DIR        Local storage for chunks + completed files
                        (default: ~/NightOwls-data)
  -h, --help            Show this help

Environment overrides:
  TRACKER_URL  PEER_PORT  PEER_IP  PEER_HOST  PEER_DATA_DIR

Examples:
  ./scripts/start_client.sh http://100.64.1.2:5000
  ./scripts/start_client.sh http://100.64.1.2:5000 --port 6002
  PEER_IP=100.64.1.9 ./scripts/start_client.sh http://100.64.1.2:5000

Completed downloads appear under:
  <data-dir>/complete/<file_id>/<filename>
EOF
}

detect_tailscale_ip() {
  if command -v tailscale >/dev/null 2>&1; then
    local ip
    ip="$(tailscale ip -4 2>/dev/null | head -n1 | tr -d '[:space:]' || true)"
    if [[ -n "$ip" ]]; then
      echo "$ip"
      return 0
    fi
  fi
  return 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
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

if [[ -z "$TRACKER_URL" ]]; then
  echo "error: TRACKER_URL is required (pass it as the first argument)." >&2
  echo >&2
  usage >&2
  exit 1
fi

TRACKER_URL="${TRACKER_URL%/}"

if [[ -z "$PEER_IP" ]]; then
  if PEER_IP="$(detect_tailscale_ip)"; then
    echo "[client] using Tailscale IP: ${PEER_IP}"
  else
    echo "error: could not detect Tailscale IP." >&2
    echo "  Install/connect Tailscale, or pass --ip <your-tailscale-ip>" >&2
    exit 1
  fi
fi

if [[ ! -x "$PYTHON" ]]; then
  echo "[client] creating virtualenv at .venv ..."
  python3 -m venv "${ROOT}/.venv"
fi
if ! "$PYTHON" -c "import flask" 2>/dev/null; then
  echo "[client] installing requirements ..."
  "$PIP" install -r "${ROOT}/requirements.txt"
fi

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
