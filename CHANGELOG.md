# Changelog

Versions are named after Sgùrr peaks in ascending height; version numbers are
canonical, codenames are flavour. All Elo figures are measured self-play match
results with 95% error bars — never estimates.

## v8.2 "Thearlaich" (Sgùrr Thearlaich) — 2026-08-04

A second speed-only release. Node-identical to v8.1: same net, same search,
same moves, ~15% faster.

- **3058 ±7 on pool-2026-07-B**, over 11,144 games at 10+0.1 (+8332 =1204 -1608,
  80.2%). That is **+31.5 vs v8.1 in the same solve**, from **+15.4% NPS**
  (median of 10 interleaved `bench 13` runs, release builds either side,
  distributions non-overlapping across all 20).
- **The speed rule was predicted in advance and it missed.** ~70 Elo per
  doubling of NPS put v8.2 at 3041, i.e. +14.5; the gauntlet says +31.5, an
  implied ~131 per doubling. Solving each anchor independently gives +29
  (Weiss-1.2), +21 (Igel), +31 (Weiss-1.0) and +28 (Zahak-5.0) — all four agree,
  so this is not the rating solver. v8.1 had matched the same rule to 0.3 Elo,
  which now reads as coincidence rather than confirmation, and the conversion is
  no longer used to predict anything.
- Two limits found while measuring this, both recorded in full in `ledger.md`:
  the four anchors disagree by **90 Elo** about v8.2's absolute rating, so ±7 is
  sampling noise only and systematic uncertainty is nearer ±45; and v8.2 scores
  **50.8%** against the top of the pool, which therefore cannot measure v8.3.
- **Transposition entry packed 24 → 16 bytes.** A 64-byte cache line now holds
  exactly 4 entries instead of 2.67, on the hottest random-access structure in
  the engine. The full 64-bit key is kept: truncating to 32 bits saves four
  more bytes but raises collisions, and a collision changes what the search
  finds — that would turn a free layout change into one needing hours of games.
  Note the default `Hash=48` keeps the same 2,097,152 entries in 32 MB rather
  than gaining capacity, because counts round down to a power of two; non-default
  sizes do gain, with `Hash=64` now giving 4.2M entries instead of 2.1M.
- **Lazy move picker.** `order_moves` bucketed every move, sorted all four
  buckets, then returned a flat `MoveList` **by value** — 514 bytes copied per
  node. Most nodes cut off within the first few moves, so the two quiet sorts
  (the largest buckets) were paid for almost everywhere and thrown away. The
  picker emits the identical sequence but sorts a bucket only when a move is
  wanted from it. `std::sort` is not stable, so order preservation is enforced
  by the bench fingerprint rather than argued.
- **`go depth` is clamped to `MAX_PLY - 1`.** Previously unbounded, which would
  have overflowed the packed entry's `int8` depth. `bench` runs at depth 11–13
  and would never have caught it.
- **Training loader can now exceed 150M positions.** `train.py` held the decoded
  form of every position in RAM at ~137 B/position, which broke between 150M and
  200M on a 33.5 GB machine — while the datagen script caps at 200M and the data
  study found returns still accelerating at 56M. A memory-mapped streaming path
  decodes per batch instead. Verified byte-identical: same batches, same loss to
  five decimals, and the two exported nets share a sha256.

**Held back:** the ten-item v9.0 search batch measured **−1.0 ±21.1** over 698
games. Inconclusive rather than negative, but an interval spanning −22…+20 makes
a true −15 entirely consistent with the data, and shipping it beside a validated
speed gain would have risked a regression nothing could rule out. The code
remains in the tree behind per-item toggles, default off, awaiting machine time.

## v8.1 "Thearlaich" (Sgùrr Thearlaich) — 2026-08-03

A speed-only release: the same net, the same search, the same moves, about 20%
faster. There is no behavioural change here at all.

- **Strength: +21.2 ±8.7 Elo vs v8.0** (+1521 =1202 −1277, 4,000 games,
  8+0.08s). **CCRL-Blitz-anchored: 3027 ±11** on pool-2026-07-B (+2492 =388
  −576, 3,456-game gauntlet @ 10+0.1), **+20.9 vs v8.0 in the same solve**.
  The two figures agree to 0.3 Elo.
- **First version whose interval clears 3000 outright.** v8.0's [2995, 3016]
  straddled it at ~84% confidence; v8.1's [3016, 3038] does not touch it.
- **PGO + ThinLTO release build** (+11.3% NPS). Profile-guided optimisation
  replaces the compiler's guesses about which branches are hot with a recording
  of the branches this engine actually takes; ThinLTO lets it optimise across
  `.cpp` boundaries at link time. `build.sh -r` runs the whole recipe.
- **Nine node-identical optimisations** (+7.98% NPS): a precomputed LMR
  reduction table (it was calling `std::log` twice per late move), direct
  slider dispatch, TT prefetch after make_move, `std::optional` out of the hot
  structures, a fixed repetition ring instead of a heap vector, incrementally
  cached occupancy, `gives_check` from precomputed geometry rather than a full
  attack scan, and capture-only generation for quiescence.
- **Every one verified byte-identical** on the new `bench` fingerprint
  (13,614,729 nodes at depth 13) before being kept. A tenth change — bulk-shift
  pawn generation — moved the fingerprint and was reverted, correct move set or
  not.
- **`bench` command**: a fixed position list at fixed depth, deterministic, so
  its node counts fingerprint what the engine searches. Any change meant to be
  speed-only must leave it unchanged. This is what made the above provable
  without playing a single game.
- **30 UCI options**, where there were previously none: `Hash`, `Clear Hash`,
  `Move Overhead`, `Threads`, and 26 search parameters. Defaults reproduce the
  previous constants exactly.
- **UCI conformance fixes**: mate scores are now `score mate <n>` rather than a
  ~10,000-pawn centipawn value; transposition-table telemetry moved from
  `tbhits` (which means *tablebase* hits, and this engine has none) to
  `hashfull`; `nps` added; a terminal root no longer reports the −INF sentinel
  as a score. The `id name` string had also read "Sgurr 7.0" throughout v8.0's
  life, including its calibration.
- **Validates the NPS→Elo conversion.** Speed gains had been converted through
  the ~70-Elo-per-doubling rule since 2026-07-22 and flagged *inferred*.
  Predicted +18.4; measured +21.2 self-play and +20.9 pooled.

## v8.0 "Thearlaich" (Sgùrr Thearlaich) — 2026-07-29

The gen8 flywheel turn, and the largest single-cycle gain in the project.

- **Strength: +126.5 ±26.6 Elo vs v7.0** (SPRT, H1). **CCRL-Blitz-anchored:
  3006 ±11** on pool-2026-07-B (3,329-game gauntlet @ 10+0.1), **+103 vs v7.0
  same-solve** — mild ~0.8× compression, consistent with the large-gain
  pattern.
- **gen8 net on 55.9M clean positions**, labelled by the v7.0 net at 150k
  nodes/position over ~7 days. The student beating its teacher by +126 is the
  flywheel working as designed: search-amplified labels carry far more than the
  labeller's own evaluation.
- **King buckets tested and rejected.** An 8-bucket variant on the same data
  measured −10.7 ±16 despite 12% lower training loss. The shipped net is the
  plain 768→384. The bucket code remains, verified and dormant, for retest when
  the dataset grows.
- λ-sweep winner 0.9.

## v7.0 "Ghreadaidh" (Sgùrr a'Ghreadaidh) — 2026-07-22

The first clean regeneration, and proof that the labels were the bottleneck.

- **Strength: +44.4 ±18.8 Elo vs v6.0** (SPRT, both AVX-512 int16 builds so the
  net was the only variable). **CCRL-Blitz-anchored: 2903 ±6** on pool-2026-07-B
  over an 8,522-game solve.
- **gen7 net, generated RFP-free.** gen6 had been produced by a labeller built
  with reverse futility pruning, which returns an unsearched static eval where a
  searched score is expected; under a fixed node budget that quietly poisoned
  every label and cost the entire generation (+6 ±20, a wash). Labeller builds
  are now required to pass `-DSGR_RFP=0`.
- **AVX-512 / int16 NNUE inference** (~+22% NPS), bit-identical to the scalar
  path and verified node-identical at fixed depth. The evaluation had been
  running plain scalar loops until this point.
- ⚠️ The absolute figure is cross-hardware: v6.0 and earlier were measured on an
  i5-9400F, v7.0 onward on a Ryzen 7 7800X3D.

## v6.0 "Banachdaich" (Sgùrr na Banachdaich) — 2026-07-16

A search-refinement package on the unchanged gen5 net — the second search-only
release in a row, and the first version to pass the old pool's ceiling.

- **Strength: +57.3 ±17.0 Elo vs v5.0** (+505 =316 −318, 1,139 games, 8+0.08s,
  SPRT [0, 5] H1 accepted). **CCRL-Blitz-anchored: 2807 ±36** on
  pool-2026-07-B (+117 =38 −85, 240-game gauntlet @ 10+0.1), **+83 vs v5.0 in
  the same solve** — statistically indistinguishable from the self-play
  figure, so the package expressed at least fully. New project high.
- **Improving flag** (`SGR_IMPROVING`): the static eval is recorded at each
  ply and compared with the same side's eval two plies up. A rising eval is a
  more trustworthy bound, so reverse futility prunes with one ply less margin;
  a falling one means the worst-ordered quiets are even less likely to rescue
  the position, so late move pruning halves its quiet budget. Also removes a
  double `evaluate_position` at depth ≤ 2.
- **History-adjusted LMR** (`SGR_HISTLMR`): a quiet's late-move reduction is
  nudged ±2 plies by its butterfly + continuation history — proven quiets
  reduced less, serial failures more. This is the pruning interaction
  continuation history has been waiting for since it measured ≈ 0 alone.
- **Singular extensions** (`SGR_SINGULAR`): at depth ≥ 7, when the TT move
  carries a lower-bound score from a nearly-as-deep search, the remaining
  moves are searched reduced against a window below it; if none reaches it,
  the TT move is extended a ply. TT cutoff/store and null move are disabled
  inside the excluded-move helper search.
- The three shipped together and are **not decomposed** — the +57 is the
  package. Each is individually toggleable (`-DSGR_IMPROVING=0` etc.).
- Engine reports `id name Sgurr 6.0`. All three toggles default on, so a bare
  rebuild is the shipped engine; the release binary was verified
  node-identical at fixed depth to the build that took the SPRT.
- Also recorded this cycle, both negative: **HL=512 on the gen6 8M is flat**
  (−5.5 ±22, stopped early — third confirmation those labels are exhausted,
  after the probe's "saturated" and the gen6-net wash), and **a larger
  transposition table buys nothing at blitz** (−12.0 ±15.7; the fixed-depth
  node savings are real but live above ~2M nodes, which 8+0.08 never reaches).
  See `DEVLOG.md`.

## v5.0 "Gillean" (Sgùrr nan Gillean) — 2026-07-15

A search-only release: reverse futility pruning (with LMP) on the unchanged
gen5 net. The gen6 net was trained but measured flat and is not shipped; the
release also moves absolute ratings onto a re-anchored pool.

- **Strength: +176.4 ±15 self-play vs v4.0** (the 07-11 factorial's `both`
  arm — this exact configuration; 3,600 games at 8+0.08).
  **CCRL-Blitz-anchored: 2724 ±36** on pool-2026-07-B (+97 =34 −109, 240-game
  gauntlet @ 10+0.1), **+119 vs v4.0 in the same solve** (2604 ±27) — the
  first large search gain this project has pool-measured, expressing about
  two-thirds of its self-play value where small search gains had compressed
  to nothing.
- **Scale note: pool-2026-07-B re-anchors every opponent to the live CCRL
  Blitz list.** An audit found pool-A's values were README figures, inflated
  by ~31 on average, and Blunder-7.2.0 was never CCRL-Blitz-rated at all (it
  now floats, and solves to 2431 — validating the method). All historical
  rows shift ~−22; compare within one Ordo solve only, never across pools.
  New upper anchors Weiss 1.0 (2896), Igel 2.2.2 (2982), Weiss 1.2 (3055):
  v5.0 landed level with Zahak 5.0 (2726), the old ceiling, so the headroom
  was necessary rather than cosmetic.
- **gen6 NNUE: not shipped.** The full pipeline ran (8.0M positions, gen5
  labeller @ 150k nodes, probe "saturated" at 0.441%, λ=1.0 won selection,
  SPRT vs v4.0 +155.0 ±28.6 H1 accepted) but a 1,200-game net-isolated A/B —
  identical search, only the net swapped — measured the net itself at
  **+6 ±20, a wash**. Diagnosis: **RFP poisons fixed-node labels.** It
  returns the raw static eval where a search score is expected, and at a
  fixed node budget its speed win buys nothing, so gen6's labels echoed the
  gen5 labeller's own opinions. Rule adopted: labeller/datagen builds get
  `-DSGR_RFP=0`; RFP belongs in the playing engine, not the labeller.
- Pipeline hardening from the run: the SPRT baseline and the calibrated
  release engine are now explicit config keys (generation and version
  numbering diverged at gen5/v4.0, which left both SPRT engines named
  identically — fastchess refused to start); the Elo parser is anchored
  `\bElo` (it had also matched fastchess's `nElo` and recorded the normalised
  value, ~35 points flattering).
- Engine reports `id name Sgurr 5.0`. Bare-build defaults still describe the
  shipped engine; the v6.0 search candidates (`SGR_IMPROVING`,
  `SGR_HISTLMR`, `SGR_SINGULAR`) are in-tree but default off pending SPRT.

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
