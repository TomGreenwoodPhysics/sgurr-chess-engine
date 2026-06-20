# Ruk

A UCI chess engine written primarily in modern C++.

Ruk was formerly called **Bitfish**. The repository also includes an earlier
pure-Python version as a legacy/reference implementation.

---

## Strength

**Ruk (C++)** has been benchmarked against **Stockfish limited to ~2400 Elo**
with both engines using **0.50 s/move**.

Across **1000 games**, Ruk scored:

```text
575 wins, 182 draws, 243 losses
666/1000 = 66.6%
```

This corresponds to approximately **+120 Elo** against the limited Stockfish
opponent, or roughly **2520 Elo in this benchmark setup**.

The estimated statistical uncertainty is about **±20 Elo at 95% confidence**
under a simple independent-games model. This should be treated as benchmark
strength rather than an official rating, since engine ratings depend strongly on
hardware, time control, opening selection, opponent calibration, and match
conditions.

Colour split:

```text
Ruk as White: 360.5/500 = 72.1%
Ruk as Black: 305.5/500 = 61.1%
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

The C++ engine is the primary version of Ruk and is the full-strength engine in
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

Requires a C++20 compiler.

From the C++ source folder:

```bash
g++ -std=c++20 -O3 -march=native -DNDEBUG -Wall -Wextra main.cpp board.cpp evaluation.cpp search.cpp -o Ruk_cpp.exe
```

Run in UCI mode:

```bash
./Ruk_cpp.exe uci
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
./Ruk_cpp.exe
```

Run SEE tests:

```bash
./Ruk_cpp.exe seetest
```

Search a specific FEN:

```bash
./Ruk_cpp.exe fen "<FEN string>"
```

---

## Legacy Python version

Requires Python 3.10+.

From the repository root:

```bash
python -m Ruk_python.Ruk_engine uci
```

For interactive terminal mode:

```bash
python -m Ruk_python.Ruk_engine
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

## Testing and validation

Correctness and strength are tested rather than assumed.

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

The quoted Elo estimate is not an official rating. It is a benchmark estimate
against a specific Stockfish configuration, on specific hardware, at a specific
time control.

The most reliable interpretation is:

```text
In this test setup, Ruk scored 66.6% against Stockfish limited to ~2400 Elo.
```

The approximate 2520 Elo figure is a convenient translation of that match score,
not an official rating.
