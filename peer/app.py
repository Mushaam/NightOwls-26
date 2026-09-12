"""NightOwls peer node — chunk server + swarm client + UI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

from flask import Flask, Response, jsonify, redirect, render_template, request, send_file
from werkzeug.utils import secure_filename

from peer.inventory import LocalInventory
from peer.store import ChunkStore
from peer.swarm import DownloadError, UploadError, download_file, upload_file
from shared.utils import CHUNK_SIZE, verify_chunk

app = Flask(__name__)

DEFAULT_DATA = Path(__file__).resolve().parent / "data"


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _format_size(num: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(num)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{num} B"


def _open_with_os(path: Path) -> None:
    """Open a local file with the OS default handler (like double-click)."""
    path = path.resolve()
    if sys.platform.startswith("darwin"):
        subprocess.Popen(["open", str(path)], start_new_session=True)
    elif sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)], start_new_session=True)


def _register_library(result: dict, *, source: str) -> None:
    inventory: LocalInventory | None = app.config.get("INVENTORY")
    if not inventory or not result:
        return
    path = result.get("path")
    file_id = result.get("file_id") or result.get("id")
    if path is None or file_id is None:
        return
    inventory.register(
        file_id=int(file_id),
        filename=str(result.get("filename") or Path(path).name),
        file_hash=str(result.get("file_hash") or ""),
        file_size=int(result.get("file_size") or 0),
        path=path,
        source=source,
    )


def _owned_library_entry(
    file_id: int, *, file_hash: str | None = None
) -> dict | None:
    """
    Return a healthy library row if this peer already has the file.
    Matches by file_id, or by SHA-256 when the tracker hash is known.
    """
    inventory: LocalInventory | None = app.config.get("INVENTORY")
    store: ChunkStore | None = app.config.get("STORE")
    if not inventory:
        return None

    def _ok(entry: dict | None) -> dict | None:
        if not entry or entry.get("status") != "ok":
            return None
        if inventory.resolve_path(int(entry["file_id"])) is None:
            return None
        return entry

    hit = _ok(inventory.get(file_id))
    if hit:
        return hit

    # Disk has a verified complete/ but library row missing — register then own.
    if store and store.is_verified_complete(file_id, expected_file_hash=file_hash):
        meta = store.load_meta(file_id) or {}
        complete = store._complete_path(file_id)
        if complete is not None:
            inventory.register(
                file_id=file_id,
                filename=str(meta.get("filename") or complete.name),
                file_hash=str(meta.get("file_hash") or file_hash or ""),
                file_size=int(meta.get("file_size") or complete.stat().st_size),
                path=complete,
                source="download",
            )
            hit = _ok(inventory.get(file_id))
            if hit:
                return hit

    if file_hash:
        for entry in inventory.list_files():
            if entry.get("file_hash") == file_hash:
                hit = _ok(entry)
                if hit:
                    return hit
    return None


def _library_focus_url(file_id: int) -> str:
    return f"/library?focus={int(file_id)}"


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
    inventory = LocalInventory(data, store)
    verify_summary = inventory.verify_all()
    print(
        "[peer] library verify: "
        f"checked={verify_summary['checked']} ok={verify_summary['ok']} "
        f"missing={verify_summary['missing']} corrupt={verify_summary['corrupt']}"
    )

    app.config.update(
        DATA_DIR=data,
        TRACKER_URL=tracker,
        PEER_IP=ip,
        PEER_PORT=port,
        STORE=store,
        INVENTORY=inventory,
        LIBRARY_VERIFY=verify_summary,
        DOWNLOADS={},
        UPLOAD_TMP=data / "_uploads",
    )
    app.config["UPLOAD_TMP"].mkdir(parents=True, exist_ok=True)

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
        print(f"[peer] WARNING: could not register with tracker ({exc})")


def _tracker_json(path: str):
    tracker = app.config["TRACKER_URL"]
    req = urllib.request.Request(f"{tracker}{path}", method="GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())


def _enrich_files(files: list[dict]) -> list[dict]:
    out = []
    for f in files:
        item = dict(f)
        item["size_label"] = _format_size(int(item.get("file_size") or 0))
        out.append(item)
    return out


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
    # Refuse to serve empty/truncated stubs that would poison other peers.
    meta = store.load_meta(file_id) or {}
    file_size = meta.get("file_size")
    chunk_count = meta.get("chunk_count")
    if file_size is not None and chunk_count is not None:
        expected = store.expected_chunk_size(file_id, chunk_index, int(file_size), int(chunk_count))
        if expected is not None and len(data) != expected:
            return jsonify({"error": "chunk size mismatch"}), 404
        hashes = meta.get("chunk_hashes") or []
        if chunk_index < len(hashes):
            if not verify_chunk(data, hashes[chunk_index]):
                return jsonify({"error": "chunk hash mismatch"}), 404
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


@app.get("/")
def home():
    error = None
    files: list[dict] = []
    try:
        files = _enrich_files(_tracker_json("/files"))
    except Exception as exc:  # noqa: BLE001
        error = f"Could not reach tracker: {exc}"
    data_dir = Path(app.config["DATA_DIR"])
    return render_template(
        "index.html",
        files=files,
        error=error,
        peer_ip=app.config["PEER_IP"],
        peer_port=app.config["PEER_PORT"],
        data_dir=str(data_dir.resolve()),
        downloads_dir=str((data_dir / "complete").resolve()),
    )


@app.get("/upload")
def upload_page():
    return render_template("upload.html")


@app.get("/download/<int:file_id>")
def download_page(file_id: int):
    filename = f"File #{file_id}"
    size_label = "—"
    seeder_count = 0
    file_hash = None
    try:
        meta = _tracker_json(f"/files/{file_id}")
        filename = meta.get("filename") or filename
        size_label = _format_size(int(meta.get("file_size") or 0))
        seeder_count = int(meta.get("seeder_count") or 0)
        file_hash = meta.get("file_hash")
    except Exception:  # noqa: BLE001
        pass

    # Already have a healthy local copy → jump to that library record.
    force = request.args.get("force") in {"1", "true", "yes"}
    if not force:
        owned = _owned_library_entry(file_id, file_hash=file_hash)
        if owned:
            return redirect(_library_focus_url(int(owned["file_id"])))

    data_dir = Path(app.config["DATA_DIR"])
    complete_dir = (data_dir / "complete" / str(file_id)).resolve()
    expected_path = complete_dir / filename
    store: ChunkStore = app.config["STORE"]
    existing = None
    if store.is_verified_complete(file_id):
        existing = store._complete_path(file_id)
    return render_template(
        "download.html",
        file_id=file_id,
        filename=filename,
        size_label=size_label,
        seeder_count=seeder_count,
        data_dir=str(data_dir.resolve()),
        downloads_dir=str((data_dir / "complete").resolve()),
        expected_path=str(expected_path),
        existing_path=str(existing) if existing else None,
    )


@app.get("/api/files")
def api_files():
    try:
        files = _enrich_files(_tracker_json("/files"))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 502
    return jsonify(files)


@app.post("/api/upload")
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "missing file field"}), 400
    uploaded = request.files["file"]
    if not uploaded or not uploaded.filename:
        return jsonify({"error": "empty filename"}), 400

    safe_name = secure_filename(uploaded.filename) or "upload.bin"
    tmp_path = app.config["UPLOAD_TMP"] / safe_name
    uploaded.save(tmp_path)

    try:
        result = upload_file(
            source=tmp_path,
            tracker_url=app.config["TRACKER_URL"],
            store=app.config["STORE"],
            peer_ip=app.config["PEER_IP"],
            peer_port=app.config["PEER_PORT"],
            filename=uploaded.filename,
        )
        _register_library(result, source="seed")
    except UploadError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500
    finally:
        tmp_path.unlink(missing_ok=True)

    return jsonify(result), 201


_ACTIVE_DOWNLOAD = {
    "starting",
    "running",
    "chunk_ok",
    "skip_existing",
    "no_peers",
    "chunk_failed",
}


def _set_progress(file_id: int, **fields) -> None:
    downloads = app.config["DOWNLOADS"]
    current = dict(downloads.get(file_id) or {})
    current.update(fields)
    current["file_id"] = file_id
    downloads[file_id] = current


def _run_download(file_id: int) -> None:
    store: ChunkStore = app.config["STORE"]

    def on_progress(info: dict) -> None:
        status = info.get("status", "running")
        warning = None
        if status == "no_peers":
            warning = (
                f"No seeders for chunk {info.get('chunk_index')}; "
                "will keep trying other chunks / refresh peer map."
            )
        elif status == "chunk_failed":
            errs = info.get("errors") or []
            hint = "; ".join(errs[:2]) if errs else "peer unreachable"
            warning = (
                f"Peer failure on chunk {info.get('chunk_index')} ({hint}). "
                "Trying remaining seeders…"
            )
        fields = {
            "status": status,
            "chunks_have": info.get("chunks_have", 0),
            "chunks_total": info.get("chunks_total", 0),
            "percent": info.get("percent", 0),
            "peers_known": info.get("peers_known", 0),
            "filename": info.get("filename"),
            "path": info.get("path"),
            "error": None,
        }
        if warning:
            fields["warning"] = warning
        elif status in {"chunk_ok", "skip_existing", "complete"}:
            fields["warning"] = None
        _set_progress(file_id, **fields)

    try:
        _set_progress(
            file_id,
            status="starting",
            percent=0,
            chunks_have=0,
            chunks_total=0,
            peers_known=0,
            path=None,
            error=None,
            warning=None,
        )
        result = download_file(
            file_id=file_id,
            tracker_url=app.config["TRACKER_URL"],
            store=store,
            peer_ip=app.config["PEER_IP"],
            peer_port=app.config["PEER_PORT"],
            on_progress=on_progress,
        )
        _register_library(result, source="download")
        _set_progress(
            file_id,
            status="complete",
            percent=100,
            path=result.get("path"),
            chunks_have=result.get("chunk_count"),
            chunks_total=result.get("chunk_count"),
            error=None,
            warning=None,
        )
    except (DownloadError, urllib.error.URLError, Exception) as exc:  # noqa: BLE001
        _set_progress(file_id, status="error", error=str(exc), warning=None)


@app.post("/api/download/<int:file_id>")
def api_download(file_id: int):
    downloads = app.config["DOWNLOADS"]
    existing = downloads.get(file_id) or {}
    if existing.get("status") in _ACTIVE_DOWNLOAD:
        return jsonify({"status": "already_running", "file_id": file_id}), 202

    file_hash = None
    try:
        meta = _tracker_json(f"/files/{file_id}")
        file_hash = meta.get("file_hash")
    except Exception:  # noqa: BLE001
        pass
    owned = _owned_library_entry(file_id, file_hash=file_hash)
    if owned:
        focus_id = int(owned["file_id"])
        return (
            jsonify(
                {
                    "status": "already_have",
                    "file_id": focus_id,
                    "filename": owned.get("filename"),
                    "redirect": _library_focus_url(focus_id),
                    "message": "File already in your library.",
                }
            ),
            200,
        )

    _set_progress(
        file_id,
        status="starting",
        percent=0,
        chunks_have=0,
        chunks_total=0,
        peers_known=0,
        path=None,
        error=None,
        warning=None,
    )
    thread = threading.Thread(target=_run_download, args=(file_id,), daemon=True)
    thread.start()
    return jsonify({"status": "started", "file_id": file_id}), 202


@app.get("/progress/<int:file_id>")
def progress(file_id: int):
    """Progress snapshot for UI polling (stable Step 7 contract)."""
    store: ChunkStore = app.config["STORE"]
    data_dir = Path(app.config["DATA_DIR"]).resolve()
    job = dict(app.config["DOWNLOADS"].get(file_id) or {})

    chunks_total = int(job.get("chunks_total") or 0)
    chunk_hashes: list[str] = []
    file_size = None
    filename = job.get("filename")
    file_hash = None
    try:
        meta = _tracker_json(f"/files/{file_id}")
        chunk_hashes = list(meta.get("chunk_hashes") or [])
        chunks_total = chunks_total or int(meta.get("chunk_count") or len(chunk_hashes))
        filename = filename or meta.get("filename")
        file_size = int(meta.get("file_size") or 0)
        file_hash = meta.get("file_hash")
    except Exception:  # noqa: BLE001
        pass

    def chunk_ok(i: int) -> bool:
        if chunk_hashes and file_size is not None and chunks_total:
            expected_size = (
                CHUNK_SIZE if i < chunks_total - 1 else file_size - (chunks_total - 1) * CHUNK_SIZE
            )
            return store.has_chunk(
                file_id, i, expected_hash=chunk_hashes[i], expected_size=expected_size
            )
        return store.has_chunk(file_id, i)

    chunks_have = int(job.get("chunks_have") or 0)
    if chunks_total:
        chunks_have = sum(1 for i in range(chunks_total) if chunk_ok(i))

    status = job.get("status") or "idle"
    percent = float(job.get("percent") or 0)
    if chunks_total and status not in {"error", "complete", "starting"}:
        percent = round(100.0 * chunks_have / chunks_total, 1)

    # Only advertise a save path when the local copy is verified complete.
    verified = store.is_verified_complete(file_id, expected_file_hash=file_hash)
    complete = store._complete_path(file_id) if verified else None
    path = None
    if complete is not None and status != "error":
        path = str(complete.resolve())
        if status in {"idle", None} and chunks_total and chunks_have == chunks_total:
            status = "complete"
            percent = 100.0
    elif status == "complete":
        filename = filename or f"file_{file_id}"
        path = job.get("path") or str(
            (data_dir / "complete" / str(file_id) / filename).resolve()
        )

    if status == "complete":
        percent = 100.0
        if chunks_total:
            chunks_have = chunks_total

    # Stable contract fields always present (null when unknown / N/A).
    return jsonify(
        {
            "file_id": file_id,
            "status": status or "idle",
            "percent": percent,
            "chunks_have": chunks_have,
            "chunks_total": chunks_total,
            "peers_known": int(job.get("peers_known") or 0),
            "path": path,
            "error": job.get("error"),
            "warning": job.get("warning"),
            "filename": filename,
            "data_dir": str(data_dir),
            "downloads_dir": str(data_dir / "complete"),
        }
    )


# ---------------------------------------------------------------------------
# Local file manager (library)
# ---------------------------------------------------------------------------


@app.get("/library")
def library_page():
    inventory: LocalInventory = app.config["INVENTORY"]
    # Light refresh of statuses for the dashboard (full hash check).
    summary = inventory.verify_all()
    app.config["LIBRARY_VERIFY"] = summary
    focus_id = request.args.get("focus", type=int)
    entries = []
    for e in inventory.list_files():
        item = dict(e)
        item["size_label"] = _format_size(int(item.get("file_size") or 0))
        item["is_zombie"] = item.get("status") in {"missing", "corrupt"}
        item["is_focus"] = focus_id is not None and int(item["file_id"]) == focus_id
        entries.append(item)
    data_dir = Path(app.config["DATA_DIR"])
    return render_template(
        "library.html",
        entries=entries,
        summary=summary,
        downloads_dir=str((data_dir / "complete").resolve()),
        zombie_count=summary.get("zombies", 0),
        focus_id=focus_id,
    )


@app.post("/api/library/verify")
def api_library_verify():
    inventory: LocalInventory = app.config["INVENTORY"]
    summary = inventory.verify_all()
    app.config["LIBRARY_VERIFY"] = summary
    return jsonify(summary)


@app.post("/api/library/clear-zombies")
def api_library_clear_zombies():
    inventory: LocalInventory = app.config["INVENTORY"]
    summary = inventory.clear_zombies()
    app.config["LIBRARY_VERIFY"] = summary
    return jsonify(summary)


@app.get("/api/library/<int:file_id>/copy")
def api_library_copy(file_id: int):
    """Save-As style download of a verified local file."""
    inventory: LocalInventory = app.config["INVENTORY"]
    entry = inventory.get(file_id)
    path = inventory.resolve_path(file_id)
    if not entry or path is None:
        return jsonify({"error": "File unavailable (missing or corrupt)"}), 404
    return send_file(
        path,
        as_attachment=True,
        download_name=entry.get("filename") or path.name,
        mimetype="application/octet-stream",
        conditional=True,
    )


@app.post("/api/library/<int:file_id>/open")
def api_library_open(file_id: int):
    """Open the file with the OS default app on this peer machine."""
    inventory: LocalInventory = app.config["INVENTORY"]
    path = inventory.resolve_path(file_id)
    if path is None:
        return jsonify({"error": "File unavailable (missing or corrupt)"}), 404
    try:
        _open_with_os(path)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"Could not open file: {exc}"}), 500
    return jsonify({"status": "opened", "path": str(path)})


@app.post("/api/library/<int:file_id>/delete")
def api_library_delete(file_id: int):
    """Remove a library entry from SQLite and wipe local complete/meta/chunks."""
    inventory: LocalInventory = app.config["INVENTORY"]
    try:
        result = inventory.delete_file(file_id)
    except KeyError:
        return jsonify({"error": "File not in library"}), 404
    # Drop any in-memory download progress for this id.
    downloads = app.config.get("DOWNLOADS") or {}
    downloads.pop(file_id, None)
    return jsonify({"status": "deleted", **result})


if __name__ == "__main__":
    create_app()
    host = _env("PEER_HOST", "0.0.0.0")
    port = int(app.config["PEER_PORT"])
    app.run(host=host, port=port, debug=False, threaded=True)
