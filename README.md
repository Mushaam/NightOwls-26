# Campus Connect

Decentralized file sharing for a college LAN — BitTorrent-style tracker + peer nodes, built with Flask.

Students seed files from their machines; others download verified 256 KB chunks over HTTP. A dark neo-brutalist Campus Connect UI runs on each peer.

## Features

- **Tracker** — central registry of files, chunk manifests, and which peers have which pieces
- **Peers** — upload/seed, download from multiple peers, serve chunks, SHA-256 verification
- **Web UI** — browse, drag-and-drop upload, live download progress
- **CLI** — upload/download without the browser

## Plug and play

From the project root (creates `.venv` and installs Flask automatically):

```bash
# Terminal 1 — tracker
./server

# Terminal 2 — peer (pass the tracker IP every time)
./client 127.0.0.1
```

On another machine on the same LAN / Tailscale:

```bash
./client <tracker-ip>
# e.g. ./client 192.168.1.10
```

| Command | What it starts |
|---------|----------------|
| `./server` | Tracker on port **5000** (prints the IP/URL to share) |
| `./client <IP>` | Peer UI on **6001** → tracker at that IP (port 5000) |
| `./client <IP>:5000` | Same, with an explicit tracker port |

Windows: `server.bat` / `client.bat` (same arguments).

### Local multi-peer demo

```bash
./scripts/run.sh --seed
```

Starts tracker + 3 peers with demo files. Press `Ctrl+C` to stop all.

| Service | URL |
|---------|-----|
| Tracker | http://127.0.0.1:5000 |
| Peer 1 UI | http://127.0.0.1:6001 |
| Peer 2 UI | http://127.0.0.1:6002 |
| Peer 3 UI | http://127.0.0.1:6003 |

## Requirements

- Python 3.10+
- Flask (`requirements.txt`)

## Documentation

- **[USER_MANUAL.md](USER_MANUAL.md)** — full guide (install, UI, CLI, LAN demo, troubleshooting, API)
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — system diagrams and flows
- **[HANDOFF.md](HANDOFF.md)** — build progress / developer handoff notes

## Project layout

```
server / client   Plug-and-play launchers (root)
tracker/          Flask tracker + SQLite
peer/             Peer node (chunk server, swarm client, UI)
shared/           SHA-256 chunking helpers
scripts/          run.sh, start_server, start_client, seed helpers
```

## License

Course / hackathon project — use and modify freely for educational purposes.
