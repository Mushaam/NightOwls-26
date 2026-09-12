#!/usr/bin/env python3
"""Seed a test file into a peer's chunk store for Step 3 curl tests."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from peer.store import ChunkStore  # noqa: E402
from shared.utils import sha256_bytes  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, help="Peer data directory")
    parser.add_argument("--file-id", type=int, default=1)
    parser.add_argument("--filename", default="step3_demo.bin")
    parser.add_argument(
        "--size",
        type=int,
        default=400_000,
        help="Bytes of generated dummy content (default ~400KB → 2 chunks)",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    raw = data_dir / "_seed_source.bin"
    raw.write_bytes((b"NightOwls-step3-" * (args.size // 16 + 1))[: args.size])

    store = ChunkStore(data_dir)
    meta = store.import_file(raw, file_id=args.file_id, filename=args.filename)
    raw.unlink(missing_ok=True)

    print("Seeded peer store:")
    for k, v in meta.items():
        if k == "chunk_hashes":
            print(f"  chunk_hashes ({len(v)}):")
            for i, h in enumerate(v):
                chunk = store.load_chunk(args.file_id, i)
                assert chunk is not None
                assert sha256_bytes(chunk) == h
                print(f"    [{i}] {h}  ({len(chunk)} bytes)")
        else:
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
