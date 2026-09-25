# v9.2-rc on pool-E, prediction registered before the run

Written 2026-09-25, before any v9.2-rc game. Rule 7 of `docs/METHODOLOGY.md`.

## What is measured

`sgr_v92rc.exe`: v9.1's search plus `SGR_NMP_EVAL` and `SGR_TTMOVE_KEEP`, with
the cosine seed-1 net (`gen9_screlu_cos_s1.nnue`, sha256 `e733e437…`). Loaded
with the v9.1 net it benches 1,551,144 nodes, identical to the SPRT's fixes
build. Calibrated on pool-E to ±12 in the same solve as v9.1, starting from the
same opening seed.

## Prediction

**v9.2-rc 15 Elo above v9.1 in the same solve, band 0 to +35.**

About +10 from the fixes (`v92_fixes_prediction.md`) and about +6 from the
cosine net. Seed 1 measured +14.1, but it was the better of two seeds with a
mean of +6, so +6 is the honest expectation. Pool gains have sometimes come in
below self-play (§6).

## Falsification

The gap at or below zero with its interval excluding +15: the gains did not
carry over to other engines, and v9.2 does not ship on self-play alone.

At ±12 per version the gap carries about ±17, so this run can confirm a
transfer or catch a failed one. It cannot size a gain to better than ±17.
