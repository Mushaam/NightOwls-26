"""Local on-disk chunk store for a peer node."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from shared.utils import (
    CHUNK_SIZE,
    chunk_file,
    iter_file_chunks,
    read_chunk_from_file,
    verify_chunk,
)


class ChunkStore:
    """Stores chunks under data_dir/chunks/<file_id>/<index>.bin."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.chunks_dir = self.data_dir / "chunks"
        self.complete_dir = self.data_dir / "complete"
        self.meta_dir = self.data_dir / "meta"
        for d in (self.chunks_dir, self.complete_dir, self.meta_dir):
            d.mkdir(parents=True, exist_ok=True)

    def _chunk_path(self, file_id: int, chunk_index: int) -> Path:
        return self.chunks_dir / str(file_id) / f"{chunk_index}.bin"

    def _meta_path(self, file_id: int) -> Path:
        return self.meta_dir / f"{file_id}.json"

    def _complete_path(self, file_id: int) -> Path | None:
        folder = self.complete_dir / str(file_id)
        if not folder.is_dir():
            return None
        files = [p for p in folder.iterdir() if p.is_file()]
        return files[0] if files else None

    def load_meta(self, file_id: int) -> dict | None:
        path = self._meta_path(file_id)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def is_verified_complete(self, file_id: int, expected_file_hash: str | None = None) -> bool:
        """True only when meta marks a finished download/seed and the file exists."""
        meta = self.load_meta(file_id)
        if not meta:
            return False
        if expected_file_hash and meta.get("file_hash") != expected_file_hash:
            return False
        complete = self._complete_path(file_id)
        if complete is None:
            return False
        expected_size = meta.get("file_size")
        if expected_size is not None and complete.stat().st_size != int(expected_size):
            return False
        return True

    def expected_chunk_size(self, file_id: int, chunk_index: int, file_size: int | None = None, chunk_count: int | None = None) -> int | None:
        meta = self.load_meta(file_id) or {}
        size = file_size if file_size is not None else meta.get("file_size")
        count = chunk_count if chunk_count is not None else meta.get("chunk_count")
        if size is None or count is None:
            return None
        size = int(size)
        count = int(count)
        if chunk_index < 0 or chunk_index >= count:
            return None
        if chunk_index < count - 1:
            return CHUNK_SIZE
        return size - (count - 1) * CHUNK_SIZE

    def save_chunk(self, file_id: int, chunk_index: int, data: bytes) -> Path:
        """Atomically write chunk bytes (temp file + os.replace) to avoid empty/partial reads."""
        path = self._chunk_path(file_id, chunk_index)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{chunk_index}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return path

    def delete_chunk(self, file_id: int, chunk_index: int) -> None:
        path = self._chunk_path(file_id, chunk_index)
        path.unlink(missing_ok=True)

    def clear_incomplete(self, file_id: int) -> None:
        """Remove a non-verified complete file so retries cannot reuse corrupt output."""
        if self.is_verified_complete(file_id):
            return
        folder = self.complete_dir / str(file_id)
        if folder.is_dir():
            for p in folder.iterdir():
                if p.is_file():
                    p.unlink(missing_ok=True)

    def has_chunk(
        self,
        file_id: int,
        chunk_index: int,
        *,
        expected_hash: str | None = None,
        expected_size: int | None = None,
    ) -> bool:
        """
        Return True only when a usable chunk is present.

        Discrete chunk files must be non-empty (and match hash/size when provided).
        Falling back to complete/ is allowed only for a verified complete file.
        """
        path = self._chunk_path(file_id, chunk_index)
        if path.is_file():
            size = path.stat().st_size
            if size <= 0:
                return False
            if expected_size is not None and size != expected_size:
                return False
            if expected_hash is not None:
                try:
                    return verify_chunk(path.read_bytes(), expected_hash)
                except OSError:
                    return False
            return True

        if not self.is_verified_complete(file_id):
            return False

        complete = self._complete_path(file_id)
        if complete is None:
            return False
        size = complete.stat().st_size
        start = chunk_index * CHUNK_SIZE
        if start >= size:
            return False
        if expected_hash is None:
            return True
        try:
            data = read_chunk_from_file(complete, chunk_index)
            return verify_chunk(data, expected_hash)
        except OSError:
            return False

    def load_chunk(self, file_id: int, chunk_index: int) -> bytes | None:
        path = self._chunk_path(file_id, chunk_index)
        if path.is_file():
            data = path.read_bytes()
            return data if data else None

        if not self.is_verified_complete(file_id):
            return None

        complete = self._complete_path(file_id)
        if complete is None:
            return None
        size = complete.stat().st_size
        start = chunk_index * CHUNK_SIZE
        if start >= size:
            return None
        data = read_chunk_from_file(complete, chunk_index)
        return data if data else None

    def import_file(self, source: str | Path, file_id: int, filename: str | None = None) -> dict:
        """
        Split source into chunks on disk and copy the full file under complete/.
        Returns metadata useful for tracker upload_metadata (Step 5).
        """
        source = Path(source)
        filename = filename or source.name
        file_hash, file_size, chunk_hashes = chunk_file(source)

        for index, block in iter_file_chunks(source):
            self.save_chunk(file_id, index, block)

        dest_dir = self.complete_dir / str(file_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / filename
        # Atomic replace for the complete file too
        fd, tmp_name = tempfile.mkstemp(prefix=".__complete.", suffix=".tmp", dir=dest_dir)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(source.read_bytes())
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, dest)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

        meta = {
            "file_id": file_id,
            "filename": filename,
            "file_hash": file_hash,
            "file_size": file_size,
            "chunk_hashes": chunk_hashes,
            "chunk_count": len(chunk_hashes),
            "verified": True,
        }
        self._meta_path(file_id).write_text(json.dumps(meta, indent=2))
        return meta
