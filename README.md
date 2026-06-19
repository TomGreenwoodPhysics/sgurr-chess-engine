# Ruk

A UCI chess engine. The primary engine is written in modern C++ (C++20); the
repository also includes an earlier, self-contained **Python** implementation
that you can play against directly.

*(Formerly **Bitfish**.)*

---

## Strength

**Ruk (C++)** — benchmarked against **Stockfish limited to ~2400 Elo** at equal
move time, with both engines using **0.50 s/move**. Across **1000 games**, Ruk
scored **666/1000 = 66.6%**, with a record of **575 wins, 182 draws, and 243
losses**. This corresponds to approximately **+120 Elo**, or roughly **2520 Elo**
in this benchmark setup, with an estimated **95% confidence interval of about
±20 Elo**.

**Ruk (Python)** — the earlier, pure-Python engine. It is a self-contained
implementation with its own board representation, move generation, evaluation,
and search, rather than a wrapper around an external chess library. It is much
slower than the C++ engine and is mainly kept as a readable reference version
and playable prototype. Formal benchmark: **measurement pending**.

Colour split:

* **Ruk as White:** 360.5/500 = **72.1%**
* **Ruk as Black:** 305.5/500 = **61.1%**

Two unfinished games were counted as draws. Excluding them gives **665/998 =
66.6%**, essentially the same estimate.

**Ruk (Python)** — the earlier, pure-Python engine; substantially weaker than
the C++ version, estimated at roughly **1800 Elo**. Formal benchmark:
**measurement pending**.

## Implementations

* **C++ (primary).** The full-strength engine. Bitboard move generation, a
  tapered evaluation, and an alpha-beta search with transposition tables, static
  exchange evaluation (SEE), null-move pruning, late move reductions, and
  quiescence.
* **Python (earlier).** A self-contained pure-Python engine with bitboard board
  representation, legal move generation, FEN parsing, incremental Zobrist
  hashing, and both UCI and interactive terminal modes. Its search uses
  iterative deepening, negamax with alpha-beta pruning, a dictionary-based
  transposition table, aspiration windows, null-move pruning, late move
  reductions, futility pruning, check extensions, killer/history move ordering,
  and quiescence search with delta pruning. Its evaluation includes material,
  piece-square tables, simple opening principles, pawn structure, king safety,
  and mobility. It does not include SEE and, because it runs in pure Python,
  searches far fewer nodes per second than the C++ version.


## Features (C++ engine)

**Board & move generation**

* Bitboard board representation
* Occupancy-aware sliding-piece attack generation
* Legal move generation, `perft`-verified against known node counts

**Search**

* Negamax with alpha-beta pruning and iterative deepening
* Aspiration windows
* Transposition table (Zobrist hashing)
* Null-move pruning
* Late move reductions (LMR)
* Quiescence search with delta pruning
* Static exchange evaluation (SEE) for pruning and ordering losing captures
* Move ordering: TT move, MVV-LVA captures, killer and history heuristics

**Evaluation**

* Tapered evaluation interpolating between middlegame and endgame
* Material, piece-square tables, pawn structure, king safety, mobility
* Evaluation weights tuned with Texel's method

## Building and running

### C++ (primary)

Requires a C++20 compiler.

```bash
g++ -std=c++20 -O3 -march=native -DNDEBUG \
    main.cpp board.cpp evaluation.cpp search.cpp -o ruk
./ruk uci
```

### Python (earlier)

Requires Python 3.10+. From the repository root:

```bash
# UCI mode (for a GUI or scripted matches)
python -m Ruk_python.Ruk_search uci

# Interactive mode - play against it from the terminal
python -m Ruk_python.Ruk_search
```

In interactive mode, useful commands are:

```text
display
moves
best
go 5
move e2e4
new
quit
```

The Python engine defaults to a maximum search depth of **8**, unless a different
depth or movetime is supplied through UCI or the terminal command mode.


Both engines speak the [UCI protocol](https://www.chessprogramming.org/UCI) and
work in any UCI-compatible GUI, such as Cute Chess, BanksiaGUI, or Arena. A
quick manual session:

```text
uci
isready
position startpos moves e2e4 e7e5
go movetime 1000
```

## Testing

Correctness and strength are verified, not assumed:

* **Move generation** is checked with `perft` against reference node counts in
  both implementations.
* **Search changes** are validated by self-play A/B matches and sequential
  probability ratio testing (SPRT) before being kept, using a custom
  engine-vs-engine match runner that reports score, Elo +/- error, LOS, and
  optional SPRT verdicts.
* **Tactical components** such as SEE are validated against exhaustive
  known-answer tests.