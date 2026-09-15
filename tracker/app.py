"""NightOwls tracker — central registry for files, chunks, and peers."""

from __future__ import annotations

import csv
import io
import os
from pathlib import Path

from flask import Flask, Response, flash, jsonify, redirect, render_template, request, url_for

from tracker import models

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("TRACKER_SECRET", "nightowls-tracker-dev")

DB_PATH = Path(os.environ.get("TRACKER_DB", models.DEFAULT_DB_PATH))


def create_app(db_path: Path | str | None = None) -> Flask:
    path = Path(db_path) if db_path else DB_PATH
    models.init_db(path)
    app.config["DB_PATH"] = path
    return app


def _conn():
    return models.get_connection(app.config["DB_PATH"])


def _csv_response(filename: str, headers: list[str], rows: list[list]) -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    writer.writerows(rows)
    return Response(
        buf.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Public JSON API
# ---------------------------------------------------------------------------


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


@app.post("/files/<int:file_id>/unshare")
@app.delete("/files/<int:file_id>")
def unshare_file(file_id: int):
    """
    Remove a file from the central catalog (stop sharing).

    Does not delete bytes on any peer — only tracker rows (file, chunks, claims).
    """
    data = request.get_json(silent=True) or {}
    actor = data.get("actor") or request.args.get("actor") or "api"
    try:
        with _conn() as conn:
            info = models.delete_file(conn, file_id, actor=str(actor))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify(
        {
            "status": "unshared",
            "file_id": file_id,
            "filename": info.get("filename"),
            "file_hash": info.get("file_hash"),
            "message": "Removed from tracker catalog; peer local copies are unchanged.",
        }
    ), 200


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


# ---------------------------------------------------------------------------
# Server portal (bare-minimum admin UI)
# ---------------------------------------------------------------------------


@app.get("/")
def root():
    return redirect(url_for("portal_home"))


@app.get("/portal")
def portal_home():
    with _conn() as conn:
        stats = models.portal_stats(conn)
        recent = models.list_audit(conn, limit=10)
    return render_template("portal_home.html", stats=stats, recent=recent)


@app.get("/portal/inventory")
def portal_inventory():
    with _conn() as conn:
        files = models.list_files(conn)
        peers = models.list_peers(conn)
    return render_template("portal_inventory.html", files=files, peers=peers)


@app.post("/portal/inventory/<int:file_id>/rename")
def portal_rename(file_id: int):
    name = (request.form.get("filename") or "").strip()
    try:
        with _conn() as conn:
            models.rename_file(conn, file_id, name)
        flash(f"Renamed file #{file_id}.", "ok")
    except ValueError as exc:
        flash(str(exc), "err")
    return redirect(url_for("portal_inventory"))


@app.post("/portal/inventory/<int:file_id>/delete")
def portal_delete(file_id: int):
    try:
        with _conn() as conn:
            info = models.delete_file(conn, file_id, actor="portal")
        flash(
            f"Unshared “{info.get('filename')}” from the tracker "
            "(peer copies were not deleted).",
            "ok",
        )
    except ValueError as exc:
        flash(str(exc), "err")
    return redirect(url_for("portal_inventory"))


@app.get("/portal/audit")
def portal_audit():
    limit = request.args.get("limit", 200, type=int)
    with _conn() as conn:
        events = models.list_audit(conn, limit=limit)
    return render_template("portal_audit.html", events=events, limit=limit)


@app.get("/portal/export/inventory.csv")
def export_inventory_csv():
    with _conn() as conn:
        files = models.list_files(conn)
    rows = [
        [
            f["id"],
            f["filename"],
            f["file_hash"],
            f["file_size"],
            f["chunk_count"],
            f.get("seeder_count", 0),
            f.get("created_at", ""),
        ]
        for f in files
    ]
    return _csv_response(
        "inventory.csv",
        ["id", "filename", "file_hash", "file_size", "chunk_count", "seeder_count", "created_at"],
        rows,
    )


@app.get("/portal/export/audit.csv")
def export_audit_csv():
    with _conn() as conn:
        events = models.list_audit(conn, limit=5000)
    # Newest first in UI; export oldest→newest for logs.
    events = list(reversed(events))
    rows = [
        [e["id"], e["created_at"], e["action"], e.get("actor") or "", e.get("detail") or ""]
        for e in events
    ]
    return _csv_response(
        "audit.csv",
        ["id", "created_at", "action", "actor", "detail"],
        rows,
    )


@app.get("/portal/export/peers.csv")
def export_peers_csv():
    with _conn() as conn:
        peers = models.list_peers(conn)
    rows = [
        [p["id"], p["ip"], p["port"], p.get("registered_at", ""), p.get("chunk_claims", 0)]
        for p in peers
    ]
    return _csv_response(
        "peers.csv",
        ["id", "ip", "port", "registered_at", "chunk_claims"],
        rows,
    )


# ---------------------------------------------------------------------------
# Magic Wormhole coordination (cross-network chunk transfer)
# ---------------------------------------------------------------------------


@app.post("/wormhole/jobs")
def wormhole_create_job():
    data = request.get_json(silent=True) or {}
    required = (
        "seeder_ip",
        "seeder_port",
        "requester_ip",
        "requester_port",
        "file_id",
        "chunk_index",
    )
    missing = [k for k in required if k not in data]
    if missing:
        return jsonify({"error": f"missing fields: {', '.join(missing)}"}), 400
    try:
        with _conn() as conn:
            job = models.create_wormhole_job(
                conn,
                seeder_ip=str(data["seeder_ip"]),
                seeder_port=int(data["seeder_port"]),
                requester_ip=str(data["requester_ip"]),
                requester_port=int(data["requester_port"]),
                file_id=int(data["file_id"]),
                chunk_index=int(data["chunk_index"]),
            )
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(job), 201


@app.get("/wormhole/jobs")
def wormhole_list_jobs():
    seeder_ip = request.args.get("seeder_ip")
    seeder_port = request.args.get("seeder_port", type=int)
    if not seeder_ip or seeder_port is None:
        return jsonify({"error": "seeder_ip and seeder_port are required"}), 400
    status = request.args.get("status", "pending")
    if status in ("", "any", "*"):
        status = None
    limit = request.args.get("limit", 20, type=int)
    with _conn() as conn:
        jobs = models.list_wormhole_jobs(
            conn,
            seeder_ip=seeder_ip,
            seeder_port=seeder_port,
            status=status,
            limit=limit,
        )
    return jsonify(jobs)


@app.get("/wormhole/jobs/<int:job_id>")
def wormhole_get_job(job_id: int):
    with _conn() as conn:
        job = models.get_wormhole_job(conn, job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404
    return jsonify(job)


@app.post("/wormhole/jobs/<int:job_id>/claim")
def wormhole_claim_job(job_id: int):
    with _conn() as conn:
        job = models.claim_wormhole_job(conn, job_id)
    if not job:
        return jsonify({"error": "job not claimable"}), 409
    return jsonify(job)


@app.post("/wormhole/jobs/<int:job_id>/code")
def wormhole_set_code(job_id: int):
    data = request.get_json(silent=True) or {}
    code = data.get("code")
    if not code or not isinstance(code, str):
        return jsonify({"error": "code is required"}), 400
    with _conn() as conn:
        job = models.set_wormhole_code(conn, job_id, code.strip())
    if not job:
        return jsonify({"error": "job not found"}), 404
    return jsonify(job)


@app.post("/wormhole/jobs/<int:job_id>/status")
def wormhole_set_status(job_id: int):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if not status or not isinstance(status, str):
        return jsonify({"error": "status is required"}), 400
    detail = data.get("detail")
    with _conn() as conn:
        if not models.get_wormhole_job(conn, job_id):
            return jsonify({"error": "job not found"}), 404
        job = models.update_wormhole_job(
            conn, job_id, status=status, detail=detail if detail is None else str(detail)
        )
    return jsonify(job)


if __name__ == "__main__":
    create_app()
    host = os.environ.get("TRACKER_HOST", "0.0.0.0")
    port = int(os.environ.get("TRACKER_PORT", "5000"))
    app.run(host=host, port=port, debug=False, use_reloader=False)
