# Roadmap

Current: **v8.0 "Thearlaich" — 3006 ±11** (pool-2026-07-B, 3,329 games).
Written 2026-08-01, after the architecture × data study. Supersedes the
2026-07-21 roadmap, whose central recommendations (king buckets, width) were
subsequently measured at ~0 and withdrawn — see `METHODOLOGY.md` §2 and §4.

---

## The strategy in one paragraph

Three things have ever moved this engine: **better data, better search, and
raw speed.** Architecture has moved it by nothing measurable. Data costs
*machine time* and no attention; search costs *attention* and no machine time.
They are therefore complementary, and the plan is to run them concurrently —
datagen in the background for weeks at a time, search work in the foreground
while it runs.

---

## Now: gen9 datagen (background, ~2 weeks)

| setting | value | why |
|---|---|---|
| labeller | **v8.0 net** (`nets/gen8.nnue`) | the flywheel's only proven lever; +126 last turn |
| build | `-DSGR_RFP=0`, SIMD on | RFP returns unsearched scores — it cost gen6 entirely |
| λ | 0.9 | sweep-confirmed optimum; 0.6/0.7/0.85/1.0 all worse or level |
| width | HL384 | genuinely does not matter (§4); keep the simple option |
| king buckets | off | measured ~0 twice, naive and factorized |
| nodes/position | 150,000 | unchanged; see the open question below |
| **target** | **as much as the calendar allows — 100M+** | returns were still *accelerating* at 56M |

At the measured ~7.9M positions/day this is ~12–14 days for 100–110M. The
cost is calendar time, not attention: launch it and leave it.

**Build the curve while you are at it.** gen9 will hold the largest dataset
the project has ever had. Training on 56M and 110M subsets of it and racing
them extends the data-scaling curve *beyond* the currently measured range for
the price of two trainings and two matches — the one place where extrapolation
is currently unavoidable.

---

## Concurrently: search work (foreground)

Search changes re-use a fixed net, so they carry **no training-seed variance**
— their only error is match noise, which more games actually fixes. That makes
them the cheapest things to validate in the whole project, and the historical
returns are large (RFP +176 self-play; the v6.0 package +57.3).

| # | change | est. | notes |
|---|---|---|---|
| 1 | **UCI `setoption` infrastructure** | 0 | there are currently *zero* UCI options; hard prerequisite for #3, and a standards fix |
| 2 | **Correction history** | +20…+35 | largest single missing search feature; corrects static eval by eval-vs-search disagreement history |
| 3 | **SPSA harness + first parameter tune** | +30…+60 | every margin, reduction and threshold is hand-set and has *never* been tuned; needs #1 |
| 4 | **Batch: IIR + capture history + razoring** | +15…+30 | individually these are sub-20 and unmeasurable; run them as one SPRT or not at all |
| 5 | ProbCut | +10…+20 | interacts with RFP; measure jointly |

Ordering is deliberate: #1 unlocks #3, and #3 is the largest untouched surface
in the engine.

---

## Owed / housekeeping

* **Re-baseline v6.0 and v5.0 on the current machine.** Every row up to v6.0
  was measured on the old i5; v7.0 and v8.0 on the 7800X3D. One Ordo solve
  places them on a single scale, but the cross-hardware caveat is currently
  carried in prose on each row.
* **Firm up the 3000 milestone.** v8.0 is 3006 ±11 — the interval brackets
  3000. A few thousand more gauntlet games would settle whether it is crossed.
* **Leave-one-out decomposition of the v6.0 package** (improving / histLMR /
  singular). Owed since 07-16. Purpose is finding *passengers* to delete, not
  Elo — note each component is likely sub-20 and therefore individually
  unmeasurable against the noise floor, so treat it as a simplification
  exercise.

---

## Open questions worth an experiment

* **Does label depth pay?** Everything to date uses 150k nodes/position.
  Stockfish's experience says moderate depth × huge volume beats deep × few,
  and our own data agrees that volume is king — but this has never been tested
  here. A clean test: label ~10M positions at 600k nodes with the v8.0 net,
  train, and race against a 10M control labelled at 150k. Same position count,
  only depth differs. ~1 day.
* **Where does the data curve actually flatten?** Returns were still
  accelerating at 56M. gen9's dataset answers this for free (above).
* **Do king buckets ever pay?** Twice measured at ~0, but both times at ~7M
  positions per bucket. The technique demonstrably works in engines trained on
  billions of positions. Retest only when the dataset is an order of magnitude
  larger; the implementation is merged, verified and dormant, so the retest is
  nearly free.

---

## Explicitly not doing

* **LazySMP / multithreading.** Large project, and the rating scale here is
  single-core — it would measure exactly zero. Revisit only if the goal
  changes to long-TC or tournament play.
* **Chasing sub-20 Elo net changes.** Below the noise floor without multi-seed
  averaging. This is a measurement limit, not pessimism.
* **Further width / bucket / λ tuning.** All three measured flat on clean
  data. The dataset, not the architecture, is the product.
