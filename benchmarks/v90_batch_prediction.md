# v9.0 tier-1 batch, prediction, registered before the run

Written **2026-08-03**, before a single game was played. Registered per
decision rule 7 of `docs/METHODOLOGY.md`, which was added *because* the singular
prediction two days earlier was badly wrong and would have been easy to
retrofit afterwards.

---

## What is being tested

Ten search changes on the v8.1 net and build, each behind its own compile-time
toggle so a failure can be bisected by halves.

| # | change | tree when disabled |
|---|---|---|
| 1 | `HistLmrDiv` 400,000 → 128 | −8.9% |
| 2 | Internal iterative reduction | **+57.9%** |
| 3 | Eval-scaled null-move reduction | +19.1% |
| 4 | Verified razoring at depth 3-4 | +20.2% |
| 5 | Move-loop futility | +12.5% |
| 6 | SEE pruning in the main search | +22.3% |
| 7 | History pruning | +13.0% |
| 8 | Capture history | +14.8% |
| 9 | Root PVS | +30.9% |
| 10 | Fifty-move eval scaling | inert on bench by design |

Combined, the batch searches a **3.4× smaller tree** at bench 12
(13,614,729 → 3,965,550 nodes).

Baseline is `sgr_v8_1.exe`, the released v8.1 at 3027 ±11. SPRT at 8+0.08,
`elo0=0 elo1=5`, α=β=0.05.

---

## Prediction

**+25 to +60 Elo. Confidence ~75% that it is net positive; ~50% that it lands
inside that band.**

### Why positive

Ten standard techniques the engine simply lacked, at a rating well below where
any of them saturate. Individually the literature puts IIR at +10 to +20, SEE
pruning +10 to +20, move-loop futility +10 to +20, capture history +8 to +15. Local
precedent agrees: RFP + LMP measured +176 self-play, and the v6.0 package
+57.3.

### Why not higher confidence

* **Severe sub-additivity.** RFP, razoring, futility, LMP, SEE pruning and
  history pruning all cut overlapping nodes. Ten items are nowhere near ten
  independent effects.
* **Three parameters are reasoned guesses, not measured.** `HistLmrDiv=128`,
  the history-prune margin, and the capture-history clamp were each chosen on
  a distribution or on structural grounds because sweeps returned noise. No
  games have chosen any of them.
* **Two features behaved erratically under sweep.** Razoring and history
  pruning both went non-monotonic across their parameter ranges.

### The specific worry

**The batch's most visible property is a 3.4× smaller tree, and that is
exactly the profile of the last thing this project got wrong.**

Removing singular extensions shrank the tree 46% and measured **−77 Elo**.
Tree size is not strength; `docs/METHODOLOGY.md` §5 now says so in two places.

The honest counter is that these are *pruning* features, meant to cut nodes
that do not matter, whereas singular is an *extension* whose cost buys
accuracy: adding pruning and removing an extension are not symmetric
operations. But treating the 3.4× as good news would be repeating the same
error in the same week. It is neutral evidence.

---

## Outcome bands, written in advance

| measured | reading |
|---|---|
| **+25 to +60** | prediction holds. Ship as v9.0 |
| **above +60** | better than expected; sub-additivity was milder than feared. Ship, and revisit whether the remaining pruning items are undervalued |
| **+5 to +25** | real but diluted. Ship, then bisect at leisure to find which items are passengers rather than contributors |
| **−5 to +5** | the package cancels out. Bisect by halves: most likely the prunes are over-cutting what the extensions and ordering gain |
| **below −5** | **over-pruning is the first hypothesis.** Split prunes from non-prunes rather than bisecting by commit order. `HistLmrDiv=128` is suspect #1 (a pure guess that *grows* the tree 14%), history pruning #2 (never behaved like a pruner at any setting) |

## Falsification

The prediction is wrong if the measured value falls outside **[+25, +60]**.

A negative result would be the more informative failure: it would mean a 3.4×
tree reduction bought nothing, which is the strongest possible restatement of
the singular lesson and would make "does this shrink the tree?" formally
useless as a design signal in this project.

## Duration

A large effect resolves fastest under SPRT. Expected **20-65 minutes**. Only a
true value sitting on `elo1 = 5` is slow, in which case it runs to the 6,000-game
cap at roughly 5 hours.
