# NightOwls-26

Decentralized file sharing for a college LAN — BitTorrent-style tracker + peer nodes, built with Flask.

Students seed files from their machines; others download verified 256 KB chunks over HTTP. A dark CRED/Spotify-inspired UI runs on each peer.

## Features

- **Tracker** — central registry of files, chunk manifests, and which peers have which pieces
- **Peers** — upload/seed, download from multiple peers, serve chunks, SHA-256 verification
- **Web UI** — browse, drag-and-drop upload, live download progress
- **CLI** — upload/download without the browser

## Quick start

```bash
cd NightOwls-26
chmod +x scripts/run.sh
./scripts/run.sh
```

This starts:

| Service | URL |
|---------|-----|
| Tracker | http://127.0.0.1:5000 |
| Peer 1 UI | http://127.0.0.1:6001 |
| Peer 2 UI | http://127.0.0.1:6002 |
| Peer 3 UI | http://127.0.0.1:6003 |

Open a peer URL → **Upload** a file on one peer → **Browse / Download** on another.

Press `Ctrl+C` in the terminal to stop everything.

### Options

```bash
./scripts/run.sh              # start tracker + 3 peers
./scripts/run.sh --seed       # also plant 2 demo files on peer 1
./scripts/run.sh --peers 2    # tracker + 2 peers only
./scripts/run.sh --help
```

## Requirements

- Python 3.10+
- Flask (`requirements.txt`)

A local `.venv` is created automatically by `scripts/run.sh` if missing.

## Documentation

- **[USER_MANUAL.md](USER_MANUAL.md)** — full guide (install, UI, CLI, LAN demo, troubleshooting, API)
- **[HANDOFF.md](HANDOFF.md)** — build progress / developer handoff notes

## Project layout

```
tracker/     Flask tracker + SQLite
peer/        Peer node (chunk server, swarm client, UI)
shared/      SHA-256 chunking helpers
scripts/     run.sh, seed helpers
```

## Manual start (without the script)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Terminal 1 — tracker
TRACKER_DB=/tmp/nightowls_tracker.db \
  .venv/bin/python -c "
from tracker.app import create_app, app
create_app()
app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)
"

# Terminal 2 — peer
PEER_DATA_DIR=/tmp/nightowls_peer6001 \
PEER_PORT=6001 PEER_IP=127.0.0.1 \
TRACKER_URL=http://127.0.0.1:5000 \
  .venv/bin/python -m peer.app
```

Then open http://127.0.0.1:6001/

## License

Course / hackathon project — use and modify freely for educational purposes.
