"""SHA-256 chunking and hashing helpers for tracker and peer nodes."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import BinaryIO, Iterable

CHUNK_SIZE = 256 * 1024  # 256 KB


def sha256_bytes(data: bytes) -> str:
    """Return hex SHA-256 digest of a bytes object."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path, chunk_size: int = CHUNK_SIZE) -> str:
    """Return hex SHA-256 digest of an entire file, streamed in chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def iter_file_chunks(
    path: str | Path, chunk_size: int = CHUNK_SIZE
) -> Iterable[tuple[int, bytes]]:
    """Yield (chunk_index, chunk_bytes) for a file."""
    with open(path, "rb") as fh:
        index = 0
        while True:
            block = fh.read(chunk_size)
            if not block:
                break
            yield index, block
            index += 1


def chunk_file(
    path: str | Path, chunk_size: int = CHUNK_SIZE
) -> tuple[str, int, list[str]]:
    """
    Split a file into chunks and hash them.

    Returns:
        file_hash: SHA-256 of the whole file
        file_size: size in bytes
        chunk_hashes: ordered list of per-chunk SHA-256 hex digests
    """
    path = Path(path)
    file_size = path.stat().st_size
    chunk_hashes: list[str] = []
    file_digest = hashlib.sha256()

    for _, block in iter_file_chunks(path, chunk_size=chunk_size):
        chunk_hashes.append(sha256_bytes(block))
        file_digest.update(block)

    return file_digest.hexdigest(), file_size, chunk_hashes


def write_chunks_to_file(
    path: str | Path, chunks: Iterable[bytes]
) -> None:
    """Reassemble ordered chunk bytes into a single file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        for block in chunks:
            fh.write(block)


def verify_chunk(data: bytes, expected_hash: str) -> bool:
    """Return True if data matches the expected SHA-256 hex digest."""
    return sha256_bytes(data) == expected_hash


def verify_file(path: str | Path, expected_hash: str) -> bool:
    """Return True if the file's SHA-256 matches expected_hash."""
    return sha256_file(path) == expected_hash


def read_chunk_from_file(
    path: str | Path, chunk_index: int, chunk_size: int = CHUNK_SIZE
) -> bytes:
    """Read a single chunk by index from a file on disk."""
    with open(path, "rb") as fh:
        fh.seek(chunk_index * chunk_size)
        return fh.read(chunk_size)


def stream_hash(fh: BinaryIO, chunk_size: int = CHUNK_SIZE) -> str:
    """Hash an already-open binary file-like object from the current position."""
    digest = hashlib.sha256()
    while True:
        block = fh.read(chunk_size)
        if not block:
            break
        digest.update(block)
    return digest.hexdigest()
