#!/usr/bin/env python3
"""Prepare equal old-book/new-book datasets for the Gen9 opening-book A/B.

The old pilot stopped at 2,420,781 complete 32-byte records spread across 12
worker shards.  The clean new-book run is larger.  This script concatenates
all old records and takes an equal prefix from every new worker shard, giving
the two arms exactly the same position count without modifying either source.

Outputs are written atomically and accompanied by a manifest containing every
input size/hash and the exact per-shard allocation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


RECORD_BYTES = 32
ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path, chunk_size: int = 4 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def shard_inventory(directory: Path) -> list[dict[str, object]]:
    paths = sorted(directory.glob("data_*.bin"))
    if not paths:
        raise RuntimeError(f"no data_*.bin shards found in {directory}")

    inventory: list[dict[str, object]] = []
    for path in paths:
        size = path.stat().st_size
        if size % RECORD_BYTES:
            raise RuntimeError(
                f"unaligned shard {path}: {size} bytes is not divisible by "
                f"{RECORD_BYTES}"
            )
        inventory.append(
            {
                "path": str(path.resolve()),
                "bytes": size,
                "records": size // RECORD_BYTES,
                "sha256": sha256(path),
            }
        )
    return inventory


def copy_prefixes(
    inventory: list[dict[str, object]], allocations: list[int], output: Path
) -> dict[str, object]:
    if len(inventory) != len(allocations):
        raise ValueError("one allocation is required for every input shard")

    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".partial")
    if partial.exists():
        partial.unlink()

    digest = hashlib.sha256()
    total_records = 0
    selected: list[dict[str, object]] = []
    try:
        with partial.open("xb") as destination:
            for item, requested in zip(inventory, allocations):
                available = int(item["records"])
                if requested < 0 or requested > available:
                    raise RuntimeError(
                        f"requested {requested} records from {item['path']}, "
                        f"but only {available} are available"
                    )

                remaining = requested * RECORD_BYTES
                with Path(str(item["path"])).open("rb") as source:
                    while remaining:
                        block = source.read(min(4 << 20, remaining))
                        if not block:
                            raise RuntimeError(f"unexpected EOF in {item['path']}")
                        destination.write(block)
                        digest.update(block)
                        remaining -= len(block)

                total_records += requested
                selected.append(
                    {
                        "path": item["path"],
                        "available_records": available,
                        "selected_records": requested,
                        "source_sha256": item["sha256"],
                    }
                )
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(partial, output)
    finally:
        if partial.exists():
            partial.unlink()

    return {
        "path": str(output.resolve()),
        "records": total_records,
        "bytes": total_records * RECORD_BYTES,
        "sha256": digest.hexdigest(),
        "selection": selected,
    }


def git_text(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=ROOT, text=True, capture_output=True, check=False
    )
    return proc.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-dir", type=Path, default=ROOT / "data/gen9_raw")
    parser.add_argument(
        "--new-dir", type=Path, default=ROOT / "data/gen9_raw_generic"
    )
    parser.add_argument(
        "--out-dir", type=Path, default=ROOT / "data/gen9_book_ab_2420781"
    )
    parser.add_argument(
        "--target",
        type=int,
        default=None,
        help="records per arm; default is the complete old-pilot count",
    )
    args = parser.parse_args()

    old_inventory = shard_inventory(args.old_dir.resolve())
    new_inventory = shard_inventory(args.new_dir.resolve())
    if len(old_inventory) != len(new_inventory):
        raise RuntimeError(
            f"worker-shard count differs: old={len(old_inventory)}, "
            f"new={len(new_inventory)}"
        )

    old_total = sum(int(item["records"]) for item in old_inventory)
    target = old_total if args.target is None else args.target
    if target <= 0 or target > old_total:
        raise RuntimeError(f"invalid target {target}; old set has {old_total} records")

    # For the canonical experiment the complete pilot is the control.  A
    # smaller explicit target is supported, distributed proportionally by a
    # deterministic prefix allocation.
    if target == old_total:
        old_allocations = [int(item["records"]) for item in old_inventory]
    else:
        base, remainder = divmod(target, len(old_inventory))
        old_allocations = [base + (index < remainder) for index in range(len(old_inventory))]

    base, remainder = divmod(target, len(new_inventory))
    new_allocations = [base + (index < remainder) for index in range(len(new_inventory))]

    out_dir = args.out_dir.resolve()
    old_output = out_dir / f"old_book_{target}.bin"
    new_output = out_dir / f"new_book_{target}.bin"
    manifest_path = out_dir / "manifest.json"
    for path in (old_output, new_output, manifest_path):
        if path.exists():
            raise RuntimeError(
                f"refusing to overwrite existing experiment artefact: {path}"
            )

    old_result = copy_prefixes(old_inventory, old_allocations, old_output)
    new_result = copy_prefixes(new_inventory, new_allocations, new_output)
    if old_result["records"] != target or new_result["records"] != target:
        raise AssertionError("output record counts do not match the requested target")

    old_book = ROOT / "testing/book.epd"
    new_book = ROOT / "testing/datagen_gen9.epd"
    net = ROOT / "nets/gen8.nnue"
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "purpose": "Gen9 old 150-root book versus new 15,000-root book A/B",
        "record_bytes": RECORD_BYTES,
        "positions_per_arm": target,
        "selection": {
            "old": "all complete old-pilot records in sorted shard order",
            "new": (
                "equal per-shard prefixes in sorted shard order; first remainder "
                "shards receive one additional record"
            ),
        },
        "controlled_conditions": {
            "labeller": str(net.resolve()),
            "labeller_sha256": sha256(net),
            "search_limit": "nodes:150000 per move",
            "datagen_filters": (
                "same datagen implementation: 4-9 random opening plies, 5000-node "
                "balance probe, quiet positions, |score| < 2000"
            ),
            "functional_difference": "opening-book root distribution",
        },
        "books": {
            "old": {
                "path": str(old_book.resolve()),
                "positions": 150,
                "sha256": sha256(old_book),
            },
            "new": {
                "path": str(new_book.resolve()),
                "positions": 15000,
                "sha256": sha256(new_book),
            },
        },
        "outputs": {"old": old_result, "new": new_result},
        "repository": {
            "commit": git_text("rev-parse", "HEAD"),
            "dirty": bool(git_text("status", "--porcelain")),
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"old: {old_result['records']} records  {old_result['sha256']}")
    print(f"new: {new_result['records']} records  {new_result['sha256']}")
    print(f"manifest: {manifest_path}")


if __name__ == "__main__":
    main()
