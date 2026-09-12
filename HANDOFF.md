# NightOwls-26 — Build Handoff Report

**Last updated:** 2026-09-12 (after Step 7)  
**Project:** Decentralized LAN file-sharing (BitTorrent-style tracker + peers)  
**Workspace:** `/home/mushaam/Desktop/cc/NightOwls-26`

> **AI agents:** start with [`AGENTS.md`](./AGENTS.md) (dense vision + architecture + APIs + next step). This file is the step-by-step build log.

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

**UI direction:** deep black/charcoal, accent `#7c3aed`, Inter via Google Fonts, card grid, CSS variables, 12–16px radius.

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
| GET | `/files/<id>` | Done |
| GET | `/peers/<file_id>` | Done |
| POST | `/peer_has_chunk` | Done |

### Peer endpoints / CLI

| Method | Path | Status |
|--------|------|--------|
| GET | `/health` | Done |
| GET | `/chunk/<file_id>/<chunk_index>` | Done |
| GET | `/` | **Done (Step 6)** — browse cards |
| GET | `/upload` | **Done (Step 6)** |
| GET | `/download/<file_id>` | **Done (Step 6)** |
| GET | `/api/files` | **Done (Step 6)** |
| POST | `/api/upload` | **Done (Step 6)** — multipart |
| POST | `/api/download/<file_id>` | **Done (Step 6)** — background thread |
| GET | `/progress/<file_id>` | **Done (Step 7)** — stable contract + warnings |
| CLI | `python -m peer.swarm upload\|download` | Done (Steps 4–5) |

---

## BUILD ORDER (checklist)

| # | Step | Status |
|---|------|--------|
| 1 | Scaffold folders + `shared/utils.py` chunking/hashing | **DONE** |
| 2 | Tracker Flask app + SQLite models; curl-tested | **DONE** |
| 3 | Peer chunk-serving endpoint; manual P2P chunk fetch | **DONE** |
| 4 | Peer download logic (manifest → fetch → verify → reassemble) | **DONE** |
| 5 | Peer upload/seed logic (chunk + hash + register with tracker) | **DONE** |
| 6 | CRED/Spotify frontend (templates + CSS) | **DONE** |
| 7 | Polling progress bars (`fetch` every 1s → `/progress/<file_id>`) | **DONE** |

### Demo requirements (keep in mind while building)

- Tracker + **3+ peers** on localhost, different ports.  
- Killing one peer mid-download must not block others.  
- Seed script: 2–3 dummy files pre-seeded for instant demo content.

---

## Current tree

```
NightOwls-26/
├── HANDOFF.md
├── README.md
├── requirements.txt          # Flask==3.1.3
├── test_utils_smoke.py
├── .venv/
├── scripts/
│   └── seed_peer_chunks.py
├── shared/
│   ├── __init__.py
│   └── utils.py
├── tracker/
│   ├── __init__.py
│   ├── app.py
│   └── models.py
└── peer/
    ├── __init__.py
    ├── app.py                # chunk server + UI routes + APIs (Step 6)
    ├── store.py
    ├── swarm.py              # upload + download
    ├── templates/
    │   ├── index.html        # Spotify-style browse grid
    │   ├── upload.html       # drag-drop seed
    │   └── download.html     # progress view
    └── static/
        ├── style.css         # dark CRED/Spotify theme
        └── script.js         # upload + 1s progress polling
```

### Peer local storage layout (`PEER_DATA_DIR`)

```
<data_dir>/
  chunks/<file_id>/<chunk_index>.bin
  complete/<file_id>/<filename>
  meta/<file_id>.json
  _uploads/                   # temp multipart uploads
```

---

## How to run (UI demo)

```bash
cd /home/mushaam/Desktop/cc/NightOwls-26

# Terminal 1 — tracker
TRACKER_DB=/tmp/nightowls_tracker.db TRACKER_PORT=5000 \
  .venv/bin/python -c "
from tracker.app import create_app, app
create_app()
app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)
"

# Terminal 2 — peer UI (open http://127.0.0.1:6001/)
PEER_DATA_DIR=/tmp/nightowls_peer6001 \
PEER_PORT=6001 PEER_IP=127.0.0.1 \
TRACKER_URL=http://127.0.0.1:5000 \
  .venv/bin/python -m peer.app

# Optional Terminal 3 — second peer UI on :6002
PEER_DATA_DIR=/tmp/nightowls_peer6002 \
PEER_PORT=6002 PEER_IP=127.0.0.1 \
TRACKER_URL=http://127.0.0.1:5000 \
  .venv/bin/python -m peer.app
```

Upload on peer 6001 → browse/download on peer 6002.

### CLI still works

```bash
.venv/bin/python -m peer.swarm upload --path FILE --data-dir DIR --peer-port PORT
.venv/bin/python -m peer.swarm download --file-id N --data-dir DIR --peer-port PORT
```

### Env vars

| Var | Default | Used by |
|-----|---------|---------|
| `TRACKER_PORT` | `5000` | tracker |
| `TRACKER_DB` | `tracker/tracker.db` | tracker |
| `TRACKER_URL` | `http://127.0.0.1:5000` | peer |
| `PEER_PORT` | `6001` | peer |
| `PEER_IP` | `127.0.0.1` | peer |
| `PEER_HOST` | `0.0.0.0` | peer bind |
| `PEER_DATA_DIR` | `peer/data` | peer |

---

## `peer/swarm.py` API (Steps 4–5)

- `upload_file(...)` / `download_file(...)` — see prior notes
- CLI subcommands: `upload`, `download`

---

## UI notes (Steps 6–7)

- Theme: `--bg-primary: #0d0d0d`, `--accent: #7c3aed`, Inter, card grid, hover lift
- Browse: server-rendered cards from tracker `/files`
- Upload: drag-drop → `POST /api/upload` (multipart) → swarm `upload_file`
- Download: page auto-starts → `POST /api/download/<id>` background thread → JS polls `/progress/<id>` every 1s
- Progress store: in-memory `app.config["DOWNLOADS"]` + local chunk counts from `ChunkStore`
- `/progress/<file_id>` always returns: `status`, `percent`, `chunks_have`, `chunks_total`, `peers_known`, `path`, `error` (+ optional `warning`)
- Mid-download peer loss: swarm emits `no_peers` / `chunk_failed` → UI shows amber warning, keeps polling
- Peer count: live bump animation when `peers_known` changes

---

## Next step instructions (for the next harness)

### Final polish — **DO THIS NEXT** (optional demo niceties)

Steps 1–7 are complete. Remaining demo polish:

1. Seed script for 2–3 dummy files (wrap `peer.swarm upload`) — check `scripts/` first; may already exist.
2. Multi-peer localhost demo (5000 + 6001/6002/6003) — see `scripts/run.sh`.
3. Prefer `debug=False` / no reloader for tracker in demos (port conflicts).
4. **Update this HANDOFF.md**, then pause

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
| Steps 1–5 backend | OK (see prior entries) |
| `GET /`, `/upload`, `/download/1` | 200 — templates render |
| `GET /static/style.css`, `script.js` | 200 |
| `POST /api/upload` | 201 — file registered + stored |
| Index shows uploaded card | OK |
| Peer2 `POST /api/download/1` + `/progress/1` | complete @ 100%, hash match |
| Step 7 `/progress` idle contract | OK — all 7 fields present; `error`/`path` null |
| Step 7 warning + error jobs | OK — `warning` surfaced; `error` status preserved |
| Download UI auto-start + warn class | OK (script.js + style.css) |

---

## Resume command for next agent

> Read `HANDOFF.md`. Steps 1–7 are done. Do **final polish only** if needed (seed/demo scripts, multi-peer run). Update `HANDOFF.md`, then pause for review.
