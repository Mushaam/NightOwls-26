# NightOwls-26 — Architecture & Flow Diagrams

Educational BitTorrent-style LAN file sharing: one **tracker** (catalog + peer map) and many **peers** (seed, download, serve 256 KB SHA-256-verified chunks over HTTP).

---

## 1. High-level system architecture

```mermaid
flowchart TB
  subgraph LAN["College LAN / Tailscale virtual LAN"]
    T["Tracker<br/>Flask :5000<br/>SQLite registry"]

    subgraph P1["Peer A (seeder)"]
      UA["Web UI<br/>Browse / Upload / Download"]
      SA["Swarm client<br/>upload_file / download_file"]
      CA["Chunk server<br/>GET /chunk/..."]
      DA["Disk store<br/>chunks/ · complete/ · meta/"]
    end

    subgraph P2["Peer B (downloader)"]
      UB["Web UI"]
      SB["Swarm client"]
      CB["Chunk server"]
      DB["Disk store"]
    end

    subgraph P3["Peer C"]
      UC["Web UI"]
      SC["Swarm client"]
      CC["Chunk server"]
      DC["Disk store"]
    end
  end

  UA --> SA
  SA -->|"register · metadata · peer_has_chunk"| T
  SA --> DA
  CA --> DA

  UB --> SB
  SB -->|"manifest · peers map"| T
  SB -->|"GET /chunk"| CA
  SB --> DB
  CB --> DB

  SC -->|"GET /chunk"| CA
  SC -->|"GET /chunk"| CB
  SC --> T
```

**Roles**

| Piece | Responsibility |
|-------|----------------|
| Tracker | Files, chunk manifests, which peer has which chunk |
| Peer UI | Human browse / upload / progress |
| Swarm | Chunk, hash, fetch, verify, reassemble, report |
| Chunk server | Serve local pieces to other peers |
| Shared utils | 256 KB split + SHA-256 |

---

## 2. Code / component map

```mermaid
flowchart LR
  subgraph shared["shared/"]
    U["utils.py<br/>CHUNK_SIZE · SHA-256"]
  end

  subgraph tracker["tracker/"]
    TA["app.py<br/>HTTP API"]
    TM["models.py<br/>SQLite schema"]
    TA --> TM
  end

  subgraph peer["peer/"]
    PA["app.py<br/>UI + APIs + /chunk"]
    PS["swarm.py<br/>upload / download"]
    ST["store.py<br/>ChunkStore"]
    TPL["templates/ + static/"]
    PA --> PS
    PA --> ST
    PS --> ST
    PS --> U
    ST --> U
    PA --> TPL
  end

  PS -->|"HTTP JSON"| TA
  PA -->|"HTTP bytes"| PA
```

---

## 3. Tracker data model

```mermaid
erDiagram
  PEERS ||--o{ PEER_CHUNKS : holds
  FILES ||--o{ CHUNKS : split_into
  FILES ||--o{ PEER_CHUNKS : mapped_by
  PEERS {
    int id PK
    text ip
    int port
    text registered_at
  }
  FILES {
    int id PK
    text filename
    text file_hash UK
    int file_size
    int chunk_count
  }
  CHUNKS {
    int id PK
    int file_id FK
    int chunk_index
    text chunk_hash
  }
  PEER_CHUNKS {
    int peer_id FK
    int file_id FK
    int chunk_index
  }
```

---

## 4. HTTP surface

```mermaid
flowchart TB
  subgraph TrackerAPI["Tracker :5000"]
    R1["POST /register_peer"]
    R2["POST /upload_metadata"]
    R3["GET /files"]
    R4["GET /files/<id>"]
    R5["GET /peers/<file_id>"]
    R6["POST /peer_has_chunk"]
  end

  subgraph PeerAPI["Peer :6001+"]
    U1["GET /  · /upload · /download/<id>"]
    U2["POST /api/upload"]
    U3["POST /api/download/<id>"]
    U4["GET /progress/<id>"]
    U5["GET /chunk/<file_id>/<index>"]
    U6["GET /health · /api/files"]
  end

  Browser --> U1
  Browser --> U2
  Browser --> U3
  Browser -->|"poll 1s"| U4
  PeerAPI --> TrackerAPI
  PeerAPI -->|"P2P chunk bytes"| PeerAPI
```

---

## 5. Upload / seed flow

```mermaid
sequenceDiagram
  autonumber
  actor User
  participant UI as Peer UI
  participant API as peer.app
  participant Swarm as swarm.upload_file
  participant Store as ChunkStore
  participant Utils as shared.utils
  participant T as Tracker

  User->>UI: Drop file → Upload & seed
  UI->>API: POST /api/upload (multipart)
  API->>Swarm: upload_file(path, …)
  Swarm->>Utils: chunk_file → hashes + 256KB pieces
  Swarm->>T: POST /upload_metadata<br/>{filename, file_hash, chunk_hashes, peer_ip, peer_port}
  T-->>Swarm: file_id + seeder registered for all chunks
  Swarm->>Store: save each chunk under chunks/<file_id>/
  Swarm->>Store: copy full file to complete/<file_id>/
  Swarm-->>API: {file_id, chunk_count, …}
  API-->>UI: 201 Seeded
  Note over API: Peer keeps serving GET /chunk/<file_id>/<i>
```

---

## 6. Download / swarm flow

```mermaid
sequenceDiagram
  autonumber
  actor User
  participant UI as Peer B UI
  participant API as Peer B app
  participant Swarm as swarm.download_file
  participant T as Tracker
  participant A as Peer A /chunk
  participant C as Peer C /chunk
  participant Store as Peer B store

  User->>UI: Start download
  UI->>API: POST /api/download/<file_id>
  API->>API: background thread + DOWNLOADS[]
  UI->>API: GET /progress/<id> every 1s

  API->>Swarm: download_file(…)
  Swarm->>T: GET /files/<id>  (manifest)
  Swarm->>T: GET /peers/<id>  (who has which chunks)

  loop each missing chunk
    Swarm->>A: GET /chunk/<id>/<i>  (round-robin peers)
    alt hash matches manifest
      Swarm->>Store: save chunk
      Swarm->>T: POST /peer_has_chunk
    else hash fail / peer down
      Swarm->>C: try another peer
    end
    Swarm-->>API: on_progress(percent, peers_known, …)
  end

  Swarm->>Store: reassemble → complete/<id>/<filename>
  Swarm-->>API: status=complete, path=…
  API-->>UI: progress shows Save location
```

---

## 7. Resilience (peer dies mid-download)

```mermaid
flowchart TD
  Start["Peer B downloading file"] --> Ask["Ask tracker: peers for each chunk"]
  Ask --> Pick["Pick a peer that has chunk i"]
  Pick --> Fetch["HTTP GET /chunk"]
  Fetch -->|OK + SHA-256 match| Save["Save + peer_has_chunk"]
  Fetch -->|timeout / 404 / bad hash| Next["Try next peer for chunk i"]
  Next --> Pick
  Save --> More{More chunks?}
  More -->|yes| Pick
  More -->|no| Done["Reassemble complete file"]
  Kill["Peer A killed"] -.->|removes one source| Ask
  Note1["As long as some peer still holds<br/>each chunk, download finishes"]
```

---

## 8. UI interaction flow

```mermaid
stateDiagram-v2
  [*] --> Browse: open peer UI
  Browse --> Upload: Upload nav
  Browse --> DownloadPage: click Download on card
  Upload --> Browse: seed success → refresh catalog
  DownloadPage --> Downloading: Start download
  Downloading --> Downloading: poll /progress every 1s
  Downloading --> Complete: status=complete + path shown
  Downloading --> Error: status=error
  Complete --> Downloading: Download again
  Error --> Downloading: retry
  Complete --> Browse: Back
```

**Progress JSON contract** (polled by the UI):

```text
status, percent, chunks_have, chunks_total, peers_known, path, error, data_dir, downloads_dir
```

Completed files are always under:

```text
<PEER_DATA_DIR>/complete/<file_id>/<filename>
```

---

## 9. Tailscale / LAN deployment

```mermaid
flowchart TB
  subgraph TS["Tailscale overlay (100.x.y.z)"]
    TR["Machine T — Tracker<br/>host 0.0.0.0:5000<br/>TRACKER_DB=…"]

    A["Machine A — start_client<br/>PEER_IP=100.a.a.a<br/>TRACKER_URL=http://100.t.t.t:5000"]
    B["Machine B — start_client<br/>PEER_IP=100.b.b.b"]
    C["Machine C — start_client<br/>PEER_IP=100.c.c.c"]
  end

  A -->|"metadata / maps"| TR
  B --> TR
  C --> TR
  B <-->|"chunks over Tailscale"| A
  C <-->|"chunks over Tailscale"| A
  C <-->|"chunks over Tailscale"| B
```

**Launch helpers**

| OS | Script |
|----|--------|
| Linux / macOS | `./scripts/start_client.sh http://<tracker-ts-ip>:5000` |
| Windows | `scripts\start_client.bat http://<tracker-ts-ip>:5000` |
| Local multi-peer demo | `./scripts/run.sh --seed` |

---

## 10. End-to-end happy path (one picture)

```mermaid
flowchart LR
  U1["1. Peer A uploads file"] --> U2["2. Chunk + SHA-256"]
  U2 --> U3["3. Tracker stores manifest<br/>+ Peer A has all chunks"]
  U3 --> U4["4. Peer B browses GET /files"]
  U4 --> U5["5. B fetches chunks from A<br/>(and later from others)"]
  U5 --> U6["6. B verifies each chunk"]
  U6 --> U7["7. B reports peer_has_chunk"]
  U7 --> U8["8. B reassembles file<br/>→ complete/… path shown in UI"]
  U8 --> U9["9. Peer C can pull from A and B"]
```

---

## Quick mental model

> **Tracker = phone book.** **Peers = actual file pieces.**  
> Discovery always goes through the tracker; bytes move peer-to-peer over HTTP `/chunk/...` with SHA-256 checks so a dead seeder only slows you down if no other peer holds those pieces.
