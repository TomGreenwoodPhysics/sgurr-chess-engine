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
published values. The current pool (pool-2026-09-F) is 16 families spanning
3087 to 3438, listed with their exact builds in `benchmarks/pool.json`. It
extends pool-E under identical conditions, so it is solved on pool-E's games
and its own, and on nothing older. Answers *"how strong is it on an absolute
scale?"*

More families make the absolute figure firmer, not the gaps. On pool-E the
anchors implied ratings for Sgurr about 52 Elo apart beyond sampling noise,
while every version gap was the same against every engine within noise. So
nine families left about ±35 of systematic error on the absolute rating. On
pool-F the spread is 30 to 49 Elo across sixteen families, which leaves about
±15 to ±24.

Since pool-E, gains are decided and sized by SPRT, which reaches a given error
bar far more cheaply. Each release then gets one pool run at about ±12 to
confirm the gain carries over to other engines (§6).

**Conditions are part of the instrument, not a detail.** Hash is pinned at 256
for every engine, the book is generic and external, pondering is off and
threads are 1, because that is what CCRL specifies and the anchors earned
their ratings under it. Leaving any of these to each engine's default silently
biases the result: see §9, where it cost 45 Elo.

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
| factorised buckets **+2.0** | inside noise |
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
| factorised king buckets | **0.00471** (best) | +2.0 |
| naive king buckets | 0.00493 | **−10.7** (worst) |
| unbucketed 768×384 | 0.00558 | 0 (reference) |
| HL512 | **0.00661** (worst) | **+9.0** (best) |

Loss is not merely uninformative here: across these variants it is
*anti-correlated* with playing strength. Earlier instances: the gen6 net A/B,
HL=512 on gen6 data, and the data-volume probe (§4).

A sixth instance, 2026-09-24: retraining the v9.1 net with a cosine learning
rate instead of a constant one lowered validation loss from 0.01132 to 0.01113
on the same holdout. Two seeds scored +0.2 and +14.1 against the original, an
average inside the seed noise of §2.

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
| King buckets (naive, then factorised) | ~0 | ~2 days |
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
| v3.1 soft time limit | +24.6 | −48, **withdrawn** | n/a |
| v9.2 (search fixes and cosine net) | +50.5 and +0.2 to +14.1 | +33.9 on pool-E, +43.1 on pool-F | ~0.6 to 0.75 |
| v9.3 (search batches and speed) | about +50 | +47.2 on pool-E, +48.0 on pool-F | ~0.95 |
| v9.4 time management | +54.9 | +64.7 | ~1.2 |

Large gains largely survive; small ones evaporate. With §2 in hand,
the likely explanation is not a mysterious "compression" but that the small
self-play numbers were never real: they sat inside the noise floor.

The soft-limit row was first entered as negative, the only case of a small
gain inverting. The −48 compared v3.1's gauntlet with v3.0's from four
days earlier, 420 games against 210, with a joint error near ±47; the three
solves that seemed to confirm it reused the same games. A direct test at
10+0.1, one net with only the clock policy changed, then found the flat soft
limit, stability scaling and hard-only level (963 games, all within ±23). The
lesson drawn from the −48, that time-management results do not carry between
time controls, may still be true, but nothing in this project shows it.
v9.4's rebuilt time management carried over in full: +54.9 in self-play at
8+0.08 and +64.7 on the pool at 10+0.1.

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
* **Opponents forfeiting on an illegal move (2026-08-09).** Two engines added
  to a new calibration pool emit uppercase promotions (`a7a8Q`, where UCI
  requires `a7a8q`). fastchess rules that illegal, so they lost every game in
  which they promoted: 23.9% and 17.6% of their games, 14% of the whole run.
  Nothing errored. The gauntlet produced a complete result whose only tell was
  a number that had moved. See §9.
* **A training default nobody chose (2026-09-24).** `train.py` defaulted to a
  constant learning rate and the SCReLU launcher never asked for cosine, so the
  v9.1 net trained without the decay every net since gen3 had used. The run
  looked normal and the net was strong. The default is now cosine, and the
  trainer logs the schedule it used.
* **Solves that mixed pools, and repeated openings (2026-09-24).** Ordo read
  every calibration PGN in the folder, so pool-D ratings included pool-B's
  uncontrolled games: v8.2 read 3033 in the combined solve against 3012 on
  pool-D alone. Separately, two runs of v9.1 started from the same opening seed
  and replayed about 470 openings. Neither showed in the output. Each pool now
  has its own games folder, and a continued run takes a new seed.
* **Broken anchors on pool-F (2026-09-26).** Onyx 2.0 played more than 400
  Elo below its CCRL rating, and its binary names its author as "Dylan (with
  Claude)", so it is probably a different engine with the same name.
  Priessnitz 2.0 lost on time in 31% of its games under our conditions. Both
  would have inflated Sgurr's rating. The implied-rating check registered
  before the run caught the first, and the endings check the second. Both
  engines were dropped and their games are left out of the solve. The lesson
  for the next pool: compare an engine's `id author` with the author CCRL lists
  before its first game.

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
8. **A change that cannot alter the tree needs no SPRT.** When the bench
   fingerprint matches on the AVX-512, AVX2 and scalar builds, and a set of
   fixed-depth searches return the same nodes, scores, PVs and moves, the
   change can only affect speed. It is accepted on measured speed (§11), and
   its Elo is carried into the next pool run with everything else.
9. **An SPRT may be stopped once its 95% interval clears zero, after at least
   300 games.** Its job here is to confirm the sign and give a rough size. The
   minimum is there so that a real regression does not slip through. Simulated
   with the noise of a typical run here and a look every 100 games, a change
   that costs 5 Elo clears zero 2.3% of the time and one that costs 10 about
   0.4%. A stopped run is recorded with its estimate as it stood and marked as
   stopped. That estimate reads high, most of all after an early stop: at 300
   games the interval is ±23, so stopping there means the run read +23 or
   more. The release's pool run is the check on it.

---

## 9. Measuring the measurement: v8.2 at 3012, not 3058

On 2026-08-10 v8.2 was re-measured at **3012.1 ±5.8** over 9,890 games, about
**45 Elo below** the 3058 ±7 published on 2026-08-05. The engine is
byte-identical between the two runs. Only the measurement changed.

The exercise began as a pool replacement: the old pool had saturated (50.8%
against its strongest member, 86-97% against five of eight) and could not
resolve a v8.3. Building a new one surfaced three faults in how strength had
been measured all along.

### Three uncontrolled variables

**Hash was never pinned.** The gauntlet passed only the time control, so every
engine ran at its own default: 8 MB for two of them, 64 for three, 128 for
one, 48 for Sgurr. CCRL's published conditions require *the same* value, 128
or 256, for every engine in a match, and the anchors earned their ratings
under that rule. An engine running on a fraction of the memory it was rated
with underperforms its anchor, and an underperforming anchor inflates the
engine under test. The signature was visible before the cause was: the solve
climbed monotonically for 4,182 games and never converged.

**The opening book was chosen by the engine under test.** `book_gen.py` keeps
positions whose score falls within ±70cp *according to Sgurr's own
evaluation*. Strength was therefore being measured on openings Sgurr believes
are balanced, and any position type it systematically misjudges entered the
book mislabelled. Colour-reversed pairs cancel an individual opening's
imbalance; nothing cancels a biased choice of which openings appear.

The same book was also too small to support the error bar being quoted. At 150
positions, measured between-opening variance was **2.96× what chance predicts**
(Sgurr scored between 9% and 80% depending on the opening), which makes the
openings a *sample*, contributing

    sqrt(0.01724 / 150) = 1.07 percentage points ~= +/-15 Elo

that **no number of games can reduce**, while the run quoted ±5.4. Uncertainty
here falls as sqrt(openings), not sqrt(games). Replaced with a generic
external book (34,700 ECO lines, 8 moves per side), which removes the
self-reference, drops the opening term to ~±0.5, and satisfies CCRL's book
condition at the same time.

**Two opponents could not play legal UCI.** Covered in §7. 580 of 4,182 games,
14%, ended in a forfeit that inflated Sgurr.

### The conclusion that had to be withdrawn

From the contaminated run, six anchors appeared to disagree by **171 Elo**
about where v8.2 sat. That was reported as strong evidence that CCRL transfer
bias exceeded the ±45 then in use. It was an artefact: the extreme outlier was
the engine forfeiting a quarter of its games.

The methodological error is worth stating plainly, because it is not the same
as the engine bug. The binaries were verified to start and to return a legal
move, which is what §7's existing practices call for. The aggregate ratings
were then read **without checking how the games ended**. The forfeits were
recorded in the PGN throughout.

**Rule added: check terminations before reading ratings.** A results table is
not evidence until the games behind it have been checked for forfeits,
timeouts and adjudications.

### What the controlled measurement shows

Five families, 3056 to 3312, all bracketing v8.2 from above. Hash 256 for
every engine, generic book, pondering off, one CPU, 10+0.1, idle machine, zero
forfeits.

| anchor | published | implies v8.2 | ±95% |
|---|---|---|---|
| 4ku 5.1 | 3056 | 3004 | ±8 |
| Bit-Genie 9 | 3086 | 3036 | ±8 |
| Monolith 3 | 3260 | 3001 | ±10 |
| Drofa 4.1.0 | 3286 | 2986 | ±11 |
| Mantissa 3.7.2 | 3312 | 3034 | ±10 |

**Anchor spread 50 Elo, against 90 on the old pool.** A wider and more diverse
pool under controlled conditions does agree better, which is what the exercise
set out to test. But the residual is real, not sampling noise: Bit-Genie's ±8
and Drofa's ±11 do not overlap. Systematic uncertainty on the absolute number
is therefore **~±25**, improved from ~±45 and still four times the sampling
error.

**Why the residual exists is unknown.** Draw rate does not predict it (−0.01),
opponent strength does not (−0.35), mean game length is suggestive (+0.84) but
rests on five points and does not reach significance. Style is a live
hypothesis and untested.

**The 45 Elo drop is likewise unattributed.** Pool, hash and book all changed
at once, and the book change alone did two things: it removed the
self-selection bias *and* changed position character from 8-ply filtered
fragments to 16-ply real openings, which is itself a style effect. Attributing
the drop to any one of them would repeat the mistake above. Decomposing it
needs runs that vary one variable at a time.

### Consequences

* **The absolute scale of every pre-2026-08-10 row is ~45 Elo high.** Their
  version-to-version gaps stand, being measured inside one solve; the level
  does not. Re-measuring the ladder under pool-D conditions is owed.
* **`testing/engine_gate.py` gates the pool**, enforced at preflight. It
  checks UCI-legal promotions, that the returned move is legal *in the
  position* (a format-only check passed an engine that ignored `position fen`
  entirely), and that a move comes back under clock-based `go`.
* **Conditions are now recorded in `pool.json`**: hash, book file with its
  sha256, and each engine's exact build.
* **An error bar is only as good as its widest ignored term.** ±5.4 was quoted
  while the opening draw alone contributed ±15. Before quoting an interval,
  ask what it is not counting.

---

## 10. SPSA steps were far too large

The tune of the v9.0 search batch validated at +90 as a set and shipped in
v9.1. The next, of 17 search parameters that had never been tuned, was stopped
on 2026-09-24 after 5,008 games because it had become a random walk.

The values had moved a long way. `NullMoveReduction` went from 2 to 5 and
`CheckExtMaxDepth` from 4 to 10. The check was whether each parameter's steps
favoured one direction more than chance would. Across 626 iterations, 16 of
the 17 t-statistics lay between -1.6 and +1.6. The 17th was 2.56, and 17 tests
of pure noise produce one that large about one time in six.

The cause is the step rule in `testing/spsa.py`. It derives `a` so that an
early step is about a fifth of the perturbation `c`:

    step = a_k * (s - 0.5) / c_k        a = c^2 * (A + 1)^alpha / (5 * 0.15)

An 8-game match gives a typical `|s - 0.5|` of 0.15, so every iteration moves
every parameter by about `c/5`, and over 8 games most of that result is noise.
OpenBench's
usual end-of-run rate, `R_end` 0.002, moves parameters roughly fifty times less
per game. Small steps let many matches average out before a value goes
anywhere. Large ones let each match push it.

Consequences:

* **The v9.1 values stand as a set,** because the set was validated in games.
  A single value that moved no further than noise would carry it, such as
  `IirMinDepth` from 4 to 8, says nothing about that parameter.
* **The tuner is fixed before the next tune,** with steps sized from an
  end-of-run rate as OpenBench does. A tune is also checked while it runs,
  since values that keep moving are not progress unless their steps favour a
  direction.

---

## 11. Speed: profile first, then measure pinned

**Profile the release build, and only the search thread.** `tools/profile.py`
suspends the search thread about every millisecond, reads its instruction
pointer and maps it to functions and source lines with llvm-symbolizer. Two
early mistakes shaped it. Sampling every thread put half or more of the
samples in `??`, which turned out to be idle Windows worker threads parked in
ntdll. And a build without LTO overstated call costs that the PGO and ThinLTO
release build inlines away. Profile what ships.

**Measure speed pinned and paired.** `tools/npscmp.ps1` runs two binaries
alternately at Hash 256, each pinned to one core at High priority, and reports
the paired change with a 95% interval, usually over 16 pairs. Pairing cancels
drift in clock speed and temperature. Pinning keeps the scheduler out of it.

What it measured in September 2026, every change leaving the tree identical:

| change | nps |
|---|---|
| move picker stores raw moves (zeroing them was 12.6% of search time) | **+19.5% ±1.9%** |
| eval cache, 2 MB | **+5.2% ±0.8%** |
| accumulator stack, one level per ply | +0.5% ±1.2% |
| move predicates computed once per move | +0.0% ±0.6% |
| early TT prefetch of the child position | -0.7% ±0.9% |
| uninitialised move list | -0.8% ±1.6% |
| PV table, 32 KB inside the engine object | -1.0% to -2.1% |
| the same table on the heap | -0.6% ±0.3% |

The largest gain was a cost the profiler found and no reading of the code had
flagged. Two standard techniques, the per-ply stack and the early prefetch,
measured nothing on this engine. The eval cache's size mattered more than
expected: 1 MB gave +3.4%, 2 MB +5.3%, 4 MB +3.0% and 16 MB -0.3%, so the size
was chosen by measurement.

Where data sits can matter more than what the code does. Inside the engine
object the PV table cost 1 to 2%, and a build with its per-node lines removed
was about as slow, so the cost came from the object's layout. On the heap it
costs 0.6%.
