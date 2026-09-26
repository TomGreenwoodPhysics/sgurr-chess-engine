# Cosine seed check and untuned-parameter SPSA, predictions registered before the run

Written 2026-09-24, before the overnight cosine result was known. Rule 7 of
`docs/METHODOLOGY.md`. Run by `tools/seedcheck_spsa.sh`.

## 1. Second cosine seed against v9.1

Same recipe as the overnight net, seed 1 instead of 0. SPRT at 8+0.08,
elo0=0 elo1=5, capped at 2,000 games.

**Seed 1 lands within 15 Elo of seed 0's overnight estimate, about 70%.** If
seed 0 accepted H1, seed 1 is positive with about 75% confidence. If seed 0
did not, seed 1 stays at or below +10.

§2 puts two seeds of one recipe at +13.7 ±10.3 apart, so a 15 Elo gap between
them is ordinary and says nothing on its own. The seed check is there to catch
a lucky seed 0, which would show as seed 1 near zero while seed 0 passed.

Falsification: the two estimates differ by more than their joint interval.
That would mean seed spread at 102M positions is wider than §2 measured at 56M,
and every single-seed net result since would need a second seed.

## 2. SPSA on the 17 untuned search parameters

`testing/spsa_v91_untuned.json`: RFP, LMP, futility, null move, LMR entry,
singular, check extension, aspiration and delta settings, all hand-set since
they were written. 5,000 iterations of 8 games at 8+0.08, run on the cosine
net if it passed overnight, otherwise on the v9.1 net. Validated at the end by
an SPRT of tuned against current defaults.

**+15 Elo, band +5 to +30. About 70% that it is positive.**

Well below the batch tune's +90. That tune found one setting three orders of
magnitude out (`HistLmrDiv`). These are conventional values, so I expect small
moves, except perhaps `AspirationWindow`, which at 50 is wider than most
engines start, and the pruning margins, which were set against older evals
than gen9 SCReLU.

Falsification: the validation SPRT lands at or below zero with an interval
excluding +10. The hand-set values were already close, and more search Elo has
to come from new features rather than tuning.

Values read before the 5,000 iterations finish are not validated and not used.

## Result, 2026-09-25

### Seed check

Seed 1 scored **+14.1 ±12.0** against v9.1 over 2,000 games, W 659 L 578 D 763.
Its log was overwritten by a file whose name differed only in case, so the
figure was worked out again from the PGN, in pairs as fastchess counts them.

Seed 0 was +0.2, so the two seeds sit 13.9 apart. That is inside the 15
predicted and inside their joint interval, so seed spread at 102M positions is
consistent with §2. The conditional part missed: seed 0 did not accept H1, so
seed 1 was expected at or below +10, and it came in at +14.1.

The net is `nets/gen9_screlu_cos_s1.nnue`, SHA-256
`e733e437ad3fbe7cb8b8ab0dbeeaa6f8c29d1bebdbf36f76a8e1851d1bd4642b`, self-check
evalsum 194037. It became the v9.2-rc network and will be committed when it
ships.

### SPSA

Stopped at iteration 626 of 5,000, after 5,008 games. No values were used, and
the validation SPRT never ran, so the prediction was not tested.

The tune had become a random walk. A t-statistic on each parameter's steps,
testing whether they favoured one direction more than chance would, found
nothing: 16 of the 17 lay between -1.6 and +1.6. The 17th was 2.56, and 17
tests of pure noise produce one that large about one time in six. The values
kept moving all the same.
Between iterations 600 and 625 alone, `RfpMaxDepth` went from 8 to 5 and
`NmpDepthDiv` from 6 to 4. The cause is the step size in `testing/spsa.py`,
set out in METHODOLOGY §10.
