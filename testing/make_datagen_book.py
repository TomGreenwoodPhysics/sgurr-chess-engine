#!/usr/bin/env python3
"""Build the engine-neutral Gen9 datagen book from Stockfish 8moves_v3.

Datagen needs FEN-per-line input, while the source book is PGN.  Taking every
source game at its final 16-ply position would also move Sgurr's first recorded
training positions eight plies later than the historical recipe.  Instead this
builder takes equal deterministic samples after 8, 10 and 12 plies.  That keeps
the opening phase close to the old eight-ply starter book while retaining far
more of the generic source's ECO coverage.

The selection is independent of Sgurr's evaluation.  Datagen itself still adds
4-9 random legal plies and applies its normal 5,000-node balance probe.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
import sys

try:
    import chess
    import chess.pgn
except ImportError as exc:  # pragma: no cover - exercised only on an incomplete dev setup
    raise SystemExit("python-chess is required: python -m pip install python-chess") from exc


ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE = ROOT / "8moves_v3.pgn"
DEFAULT_OUTPUT = ROOT / "datagen_gen9.epd"
DEFAULT_MANIFEST = ROOT / "datagen_gen9_book.json"
SOURCE_SHA256 = "5835239f88cc2c7511b177c32392a69f3ede21819cf0616f80a7f907cd21d17e"
SOURCE_URL = "https://github.com/official-stockfish/books/blob/master/8moves_v3.pgn.zip"
SELECTION_SEED = "sgurr-gen9-datagen-book-v1"
DEPTHS = (8, 10, 12)
POSITIONS_PER_DEPTH = 5_000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def position_key(fen: str) -> str:
    """Deduplicate by the four fields that affect the chess position."""
    return " ".join(fen.split()[:4])


def stable_rank(depth: int, key: str) -> bytes:
    return hashlib.sha256(f"{SELECTION_SEED}|{depth}|{key}".encode("ascii")).digest()


def parse_source(path: Path) -> tuple[dict[int, dict[str, dict]], dict]:
    candidates: dict[int, dict[str, dict]] = {depth: {} for depth in DEPTHS}
    source_ecos: collections.Counter[str] = collections.Counter()
    source_results: collections.Counter[str] = collections.Counter()
    games = 0
    malformed = 0

    with path.open(encoding="utf-8", errors="strict") as pgn:
        while True:
            game = chess.pgn.read_game(pgn)
            if game is None:
                break
            games += 1
            if game.errors:
                malformed += 1
                continue

            eco = game.headers.get("Eco", "???")
            source_ecos[eco] += 1
            source_results[game.headers.get("Result", "?")] += 1
            board = game.board()
            for ply, move in enumerate(game.mainline_moves(), 1):
                board.push(move)
                if ply not in candidates:
                    if ply >= max(DEPTHS):
                        break
                    continue
                if not board.is_valid() or board.is_game_over(claim_draw=True):
                    continue
                fen = board.fen(en_passant="fen")
                key = position_key(fen)
                record = candidates[ply].setdefault(
                    key, {"fen": fen, "ecos": set(), "occurrences": 0}
                )
                record["ecos"].add(eco)
                record["occurrences"] += 1

    if malformed:
        raise ValueError(f"source contains {malformed} malformed PGN game(s)")
    if games != 34_700:
        raise ValueError(f"expected 34,700 source games, found {games:,}")

    stats = {
        "games": games,
        "eco_codes": len(source_ecos),
        "eco_counts": dict(sorted(source_ecos.items())),
        "results": dict(sorted(source_results.items())),
    }
    return candidates, stats


def select_positions(candidates: dict[int, dict[str, dict]]) -> tuple[list[dict], dict]:
    selected: list[dict] = []
    globally_seen: set[str] = set()
    depth_stats: dict[str, dict] = {}

    for depth in DEPTHS:
        pool = candidates[depth]
        ordered = sorted(pool.items(), key=lambda item: stable_rank(depth, item[0]))
        picked = 0
        selected_ecos: set[str] = set()
        for key, record in ordered:
            if key in globally_seen:
                continue
            globally_seen.add(key)
            selected_ecos.update(record["ecos"])
            selected.append({
                "fen": record["fen"],
                "key": key,
                "depth": depth,
                "ecos": sorted(record["ecos"]),
            })
            picked += 1
            if picked == POSITIONS_PER_DEPTH:
                break
        if picked != POSITIONS_PER_DEPTH:
            raise ValueError(
                f"ply {depth} supplied only {picked:,} globally unique positions; "
                f"need {POSITIONS_PER_DEPTH:,}"
            )
        depth_stats[str(depth)] = {
            "source_unique_positions": len(pool),
            "selected_positions": picked,
            "selected_eco_codes": len(selected_ecos),
        }

    # Do not leave depth blocks in the output.  Datagen samples randomly, but a
    # stable global shuffle also makes line-based inspection/sampling unbiased.
    selected.sort(
        key=lambda item: hashlib.sha256(
            f"{SELECTION_SEED}|output|{item['key']}".encode("ascii")
        ).digest()
    )
    return selected, depth_stats


def validate_selection(selected: list[dict]) -> dict:
    keys: set[str] = set()
    sides: collections.Counter[str] = collections.Counter()
    ecos: set[str] = set()
    depths: collections.Counter[int] = collections.Counter()

    for item in selected:
        board = chess.Board(item["fen"])
        if not board.is_valid() or board.is_game_over(claim_draw=True):
            raise ValueError(f"invalid or terminal selected position: {item['fen']}")
        key = position_key(item["fen"])
        if key in keys:
            raise ValueError(f"duplicate selected position: {key}")
        keys.add(key)
        sides["white" if board.turn == chess.WHITE else "black"] += 1
        ecos.update(item["ecos"])
        depths[item["depth"]] += 1

    expected = len(DEPTHS) * POSITIONS_PER_DEPTH
    if len(selected) != expected:
        raise ValueError(f"expected {expected:,} positions, selected {len(selected):,}")
    return {
        "positions": len(selected),
        "unique_position_keys": len(keys),
        "side_to_move": dict(sorted(sides.items())),
        "source_eco_codes_represented": len(ecos),
        "positions_by_source_ply": {str(k): v for k, v in sorted(depths.items())},
    }


def write_outputs(
    output: Path,
    manifest_path: Path,
    source: Path,
    source_hash: str,
    selected: list[dict],
    source_stats: dict,
    depth_stats: dict,
    selection_stats: dict,
) -> None:
    header = [
        "# Sgurr Gen9 engine-neutral datagen opening book",
        "# Generated by testing/make_datagen_book.py from Stockfish 8moves_v3.pgn",
        "# 5,000 unique positions each at source plies 8, 10 and 12",
    ]
    text = "\n".join(header + [item["fen"] for item in selected]) + "\n"
    output.write_text(text, encoding="ascii", newline="\n")

    manifest = {
        "schema_version": 1,
        "generator": "testing/make_datagen_book.py",
        "generator_sha256": sha256_file(Path(__file__).resolve()),
        "source": source.name,
        "source_url": SOURCE_URL,
        "source_sha256": source_hash,
        "source_stats": source_stats,
        "selection": {
            "seed": SELECTION_SEED,
            "source_plies": list(DEPTHS),
            "positions_per_ply": POSITIONS_PER_DEPTH,
            "method": "SHA-256 rank of unique four-field FENs; no engine evaluation",
            "depth_stats": depth_stats,
        },
        "output": output.name,
        "output_sha256": sha256_file(output),
        "output_bytes": output.stat().st_size,
        "output_stats": selection_stats,
        "datagen_recipe": {
            "random_plies_added": "4-9",
            "opening_probe": "5,000 nodes; accept abs(score) <= 200 cp",
            "positions_skipped_after_opening": 8,
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    source = args.source.resolve()
    output = args.output.resolve()
    manifest = args.manifest.resolve()
    if not source.is_file():
        parser.error(f"source PGN not found: {source}")
    source_hash = sha256_file(source)
    if source_hash != SOURCE_SHA256:
        parser.error(
            f"source SHA-256 mismatch: expected {SOURCE_SHA256}, got {source_hash}"
        )

    candidates, source_stats = parse_source(source)
    selected, depth_stats = select_positions(candidates)
    selection_stats = validate_selection(selected)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    write_outputs(
        output, manifest, source, source_hash, selected,
        source_stats, depth_stats, selection_stats,
    )

    print(f"wrote {selection_stats['positions']:,} positions to {output}")
    print(f"SHA-256 {sha256_file(output)}")
    print(f"represented {selection_stats['source_eco_codes_represented']} ECO codes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
