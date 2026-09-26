# v9.3-rc1 on pool-F, prediction registered before the run

Written 2026-09-26, before any pool-F game. Rule 7 of `docs/METHODOLOGY.md`.

## What is measured

Pool-F is pool-E plus nine families, under identical conditions (see
`pool.json`). v9.3-rc1 (`sprt_batch_d.exe`, commit 34662b3, cosine seed-1
net) already has 1,902 games against pool-E's nine. It now plays 210 games
against each new family, 1,890 in all, the same number it played against each
pool-E engine. Ordo then solves its games against all 18 families, anchored at
their CCRL ratings, together with v9.1's and v9.2-rc's pool-E games.

## Prediction

**v9.3-rc1 at 3266 on pool-F, band 3242 to 3290.** On pool-E each anchor
implied a rating about 52 Elo from the others beyond noise. If the new nine
behave the same, their average differs from the old nine's by about ±48, and
the pooled rating moves by half of that, about ±25.

**The spread between anchors stays at about 50 Elo per family, so the
systematic error on the absolute rating falls to about ±25.** The spread comes
from carrying CCRL ratings over to our conditions, and nothing about the new
engines should change it.

**No abnormal endings,** and Onyx plays without its book.

## Falsification

A new family implying a rating more than 150 from the pooled value points to a
problem with that engine's build or settings rather than its style. It is
checked before its games are used. A spread well above 50, say 80, would mean
the new families disagree more than the old ones, and eighteen families would
not reduce the systematic error as far as expected.

## Checked before the run

All nine binaries are official release builds of the exact CCRL-rated
versions, with SHA-256 recorded in `pool.json`; Pounce's matches its published
checksum. Each reports its version via `id name`, supports Hash, runs one
thread and passed `engine_gate.py`. A live smoke test of one round against the
nine played 18 games with no abnormal endings and Onyx's book switched off.
Its final solve failed, which was expected with two games per engine: two
engines lost both games, and Ordo cannot place a player with only losses. With
those games relabelled as v9.3-rc1, the solve connected every other engine and
reproduced v9.3-rc1, v9.2-rc and v9.1 at their pool-E values.

## Result, 2026-09-26

**v9.3-rc1 at 3257.3 ±8.8, inside the band** and 9 below the point
prediction, solved on the sixteen families left after two were removed.

**Two new families failed the checks registered above.** Onyx 2.0 implied
ratings for Sgurr 407 to 486 above the solve on the other sixteen, far past
the 150 allowed. Its binary gives its author as "Dylan (with Claude)", which
suggests a different engine from the Onyx 2.0 that CCRL rated. Priessnitz 2.0
lost on time in 230 of its 746 games, so the prediction of no abnormal endings
failed on its account. Both were dropped. Their games are kept but left out of
every solve, listed under `excluded_engines` in `pool.json`.

**The spread came in below 50.** For v9.3-rc1 the anchors imply ratings 42
Elo apart beyond noise, and 30 to 49 across the four versions solved, which
leaves about ±15 to ±24 of systematic error. That beats the ±25 predicted for
eighteen families.

v9.1 reads 3166.2 on pool-F, 40.0 below pool-D and 19.4 below pool-E alone.
