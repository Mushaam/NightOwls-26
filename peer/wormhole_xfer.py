"""Magic Wormhole chunk transfer (transit) — sync wrappers via crochet."""

from __future__ import annotations

import hashlib
import io
import json
import time
import urllib.error
import urllib.request
from typing import Any, Callable

import crochet
from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks
from twisted.protocols import basic
from wormhole import create
from wormhole.transit import TransitReceiver, TransitSender
from wormhole.util import bytes_to_dict, bytes_to_hexstr, dict_to_bytes

from shared.config import load_config

_crochet_ready = False


def _ensure_crochet() -> None:
    global _crochet_ready
    if not _crochet_ready:
        crochet.setup()
        _crochet_ready = True


def _wh_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    cfg = cfg or load_config()
    return dict(cfg.get("wormhole") or {})


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


@inlineCallbacks
def _send_chunk_deferred(
    payload: bytes,
    *,
    appid: str,
    mailbox_url: str,
    transit_helper: str,
    on_code: Callable[[str], None] | None,
):
    w = create(appid, mailbox_url, reactor)
    try:
        yield w.get_welcome()
        w.allocate_code()
        code = yield w.get_code()
        if on_code is not None:
            on_code(str(code))

        # Peer must join (PAKE) before derive_key / transit is valid.
        yield w.get_verifier()

        ts = TransitSender(transit_helper, reactor=reactor)
        sender_abilities = ts.get_connection_abilities()
        sender_hints = yield ts.get_connection_hints()
        transit_key = w.derive_key(appid + "/transit-key", ts.TRANSIT_KEY_LENGTH)
        ts.set_transit_key(transit_key)
        w.send_message(
            dict_to_bytes(
                {
                    "transit": {
                        "abilities-v1": sender_abilities,
                        "hints-v1": sender_hints,
                    },
                    "offer": {"size": len(payload)},
                }
            )
        )

        got_transit = False
        got_answer = False
        while not (got_transit and got_answer):
            them = bytes_to_dict((yield w.get_message()))
            if "error" in them:
                raise RuntimeError(str(them["error"]))
            if "transit" in them:
                ts.add_connection_hints(them["transit"].get("hints-v1") or [])
                got_transit = True
            if "answer" in them:
                if them["answer"].get("file_ack") != "ok":
                    raise RuntimeError(f"receiver rejected transfer: {them['answer']!r}")
                got_answer = True

        record_pipe = yield ts.connect()
        hasher = hashlib.sha256()

        def _count(data: bytes) -> bytes:
            hasher.update(data)
            return data

        bio = io.BytesIO(payload)
        if payload:
            fs = basic.FileSender()
            yield fs.beginFileTransfer(bio, record_pipe, transform=_count)
        else:
            hasher.update(b"")

        ack = bytes_to_dict((yield record_pipe.receive_record()))
        record_pipe.close()
        if ack.get("ack") != "ok":
            raise RuntimeError(f"bad transit ack: {ack!r}")
        expected = bytes_to_hexstr(hasher.digest())
        if ack.get("sha256") and ack["sha256"] != expected:
            raise RuntimeError("receiver reported hash mismatch")
    finally:
        try:
            yield w.close()
        except Exception:
            pass


@inlineCallbacks
def _recv_chunk_deferred(
    code: str,
    *,
    appid: str,
    mailbox_url: str,
    transit_helper: str,
):
    w = create(appid, mailbox_url, reactor)
    try:
        yield w.get_welcome()
        w.set_code(code)
        yield w.get_code()
        yield w.get_verifier()

        them = bytes_to_dict((yield w.get_message()))
        if "error" in them:
            raise RuntimeError(str(them["error"]))
        if "transit" not in them or "offer" not in them:
            raise RuntimeError(f"unexpected first message: {them!r}")

        size = int(them["offer"]["size"])
        tr = TransitReceiver(transit_helper, reactor=reactor)
        tr.add_connection_hints(them["transit"].get("hints-v1") or [])
        receiver_abilities = tr.get_connection_abilities()
        receiver_hints = yield tr.get_connection_hints()
        transit_key = w.derive_key(appid + "/transit-key", tr.TRANSIT_KEY_LENGTH)
        tr.set_transit_key(transit_key)

        w.send_message(
            dict_to_bytes(
                {
                    "transit": {
                        "abilities-v1": receiver_abilities,
                        "hints-v1": receiver_hints,
                    }
                }
            )
        )
        w.send_message(dict_to_bytes({"answer": {"file_ack": "ok"}}))

        record_pipe = yield tr.connect()
        buf = io.BytesIO()
        hasher = hashlib.sha256()
        received = yield record_pipe.writeToFile(buf, size, None, hasher.update)
        if received != size:
            raise RuntimeError(f"short read: got {received}, wanted {size}")
        ack = {"ack": "ok", "sha256": bytes_to_hexstr(hasher.digest())}
        yield record_pipe.send_record(dict_to_bytes(ack))
        record_pipe.close()
        return buf.getvalue()
    finally:
        try:
            yield w.close()
        except Exception:
            pass


def send_chunk_bytes(
    payload: bytes,
    *,
    cfg: dict[str, Any] | None = None,
    on_code: Callable[[str], None] | None = None,
    timeout: float | None = None,
) -> None:
    """Send raw chunk bytes; call on_code(code) once the wormhole code exists."""
    _ensure_crochet()
    wh = _wh_cfg(cfg)
    timeout = float(timeout if timeout is not None else wh.get("job_timeout_sec", 90))

    @crochet.wait_for(timeout=timeout)
    def _run():
        return _send_chunk_deferred(
            payload,
            appid=str(wh.get("appid") or "nightowls.file-share"),
            mailbox_url=str(wh["mailbox_url"]),
            transit_helper=str(wh["transit_helper"]),
            on_code=on_code,
        )

    _run()


def receive_chunk_bytes(
    code: str,
    *,
    cfg: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> bytes:
    """Receive raw chunk bytes using a wormhole code from the seeder."""
    _ensure_crochet()
    wh = _wh_cfg(cfg)
    timeout = float(timeout if timeout is not None else wh.get("job_timeout_sec", 90))

    @crochet.wait_for(timeout=timeout)
    def _run():
        return _recv_chunk_deferred(
            code,
            appid=str(wh.get("appid") or "nightowls.file-share"),
            mailbox_url=str(wh["mailbox_url"]),
            transit_helper=str(wh["transit_helper"]),
        )

    return _run()


def fetch_chunk_via_wormhole(
    tracker_url: str,
    seeder: dict[str, Any],
    file_id: int,
    chunk_index: int,
    requester_ip: str,
    requester_port: int,
    cfg: dict[str, Any] | None = None,
) -> bytes:
    """
    Ask the tracker to schedule a wormhole job with ``seeder``, wait for a code,
    then receive the chunk over transit.
    """
    cfg = cfg or load_config()
    wh = _wh_cfg(cfg)
    base = tracker_url.rstrip("/")
    poll = float(wh.get("job_poll_sec", 1.0))
    timeout = float(wh.get("job_timeout_sec", 90))

    job = _http_json(
        f"{base}/wormhole/jobs",
        method="POST",
        payload={
            "seeder_ip": seeder["ip"],
            "seeder_port": int(seeder["port"]),
            "requester_ip": requester_ip,
            "requester_port": int(requester_port),
            "file_id": int(file_id),
            "chunk_index": int(chunk_index),
        },
    )
    job_id = int(job["id"])
    deadline = time.time() + timeout
    code = None
    while time.time() < deadline:
        cur = _http_json(f"{base}/wormhole/jobs/{job_id}")
        status = cur.get("status")
        if status == "error":
            raise RuntimeError(cur.get("detail") or "seeder reported wormhole error")
        if cur.get("code"):
            code = cur["code"]
            break
        if status == "done":
            raise RuntimeError("job finished before code was observed")
        time.sleep(poll)
    if not code:
        raise TimeoutError(f"wormhole job {job_id} timed out waiting for code")

    try:
        data = receive_chunk_bytes(code, cfg=cfg, timeout=max(5.0, deadline - time.time()))
    except Exception:
        try:
            _http_json(
                f"{base}/wormhole/jobs/{job_id}/status",
                method="POST",
                payload={"status": "error", "detail": "receiver failed"},
            )
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
            pass
        raise

    try:
        _http_json(
            f"{base}/wormhole/jobs/{job_id}/status",
            method="POST",
            payload={"status": "done"},
        )
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        pass
    return data
