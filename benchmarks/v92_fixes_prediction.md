# Null-move eval gate and TT move keeping, prediction registered before the run

Written 2026-09-25, before any games. Rule 7 of `docs/METHODOLOGY.md`.

## What changed

- `SGR_NMP_EVAL`: null move is tried only when the static eval is at or above
  beta. Before, it ran even far below beta, where the eval term drove R down
  to 1 and a near-full-depth search almost always failed.
- `SGR_TTMOVE_KEEP`: fail-low nodes store no TT move, and a store without a
  move keeps the move already held for that position. Before, null-move cuts
  and fail-lows overwrote a proven move with nothing or with noise.

Both default on. With both off the build benches 2,199,384 nodes, identical to
the calibrated v9.1. On: 1,551,144. The TT change alone gives 1,541,015 and the
null-move gate alone 2,125,441. Perft 4 = 197,281 and SEE 9/9 still pass.

## Measurement

`sprt_fixes.exe` against `sprt_v91_ref.exe`, same commit apart from the two
toggles, both with `gen9_screlu.nnue` baked in. 8+0.08, Hash 256,
`8moves_v3.pgn`, elo0=0 elo1=5, capped at 5,000 games.

## Prediction

**+10 Elo, band 0 to +25. About 70% that H1 is accepted.**

The null-move gate is standard and mostly saves wasted nodes, so perhaps +3 to
+10. The TT change removes 30% of the bench tree, which could be worth more,
but a smaller tree is not strength (§5), and keeping an older move after a
fail-low could order some nodes worse.

## Falsification

H0 accepted. Then build each toggle alone and test them separately, TT change
first, since it moves the tree far more.

## Result, 2026-09-25

H1 accepted at 1,040 games: **+50.5 ±14.2**, W 351 L 201 D 488, 0 abnormal
endings. Five times the prediction and far above the band.

I priced both changes as refinements to working code. The result says the old
behaviour was costing a great deal. Neither toggle was tested alone, so how the
gain divides between them is not known.
