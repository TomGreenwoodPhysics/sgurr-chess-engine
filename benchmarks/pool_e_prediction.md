# pool-2026-09-E validation, prediction registered before the run

Written 2026-09-24, before any pool-E game. Rule 7 of `docs/METHODOLOGY.md`.

## What is measured

v9.1 and v9.0 each calibrated on pool-E to about ±8, with the exact binaries
and nets used on pool-D (`sprt_bundle.exe` with `gen9_screlu.nnue`,
`sgr_v9_0.exe` with `gen9.nnue`) and the same opening seed. Only the pool
changes: nine families from 3087 to 3362, solved on pool-E games alone.

## Prediction

**The v9.0 to v9.1 gap reproduces pool-D's +124.5 ±13.6: +120, band +100 to
+140.** Two independent pools measuring the same two binaries should agree
within their joint error, about ±15 here.

v9.1's absolute rating lands within the ±25 systematic band around pool-D's
3206. Pool-E has stronger anchors and more families, so it can move, but a
shift beyond 25 would say the anchors disagree more than pool-D suggested.

## Falsification

The gap outside +95 to +155. Then the two pools disagree about the same pair
of binaries, and pool-E does not get used for version gaps until that is
explained.

Games are checked for forfeits and time losses before any of this is read.

## Changed before the test ran, 2026-09-25

The gap test above was dropped with v9.1 at 541 of its games and v9.0 not
started, so this prediction is neither confirmed nor falsified.

A +124 gap is too large to show whether pool-E resolves medium gains, and
pool-E already looked sane (v9.1 at 3188 ±25 after 459 games against 3206 on
pool-D). Tighter absolute numbers buy little: with systematic error near ±25,
total uncertainty is about ±26 at ±8 sampling and ±28 at ±12. For gaps the pool
is the expensive instrument: pool-D spent 8,232 games on a ±13.6 gap that a
direct match reaches in about 1,650.

So v9.1 is calibrated to ±12 as a baseline only. Gains are decided and sized
by SPRT; each release gets one pool run at ±12 to confirm the gain carries over
to other engines, the METHODOLOGY 6 question.
