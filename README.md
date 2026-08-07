# Sgurr

[![CI](https://github.com/TomGreenwoodPhysics/sgurr-chess-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/TomGreenwoodPhysics/sgurr-chess-engine/actions/workflows/ci.yml)

A UCI chess engine in C++20 with an NNUE evaluation trained on its own
self-play games. The current release, **v8.2 "Thearlaich"**, is internally
calibrated at an estimated **3058** on a CCRL-Blitz-anchored scale, measured
over an 11,144-game gauntlet.

That figure is a self-calibrated estimate, not an official rating. Sgurr has
never been submitted to CCRL and does not appear on any published list. The
±7 quoted below is sampling error only; systematic uncertainty on the absolute
number is nearer **±45**, for reasons set out under [Strength](#strength).

The whole evaluation pipeline is built in this repository end to end: the
self-play data generator, the PyTorch trainer, the quantisation scheme, the
network file format, and the AVX-512 inference that reads it. Each generation
of the network is trained on positions labelled by the previous generation, so
the engine is its own teacher. External engines appear only as rating anchors,
never in the training loop.

Where to read further:

* [docs/METHODOLOGY.md](docs/METHODOLOGY.md) records what was learned rather
  than what happened, including the results that had to be withdrawn. It is the
  most useful file here.
* [benchmarks/ledger.md](benchmarks/ledger.md) is the append-only record of
  every rating ever measured, with game counts and caveats.
* [docs/CHANGELOG.md](docs/CHANGELOG.md) covers the released versions with
  error bars, and [docs/DEVLOG.md](docs/DEVLOG.md) is the dated engineering log.
* [docs/ROADMAP.md](docs/ROADMAP.md) sets out what is next and why.
* [sgurr_cpp/BUILD.md](sgurr_cpp/BUILD.md) has the toolchain notes, the PGO
  recipe and the fingerprint check.

---

## What makes this interesting

The engine is ordinary work of its kind. The measurement discipline around it
is the part worth reading.

Nothing here is selected on training loss, because on this data loss is worse
than uninformative about strength. Across five instances trained on identical
data the ranking inverted completely: the variant with the best loss (0.00471)
measured +2 Elo, and the variant with the worst (0.00661) measured +9. Only
games decide, and that rule exists because the alternative was tried.

The noise floor is measured rather than assumed. Two networks trained on
identical data with an identical recipe, differing only in random seed, score
+13.7 ±10.3 against each other over 3,000 games, so training is not
reproducible at the Elo level. That figure had been taken for zero over the
project's whole history. Measuring it retracted several published results,
including a width finding that had already been recommended for the next
generation. Anything below roughly ±25 Elo on a network change is now
indistinguishable from seed luck unless several seeds are trained per
configuration.

Speed-only work is proved rather than argued. `bench` searches a fixed position
list to a fixed depth with no clock and no randomness, so its node counts are a
fingerprint of *what* the engine searches. A change claimed to be speed-only
has to leave that fingerprint byte-identical:

```bash
diff <(old.exe bench 2>/dev/null) <(new.exe bench 2>/dev/null)
```

The AVX-512 inference, the PGO build and nine separate data-layout
optimisations were all validated that way, without playing a game. If the
fingerprint moves, the change altered behaviour and the speedup was not free.
CI now asserts it on every push.

Results that went the wrong way stay in the tree. v3.1 rates below v3.0 and the
table further down says so. Eight king buckets measured −10.7 ±16 against the
plain 768→384 control despite 12% lower loss, so the control shipped. A
ten-item v9.0 search batch measured −1.0 ±21.1 and was held back.
[docs/METHODOLOGY.md](docs/METHODOLOGY.md) is largely a record of conclusions
that had to be withdrawn.

Predictions are registered before the games are played, with a stated
falsification band.
[benchmarks/v81_speed_prediction.md](benchmarks/v81_speed_prediction.md) was
written before a single v8.1 game: +18 to +19 Elo, roughly 55% confidence of
landing in [+10, +27], and a table saying in advance what each outcome would
mean. It landed inside the band, which appeared to confirm the ~70-Elo-per-
doubling NPS conversion this project had been valuing speed work with.

Then v8.2 broke it. Node-identical to v8.1 and 15.4% faster, the same rule put
it at 3041, a gain of +14.5. The gauntlet says +31.5, an implied ~131 per
doubling. Solving each anchor independently gives +29, +21, +31 and +28, so the
rating solver is not the explanation. v8.1's agreement now reads as
coincidence, and the conversion is no longer used to predict anything here.

---

## Strength

| engine | rating (CCRL-Blitz-anchored estimate, pool-2026-07-B) |
|---|---|
| Sgurr v8.2 "Thearlaich" | **3058 ±7** |
| Sgurr v8.1 "Thearlaich" | 3027 ±11 |
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

Every row is solved from games. None is estimated.

Ratings come from a gauntlet against a fixed pool of open-source engines with
published CCRL Blitz ratings: four families (Blunder, Zahak, Weiss, Igel)
spanning 2105 to 3055, solved with Ordo anchored to those values. They are estimates on
the CCRL Blitz scale produced here, not official CCRL ratings, and the
absolute scale is only as good as the anchors.

**Why the systematic uncertainty is ±45 while the interval is ±7.** v8.2's
11,144 games are enough to place it against each anchor *separately*, and the
four anchors disagree by **90 Elo** about where it sits: Igel says 3106,
Weiss-1.0 says 3016. The spread is not new (63, 100 and 90 for v8.0, v8.1 and
v8.2) and it is not sampling noise. It is what happens when ratings measured
under CCRL's conditions are transferred to a different book, time control and
machine. So ±7 counts coin-flip noise only.

**Version-to-version gaps do not carry that uncertainty**, because they are
measured inside one solve against one pool. Each generational gap
independently reproduces the direct SPRT between those versions: v4.0's net
change measured +54 in the pool against +55.5 ±17.0 in a 1,194-game SPRT.

One further limit, stated plainly: v8.2 scores **50.8%** against Weiss-1.2,
the strongest engine in the pool, and 86-97% against five of the other seven.
The pool can no longer resolve improvements at this level, and a stronger one
is needed before v8.3 means anything.

Anchors were re-sourced from the live CCRL list on 2026-07-15 after an audit
found the previous set inflated by a mean of ~31 Elo; every row above is from
one consistent solve. v7.0 onward were measured on a Ryzen 7 7800X3D, v6.0 and
earlier on an i5-9400F: a single Ordo solve places them on one scale, but
cross-hardware absolute gaps carry that caveat. The version-to-version SPRTs,
run on one machine, do not.

**v3.1 sits below v3.0** despite a positive interim SPRT at 8+0.08. Its flat
soft time limit loses at the pool's 10+0.1. v4.0 replaced it with best-move
stability scaling, which measures positive at both controls.

---

## Architecture

```text
sgurr_cpp/     the engine: bitboard movegen, search, NNUE inference, datagen
nnue/          the trainer: PyTorch model, quantisation, .nnue export, verifiers
nets/          the shipped network, with its release record and SHA-256
pipeline.py    one resumable command from self-play data to a ledger row
configs/       per-generation pipeline configs
testing/       match runner, SPRT harness, SPSA tuner, opening-book generator
benchmarks/    rating pool, CCRL anchors, results ledger, registered predictions
data/          dataset manifests, shard checksums and training logs per version
web/           FastAPI backend + zero-build browser frontend
sgurr_python/  earlier pure-Python engine, kept as a readable reference
tools/         calibration and datagen launchers
docs/          methodology, dev log, changelog, roadmap, provenance, notices
```

### Engine

Bitboards with magic-bitboard sliders. Legality is decided without
make/unmake: a per-node structure carries the king square, checker count, pin
mask and check mask, so each move is answered in O(1). Incremental Zobrist
hashing verified against full recomputation. Full static exchange evaluation
with x-ray resolution and a king-legality rule, plus a threshold-only variant
with early exit.

Search is iterative deepening with aspiration windows over negamax /
alpha-beta / PVS, with: a runtime-sized transposition table, null-move pruning,
late move reductions adjusted by history, reverse futility pruning, late move
pruning, razoring, singular extensions, check extensions, an improving flag
feeding both the RFP margin and the LMP quiet budget, quiescence search with
delta and SEE pruning, killers, butterfly history with malus, continuation
history, a good/bad capture split by SEE, and soft/hard time management with
best-move-stability scaling.

Singular extensions are implemented with the excluded-move search properly
isolated: no TT cutoff, no null move, and no TT store while a move is excluded.

Every feature added since v4.0 carries a compile-time toggle (`SGR_RFP`,
`SGR_LMP`, `SGR_IMPROVING`, `SGR_HISTLMR`, `SGR_SINGULAR`, `SGR_HMALUS`,
`SGR_CONTHIST`, `SGR_BMSTAB`), so any one can be A/B tested from a single
source tree without a branch.

### Evaluation

The shipped evaluation is a `768 → 384 → 1` perspective network,
integer-quantised throughout, with accumulators updated incrementally through
make and unmake. Inference dispatches to AVX-512, AVX2 or scalar depending on
the build target, and all three produce bit-identical output: so the vector
paths are a speed change and never a numeric one. Every accumulator hook checks
the position's Zobrist key before touching anything and falls back to a full
rebuild on a mismatch, so a missed update can cost speed but not correctness.

A hand-crafted evaluation remains in the tree and is used when no network
loads: tapered material and piece-square tables, pawn structure with a cache,
king safety, mobility, and a mop-up term for bare-king endings. It is roughly
630 Elo weaker than the NNUE and exists as a fallback and a reference.

### Training pipeline

One resumable command produces a network generation:

```bash
python pipeline.py configs/pipeline_gen8.json           # run or resume
python pipeline.py configs/pipeline_gen8.json --status  # stage progress
```

The stages are parallel self-play **datagen** with balance-filtered openings →
**freeze** into a versioned dataset with a per-shard manifest and checksums →
**train** → **build** → **select** the best variant by games → **SPRT** against
the previous generation → pool **calibrate** with Ordo → append to the
**ledger**. Every stage checkpoints, so the pipeline survives interruption.
Datasets, weights and ledger rows are append-only.

The generator writes 32-byte records, is resumable and shard-tagged so parallel
workers never collide, and is safe to kill: loaders floor to whole records, so
a torn tail is ignored. Labeller builds must be compiled with `-DSGR_RFP=0`:
reverse futility pruning returns an unsearched score where a searched one is
expected, and that mistake cost an entire generation.

### Web application

`web/` serves the engine in a browser. FastAPI owns one persistent UCI process,
validates chess state with `python-chess`, serves the frontend and an allowlist
of media, and exposes a small JSON API. The frontend is 19 plain ES modules and
12 CSS partials with no build step and no npm runtime dependency. Every
canonical release from the classical evaluation to v8.2 is selectable as an
opponent, with its measured rating shown. See [web/README.md](web/README.md).

---

## Tech stack

| layer | stack |
|---|---|
| engine | C++20, clang from MSYS2 `clang64`, PGO + ThinLTO release build |
| inference | hand-written AVX-512 / AVX2 paths with a scalar fallback |
| trainer | Python 3.12, PyTorch, NumPy |
| tournaments and rating | fastchess, Ordo, plus an in-repo Python SPRT harness |
| web backend | FastAPI, Uvicorn, python-chess |
| web frontend | native ES modules and CSS, no build step |
| browser tests | Playwright |
| desktop GUI | pygame, python-chess |

---

## Building and running

`build.sh` in `sgurr_cpp/` runs the documented recipes and then checks that the
resulting binary actually starts:

```bash
cd sgurr_cpp
./build.sh                     # development build   -> sgr.exe
./build.sh -r                  # release build       -> sgr.exe  (PGO + ThinLTO)
./build.sh -d                  # data generator      -> datagen.exe
```

The release build is worth **+11.3% NPS** over plain `-O3 -march=native`,
measured over 12 interleaved runs, with an identical search fingerprint.

The verification step is not decoration. Smart App Control on the development
machine intermittently refuses to start freshly linked unsigned binaries, and
an engine that cannot start does not crash a match: it forfeits every game and
still produces a complete, plausible-looking result. `build.sh` relinks until
the binary runs, and both `testing/sprt.py` and `pipeline.py` verify every
engine before playing.

Building by hand needs a C++20 compiler; [sgurr_cpp/BUILD.md](sgurr_cpp/BUILD.md)
has the toolchain notes, the full PGO recipe and the data generator.

Run it:

```bash
SGR_EVALFILE=../nets/gen8.nnue ./sgr.exe    # bare launch defaults to UCI
```

```text
uci
setoption name Hash value 256
position startpos moves e2e4 e7e5
go movetime 1000
```

Without `SGR_EVALFILE` the engine falls back to the hand-crafted evaluation and
says so on stdout, so a missing network is visible rather than silent.

The engine advertises 48 UCI options: `Hash`, `Clear Hash`, `Move Overhead`,
`Threads`, and 44 search parameters: every margin, divisor and threshold in
the search, exposed so they can be tuned. None of them has been swept yet.

`Threads` is pinned at 1. The engine is single-threaded on purpose: the rating
scale used here is single-core, so a parallel search would measure exactly zero.

---

## Reproducing the benchmark and the tests

Expected output is given for each command so a mismatch is obvious.

**Note on networks.** Trained `.nnue` files are build artefacts of the training
pipeline and are gitignored, with one exception: `nets/gen8.nnue`, the network
shipped in v8.0, v8.1 and v8.2, is committed so that a clone can reproduce the
release fingerprint. Its release record and SHA-256 are in
[nets/README.md](nets/README.md). With no network at all the engine falls back
to the hand-crafted evaluation and says so on stdout, so both fingerprints are
given below.

```bash
cd sgurr_cpp

# Deterministic search fingerprint: 19 positions at depth 11.
SGR_EVALFILE=../nets/gen8.nnue ./sgr.exe bench
#   -> nodes 3601424        (the shipped v8.2 fingerprint)

./sgr.exe bench
#   -> nodes 4616415        (hand-crafted eval, i.e. no network present)

# Move generation, unmake, and null-move hash/eval restoration.
./sgr.exe test
#   -> perft(1..4) = 20 / 400 / 8902 / 197281
#   -> "after unmake eval = 0", "null restored hash = yes", "... eval = yes"

# Static exchange evaluation against hand-verified tactical cases.
./sgr.exe seetest
#   -> SEE: 9/9 passed
```

The `nodes` total is the fingerprint. For a given evaluation it is identical
across the dev build, the PGO release build, and the AVX-512, AVX2 and scalar
inference paths: that is what makes those a speed change rather than a
behaviour change.

The bit-exactness gate compares engine inference against the trainer's own
forward pass across every special move type and thousands of random game
chains. It is built by `pipeline.py` rather than `build.sh`, so compile it
directly:

```bash
clang++ -std=c++20 -O3 -march=native -DNDEBUG -static \
  nnue_selfcheck.cpp board.cpp evaluation.cpp search.cpp nnue.cpp \
  -o nnue_selfcheck.exe
./nnue_selfcheck.exe ../nets/gen8.nnue
#   -> loaded ../nets/gen8.nnue active=1 simd=avx512 buckets=1
#   -> checks=4516 fails=0 evalsum=-142859 -> PASS
```

Web tests, from the repository root:

```bash
python -m unittest discover -s web/backend -p "test_*.py"   # -> 23 tests, OK

cd web && npm ci && npx playwright install chromium
npx playwright test                                         # -> 7 passed
```

Strength changes are decided by SPRT at 8+0.08 against the previous accepted
version; releases are calibrated against the pool at 10+0.1. Every rating is
reported with an interval. [testing/README.md](testing/README.md) covers the
match runner, the SPRT harness and the opening book.

---

## Releases

Versions are named after Sgùrr peaks in ascending height. Version numbers are
canonical; peak names are codenames.

| version | codename | peak | summary |
|---|---|---|---|
| v1.0 | Fox | Sgùrr a' Mhadaidh | first NNUE (gen1): parity with the classical eval |
| v2.0 | Notches | Sgùrr nan Eag | gen2 NNUE: +77.7 ±37.4 vs v1.0 (300 games, 8+0.08) |
| v3.0 | Blackpeak | Sgùrr Dubh Mòr | gen3 NNUE: +119.8 ±26.3 vs v2.0 (618 games, SPRT) |
| v3.1 | Blackpeak | Sgùrr Dubh Mòr | search-only: soft/hard time management. Calibrated **below v3.0**: the flat soft limit loses at 10+0.1. Superseded in v4.0 |
| v4.0 | MacKenzie | Sgùrr MhicChoinnich | gen5 NNUE (768→384, first architecture change): +55.5 ±17.0 vs the gen3 engine (1,194 games, SPRT), plus history malus and best-move-stability time management |
| v5.0 | Gillean | Sgùrr nan Gillean | search-only on the gen5 net: reverse futility pruning (+176.4 ±15 self-play, factorial) and LMP. The gen6 net measured flat and was not shipped |
| v6.0 | Banachdaich | Sgùrr na Banachdaich | search refinement package: improving flag, history-adjusted LMR, singular extensions. +57.3 ±17.0 vs v5.0 (1,139 games, SPRT); first version above the old pool's ceiling |
| v7.0 | Ghreadaidh | Sgùrr a'Ghreadaidh | gen7 NNUE, the first clean RFP-free datagen regen: +44.4 ±18.8 vs v6.0 against gen6's +6 wash: the labels really were the bottleneck. AVX-512/int16 inference landed here, ~+22% NPS and bit-identical |
| v8.0 | Thearlaich | Sgùrr Thearlaich | gen8 NNUE on 55.9M clean positions: **+126.5 ±26.6 vs v7.0**, the largest single-cycle gain in the project. King buckets were tested on the same data and measured flat (−10.7 ±16, despite 12% lower loss), so the shipped net is the plain 768→384 |
| v8.1 | Thearlaich | Sgùrr Thearlaich | speed-only on the gen8 net: PGO + ThinLTO and nine node-identical optimisations, ~20% NPS. **+21.2 ±8.7 vs v8.0** self-play and **+20.9 pooled**: the two agree to 0.3 Elo. Same net, same search, same moves |
| v8.2 | Thearlaich | Sgùrr Thearlaich | speed-only again: TT entry packed 24→16 bytes and a lazy move picker, **+15.4% NPS**, node-identical to v8.1. **+31.5 vs v8.1** against +14.5 predicted. The ten-item v9.0 search batch measured −1.0 ±21.1 and was held back |

Ratings for each row are in the [Strength](#strength) table above and in
[benchmarks/ledger.md](benchmarks/ledger.md) with full game counts.

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

## Licence

Original Sgurr material is proprietary, see [LICENSE](LICENSE). You are free
to read, build, run and evaluate it. Third-party software and assets keep their
own terms, inventoried in [docs/THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md)
and [docs/THIRD_PARTY_ASSETS.md](docs/THIRD_PARTY_ASSETS.md).
