# Bitfish Texel Tuning — Runbook

This kit tunes Bitfish's hand-set evaluation constants against real game
outcomes by logistic regression (Texel's method). It optimises the engine's
**actual** `Board::evaluate()` — the tuner `#include`s `evaluation.cpp`, so
there is no separate eval reimplementation to drift out of sync.

## The one guarantee that matters

The refactored `evaluation.cpp` is **behaviourally bit-identical to v13** at its
default values. Verified two ways before shipping:
- `evaluate()` over a FEN set: identical to the v13 binary.
- Fixed-depth search over the 6-FEN suite: identical nodes, scores, TT hits,
  and moves vs `bitfish_v13`.

The only change is a macro: `EVAL_PARAM` expands to nothing under `-DTUNING`
(parameters become mutable globals the tuner can poke) and to `constexpr` in
your normal build. So your current engine is unchanged until *you* paste tuned
numbers in.

## Files (drop into your Bitfish source dir)

- `evaluation.cpp`   — REPLACES your current one (identical behaviour; enables tuning)
- `selfplay.cpp`     — self-play game generator → quiet positions
- `pgn_extract.cpp`  — turns your benchmark PGNs into the same position format
- `texel_tune.cpp`   — the tuner (K-fit + coordinate descent, held-out split)
- `ab_match.cpp`     — A/B self-play validator (tuned vs default), the safety gate
- `run_tuning.sh`    — one-shot: build → generate → extract → merge → tune

Your other files (`board.*`, `search.*`, `main.cpp`, `move.hpp`) are unchanged
from v13.

> Windows note: `run_tuning.sh` uses `nproc`, `seq`, and background jobs, so run
> it under WSL / MSYS2 / Git-bash (same place you run `compare_search.sh`). If
> you only have native cmd, run the build/generate/tune commands by hand — they
> are all listed in the script.

---

## Your data question

300 benchmark games ≈ ~25–30k quiet positions after extraction. That is usable
but **thin**, and the positions are heavily correlated (many per game), so it
over-fits easily — especially anything high-dimensional like PSTs.

Targets:
- **Scalars** (material + bonuses/penalties, ~25 params): **~100k positions** is
  comfortable.
- **PSTs** (mode `all`, ~768 params): want **300k–500k+**.

Two sources, combined:
1. **Self-play** (the bulk). `run_tuning.sh` plays `GAMES_PER_CORE × cores` games
   from randomised 8-ply openings at a fixed depth and samples quiet positions.
2. **Your PGNs** (free diversity). Put your benchmark PGN in the source dir as
   `benchmark.pgn`; the script extracts it automatically. Combine all the PGNs
   you've saved into one file first.

Honest caveat on self-play data: it teaches the eval to be internally
consistent (better at beating *itself*), which correlates with — but is not
identical to — beating Stockfish. That's standard Texel practice and reliably
worth tens of Elo. The `ab_match` gate and your Stockfish benchmark are the
real arbiters of whether it worked.

---

## Workflow

### Step 1 — calibrate throughput (2 min)

Edit the CONFIG block of `run_tuning.sh`: set `GAMES_PER_CORE=20`, `MODE=scalars`.
Run it once and watch the wall-clock for the self-play stage. Depth-6 games are
short; on your hardware (~680k nps in the benchmark, and multi-core) they'll be
much faster than a tournament game. Use the observed per-game time to pick a
real `GAMES_PER_CORE` that yields ~100k positions:

    positions ≈ GAMES_PER_CORE × cores × ~60

So ~1,600 games gets you in the ballpark. On 8 cores that's `GAMES_PER_CORE=200`.

### Step 2 — generate + tune scalars

    ./run_tuning.sh

Tuned constants land in `tuned_params.txt`. Read the log as it runs:
- `fitted K = ...` — the sigmoid scale; ~0.7–1.3 is normal.
- Each sweep prints `train E` and `valid E` (held-out, every 10th position).
  **Both should fall together.** If `valid E` starts rising while `train E`
  keeps dropping, that's over-fit — stop trusting later sweeps, and get more
  data.

Sanity-check the numbers before believing them. Penalties should stay positive,
bonuses positive, material ordering sane (N≈B < R < Q). The smoke run that built
this kit produced nonsense (negative doubled-pawn penalty, negative bishop pair,
`BISHOP_MOBILITY_BONUS=33`) precisely because it had only ~1k positions — a live
demonstration of what too-little data looks like. With ~100k it settles down.

### Step 3 — validate with A/B self-play (the gate)

Build the validator (needs `-DTUNING`):

    g++ -std=c++20 -O2 -DTUNING ab_match.cpp board.cpp search.cpp -o ab_match

Run a colour-balanced match, tuned (A) vs current default (B):

    ./ab_match tuned_params.txt 100 6 1     # 100 pairs = 200 games, depth 6, seed 1

It swaps colours each pair (opening luck cancels) and uses identical search on
both sides — only the eval differs. **Only proceed if A's Elo delta is clearly
positive** (the ±1σ margin it prints is wide at 200 games; want the delta well
clear of it). If A is flat or negative, do not touch the engine — get more data
or stay on scalars. This step costs minutes and saves you a 50-minute Stockfish
benchmark on a bad tune.

### Step 4 — apply and benchmark

If A/B is positive, edit the default values in `evaluation.cpp` to match
`tuned_params.txt`. For scalars this is ~25 direct substitutions — the names map
one-to-one onto the `EVAL_PARAM` lines:
- `PIECE_VALUE_KNIGHT/BISHOP/ROOK/QUEEN` → `PIECE_VALUE[1..4]` **and** their
  mirror `[7..10]` (black copies — keep equal).
- `PASSED_PAWN_BONUS_rN` → `PASSED_PAWN_BONUS[N-1]`.
- Everything else is a same-named scalar.

Rebuild your normal engine and run your usual 100-game Stockfish benchmark. That
is the final word.

### Step 5 (later session) — PSTs

Once you have 300k+ positions, set `MODE=all`. Two changes I'd want to make
first, so flag it when you get there:
- The held-out split is currently per-position, and positions from one game are
  correlated, so it under-estimates over-fit for 768-param PST tuning. We should
  switch to **game-level** holdout for that round.
- I'll give you a small `apply_tuned.py` to paste the PST grids back
  automatically (hand-editing 768 numbers is error-prone).

---

## Build reference (if running by hand)

    # normal engine (constexpr eval — unchanged behaviour)
    g++ -std=c++20 -O2 main.cpp board.cpp evaluation.cpp search.cpp -o bitfish

    # tools
    g++ -std=c++20 -O2 selfplay.cpp board.cpp evaluation.cpp search.cpp -o selfplay
    g++ -std=c++20 -O2 pgn_extract.cpp board.cpp evaluation.cpp -o pgn_extract
    g++ -std=c++20 -O2 texel_tune.cpp board.cpp -o texel_tune          # in-file #define TUNING
    g++ -std=c++20 -O2 -DTUNING ab_match.cpp board.cpp search.cpp -o ab_match

    # generate one shard
    ./selfplay selfplay <games> <depth> <seed> out.csv >/dev/null 2>log
    # extract a PGN
    ./pgn_extract benchmark.pgn pgn.csv
    # tune
    ./texel_tune all_positions.csv scalars | tee tuned_params.txt

## What to send back

Just two things, so we keep the next session short:
1. The `ab_match` result line (score + Elo delta).
2. Your 100-game Stockfish benchmark summary.

That tells us whether scalars-Texel paid off and whether to push on to PSTs.
