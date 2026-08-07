# Roadmap

> **Status note, 2026-08-07.** This document is the 2026-08-01 snapshot and is
> left as written. Two speed-only releases have shipped since: v8.1 (3027 ±11)
> and v8.2 (3058 ±7). Neither changes the plan below, but v8.2's calibration
> did establish that the pool can no longer resolve a v8.3 — see
> `../benchmarks/ledger.md`. The rating baseline in the next line is therefore
> the one this plan was written against, not the current release.

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
| ~~1~~ | ~~UCI `setoption` infrastructure~~ | 0 | **done 2026-08-02** — 30 options, 26 of them tunable search parameters |
| 2 | **SPSA: singular extensions first** | +20…+50 | promoted. Singular measured **+77.2** on 2026-08-03 as an *unrefined* implementation with three never-tuned constants (`SingularMinDepth`, `SingularTtDepthSlack`, `SingularMargin`). The most valuable thing in the search is also among the least tuned |
| 3 | **Correction history** | +20…+35 | largest single missing search feature; corrects static eval by eval-vs-search disagreement history |
| 4 | **Retune `HistLmrDiv`** | +0…+15 | history-adjusted LMR has been shipped INERT since v6.0 — the divisor is ~2 orders of magnitude too large, and removing the feature measures +1.1 ±8.7. At 5,000 the tree moves ~10%. Cheap, and it is already an exposed option |
| 5 | **SPSA: everything else** | +20…+40 | the remaining 22 parameters. Exclude the time-management block or tune it against the pool — §6 records the v3.1 soft limit at +24.6 self-play and NEGATIVE pooled |
| 6 | **Batch: IIR + capture history + move-loop futility + SEE pruning + null-move R scaling** | +40…+80 | individually sub-20 and unmeasurable; one SPRT resolves the batch in ~2 h. Bisect by halves on failure, never by item |
| 7 | **Singular refinements** | +15…+30 | double extensions, negative extensions, multicut return from the singular search. Raised from the original +10…+20: the base feature is worth far more than assumed, so its refinements plausibly are too |
| 8 | ProbCut | +8…+15 | interacts with RFP; measure jointly |

Ordering changed on 2026-08-03. The decomposition put singular extensions at
**+77.2** — roughly four times the improving flag, and the single most valuable
thing in the search — while its three constants have never been swept. Tuning
the most valuable and least tuned feature now outranks adding a new one.

Do not judge any of these by tree size. §5 of `METHODOLOGY.md` records what
happened the last time that was tried.

---

## Owed / housekeeping

* ~~**Pool-calibrate v8.2.**~~ **Done 2026-08-05: 3058.5 ±6.5** over 11,144
  games, **+31.5 vs v8.1 same-solve** against **+14.5 predicted**. The
  ~70-per-doubling rule missed low by 17 Elo; per-anchor solves give +29/+21/
  +31/+28, so all four agree and it is not a solver artefact. Ledger, CHANGELOG,
  README and the website carry the measured figure. Two limits surfaced, both
  now blocking below: **anchor disagreement** and **pool saturation**.

* **Rebuild the pool before v8.3.** Now the binding constraint on everything
  else here, and it is measurement work rather than engine work.
  * **Saturation.** v8.2 scores **50.8%** against Weiss-1.2, the strongest
    engine in the pool, and 86–97% against five of the other seven. Those five
    contribute almost no information. The pool cannot resolve the next
    improvement, whatever it is — needs 2–3 engines in the 3050–3200 band.
  * **Anchor disagreement.** The four anchored engines disagree by **90 Elo**
    about v8.2's absolute rating (Igel 3106, Weiss-1.0 3016). Longstanding —
    63/100/90 for v8.0/v8.1/v8.2 — and not sampling noise, so Ordo's ±6.5 is
    sampling error only and the true systematic band is ~±45. Same-solve gaps
    are unaffected, which is why the ledger has always led with them.
  * **The 150-position opening book.** At 11,144 games every opening has been
    played ~74 times. Ordo's interval assumes independent games; heavily
    recycled openings are not, so reported errors are optimistic and the
    estimate is partly *"strength on these 150 positions"*. A few thousand
    positions is standard practice and this is the cheapest of the three fixes.
* **Validate or drop the v9.0 batch.** Ten search features, measured
  **−1.0 ±21.1** over 698 games, now default-OFF in the tree. The interval
  spans −22…+20, so it is undecided rather than dead. Bisect order and outcome
  bands: `benchmarks/v90_batch_prediction.md`. Needs machine time that gen10
  will occupy for weeks.

* **Re-baseline v6.0 and v5.0 on the current machine.** Every row up to v6.0
  was measured on the old i5; v7.0 and v8.0 on the 7800X3D. One Ordo solve
  places them on a single scale, but the cross-hardware caveat is currently
  carried in prose on each row.
* ~~**Firm up the 3000 milestone.**~~ **Done 2026-08-03**, though not the way
  this line expected. More games on v8.0 were never needed: v8.1's **3027 ±11**
  gives an interval of [3016, 3038] that does not touch 3000, where v8.0's
  [2995, 3016] straddled it at ~84%. The milestone was crossed by making the
  engine faster, not by measuring it harder.
* ~~**Leave-one-out decomposition of the v6.0 package.**~~ **Done 2026-08-03.**
  Singular **−77.2 ±19.6** when removed, improving **−19.6 ±10.5**,
  history-adjusted LMR **+1.1 ±8.7**. The premise above was wrong on both
  counts: the components were not "likely sub-20", and the exercise found no
  passenger to delete — histLMR is inert only because its divisor is
  mis-scaled, not because the technique is worthless.
* ~~**Pool-calibrate v8.1.**~~ **Done 2026-08-03: 3026.7 ±11.1** over 3,456
  games, **+20.9 vs v8.0 same-solve** against +21.2 ±8.7 self-play. No
  compression — the two agree to 0.3 Elo, which is itself the finding: §6's
  compression pattern applies to *behaviour* changes, not speed. Ledger,
  CHANGELOG, README and the website are updated. **3000 is now cleared
  outright** — [3016, 3038] does not touch it, so that milestone is closed too.

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
