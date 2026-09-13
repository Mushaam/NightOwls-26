"""Load NightOwls client/server addresses from config/nightowls.json.

Env vars always win over the file (for demos and scripts/run.sh).
Search order for the file:
  1. $NIGHTOWLS_CONFIG
  2. ./config/nightowls.json (repo default)
  3. ./nightowls.json
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_PATHS = (
    Path(os.environ["NIGHTOWLS_CONFIG"]) if os.environ.get("NIGHTOWLS_CONFIG") else None,
    _ROOT / "config" / "nightowls.json",
    _ROOT / "nightowls.json",
)

_DEFAULTS: dict[str, Any] = {
    "tracker_url": "http://127.0.0.1:5000",
    "peer": {
        "host": "0.0.0.0",
        "port": 6001,
        "advertise_host": "127.0.0.1",
        "advertise_port": 6001,
    },
    "wormhole": {
        "enabled": True,
        "appid": "nightowls.file-share",
        "mailbox_url": "ws://relay.magic-wormhole.io:4000/v1",
        "transit_helper": "tcp:transit.magic-wormhole.io:4001",
        "direct_timeout_sec": 4,
        "job_poll_sec": 1.0,
        "job_timeout_sec": 90,
    },
}


def _deep_merge(base: dict, overlay: dict) -> dict:
    out = deepcopy(base)
    for key, val in overlay.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def config_path() -> Path | None:
    for path in _DEFAULT_PATHS:
        if path is not None and path.is_file():
            return path
    return None


def load_config() -> dict[str, Any]:
    cfg = deepcopy(_DEFAULTS)
    path = config_path()
    if path is not None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cfg = _deep_merge(cfg, raw)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[config] WARNING: could not read {path}: {exc}")

    # Environment overrides (scripts / one-off demos)
    if os.environ.get("TRACKER_URL"):
        cfg["tracker_url"] = os.environ["TRACKER_URL"].rstrip("/")
    else:
        cfg["tracker_url"] = str(cfg.get("tracker_url") or _DEFAULTS["tracker_url"]).rstrip("/")

    peer = cfg.setdefault("peer", {})
    if os.environ.get("PEER_HOST"):
        peer["host"] = os.environ["PEER_HOST"]
    if os.environ.get("PEER_PORT"):
        peer["port"] = int(os.environ["PEER_PORT"])
    if os.environ.get("PEER_IP"):
        peer["advertise_host"] = os.environ["PEER_IP"]
    if os.environ.get("PEER_ADVERTISE_PORT"):
        peer["advertise_port"] = int(os.environ["PEER_ADVERTISE_PORT"])
    peer.setdefault("advertise_port", peer.get("port", 6001))

    wh = cfg.setdefault("wormhole", {})
    if os.environ.get("WORMHOLE_ENABLED") is not None:
        wh["enabled"] = os.environ["WORMHOLE_ENABLED"].strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    if os.environ.get("WORMHOLE_MAILBOX_URL"):
        wh["mailbox_url"] = os.environ["WORMHOLE_MAILBOX_URL"]
    if os.environ.get("WORMHOLE_TRANSIT_HELPER"):
        wh["transit_helper"] = os.environ["WORMHOLE_TRANSIT_HELPER"]
    if os.environ.get("WORMHOLE_APPID"):
        wh["appid"] = os.environ["WORMHOLE_APPID"]

    return cfg


def wormhole_enabled(cfg: dict[str, Any] | None = None) -> bool:
    cfg = cfg or load_config()
    return bool((cfg.get("wormhole") or {}).get("enabled", True))
