# Changelog

Versions are named after Sgùrr peaks in ascending height; version numbers are
canonical, codenames are flavour. All Elo figures are measured self-play match
results with 95% error bars — never estimates.

## v4.0 "MacKenzie" (Sgùrr MhicChoinnich) — 2026-07-10

The gen5 NNUE — the first architecture change since NNUE arrived — plus two
measured search improvements, all landed and tested in one day.

- **Strength: +55.5 ±17.0 Elo vs the gen3 engine from the net alone**
  (+580 =223 −391, 1,194 games, 8+0.08s, SPRT [0, 5] H1 accepted), with the
  search changes measured separately on top (below).
  **CCRL-Blitz-anchored: 2627 ±27** (+216 =60 −144, 420-game gauntlet @
  10+0.1, Ordo over all accumulated calibration games — see
  `benchmarks/ledger.md`). +63 over v3.1 on the pool scale; statistically
  level with the same engine measured before the history changes
  (2635 ±26) — the self-play malus gain compresses against a diverse pool.
- Net: 768→**384**→1 perspective NNUE (hidden layer widened from 256), trained
  on 6.0M self-play positions labelled by the v3.0 net at 150,000 nodes/move
  (dataset `data/v4.0`). The same dataset retrained at 256 (gen4) had
  *regressed* −28.8 ±22.3 and was never released: the 256 net was saturated,
  and the +55.5 confirms capacity, not label quality, was the wall.
- Search: **history malus** — on a quiet beta cutoff the quiets already tried
  are penalised, not just the cutoff move rewarded. Measured **≈ +33 Elo**
  (2×2 factorial round-robin, 2,158 games, malus arms vs non-malus arms,
  split error ≈ ±9). Continuation history landed alongside it (≈ 0 Elo alone
  at the current search — kept, toggleable, feeds the next round of pruning
  work).
- Time management: **best-move-stability scaling** of the soft limit (stretch
  while the root best move keeps changing, trim once it has held). +17 at
  10+0.1 / +6 at 8+0.08 versus the flat soft limit — and the flat v3.1 soft
  limit itself measured **−48 vs v3.0 at 10+0.1** (see below), so the
  adaptive version replaces it.
- v3.1's deferred calibration debt settled: **2564 ±26**, *below* v3.0's
  2613 ±38 — the flat soft limit loses at the pool time control despite its
  positive interim SPRT at 8+0.08. Lesson recorded: time-management results
  do not transfer across TCs; test at the TC that matters.
- Engine reports `id name Sgurr 4.0`. Build defaults now describe the shipped
  engine: `SGR_HL=384` in engine and trainer (rebuild older 256-wide nets
  with `-DSGR_HL=256`); search features behind default-on toggles
  (`SGR_BMSTAB`, `SGR_HMALUS`, `SGR_CONTHIST`).

## v3.1 "Blackpeak" (Sgùrr Dubh Mòr) — 2026-07-08

A search-only point release on the **unchanged gen3 net** — time-management
only, no NNUE change. First result off the search track.

- **Time management: soft/hard search limits.** The clock path was hard-limit
  only, so iterative deepening always started a depth it could not finish and
  aborted it mid-search, discarding the roughly 30–40% of each move's thinking
  spent on that unfinished pass. A soft limit (`SOFT_TIME_FRACTION`) now stops
  a new iteration from starting once the budget is mostly gone, so the last
  pass completes and the banked time funds deeper later searches. A
  `MOVE_OVERHEAD_MS` margin is held back for transmission latency (Lichess).
  Explicit `go movetime` and node limits are unchanged, so datagen and
  fixed-time analysis stay bit-identical.
- Engine now reports `id name Sgurr 3.1`.
- **Strength — provisional, not yet a completed test:** an interim SPRT vs the
  v3.0 engine (same gen3 net on both sides, so only the time code differs;
  8+0.08s) was stopped early at 706 games: **+24.6 ±22.7** (+300 =156 −250,
  LLR +0.84, bounds ±2.94). Encouraging and consistently positive, but no SPRT
  bound was crossed and no CCRL calibration was run — full Elo testing is
  deferred to before the next generation. This is the one release whose Elo
  figure is an interim estimate rather than a completed measurement.

## v3.0 "Blackpeak" (Sgùrr Dubh Mòr) — 2026-07-06

The gen3 NNUE: corrected training methodology, same architecture.

- **Strength: +119.8 ±26.3 Elo vs v2.0** (+357 =109 −152, 618 games, 8+0.08s,
  SPRT [0, 5] H1 accepted) — the largest generational gain so far.
  **CCRL-Blitz-anchored: 2616 ±37** (see `benchmarks/ledger.md`); the +125
  pool gap independently reproduces the SPRT.
- Net: 768→256→1 perspective NNUE trained on 3.0M self-play positions
  labelled by the v2.0 net at 150,000 nodes/move (dataset `data/v3.0`).
- Data quality: openings from the balanced book + 4-9 random plies, gated by
  an eval-balance filter (±200cp at a 5,000-node probe); engine state fully
  cleared between unrelated datagen searches (history-heuristic leakage fix —
  damaged pre-fix labels quarantined, damage confirmed by matched-protocol
  retrial).
- Training targets: lambda swept {0.6, 0.7, 0.8, 1.0} and decided by a
  600-game round-robin — **pure search-score targets (lambda=1.0) won**
  (+117 over the field); the WDL blend that helped when labels were shallow
  now dilutes them.
- Corrected training protocol: cosine LR decay (1e-3→1e-5) over a ~2k-step
  budget (12 epochs at 3M). Fixed-epoch constant-LR training was found to
  degrade nets as data (and therefore step count) grew, invalidating earlier
  scaling verdicts; probes now compare at matched optimiser steps
  (`nnue/probe_scaling.py`).

## v2.0 "Notches" (Sgùrr nan Eag) — 2026-07-03

The gen2 NNUE and the training pipeline around it.

- **Strength: +77.7 ±37.4 Elo vs v1.0** (+162 =42 −96, 300 games, 8+0.08s,
  150-opening balanced book, colour-reversed pairs).
- Net: 768→256→1 perspective NNUE trained on 14.5M self-play positions
  labelled by the v1.0 net at 50,000 nodes/move (dataset `data/v2.0`).
- Incremental accumulator: NNUE eval updated on make/unmake instead of full
  refresh per node (~1.66× search speedup; bit-identical output, verified by
  `nnue_selfcheck.cpp`).
- Resumable, parallel-safe data generator (`datagen.cpp`): auto-numbered
  tagged shards, clean Ctrl+C, shared on-disk position target.
- Leakage-safe training: validation held out as contiguous blocks (~whole
  games); random position-level splits measurably inflate validation scores
  through same-game sibling positions.
- Toolchain: builds use MSYS2 **clang64** (`clang++`). The ucrt64 g++ 16.1.0
  miscompiles `std::fstream` at `-O1+` (optimised binaries segfault opening
  files) — do not build with it.

## v1.0 "Fox" (Sgùrr a' Mhadaidh) — 2026-06-24 (retroactive)

First NNUE generation.

- **Strength: +9.3 ±36.3 Elo vs the classical evaluation** (300 games,
  8+0.08s) — statistical parity; the bootstrap gate.
- Net: 768→256→1 perspective NNUE trained on 16.7M self-play positions
  labelled by the classical (hand-crafted) evaluation at depth 8
  (dataset `data/v1.0`).
- Engine loads networks via `SGR_EVALFILE` (falls back to the classical
  evaluation when no net is found). Trainer/engine share one exact
  quantised format (`RUKN` magic — retained across the rename so existing
  weight files remain valid).

## Pre-history

Classical (hand-crafted) evaluation engine, formerly named Ruk (and earlier
Bitfish): bitboards, magic sliders, PVS + iterative deepening, TT, null-move,
LMR, futility, SEE, quiescence; tapered tuned evaluation. Benchmarked ~2520
on an Elo-limited-Stockfish setup (method known-flawed; superseded by the
pool-based benchmark ladder introduced after v2.0).
