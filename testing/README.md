# Sgurr engine match / SPRT testing

## Plain match between two engines (`match.py`)

Point it at two compiled binaries, play N games, get a result. Either edit the
two paths at the top of `match.py` and run it, or pass them on the command
line:

    python3 match.py ./engineA ./engineB --games 100 --tc 8+0.08 --concurrency 6

- `--tc 8+0.08` = 8s + 0.08s/move; or `--tc mt=0.1` for a flat 0.1s per move.
- `--book book.epd` gives opening variety (without it, two deterministic
  engines replay the same game); `--book ""` forces the start position.
- Prints running and final W/D/L, score%, and an Elo estimate with error bars,
  from engine A's perspective. No early stopping; it plays all N games.

This covers most day-to-day testing. The SPRT runner below stops automatically
once a result is statistically settled.

## SPRT: new-vs-old

Each patch is tested against the previous accepted version, not a fixed
opponent:

1. Build the current `main` as `sgr_base` and keep it.
2. Make one change. Build it as `sgr_new`.
3. Run SPRT `sgr_new` vs `sgr_base`.
4. If it passes (H1), `sgr_new` becomes the new `sgr_base`. If it fails (H0),
   discard the change. One idea per test.

### Reading the result

- **H1 ACCEPTED (pass)**: the change is an improvement (by more than `elo0`).
- **H0 ACCEPTED (fail)**: the change is not an improvement; revert it.
- `elo0`/`elo1` are the hypothesis bounds. The standard non-regression test is
  `elo0=0 elo1=5`: H0 = "0 Elo or worse", H1 = "at least +5 Elo".
  `alpha=beta=0.05` gives 5% error each way, so the LLR runs between -2.94 and
  +2.94.
- For a large expected jump (e.g. NNUE), widening to `elo0=0 elo1=10` resolves
  faster.

### A) The included Python harness

No dependencies beyond Python 3:

    python3 sprt.py --new ./sgr_new --base ./sgr_base \
        --tc 8+0.08 --book book.epd --concurrency 8 \
        --elo0 0 --elo1 5 --alpha 0.05 --beta 0.05

Flags: `--tc base+inc` seconds (e.g. `8+0.08`); `--concurrency` parallel games;
`--rounds` cycles the book; `--min-games` guards against tiny-sample variance
(default 16). The harness tracks every game independently and checks every
engine move for legality, so a movegen bug surfaces immediately as a forfeit
plus a warning.

### B) fastchess (higher volume)

`fastchess`/`cutechess-cli` are the standard C++ tournament managers: much
higher throughput and a pentanomial SPRT. Use the same book and bounds.
`fastchess.md` has the exact command.

### C) `tools/sprt.sh`, the standard run

Every SPRT now goes through one script, so conditions cannot drift between
runs: fastchess at 8+0.08, Hash 256, the generic `8moves_v3.pgn`, concurrency
7, `elo0=0 elo1=5`, capped at 5,000 games.

    tools/sprt.sh NAME NEW.exe NEW_NODES BASE.exe BASE_NODES [MAX_GAMES]
    tools/sprt.sh --stop

Both binaries sit in `sgurr_cpp/` with their nets baked in. The node counts
are their bench fingerprints, and the run refuses to start if either binary is
not the one that was checked. Results land in `runs/sprt/NAME/summary.txt`.
Each run has a prediction committed in `benchmarks/` before it starts.

## The opening book

`book.epd` is a starter book of balanced positions (each ~8 plies in, filtered
to within +/-70 cp by Sgurr's own eval). Regenerate or enlarge it with:

    python3 book_gen.py --engine ./sgr_new --out book.epd --count 1000

For serious testing, a large curated book such as UHO (unbalanced human
openings) or a Pohl book reduces draw rates and variance.

Gen9 datagen uses `datagen_gen9.epd`, not the starter book. It contains 15,000
unique engine-neutral positions selected reproducibly from Stockfish's generic
34,700-line `8moves_v3.pgn`: equal 5,000-position samples after 8, 10 and 12
plies. This preserves early-opening training coverage while representing all
385 ECO codes in the source. Rebuild it with:

    python make_datagen_book.py

The exact source and output hashes, selection seed and coverage statistics are
recorded in `datagen_gen9_book.json`. The Gen9 launcher refuses a different
book or manifest.

The preserved 2,420,781-position starter-book pilot can be compared fairly
with an equal new-book subset using:

    python prepare_gen9_book_ab.py

`prepare_gen9_book_ab.py` never changes either raw directory. It concatenates
the complete old pilot, selects equal record prefixes from all 12 new-book
worker shards, and writes exact input/output hashes plus allocations to
`data/gen9_book_ab_2420781/manifest.json`.

`run_gen9_book_ab.py` runs the controlled two-seed comparison. It uses those
matched datasets and a pinned, training-disjoint Stockfish UHO match book,
waits for Trackmania/datagen to stop, keeps production datagen paused, and
writes atomic status plus complete logs under `runs/gen9_book_ab/`.

## Time control

Test at the TC that matters. Fast TC (8+0.08) gives many games quickly and is
standard for iteration; big changes are worth verifying at a slower TC too,
since some gains (deeper search, time management) scale with thinking time.
Avoid extremely fast TC with the Python harness: its per-move overhead can
cause spurious time forfeits below ~1s base.

## Pool calibration

Absolute ratings come from a gauntlet against pool-2026-09-F: 18 engine
families from 3087 to 3438 on the CCRL Blitz list, at 10+0.1 and Hash 256 with
`8moves_v3.pgn`. `benchmarks/pool.json` pins each engine's build and records
why the pool is built the way it is.

    tools/calibrate_pool.sh VERSION EXE NET
    tools/calibrate_pool.sh --stop

The run stops at about ±12 and can be paused without losing games. Pool-F is
pool-E plus nine families under identical conditions, so Ordo solves pool-F's
games together with pool-E's and with nothing older. A version's first run uses
opening seed 1, so every version meets the same openings, and a continued run
takes a new seed.

When engines join the pool, a version that already has games can be topped up
against just those engines for a fixed number of games:

    CALIB_OPPONENTS=Onyx-2.0,Svart-6 CALIB_GAMES_PER_ENGINE=210 tools/calibrate_pool.sh VERSION EXE NET

An engine joins the pool only after passing `engine_gate.py`. Before any rating
is read, `pgn_endings.py` checks how every game ended, since a forfeit or a
time loss makes the rating untrustworthy. Results go into
`benchmarks/ledger.md`.

## Unattended runs

`tools/match.sh` plays a fixed number of games between two builds at any time
control, with the same checks as an SPRT. It fails if any game ended
abnormally, so a flag test is just a short match:

    tools/match.sh NAME NEW.exe NEW_NODES BASE.exe BASE_NODES TC GAMES

`tools/queue.sh` runs a list of jobs one after another. A job whose
prerequisites failed is skipped, and starting the queue again carries on where
it stopped. Each line of a queue file is `NAME | NEEDS | COMMAND`.

    tools/queue.sh QUEUE_FILE
    tools/queue.sh --stop

## Files

- `match.py`      plain two-engine match
- `sprt.py`       SPRT runner (stops on a decision)
- `test_sprt.py`  unit tests for the SPRT statistics and stopping rule
- `chesslite.py`  perft-verified board/movegen used to arbitrate games
- `book_gen.py`   balanced-book generator (uses the engine's eval)
- `book.epd`      starter book (150 balanced positions)
- `fastchess.md`  fastchess / cutechess-cli setup and command
- `engine_gate.py` UCI checks an engine must pass before joining the pool
- `pgn_endings.py` counts games that ended abnormally
- `spsa.py`       SPSA tuner; its steps are too large (METHODOLOGY §10)

`sprt.py` decides whether a change ships, so its arithmetic is checked rather
than trusted. The tests pin closed-form values (the Elo formula is analytic),
invariants that must hold for any correct implementation (antisymmetry,
monotonicity, the 1/sqrt(n) shrink of the interval), and the decision rule
itself including the minimum-games guard. No engine is started, so:

    python3 -m unittest discover -s testing -p "test_*.py"

runs in milliseconds, and CI runs it on every push.
