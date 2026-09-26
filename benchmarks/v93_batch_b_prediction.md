# Batch B: singular refinements, prediction registered before the run

Written 2026-09-25, before any games. Rule 7 of `docs/METHODOLOGY.md`.

## What changed

Singular extensions measured +77 in v6.0 but only ever extended by one ply and
did nothing when the TT move turned out not to be singular. Three toggles, all
on, following Stockfish's structure:

- `SGR_SE_DOUBLE`: at non-PV nodes, extend by 2 when the alternatives fall
  more than `SeDoubleMargin` (16 cp) below singular beta, and by 3 for a quiet
  TT move more than `SeTripleMargin` (80 cp) below. At most `SeDoubleLimit` (8)
  double extensions per line, counted along the path.
- `SGR_SE_MULTICUT`: when the reduced search without the TT move already
  reaches singular beta and singular beta is at least beta, return it: another
  move refutes this node as well.
- `SGR_SE_NEGATIVE`: a TT move that is not singular is searched two plies
  shallower when its stored score beats beta, one when an alternative scores
  as well as it.

## Checked before any games

| build | bench nodes |
|---|---|
| all three off | 2,390,227, identical to the current best |
| double and triple only | 2,530,536 |
| multicut only | 2,049,842 |
| negative only | 1,590,372 |
| all three | 1,983,513 (release build identical) |

No compiler warnings; perft 4 = 197,281; SEE 9/9; repeat benches identical;
no false mate claim on seven positions; 80 searches legal at 1 MB and 256 MB
hash; trace and datagen build; rules gate passes. Explosion check at depth 17
on 12 varied positions: the new tree is never more than 1.01 times the old.

## Measurement

`tools/sprt.sh batch_b sprt_batch_b.exe 1983513 sprt_round2.exe 2390227`:
8+0.08, [0, 5], capped at 5,000 games, against the current best.

## Prediction

**+15 Elo, band +3 to +35. About 70% that it is positive.**

Negative extensions and multicut are established gains in comparable engines.
Double extensions help most at longer time controls, so their share here may
be small.

## Falsification

A clearly negative result. Then split it: negative extensions alone first,
since they move the tree most.

## Result, 2026-09-25

Stopped under rule 9 once the interval cleared zero: **+16.2 ±13.7** over 860
games, W 183 L 143 D 534, LLR 0.88 of 2.94. No abnormal endings in the 871
games in the PGN. On the prediction of +15 and inside its band.
