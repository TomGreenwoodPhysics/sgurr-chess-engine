# v9.0 batch after SPSA, prediction registered before the run

Written 2026-09-21, before any games. Rule 7 of `docs/METHODOLOGY.md`.
Companion to `v90_batch_prediction.md`, which predicted the untuned batch and
was wrong.

## What is being measured

`runs/spsa/v90_batch_gen9` tunes ten search parameters over 3,000 iterations of
8 games at 8+0.08, Hash 256, `8moves_v3.pgn`, on HEAD with all nine batch
toggles on and gen9 loaded.

The measurement that follows is an SPRT of the tuned build against
`sgr_v9_0.exe`, same net, 8+0.08, `elo0=0 elo1=5`, alpha=beta=0.05.

It is a clean isolation. v9.0 kept v8.1's search and changed only the network,
so the original **-1.0 +/-21.1** was already batch-on against batch-off on this
same baseline. With gen9 on both sides the only remaining difference is the
tune, so whatever this SPRT measures above -1.0 is what SPSA bought.

## Prediction

**+10 to +30 Elo. ~70% that it is net positive, ~45% that it lands in the band.**

Positive because three of the ten settings were reasoned rather than measured,
and one of them -- `HistLmrDiv` at 400,000 -- is about three orders of magnitude
out and has shipped inert for four versions. A first SPSA tune is worth ~+24 in
comparable engines. The per-item literature priors sum well above this band, so
the band already assumes most of the batch underperforms its prior.

Not higher confidence because -1.0 +/-21.1 comfortably admits a true -15. If the
batch is negative at its core rather than mis-tuned, tuning polishes a loss.
SPSA also optimises its own self-play objective, and METHODOLOGY 6 records the
v3.1 soft limit at +24.6 self-play and negative pooled.

24,000 games over 10 parameters is ~2,400 per parameter against the ~5,000
usually wanted. Expect the large mis-scalings found and the fine margins left
noisy.

## Falsification

If the tuned batch measures <= 0 with an interval excluding +10, the "good ideas
at guessed settings" hypothesis is wrong. Stop tuning the batch as a unit and
run the item-by-item bisect in `v90_batch_prediction.md`, halves first.

Two items cannot be reached by this tune at all: Root PVS and fifty-move eval
scaling are compiled in but carry no tunable parameter. If either is the
problem, the bisect is owed regardless of the outcome here.

## Not predicted

The pooled figure. METHODOLOGY 6 records self-play gains compressing against a
diverse pool while large pruning gains mostly survive. A pool gauntlet is a
separate measurement and gets its own prediction.
