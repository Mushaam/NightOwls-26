# NightOwls-26 — Build Handoff Report

**Last updated:** 2026-09-12 (after Step 3)  
**Project:** Decentralized LAN file-sharing (BitTorrent-style tracker + peers)  
**Workspace:** `/home/harsh/Desktop/CC/NightOwls-26`

This document is the source of truth for resuming work after a context/token reset. Follow the **BUILD ORDER**; do not skip ahead. Pause after each step for human review unless the user says otherwise.

**Maintainers:** Update this file after **every** completed BUILD ORDER step.

---

## Goal (one line)

Flask tracker + Flask peer nodes that chunk files (256 KB), hash with SHA-256, exchange chunks over HTTP, and expose a dark CRED/Spotify-style UI.

---

## Tech stack (strict)

| Layer | Choice |
|-------|--------|
| Backend | Flask (Python) |
| Frontend | HTML + CSS (custom, no Bootstrap); vanilla JS only for polling/progress |
| Optional | Streamlit for admin/debug only (not main UI) |
| DB | SQLite |
| Env | `.venv/` (required on Kali — PEP 668); `requirements.txt` pins `Flask==3.1.3` |

**UI direction:** deep black/charcoal, one vibrant accent (e.g. electric purple `#7c3aed`), bold rounded sans, card grid, CSS variables, Google Fonts (Inter or similar). No React/Vue.

---

## Architecture summary

1. **Tracker** (one on the LAN) — registry of files, chunk manifests, peer↔chunk map.  
2. **Peer** (every student machine) — client + mini HTTP server that serves `/chunk/<file_id>/<chunk_index>`, downloads from other peers, verifies hashes, reports `peer_has_chunk`.  
3. **Frontend** — served by peer Flask templates; file browser, upload, download progress with 1s polling.

### Tracker endpoints

| Method | Path | Status |
|--------|------|--------|
| POST | `/register_peer` | Done |
| POST | `/upload_metadata` | Done |
| GET | `/files` | Done |
| GET | `/files/<id>` | Done (extra; useful for manifest) |
| GET | `/peers/<file_id>` | Done |
| POST | `/peer_has_chunk` | Done |

### Peer endpoints

| Method | Path | Status |
|--------|------|--------|
| GET | `/health` | Done (Step 3) |
| GET | `/chunk/<file_id>/<chunk_index>` | **Done (Step 3)** |
| (UI routes) | `/`, `/upload`, `/download/...` | Steps 6–7 |
| GET | `/progress/<file_id>` | Step 7 |

---

## BUILD ORDER (checklist)

| # | Step | Status |
|---|------|--------|
| 1 | Scaffold folders + `shared/utils.py` chunking/hashing | **DONE** |
| 2 | Tracker Flask app + SQLite models; curl-tested | **DONE** |
| 3 | Peer chunk-serving endpoint; manual P2P chunk fetch | **DONE** |
| 4 | Peer download logic (manifest → fetch → verify → reassemble) | **NEXT** |
| 5 | Peer upload/seed logic (chunk + hash + register with tracker) | Pending |
| 6 | CRED/Spotify frontend (templates + CSS) | Pending |
| 7 | Polling progress bars (`fetch` every 1s → `/progress/<file_id>`) | Pending |

### Demo requirements (keep in mind while building)

- Tracker + **3+ peers** on localhost, different ports.  
- Killing one peer mid-download must not block others.  
- Seed script: 2–3 dummy files pre-seeded for instant demo content.

---

## Current tree

```
NightOwls-26/
├── HANDOFF.md                # THIS FILE — update after every step
├── README.md                 # stub title only
├── requirements.txt          # Flask==3.1.3
├── test_utils_smoke.py       # Step 1 smoke test
├── .venv/                    # local virtualenv
├── scripts/
│   └── seed_peer_chunks.py   # seed local chunk store for curl tests
├── shared/
│   ├── __init__.py
│   └── utils.py              # CHUNK_SIZE=256KB, hash/chunk/verify helpers
├── tracker/
│   ├── __init__.py
│   ├── app.py                # Flask tracker (Step 2 complete)
│   └── models.py             # SQLite schema + CRUD helpers
└── peer/
    ├── __init__.py
    ├── app.py                # chunk server + tracker register (Step 3)
    ├── store.py              # on-disk chunk/complete/meta store (Step 3)
    ├── swarm.py              # EMPTY — implement Step 4–5 HERE
    ├── templates/            # empty placeholders (index, upload, download)
    └── static/               # empty placeholders (style.css, script.js)
```

### Peer local storage layout (`PEER_DATA_DIR`)

```
<data_dir>/
  chunks/<file_id>/<chunk_index>.bin
  complete/<file_id>/<filename>     # optional full file
  meta/<file_id>.json               # filename, hashes, sizes
```

`ChunkStore.load_chunk` prefers discrete chunk files, else slices from `complete/`.

---

## How to run what exists

```bash
cd /home/harsh/Desktop/CC/NightOwls-26
# use .venv/bin/python (PEP 668 on Kali)

# Utils smoke test
.venv/bin/python test_utils_smoke.py

# Tracker (port 5000)
TRACKER_DB=/tmp/nightowls_tracker.db TRACKER_PORT=5000 .venv/bin/python -m tracker.app

# Seed chunks into a peer data dir (for Step 3-style tests)
.venv/bin/python scripts/seed_peer_chunks.py \
  --data-dir /tmp/nightowls_peer6001 --file-id 1 --size 400000

# Peer chunk server (port 6001)
PEER_DATA_DIR=/tmp/nightowls_peer6001 \
PEER_PORT=6001 PEER_IP=127.0.0.1 \
TRACKER_URL=http://127.0.0.1:5000 \
  .venv/bin/python -m peer.app
```

### Env vars

| Var | Default | Used by |
|-----|---------|---------|
| `TRACKER_PORT` | `5000` | tracker |
| `TRACKER_DB` | `tracker/tracker.db` | tracker |
| `TRACKER_URL` | `http://127.0.0.1:5000` | peer |
| `PEER_PORT` | `6001` | peer |
| `PEER_IP` | `127.0.0.1` | peer (announced to tracker) |
| `PEER_HOST` | `0.0.0.0` | peer bind |
| `PEER_DATA_DIR` | `peer/data` | peer |

### Example curl (tracker)

```bash
curl -sS -X POST http://127.0.0.1:5000/register_peer \
  -H 'Content-Type: application/json' \
  -d '{"ip":"127.0.0.1","port":6001}'

curl -sS -X POST http://127.0.0.1:5000/upload_metadata \
  -H 'Content-Type: application/json' \
  -d '{"filename":"demo.txt","file_hash":"abc","file_size":512000,"chunk_hashes":["h0","h1"],"peer_ip":"127.0.0.1","peer_port":6001}'

curl -sS http://127.0.0.1:5000/files
curl -sS http://127.0.0.1:5000/peers/1
curl -sS -X POST http://127.0.0.1:5000/peer_has_chunk \
  -H 'Content-Type: application/json' \
  -d '{"peer_ip":"127.0.0.1","peer_port":6002,"file_id":1,"chunk_index":0}'
```

### Example curl (peer chunk fetch — Step 3)

```bash
curl -sS http://127.0.0.1:6001/health
curl -sS -o /tmp/chunk0.bin http://127.0.0.1:6001/chunk/1/0
curl -sS -o /tmp/chunk1.bin http://127.0.0.1:6001/chunk/1/1
# missing → 404
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:6001/chunk/1/99
```

---

## `shared/utils.py` API (do not reinvent)

- `CHUNK_SIZE = 256 * 1024`
- `sha256_bytes(data)`, `sha256_file(path)`
- `chunk_file(path) → (file_hash, file_size, chunk_hashes)`
- `iter_file_chunks`, `read_chunk_from_file`, `write_chunks_to_file`
- `verify_chunk(data, expected_hash)`, `verify_file(path, expected_hash)`

---

## SQLite schema (tracker)

- **peers** — `id`, `ip`, `port` (UNIQUE), `registered_at`
- **files** — `id`, `filename`, `file_hash` (UNIQUE), `file_size`, `chunk_count`, `created_at`
- **chunks** — `file_id`, `chunk_index`, `chunk_hash` (UNIQUE per file+index)
- **peer_chunks** — `(peer_id, file_id, chunk_index)` — who has what

On `upload_metadata`, the uploading peer is registered as having **all** chunks.

---

## `peer/store.py` API

- `ChunkStore(data_dir)`
- `save_chunk(file_id, chunk_index, data)`
- `load_chunk(file_id, chunk_index) → bytes | None`
- `has_chunk(file_id, chunk_index) → bool`
- `import_file(source, file_id, filename=None) → meta dict`

---

## Next step instructions (for the next harness)

### Step 4 — Download logic (`peer/swarm.py`) — **DO THIS NEXT**

1. Implement swarm download in `peer/swarm.py`:
   - Fetch manifest: `GET {tracker}/files/<file_id>` (includes `chunk_hashes`).
   - Fetch peer map: `GET {tracker}/peers/<file_id>`.
   - For each missing chunk: pick a peer that lists that chunk (round-robin or random).
   - `GET http://{ip}:{port}/chunk/<file_id>/<chunk_index>`
   - `verify_chunk` against manifest; on failure try another peer.
   - `store.save_chunk(...)` then `POST {tracker}/peer_has_chunk`.
   - When all chunks present: `write_chunks_to_file` into `complete/<file_id>/`.
2. Wire a minimal CLI or Flask route to trigger download (CLI is fine for Step 4; UI is Step 6).
3. Curl/CLI test with tracker + 2 peers (one seeder with chunks, one empty downloader).
4. **Update this HANDOFF.md**, then pause for human review.

### Step 5 — Upload/seed

- `chunk_file` / `store.import_file` → `POST /upload_metadata` → keep serving chunks.

### Steps 6–7 — UI + progress polling

- Only after CLI/curl proves the swarm works.
- CSS variables: `--bg-primary: #0d0d0d`, `--accent: #7c3aed` (or similar).
- Poll `/progress/<file_id>` every 1s.

### Final polish

- Seed script for 2–3 dummy files.
- Multi-peer localhost demo (ports e.g. 5000 tracker, 6001/6002/6003 peers).

---

## Working agreements with the human

- Work in the current folder; create files and use terminal for `pip` (via `.venv`).
- Follow BUILD ORDER **step by step**.
- **Pause after each step** for review before continuing.
- **Update `HANDOFF.md` after every step** so other harnesses can resume.

---

## Verification log

| Check | Result |
|-------|--------|
| `test_utils_smoke.py` | OK — multi-chunk hash/reassemble |
| Tracker curl suite (register, upload, files, peers, peer_has_chunk) | ALL PASSED |
| Peer `/health` | OK |
| Peer `GET /chunk/1/0` and `/chunk/1/1` | OK — sizes 262144 + 137856; SHA-256 matched seed hashes |
| Peer missing chunk | HTTP 404 |
| Peer auto-register with tracker on startup | OK |

---

## Resume command for next agent

> Read `HANDOFF.md`. Steps 1–3 are done. Implement **Step 4 only** (`peer/swarm.py` download: manifest → fetch chunks from peers → verify → save → `peer_has_chunk` → reassemble). Curl/CLI test with tracker + 2 peers. Update `HANDOFF.md`, then pause for review.
