# v9.1 net retrained with a cosine schedule, prediction registered before the run

Written 2026-09-24, before training. Rule 7 of `docs/METHODOLOGY.md`.

## What changed

`tools/mainline_screlu_train.sh` never passed `--schedule cosine`, and
`train.py` defaults to `constant`. So `gen9_screlu.nnue`, the v9.1 network,
trained at a flat 1e-3 for all 22 epochs, about 130,000 steps. Every network
since gen3 has used cosine decay because v3.0 found a constant rate degrades
nets as the step count grows. The shipped run's validation loss stopped
moving at 0.01135 around epoch 12.

The retrain changes that one flag. Same 102,011,689 positions, lambda 0.8,
22 epochs, seed 0 and the same 5% holdout, so the two validation curves are
directly comparable.

## How it is measured

`sprt_v91_cos.exe` against `sprt_v91_ref.exe`, both built from one commit and
differing only in the baked net. The reference must be bench-identical to
`sprt_bundle.exe`, the binary calibrated as v9.1, or the run stops. SPRT at
8+0.08, elo0=0 elo1=5, capped at 3,000 games. Pool calibration at 10+0.1 only
if H1 is accepted.

## Prediction

**+15 Elo, band +5 to +30. About 75% that it is positive, 50% that it lands in
the band.**

Positive because a rate that never decays ends with the weights jittering
around the minimum instead of settling into it. The final low-rate stretch is
where a lot of late gain usually comes from.

Not higher because this is one seed per arm, and two seeds of one recipe
differ by +13.7 ±10.3 (§2). A single pair cannot separate a +10 recipe effect
from seed luck. The shipped net is also not broken: it measured +22.6 against
v9.0 and carried the +142 bundle.

If this lands well above +15, the +22.6 credited to SCReLU was held down by
the recipe, and SCReLU is worth more than the ledger says.

## Falsification

H0 accepted, or an estimate at or below zero with the interval excluding +10:
the schedule was not holding the net back, and the flat validation curve was
a real plateau.

Validation loss is logged to confirm the schedule did what it says. It does
not choose anything (§3).

## Not in this run

- A second cosine seed trains after the games, ready for a seed-luck check.
- Feature weights clip at 127/255 even at QA=181; 1.3% of the shipped net's
  weights sit on the clip. Separate test.
