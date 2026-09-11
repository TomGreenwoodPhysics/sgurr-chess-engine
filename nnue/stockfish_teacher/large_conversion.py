"""Whole-chunk, resumable conversion to a target number of unique positions.

The same strict Python adapter validates each shard in separate worker
processes. A single deterministic merge removes duplicates across shards.
No self-play worker or data path is used.
"""
from collections import Counter, deque
from concurrent.futures import ProcessPoolExecutor
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time

import numpy as np

from common import atomic_json, read_json, sha256, space_check, verified, require_idle, run, CACHE
from records import (Stats, chunk_index, convert_plain, stem_metadata,
                     plain_records, independent_check)


def ranked_chunks(index, seed, maximum):
    if not isinstance(maximum, int) or not 0 < maximum <= len(index):
        raise ValueError("Invalid maximum chunk count")
    return sorted(index, key=lambda c: hashlib.sha256(
        f"binpack-chunk:{seed}:{c['index']}".encode()).digest())[:maximum]


def prepare_shard(artifact, tool, chunk, destination, config):
    """An independently resumable immutable shard, with its own persistent log."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with (destination / "conversion.log").open("a", encoding="utf-8", buffering=1) as log:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            packed = destination / "source.binpack"
            plain = destination / "source.plain"
            receipt = destination / "source.json"
            if receipt.exists():
                old = read_json(receipt)
                if old["chunk"] != chunk or sha256(packed) != old["binpack_sha256"] or sha256(plain) != old["plain_sha256"]:
                    raise RuntimeError("Completed source shard changed")
            else:
                # Reserve the documented worst-case expansion for this bounded
                # worker before the official converter writes its plain text.
                space_check(destination, chunk["bytes"] * 256 + (512 << 20))
                with Path(artifact).open("rb") as f:
                    f.seek(chunk["offset"])
                    content = f.read(chunk["bytes"])
                if len(content) != chunk["bytes"]:
                    raise ValueError("Truncated source chunk")
                if packed.exists() and packed.read_bytes() != content:
                    raise RuntimeError("Existing source chunk differs")
                if not packed.exists():
                    with packed.open("xb") as f:
                        f.write(content)
                partial = destination / "source.partial.plain"
                converter_log = destination / "official-convert.log"
                run([tool, "convert", packed, partial, "validate"], converter_log, timeout=600)
                output = converter_log.read_text()
                latest = output[output.rfind("command="):]
                if not re.search(r"Finished\. Converted [1-9][0-9]* positions", latest) or "Invalid" in latest:
                    raise RuntimeError("Official converter failed validated completion")
                if plain.exists():
                    raise RuntimeError("Unmanifested source text exists; preserve and investigate")
                partial.rename(plain)
                atomic_json(receipt, {"chunk": chunk, "plain_sha256": sha256(plain),
                                      "plain_bytes": plain.stat().st_size, "binpack_sha256": sha256(packed)})
            with plain.open(encoding="ascii") as f:
                first = next(plain_records(f))
            scalars = stem_metadata(packed)
            if any(int(first[k]) != scalars[k] for k in ("score", "ply", "result")) or int(first["fen"].split()[4]) != scalars["rule50"]:
                raise RuntimeError("Independent source scalar decode differs")
            atomic_json(destination / "stem-check.json", {"source_scalars": scalars, "first_plain_record": first, "status": "PASS"})
            convert_plain([plain], destination, config, raw_scores=True)
    return str(destination)


def _counts(values):
    keys, counts = np.unique(values, return_counts=True)
    return Counter({int(k): int(n) for k, n in zip(keys, counts)})


def _pairs(scores, results):
    return Counter({(k // 3, k % 3 - 1): n for k, n in _counts(scores.astype(np.int64) * 3 + results).items()})


def add_binary_stats(stats, data, raw_scores):
    """Vectorized exact statistics, checked against the ordinary board path."""
    a = np.frombuffer(data, dtype=np.uint8).reshape(-1, 32)
    scores = np.asarray(raw_scores, dtype=np.int16)
    if len(a) != len(scores):
        raise ValueError("Raw score sidecar length differs")
    cp = a[:, 25:27].copy().view("<i2").reshape(-1)
    weights = np.array([0, 1, 1, 2, 4, 0, 0, 1, 1, 2, 4, 0, 0, 0, 0, 0], dtype=np.uint8)
    phase = (weights[a[:, 8:24] & 15] + weights[a[:, 8:24] >> 4]).sum(axis=1)
    stats.count += len(a)
    stats.pieces.update(_counts(np.bitwise_count(a[:, :8]).sum(axis=1)))
    stats.stm.update({("white" if k == 0 else "black"): n for k, n in _counts(a[:, 24]).items()})
    stats.results.update({k - 1: n for k, n in _counts(a[:, 27]).items()})
    stats.cp.update(_counts(cp))
    stats.scores.update(_pairs(scores, a[:, 27]))
    for name, mask in (("opening", phase >= 20), ("middlegame", (phase >= 8) & (phase < 20)), ("endgame", phase < 8)):
        n = int(mask.sum())
        if n:
            stats.phase[name] += n
            stats.phase_scores.setdefault(name, Counter()).update(_pairs(scores[mask], a[mask, 27]))


def stats_state(stats):
    return {"count": stats.count,
            "simple": {k: list(getattr(stats, k).items()) for k in ("pieces", "stm", "results", "phase", "cp")},
            "scores": [[s, r, n] for (s, r), n in stats.scores.items()],
            "phase_scores": {k: [[s, r, n] for (s, r), n in v.items()] for k, v in stats.phase_scores.items()}}


def restore_stats(state):
    result = Stats()
    if state is not None:
        result.count = state["count"]
        for key, items in state["simple"].items():
            setattr(result, key, Counter(dict(items)))
        result.scores = Counter({(s, r): n for s, r, n in state["scores"]})
        result.phase_scores = {k: Counter({(s, r): n for s, r, n in items}) for k, items in state["phase_scores"].items()}
    return result


class Merge:
    """Checkpoint database and flushed output commit together at each shard.

    An interrupted uncommitted tail is truncated to the last database commit.
    Only this run's dedicated temporary output is truncated; inputs are immutable.
    """
    def __init__(self, destination, identity):
        self.root = Path(destination)
        self.root.mkdir(parents=True, exist_ok=True)
        binding = self.root / "conversion-inputs.json"
        if binding.exists() and read_json(binding) != identity:
            raise RuntimeError("Conversion identity changed; choose a new run ID")
        atomic_json(binding, identity)
        self.db = sqlite3.connect(self.root / "merge.sqlite")
        self.db.execute("PRAGMA cache_size=-1048576")  # 1 GiB maximum, one merger.
        self.db.execute("CREATE TABLE IF NOT EXISTS seen (key BLOB PRIMARY KEY) WITHOUT ROWID")
        self.db.execute("CREATE TABLE IF NOT EXISTS checkpoint (id INTEGER PRIMARY KEY, state TEXT NOT NULL)")
        row = self.db.execute("SELECT state FROM checkpoint WHERE id=1").fetchone()
        self.state = json.loads(row[0]) if row else {"chunks": [], "segments": [], "counts": {}, "statistics": None, "examples": []}
        self.counts = Counter(self.state["counts"])
        self.stats = restore_stats(self.state["statistics"])
        partial = self.root / "train.bin.partial"
        expected = self.counts["train"] * 32
        if expected and (not partial.exists() or partial.stat().st_size < expected):
            raise RuntimeError("Checkpoint output missing or truncated")
        self.out = partial.open("r+b" if partial.exists() else "w+b")
        for segment in self.state["segments"]:
            digest = hashlib.sha256()
            remaining = segment["bytes"]
            while remaining:
                block = self.out.read(min(remaining, 4 << 20))
                if not block:
                    raise RuntimeError("Committed merge segment truncated")
                digest.update(block)
                remaining -= len(block)
            if digest.hexdigest() != segment["sha256"]:
                self.close()
                raise RuntimeError("Committed merge segment changed")
        self.out.truncate(expected)
        self.out.seek(expected)

    def add(self, chunk, directory):
        directory = Path(directory)
        report = read_json(directory / "conversion.json")
        if chunk["index"] in self.state["chunks"]:
            raise ValueError("Shard already merged")
        for name, spec in report["outputs"].items():
            if sha256(directory / name) != spec["sha256"]:
                raise RuntimeError("Validated shard changed")
        if report["counts"]["invalid"]:
            raise ValueError("Invalid shard")
        self.counts.update({k: v for k, v in report["counts"].items() if k not in ("train", "val")})
        segment_hash = hashlib.sha256()
        segment_bytes = 0
        with (directory / "train.bin").open("rb") as source, (directory / "train.scores").open("rb") as sidecar:
            while data := source.read(32 * 65536):
                if len(data) % 32:
                    raise ValueError("Truncated validated record")
                n = len(data) // 32
                raw = np.frombuffer(sidecar.read(2 * n), dtype="<i2")
                if len(raw) != n:
                    raise ValueError("Truncated raw score sidecar")
                keep = np.fromiter((bool(self.db.execute("INSERT OR IGNORE INTO seen VALUES (?)", (data[i:i+25],)).rowcount)
                                    for i in range(0, len(data), 32)), dtype=bool, count=n)
                accepted = np.frombuffer(data, dtype=np.uint8).reshape(-1, 32)[keep].tobytes()
                self.out.write(accepted)
                segment_hash.update(accepted)
                segment_bytes += len(accepted)
                self.counts["train"] += int(keep.sum())
                self.counts["duplicates"] += n - int(keep.sum())
                self.counts["cross_chunk_duplicates"] += n - int(keep.sum())
                add_binary_stats(self.stats, accepted, raw[keep])
            if sidecar.read(1):
                raise ValueError("Excess raw score data")
        # A seeded sample from each shard, then hash-rank across all shards.
        # Kept as diagnostic source examples even if globally duplicated.
        examples = self.state["examples"] + report["independent_samples"]
        examples.sort(key=lambda e: hashlib.sha256(bytes.fromhex(e["record_hex"])).digest())
        self.state["examples"] = examples[:16]
        self.state["chunks"].append(chunk["index"])
        self.state["segments"].append({"bytes": segment_bytes, "sha256": segment_hash.hexdigest()})
        self.state["counts"] = dict(self.counts)
        self.state["statistics"] = stats_state(self.stats)
        self.out.flush()
        os.fsync(self.out.fileno())
        self.db.execute("INSERT OR REPLACE INTO checkpoint VALUES (1, ?)", (json.dumps(self.state),))
        self.db.commit()
        atomic_json(self.root / "conversion-status.json", {"chunks_complete": len(self.state["chunks"]), "counts": dict(self.counts)})

    def close(self):
        self.out.close()
        self.db.close()


def convert_target(w):
    require_idle()
    cfg = w.config["sampling"]
    target, workers = cfg["target_positions"], cfg["workers"]
    if not isinstance(target, int) or target <= 0 or not isinstance(workers, int) or not 1 <= workers <= 16:
        raise ValueError("Invalid target or conversion worker count")
    verified(w.artifact, w.dataset)
    receipt = read_json(CACHE / "tool-build.json")
    if sha256(w.tool) != receipt["binary_sha256"]:
        raise RuntimeError("Converter binary changed")
    index = chunk_index(w.artifact)
    ranked = ranked_chunks(index, cfg["seed"], cfg["max_chunks"])
    identity = {"config": w.config["conversion"], "sampling": cfg, "val_frac": 0,
                "artifact_sha256": w.dataset["sha256"], "converter_sha256": receipt["binary_sha256"],
                "source_sha256": {p.name: sha256(p) for p in (Path(__file__), Path(__file__).with_name("records.py"))},
                "ranked_chunks": ranked}
    w.data.mkdir(parents=True, exist_ok=True)
    final = w.data / "conversion.json"
    if final.exists():
        report = read_json(final)
        if report["parameters"] != identity:
            raise RuntimeError("Completed conversion identity differs")
        for name, item in report["outputs"].items():
            if sha256(w.data / name) != item["sha256"]:
                raise RuntimeError("Completed training data changed")
        print(f"Completed conversion verified: {report['counts']['train']:,} positions", flush=True)
        return report
    if (w.data / "train.bin").exists() or (w.data / "val.bin").exists():
        raise RuntimeError("Unmanifested completed output exists; preserve and investigate")
    # Plain text stays on disk, but only a bounded worker window is being
    # expanded at once. Recheck remaining output/index capacity after every
    # merged shard rather than reserving worst-case text for every unused chunk.
    expansion_reserve = max(c["bytes"] for c in ranked) * 256 * workers
    space_check(w.data, expansion_reserve + target * 128 + (2 << 30))
    merger = Merge(w.data, identity)
    done = merger.state["chunks"]
    if done != [c["index"] for c in ranked[:len(done)]]:
        merger.close()
        raise RuntimeError("Checkpoint is not a prefix of seeded rank order")
    remaining = iter(ranked[len(done):])
    pending = deque()
    start = time.monotonic()
    initial = merger.counts["train"]
    try:
        if merger.counts["train"] < target:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                def submit():
                    chunk = next(remaining, None)
                    if chunk is not None:
                        directory = w.data / "shards" / f"chunk-{chunk['index']:06d}"
                        pending.append((chunk, pool.submit(prepare_shard, w.artifact, w.tool, chunk, directory, w.config["conversion"])))
                for _ in range(workers):
                    submit()
                while pending:
                    chunk, future = pending.popleft()
                    directory = future.result()
                    merger.add(chunk, directory)
                    elapsed = time.monotonic() - start
                    count = merger.counts["train"]
                    space_check(w.data, expansion_reserve + max(0, target - count) * 128 + (2 << 30))
                    rate = (count - initial) / max(elapsed, 1)
                    print(f"chunks={len(merger.state['chunks'])}; accepted={count:,}/{target:,}; source={merger.counts['source_records']:,}; duplicates={merger.counts['duplicates']:,}; rate={rate:,.0f}/s; elapsed={elapsed:.0f}s", flush=True)
                    if count >= target:
                        # Already running, bounded lookahead shards finish safely.
                        # They remain audited cache files, excluded from this dataset.
                        for _, task in pending:
                            task.cancel()
                        break
                    submit()
        if merger.counts["train"] < target:
            raise RuntimeError("Maximum chunks exhausted below target; checkpoint retained. Extend only with a new explicit run/config.")
        examples = [independent_check(e["source"], bytes.fromhex(e["record_hex"])) for e in merger.state["examples"]]
        report = {"parameters": identity, "counts": {"invalid": 0, **dict(merger.counts)},
                  "statistics": merger.stats.report(), "independent_samples": examples,
                  "split": "No holdout; no source game IDs", "completed_chunk_indices": merger.state["chunks"],
                  "sampling_note": "Seeded hash order over all source chunks; stop only after a complete shard reaches the accepted unique target. Prefetched unused shards are excluded."}
    finally:
        merger.close()
    partial = w.data / "train.bin.partial"
    report["outputs"] = {"train.bin": {"positions": report["counts"]["train"], "bytes": partial.stat().st_size, "sha256": sha256(partial)},
                         "val.bin": {"positions": 0, "bytes": 0, "sha256": hashlib.sha256(b"").hexdigest()}}
    partial.rename(w.data / "train.bin")
    with (w.data / "val.bin").open("xb"):
        pass
    atomic_json(final, report)
    atomic_json(w.data / "sampling.json", {"artifact_sha256": w.dataset["sha256"], "total_chunks": len(index),
                                           "target_positions": target, "seed": cfg["seed"],
                                           "selected": ranked[:len(report["completed_chunk_indices"])]})
    print(json.dumps({"counts": report["counts"], "outputs": report["outputs"]}, indent=2), flush=True)
    return report
