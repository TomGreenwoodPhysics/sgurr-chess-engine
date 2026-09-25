# Batch A plus the accumulator stack, prediction registered before the run

Written 2026-09-25, before any games. Rule 7 of `docs/METHODOLOGY.md`.

## What changed

`SGR_NNUE_STACK`: one accumulator per ply. Make and unmake only push and pop,
recording which features changed; a level is computed when its position is
evaluated, in one fused pass from its nearest computed ancestor. Evaluations
are bit-identical, so the tree is unchanged: 2,390,227 bench nodes with the
stack on or off, on AVX-512, AVX2 and scalar builds. The self-check's 4,516
checks keep their evalsums (156878 on gen9_screlu), 60,240 new checks cover
search-like walks with null moves and a 2,500-ply stack overrun, and 10-, 16-
and 32-bucket nets give identical evalsums and benches on and off.

Speed, 10 interleaved pairs pinned to one core: **+0.8% ±2.8%** (median 3.778M
to 3.820M nps). Most nodes are evaluated anyway, and a level per ply touches
new cache lines where the old single accumulator stayed hot.

## Measurement

`tools/sprt.sh batch_a_speed sprt_batch_a_speed.exe 2390227 sgr_v92rc.exe
1681306`: batch A plus the stack against v9.2-rc, 8+0.08, [0, 5], capped at
5,000 games.

## Prediction

**+17 Elo, band +5 to +30.** Batch A measured +16.4 ±12.9 on its own; the
stack adds perhaps 1 or 2 through speed. In practice this run firms up batch A.

## Falsification

A result below +5 with its interval excluding +17 would say batch A's first
1,142 games ran high.
