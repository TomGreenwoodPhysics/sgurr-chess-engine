#!/usr/bin/env python3
"""Freeze the completed Gen9 production shards into one training artifact.

The raw shard directory is left untouched.  The aggregate is written through
an adjacent temporary file and atomically installed only after every shard has
been structurally sampled and hashed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path


RECORD_BYTES = 32
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW = ROOT / "data/gen9_raw_generic"
DEFAULT_OUT = ROOT / "data/gen9_102m"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(8 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def validate_record(record: bytes, path: Path, index: int) -> None:
    if len(record) != RECORD_BYTES:
        raise RuntimeError(f"short record in {path.name} at index {index}")
    occupancy = int.from_bytes(record[0:8], "little")
    piece_count = occupancy.bit_count()
    if not 2 <= piece_count <= 32:
        raise RuntimeError(f"bad occupancy in {path.name} at index {index}")
    pieces = []
    for slot in range(piece_count):
        packed = record[8 + (slot >> 1)]
        pieces.append((packed >> 4) if slot & 1 else (packed & 0x0F))
    if pieces.count(5) != 1 or pieces.count(11) != 1:
        raise RuntimeError(f"bad kings in {path.name} at index {index}")
    if any(piece > 11 for piece in pieces):
        raise RuntimeError(f"bad piece code in {path.name} at index {index}")
    if record[24] > 1 or record[27] > 2:
        raise RuntimeError(f"bad stm/result in {path.name} at index {index}")


def sample_shard(path: Path, positions: int) -> None:
    sample_count = min(201, positions)
    indices = {
        round(i * (positions - 1) / max(1, sample_count - 1))
        for i in range(sample_count)
    }
    with path.open("rb") as source:
        for index in sorted(indices):
            source.seek(index * RECORD_BYTES)
            validate_record(source.read(RECORD_BYTES), path, index)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--expected-positions", type=int, required=True)
    args = parser.parse_args()

    raw = args.raw.resolve()
    output_dir = args.out.resolve()
    shards = sorted(raw.glob("data_*.bin"))
    if not shards:
        raise RuntimeError(f"no data shards in {raw}")

    inventory: list[dict[str, object]] = []
    total_positions = 0
    for path in shards:
        size = path.stat().st_size
        if size % RECORD_BYTES:
            raise RuntimeError(f"partial record tail in {path}: {size % RECORD_BYTES} bytes")
        positions = size // RECORD_BYTES
        sample_shard(path, positions)
        total_positions += positions
        inventory.append(
            {
                "name": path.name,
                "bytes": size,
                "positions": positions,
                "modified_at": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(),
            }
        )

    if total_positions != args.expected_positions:
        raise RuntimeError(
            f"snapshot moved: found {total_positions:,}, expected {args.expected_positions:,} positions"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    aggregate = output_dir / "all.bin"
    temporary = output_dir / "all.bin.part"
    if aggregate.exists() or temporary.exists():
        raise RuntimeError(f"refusing to replace an existing aggregate in {output_dir}")

    aggregate_digest = hashlib.sha256()
    with temporary.open("xb") as target:
        for item, path in zip(inventory, shards, strict=True):
            shard_digest = hashlib.sha256()
            with path.open("rb") as source:
                while chunk := source.read(8 << 20):
                    shard_digest.update(chunk)
                    aggregate_digest.update(chunk)
                    target.write(chunk)
            item["sha256"] = shard_digest.hexdigest()
        target.flush()
        os.fsync(target.fileno())
    os.replace(temporary, aggregate)

    expected_bytes = total_positions * RECORD_BYTES
    if aggregate.stat().st_size != expected_bytes:
        raise RuntimeError("aggregate size changed after installation")

    net = ROOT / "nets/gen8.nnue"
    book = ROOT / "testing/datagen_gen9.epd"
    generator = ROOT / "sgurr_cpp/datagen.exe"
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(),
        "purpose": "Frozen 102M Gen9 production snapshot for training and strength testing",
        "positions": total_positions,
        "record_bytes": RECORD_BYTES,
        "source_directory": str(raw),
        "aggregate": {
            "path": str(aggregate),
            "bytes": aggregate.stat().st_size,
            "sha256": aggregate_digest.hexdigest(),
        },
        "generation": {
            "labeller": str(net),
            "labeller_sha256": sha256(net),
            "search_limit": "nodes:150000 per move",
            "binary": str(generator),
            "binary_sha256": sha256(generator),
            "book": str(book),
            "book_sha256": sha256(book),
            "filters": (
                "4-9 random opening plies; 5000-node +/-200cp balance probe; "
                "quiet positions only; |score| < 2000; first 8 self-play plies skipped; "
                "win adjudication at 2000cp sustained for 6 plies"
            ),
        },
        "validation": {
            "partial_record_files": 0,
            "structural_samples_per_shard": 201,
            "shards_checked": len(shards),
            "raw_shards_unchanged": True,
            "stale_raw_all_bin_excluded": True,
        },
        "shards": inventory,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        f"froze {total_positions:,} positions from {len(shards)} shards -> {aggregate}\n"
        f"aggregate sha256 {manifest['aggregate']['sha256']}\n"
        f"manifest {manifest_path}"
    )


if __name__ == "__main__":
    main()
