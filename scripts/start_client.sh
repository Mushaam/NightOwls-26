#!/usr/bin/env bash
# NightOwls — plug-and-play peer client.
#
# Usage:
#   ./client                          # tracker_url from config/nightowls.json
#   ./client 192.168.1.10             # optional override
#   ./client https://….ngrok-free.app
#   ./scripts/start_client.sh --port 6001

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"
nightowls_root

# Capture whether the user already set these via the environment (env wins over file).
TRACKER_URL="${TRACKER_URL:-}"
TRACKER_FROM_ENV=0
[[ -n "$TRACKER_URL" ]] && TRACKER_FROM_ENV=1

PEER_PORT="${PEER_PORT:-}"
PEER_PORT_FROM_ENV=0
[[ -n "$PEER_PORT" ]] && PEER_PORT_FROM_ENV=1

PEER_IP="${PEER_IP:-}"
PEER_IP_FROM_ENV=0
[[ -n "$PEER_IP" ]] && PEER_IP_FROM_ENV=1

PEER_HOST="${PEER_HOST:-}"
PEER_HOST_FROM_ENV=0
[[ -n "$PEER_HOST" ]] && PEER_HOST_FROM_ENV=1

PEER_DATA_DIR="${PEER_DATA_DIR:-${HOME}/NightOwls-data}"
DEFAULT_TRACKER_PORT=5000
TRACKER_FROM_CLI=0
CONFIG_PATH=""

usage() {
  cat <<EOF
NightOwls peer client

Usage: $(basename "$0") [TRACKER_IP_OR_URL] [options]

Tracker address (first match wins):
  1. CLI argument          ./client https://….ngrok-free.app
  2. \$TRACKER_URL env
  3. config/nightowls.json → tracker_url   (default)

Accepted CLI forms:
  192.168.1.10              → http://192.168.1.10:5000
  192.168.1.10:5000         → http://192.168.1.10:5000
  http://192.168.1.10:5000  → as written
  https://….ngrok-free.app  → as written

Options:
  --port N              Peer listen port (default: from config, else 6001)
  --ip IP               Advertise this IP to the tracker
                        (default: config advertise_host, else Tailscale/LAN)
  --data-dir DIR        Local storage (default: ~/NightOwls-data)
  -h, --help            Show this help

Environment overrides (beat the config file):
  TRACKER_URL  PEER_PORT  PEER_IP  PEER_HOST  PEER_DATA_DIR  NIGHTOWLS_CONFIG

Examples:
  ./client
  ./client https://abc123.ngrok-free.app
  ./client 192.168.1.10 --port 6002

Completed downloads:
  <data-dir>/complete/<file_id>/<filename>
EOF
}

# Turn IP / IP:port / URL into a full tracker base URL.
normalize_tracker() {
  local raw="${1%/}"
  if [[ "$raw" =~ ^https?:// ]]; then
    echo "$raw"
    return 0
  fi
  if [[ "$raw" =~ ^\[.+\]:[0-9]+$ ]]; then
    echo "http://${raw}"
    return 0
  fi
  if [[ "$raw" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "http://${raw}:${DEFAULT_TRACKER_PORT}"
    return 0
  fi
  if [[ "$raw" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+:[0-9]+$ ]]; then
    echo "http://${raw}"
    return 0
  fi
  if [[ "$raw" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "http://${raw}:${DEFAULT_TRACKER_PORT}"
    return 0
  fi
  if [[ "$raw" =~ ^[A-Za-z0-9._-]+:[0-9]+$ ]]; then
    echo "http://${raw}"
    return 0
  fi
  echo "error: not a valid tracker IP/URL: $1" >&2
  echo "  try:  ./client" >&2
  echo "    or: ./client 192.168.1.10" >&2
  echo "    or: ./client https://….ngrok-free.app" >&2
  return 1
}

# Read tracker + peer defaults from shared.config (no Flask needed).
load_config_values() {
  # Prefer venv python if present; else system python3.
  local py="${PYTHON}"
  if [[ ! -x "$py" ]]; then
    py="$(command -v python3 || true)"
  fi
  if [[ -z "$py" ]]; then
    echo "error: python3 not found" >&2
    return 1
  fi
  "$py" - <<'PY'
from shared.config import load_config, config_path

cfg = load_config()
peer = cfg.get("peer") or {}
path = config_path()
# One value per line for easy bash read
print(cfg.get("tracker_url") or "")
print(peer.get("port") or "")
print(peer.get("advertise_host") or "")
print(peer.get("advertise_port") or "")
print(peer.get("host") or "")
print(str(path) if path else "")
PY
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --port)
      PEER_PORT="${2:-}"
      [[ -n "$PEER_PORT" ]] || { echo "error: --port needs a value" >&2; exit 1; }
      PEER_PORT_FROM_ENV=1  # treat CLI as explicit
      shift 2
      ;;
    --ip)
      PEER_IP="${2:-}"
      [[ -n "$PEER_IP" ]] || { echo "error: --ip needs a value" >&2; exit 1; }
      PEER_IP_FROM_ENV=1
      shift 2
      ;;
    --data-dir)
      PEER_DATA_DIR="${2:-}"
      [[ -n "$PEER_DATA_DIR" ]] || { echo "error: --data-dir needs a value" >&2; exit 1; }
      shift 2
      ;;
    -*)
      echo "error: unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
    *)
      if [[ "$TRACKER_FROM_CLI" -eq 1 ]]; then
        echo "error: unexpected extra argument: $1" >&2
        exit 1
      fi
      # CLI overrides env + config
      TRACKER_URL="$(normalize_tracker "$1")" || exit 1
      TRACKER_FROM_CLI=1
      shift
      ;;
  esac
done

# Fill gaps from config/nightowls.json
CFG_TRACKER=""
CFG_PEER_PORT=""
CFG_ADVERTISE_HOST=""
CFG_ADVERTISE_PORT=""
CFG_PEER_HOST=""
if CFG_LINES="$(load_config_values)"; then
  CFG_TRACKER="$(printf '%s\n' "$CFG_LINES" | sed -n '1p')"
  CFG_PEER_PORT="$(printf '%s\n' "$CFG_LINES" | sed -n '2p')"
  CFG_ADVERTISE_HOST="$(printf '%s\n' "$CFG_LINES" | sed -n '3p')"
  CFG_ADVERTISE_PORT="$(printf '%s\n' "$CFG_LINES" | sed -n '4p')"
  CFG_PEER_HOST="$(printf '%s\n' "$CFG_LINES" | sed -n '5p')"
  CONFIG_PATH="$(printf '%s\n' "$CFG_LINES" | sed -n '6p')"
fi

if [[ "$TRACKER_FROM_CLI" -eq 0 && "$TRACKER_FROM_ENV" -eq 0 ]]; then
  if [[ -n "$CFG_TRACKER" ]]; then
    TRACKER_URL="${CFG_TRACKER%/}"
  fi
fi

if [[ -z "$TRACKER_URL" ]]; then
  echo "error: no tracker URL — set config/nightowls.json → tracker_url" >&2
  echo "  or pass: ./client https://YOUR-NGROK.ngrok-free.app" >&2
  exit 1
fi

TRACKER_URL="${TRACKER_URL%/}"

if [[ "$PEER_PORT_FROM_ENV" -eq 0 ]]; then
  if [[ -n "$CFG_ADVERTISE_PORT" ]]; then
    PEER_PORT="$CFG_ADVERTISE_PORT"
  elif [[ -n "$CFG_PEER_PORT" ]]; then
    PEER_PORT="$CFG_PEER_PORT"
  else
    PEER_PORT=6001
  fi
fi

if [[ "$PEER_HOST_FROM_ENV" -eq 0 ]]; then
  PEER_HOST="${CFG_PEER_HOST:-0.0.0.0}"
fi

if [[ "$PEER_IP_FROM_ENV" -eq 0 ]]; then
  if [[ -n "$CFG_ADVERTISE_HOST" && "$CFG_ADVERTISE_HOST" != "127.0.0.1" ]]; then
    PEER_IP="$CFG_ADVERTISE_HOST"
    echo "[client] advertising IP from config: ${PEER_IP}"
  else
    PEER_IP="$(detect_advertise_ip)"
    if [[ "$PEER_IP" == "127.0.0.1" ]]; then
      echo "[client] advertising 127.0.0.1 (localhost only)"
    else
      echo "[client] advertising IP: ${PEER_IP}"
    fi
  fi
fi

ensure_venv "[client]"
# Cross-network demos need wormhole.
if ! "$PYTHON" -c "import wormhole, crochet" 2>/dev/null; then
  echo "[client] installing magic-wormhole stack ..."
  "$PYTHON" -m pip install -r "${ROOT}/requirements.txt"
fi

mkdir -p "$PEER_DATA_DIR"
COMPLETE_DIR="${PEER_DATA_DIR}/complete"

TRACKER_SOURCE="config"
[[ -n "$CONFIG_PATH" ]] || TRACKER_SOURCE="defaults"
[[ "$TRACKER_FROM_ENV" -eq 1 ]] && TRACKER_SOURCE="env TRACKER_URL"
[[ "$TRACKER_FROM_CLI" -eq 1 ]] && TRACKER_SOURCE="CLI"

echo
echo "=============================================="
echo " NightOwls peer client"
echo "----------------------------------------------"
echo " Tracker:     ${TRACKER_URL}"
echo " Source:      ${TRACKER_SOURCE}"
if [[ -n "$CONFIG_PATH" ]]; then
  echo " Config:      ${CONFIG_PATH}"
fi
echo " Peer IP:     ${PEER_IP}  (advertised to tracker)"
echo " Listen:      ${PEER_HOST}:${PEER_PORT}"
echo " Data dir:    ${PEER_DATA_DIR}"
echo " Downloads:   ${COMPLETE_DIR}/<file_id>/<filename>"
echo " UI:          http://127.0.0.1:${PEER_PORT}/  (local)"
echo "----------------------------------------------"
echo " Press Ctrl+C to stop."
echo "=============================================="
echo

export TRACKER_URL PEER_IP PEER_PORT PEER_HOST PEER_DATA_DIR
exec "$PYTHON" -m peer.app
