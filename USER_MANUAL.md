# NightOwls — User Manual

Decentralized LAN file sharing for campus networks. One **tracker** keeps the catalog; each student runs a **peer** that can seed and download files in 256 KB chunks with SHA-256 verification.

---

## Table of contents

1. [What you get](#1-what-you-get)
2. [System requirements](#2-system-requirements)
3. [Install](#3-install)
4. [Start everything at once](#4-start-everything-at-once)
5. [Using the web UI](#5-using-the-web-ui)
6. [Multi-peer demo (localhost)](#6-multi-peer-demo-localhost)
7. [Command-line usage](#7-command-line-usage)
8. [Running on a real LAN](#8-running-on-a-real-lan)
9. [How it works](#9-how-it-works)
10. [Configuration (environment variables)](#10-configuration-environment-variables)
11. [HTTP API reference](#11-http-api-reference)
12. [Data on disk](#12-data-on-disk)
13. [Troubleshooting](#13-troubleshooting)
14. [FAQ](#14-faq)

---

## 1. What you get

| Piece | Role |
|-------|------|
| **Tracker** | Single registry: filenames, hashes, chunk lists, which peers hold which chunks |
| **Peer** | Your node: web UI + chunk server + upload/download client |
| **Shared utils** | Split files into 256 KB pieces and compute SHA-256 |

Typical flow:

1. Peer A uploads a file → chunks stored locally → metadata sent to tracker.
2. Peer B opens Browse → picks the file → fetches chunks from A (and any other seeders).
3. Each chunk is verified; B reassembles the file and announces “I have these chunks” so others can pull from B too.

---

## 2. System requirements

- **OS:** Linux, macOS, or Windows (WSL recommended on Windows)
- **Python:** 3.10 or newer
- **Network:** localhost for demos; same LAN/Wi‑Fi for a classroom demo
- **Browser:** any modern browser (Chrome, Firefox, Edge, Safari)

Ports used by default:

| Port | Service |
|------|---------|
| 5000 | Tracker |
| 6001+ | Peer UIs / chunk servers |

---

## 3. Install

No separate install step is required for the plug-and-play launchers — they create `.venv` and install Flask on first run.

Optional manual setup:

```bash
cd NightOwls-26
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

---

## 3b. Plug and play (server + client)

**Machine A — tracker:**

```bash
./server
```

Copy the printed **Share this:** URL (e.g. `http://192.168.1.10:5000`).

**Same machine or Machine B — peer UI:**

```bash
./client
# or, pointing at a remote tracker:
./client http://192.168.1.10:5000
```

Open the printed peer UI URL (usually http://127.0.0.1:6001/). Upload on one peer, browse/download on another.

Windows: `server.bat` / `client.bat`.

---

## 4. Start everything at once (local multi-peer demo)

```bash
./scripts/run.sh
```

What it does:

1. Ensures `.venv` + Flask are installed  
2. Frees ports 5000 / 6001–6003 if leftover processes hold them  
3. Starts the tracker  
4. Starts **3 peers** (ports 6001, 6002, 6003)  
5. Prints URLs and waits — `Ctrl+C` stops all processes  

### Useful flags

| Flag | Meaning |
|------|---------|
| `--seed` | Create two demo files and seed them on peer 1 |
| `--peers N` | Start `N` peers instead of 3 (default 3, max 8) |
| `--no-free-ports` | Do not kill processes already bound to demo ports |
| `--help` | Show help |

Examples:

```bash
./scripts/run.sh --seed
./scripts/run.sh --peers 2
./scripts/run.sh --seed --peers 3
```

### Manual start (separate terminals)

**Tracker:**

```bash
TRACKER_DB=/tmp/nightowls_tracker.db \
  .venv/bin/python -c "
from tracker.app import create_app, app
create_app()
app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)
"
```

**Peer:**

```bash
PEER_DATA_DIR=/tmp/nightowls_peer6001 \
PEER_PORT=6001 PEER_IP=127.0.0.1 \
TRACKER_URL=http://127.0.0.1:5000 \
  .venv/bin/python -m peer.app
```

Open http://127.0.0.1:6001/

---

## 5. Using the web UI

Each peer serves its own UI (e.g. http://127.0.0.1:6001/).

### Browse

- Home page lists every file registered on the tracker as cards.
- Each card shows **filename**, **size**, **seeder count**, and **chunk count**.
- Click **Download** to open the progress page for that file.

If the list is empty, no one has seeded yet — use **Upload**, or run `./scripts/run.sh --seed`.

### Upload / seed

1. Open **Upload**.
2. Drag a file onto the drop zone (or click to choose).
3. Click **Upload & seed**.
4. The peer chunks the file (256 KB), hashes it, registers metadata with the tracker, and keeps serving chunks.

After a successful upload, refresh **Browse** on any peer to see the new card.

### Download

1. From Browse, open a file’s download page.
2. Click **Start download**.
3. Progress updates about once per second:
   - percent complete  
   - chunks received  
   - number of peers being used as sources  
4. When status is **complete**, the file is under that peer’s data directory (see [Data on disk](#12-data-on-disk)).

**Tip:** Upload on peer **6001**, then open peer **6002**’s UI to download — that proves peer-to-peer transfer.

---

## 6. Multi-peer demo (localhost)

Simulates three students on one machine:

```bash
./scripts/run.sh --seed
```

Then:

1. Open http://127.0.0.1:6001/ — demo files should appear (if `--seed` was used).  
2. Open http://127.0.0.1:6002/ — same catalog from the tracker.  
3. Download a file on 6002; watch progress hit 100%.  
4. Optionally kill peer 6001 mid-download on a larger file while 6003 also seeds — remaining peers should still finish if they hold enough chunks.

---

## 7. Command-line usage

Activate the project environment implicitly via `.venv/bin/python`.

### Upload (seed)

```bash
.venv/bin/python -m peer.swarm upload \
  --path /path/to/file.bin \
  --tracker http://127.0.0.1:5000 \
  --data-dir /tmp/nightowls_peer6001 \
  --peer-ip 127.0.0.1 \
  --peer-port 6001 \
  --filename my_demo.bin
```

Then start (or keep running) the peer on that same `--data-dir` / port so others can fetch chunks.

### Download

```bash
.venv/bin/python -m peer.swarm download \
  --file-id 1 \
  --tracker http://127.0.0.1:5000 \
  --data-dir /tmp/nightowls_peer6002 \
  --peer-ip 127.0.0.1 \
  --peer-port 6002
```

`--file-id` is the numeric id from the tracker (`GET http://127.0.0.1:5000/files`).

### Smoke test (chunking utils)

```bash
.venv/bin/python test_utils_smoke.py
```

---

## 8. Running on a real LAN

1. Pick one machine as the **tracker**. Note its LAN IP (e.g. `192.168.1.10`).
2. Start the tracker bound to all interfaces:

   ```bash
   TRACKER_DB=/tmp/nightowls_tracker.db \
     .venv/bin/python -c "
   from tracker.app import create_app, app
   create_app()
   app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
   "
   ```

3. On each student machine, start a peer with:

   | Variable | Value |
   |----------|--------|
   | `TRACKER_URL` | `http://192.168.1.10:5000` |
   | `PEER_IP` | That machine’s LAN IP (e.g. `192.168.1.42`) |
   | `PEER_PORT` | Free port (e.g. `6001`) |
   | `PEER_HOST` | `0.0.0.0` (default) so others can reach `/chunk/...` |
   | `PEER_DATA_DIR` | Local folder for chunks |

   Example:

   ```bash
   PEER_DATA_DIR="$HOME/nightowls-data" \
   PEER_PORT=6001 \
   PEER_IP=192.168.1.42 \
   PEER_HOST=0.0.0.0 \
   TRACKER_URL=http://192.168.1.10:5000 \
     .venv/bin/python -m peer.app
   ```

4. Students open `http://<their-lan-ip>:6001/` (or localhost if using the UI only on their own machine).

**Firewall:** allow inbound TCP on the tracker port (5000) and each peer port (6001, …).

**Important:** `PEER_IP` must be an address other peers can reach — not `127.0.0.1` when testing across machines.

---

## 9. How it works

### Chunking

- Files are split into **256 KB** pieces (`shared/utils.py`).
- Each chunk and the whole file get a **SHA-256** hex digest.
- The tracker stores the ordered list of chunk hashes (the **manifest**).

### Upload path

1. Hash/chunk the file.  
2. `POST /upload_metadata` on the tracker (peer is marked as having every chunk).  
3. Save chunks under the peer’s data directory.  
4. Peer keeps serving `GET /chunk/<file_id>/<chunk_index>`.

### Download path

1. `GET /files/<id>` → manifest.  
2. `GET /peers/<id>` → who has which chunks.  
3. For each missing chunk, pick a peer (round-robin), fetch bytes, **verify hash**.  
4. On success: save locally + `POST /peer_has_chunk`.  
5. When all chunks exist: reassemble into `complete/<file_id>/<filename>`.

If one seeder goes offline, other peers that already hold pieces can still supply them.

---

## 10. Configuration (environment variables)

### Tracker

| Variable | Default | Description |
|----------|---------|-------------|
| `TRACKER_PORT` | `5000` | Listen port (when using `python -m tracker.app`) |
| `TRACKER_HOST` | `0.0.0.0` | Bind address |
| `TRACKER_DB` | `tracker/tracker.db` | SQLite database path |

### Peer

| Variable | Default | Description |
|----------|---------|-------------|
| `TRACKER_URL` | `http://127.0.0.1:5000` | Tracker base URL |
| `PEER_PORT` | `6001` | This peer’s port |
| `PEER_IP` | `127.0.0.1` | Address announced to the tracker |
| `PEER_HOST` | `0.0.0.0` | Bind address for the peer server |
| `PEER_DATA_DIR` | `peer/data` | Local chunk / complete / meta store |

---

## 11. HTTP API reference

### Tracker

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/register_peer` | Body: `{ "ip", "port" }` |
| `POST` | `/upload_metadata` | Body: `{ "filename", "file_hash", "file_size", "chunk_hashes", "peer_ip", "peer_port" }` |
| `GET` | `/files` | List files |
| `GET` | `/files/<id>` | Manifest + metadata |
| `GET` | `/peers/<file_id>` | Peers and chunk indexes they hold |
| `POST` | `/peer_has_chunk` | Body: `{ "peer_ip", "peer_port", "file_id", "chunk_index" }` |

### Peer

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/` | Browse UI |
| `GET` | `/upload` | Upload UI |
| `GET` | `/download/<file_id>` | Download progress UI |
| `GET` | `/health` | Liveness JSON |
| `GET` | `/chunk/<file_id>/<chunk_index>` | Raw chunk bytes |
| `GET` | `/api/files` | Proxy of tracker file list |
| `POST` | `/api/upload` | Multipart field `file` |
| `POST` | `/api/download/<file_id>` | Start background download |
| `GET` | `/progress/<file_id>` | Progress JSON (polled every ~1s by the UI) |

Example progress payload:

```json
{
  "file_id": 1,
  "status": "complete",
  "percent": 100.0,
  "chunks_have": 2,
  "chunks_total": 2,
  "peers_known": 1,
  "path": "/tmp/nightowls_peer6002/complete/1/demo.bin"
}
```

---

## 12. Data on disk

Each peer’s `PEER_DATA_DIR` looks like:

```
<data_dir>/
  chunks/<file_id>/<chunk_index>.bin
  complete/<file_id>/<filename>
  meta/<file_id>.json
  _uploads/                 # temporary browser uploads
```

Downloaded files are in `complete/<file_id>/`.

The tracker SQLite file is wherever `TRACKER_DB` points (the run script uses `/tmp/nightowls_tracker.db` by default).

---

## 13. Troubleshooting

| Problem | What to try |
|---------|-------------|
| `Address already in use` | Stop old processes, or re-run `./scripts/run.sh` (it frees demo ports). `ss -ltnp \| grep -E '5000\|6001'` |
| Browse shows tracker error | Tracker not running or wrong `TRACKER_URL` |
| Download stuck at 0% | No seeder online; start the peer that uploaded, with the **same** data dir it used when seeding |
| Download hash / incomplete errors | Seeder missing chunks; re-upload, or check `chunks/` under the seeder’s data dir |
| Works on localhost, fails on LAN | Set `PEER_IP` to the real LAN IP; open firewall; use `PEER_HOST=0.0.0.0` |
| Empty file rejected | Tracker requires a non-empty `chunk_hashes` list — seed a non-empty file |
| UI styles missing | Confirm `/static/style.css` loads; run from project root via `python -m peer.app` |

Logs for the all-in-one script go under `/tmp/nightowls_run/` (tracker and peer stdout/stderr).

---

## 14. FAQ

**Do I need JavaScript frameworks?**  
No. The UI is Flask templates + CSS + a small vanilla JS file for upload and progress polling.

**Is the tracker a single point of failure?**  
For discovery, yes — if the tracker is down, new peers cannot learn the catalog. Already-known peers could still exchange chunks if you pointed them manually; this project always uses the tracker for manifests and peer maps.

**Can two peers use the same port?**  
No. Each peer needs a unique `PEER_PORT` (and usually its own `PEER_DATA_DIR`).

**Where is Step 7 / polish?**  
Basic 1-second progress polling is already in the UI. See `HANDOFF.md` for remaining polish and demo seed-script notes.

**Is this production BitTorrent?**  
No. It is an educational LAN demo: HTTP chunks, Flask, SQLite — not the BitTorrent wire protocol.

---

## Quick reference card

```text
Install:   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
Run all:   ./scripts/run.sh --seed
UI:        http://127.0.0.1:6001  (also :6002, :6003)
Stop:      Ctrl+C in the run.sh terminal
Docs:      README.md  ·  USER_MANUAL.md  ·  HANDOFF.md
```
