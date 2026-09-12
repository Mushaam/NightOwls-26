#!/usr/bin/env bash
# Shared helpers for NightOwls launchers.

_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

nightowls_root() {
  ROOT="$(cd "${_LIB_DIR}/.." && pwd)"
  cd "$ROOT" || exit 1
  if [[ -x "${ROOT}/.venv/bin/python" ]]; then
    PYTHON="${ROOT}/.venv/bin/python"
    PIP="${ROOT}/.venv/bin/pip"
  elif [[ -x "${ROOT}/.venv/Scripts/python.exe" ]]; then
    PYTHON="${ROOT}/.venv/Scripts/python.exe"
    PIP="${ROOT}/.venv/Scripts/pip.exe"
  else
    PYTHON="${ROOT}/.venv/bin/python"
    PIP="${ROOT}/.venv/bin/pip"
  fi
}

ensure_venv() {
  local label="${1:-[setup]}"
  local need_create=0

  if [[ ! -x "$PYTHON" ]]; then
    need_create=1
  elif ! "$PYTHON" -c "import sys" 2>/dev/null; then
    echo "${label} existing .venv is broken — recreating ..."
    need_create=1
  fi

  if [[ "$need_create" -eq 1 ]]; then
    echo "${label} creating virtualenv at .venv ..."
    rm -rf "${ROOT}/.venv"
    python3 -m venv "${ROOT}/.venv"
    PYTHON="${ROOT}/.venv/bin/python"
    PIP="${ROOT}/.venv/bin/pip"
  fi

  if ! "$PYTHON" -c "import flask" 2>/dev/null; then
    echo "${label} installing requirements ..."
    if ! "$PYTHON" -m pip install -r "${ROOT}/requirements.txt"; then
      echo "${label} pip failed — recreating .venv and retrying ..."
      rm -rf "${ROOT}/.venv"
      python3 -m venv "${ROOT}/.venv"
      PYTHON="${ROOT}/.venv/bin/python"
      PIP="${ROOT}/.venv/bin/pip"
      "$PYTHON" -m pip install -r "${ROOT}/requirements.txt"
    fi
  fi
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

detect_lan_ip() {
  local ip=""
  if command -v ip >/dev/null 2>&1; then
    ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}')"
  fi
  if [[ -z "$ip" ]] && command -v hostname >/dev/null 2>&1; then
    ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  fi
  if [[ -n "$ip" && "$ip" != "127.0.0.1" ]]; then
    echo "$ip"
    return 0
  fi
  return 1
}

detect_advertise_ip() {
  local ip
  if ip="$(detect_tailscale_ip)"; then
    echo "$ip"
    return 0
  fi
  if ip="$(detect_lan_ip)"; then
    echo "$ip"
    return 0
  fi
  echo "127.0.0.1"
}
