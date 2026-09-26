# v9.3-rc1 on pool-E, prediction registered before the run

Written 2026-09-26, before any v9.3-rc1 game. Rule 7 of `docs/METHODOLOGY.md`.

## What is measured

`sprt_batch_d.exe`, commit 34662b3 with the cosine seed-1 net baked in
(bench 1,847,491). It is v9.2-rc plus batch A, the speed work (accumulator
stack, raw picker moves with lazy SEE, eval cache), batch B and batch D.
Calibrated on pool-E to ±12 in the same solve as v9.1 and v9.2-rc, starting
from the same opening seed, so all three meet the same openings in the same
order. A checkpoint before time management, not a release.

## Prediction

**v9.3-rc1 30 Elo above v9.2-rc in the same solve, band +10 to +50. About
3250.**

Self-play since v9.2-rc: batch A with the speed work +26.0, batch B +16.2 and
batch D +4.3, plus the eval cache's 5.2% of speed, never played. Search
changes have come through on the pool at about 60% of their self-play value
and speed at about 100%, which gives about +35. Every one of those runs was
stopped by decision while it looked good, so they probably read a little
high, hence +30.

The gap is measured inside one solve, so the anchors' disagreement about the
absolute scale cancels. Only its sampling error, about ±16, applies.

## Falsification

A gap at or below +10: less than a third of the self-play gain carried over
to other engines. Then each batch is checked on its own before anything is
stacked on top.

## Result, 2026-09-26

**3266.3 ±11.9** over 1,902 games (+526 =725 -651), no abnormal endings. In
the same solve v9.2-rc is 3219.1 and v9.1 3185.1, so the gap is **+47.2
±16.5** over v9.2-rc and +81.2 over v9.1. Inside the band, 17 above the point
prediction.

The batches carried over almost in full: about +50 in self-play became +47 on
the pool, where the estimate assumed 60% for search changes. Per engine the
gap runs from -5 against Counter to +101 against Drofa, which is consistent
with one gain and sampling noise (Q = 11.8 on 8 degrees of freedom).

The anchors disagree about the absolute rating as much as they did for v9.1:
about 52 Elo per engine beyond noise, which over nine families is about ±35
systematic.
