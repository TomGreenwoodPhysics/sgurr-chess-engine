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

See `CHANGELOG.md` for details and measured results with error bars,
`benchmarks/ledger.md` for the append-only record of measured ratings, and
`DEVLOG.md` for the dated engineering log — findings, bugs, and the
methodology decisions behind them.

---

## Strength

**Sgurr (C++)** has been benchmarked against **Stockfish limited to ~2400 Elo**
with both engines using **0.50 s/move**.

Across **1000 games**, Sgurr scored:

```text
575 wins, 182 draws, 243 losses
666/1000 = 66.6%
```

This corresponds to approximately **+120 Elo** against the limited Stockfish
opponent, or roughly **2520 Elo in this benchmark setup**, with an estimated
uncertainty of about **±20 Elo at 95% confidence**. This is benchmark strength
rather than an official rating; see the notes at the end of this file.

Colour split:

```text
Sgurr as White: 360.5/500 = 72.1%
Sgurr as Black: 305.5/500 = 61.1%
```

Two unfinished games were counted as draws. Excluding them gives:

```text
665/998 = 66.6%
```

which gives essentially the same estimate.

**Legacy Python version** - benchmarked against **Stockfish limited to 1500 Elo**
at equal **0.50 s/move**. Across **1000 games**, it scored approximately
**495.5/1000 = 49.6%**, corresponding to roughly **1500 Elo in this benchmark
setup**, with an estimated **95% confidence interval of about ±20 Elo**.

**NOTE** - Stated playing strengths will vary with time per move and max depth conditions. This mostly affects the Python prototype.

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
at any point; datasets, weights, and ledger rows are append-only artifacts.

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

The quoted Elo is a benchmark estimate against a specific Stockfish
configuration, on specific hardware, at a specific time control, not an
official rating. The safest interpretation is simply:

```text
In this test setup, Sgurr scored 66.6% against Stockfish limited to ~2400 Elo.
```

The approximate 2520 Elo figure is a translation of that match score.
