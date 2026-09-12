#!/usr/bin/env python3
"""Quick smoke test for shared.utils chunking/hashing."""

from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from shared.utils import (  # noqa: E402
    CHUNK_SIZE,
    chunk_file,
    read_chunk_from_file,
    verify_chunk,
    verify_file,
    write_chunks_to_file,
)


def main() -> None:
    data = b"NightOwls-" * 40000  # ~400KB → multiple 256KB chunks
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "sample.bin"
        dst = Path(tmp) / "reassembled.bin"
        src.write_bytes(data)

        file_hash, file_size, chunk_hashes = chunk_file(src)
        assert file_size == len(data)
        assert len(chunk_hashes) == (len(data) + CHUNK_SIZE - 1) // CHUNK_SIZE

        chunks = [read_chunk_from_file(src, i) for i in range(len(chunk_hashes))]
        for i, block in enumerate(chunks):
            assert verify_chunk(block, chunk_hashes[i]), f"chunk {i} mismatch"

        write_chunks_to_file(dst, chunks)
        assert verify_file(dst, file_hash)
        assert dst.read_bytes() == data

    print(f"OK — {len(chunk_hashes)} chunks, file_hash={file_hash[:16]}…")


if __name__ == "__main__":
    main()
