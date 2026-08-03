# Sgurr

A UCI chess engine in C++20 with an NNUE evaluation trained on its own
self-play games. Current release is **v8.1 "Thearlaich"** at **3027 ±11** on a
CCRL-Blitz-anchored scale.

The evaluation pipeline is built end to end in this repository: the self-play
data generator, the PyTorch trainer, the quantisation scheme, the network file
format, and the AVX-512 inference that reads it. Each generation of the network
is trained on positions labelled by the previous generation, so the engine is
its own teacher. External engines appear only as rating anchors, never in the
training loop.

There is also an earlier pure-Python engine kept as a reference implementation.

---

## Strength

| engine | rating (CCRL-Blitz-anchored, pool-2026-07-B) |
|---|---|
| Sgurr v8.1 "Thearlaich" | **3027 ±11** |
| Sgurr v8.0 "Thearlaich" | 3006 ±11 |
| Sgurr v7.0 "Ghreadaidh" | 2903 ±6 |
| Sgurr v6.0 "Banachdaich" | 2807 ±36 |
| Sgurr v5.0 "Gillean" | 2724 ±36 |
| Sgurr v4.0 "MacKenzie" | 2604 ±27 |
| Sgurr v3.0 "Blackpeak" | 2590 ±39 |
| Sgurr v3.1 "Blackpeak" | 2541 ±27 |
| Sgurr v2.0 "Notches" | 2467 ±34 |
| Sgurr v1.0 "Fox" | 2386 ±34 |
| Sgurr classical (HCE) | 2377 ±35 |

Ratings come from a gauntlet against a fixed pool of open-source engines with
published CCRL Blitz ratings (Blunder, Zahak, Weiss, Igel — four families,
2105–3055), solved with Ordo anchored to those values. They are estimates on
the CCRL Blitz scale, not official CCRL ratings, and the absolute scale is only
as good as the anchors. The *gaps* between versions are anchor-independent.

Anchors were re-sourced from the live CCRL list on 2026-07-15 after an audit
found the previous set inflated by a mean of ~31 Elo; every row above is from
one consistent solve. v7.0 onward were measured on a Ryzen 7 7800X3D, v6.0
and earlier on an i5-9400F. A single Ordo solve places them on one scale, but
cross-hardware absolute gaps carry that caveat — the version-to-version SPRTs,
run on one machine, do not.

Each generational gap in the pool independently reproduces the direct SPRT
between those versions. v4.0's net change, for instance, measured +54 in the
pool against +55.5 ±17.0 in a 1,194-game SPRT.

**v3.1 sits below v3.0** despite a positive interim SPRT at 8+0.08. Its flat
soft time limit loses at the pool's 10+0.1. v4.0 replaced it with best-move
stability scaling, which measures positive at both controls.

---

## How strength is measured, and what it costs to know

`METHODOLOGY.md` is the most useful file in this repository. It records what
was learned rather than what happened, including the results that had to be
withdrawn.

Two things in it are worth stating here.

**The noise floor.** Two networks trained on identical data with an identical
recipe, differing only in random seed, score **+13.7 ±10.3** against each other
over 3,000 games. Training is not reproducible at the Elo level. That number
had been assumed to be zero for the project's entire history, and measuring it
invalidated several published conclusions — including a width result that had
already been recommended for the next generation. Anything below roughly ±25
Elo on a network change is not distinguishable from seed luck without training
several seeds per configuration.

Search changes reuse one fixed network and carry no training variance, so they
are far cheaper to validate. That asymmetry drives most of the planning here.

**Training loss does not predict strength.** Across five instances on identical
data the ranking inverted completely: the variant with the best loss (0.00471)
measured +2 Elo, and the variant with the worst loss (0.00661) measured +9.
Loss is not merely uninformative, it is anti-correlated. The standing rule is
that no architecture, dataset size, or hyper-parameter is ever selected on
loss. Only games decide.

Related files: `CHANGELOG.md` for released versions with error bars,
`benchmarks/ledger.md` for the append-only record of every rating measured,
`DEVLOG.md` for the dated engineering log, and `ROADMAP.md` for what is next.

---

## Releases

Versions are named after Sgùrr peaks in ascending height. Version numbers are
canonical; peak names are codenames.

| version | codename | peak | summary |
|---|---|---|---|
| v1.0 | Fox | Sgùrr a' Mhadaidh | first NNUE (gen1): parity with the classical eval |
| v2.0 | Notches | Sgùrr nan Eag | gen2 NNUE: +77.7 ±37.4 vs v1.0 (300 games, 8+0.08) |
| v3.0 | Blackpeak | Sgùrr Dubh Mòr | gen3 NNUE: +119.8 ±26.3 vs v2.0 (618 games, SPRT); 2616 ±37 |
| v3.1 | Blackpeak | Sgùrr Dubh Mòr | search-only: soft/hard time management. Calibrated 2564 ±26, below v3.0 — the flat soft limit loses at 10+0.1. Superseded in v4.0 |
| v4.0 | MacKenzie | Sgùrr MhicChoinnich | gen5 NNUE (768→384, first architecture change): +55.5 ±17.0 vs the gen3 engine (1,194 games, SPRT), plus history malus and best-move-stability time management; 2627 ±27 |
| v5.0 | Gillean | Sgùrr nan Gillean | search-only on the gen5 net: reverse futility pruning (+176.4 ±15 self-play, factorial) and LMP; 2724 ±36, +119 vs v4.0 in the same solve. The gen6 net measured flat and was not shipped |
| v6.0 | Banachdaich | Sgùrr na Banachdaich | search refinement package: improving flag, history-adjusted LMR, singular extensions. +57.3 ±17.0 vs v5.0 (1,139 games, SPRT); **2807 ±36**, first version above the old pool's ceiling |
| v7.0 | Ghreadaidh | Sgùrr a'Ghreadaidh | gen7 NNUE, the first clean RFP-free datagen regen: +44.4 ±18.8 vs v6.0 against gen6's +6 wash — the labels really were the bottleneck. 2903 ±6 over an 8,522-game solve. AVX-512/int16 inference landed here, ~+22% NPS and bit-identical |
| v8.0 | Thearlaich | Sgùrr Thearlaich | gen8 NNUE on 55.9M clean positions: **+126.5 ±26.6 vs v7.0**, the largest single-cycle gain in the project. **3005.5 ±11** over 3,329 games. King buckets were tested on the same data and measured flat (−10.7 ±16, despite 12% lower loss), so the shipped net is the plain 768→384 |
| v8.1 | Thearlaich | Sgùrr Thearlaich | speed-only on the gen8 net: PGO + ThinLTO and nine node-identical optimisations, ~20% NPS. **+21.2 ±8.7 vs v8.0** self-play and **+20.9 pooled** — the two agree to 0.3 Elo, so no compression. **3027 ±11**; the first version whose interval clears 3000 outright. Same net, same search, same moves |

---

## What is in the engine

### Board and move generation

* Bitboards with magic-bitboard sliders
* Legality decided without make/unmake — a per-node structure carries the king
  square, checker count, pin mask and check mask, so each move is answered in
  O(1)
* Incremental Zobrist hashing, verified against full recomputation
* Full static exchange evaluation with x-ray resolution and a king-legality
  rule, plus a threshold-only variant with early exit
* `perft` against known reference counts

### Search

* Iterative deepening with aspiration windows
* Negamax, alpha-beta, principal variation search
* Transposition table, runtime-sized via the `Hash` option
* Null-move pruning
* Late move reductions, adjusted by history
* Reverse futility pruning and late move pruning
* Razoring at shallow depth
* Singular extensions, implemented with the excluded-move search correctly
  isolated: no TT cutoff, no null move, and no TT store while a move is excluded
* Check extensions
* Improving flag, feeding both the RFP margin and the LMP quiet budget
* Quiescence search with delta pruning and SEE pruning
* Killer moves, butterfly history with malus, continuation history
* Good/bad capture split by SEE, ordered between killers and quiets
* Draw detection by repetition and the fifty-move rule
* Time management: soft and hard clock limits, a move-overhead margin, and
  best-move-stability scaling of the soft limit

The features added since v4.0 each carry a compile-time toggle — `SGR_RFP`,
`SGR_LMP`, `SGR_IMPROVING`, `SGR_HISTLMR`, `SGR_SINGULAR`, `SGR_HMALUS`,
`SGR_CONTHIST`, `SGR_BMSTAB` — so any one of them can be A/B tested from a
single source tree without a branch.

### Evaluation

The shipped evaluation is the NNUE: a `768 → 384 → 1` perspective network,
integer-quantised throughout, with accumulators updated incrementally through
make and unmake. Inference dispatches to AVX-512, AVX2 or scalar depending on
the build target; all three produce bit-identical output, so the vector paths
are a speed change and never a numeric one. Every accumulator hook checks the
position's Zobrist key before touching anything and falls back to a full
rebuild on a mismatch, so a missed update can cost speed but not correctness.

A hand-crafted evaluation is still in the tree and is used when no network
loads — tapered material and piece-square tables, pawn structure with a cache,
king safety, mobility, and a mop-up term for bare-king endings. It is roughly
630 Elo weaker than the NNUE and exists as a fallback and a reference.

---

## Building and running

`build.sh` in `sgurr_cpp/` runs the documented recipes and then checks that the
resulting binary actually starts:

```bash
./build.sh                     # development build   -> sgr.exe
./build.sh -r                  # release build       -> sgr.exe  (PGO + ThinLTO)
./build.sh -d                  # data generator      -> datagen.exe
```

The release build is worth **+11.3% NPS** over plain `-O3 -march=native`,
measured over 12 interleaved runs, with an identical search fingerprint.

The verification step is not decoration. Smart App Control on the development
machine intermittently refuses to start freshly linked unsigned binaries, and
an engine that cannot start does not crash a match — it forfeits every game and
still produces a complete, plausible-looking result. `build.sh` relinks until
the binary runs, and both `testing/sprt.py` and `pipeline.py` verify every
engine before playing.

Building by hand needs a C++20 compiler; see `sgurr_cpp/BUILD.md` for the
toolchain notes, the full PGO recipe, and the data generator.

Run it:

```bash
./sgr.exe                      # bare launch defaults to UCI
```

```text
uci
setoption name Hash value 256
position startpos moves e2e4 e7e5
go movetime 1000
```

The engine advertises 30 UCI options: `Hash`, `Clear Hash`, `Move Overhead`,
`Threads`, and 26 search parameters — every margin, divisor and threshold in
the search, exposed so they can be tuned. None of them has been swept yet.

`Threads` is pinned at 1. The engine is single-threaded on purpose: the rating
scale used here is single-core, so a parallel search would measure exactly
zero.

---

## Testing and verification

**`bench`** is the main instrument.

```bash
./sgr.exe bench                # 19 fixed positions at depth 11
./sgr.exe bench 13
```

It searches a fixed position list to a fixed depth. The search is deterministic
— no clock, no randomness, heuristics cleared between positions — so the node
counts are a fingerprint of what the engine searches. Any change that is meant
to be speed-only must leave that fingerprint byte-identical. If it moves, the
change altered behaviour and the speedup is not free.

The fingerprint goes to stdout and everything non-deterministic to stderr, so
comparing two builds is:

```bash
diff <(old.exe bench 2>/dev/null) <(new.exe bench 2>/dev/null)
```

That turned a whole category of work into something provable without playing
games. The AVX-512 inference, the PGO build, and nine separate data-layout
optimisations were all verified this way.

The rest:

* `perft` for move generation
* Make/unmake checked by restoring board state and hash keys
* Incremental Zobrist checked against full recomputation
* Null moves checked for correct restoration
* `seetest` runs static exchange evaluation against hand-verified tactical
  cases, including x-rays, en passant and the king-capture rule
* `nnue_selfcheck` compares engine inference against the trainer's own forward
  pass and produces a cross-build evaluation checksum
* Search changes are decided by SPRT at 8+0.08; releases are calibrated against
  the pool
* Every rating is reported with an interval

---

## Training pipeline

One resumable command produces a network generation:

```bash
python pipeline.py pipeline_gen8.json           # run or resume the cycle
python pipeline.py pipeline_gen8.json --status  # stage progress
```

The stages are: parallel self-play **datagen** with balance-filtered openings →
**freeze** into a versioned dataset with a per-shard manifest and checksums →
**train** → **build** → **select** the best variant by games → **SPRT** against
the previous generation → pool **calibrate** with Ordo → append to the
**ledger**. Every stage checkpoints, so the pipeline can be interrupted and
resumed. Datasets, weights and ledger rows are append-only.

The generator writes 32-byte records and is resumable, shard-tagged so parallel
workers never collide, and safe to kill — loaders floor to whole records, so a
torn tail is ignored. Labeller builds must be compiled with `-DSGR_RFP=0`;
reverse futility pruning returns an unsearched score where a searched one is
expected, and that mistake cost an entire generation.

---

## Legacy Python engine

An earlier self-contained implementation with its own board representation,
move generation, FEN parsing, Zobrist hashing, evaluation and search. It runs
in UCI mode or as an interactive terminal program.

```bash
python -m sgurr_python.sgurr_engine uci
python -m sgurr_python.sgurr_engine       # interactive
```

Interactive commands: `display`, `moves`, `best`, `go 5`, `move e2e4`, `new`,
`quit`. Default maximum depth is 8.

Benchmarked against Stockfish limited to 1500 Elo at 0.50 s/move, it scored
~49.6% over 1000 games. It is kept as a readable reference, not as a strength
target.

---

## The name

Sgùrr is Gaelic for a rocky mountain peak. The engine name is plain-ASCII
`Sgurr` and the binary is `sgr`. It was called Ruk before that, and Bitfish
before that.
