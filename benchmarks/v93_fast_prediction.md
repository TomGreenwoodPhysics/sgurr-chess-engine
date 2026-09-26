# Batch A plus the speed bundle, prediction registered before the run

Written 2026-09-25, before any games. Rule 7 of `docs/METHODOLOGY.md`.

## What changed

Two speed changes on top of batch A, both leaving the search tree identical.

- The accumulator stack (`SGR_NNUE_STACK`, commit c277e0d).
- The move picker stores moves as raw 16 bits. A default `Move` zeroes itself,
  so its four 256-entry buckets were being zeroed on every node: 12.6% of
  search time in a sampling profile. SEE now splits good captures from bad
  when the capture stage is reached, not when the picker is built, so nodes
  that cut on the TT move skip it. Both buckets keep generation order, so the
  sorts give the same sequence.

Identical trees: 2,390,227 bench nodes on AVX-512, AVX2 and scalar, repeat
runs identical, and 43 searches at depth 13 (40 random openings plus
Kiwipete, a middlegame and an endgame) match the previous build in nodes,
score, PV and best move. Perft 4 and SEE 9/9 pass; trace and datagen build.

Speed, 10 interleaved runs pinned to one core against batch A: stack alone
+0.5% ±1.2%, stack and picker **+19.5% ±1.9%** (3.753M to 4.476M nps).

## Measurement

`tools/sprt.sh batch_a_fast sprt_batch_a_fast.exe 2390227 sgr_v92rc.exe
1681306`: against v9.2-rc, 8+0.08, [0, 5], capped at 5,000 games.

## Prediction

**+40 Elo, band +20 to +60.** Batch A measured +16.4 ±12.9. Speed releases
here converted +20% nps to +21 (v8.1) and +15% to +31 (v8.2), so +20 to +30
from the speed.

## Falsification

Below +20 with the interval excluding +40: the speed did not convert, or batch
A's first measurement ran high.

## Result, 2026-09-25

Stopped by decision once clearly positive, before a bound was crossed:
**+26.0 ±16.2** over 764 games, LLR 1.17. Inside the predicted band, at its low
end. No abnormal endings.
