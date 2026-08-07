#!/usr/bin/env python3
"""Extended gen7 calibration.

The pipeline's calibrate stage already plays ~240 gauntlet games (rating error
~+/-36). This keeps sgr_gen7.exe playing the same CCRL-anchored pool for as
long as it is left running, appending PGN, to shrink that error bar. Error
scales ~1/sqrt(games): ~4x the games roughly halves it.

Deliberately does NOT solve Ordo or write the ledger -- that is a reviewed
morning step (see the command printed on exit). Stop any time with Ctrl+C;
every finished game is already durable in the PGN, and Ordo reads whatever is
there. Same opponents/TC/book as the pipeline, plus -recover so one engine
crash cannot end an overnight run.
"""
import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BM = ROOT / "benchmarks"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=100000,
                    help="gauntlet rounds; the default is effectively "
                         "'until stopped'")
    ap.add_argument("--tc", default="10+0.1", help="match the pool TC")
    ap.add_argument("--concurrency", type=int, default=7,
                    help="7 physical cores; leaves headroom on the 8-core CCD")
    ap.add_argument("--dry-run", action="store_true",
                    help="resolve paths and print the command without playing")
    ap.add_argument("--config", default="configs/pipeline_gen8.json",
                    help="pipeline config naming the generation/version to extend")
    args = ap.parse_args()

    cfg = json.loads((ROOT / args.config).read_text(encoding="utf-8"))
    version = cfg["version"]
    pool = json.loads((BM / "pool.json").read_text(encoding="utf-8"))
    fc = BM / "tools" / "fastchess.exe"
    gen7 = ROOT / "sgurr_cpp" / f"sgr_gen{cfg['generation']}.exe"
    book = ROOT / "testing" / "book.epd"
    pgn = BM / "games" / f"calib-{version}-{date.today().isoformat()}-extended.pgn"

    missing = [p for p in (fc, gen7, book) if not p.exists()]
    missing += [BM / e["cmd"] for e in pool["engines"]
                if not (BM / e["cmd"]).exists()]
    if missing:
        tag = "WARNING (dry run)" if args.dry_run else "ERROR"
        print(f"{tag}: missing files:")
        for p in missing:
            print(f"    {p}")
        if not args.dry_run:
            return 1
        print("  (sgr_gen7.exe is produced by the pipeline; expected before "
              "phase 2)")

    cmd = [str(fc), "-tournament", "gauntlet", "-seeds", "1",
           "-engine", f"cmd={gen7}", f"name=Sgurr-{version}"]
    for e in pool["engines"]:
        cmd += ["-engine", f"cmd={BM / e['cmd']}", f"name={e['name']}"]
    cmd += ["-each", f"tc={args.tc}",
            "-rounds", str(args.rounds), "-repeat",
            "-concurrency", str(args.concurrency),
            "-recover",
            "-openings", f"file={book}", "format=epd", "order=random",
            "-pgnout", f"file={pgn}", "-ratinginterval", "50"]

    print(f"gen7 engine : {gen7.name}")
    print(f"opponents   : {len(pool['engines'])} pool engines [{pool['pool_id']}]")
    print(f"settings    : tc={args.tc}  concurrency={args.concurrency}  "
          f"rounds={args.rounds}")
    print(f"pgn         : {pgn}")
    print(f"\nmorning solve (all accumulated games -> gen7 rating):\n"
          f"    cat benchmarks/games/calib-*.pgn > /tmp/all.pgn\n"
          f"    benchmarks/tools/ordo.exe -Q -p /tmp/all.pgn "
          f"-m benchmarks/anchors.txt -W -s 1500 -n 5 -N 1")

    if args.dry_run:
        print("\nDRY RUN -- not launching. Command:\n  " + " ".join(cmd))
        return 0

    print("\nPlaying until stopped (Ctrl+C). Each finished game is saved.\n",
          flush=True)
    try:
        return subprocess.call(cmd, cwd=str(BM))
    except KeyboardInterrupt:
        print(f"\nStopped by user. Games saved to:\n  {pgn}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
