# AGENTS.md — NightOwls-26 (AI resume context)

> **Read this first.** Dense source of truth for vision, architecture, status, and how to continue.  
> Deeper docs: `prompt.txt` (spec), `HANDOFF.md` (step log), `ARCHITECTURE.md` (diagrams), `USER_MANUAL.md` (ops), `README.md` (quickstart).  
> **Update this file + `HANDOFF.md` after every completed step.**

---

## Vision

Educational **BitTorrent-style LAN file sharer** for a college network: one central **tracker** (catalog + peer↔chunk map), many **peer** nodes (seed + download + serve chunks). Not real BitTorrent wire protocol — HTTP + Flask + SQLite + SHA-256 chunk verify.

**User experience:** dark CRED/Spotify UI on each peer — browse cards → upload/seed → download with live % / peer-count polling.

**Demo bar:** tracker + **3+ peers** on localhost (different ports); kill one peer mid-download → others still finish; seed script with 2–3 dummy files.

---

## Status (2026-09-12)

| Step | What | State |
|------|------|-------|
| 1 | `shared/utils.py` 256KB + SHA-256 | DONE |
| 2 | Tracker Flask + SQLite | DONE |
| 3 | Peer `GET /chunk/...` | DONE |
| 4 | `swarm.download_file` | DONE |
| 5 | `swarm.upload_file` | DONE |
| 6 | UI templates/CSS/JS | DONE |
| 7 | `/progress` contract + poll polish + auto-start | DONE |

**NEXT:** final demo polish only — verify/extend seed + multi-peer launcher (`scripts/run.sh --seed` exists); no new architecture. Pause for human review after changes.

**Recent UX:** browse **card/list views** + schema-driven **sort** (`peer/static/file-catalog.js`).  
**Tracker portal:** bare admin UI at `http://<tracker>/portal` — inventory + audit + CSV export.  
**Peer file manager:** `/library` — local `library.db`, startup SHA-256 verify, zombie clear, View/Copy.

**Branch:** `step7` (tracks build step naming; Steps 1–7 complete).

---

## Hard constraints (do not violate)

| Layer | Rule |
|-------|------|
| Backend | Flask only (`Flask==3.1.3` in `requirements.txt`) |
| Frontend | HTML/CSS + **vanilla JS** (polling only). No React/Vue/Bootstrap |
| DB | SQLite on tracker |
| Chunks | **256 KB** (`shared.utils.CHUNK_SIZE`), SHA-256 per chunk + whole file |
| Theme | `--bg-primary:#0d0d0d` `--accent:#7c3aed` Inter, cards, 12–16px radius |
| Env | Use `.venv/` (PEP 668). Never skip BUILD ORDER; pause after each step unless told |
| Scope | Educational LAN demo — no DHT, no real BT protocol, no prod hardening unless asked |

---

## Architecture (mental model)

```
[Peer UI] → [peer/app.py] → [swarm.py] ⇄ HTTP JSON ⇄ [tracker/app.py + models.py + SQLite]
                ↓                ↓
           templates/        [ChunkStore]
           static/               ↓
                         data/chunks|complete|meta
                ↓
         GET /chunk/<fid>/<i>  ← other peers fetch bytes here
```

**Flows**
1. **Seed:** split→hash→`POST /upload_metadata`→store chunks→serve `/chunk`→`POST /peer_has_chunk` for all.
2. **Download:** `GET /files/<id>` + `GET /peers/<id>` → RR fetch `/chunk` → verify → save → report have → reassemble `complete/<id>/<name>` → whole-file hash check.
3. **UI download:** `POST /api/download/<id>` (thread) → JS polls `GET /progress/<id>` every **1s**.

**Resilience:** refresh peer map periodically; try multiple peers per chunk; mid-fail → warning UI, other peers continue.

---

## Repo map

```
NightOwls-26/
├── AGENTS.md              ← YOU ARE HERE
├── HANDOFF.md             step checklist + resume blurb
├── prompt.txt             original assignment
├── ARCHITECTURE.md        mermaid diagrams
├── USER_MANUAL.md / README.md
├── requirements.txt       Flask==3.1.3
├── test_utils_smoke.py
├── scripts/
│   ├── run.sh             tracker + N peers; --seed
│   ├── seed_peer_chunks.py
│   └── start_{server,client}.{sh,bat}
├── shared/utils.py        CHUNK_SIZE, chunk_file, verify_*, sha256_*
├── tracker/
│   ├── app.py             HTTP API + /portal admin UI
│   ├── models.py          peers, files, chunks, peer_chunks, audit_log
│   ├── templates/         portal_*.html
│   └── static/portal.css  bare admin styles
└── peer/
    ├── app.py             UI + /chunk + /api/* + /progress + /library + DOWNLOADS{}
    ├── swarm.py           upload_file / download_file (+ CLI)
    ├── store.py           ChunkStore disk layout
    ├── inventory.py       LocalInventory — library.db + verify/zombies
    ├── templates/         index | upload | download | library
    └── static/            style.css | script.js | file-catalog.js
```

Helpers: `./server` `./client` (or `.bat`) wrap common launches.

---

## Disk layout (`PEER_DATA_DIR`)

```
<data>/
  chunks/<file_id>/<chunk_index>.bin
  complete/<file_id>/<filename>     # verified whole file only
  meta/<file_id>.json
  library.db                        # local file manager inventory
  _uploads/                         # temp multipart
```

---

## Tracker SQLite

`peers(id, ip, port UNIQUE)` · `files(id, filename, file_hash UNIQUE, file_size, chunk_count)` · `chunks(file_id, chunk_index, chunk_hash)` · `peer_chunks(peer_id, file_id, chunk_index)` PK composite · `audit_log(id, created_at, action, actor, detail)`.

Env: `TRACKER_PORT=5000` `TRACKER_DB=tracker/tracker.db` `TRACKER_SECRET` (Flask flash sessions; default dev key)

### Tracker HTTP

| Method | Path | Body / notes |
|--------|------|----------------|
| POST | `/register_peer` | `{ip,port}` · audits `peer_register` |
| POST | `/upload_metadata` | `{filename,file_hash,file_size,chunk_hashes[],peer_ip,peer_port}` · audits `file_register`/`file_update` |
| GET | `/files` | list + seeder hints |
| GET | `/files/<id>` | manifest + `chunk_hashes` |
| GET | `/peers/<file_id>` | `[{ip,port,chunks:[…]}]` |
| POST | `/peer_has_chunk` | `{peer_ip,peer_port,file_id,chunk_index}` · **not** audited (noise) |
| POST/DELETE | `/files/<id>/unshare` | remove from catalog only (peer disks untouched); audits `file_unshare` |
| GET | `/` | redirect → `/portal` |
| GET | `/portal` | home + stats + recent audit |
| GET | `/portal/inventory` | catalog table: rename / delete; peer list |
| POST | `/portal/inventory/<id>/rename` | form `filename` |
| POST | `/portal/inventory/<id>/delete` | **unshare** — remove file from catalog only (+cascade chunks/claims); peers keep copies |
| GET | `/portal/audit` | audit log (`?limit=`) |
| GET | `/portal/export/inventory.csv` | CSV download |
| GET | `/portal/export/audit.csv` | CSV download |
| GET | `/portal/export/peers.csv` | CSV download |

Portal UI is intentionally plain (not peer CRED theme). No auth — LAN demo only.

---

## Peer HTTP / CLI

Env: `PEER_PORT=6001` `PEER_IP=127.0.0.1` `PEER_HOST=0.0.0.0` `PEER_DATA_DIR=peer/data` `TRACKER_URL=http://127.0.0.1:5000`

| Method | Path | Role |
|--------|------|------|
| GET | `/health` | diagnostics |
| GET | `/chunk/<fid>/<i>` | bytes; rejects size/hash mismatch |
| GET | `/` `/upload` `/download/<fid>` `/library` | UI (Files = local manager) |
| GET | `/api/files` | JSON catalog |
| POST | `/api/upload` | multipart `file` → `upload_file` → library register |
| POST | `/api/download/<fid>` | start bg thread; 202; idempotent if active |
| GET | `/progress/<fid>` | poll contract (below) |
| POST | `/api/library/verify` | re-check all local files (size + SHA-256) |
| POST | `/api/library/clear-zombies` | drop missing/corrupt DB rows + leftover complete/meta |
| GET | `/api/library/<fid>/copy` | Save-As download (`Content-Disposition: attachment`) |
| POST | `/api/library/<fid>/open` | OS default open (`xdg-open` / `open` / `startfile`) |
| POST | `/api/library/<fid>/unshare` | ask tracker to drop catalog entry; **keep** local library/disk |
| POST | `/api/library/<fid>/delete` | remove library row + wipe `complete/` `meta/` `chunks/` |

CLI: `python -m peer.swarm upload --path F --data-dir D --peer-port P` · `… download --file-id N …`

### `/progress/<fid>` contract (always present)

```json
{
  "file_id": 1,
  "status": "idle|starting|chunk_ok|skip_existing|no_peers|chunk_failed|complete|error",
  "percent": 0.0,
  "chunks_have": 0,
  "chunks_total": 0,
  "peers_known": 0,
  "path": null,
  "error": null,
  "warning": null
}
```

`path` only when verified complete. `warning` for mid-download peer loss (UI amber; keep polling). In-memory: `app.config["DOWNLOADS"]`.

---

## Key code APIs

**`shared/utils.py`:** `CHUNK_SIZE=262144` · `chunk_file` · `verify_chunk` · `verify_file` · `write_chunks_to_file` · `sha256_*`

**`peer.store.ChunkStore`:** `save_chunk` `load_chunk` `has_chunk(..., expected_hash=, expected_size=)` `delete_chunk` `clear_incomplete` `is_verified_complete` `load_meta` · dirs under `data_dir`

**`peer.inventory.LocalInventory`:** SQLite `library.db` · `register` · `verify_all` (startup + manual) · `clear_zombies` · `delete_file` (DB + disk) · `resolve_path` · statuses `ok|missing|corrupt`

**`peer.swarm`:**  
- `upload_file(source, tracker_url, store, peer_ip, peer_port, filename=)`  
- `download_file(..., on_progress=callable|None, refresh_peers=True)` — emits progress dicts; raises `DownloadError` if missing chunks  
- Progress statuses: `starting` `skip_existing` `chunk_ok` `no_peers` `chunk_failed` `complete`

**`peer.app.create_app(...)`:** builds store + inventory, **`verify_all()` on startup**, registers with tracker (unless `register=False`), sets config keys.

**`tracker.models`:** `init_db` `register_peer` `upload_metadata` `list_files` `get_file` `peers_for_file` `peer_has_chunk` `log_audit` `list_audit` `list_peers` `portal_stats` `rename_file` `delete_file`

---

## UI notes

- Browse: server-rendered cards from tracker `/files` + **live client search**
- **Views:** Cards (default) ↔ List — toggle `#view-toggle`; preference in `localStorage` key `nightowls.browse.view`
- **Sort:** schema-driven — dropdown `#browse-sort` + clickable list headers; preference `nightowls.browse.sort` (`{field,dir}`)
- **Catalog schema:** `FILE_FIELDS` in `peer/static/file-catalog.js` — single place to add metadata columns
  - Add field: (1) `data-*` on `.card` in `index.html` (2) append object to `FILE_FIELDS` with `list` / `sortable` / `searchable`
  - Optional fields already defined but `list:false`: `hash`, `created` — flip `list:true` to show
- Search: ranks by name/prefix/tokens/id/ext/hash; IME-safe `input`; `/` focuses, Esc clears; match highlight
- Upload: drag-drop → `POST /api/upload`
- Download page: **auto-starts** unless already complete; button = start/retry; poll 1s; peer-count bump CSS (`.live-counter.bump`); `.status.warn` for peer failures
- **Files (`/library`):** local downloads/seeds; zombie rows; **View** / **Copy** / **Unshare** (tracker catalog only) / **Delete local** (DB + disk); Re-verify + Clear zombies
- **Already-have download:** `GET /download/<id>` (and `POST /api/download/<id>`) check local library by file_id or SHA-256; if healthy copy exists → redirect `/library?focus=<id>` (use `?force=1` to bypass)
- Files: `peer/templates/index.html` `library.html` `peer/static/file-catalog.js` `script.js` `style.css` · `peer/inventory.py`

---

## Run (minimal)

```bash
cd /home/mushaam/Desktop/cc/NightOwls-26
# one-shot demo
./scripts/run.sh --seed          # :5000 + :6001.. UI http://127.0.0.1:6001
# tracker portal
# http://127.0.0.1:5000/portal

# or manual
TRACKER_DB=/tmp/t.db TRACKER_PORT=5000 .venv/bin/python -c \
  "from tracker.app import create_app,app; create_app(); app.run('127.0.0.1',5000,False,use_reloader=False)"
PEER_DATA_DIR=/tmp/p6001 PEER_PORT=6001 TRACKER_URL=http://127.0.0.1:5000 .venv/bin/python -m peer.app
```

Smoke: `test_utils_smoke.py` · progress idle must include all 7 contract keys.

---

## Agent work rules

1. Read this + `HANDOFF.md` before coding.
2. Prefer smallest change; match existing style; no drive-by refactors.
3. After a step **or any meaningful change** (APIs, status, NEXT, env, contracts, run paths): update **this file** and `HANDOFF.md` when status/next shifts; then **pause** after BUILD ORDER steps.
4. Keep this file accurate over chat continuity — do not let Status/NEXT/APIs drift from the repo.
5. Demo polish next — do not invent new stack/features unless human asks.
6. Secrets: none expected; don’t commit `.venv` / local DBs / peer data dirs.

## Resume one-liner

> Steps 1–7 done. Do final polish (seed/multi-peer demo hygiene via `scripts/run.sh`). Update `AGENTS.md` + `HANDOFF.md`. Pause.
