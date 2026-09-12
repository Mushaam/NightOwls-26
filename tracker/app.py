"""NightOwls tracker — central registry for files, chunks, and peers."""

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, jsonify, request

from tracker import models

app = Flask(__name__)

DB_PATH = Path(os.environ.get("TRACKER_DB", models.DEFAULT_DB_PATH))


def create_app(db_path: Path | str | None = None) -> Flask:
    path = Path(db_path) if db_path else DB_PATH
    models.init_db(path)
    app.config["DB_PATH"] = path
    return app


def _conn():
    return models.get_connection(app.config["DB_PATH"])


@app.post("/register_peer")
def register_peer():
    data = request.get_json(silent=True) or {}
    ip = data.get("ip") or request.remote_addr
    port = data.get("port")
    if port is None:
        return jsonify({"error": "port is required"}), 400
    try:
        port = int(port)
    except (TypeError, ValueError):
        return jsonify({"error": "port must be an integer"}), 400

    with _conn() as conn:
        peer = models.register_peer(conn, ip, port)
    return jsonify(peer), 200


@app.post("/upload_metadata")
def upload_metadata():
    data = request.get_json(silent=True) or {}
    required = ("filename", "file_hash", "file_size", "chunk_hashes", "peer_ip", "peer_port")
    missing = [k for k in required if k not in data]
    if missing:
        return jsonify({"error": f"missing fields: {', '.join(missing)}"}), 400

    chunk_hashes = data["chunk_hashes"]
    if not isinstance(chunk_hashes, list) or not chunk_hashes:
        return jsonify({"error": "chunk_hashes must be a non-empty list"}), 400

    register_as_seeder = data.get("register_as_seeder", True)
    if not isinstance(register_as_seeder, bool):
        return jsonify({"error": "register_as_seeder must be a boolean"}), 400

    try:
        with _conn() as conn:
            meta = models.upload_metadata(
                conn,
                filename=data["filename"],
                file_hash=data["file_hash"],
                file_size=int(data["file_size"]),
                chunk_hashes=chunk_hashes,
                peer_ip=data["peer_ip"],
                peer_port=int(data["peer_port"]),
                register_as_seeder=register_as_seeder,
            )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 400

    return jsonify(meta), 201


@app.get("/files")
def list_files():
    with _conn() as conn:
        files = models.list_files(conn)
    return jsonify(files), 200


@app.get("/files/<int:file_id>")
def get_file(file_id: int):
    with _conn() as conn:
        meta = models.get_file(conn, file_id)
    if not meta:
        return jsonify({"error": "file not found"}), 404
    return jsonify(meta), 200


@app.get("/peers/<int:file_id>")
def peers_for_file(file_id: int):
    with _conn() as conn:
        if not models.get_file(conn, file_id):
            return jsonify({"error": "file not found"}), 404
        peers = models.peers_for_file(conn, file_id)
    return jsonify(peers), 200


@app.post("/peer_has_chunk")
def peer_has_chunk():
    data = request.get_json(silent=True) or {}
    required = ("peer_ip", "peer_port", "file_id", "chunk_index")
    missing = [k for k in required if k not in data]
    if missing:
        return jsonify({"error": f"missing fields: {', '.join(missing)}"}), 400

    try:
        with _conn() as conn:
            result = models.peer_has_chunk(
                conn,
                peer_ip=data["peer_ip"],
                peer_port=int(data["peer_port"]),
                file_id=int(data["file_id"]),
                chunk_index=int(data["chunk_index"]),
            )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 400

    return jsonify(result), 200


if __name__ == "__main__":
    create_app()
    host = os.environ.get("TRACKER_HOST", "0.0.0.0")
    port = int(os.environ.get("TRACKER_PORT", "5000"))
    app.run(host=host, port=port, debug=True)
