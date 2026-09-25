# Speed round 2: the eval cache, prediction registered before the run

Written 2026-09-25, before any games. Rule 7 of `docs/METHODOLOGY.md`.

## What changed

A profile of the release build (PGO and ThinLTO, search thread only) put NNUE
at about 30% of search time. `SGR_EVAL_CACHE` keeps `nnue::evaluate()`'s score
by full position key in a 2 MB table; positions come back through re-searches,
deeper iterations, singular searches and transpositions. The score depends
only on the position, so the tree is unchanged.

Size, measured at Hash 256 over 16 pinned pairs: 256 KB +2.8%, 512 KB +2.8%,
1 MB +3.4%, **2 MB +5.3%**, 4 MB +3.0%, 16 MB -0.3%.

Three other candidates were built, measured and dropped at no gain: an exact
early TT prefetch (`key_after`, predicting the child key on all 10.8M moves
tested) at -0.7% ±0.9%, uninitialised `MoveList` storage at -0.8% ±1.6%, and
computing `is_noisy_move` and `is_killer_move` once per move at +0.0% ±0.6%.

Checked: 2,390,227 bench nodes on AVX-512, AVX2 and scalar and with the cache
off; 43 of 43 searches identical to the baseline; self-check evalsum 156878;
the 1,201-move game identical; trace and datagen build. Final speed
**+5.2% ±0.8%**.

## Measurement

`tools/sprt.sh round2 sprt_round2.exe 2390227 sprt_batch_a_fast.exe 2390227`:
8+0.08, [0, 5], capped at 5,000 games.

## Prediction

**+6 Elo, band 0 to +15.** Speed has converted here at roughly 1 to 2 Elo per
percent. An effect this size may not reach a bound within the cap.

## Falsification

H0 accepted. For a change that cannot alter the tree, that would say speed
converts to nothing at this margin.
