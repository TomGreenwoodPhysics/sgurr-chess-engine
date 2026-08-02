# v6.0 decomposition — predictions, registered before the run

Written **2026-08-02**, before a single game was played, against binaries
built from commit `ce303c9`. Committed ahead of the result so the reasoning
below cannot be quietly reshaped to fit whatever comes back.

`METHODOLOGY.md` is largely a record of conclusions that had to be withdrawn.
The cheapest defence against adding another is to say in advance what is
expected and what would count as being wrong.

---

## What is being tested

The v6.0 package — improving flag + history-adjusted LMR + singular extensions
— shipped as one SPRT, **+57.3 ±17.3 vs v5.0**, undecomposed. Which component
earned it has been open since 2026-07-16.

Node counts (bench 13, verified independently twice):

| build | nodes | vs baseline |
|---|---|---|
| baseline | 13,614,729 | — |
| `-DSGR_IMPROVING=0` | 17,373,703 | **+27.6%** |
| `-DSGR_HISTLMR=0` | 13,796,251 | **+1.3%** |
| `-DSGR_SINGULAR=0` | 7,351,781 | **−46.0%** |

---

## Job 1 — removing singular extensions

**Prediction: positive, +5 to +25 Elo. Confidence ~60%.**

Singular costs **+85% of the tree**, which at a fixed time control is paid out
of the clock. At an effective branching factor around 1.85, a 0.54× node count
is roughly **one extra ply** for the build without it — about **60 Elo of free
depth** at the project's ~70 Elo/doubling rule. Singular has to beat that to be
worth keeping.

Three settings suggest this implementation over-fires:

* `SINGULAR_MARGIN` = 2 cp/ply → a 26 cp window at depth 13, so "singular" is
  declared often
* `SINGULAR_TT_DEPTH_SLACK` = 3 → permissive gate
* `SINGULAR_MIN_DEPTH` = 7 → active across most of the tree at blitz depths

For scale, Stockfish's singular runs nearer +20–30% tree cost *with* double
extensions, negative extensions and a multicut return — none of which exist
here. +85% is anomalous for an unrefined implementation.

**Why only 60%.** Node counts systematically understate singular: it pays off
in forcing tactical lines, which is where blitz games are decided, and tree
size cannot see that.

**Time-to-decision is itself a signal**, since `elo0=0` makes H0 faster to
accept than H1:

| finish | games | reading |
|---|---|---|
| < 45 min | ~400–900 | H0 fast → singular is clearly good, prediction wrong |
| 45 min – 2 h | ~800–2,500 | H1 → prediction holds |
| 1.5–2.5 h | ~2,000–3,000 | H0 near zero → cost and benefit cancel |
| hits the cap | 6,000 | effect sits at ~+5, genuinely marginal |

**Falsified by:** anything below −5. A result worse than −20 would mean
singular is worth more than a full ply and is *underpriced*, not expensive.

---

## Job 2 — removing the improving flag

**Prediction: clearly negative, −15 to −40 Elo. Confidence ~75%.**

Removing it inflates the tree **+27.6%** and changes 18 of 19 bench scores. It
is doing real pruning work, and it feeds two other mechanisms: RFP's margin
(one ply smaller when improving) and LMP's quiet budget (halved when not).

Expected to resolve fast, ~400–800 games, since H0 accepts quickly.

**Falsified by:** anything above −5.

---

## Job 3 — removing history-adjusted LMR

**Prediction: ≈ 0. CI brackets zero, |measured| < 8. Confidence ~85%.**

This one is near-certain because the mechanism is understood, and it is not
what the leave-one-out implied.

**History-adjusted LMR has been effectively inert since v6.0.** History earns
`depth * depth` per cutoff (169 at depth 13) and is halved every move, so
`hist_score / 400'000` rounds to zero almost always. Setting `HistLmrMax = 0`,
which disables the adjustment outright, changes the bench tree *not at all*.
The only live part of the block is the reduction re-clamp, which is nearly
redundant anyway — that is the whole 1.3%.

With the divisor somewhere it functions:

| `HistLmrDiv` | nodes | |
|---|---|---|
| 1,000 | 18,728,103 | +37.6% |
| 5,000 | 12,239,286 | −10.1% |
| 400,000 (shipped) | 13,614,729 | inert |

**How to read a null result.** ≈0 means *"histLMR at HistLmrDiv=400,000 is
worth nothing"* — **not** *"the technique is worthless"*. Deleting the code on
this result would be the wrong inference. The right one is that it is an
untuned parameter and an SPSA target.

**Falsified by:** |result| > 15.

---

## The composite claim

**The v6.0 package's +57.3 was mostly the improving flag, with singular around
break-even-to-negative and history-adjusted LMR contributing nothing.**

If Job 1 returns strongly negative, that story collapses and singular was
carrying the package after all.

## Summary

| arm | prediction | confidence | falsified by |
|---|---|---|---|
| singular removal | **+5 to +25** | 60% | < −5 |
| improving removal | **−15 to −40** | 75% | > −5 |
| histLMR removal | **0 ± 8** | 85% | \|result\| > 15 |

Total runtime estimate: **~6.5–8 h**, Job 1 most likely inside 2 h.
