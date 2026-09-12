"""Local download library — SQLite inventory + integrity checks for a peer."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from peer.store import ChunkStore
from shared.utils import verify_file

STATUS_OK = "ok"
STATUS_MISSING = "missing"
STATUS_CORRUPT = "corrupt"
ZOMBIE_STATUSES = frozenset({STATUS_MISSING, STATUS_CORRUPT})


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class LocalInventory:
    """Tracks completed downloads/seeds under PEER_DATA_DIR/complete/."""

    def __init__(self, data_dir: str | Path, store: ChunkStore) -> None:
        self.data_dir = Path(data_dir)
        self.store = store
        self.db_path = self.data_dir / "library.db"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS local_files (
                    file_id INTEGER PRIMARY KEY,
                    filename TEXT NOT NULL,
                    file_hash TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    path TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ok',
                    source TEXT NOT NULL DEFAULT 'download',
                    added_at TEXT NOT NULL,
                    verified_at TEXT,
                    note TEXT
                )
                """
            )
            conn.commit()

    def register(
        self,
        *,
        file_id: int,
        filename: str,
        file_hash: str,
        file_size: int,
        path: str | Path,
        source: str = "download",
        status: str = STATUS_OK,
    ) -> dict[str, Any]:
        path = str(Path(path).resolve())
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO local_files
                    (file_id, filename, file_hash, file_size, path, status, source, added_at, verified_at, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                ON CONFLICT(file_id) DO UPDATE SET
                    filename = excluded.filename,
                    file_hash = excluded.file_hash,
                    file_size = excluded.file_size,
                    path = excluded.path,
                    status = excluded.status,
                    source = excluded.source,
                    verified_at = excluded.verified_at,
                    note = NULL
                """,
                (file_id, filename, file_hash, int(file_size), path, status, source, now, now),
            )
            conn.commit()
        row = self.get(file_id)
        assert row is not None
        return row

    def get(self, file_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM local_files WHERE file_id = ?", (file_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_files(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM local_files ORDER BY added_at DESC, file_id DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def _discover_from_disk(self) -> None:
        """Import any complete/meta pairs that are not yet in the library DB."""
        meta_dir = self.store.meta_dir
        if not meta_dir.is_dir():
            return
        for meta_path in sorted(meta_dir.glob("*.json")):
            try:
                file_id = int(meta_path.stem)
            except ValueError:
                continue
            if self.get(file_id):
                continue
            try:
                meta = json.loads(meta_path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if not meta.get("verified") and not meta.get("file_hash"):
                continue
            complete = self.store._complete_path(file_id)
            filename = meta.get("filename") or (complete.name if complete else f"file_{file_id}")
            path = complete if complete else (self.store.complete_dir / str(file_id) / filename)
            self.register(
                file_id=file_id,
                filename=filename,
                file_hash=str(meta.get("file_hash") or ""),
                file_size=int(meta.get("file_size") or 0),
                path=path,
                source="seed" if meta.get("fetched_this_run") is None and complete else "download",
                status=STATUS_OK,
            )

    def _check_entry(self, entry: dict[str, Any]) -> tuple[str, str | None]:
        """Return (status, note) after existence / size / hash checks."""
        path = Path(entry["path"])
        expected_hash = entry.get("file_hash") or ""
        expected_size = int(entry.get("file_size") or 0)

        # Prefer live complete/ location if the stored path moved.
        live = self.store._complete_path(int(entry["file_id"]))
        if live is not None:
            path = live

        if not path.is_file():
            return STATUS_MISSING, "File missing from disk"

        try:
            size = path.stat().st_size
        except OSError as exc:
            return STATUS_MISSING, f"Unreadable: {exc}"

        if expected_size and size != expected_size:
            return STATUS_CORRUPT, f"Size mismatch ({size} != {expected_size})"

        if expected_hash:
            try:
                if not verify_file(path, expected_hash):
                    return STATUS_CORRUPT, "SHA-256 mismatch"
            except OSError as exc:
                return STATUS_CORRUPT, f"Hash failed: {exc}"

        return STATUS_OK, None

    def verify_all(self) -> dict[str, Any]:
        """
        Startup / manual validation: discover disk entries, re-check every row.
        Updates status in the DB. Does not delete zombies.
        """
        self._discover_from_disk()
        entries = self.list_files()
        counts = {STATUS_OK: 0, STATUS_MISSING: 0, STATUS_CORRUPT: 0}
        now = _utc_now()

        with self._connect() as conn:
            for entry in entries:
                status, note = self._check_entry(entry)
                counts[status] = counts.get(status, 0) + 1
                live = self.store._complete_path(int(entry["file_id"]))
                path = str(live.resolve()) if live else entry["path"]
                conn.execute(
                    """
                    UPDATE local_files
                    SET status = ?, note = ?, verified_at = ?, path = ?,
                        filename = COALESCE(?, filename)
                    WHERE file_id = ?
                    """,
                    (
                        status,
                        note,
                        now,
                        path,
                        live.name if live else None,
                        entry["file_id"],
                    ),
                )
            conn.commit()

        return {
            "checked": len(entries),
            "ok": counts.get(STATUS_OK, 0),
            "missing": counts.get(STATUS_MISSING, 0),
            "corrupt": counts.get(STATUS_CORRUPT, 0),
            "zombies": counts.get(STATUS_MISSING, 0) + counts.get(STATUS_CORRUPT, 0),
            "verified_at": now,
        }

    def clear_zombies(self) -> dict[str, Any]:
        """Remove missing/corrupt library rows and leftover complete/meta debris."""
        self.verify_all()
        zombies = [e for e in self.list_files() if e["status"] in ZOMBIE_STATUSES]
        removed = []

        with self._connect() as conn:
            for entry in zombies:
                file_id = int(entry["file_id"])
                # Drop broken complete bytes / empty folders
                folder = self.store.complete_dir / str(file_id)
                if folder.is_dir():
                    for p in folder.iterdir():
                        if p.is_file():
                            p.unlink(missing_ok=True)
                    try:
                        folder.rmdir()
                    except OSError:
                        pass
                meta_path = self.store.meta_dir / f"{file_id}.json"
                meta_path.unlink(missing_ok=True)
                conn.execute("DELETE FROM local_files WHERE file_id = ?", (file_id,))
                removed.append(file_id)
            conn.commit()

        summary = self.verify_all()
        summary["cleared"] = removed
        summary["cleared_count"] = len(removed)
        return summary

    def resolve_path(self, file_id: int) -> Path | None:
        """Return a path only if the entry is currently OK and the file exists."""
        entry = self.get(file_id)
        if not entry or entry["status"] != STATUS_OK:
            return None
        live = self.store._complete_path(file_id)
        path = live if live is not None else Path(entry["path"])
        if not path.is_file():
            return None
        # Containment: must live under complete/
        try:
            path.resolve().relative_to(self.store.complete_dir.resolve())
        except ValueError:
            return None
        return path
