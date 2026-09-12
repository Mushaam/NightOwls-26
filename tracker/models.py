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
            """
        )


def register_peer(conn: sqlite3.Connection, ip: str, port: int) -> dict[str, Any]:
    conn.execute(
        "INSERT INTO peers (ip, port) VALUES (?, ?) "
        "ON CONFLICT(ip, port) DO UPDATE SET registered_at = datetime('now')",
        (ip, port),
    )
    row = conn.execute(
        "SELECT id, ip, port, registered_at FROM peers WHERE ip = ? AND port = ?",
        (ip, port),
    ).fetchone()
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
    peer = register_peer(conn, peer_ip, peer_port)

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
    peer = register_peer(conn, peer_ip, peer_port)
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
