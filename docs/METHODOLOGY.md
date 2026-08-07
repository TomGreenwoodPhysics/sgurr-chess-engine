# Methodology and findings

`DEVLOG.md` records *what happened, when*. This file records *what was
learned*: the transferable results, the measurement discipline behind them,
and the decision rules that came out. Where a conclusion was later overturned,
the correction is kept alongside it; the corrections are the useful part.

---

## 1. How strength is measured

Two independent instruments, used for different questions.

**Self-play SPRT**: the candidate against one baseline, 8+0.08, sequential
test with `elo0=0 / elo1=5`, both sides on the same machine and the same
binary except for the change under test. Answers *"is this change an
improvement?"* with a bounded error rate.

**Pool calibration**: a gauntlet against fixed open-source engines with
published CCRL Blitz ratings, at 10+0.1, solved with Ordo anchored to those
published values. The pool is four families (Blunder, Zahak, Weiss, Igel)
spanning 2105 to 3055.
Answers *"how strong is it on an absolute scale?"* Ordo re-solves over **all**
accumulated PGNs, so every Sgurr version sits on one internally consistent
scale.

Both are needed. Self-play measures the delta precisely but drifts from
absolute reality; the pool grounds it but with wider bars. Where they have
been compared, they agree (see §6).

**Anchor hygiene.** An audit on 2026-07-15 found every pool-A anchor inflated
by 12-50 Elo (mean ≈31) because values came from engine READMEs rather than
the live CCRL list, and one "anchor" had never had a CCRL rating at all.
pool-2026-07-B re-sourced everything from the live list. Consequence: ratings
are only comparable **within one solve**, and the ledger says so on every row.

---

## 2. The noise floor: what is measurable at all

**Two nets trained on identical data with an identical recipe, differing only
in random seed, score +13.7 ±10.3 against each other over 3,000 games**: a
95% interval excluding zero. Training is not reproducible at the Elo level.

This was assumed to be ~0 for the project's entire history and never checked.
Measuring it invalidated several published conclusions:

| result | fate |
|---|---|
| gen8 net vs gen7 **+126.5** | survives |
| 14M vs 56M data **−65** | survives |
| λ=0.6 **−52** | survives |
| gen7 net vs gen6 **+44.4** | survives |
| HL512 width **+9.0** | **inside noise, withdrawn** |
| naive king buckets **−10.7** | inside noise |
| factorized buckets **+2.0** | inside noise |
| λ=0.85 **−4.4** | inside noise |

**More games do not fix this.** The variance is in the *training*, not the
measurement: 10,000 games shrinks the match error and leaves the seed error
untouched. Resolving sub-20-Elo net effects requires training N seeds per
configuration and averaging, 3-5× the cost of every architecture experiment.

**The asymmetry that follows is the single most useful planning fact in this
project:**

* **Net/architecture changes** carry an irreducible ±14 floor. Small gains are
  effectively unmeasurable at reasonable cost.
* **Search changes** re-use one fixed net, so they have *no training variance*.
  Their only error is match noise, which more games genuinely does shrink.

Search work is therefore far cheaper to validate than architecture work, and
should be preferred when both look similarly promising.

This also retroactively explains the "magnitude predicts survival" pattern
noticed on 2026-07-16: small deltas evaporated partly because they were never
distinguishable from noise to begin with.

---

## 3. Training loss does not predict strength

Five independent instances, culminating in a fully inverted ranking on
identical data:

| net (gen8 56M, λ=1.0) | training loss | measured Elo |
|---|---|---|
| factorized king buckets | **0.00471** (best) | +2.0 |
| naive king buckets | 0.00493 | **−10.7** (worst) |
| unbucketed 768×384 | 0.00558 | 0 (reference) |
| HL512 | **0.00661** (worst) | **+9.0** (best) |

Loss is not merely uninformative here: across these variants it is
*anti-correlated* with playing strength. Earlier instances: the gen6 net A/B,
HL=512 on gen6 data, and the data-volume probe (§4).

**Rule: never select an architecture, dataset size, or hyper-parameter on
loss. Only games decide.** Loss retains exactly one valid use, *train-vs-val
divergence within a single training run*, as an overfitting diagnostic.

---

## 4. Data volume dominates architecture

Five configurations, 15,000 games, all measured against HL384 @ 56M:

| | 14M | 28M | 56M |
|---|---|---|---|
| **HL256** | −75.8 ±10.5 | - | −6.9 ±10.0 |
| **HL384** | −65 (32ep) / −119.1 (8ep) | −48.5 ±10.4 | 0 (ref) |
| **HL512** | - | - | +9.0 ±10.3 |

**Data beats width by roughly 4×.** The entire 256→512 width range spans ~16
Elo, every point inside the noise floor. The 14M→56M data range is worth
**65 Elo**, far outside it.

**A smaller net is not more data-efficient.** Each architecture's shortfall at
14M against *its own* 56M ceiling: HL384 65 Elo short, HL256 69 Elo short,
identical. So the appealing idea of trading a slightly weaker net for many
more flywheel turns (2-day generations instead of 7-day) does not work: at
14M you lose ~65-70 Elo whatever the width, and since that net becomes the
next generation's *labeller*, the deficit compounds rather than washing out.

**Returns accelerate over the measured range.** 14M→28M buys +17; 28M→56M
buys +48. The curve is convex, so 56M is *not* near saturation and more data
was still paying when the experiment stopped. (Beyond 56M is extrapolation,
untested.)

**The recipe confound, resolved.** Comparing subsets forces a choice: equal
optimiser steps (small sets take many passes → overfitting risk) or equal
epochs (small sets get fewer steps → undertraining risk). Both biases push the
same way, so one recipe cannot separate them. Measuring both arms at 14M gave
−65 (32 epochs) vs −119 (8 epochs): the deficit is robust to recipe, and
undertraining hurts more than overfitting at this scale.

**The data-scaling probe is unreliable.** The pipeline's `probe` stage
declared gen6, gen7 *and* gen8 "saturated" (0.44%, 0.32%, 0.21% half→full
validation-loss improvement) while 14M→56M was worth 65 Elo. It is a
loss-based signal, see §3. It must not be used as a datagen stopping rule.

---

## 5. What actually moves the needle

Ranked by measured Elo per unit of effort:

| change | measured | cost |
|---|---|---|
| Flywheel turn (gen7→gen8 labeller + 5× data) | **+126.5** | ~7 days datagen |
| RFP + LMP search (v5.0) | +176 self-play → **+119** pooled | days of coding |
| Search refinement package (v6.0) | **+57.3** | days of coding |
| Clean RFP-free data regen (gen7) | **+44.4** | ~2 days datagen |
| Singular extensions alone (inside the v6.0 package) | **+77.2** | part of days |
| Packed TT + lazy move picker (v8.2) | +15.4% NPS → **+31.5 measured** | ~1 day |
| PGO + ThinLTO + data layout (v8.1) | ~+20% NPS → **+21.2 measured** | ~2 days |
| AVX-512 / int16 NNUE inference | ~+22% NPS (≈+15 to +22 Elo) | ~3 h coding |
| Improving flag alone (inside the v6.0 package) | **+19.6** | part of days |
| King buckets (naive, then factorized) | ~0 | ~2 days |
| Width, λ tuning | ~0 (inside noise) | ~1 day |
| History-adjusted LMR as shipped | **~0** (inert divisor) | part of days |

Two observations. **Data and search dominate; architecture is a rounding
error.** And the two big categories are complementary in resource terms,
datagen consumes CPU for days while coding consumes none, so they should run
concurrently.

**The ~70-Elo-per-doubling rule is retired as a predictor, 2026-08-05.**

It was adopted as a rule of thumb, appeared to be confirmed once, then failed
the second time it was used to predict something. Both tests were clean: a
speed-only release, bench-fingerprint-identical to its predecessor, so speed
was the only variable in existence between them.

| release | NPS gain | predicted | measured | ratio |
|---|---|---|---|---|
| v8.1 (PGO + ThinLTO + layout) | +20% | +18.4 | **+21.2 ±8.7** self-play, +20.9 pooled | 1.14 |
| v8.2 (packed TT + lazy picker) | +15.4% | +14.5 | **+31.5** pooled, 11,144 games | **2.17** |

v8.2's implied rate is ~131 Elo per doubling, not 70. The obvious escape, that
Ordo mis-weighted a saturating pool, does not survive checking: solving each
anchor separately gives +29, +21, +31 and +28, mean +27.1, so all four
independently disagree with the prediction in the same direction.

The honest reading is that **one agreement was never evidence of a law.** v8.1
matching to 0.3 Elo made the rule feel established when it rested on a single
point; the second point is 2.2× off. A constant fitted to other engines,
at other time controls, on other hardware, was being carried as though this
project had derived it.

What replaces it: nothing. Speed changes get a gauntlet like everything else.
The rule is still useful for *ordering* candidate work (faster is better,
monotonically), but a number produced by it is a guess, and this project's
convention is that guesses do not enter the ledger, the README or the website
without the word *inferred* attached. That convention is the only reason this
cost a footnote instead of a wrong published rating.

### Anchored ratings carry a systematic error the error bar does not show

v8.2's 11,144 games are enough to place it against each anchor *separately*
rather than through Ordo's joint fit. The four anchors disagree by **90 Elo**:

| anchor | CCRL | implies Sgurr v8.2 at |
|---|---|---|
| Igel-2.2.2 | 2982 | 3106 |
| Weiss-1.2 | 3055 | 3060 |
| Zahak-5.0 | 2726 | 3046 |
| Weiss-1.0 | 2896 | 3016 |

Ordo's solve is 3058.5 **±6.5**, and that ±6.5 counts sampling noise only. The
spread above is not noise: it is stable across releases (63, 100 and 90 Elo for
v8.0, v8.1 and v8.2) and it is what happens when ratings measured under CCRL's
book, control and hardware are transferred to ours. Systematic uncertainty on
any *absolute* figure here is nearer **±45**.

This does not touch version-to-version gaps, which are measured inside one solve
against one pool and are why the ledger has always led with them. It does mean
"3058 ±7" should never be read as 3058 ± 7.

### Tree size measures what a feature spends, not what it buys

The v6.0 package (improving flag + history-adjusted LMR + singular extensions)
shipped as one undecomposed SPRT at +57.3. Node counts made the three look
wildly unequal, which was true, and suggested an ordering, which was wrong:

| component | tree change when removed | Elo when removed |
|---|---|---|
| singular extensions | **−46.0%** (it costs +85% of the tree) | **−77.2 ±19.6** |
| improving flag | +27.6% | −19.6 ±10.5 |
| history-adjusted LMR | +1.3% | +1.1 ±8.7 |

Singular is by far the most expensive thing in the search and by far the most
valuable. Reading its +85% tree cost as evidence it was over-firing produced a
registered prediction of *positive* for its removal, at 60% confidence. The
measured value was −77.2, rejecting in 36 minutes.

Node counts did do one job well: they identified the inert component before any
games were played, and explained *why* it was inert (a divisor two orders of
magnitude too large). As a screen for "is this doing anything at all", tree size
works. As a proxy for value, it is not merely uninformative: for singular it
pointed the wrong way, which is the same failure mode as §3's loss result.

This is the second cheap proxy in this project to be caught predicting strength
backwards. There is unlikely to be a third that behaves better.

---

## 6. Self-play gains partially survive the pool

| change | self-play | pooled | ratio |
|---|---|---|---|
| RFP (v5.0) | +176 | +119 | ~0.68 |
| refinement package (v6.0) | +57.3 | +83 | ~1.0 (no compression) |
| gen8 net | +126.5 | +103 | ~0.81 |
| history malus | +33 | ~0 | ~0 |
| v3.1 soft time limit | +24.6 | negative | <0 |

Large gains largely survive; small ones evaporate or invert. With §2 in hand,
the likely explanation is not a mysterious "compression" but that the small
self-play numbers were never real: they sat inside the noise floor.

---

## 7. Silent failures cost more than bugs

Every expensive incident in this project shared one property: **the failure
produced plausible output instead of an error.**

* **RFP-poisoned labels (gen6).** The data generator used reverse futility
  pruning, which returns raw rather than searched scores. The dataset looked
  fine and trained fine; the whole generation was a wash. Cost: one full
  cycle. Fix: labellers must be built `-DSGR_RFP=0`, enforced in the launcher.
* **Dead baked-in net paths.** 44 of ~50 released binaries had an absolute
  `-DSGR_DEFAULT_NET` that only resolved on the machine that built them. On a
  new machine they fell back to the hand-crafted eval: one `info string` line,
  no error, ~430 Elo missing. Discovered during a workstation migration; would
  have silently corrupted every calibration.
* **A hardcoded hardware string** put the wrong CPU on a ledger row.
* **A mis-set `release_exe`** would have had the pipeline calibrate the *old*
  engine while labelling the row with the new version's name.
* **Antivirus blocking freshly linked binaries** killed a multi-hour gauntlet
  32 seconds in, and later skipped a validation gate without failing.

Practices adopted in response: binaries self-report their configuration at
startup (`nnue: loaded <net> (avx512, k=8)`); a bit-exactness selfcheck gates
every net before it is allowed into a match; A/B binaries are verified
node-identical at fixed depth before being trusted; the ledger is append-only
with corrections as new rows; and harnesses abort rather than continue when a
precondition fails.

---

## 8. Decision rules

1. **Only games decide.** Never loss, never a probe, never node count, never
   intuition about capacity. Two cheap proxies have now been caught predicting
   strength *backwards* (§3 loss, §5 tree size); assume the next one will too.
2. **Respect the ±14 net-training noise floor.** If a net change is predicted
   to be worth less than ~25 Elo, either budget for multi-seed averaging or do
   not run it.
3. **Prefer search work to architecture work** when both look equally
   promising: search has no training variance and is cheap to validate.
4. **One variable per test**, and verify it *is* one variable (node-identical
   binaries, matching nets, equal-speed baselines).
5. **Timed measurements require an idle machine.** Two concurrent experiments
   corrupt each other; this happened and cost a night of games.
6. **Record negative results with the same care as positive ones.** Most of
   this document is negative results.
7. **Register the prediction before the run.** Point estimate, confidence, and
   an explicit falsification condition, committed ahead of the games. It costs
   ten minutes and it is the only thing that stops a wrong prediction being
   quietly reshaped into a right one afterwards. The 2026-08-03 singular result
   is the case in point: the reasoning was wrong in a way that would have been
   easy to forget having believed.
