"""NightOwls peer node — chunk server (client logic arrives in later steps)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from flask import Flask, Response, jsonify

from peer.store import ChunkStore

app = Flask(__name__)

DEFAULT_DATA = Path(__file__).resolve().parent / "data"


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def create_app(
    data_dir: str | Path | None = None,
    tracker_url: str | None = None,
    peer_ip: str | None = None,
    peer_port: int | None = None,
    register: bool = True,
) -> Flask:
    data = Path(data_dir or _env("PEER_DATA_DIR", str(DEFAULT_DATA)))
    tracker = (tracker_url or _env("TRACKER_URL", "http://127.0.0.1:5000")).rstrip("/")
    ip = peer_ip or _env("PEER_IP", "127.0.0.1")
    port = int(peer_port if peer_port is not None else _env("PEER_PORT", "6001"))

    store = ChunkStore(data)
    app.config.update(
        DATA_DIR=data,
        TRACKER_URL=tracker,
        PEER_IP=ip,
        PEER_PORT=port,
        STORE=store,
    )

    if register:
        _register_with_tracker(tracker, ip, port)

    return app


def _register_with_tracker(tracker_url: str, ip: str, port: int) -> None:
    payload = json.dumps({"ip": ip, "port": port}).encode()
    req = urllib.request.Request(
        f"{tracker_url}/register_peer",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode()
            print(f"[peer] registered with tracker: {body}")
    except urllib.error.URLError as exc:
        # Allow peer to start even if tracker is briefly down (retry later in Step 4+)
        print(f"[peer] WARNING: could not register with tracker ({exc})")


@app.get("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "peer_ip": app.config["PEER_IP"],
            "peer_port": app.config["PEER_PORT"],
            "tracker_url": app.config["TRACKER_URL"],
            "data_dir": str(app.config["DATA_DIR"]),
        }
    )


@app.get("/chunk/<int:file_id>/<int:chunk_index>")
def get_chunk(file_id: int, chunk_index: int):
    store: ChunkStore = app.config["STORE"]
    data = store.load_chunk(file_id, chunk_index)
    if data is None:
        return jsonify({"error": "chunk not found"}), 404
    return Response(
        data,
        status=200,
        mimetype="application/octet-stream",
        headers={
            "Content-Length": str(len(data)),
            "X-File-Id": str(file_id),
            "X-Chunk-Index": str(chunk_index),
        },
    )


if __name__ == "__main__":
    create_app()
    host = _env("PEER_HOST", "0.0.0.0")
    port = int(app.config["PEER_PORT"])
    app.run(host=host, port=port, debug=False, threaded=True)
