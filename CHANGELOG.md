# Changelog

Versions are named after Sgùrr peaks in ascending height; version numbers are
canonical, codenames are flavour. All Elo figures are measured self-play match
results with 95% error bars — never estimates.

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
