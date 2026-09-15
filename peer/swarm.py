"""Peer swarm logic — upload/seed and download chunks across peers."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from peer.store import ChunkStore
from shared.utils import CHUNK_SIZE, chunk_file, verify_chunk, verify_file, write_chunks_to_file


class SwarmError(RuntimeError):
    """Base error for swarm upload/download failures."""


class DownloadError(SwarmError):
    """Raised when a file cannot be fully downloaded."""


class UploadError(SwarmError):
    """Raised when a file cannot be seeded to the tracker."""


def _http_json(url: str, method: str = "GET", payload: dict | None = None, timeout: float = 10) -> Any:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode()
        return json.loads(body) if body else None


def _http_bytes(url: str, timeout: float = 15) -> bytes:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _try_fetch_chunk(
    peer: dict[str, Any],
    *,
    file_id: int,
    chunk_index: int,
    expected_size: int,
    expected_hash: str,
    tracker_url: str,
    peer_ip: str,
    peer_port: int,
    direct_timeout: float,
    wormhole_on: bool,
    cfg: dict[str, Any] | None,
) -> tuple[bytes | None, str | None, list[str]]:
    """
    Try direct HTTP, then Magic Wormhole fallback.
    Returns (data, from_label, errors).
    """
    errors: list[str] = []
    label = f"{peer['ip']}:{peer['port']}"
    url = f"http://{peer['ip']}:{peer['port']}/chunk/{file_id}/{chunk_index}"
    data: bytes | None = None
    try:
        data = _http_bytes(url, timeout=direct_timeout)
    except urllib.error.HTTPError as exc:
        errors.append(f"{label} HTTP {exc.code}")
    except urllib.error.URLError as exc:
        errors.append(f"{label} {exc.reason}")

    if data is None and wormhole_on:
        try:
            from peer.wormhole_xfer import fetch_chunk_via_wormhole

            data = fetch_chunk_via_wormhole(
                tracker_url,
                peer,
                file_id,
                chunk_index,
                peer_ip,
                peer_port,
                cfg,
            )
            label = f"wormhole:{peer['ip']}:{peer['port']}"
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{label} wormhole {exc}")
            data = None

    if data is None:
        return None, None, errors

    if len(data) != expected_size:
        errors.append(f"{label} size {len(data)} != {expected_size}")
        return None, None, errors
    if not verify_chunk(data, expected_hash):
        errors.append(f"{label} hash mismatch")
        return None, None, errors
    return data, label, errors


def fetch_manifest(tracker_url: str, file_id: int) -> dict[str, Any]:
    meta = _http_json(f"{tracker_url.rstrip('/')}/files/{file_id}")
    if not meta or "chunk_hashes" not in meta:
        raise DownloadError(f"Invalid manifest for file_id={file_id}")
    return meta


def fetch_peer_map(tracker_url: str, file_id: int) -> list[dict[str, Any]]:
    peers = _http_json(f"{tracker_url.rstrip('/')}/peers/{file_id}")
    if not isinstance(peers, list):
        raise DownloadError(f"Invalid peer map for file_id={file_id}")
    return peers


def _peers_for_chunk(
    peer_map: list[dict[str, Any]],
    chunk_index: int,
    exclude: tuple[str, int] | None = None,
) -> list[dict[str, Any]]:
    candidates = []
    for peer in peer_map:
        chunks = peer.get("chunks") or []
        if chunk_index not in chunks:
            continue
        if exclude and peer.get("ip") == exclude[0] and int(peer.get("port", -1)) == exclude[1]:
            continue
        candidates.append(peer)
    return candidates


def _report_have_chunk(
    tracker_url: str,
    peer_ip: str,
    peer_port: int,
    file_id: int,
    chunk_index: int,
) -> None:
    _http_json(
        f"{tracker_url.rstrip('/')}/peer_has_chunk",
        method="POST",
        payload={
            "peer_ip": peer_ip,
            "peer_port": peer_port,
            "file_id": file_id,
            "chunk_index": chunk_index,
        },
    )


def upload_file(
    source: str | Path,
    tracker_url: str,
    store: ChunkStore,
    peer_ip: str,
    peer_port: int,
    *,
    filename: str | None = None,
) -> dict[str, Any]:
    """
    Seed a local file into the swarm.

    Steps:
      1. Hash/chunk the source (256 KB chunks, SHA-256)
      2. POST /upload_metadata with register_as_seeder=false (get file_id only)
      3. import_file into the local store so GET /chunk/<file_id>/<index> works
      4. POST /upload_metadata again with register_as_seeder=true (announce ready)
    """
    source = Path(source)
    if not source.is_file():
        raise UploadError(f"Source is not a file: {source}")

    tracker_url = tracker_url.rstrip("/")
    filename = filename or source.name

    file_hash, file_size, chunk_hashes = chunk_file(source)
    if file_size == 0 or not chunk_hashes:
        raise UploadError("Cannot seed an empty file")

    meta_payload = {
        "filename": filename,
        "file_hash": file_hash,
        "file_size": file_size,
        "chunk_hashes": chunk_hashes,
        "peer_ip": peer_ip,
        "peer_port": peer_port,
    }

    try:
        # Register the file first without advertising chunks — otherwise other
        # peers can start downloading while local pieces are still being written.
        tracker_meta = _http_json(
            f"{tracker_url}/upload_metadata",
            method="POST",
            payload={**meta_payload, "register_as_seeder": False},
        )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise UploadError(f"Tracker rejected upload_metadata ({exc.code}): {body}") from exc
    except urllib.error.URLError as exc:
        raise UploadError(f"Could not reach tracker: {exc}") from exc

    if not tracker_meta or "id" not in tracker_meta:
        raise UploadError(f"Unexpected tracker response: {tracker_meta!r}")

    file_id = int(tracker_meta["id"])
    local = store.import_file(source, file_id=file_id, filename=filename)

    # Sanity: local hashes must match what we announced
    if local["file_hash"] != file_hash or local["chunk_hashes"] != chunk_hashes:
        raise UploadError("Local import hash mismatch after upload")

    try:
        tracker_meta = _http_json(
            f"{tracker_url}/upload_metadata",
            method="POST",
            payload={**meta_payload, "register_as_seeder": True},
        )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise UploadError(
            f"Local seed ready but tracker rejected seeder announce ({exc.code}): {body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise UploadError(
            f"Local seed ready but could not announce seeder to tracker: {exc}"
        ) from exc

    result = {
        "file_id": file_id,
        "filename": filename,
        "file_hash": file_hash,
        "file_size": file_size,
        "chunk_hashes": chunk_hashes,
        "chunk_count": len(chunk_hashes),
        "peer_ip": peer_ip,
        "peer_port": peer_port,
        "path": str(store.complete_dir / str(file_id) / filename),
        "seeder_count": tracker_meta.get("seeder_count") if tracker_meta else None,
    }
    return result


def download_file(
    file_id: int,
    tracker_url: str,
    store: ChunkStore,
    peer_ip: str,
    peer_port: int,
    *,
    refresh_peers: bool = True,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Download a file from the swarm into ``store``.

    Steps:
      1. Fetch manifest + peer map from tracker
      2. For each missing chunk, round-robin peers that have it
         (direct HTTP first; Magic Wormhole fallback when configured)
      3. Verify SHA-256; save; report peer_has_chunk
      4. Reassemble into complete/<file_id>/<filename>
    """
    from shared.config import load_config, wormhole_enabled

    tracker_url = tracker_url.rstrip("/")
    exclude = (peer_ip, peer_port)
    cfg = config if config is not None else load_config()
    wormhole_on = wormhole_enabled(cfg)
    direct_timeout = float((cfg.get("wormhole") or {}).get("direct_timeout_sec", 4))

    manifest = fetch_manifest(tracker_url, file_id)
    chunk_hashes: list[str] = list(manifest["chunk_hashes"])
    chunk_count = len(chunk_hashes)
    filename = manifest.get("filename") or f"file_{file_id}"
    file_hash = manifest["file_hash"]
    file_size = int(manifest["file_size"])

    # Drop leftover corrupt complete/ from a previous failed run so has_chunk
    # cannot treat it as a source of truth.
    store.clear_incomplete(file_id)

    def chunk_size_for(index: int) -> int:
        if index < chunk_count - 1:
            return CHUNK_SIZE
        return file_size - (chunk_count - 1) * CHUNK_SIZE

    def have_valid(index: int) -> bool:
        return store.has_chunk(
            file_id,
            index,
            expected_hash=chunk_hashes[index],
            expected_size=chunk_size_for(index),
        )

    peer_map = fetch_peer_map(tracker_url, file_id)
    rr_cursor = 0
    fetched_this_run = 0
    failed_chunks: list[int] = []
    failure_details: list[str] = []

    def emit(status: str, **extra: Any) -> None:
        if on_progress is None:
            return
        have = sum(1 for i in range(chunk_count) if have_valid(i))
        payload = {
            "file_id": file_id,
            "filename": filename,
            "status": status,
            "chunks_total": chunk_count,
            "chunks_have": have,
            "percent": round(100.0 * have / chunk_count, 1) if chunk_count else 100.0,
            "peers_known": len(peer_map),
            **extra,
        }
        on_progress(payload)

    emit("starting")

    for chunk_index, expected_hash in enumerate(chunk_hashes):
        expected_size = chunk_size_for(chunk_index)
        if have_valid(chunk_index):
            emit("skip_existing", chunk_index=chunk_index)
            continue

        # Stale/empty/corrupt local piece — delete and re-fetch.
        store.delete_chunk(file_id, chunk_index)

        if refresh_peers and chunk_index > 0 and chunk_index % 5 == 0:
            try:
                peer_map = fetch_peer_map(tracker_url, file_id)
            except (urllib.error.URLError, DownloadError, json.JSONDecodeError):
                pass

        candidates = _peers_for_chunk(peer_map, chunk_index, exclude=exclude)
        if not candidates:
            # Refresh once if nobody listed yet
            peer_map = fetch_peer_map(tracker_url, file_id)
            candidates = _peers_for_chunk(peer_map, chunk_index, exclude=exclude)

        if not candidates:
            failed_chunks.append(chunk_index)
            detail = (
                f"chunk {chunk_index}: no reachable seeders "
                f"(known peers={len(peer_map)}; check PEER_IP / that the uploader is online)"
            )
            failure_details.append(detail)
            emit("no_peers", chunk_index=chunk_index)
            continue

        got = False
        # Round-robin start offset across chunks
        start = rr_cursor % len(candidates)
        ordered = candidates[start:] + candidates[:start]
        rr_cursor += 1

        errors: list[str] = []
        for peer in ordered:
            data, from_label, peer_errors = _try_fetch_chunk(
                peer,
                file_id=file_id,
                chunk_index=chunk_index,
                expected_size=expected_size,
                expected_hash=expected_hash,
                tracker_url=tracker_url,
                peer_ip=peer_ip,
                peer_port=peer_port,
                direct_timeout=direct_timeout,
                wormhole_on=wormhole_on,
                cfg=cfg,
            )
            errors.extend(peer_errors)
            if data is None:
                continue

            store.save_chunk(file_id, chunk_index, data)
            try:
                _report_have_chunk(tracker_url, peer_ip, peer_port, file_id, chunk_index)
            except (urllib.error.URLError, json.JSONDecodeError) as exc:
                # Chunk is local; tracker notify can be retried later
                errors.append(f"tracker notify failed: {exc}")

            fetched_this_run += 1
            got = True
            emit(
                "chunk_ok",
                chunk_index=chunk_index,
                from_peer=from_label,
            )
            break

        if not got:
            failed_chunks.append(chunk_index)
            failure_details.append(
                f"chunk {chunk_index}: " + ("; ".join(errors) if errors else "unknown error")
            )
            emit("chunk_failed", chunk_index=chunk_index, errors=errors)

    missing = [i for i in range(chunk_count) if not have_valid(i)]
    if missing:
        hint = ""
        if failure_details:
            # Keep the message readable; full detail is in the first few failures.
            shown = failure_details[:3]
            more = len(failure_details) - len(shown)
            hint = " — " + " | ".join(shown)
            if more > 0:
                hint += f" | …+{more} more"
        raise DownloadError(
            f"Incomplete download for file_id={file_id}; "
            f"missing chunks: {failed_chunks or missing}{hint}"
        )

    dest_dir = store.complete_dir / str(file_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename

    ordered_chunks = []
    for i in range(chunk_count):
        block = store.load_chunk(file_id, i)
        if block is None:
            raise DownloadError(f"Missing chunk {i} during reassembly")
        if len(block) != chunk_size_for(i) or not verify_chunk(block, chunk_hashes[i]):
            store.delete_chunk(file_id, i)
            raise DownloadError(f"Corrupt chunk {i} during reassembly")
        ordered_chunks.append(block)

    # Write to a temp path first; only publish after whole-file hash matches.
    tmp_dest = dest_dir / f".{filename}.partial"
    try:
        write_chunks_to_file(tmp_dest, ordered_chunks)
        if not verify_file(tmp_dest, file_hash):
            raise DownloadError(f"Reassembled file hash mismatch for file_id={file_id}")
        tmp_dest.replace(dest)
    except Exception:
        tmp_dest.unlink(missing_ok=True)
        store.clear_incomplete(file_id)
        raise

    meta = {
        "file_id": file_id,
        "filename": filename,
        "file_hash": file_hash,
        "file_size": file_size,
        "chunk_hashes": chunk_hashes,
        "chunk_count": chunk_count,
        "path": str(dest),
        "fetched_this_run": fetched_this_run,
        "verified": True,
    }
    (store.meta_dir / f"{file_id}.json").write_text(json.dumps(meta, indent=2))
    emit("complete", path=str(dest))
    return meta


def _progress_printer(info: dict[str, Any]) -> None:
    status = info.get("status")
    pct = info.get("percent")
    have = info.get("chunks_have")
    total = info.get("chunks_total")
    extra = ""
    if status == "chunk_ok":
        extra = f" chunk={info.get('chunk_index')} from {info.get('from_peer')}"
    elif status in ("no_peers", "chunk_failed"):
        extra = f" chunk={info.get('chunk_index')}"
    print(f"[swarm] {status} {have}/{total} ({pct}%){extra}")


def _print_result(label: str, result: dict[str, Any]) -> None:
    print(f"[swarm] {label}:")
    for k, v in result.items():
        if k == "chunk_hashes":
            print(f"  chunk_hashes: {len(v)} entries")
        else:
            print(f"  {k}: {v}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NightOwls peer swarm client")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--tracker", default="http://127.0.0.1:5000")
    common.add_argument("--data-dir", required=True, help="Local peer data directory")
    common.add_argument("--peer-ip", default="127.0.0.1")
    common.add_argument("--peer-port", type=int, required=True)

    up = sub.add_parser("upload", parents=[common], help="Seed a local file to the tracker")
    up.add_argument("--path", required=True, help="File to upload/seed")
    up.add_argument("--filename", default=None, help="Override filename announced to tracker")

    down = sub.add_parser("download", parents=[common], help="Download a file from the swarm")
    down.add_argument("--file-id", type=int, required=True)

    args = parser.parse_args(argv)
    store = ChunkStore(args.data_dir)

    try:
        if args.command == "upload":
            result = upload_file(
                source=args.path,
                tracker_url=args.tracker,
                store=store,
                peer_ip=args.peer_ip,
                peer_port=args.peer_port,
                filename=args.filename,
            )
            _print_result("uploaded", result)
            return 0

        result = download_file(
            file_id=args.file_id,
            tracker_url=args.tracker,
            store=store,
            peer_ip=args.peer_ip,
            peer_port=args.peer_port,
            on_progress=_progress_printer,
        )
        _print_result("downloaded", result)
        return 0
    except SwarmError as exc:
        print(f"[swarm] ERROR: {exc}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"[swarm] ERROR: network: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
