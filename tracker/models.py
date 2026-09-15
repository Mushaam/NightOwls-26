"""SQLite models and helpers for the NightOwls tracker."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "tracker.db"


def get_connection(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with get_connection(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS peers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT NOT NULL,
                port INTEGER NOT NULL,
                registered_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(ip, port)
            );

            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                file_hash TEXT NOT NULL UNIQUE,
                file_size INTEGER NOT NULL,
                chunk_count INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                chunk_hash TEXT NOT NULL,
                FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
                UNIQUE(file_id, chunk_index)
            );

            CREATE TABLE IF NOT EXISTS peer_chunks (
                peer_id INTEGER NOT NULL,
                file_id INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                PRIMARY KEY (peer_id, file_id, chunk_index),
                FOREIGN KEY (peer_id) REFERENCES peers(id) ON DELETE CASCADE,
                FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                action TEXT NOT NULL,
                actor TEXT,
                detail TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at DESC);

            CREATE TABLE IF NOT EXISTS wormhole_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seeder_ip TEXT NOT NULL,
                seeder_port INTEGER NOT NULL,
                requester_ip TEXT NOT NULL,
                requester_port INTEGER NOT NULL,
                file_id INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                code TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                detail TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_wh_seeder
                ON wormhole_jobs(seeder_ip, seeder_port, status);
            """
        )


def log_audit(
    conn: sqlite3.Connection,
    action: str,
    *,
    actor: str | None = None,
    detail: str | None = None,
) -> None:
    """Append one audit row. Caller commits (or shares an outer transaction)."""
    conn.execute(
        "INSERT INTO audit_log (action, actor, detail) VALUES (?, ?, ?)",
        (action, actor, detail),
    )


def list_audit(conn: sqlite3.Connection, limit: int = 200) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 5000))
    rows = conn.execute(
        "SELECT id, created_at, action, actor, detail FROM audit_log "
        "ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_peers(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT p.id, p.ip, p.port, p.registered_at,
               COUNT(pc.chunk_index) AS chunk_claims
        FROM peers p
        LEFT JOIN peer_chunks pc ON pc.peer_id = p.id
        GROUP BY p.id
        ORDER BY p.id
        """
    ).fetchall()
    return [dict(r) for r in rows]


def portal_stats(conn: sqlite3.Connection) -> dict[str, int]:
    files = conn.execute("SELECT COUNT(*) AS n FROM files").fetchone()["n"]
    peers = conn.execute("SELECT COUNT(*) AS n FROM peers").fetchone()["n"]
    claims = conn.execute("SELECT COUNT(*) AS n FROM peer_chunks").fetchone()["n"]
    audits = conn.execute("SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
    return {
        "files": files,
        "peers": peers,
        "chunk_claims": claims,
        "audit_events": audits,
    }


def rename_file(conn: sqlite3.Connection, file_id: int, filename: str) -> dict[str, Any]:
    name = (filename or "").strip()
    if not name:
        raise ValueError("filename required")
    row = conn.execute("SELECT id, filename FROM files WHERE id = ?", (file_id,)).fetchone()
    if not row:
        raise ValueError(f"Unknown file_id: {file_id}")
    old = row["filename"]
    conn.execute("UPDATE files SET filename = ? WHERE id = ?", (name, file_id))
    log_audit(
        conn,
        "inventory_rename",
        actor="portal",
        detail=f"file_id={file_id} '{old}' -> '{name}'",
    )
    conn.commit()
    meta = get_file(conn, file_id)
    if not meta:
        raise ValueError(f"Unknown file_id: {file_id}")
    return meta


def delete_file(
    conn: sqlite3.Connection,
    file_id: int,
    *,
    actor: str = "portal",
) -> dict[str, Any]:
    """
    Remove a file from the tracker catalog only.

    Cascades chunk manifests and peer_chunk claims. Does **not** touch peer disks.
    After this, the swarm treats the file as if it was never announced.
    """
    row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    if not row:
        raise ValueError(f"Unknown file_id: {file_id}")
    info = dict(row)
    conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
    log_audit(
        conn,
        "file_unshare",
        actor=actor,
        detail=(
            f"file_id={file_id} name={info.get('filename')} "
            f"hash={info.get('file_hash')} (catalog only; peer copies kept)"
        ),
    )
    conn.commit()
    return info


def register_peer(
    conn: sqlite3.Connection,
    ip: str,
    port: int,
    *,
    audit: bool = True,
) -> dict[str, Any]:
    conn.execute(
        "INSERT INTO peers (ip, port) VALUES (?, ?) "
        "ON CONFLICT(ip, port) DO UPDATE SET registered_at = datetime('now')",
        (ip, port),
    )
    row = conn.execute(
        "SELECT id, ip, port, registered_at FROM peers WHERE ip = ? AND port = ?",
        (ip, port),
    ).fetchone()
    if audit:
        log_audit(conn, "peer_register", actor=f"{ip}:{port}", detail=f"peer_id={row['id']}")
    conn.commit()
    return dict(row)


def upload_metadata(
    conn: sqlite3.Connection,
    filename: str,
    file_hash: str,
    file_size: int,
    chunk_hashes: list[str],
    peer_ip: str,
    peer_port: int,
    *,
    register_as_seeder: bool = True,
) -> dict[str, Any]:
    peer = register_peer(conn, peer_ip, peer_port, audit=False)

    existing = conn.execute(
        "SELECT id FROM files WHERE file_hash = ?", (file_hash,)
    ).fetchone()

    if existing:
        file_id = existing["id"]
        conn.execute(
            "UPDATE files SET filename = ?, file_size = ?, chunk_count = ? WHERE id = ?",
            (filename, file_size, len(chunk_hashes), file_id),
        )
    else:
        cur = conn.execute(
            "INSERT INTO files (filename, file_hash, file_size, chunk_count) "
            "VALUES (?, ?, ?, ?)",
            (filename, file_hash, file_size, len(chunk_hashes)),
        )
        file_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO chunks (file_id, chunk_index, chunk_hash) VALUES (?, ?, ?)",
            [(file_id, i, h) for i, h in enumerate(chunk_hashes)],
        )

    # Only claim chunks once local bytes are ready to serve (see swarm.upload_file).
    if register_as_seeder:
        conn.executemany(
            "INSERT OR IGNORE INTO peer_chunks (peer_id, file_id, chunk_index) "
            "VALUES (?, ?, ?)",
            [(peer["id"], file_id, i) for i in range(len(chunk_hashes))],
        )
    action = "file_update" if existing else "file_register"
    log_audit(
        conn,
        action,
        actor=f"{peer_ip}:{peer_port}",
        detail=(
            f"file_id={file_id} name={filename} size={file_size} "
            f"chunks={len(chunk_hashes)} seeder={register_as_seeder}"
        ),
    )
    conn.commit()

    return get_file(conn, file_id)


def get_file(conn: sqlite3.Connection, file_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    if not row:
        return None
    chunks = conn.execute(
        "SELECT chunk_index, chunk_hash FROM chunks WHERE file_id = ? "
        "ORDER BY chunk_index",
        (file_id,),
    ).fetchall()
    seeder_count = conn.execute(
        "SELECT COUNT(DISTINCT peer_id) AS n FROM peer_chunks WHERE file_id = ?",
        (file_id,),
    ).fetchone()["n"]
    return {
        **dict(row),
        "chunk_hashes": [c["chunk_hash"] for c in chunks],
        "seeder_count": seeder_count,
    }


def list_files(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM files ORDER BY id").fetchall()
    result = []
    for row in rows:
        seeder_count = conn.execute(
            "SELECT COUNT(DISTINCT peer_id) AS n FROM peer_chunks WHERE file_id = ?",
            (row["id"],),
        ).fetchone()["n"]
        result.append({**dict(row), "seeder_count": seeder_count})
    return result


def peers_for_file(conn: sqlite3.Connection, file_id: int) -> list[dict[str, Any]]:
    """Return peers that have at least one chunk of this file, with chunk indexes."""
    peers = conn.execute(
        """
        SELECT p.id AS peer_id, p.ip, p.port,
               GROUP_CONCAT(pc.chunk_index) AS chunk_indexes
        FROM peer_chunks pc
        JOIN peers p ON p.id = pc.peer_id
        WHERE pc.file_id = ?
        GROUP BY p.id, p.ip, p.port
        ORDER BY p.id
        """,
        (file_id,),
    ).fetchall()

    out = []
    for p in peers:
        indexes = (
            [int(x) for x in p["chunk_indexes"].split(",")]
            if p["chunk_indexes"]
            else []
        )
        out.append(
            {
                "peer_id": p["peer_id"],
                "ip": p["ip"],
                "port": p["port"],
                "chunks": sorted(indexes),
            }
        )
    return out


def peer_has_chunk(
    conn: sqlite3.Connection,
    peer_ip: str,
    peer_port: int,
    file_id: int,
    chunk_index: int,
) -> dict[str, Any]:
    peer = register_peer(conn, peer_ip, peer_port, audit=False)
    file_row = conn.execute("SELECT id FROM files WHERE id = ?", (file_id,)).fetchone()
    if not file_row:
        raise ValueError(f"Unknown file_id: {file_id}")

    chunk_row = conn.execute(
        "SELECT id FROM chunks WHERE file_id = ? AND chunk_index = ?",
        (file_id, chunk_index),
    ).fetchone()
    if not chunk_row:
        raise ValueError(f"Unknown chunk_index {chunk_index} for file_id {file_id}")

    conn.execute(
        "INSERT OR IGNORE INTO peer_chunks (peer_id, file_id, chunk_index) "
        "VALUES (?, ?, ?)",
        (peer["id"], file_id, chunk_index),
    )
    conn.commit()
    return {
        "peer_id": peer["id"],
        "file_id": file_id,
        "chunk_index": chunk_index,
        "status": "recorded",
    }


# ---------------------------------------------------------------------------
# Magic Wormhole job coordination (cross-network chunk fallback)
# ---------------------------------------------------------------------------


def _wormhole_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def create_wormhole_job(
    conn: sqlite3.Connection,
    *,
    seeder_ip: str,
    seeder_port: int,
    requester_ip: str,
    requester_port: int,
    file_id: int,
    chunk_index: int,
) -> dict[str, Any]:
    cur = conn.execute(
        """
        INSERT INTO wormhole_jobs (
            seeder_ip, seeder_port, requester_ip, requester_port,
            file_id, chunk_index, status
        ) VALUES (?, ?, ?, ?, ?, ?, 'pending')
        """,
        (
            seeder_ip,
            int(seeder_port),
            requester_ip,
            int(requester_port),
            int(file_id),
            int(chunk_index),
        ),
    )
    conn.commit()
    return get_wormhole_job(conn, int(cur.lastrowid))


def get_wormhole_job(conn: sqlite3.Connection, job_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM wormhole_jobs WHERE id = ?",
        (int(job_id),),
    ).fetchone()
    return _wormhole_row(row)


def list_wormhole_jobs(
    conn: sqlite3.Connection,
    *,
    seeder_ip: str,
    seeder_port: int,
    status: str | None = "pending",
    limit: int = 20,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 100))
    if status:
        rows = conn.execute(
            """
            SELECT * FROM wormhole_jobs
            WHERE seeder_ip = ? AND seeder_port = ? AND status = ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (seeder_ip, int(seeder_port), status, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM wormhole_jobs
            WHERE seeder_ip = ? AND seeder_port = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (seeder_ip, int(seeder_port), limit),
        ).fetchall()
    return [dict(r) for r in rows]


def claim_wormhole_job(conn: sqlite3.Connection, job_id: int) -> dict[str, Any] | None:
    """Mark a pending job as sending. Returns None if already claimed/missing."""
    cur = conn.execute(
        """
        UPDATE wormhole_jobs
        SET status = 'sending', updated_at = datetime('now')
        WHERE id = ? AND status = 'pending'
        """,
        (int(job_id),),
    )
    conn.commit()
    if cur.rowcount == 0:
        return None
    return get_wormhole_job(conn, job_id)


def set_wormhole_code(
    conn: sqlite3.Connection, job_id: int, code: str
) -> dict[str, Any] | None:
    cur = conn.execute(
        """
        UPDATE wormhole_jobs
        SET code = ?, status = 'ready', updated_at = datetime('now')
        WHERE id = ? AND status IN ('pending', 'sending')
        """,
        (code, int(job_id)),
    )
    conn.commit()
    if cur.rowcount == 0:
        return get_wormhole_job(conn, job_id)
    return get_wormhole_job(conn, job_id)


def update_wormhole_job(
    conn: sqlite3.Connection,
    job_id: int,
    *,
    status: str,
    detail: str | None = None,
) -> dict[str, Any] | None:
    conn.execute(
        """
        UPDATE wormhole_jobs
        SET status = ?, detail = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (status, detail, int(job_id)),
    )
    conn.commit()
    return get_wormhole_job(conn, job_id)
