"""Local on-disk chunk store for a peer node."""

from __future__ import annotations

import json
from pathlib import Path

from shared.utils import CHUNK_SIZE, chunk_file, iter_file_chunks, read_chunk_from_file


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

    def _complete_path(self, file_id: int) -> Path | None:
        folder = self.complete_dir / str(file_id)
        if not folder.is_dir():
            return None
        files = [p for p in folder.iterdir() if p.is_file()]
        return files[0] if files else None

    def save_chunk(self, file_id: int, chunk_index: int, data: bytes) -> Path:
        path = self._chunk_path(file_id, chunk_index)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def has_chunk(self, file_id: int, chunk_index: int) -> bool:
        if self._chunk_path(file_id, chunk_index).is_file():
            return True
        complete = self._complete_path(file_id)
        if complete is None:
            return False
        size = complete.stat().st_size
        start = chunk_index * CHUNK_SIZE
        return start < size

    def load_chunk(self, file_id: int, chunk_index: int) -> bytes | None:
        path = self._chunk_path(file_id, chunk_index)
        if path.is_file():
            return path.read_bytes()

        complete = self._complete_path(file_id)
        if complete is None:
            return None
        size = complete.stat().st_size
        start = chunk_index * CHUNK_SIZE
        if start >= size:
            return None
        return read_chunk_from_file(complete, chunk_index)

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
        dest.write_bytes(source.read_bytes())

        meta = {
            "file_id": file_id,
            "filename": filename,
            "file_hash": file_hash,
            "file_size": file_size,
            "chunk_hashes": chunk_hashes,
            "chunk_count": len(chunk_hashes),
        }
        (self.meta_dir / f"{file_id}.json").write_text(json.dumps(meta, indent=2))
        return meta
