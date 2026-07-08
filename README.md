# Sgurr

A UCI chess engine written primarily in modern C++, with an NNUE evaluation
trained on self-play data.

Sgurr was formerly called **Ruk**, and before that **Bitfish**. The name comes
from the Gaelic *Sgùrr* — a rocky mountain peak (the engine name itself is
plain-ASCII `Sgurr`; the binary is `sgr`). The repository also includes an
earlier pure-Python version as a legacy/reference implementation.

## Releases

Versions are named after Sgùrr peaks in ascending height. Version numbers are
the canonical identifiers; peak names are codenames only.

| version | codename | peak | summary |
|---|---|---|---|
| v1.0 | Fox | Sgùrr a' Mhadaidh | first NNUE (gen1): parity with the classical eval |
| v2.0 | Notches | Sgùrr nan Eag | gen2 NNUE: +77.7 ±37.4 Elo vs v1.0 (300 games, 8+0.08) |
| v3.0 | Blackpeak | Sgùrr Dubh Mòr | gen3 NNUE: +119.8 ±26.3 Elo vs v2.0 (618 games, SPRT); 2616 ±37 CCRL-Blitz-anchored |
| v3.1 | Blackpeak | Sgùrr Dubh Mòr | search-only on the gen3 net: soft/hard time management; interim +24.6 ±22.7 vs v3.0 (706 games, SPRT stopped early), full calibration pending |

See `CHANGELOG.md` for details and measured results with error bars,
`benchmarks/ledger.md` for the append-only record of measured ratings, and
`DEVLOG.md` for the dated engineering log — findings, bugs, and the
methodology decisions behind them.

---

## Strength

Ratings are measured with a fixed pool of open-source UCI engines with
published CCRL Blitz ratings (Blunder 6.1–8.0, Zahak 4.0/5.0), solved with
Ordo anchored to those ratings — estimates on the CCRL Blitz scale, not
official CCRL ratings. Full method and append-only history:
`benchmarks/ledger.md`.

| engine | rating (CCRL-Blitz-anchored) |
|---|---|
| Sgurr v3.0 "Blackpeak" | **2616 ±37** |
| Sgurr v2.0 "Notches" | 2491 ±33 |
| Sgurr v1.0 "Fox" | 2408 ±34 |
| Sgurr classical (HCE) | 2400 ±35 |

Each generational gap in the pool table independently reproduces the direct
SPRT match result between those versions (e.g. v3.0 vs v2.0: +125 in the
pool vs +119.8 ±26.3 in a 618-game SPRT), so the self-play gains are real
rather than self-play-inflated.

**v3.1** shares v3.0's gen3 net (it is a search-only release) and has no
separate pool calibration yet, so it is not listed above; its only figure is
the interim head-to-head SPRT vs v3.0 (+24.6 ±22.7, stopped early). A full
calibration is planned before the next generation.

**Legacy Python version** — benchmarked against Stockfish limited to 1500
Elo at equal 0.50 s/move: ~49.6% over 1000 games, i.e. roughly 1500 in that
benchmark setup (±20 at 95%). Playing strength varies with time controls;
this mostly affects the Python prototype.

---

## Implementations

### C++ engine

The C++ engine is the primary version of Sgurr and is the full-strength engine in
this repository.

It uses:

* bitboard board representation
* legal move generation
* FEN parsing
* incremental Zobrist hashing
* UCI support
* iterative deepening search
* alpha-beta negamax search
* principal variation search
* aspiration windows
* transposition table
* null-move pruning
* late move reductions
* futility pruning
* check extensions
* quiescence search
* delta pruning
* static exchange evaluation
* killer/history move ordering
* tapered evaluation
* tuned evaluation weights

### Legacy Python engine

The Python version is an earlier self-contained implementation. It has its own
board representation, move generation, FEN parsing, incremental Zobrist hashing,
evaluation, and search. It can be run in UCI mode or as an interactive terminal
program.

It is kept mainly as a readable reference version and playable prototype. It is
substantially slower than the C++ engine and is not the main strength target of
the project.

---

## Features

### Board and move generation

* Bitboard board representation
* Legal move generation
* FEN support
* Castling, promotion, and en passant handling
* Incremental make/unmake move support
* Incremental Zobrist hashing
* `perft` testing against known reference node counts

### Search

* Iterative deepening
* Time management: soft/hard clock limits with a move-overhead margin
* Negamax with alpha-beta pruning
* Principal variation search
* Aspiration windows
* Fixed-size transposition table
* Null-move pruning
* Late move reductions
* Futility pruning
* Check extensions
* Quiescence search
* Delta pruning
* Static exchange evaluation for capture pruning and move ordering
* Killer move heuristic
* History heuristic
* Draw detection by repetition and the fifty-move rule

### Evaluation

* Tapered middlegame/endgame evaluation
* Material balance
* Piece-square tables
* Pawn structure
* Passed pawns
* King safety
* Mobility
* Rook activity
* Bishop pair
* Tuned evaluation weights

---

## Building and running

### C++ engine

Requires a C++20 compiler. From the C++ source folder:

```bash
clang++ -std=c++20 -O3 -march=native -DNDEBUG -Wall -Wextra main.cpp board.cpp evaluation.cpp search.cpp nnue.cpp -o sgr.exe
```

See `sgurr_cpp/BUILD.md` for the recommended toolchain on Windows (MSYS2 clang64)
and for building the NNUE data generator.

Run in UCI mode (bare launch also defaults to UCI):

```bash
./sgr.exe uci
```

A quick manual UCI session:

```text
uci
isready
position startpos moves e2e4 e7e5
go movetime 1000
```

The engine should return a move in the form:

```text
bestmove <move>
```

For example:

```text
bestmove g1f3
```

### Test modes

Run the built-in general test mode:

```bash
./sgr.exe test
```

Run SEE tests:

```bash
./sgr.exe seetest
```

Search a specific FEN:

```bash
./sgr.exe fen "<FEN string>"
```

---

## Legacy Python version

Requires Python 3.10+.

From the repository root:

```bash
python -m sgurr_python.sgurr_engine uci
```

For interactive terminal mode:

```bash
python -m sgurr_python.sgurr_engine
```

Useful interactive commands:

```text
display
moves
best
go 5
move e2e4
new
quit
```

The Python engine defaults to a maximum search depth of **8** unless a different
depth or movetime is supplied.

---

## Training pipeline

Each NNUE generation is produced by a single resumable command:

```bash
python pipeline.py pipeline_gen3.json          # run / resume the whole cycle
python pipeline.py pipeline_gen3.json --status # stage progress
```

Stages: parallel self-play **datagen** (resumable, balance-filtered openings)
→ **freeze** into a versioned dataset + manifest (`data/vX.Y/`) → NNUE
**train**ing with logged loss curves (optionally a lambda grid) → engine
**build** → **select**ion of the best variant by games → **SPRT** vs the
previous generation → pool **calibrat**ion against CCRL-anchored engines
(Ordo) → append to the results **ledger** (`benchmarks/ledger.md`). Every
stage checkpoints to `runs/`, so the pipeline can be interrupted and re-run
at any point; datasets, weights, and ledger rows are append-only artefacts.

---

## Testing and validation

* Move generation is checked using `perft`.
* Make/unmake logic is tested by verifying that board state and hash keys are
  restored correctly.
* Incremental Zobrist hashing is checked against recomputed hashes.
* Null moves are tested for correct restoration.
* Static exchange evaluation is tested against known-answer tactical cases.
* Search changes are evaluated with engine-vs-engine benchmark matches.
* Strength estimates are reported with Elo uncertainty where possible.

---

## Notes on rating estimates

The quoted ratings are Ordo estimates anchored to the pool engines'
published CCRL Blitz values, measured on one machine at one time control —
not official CCRL ratings. The absolute scale is only as accurate as the
anchor values; the *gaps* between Sgurr versions are anchor-independent and
are cross-checked against direct SPRT matches. Method, caveats, and every
measurement: `benchmarks/ledger.md`.
