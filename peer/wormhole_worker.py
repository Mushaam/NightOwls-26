"""Background seeder: fulfill tracker wormhole jobs by sending local chunks."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

from shared.config import wormhole_enabled

if TYPE_CHECKING:
    from flask import Flask


def _http_json(url: str, method: str = "GET", payload: dict | None = None, timeout: float = 10):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode()
        return json.loads(body) if body else None


def _process_job(app: Flask, job: dict) -> None:
    from peer.wormhole_xfer import send_chunk_bytes

    store = app.config["STORE"]
    cfg = app.config.get("NIGHTOWLS_CFG") or {}
    tracker = app.config["TRACKER_URL"].rstrip("/")
    job_id = int(job["id"])
    file_id = int(job["file_id"])
    chunk_index = int(job["chunk_index"])

    try:
        claimed = _http_json(f"{tracker}/wormhole/jobs/{job_id}/claim", method="POST")
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            return
        raise
    if not claimed:
        return

    data = store.load_chunk(file_id, chunk_index)
    if data is None:
        _http_json(
            f"{tracker}/wormhole/jobs/{job_id}/status",
            method="POST",
            payload={"status": "error", "detail": "chunk not found locally"},
        )
        return

    def on_code(code: str) -> None:
        _http_json(
            f"{tracker}/wormhole/jobs/{job_id}/code",
            method="POST",
            payload={"code": code},
        )

    try:
        send_chunk_bytes(data, cfg=cfg, on_code=on_code)
        _http_json(
            f"{tracker}/wormhole/jobs/{job_id}/status",
            method="POST",
            payload={"status": "done"},
        )
        print(
            f"[wormhole] sent file={file_id} chunk={chunk_index} "
            f"to {job.get('requester_ip')}:{job.get('requester_port')}"
        )
    except Exception as exc:  # noqa: BLE001 — keep worker alive
        detail = str(exc)[:500]
        print(f"[wormhole] ERROR job={job_id}: {detail}")
        try:
            _http_json(
                f"{tracker}/wormhole/jobs/{job_id}/status",
                method="POST",
                payload={"status": "error", "detail": detail},
            )
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
            pass


def _worker_loop(app: Flask) -> None:
    cfg = app.config.get("NIGHTOWLS_CFG") or {}
    wh = cfg.get("wormhole") or {}
    poll = float(wh.get("job_poll_sec", 1.0))
    tracker = app.config["TRACKER_URL"].rstrip("/")
    ip = app.config["PEER_IP"]
    port = int(app.config["PEER_PORT"])
    print(f"[wormhole] seeder worker online for {ip}:{port}")

    while True:
        try:
            q = urllib.parse.urlencode(
                {
                    "seeder_ip": ip,
                    "seeder_port": port,
                    "status": "pending",
                    "limit": 5,
                }
            )
            jobs = _http_json(f"{tracker}/wormhole/jobs?{q}")
            if isinstance(jobs, list):
                for job in jobs:
                    _process_job(app, job)
        except Exception as exc:  # noqa: BLE001
            print(f"[wormhole] worker poll error: {exc}")
        time.sleep(poll)


def start_wormhole_seeder(app: Flask) -> None:
    cfg = app.config.get("NIGHTOWLS_CFG")
    if not wormhole_enabled(cfg):
        print("[wormhole] disabled (config)")
        return
    if app.config.get("WORMHOLE_WORKER_STARTED"):
        return
    app.config["WORMHOLE_WORKER_STARTED"] = True
    thread = threading.Thread(
        target=_worker_loop,
        args=(app,),
        name="nightowls-wormhole-seeder",
        daemon=True,
    )
    thread.start()
