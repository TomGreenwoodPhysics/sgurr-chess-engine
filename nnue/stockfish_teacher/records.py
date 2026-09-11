"""Original Sgurr adapter for the documented external .plain interchange.

Binpack internals are decoded only by the separate official converter. python-
chess is an installed development dependency; no third-party source is copied.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import heapq
import math
from pathlib import Path
import sqlite3
import struct
import sys

import chess

from common import ROOT, atomic_json, read_json, sha256, space_check

PIECES = "PNBRQKpnbrqk"
REQUIRED = {"fen", "move", "score", "ply", "result"}


def plain_records(stream):
    record = {}
    for line_no, line in enumerate(stream, 1):
        line = line.strip()
        if not line:
            continue
        if line == "e":
            if not REQUIRED.issubset(record):
                raise ValueError(f"Incomplete .plain record ending at line {line_no}")
            yield record
            record = {}
            continue
        key, sep, value = line.partition(" ")
        if not sep or key not in REQUIRED | {"game"} or key in record:
            raise ValueError(f"Unknown/duplicate field at line {line_no}")
        record[key] = value
    if record:
        raise ValueError("Truncated .plain record at EOF")


def group_split(game_id, seed, val_frac):
    """Only explicit stable game IDs qualify; never infer them from ply resets."""
    if not 0 <= val_frac < 1:
        raise ValueError("Invalid validation fraction")
    if val_frac == 0:
        return "train"
    if not game_id:
        raise ValueError("Game-disjoint holdout requires explicit source game IDs")
    h = hashlib.sha256(f"split:{seed}:{game_id}".encode()).digest()
    return "val" if int.from_bytes(h[:8], "big") / 2**64 < val_frac else "train"


def score_to_cp(score, teacher_scale, runtime_scale=400):
    if not math.isfinite(teacher_scale) or teacher_scale <= 0 or runtime_scale != 400:
        raise ValueError("Finite positive teacher scale and Sgurr runtime scale 400 required")
    return round(score * runtime_scale / teacher_scale)


def pack(board, cp, result):
    if not -32768 <= cp <= 32767 or result not in (-1, 0, 1):
        raise ValueError("Score/result outside Sgurr record range")
    pieces = sorted(board.piece_map().items())
    if len(pieces) > 32:
        raise ValueError("More than 32 pieces")
    occupancy = sum(1 << sq for sq, _ in pieces)
    nibbles = bytearray(16)
    for i, (_, piece) in enumerate(pieces):
        nibbles[i // 2] |= PIECES.index(piece.symbol()) << (4 * (i % 2))
    return struct.pack("<Q16sBhB4x", occupancy, nibbles, 0 if board.turn else 1, cp, result + 1)


def unpack(record):
    if len(record) != 32:
        raise ValueError("Expected exactly 32 bytes")
    occ, nib, stm, cp, result = struct.unpack("<Q16sBhB4x", record)
    if stm not in (0, 1) or result not in (0, 1, 2) or any(record[28:]):
        raise ValueError("Invalid metadata or nonzero padding")
    squares = [s for s in range(64) if (occ >> s) & 1]
    if len(squares) > 32:
        raise ValueError("Too many occupied squares")
    board = chess.Board(None)
    board.turn = stm == 0
    for i in range(32):
        code = (nib[i // 2] >> (4 * (i % 2))) & 15
        if i < len(squares):
            if code >= 12:
                raise ValueError("Invalid piece code")
            board.set_piece_at(squares[i], chess.Piece.from_symbol(PIECES[code]))
        elif code:
            raise ValueError("Nonzero unused nibble")
    return board, cp, result - 1


def validate_source(rec):
    if len(rec["fen"].split()) != 6:
        raise ValueError("Require all six FEN fields")
    board = chess.Board(rec["fen"])
    if not board.is_valid() or len(board.piece_map()) > 32:
        raise ValueError(f"Invalid orthodox position (status {board.status()})")
    score, result, ply = (int(rec[k]) for k in ("score", "result", "ply"))
    if not -32768 <= score <= 32767 or result not in (-1, 0, 1) or not 0 <= ply <= 16383:
        raise ValueError("Invalid source score/result/ply")
    # Official .plain uses standard UCI moves for orthodox castling.
    move = board.parse_uci(rec["move"])
    if move not in board.legal_moves:
        raise ValueError("Illegal source best move")
    return board, move, score, result, ply


def independent_check(rec, record):
    """Compare three decoders, including Sgurr's existing chesslite and exporter."""
    sys.path.insert(0, str(ROOT / "testing"))
    sys.path.insert(0, str(ROOT / "nnue"))
    import chesslite
    import nnue_tools as nt
    board, cp, result = unpack(record)
    original = chesslite.Position.from_fen(rec["fen"])
    actual = [board.piece_at(s).symbol() if board.piece_at(s) else "." for s in range(64)]
    if original.bd != actual or original.white != board.turn:
        raise ValueError("Independent board reconstruction disagrees")
    pieces, stm, ncp, nresult = nt.decode_record(record)
    expected = sorted((0 if p.color else 1, p.piece_type - 1, s) for s, p in board.piece_map().items())
    if sorted(pieces) != expected or (stm, ncp, nresult) != (0 if board.turn else 1, cp, result + 1):
        raise ValueError("Existing Sgurr decoder disagrees")
    if pack(board, cp, result) != record:
        raise ValueError("Record round-trip disagrees")
    return {"source": rec, "record_hex": record.hex(), "board_ascii": str(board), "mapped_cp": cp}


def chunk_index(path):
    """Only framing: no third-party board/score decoding implementation."""
    size = Path(path).stat().st_size
    result = []
    with Path(path).open("rb") as f:
        while f.tell() < size:
            offset = f.tell()
            header = f.read(8)
            if len(header) != 8 or header[:4] != b"BINP":
                raise ValueError(f"Invalid/truncated binpack header at {offset}")
            payload = struct.unpack("<I", header[4:])[0]
            if not 34 <= payload <= 100 * 1024**2 or offset + 8 + payload > size:
                raise ValueError(f"Invalid/truncated binpack payload at {offset}")
            result.append({"index": len(result), "offset": offset, "bytes": payload + 8})
            f.seek(payload, 1)
    if not result:
        raise ValueError("Empty binpack")
    return result


def select_chunks(index, seed, count):
    if not 0 < count <= len(index):
        raise ValueError(f"Need 1..{len(index)} chunks, requested {count}")
    priority = lambda c: hashlib.sha256(f"binpack-chunk:{seed}:{c['index']}".encode()).digest()
    return sorted(sorted(index, key=priority)[:count], key=lambda c: c["index"])


def stem_metadata(path):
    """Independent documented big-endian scalar decode of first chunk stem.

    The complex compressed board/move stream remains the official tool's job.
    This catches byte-order, sign and result mistakes at the actual source bytes.
    """
    with Path(path).open("rb") as f:
        raw = f.read(40)
    if len(raw) != 40 or raw[:4] != b"BINP":
        raise ValueError("Missing complete first stem")
    score, ply_result, rule50 = struct.unpack(">HHH", raw[34:40])
    def signed(value):
        return -(value // 2) - 1 if value & 1 else value // 2
    return {"score": signed(score), "ply": ply_result & 16383,
            "result": signed(ply_result >> 14), "rule50": rule50}


class Stats:
    def __init__(self):
        self.count = 0
        self.pieces, self.stm, self.results, self.phase = (Counter() for _ in range(4))
        self.scores, self.cp = Counter(), Counter()
        self.phase_scores = {}

    def add(self, board, score, cp, result):
        self.count += 1
        self.pieces[len(board.piece_map())] += 1
        self.stm["white" if board.turn else "black"] += 1
        self.results[result] += 1
        phase = sum(len(board.pieces(pt, c)) * w for pt, w in ((2, 1), (3, 1), (4, 2), (5, 4)) for c in (False, True))
        phase_name = "opening" if phase >= 20 else "middlegame" if phase >= 8 else "endgame"
        self.phase[phase_name] += 1
        self.scores[score, result] += 1
        self.cp[cp] += 1
        self.phase_scores.setdefault(phase_name, Counter())[score, result] += 1

    @staticmethod
    def calibration(scores):
        total = sum(scores.values())
        errors = {}
        for scale in (150, 200, 250, 300, 361, 400, 500, 600, 800):
            loss = 0.0
            for (score, result), n in scores.items():
                p = 1 / (1 + math.exp(-max(-60, min(60, score / scale))))
                loss += n * (p - (result + 1) / 2) ** 2
            errors[str(scale)] = loss / total if total else None
        bins = {}
        for (score, result), n in scores.items():
            key = str(math.floor(score / 100) * 100)
            entry = bins.setdefault(key, {"n": 0, "result_sum": 0})
            entry["n"] += n
            entry["result_sum"] += n * (result + 1) / 2
        return {"brier_by_teacher_scale": errors, "raw_score_bins_width100": bins}

    def report(self):
        return {"positions": self.count, "piece_counts": dict(self.pieces), "stm": dict(self.stm),
                "results_minus1_0_plus1": dict(self.results), "phase": dict(self.phase),
                "mapped_cp_histogram": dict(sorted(self.cp.items())),
                "calibration": self.calibration(self.scores),
                "calibration_by_phase": {k: self.calibration(v) for k, v in self.phase_scores.items()},
                "calibration_scope": "Descriptive fit to stored outcomes in this sample; unknown adjudication and no game IDs. Not held-out accuracy, strength, or automatic scale selection."}


def convert_plain(paths, destination, config, *, val_frac=0, seed=0, raw_scores=False):
    """Streaming validation; completed outputs are immutable. Scratch can restart.

    Optional explicit game IDs give exact group splits; chosen binpack has none
    and uses val_frac=0. Feature duplicates are removed across both splits.
    """
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    params = {"config": config, "val_frac": val_frac, "seed": seed,
              "sources": [{"path": str(Path(p).resolve()), "sha256": sha256(p)} for p in paths]}
    if raw_scores:
        params["raw_score_sidecars"] = True
    final_manifest = destination / "conversion.json"
    if final_manifest.exists():
        old = read_json(final_manifest)
        if old["parameters"] != params:
            raise RuntimeError("Conversion settings changed; use a new run ID")
        for name, item in old["outputs"].items():
            if sha256(destination / name) != item["sha256"]:
                raise RuntimeError("Converted data changed")
        return old
    binding = destination / "conversion-inputs.json"
    if binding.exists() and read_json(binding) != params:
        raise RuntimeError("Partial conversion belongs to different inputs/configuration")
    for name in ("train.bin", "val.bin"):
        if (destination / name).exists():
            raise RuntimeError("Unmanifested completed data exists; preserve it and use another run ID")
    atomic_json(binding, params)
    # Upper bound from text size is conservative for 32-byte output plus SQLite.
    space_check(destination, sum(Path(p).stat().st_size for p in paths) * 2 + (512 << 20))
    db_path = destination / "dedup.sqlite.partial"
    if db_path.exists():
        db_path.unlink()  # This run's disposable dedup index only; inputs untouched.
    db = sqlite3.connect(db_path)
    db.execute("CREATE TABLE seen (key BLOB PRIMARY KEY) WITHOUT ROWID")
    stats = Stats()
    counts = Counter()
    examples = []
    outputs = {}
    handles = {s: (destination / f"{s}.bin.partial").open("wb") for s in ("train", "val")}
    score_handles = {s: (destination / f"{s}.scores.partial").open("wb") for s in handles} if raw_scores else {}
    try:
        for path in paths:
            with Path(path).open(encoding="ascii") as f:
                for rec in plain_records(f):
                    counts["source_records"] += 1
                    board, move, score, result, ply = validate_source(rec)
                    split = group_split(rec.get("game"), seed, val_frac)
                    cp = score_to_cp(score, config["teacher_sigmoid_scale"], config["runtime_scale"])
                    if ply < config["min_ply"]:
                        counts["early_ply"] += 1
                        continue
                    if abs(cp) >= config["max_abs_cp"]:
                        counts["extreme_score"] += 1
                        continue
                    if config["quiet_only"] and (board.is_check() or board.is_capture(move) or move.promotion):
                        counts["noisy"] += 1
                        continue
                    record = pack(board, cp, result)
                    cursor = db.execute("INSERT OR IGNORE INTO seen VALUES (?)", (record[:25],))
                    if not cursor.rowcount:
                        counts["duplicates"] += 1
                        continue
                    # Complete per-record board/metadata round trip, not just samples.
                    recovered, sc, res = unpack(record)
                    if recovered.piece_map() != board.piece_map() or recovered.turn != board.turn or (sc, res) != (cp, result):
                        raise ValueError("Record round-trip mismatch")
                    handles[split].write(record)
                    if raw_scores:
                        score_handles[split].write(struct.pack("<h", score))
                    counts[split] += 1
                    stats.add(board, score, cp, result)
                    # Lowest hash ranks give diagnostic records from throughout input.
                    rank = int.from_bytes(hashlib.sha256(record).digest(), "big")
                    entry = (-rank, counts["source_records"], rec.copy(), record)
                    if len(examples) < 16:
                        heapq.heappush(examples, entry)
                    elif entry > examples[0]:
                        heapq.heapreplace(examples, entry)
                    if counts["train"] % 100000 == 0:
                        db.commit()
                        print(f"source={counts['source_records']:,}; accepted={counts['train']:,}; duplicates={counts['duplicates']:,}", flush=True)
        if not counts["train"]:
            raise ValueError("No training records survived")
        checked = [independent_check(rec, record) for _, _, rec, record in sorted(examples)]
    except (ValueError, KeyError, OverflowError) as exc:
        counts["invalid"] += 1
        atomic_json(destination / "conversion-failure.json", {"counts": dict(counts), "error": str(exc)})
        raise
    finally:
        for f in (*handles.values(), *score_handles.values()):
            f.close()
        db.close()
    for split in handles:
        partial = destination / f"{split}.bin.partial"
        outputs[f"{split}.bin"] = {"bytes": partial.stat().st_size, "sha256": sha256(partial), "positions": counts[split]}
        if raw_scores:
            partial = destination / f"{split}.scores.partial"
            outputs[f"{split}.scores"] = {"bytes": partial.stat().st_size, "sha256": sha256(partial), "positions": counts[split]}
    report = {"parameters": params, "counts": {"invalid": 0, **dict(counts)}, "outputs": outputs,
              "statistics": stats.report(), "independent_samples": checked,
              "split": "No holdout" if val_frac == 0 else "SHA-256 of explicit game ID; duplicates removed globally"}
    # Manifest-last publication. On a crash during these renames, refuse an
    # unmanifested output instead of silently treating partial work as complete.
    for split in handles:
        (destination / f"{split}.bin.partial").rename(destination / f"{split}.bin")
        if raw_scores:
            (destination / f"{split}.scores.partial").rename(destination / f"{split}.scores")
    atomic_json(final_manifest, report)
    return read_json(final_manifest)
