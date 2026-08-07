# Engineering log

Dated record of findings, bugs, and methodology decisions. Measured results
live in `benchmarks/ledger.md`; releases in `CHANGELOG.md`; dataset provenance
in `data/*/manifest.json`. This file is the story of *why* things are the way
they are. Append-only, newest entry last.

---

## 2026-07-01 — Toolchain: ucrt64 g++ 16.1.0 miscompiles `std::fstream`

Symptom: every optimised build segfaulted before `main`'s first output.
Bisection: crashes at `-O1+`, fine at `-O0`; per-translation-unit bisection
pinned it to `nnue.cpp`; a 5-line repro proved bare `std::ifstream`
construction at `-O2` crashes with this compiler. `std::string`/`vector`/
C `fopen` were unaffected — narrowly a libstdc++ fstream/locale issue in the
MSYS2 ucrt64 gcc 16.1.0 dev build. Fix: switched to MSYS2 **clang64**
(`clang++`, libc++, `-static`). Rule: never build with the ucrt64 gcc
(documented in `sgurr_cpp/BUILD.md`).

Consequence: the earlier "NNUE is ~100 Elo below classical" result was
measured on a compromised (likely `-O0`) build and was not a property of the
net at all.

## 2026-07-01 — Incremental NNUE accumulator: 63% → 104% of classical NPS

The original NNUE recomputed both perspective accumulators from scratch every
node. Implemented make/unmake deltas (`nnue.cpp`: `refresh`/`on_make`/
`on_unmake`/`note_hash`), self-checking by Zobrist tag with automatic refresh
on any desync. Verified bit-identical to full refresh across castling/EP/
promotions plus 2,000 random game chains (`nnue_selfcheck.cpp`, 4,468 checks,
0 mismatches; node counts identical, so the search tree is provably
unchanged). Re-benched: NNUE search went from ~63% of classical NPS to ~104%.

Re-SPRT (300 games, 8+0.08): gen1 NNUE vs classical = **+9.3 ±36.3** — parity.
The "-100 Elo" was entirely build/speed artefacts. Bootstrap gate cleared.

## 2026-07-01 — Resumable data generator

Rewrote datagen as stop/resume-friendly: auto-numbered tagged shards (safe for
parallel processes), Ctrl+C-clean on game boundaries, shared on-disk position
target, optional NNUE labeller, node-budgeted labels (hardware-independent).
Audited gen1's dataset while at it: 97% unique positions — the old data was
fine; its problem had been the build, never the data.

## 2026-07-01 → 07-03 — gen2 data: 14.5M positions

Labelled by the gen1 net at nodes:50000 (vs gen1's depth-8 HCE labels), 150-
line balanced book + light randomisation. Generated across 5 stop/resume
sessions on 6 processes.

## 2026-07-03 — The validation-leakage saga (biggest methodology lesson)

A "checkpoint" training at 14.5M scored *worse* than at 5.6M — more data
apparently hurting. Chased through: shard audits (clean), torn-tail checks
(clean), duplicate analysis (clean), a 5x5 batch-transfer matrix. The matrix
showed every batch "special" only to itself — no domain structure — which has
exactly one explanation: **train/val leakage through shared games**. Datagen
writes each game's ~50-130 positions consecutively; a random position-level
split puts same-game siblings of nearly every validation position into
training, so "validation" partly measured memorisation. Small datasets
memorise more → looked artificially better; the illusion deflated as data
grew.

Corrected protocol: hold out **whole shards** (each shard is one process's
games — game-disjoint by construction). Under the clean protocol:

- True scaling for the 256-wide net **saturates at ~3M positions**
  (the leaky curve's "7% per doubling forever" was memorisation).
- The apparent +5.7% for HL=512 **inverted** to −6.4%: the wider net's "win"
  was memorisation capacity, not chess.

`train.py` now holds out contiguous blocks (~whole games) permanently.
Standing rule: loss comparisons require identical, game-disjoint validation;
games (SPRT) are the only ground truth.

## 2026-07-03 — gen2 result: +77.7 ±37.4 vs gen1

Deploy net trained on all 14.5M (val_frac 0). SPRT vs gen1 (300 games,
8+0.08): **+162 =42 −96, +77.7 ±37.4**. The entire gain came from label
quality (deeper search + NNUE labeller) at fixed architecture — measured
val loss had plateaued, proving loss and Elo are different currencies.

## 2026-07-03 — Rename (Ruk → Sgurr) and dataset versioning

Engine renamed Bitfish → Ruk → **Sgurr** (binary `sgr`, UCI id "Sgurr");
release codenames = Sgùrr peaks by ascending height (v1.0 "Fox",
v2.0 "Notches"). Datasets versioned as append-only archives with manifests:
`data/v1.0` (16.7M — recovered after being believed deleted; the event that
motivated the versioning discipline) and `data/v2.0` (14.5M). Round-trip
sha256 verification before originals were removed.

## 2026-07-04 — Benchmark stack: first honest absolute ratings

Replaced the Elo-limited-Stockfish estimate (saturating, uncalibrated) with a
7-engine CCRL-anchored pool (Blunder 6.1–8.0, Zahak 4.0/5.0; CCRL Blitz
2155–2763) via fastchess + Ordo multi-anchor. 720-game calibration:

| engine | rating |
|---|---|
| Sgurr v2.0 | **2489 ±34** |
| Sgurr v1.0 | 2407 ±35 |
| Sgurr classical | 2398 ±34 |

Version gaps (+82, +9) reproduce the direct SPRTs → self-play gains were not
inflated. The old "~2520" classical estimate is retired (flawed method,
different scale). Pool finished in exact CCRL order, validating the anchors.
Results ledger (`benchmarks/ledger.md`) is append-only from here on.
Engine fix along the way: bare launch now defaults to UCI (tournament tools
don't pass arguments); test mode moved behind `sgr test`.

## 2026-07-04 — gen3 recipe: diversity + opening balance filter

gen3 = flywheel step: labelled by gen2 at nodes:150000 (label quality over
volume — the 256-net saturates ~3M). Data-quality upgrade: 4-9 random plies
per opening (up from 1-4) made *possible* by a new eval-based balance filter
(reject openings beyond ±200cp at a 5000-node probe, ~48% rejected). Result:
maximum opening diversity AND competitive games (draw rate restored to ~14%,
phases well covered, 99.4% unique positions in production data).

## 2026-07-04 — Single-command pipeline (`pipeline.py`)

datagen → probe → freeze → train → build → select → sprt → calibrate →
ledger, resumable via per-stage state. Includes a **data-sufficiency probe**
(half-vs-full training on game-disjoint validation) that extends the
generation target empirically instead of trusting a configured number, with a
tri-state verdict whose third state ("anomalous": full trained *worse* than
half — physically implausible for healthy data) exists specifically so noisy
measurements can never masquerade as "saturated". Foolproofing: game stages
refuse to run while datagen is alive (timed games under load are silently
invalid), every built net must pass the bit-exact selfcheck before games,
divergence gates, idempotent ledger, atomic state, instance lock.

## 2026-07-04 — datagen bug: engine state leaked across unrelated searches

The probe stage immediately earned its keep: reproducible "anomalous"
verdicts on early gen3 data (full 3-6% worse than half). A 2x2 cross-domain
matrix (gen2-trained vs gen3-trained nets, each scored on both generations'
held-out shards — gen2's extracted from the v2.0 archive) showed the
gen2-trained net beating the gen3-trained net **on gen3's own positions**:
the signature of systematically noisy labels, not benign difficulty.

Root cause: datagen's single long-lived `Engine` reset killer moves per
search but **never the history heuristic**, so move-ordering state accumulated
across unrelated positions — most damagingly from the ~48% of shallow opening
probes the balance filter rejects, polluting the next game's node-budgeted
searches (worse ordering = less effective depth = noisier labels). Introduced
alongside the balance filter; gen1/gen2 had only the milder cross-game
variant. Fix: full `clear_for_new_game()` (history + TT) before every attempt,
making each game's labels independent of process history (commit 88d9498).

The 2.9M pre-fix positions were quarantined (kept) in
`data/gen3_raw_prefix_history_bug/`; clean generation restarted. The
quarantined set doubles as the "before" sample for confirming the diagnosis
against post-fix data.

Lesson: any long-lived search object reused across independent positions
needs an explicit full state reset between them — and label-quality bugs are
invisible in per-record validation; only distribution-level experiments
(transfer matrices, scaling probes) catch them.

## 2026-07-04 — Elo outlook (evidence-based)

Measured trajectory: 2398 → 2407 → 2489, all CCRL-anchored. Near-term
realistic ceiling **2600-2700** (search improvements + one architecture bump +
continued flywheel); stretch **2750-2850** (scaled net + SMP + tuning hours);
3000+ is out of scope at this project size. Top-ranked next levers:
continuation history + malus (best Elo/effort), then architecture
(king-relative features / properly-trained wider net — now priority per the
capacity evidence), with Lazy SMP as the biggest but riskiest single item.

## 2026-07-05 — Datagen fix confirmed; which diagnostic to trust

At 610k clean post-fix positions, re-ran both diagnostics (datagen left
running — these are loss comparisons, not timed games; only shard snapshots
need byte-exact care):

- **Within-gen3 half-vs-full** (426k pool, whole-shard game-disjoint val):
  full trained **10.8% better** than half. Pre-fix the same probe had full
  3-6% *worse*. Verdict flipped from anomalous to healthy → the
  `clear_for_new_game()` fix worked; generation continues to 3M.
- **Cross-domain 2x2 matrix**: the gen2-trained net *still* wins on gen3-val
  (0.02073 vs 0.02315). With the within-gen probe now healthy, this residual
  inversion is explained by a confound, not a bug: gen3's labeller (gen2-net
  at nodes:150000) differs from gen2's (gen1-net at nodes:50000), and sharper
  labels are higher-variance targets — harder to fit, so the net trained on
  smoother gen2 labels can win on *loss* without being better at chess.

Methodology correction: the cross-domain matrix detects "distributions
differ", not "data broken" — it was over-credited in the 07-04 diagnosis
(the probe's anomalous verdict was the trustworthy signal all along).
Standing rule: **within-generation scaling (same labeller) is the
data-health diagnostic; loss is not comparable across labellers; games
(SPRT) remain ground truth.**

## 2026-07-06 — The probe was measuring the optimiser, not the data

At 3M the sufficiency probe went anomalous AGAIN (full +5.6% worse than
half), and seed replicates agreed to 0.1% — real, not noise. Yet every audit
came back clean: session-2 shards statistically identical to session-1
(distributions, generation rates), no RNG replay (random_device-seeded),
duplicates *lower* than healthy gen2 at the same scale (0.95% vs 1.34%, same
label spread). The data looked innocent because it was.

A 2x2 step-matched control found the real culprit: **fixed-epoch training
gives bigger datasets proportionally more optimiser steps, and constant
LR 1e-3 with the per-step WCLIP clamp degrades the net ~9% per step-doubling
past ~2k steps.** At *matched* steps, more data won every single comparison.
Every fixed-epoch constant-LR cross-size comparison ever run was confounded
— including the pre-fix "anomalous" verdicts, the gen2-era "saturates ~3M"
point, and the "HL=512 is worse" result (all now suspect, to be redone under
the corrected protocol before being believed).

Two consequences, tested the same night:

- **Cosine decay (1e-3 → 1e-5) is free strength:** identical data and
  epochs, 5-8% lower val loss across the board. Best recipe found for the
  gen3 deploy net: all data, cosine, ~12 epochs (~2k steps total) →
  val 0.01935 vs 0.02068 for the old protocol's best. `train.py` now has
  `--schedule cosine --lr_min 1e-5`.
- **Quarantine retrial — GUILTY confirmed:** the original conviction rested
  on the broken probe, so it was re-tried cleanly (matched n=1.07M, matched
  steps, cosine, both nets scored on both vals). The clean-trained net beat
  the quarantine-trained net *on the quarantine's own val* (0.01924 vs
  0.02055, ~60x seed noise) — the history-leak bug genuinely damaged labels.
  Right verdict originally, wrong evidence; now both are right.

Standing rules: **cross-size loss comparisons only at matched optimiser
steps; deploy training uses cosine decay with a step budget (~2k steps for
HL=256), not a fixed epoch count.** gen3 is unblocked: 3M positions healthy,
still mildly data-limited at 2.5M (more data keeps helping at matched
steps), freeze and train.

## 2026-07-06 — v3.0 "Blackpeak": +119.8 ±26.3, 2616 CCRL-anchored

The whole release cycle ran in one evening (manually, as a dry run of the
pipeline stages). Frozen `data/v3.0` (3,016,181 positions, manifest +
round-trip sha256). Trained the lambda sweep {0.6, 0.7, 0.8, 1.0} under the
corrected recipe (cosine 1e-3→1e-5, 12 epochs ≈ 2.2k steps); all four built,
selfcheck PASS.

**Selection (600-game round-robin): lambda=1.0 won decisively** (+117 ±41 vs
the field; monotonic in lambda, 0.6 collapsed at −140). With a strong
labeller at nodes:150000, pure search-score targets beat every WDL blend —
the game-result term that helped when labels were shallow now only dilutes
them. gen2 finished 4th, behind three of the four gen3 variants.

**SPRT vs v2.0: H1 accepted — +119.8 ±26.3** (+357 =109 −152, 618 games,
8+0.08). Largest generational gain yet (gen2's was +77.7), at fixed
architecture, from a *smaller* dataset than gen2's (3M vs 14.5M): label
quality and training protocol, not volume.

**Calibration: 2616 ±37** (210-game gauntlet, Ordo re-solved over all 930
accumulated calibration games; earlier versions moved ≤2.4 points).
Trajectory: 2400 → 2408 → 2491 → 2616. The pool gap (+125) reproduces the
SPRT independently. v3.0 now sits above Zahak-4.0 (2601) — inside the
2600-2700 near-term window predicted on 07-04, one generation in. White
advantage again negative (−20 ±9); book side-to-move question still open.

Attribution of the +120: three compounding fixes — clean labels (deeper
searches by a stronger labeller, post history-leak fix), lambda=1.0 targets
(+~90 of it, per the round-robin gap to lambda=0.7 which matches the old
recipe), and the cosine schedule. The flywheel plus honest measurement is
the story of this release.

## 2026-07-06 — Architecture width re-test: "HL=512 is worse" was the artefact

With the protocol confound understood, re-ran HL=256 vs 384 vs 512 the fair
way: matched optimiser budgets (1900 and 3800 steps, cosine to 1e-5),
identical 2.5M-pool / game-disjoint val, lambda=1.0. On v3.0 data:

| budget | HL=256 | HL=384 | HL=512 |
|---|---|---|---|
| 1900 steps | 0.00558 | 0.00541 (−3.0%) | 0.00537 (−3.8%) |
| 3800 steps | 0.00522 | 0.00518 (−0.8%) | 0.00520 (−0.4%) |

The gen2-era "HL=512 is 6.4% worse under clean eval" is **retired** — it was
the fixed-epoch constant-LR artefact, not a property of the net. Under the
corrected protocol wider is at worst neutral, modestly better at the standard
budget.

But the effect is small and mostly *faster convergence, not a lower floor*:
double the steps and 256 nearly closes the gap, and 512 stops beating 384.
On 2.5M positions the extra capacity is only mildly exploited (wider nets are
data-hungry — gen4's 6M is the better testbed). **384 is the pick over 512**
(wins at 3800 steps, cheaper NPS).

Not a green light yet, for the two reasons this project keeps relearning:
(1) **loss ≠ Elo** — a 3% val-loss edge could be +30 Elo or ~0; (2) a wider
net **costs NPS**, giving Elo back in search depth. Verdict: wider-net is a
justified *gen5* experiment targeting HL=384, gated on a real SPRT of an
HL=384 engine vs the HL=256 engine (needs the C++ HL constant parameterised
and the accumulator re-verified), ideally trained on the 6M gen4 data.

## 2026-07-07 — gen4 (HL=256): the label flywheel is tapped out

gen4 = 6.0M positions, labelled by the gen3 net at nodes:150000 (same node
budget as gen3, stronger labeller), lambda sweep {0.9, 1.0}, cosine 6 epochs
(~2.2k steps — step-matched to gen3's deploy net). Ran the full pipeline
autonomously.

- **Probe: saturated** (+0.56% half→full at matched steps). A clean,
  protocol-correct confirmation that the 256-net is essentially saturated by
  ~3–6M — the retired gen2-era "~3M" number, re-measured properly, lands in a
  similar place. So generating 6M was for the *gen5 384 experiment*, not for
  gen4's own 256 net.
- **Select round-robin: lambda=0.9 "won"** (+11.6 vs gen3 +5.8 vs gen4-l100
  −17.4) — but only ~60 games/pairing, i.e. within noise. Note the apparent
  optimum moved 1.0 (gen3) → 0.9 (gen4); underpowered, but a reminder the
  lambda optimum is not a constant.
- **SPRT vs gen3 (stopped early at 750 games): +270 =148 −332, 45.9%,
  −28.8 ±22.3 — a genuine REGRESSION.** The select round-robin's slight
  positive was small-sample noise; with 750 games gen4 is clearly *behind*
  gen3.

Interpretation: both gen3 and gen4 probes say the 256-net is saturated, and
gen3→gen4 (better labeller, more data) delivered *nothing* — slightly
negative. **The label-quality flywheel has run out of road at HL=256.** The
net is full; better labels can't be expressed, and recipe/lambda differences
nudge it negative. (Secondary possibility not yet excluded: gen4's labels are
genuinely a touch worse than gen3's — −29 is a bit more than a pure ceiling
would predict. Optional diagnostic: retrain on gen3 data with gen4's exact
recipe, SPRT vs gen4; equal ⇒ ceiling, gen3-data wins ⇒ label regression.)

Decisions:
- **v4.0 is NOT released** — not stronger than gen3. No version bump, no
  ledger row (calibration skipped — pointless for a regression). All
  artefacts kept per the nothing-deleted rule: `data/v4.0` (frozen, 6.0M),
  `nets/gen4*.nnue`, `sgr_gen4*.exe`. Pipeline stopped mid-SPRT on purpose.
- **The next Elo must come from architecture or search, not labels.**
  gen4 is the empirical proof. Critical path is now the **HL=384** experiment
  (C++ HL parameterisation + accumulator re-verify + train on the 6M gen4
  data + SPRT vs the 256 net), with the untouched **search track**
  (continuation history + malus, LMP, RFP) as the parallel lever. Another
  256 generation is off the table.

## 2026-07-08 — Search track opens: soft time limit + move overhead

Connected the engine to Lichess and audited the clock code, which was
**hard-limit only**: `parse_go_movetime` computed a single budget
(`time_left/30 + inc/2`, capped at half the clock) and the iterative-deepening
loop always started the next depth, stopping only when the in-search deadline
aborted it mid-pass. Because each depth costs roughly 2–3x the cumulative time
before it, the final (aborted) iteration is pure waste — its result is
discarded and the previous depth's move is returned regardless. Modelled over
a geometric iteration cost that is ~1 − ln(r)/(r−1) of the budget lost per
move: ~30% at r=2, ~39% at r=2.5.

Changes (search/time only; net untouched):
- **Soft limit** (`SOFT_TIME_FRACTION = 0.6`): checked at the top of the ID
  loop — do not *start* a new iteration once past this fraction of the hard
  budget, so the last pass completes instead of being thrown away. The banked
  time raises `time_left/mtg` on later moves, so the reclaimed effort is spent
  as extra depth where it counts. Depth 1 always runs so a searched move
  always exists.
- **Move overhead** (`MOVE_OVERHEAD_MS = 30`): held back before allocating so
  the move is transmitted before the flag falls — chiefly Lichess-latency
  insurance; ~0 Elo in local SPRT.
- Explicit `go movetime` and node limits get **no** soft limit, so datagen and
  fixed-time analysis stay bit-identical to before.

Verified: clean clang64 build; a UCI smoke test shows the clock path stopping
at an iteration boundary (~198 ms, depth 9 complete) instead of burning to the
hard cap (~305 ms) and returning the same move, while `go movetime 1000` still
uses the full second.

Evidence (interim, **not** a completed test): SPRT vs gen3 at 8+0.08, same
gen3 net on both sides so only the time code differs, stopped early by choice
at 706 games: +300 =156 −250, **+24.6 ±22.7**, LLR +0.84 (bounds ±2.94 for
elo0=0/elo1=5). A small effect against a [0,5]-Elo band needs ~2000+ games to
cross a bound; the point estimate stayed stable and positive across the run
but its CI still reaches down near zero. Encouraging, not confirmed.

Decision: **no version bump, no ledger row, no CHANGELOG entry** — gated on a
proper pool calibration (to be run). This is the first result off the search
track flagged on 07-07 as the way forward now the label flywheel is tapped out
at HL=256; if the pool confirms it, it becomes the search half of the next
release. Follow-ups once confirmed: sweep `SOFT_TIME_FRACTION` (0.5/0.6/0.7)
and expose `Move Overhead` as a real UCI option for lichess-bot.

**Update (same day) — shipped as v3.1 "Blackpeak".** Overriding the "no version
bump" line above: at the maintainer's call it is released now because it is
wanted in play, as a **search-only point release on the unchanged gen3 net**
(hence still "Blackpeak" — same peak, same generation, no new NNUE). The
release deliberately breaks the usual measured-ledger discipline for this one
version: it ships on the interim SPRT (+24.6 ±22.7, stopped early, no bound
crossed) with **no pool calibration** — CHANGELOG/README/ledger all flag the
figure as provisional, and a full gauntlet + a completed SPRT are deferred to
before the next generation. Engine self-reports `id name Sgurr 3.1`; deploy
binary `sgurr_cpp/sgr_v3_1.exe` (gen3 net via `SGR_EVALFILE`).

## 2026-07-10 — gen5: HL=384 is the first architecture win (+55.5 ±17.0)

The width experiment flagged on 07-06 as the critical path ran overnight and
delivered. Trainer side: `train.py` gained `--hl` (one override sets both the
model width and `nnue_tools.HL`, so the exported header always matches the
weights). Trained on the frozen 6.0M `data/v4.0` positions — generated for
exactly this experiment, no new datagen — with the corrected recipe (cosine
1e-3→1e-5, 10 epochs ≈ 3.7k steps, the budget at which the 07-06 re-test had
384 winning; lambda 1.0). ~5 minutes on the GPU. Engine side: `nnue::HL`
became a `-DSGR_HL` build define; `nnue.cpp` was already width-clean (the
literal 384 in `feature_index` is INPUT/2, the colour stride — unrelated).
`nnue_selfcheck` rebuilt at 384 against the new net: **PASS, 4,468 checks, 0
mismatches** — the incremental accumulator is provably bit-exact at the new
width, so games can be trusted.

**SPRT vs the gen3/256 engine: H1 accepted at 1,194 games — +580 =223 −391,
+55.5 ±17.0** (8+0.08, [0,5] band, LLR crossed +2.94). The point estimate sat
at +47…+55 the whole run. The punchline writes itself: the same 6M positions
that gave the saturated 256 net *minus* 29 Elo (gen4) gave the 384 net +55.
Capacity, not label quality, was the wall — the gen4 post-mortem's conclusion,
now proved from both sides. The label flywheel is dead at 256 but the
architecture lever is alive, and wider nets really are data-hungry.

## 2026-07-10 — Calibration day: v3.1's debt paid, and a soft-limit surprise

The v3.1 calibration owed since 07-08 ran first: **2565.8 ±25.9** (420 games
@ 10+0.1), and ~2564 in every later combined re-solve. That is ~50 points
**below** v3.0's 2616 on the same scale — despite the +24.6 ±22.7 interim
head-to-head at 8+0.08 that v3.1 shipped on. The finding reproduced across
independent Ordo solves as more games accumulated, so it is believed: **the
flat soft limit loses Elo at 10+0.1 even though it measured positive at
8+0.08.** Lesson (the time-management cousin of loss≠Elo): mechanism ≠ Elo,
and a time-management result at one TC does not transfer to another — test at
the TC you care about.

The gen5 nets were then calibrated as a two-seed gauntlet (both
time-management variants, 900 games @ 10+0.1, ~480 games/seed):
**gen5-bmstab 2635.7 ±24.9, gen5-soft 2618.7 ±23.3**. Cross-checks all landed:
gen5-soft − v3.1 = +54, reproducing the +55.5 SPRT at a different TC (the
anchoring is consistent session to session); best-move stability — a
same-day addition that scales the soft budget by how long the root move has
held (`BM_STABILITY_FACTOR`, stretch while unsettled, trim once stable,
clamped to the hard deadline) — measured +17 here and +6/+23 (gen5/gen3) in a
1,436-game 8+0.08 round-robin. Positive at both TCs, never negative; and it
is exactly the mechanism that un-does the flat limit's damage (stretch when
stopping early would be wrong). **Champion call: gen5 + stability**, on the
pragmatic rule that the nominal #1 which is at-worst-equal gets taken.

## 2026-07-10 — History 2x2: malus is worth +33, continuation history ±0

Two move-ordering upgrades, tested factorially the same evening on the new
champion: **history malus** (on a quiet beta cutoff, the quiets already tried
get −depth², floored at −HISTORY_MAX — the mirror of the existing +depth²
bonus; the previously-unsorted zero-history bucket became a scored, sorted
bucket so negative scores actually demote) and **continuation history**
(a [prev_piece][prev_to][piece][to] follow-up table added into quiet
ordering, per-ply previous-move stack, cleared across null moves, fully reset
by `clear_for_new_game()` per the 07-04 datagen rule). Both behind build
toggles (`-DSGR_HMALUS`, `-DSGR_CONTHIST`, default on) so all four
combinations build from one tree.

Methodology note that earned its keep: the toggles-off build was verified
**node-for-node identical** to the champion binary (two positions, exact node
counts) before any games — the baseline provably is the champion, so any gap
is attributable to the toggles alone. Fixed-depth node counts then showed the
ordering effect directly: −39% nodes to depth 9 (malus), −22% (conthist).

Round-robin (8+0.08, stopped at 2,158 games / 1,020 per engine):
mch +19.4, malus +14.0, base −14.3, ch −19.1 (all ±18). Factorial
decomposition: **malus main effect ≈ +33** (the two malus arms separate
cleanly from the two non-malus arms; pooled split SE ≈ ±9), **continuation
history ≈ 0** (−4.8 alone, +5.5 with malus — noise). Interpretation: a
bonus-only butterfly table accumulates stale flattery that malus corrects,
while 1-ply continuation history has nothing to feed at Sgurr's current
search — its value elsewhere comes through history-informed LMR/LMP, which
do not exist here yet. The plumbing stays (default-on, ~free, and those
consumers are next on the search list). Champion: base + malus + conthist.

## 2026-07-10 — v4.0 "MacKenzie" (Sgùrr MhicChoinnich): released

One day, three measured gains, one release: the gen5 NNUE (768→384→1, the
first architecture change since NNUE arrived), best-move-stability time
management, and history malus. Deploy binary `sgurr_cpp/sgr_v4_0.exe`
(canonical `nets/gen5.nnue` baked), verified node-identical to the pooled
champion and selfcheck-PASS. Source defaults now describe the shipped engine:
`SGR_HL` 384 in both engine and trainer (256-net builds need `-DSGR_HL=256`),
search toggles (`SGR_BMSTAB`/`SGR_HMALUS`/`SGR_CONTHIST`) default-on.

**Release calibration: Sgurr-v4.0 = 2627 ±27** (+216 =60 −144, 420-game
gauntlet @ 10+0.1, 58.6%; Ordo over all ~3,600 accumulated calibration
games). Ladder: 2399 → 2408 → 2490 → 2613 → **2627** (v3.0 drifted 2616 →
2613 in the combined re-solve, inside its bars). On the pool scale the
one-day v3.1 → v4.0 jump is **+63**.

Honest footnote: 2627 is statistically level with the same engine measured
*without* the history changes (gen5-bmstab, 2635.5 ±25.5) — the self-play
+33 from malus did not express against the pool (difference −8.5 with ~±37
joint error). Self-play gains compressing against a diverse pool is the
expected direction, and the factorial malus result stands as a self-play
measurement; but the pool-scale claim for v4.0 is +63 over v3.1, not the
+105 the isolated measurements would sum to. loss ≠ Elo, self-play Elo ≠
pool Elo — same lesson, next scale up. Also noted: the white-advantage
anomaly (−23 ±10 on 07-04, −20 ±9 on 07-06) has washed out to −2.3 ±5.3
over the full 3,600-game set — it was small-sample noise, and the book
side-to-move question can close.

Next levers, in order: LMP/RFP (which may activate conthist), then gen6
datagen labelled by this ~+60-stronger engine — the flywheel is alive again
at 384.

## 2026-07-10 → 07-11 — Post-release verification and the search seam

**Time management is a wash on gen5 (07-10).** The question was whether v4.0
still carried v3.1's regressive flat soft limit. A three-way on the *release
engine* at 10+0.1 — stability (shipped) vs flat 0.6 vs hard-only
(`SGR_SOFT_TIME_FRACTION=1.0`), all node-identical at fixed depth, so only the
clock policy differs — settled it: at 457 games stab+hard led and flat trailed
−26; at 963 games the ranking had *reversed* (flat +9, hard −1, stab −8), the
whole spread inside ±23. A ranking that flips between checks is noise, not
signal: the three policies are statistically equal on gen5. So **v3.1's −48 at
10+0.1 did not reproduce** in a clean same-net direct test — it was a
cross-session gauntlet artefact (v3.1's 420-game gauntlet vs v3.0's 210-game
one from another day; the "three solves" reused the same games, not
independent replication). No time-management Elo was left on the table, and
the shipped stability config is fine. Stopped at 963 games. Added
`-DSGR_SOFT_TIME_FRACTION` as a build override along the way.

**LMP + RFP: reverse futility is a monster (07-11).** A 2x2 factorial on the
v4.0 baseline (base / LMP / RFP / both; toggles `SGR_LMP`, `SGR_RFP`, gen5 net
baked, base verified node-identical to `sgr_v4_0`), 8+0.08, full 3,600 games:
**both +96.0, RFP +79.1, base −80.4, LMP −94.7 (all ±15).** Factorial
decomposition: **RFP ≈ +175 self-play Elo** — both RFP arms tower over both
non-RFP arms with ~11σ of separation, the largest single search gain the
project has measured; reverse futility (stand pat when the static eval beats
beta by a per-ply margin at shallow depth) was simply missing. **LMP ≈ 0**
(−14 alone, +17 with RFP — noise), the passenger again, kept default-on for
the pruning interactions it may yet feed. Fixed-depth node counts confirmed
the mechanism before any game: LMP −63%, both −67%. As always self-play Elo
overstates pool Elo, but +96 is far too large to vanish, and for a *labeller*
self-play depth-per-node is exactly the currency that matters.

## 2026-07-11 — gen6 datagen launched (flywheel restarts at HL=384)

The label flywheel, dead at 256, restarts on the wider net with a much
stronger labeller. gen6 datagen kicked off toward **8.0M positions**
(`data/gen6_raw`, dataset v5.0 "Gillean") labelled by **`nets/gen5.nnue`** at
**nodes:150000** — the node budget held *identical* to gen3/gen4 on purpose,
so the generation-over-generation comparison stays controlled at one variable
(labeller strength). The labeller upgrade is itself a large free depth
increase: the labelling engine is now the full v4.0 + RFP build (net +55,
malus ordering, RFP pruning — together ~1.5–2 plies deeper per 150k nodes than
gen4's gen3-labeller), so keeping 150k already delivers the biggest
label-quality jump of any generation at zero throughput cost. Volume is left
to the pipeline's data-sufficiency probe (384 has never been probed — gen4's
"saturated ~3–6M" was the 256 net), which auto-extends 8M→12M if
data-limited. gen4's 6M is deliberately *not* mixed in (gen3-labelled = weaker
targets; the lambda=1.0 lesson says don't dilute). Config `configs/pipeline_gen6.json`,
detached via `resume_gen6.bat` / paused by `stop_gen6.bat` (append-only shards,
fully resumable). ~2.5–3 days to 8M on ~6 cores, then the pipeline runs
probe→freeze→train→build→select→sprt→calibrate on its own. Note for the SPRT
stage (days out): `sgr_gen5.exe` is a stale pre-RFP build — rebuild the gen5
comparison engine from current source before gen6-vs-gen5 so the net is the
only variable.

## 2026-07-15 — the anchor audit: pool-2026-07-A was ~31 Elo optimistic

Sourcing higher anchors for the v5.0 calibration (the projected release sat at
the old pool's ceiling) forced a check of `anchors.txt` against the live CCRL
Blitz list — and every anchor was high: Blunder-6.1.0 −50, Zahak-4.0 −50,
Zahak-5.0 −37, Blunder-8.0.0 −23, the rest −12..−13. The values had been taken
from each engine's README rather than the list. Worse, **Blunder-7.2.0 has no
CCRL Blitz rating at any version** — one of seven "CCRL-anchored" anchors
never was. **pool-2026-07-B** re-sources every value (2026-07-15), adds two
families above the ceiling (Weiss 1.0 @2896, Igel 2.2.2 @2982, Weiss 1.2
@3055, all UCI-verified pext/popcnt builds), drops Blunder-6.1.0 from the
roster (93% score = no signal) while keeping it pinned in `anchors.txt` to
bracket the historical rows, and floats Blunder-7.2.0 as a free node.
Validation came out clean twice: historical Sgurr rows shifted uniformly
−21..−26 (a scale translation, nothing structural), and the floating
Blunder-7.2.0 solved to 2430.6 ±31 against its README 2425. Mixing fresh and
stale anchors would have been worse than either alone (Ordo pins all anchors
and fits a compromise), hence the full re-source. Rule: anchor values come
from the live list, dated, never from READMEs.

## 2026-07-15 — gen6 is a wash: RFP poisons fixed-node labels

The 07-11 entry predicted the v4.0+RFP labeller would deliver "the biggest
label-quality jump of any generation". It delivered nothing, and the reason
is instructive. The pipeline ran gen6 end-to-end (8,000,353 positions, probe
**"saturated"** at 0.441% half→full — no 12M extension; λ=1.0 won selection
+107.5 vs +49.6; SPRT vs v4.0 **+155.0 ±28.6**, H1). But a 1,200-game
**net-isolated A/B** — same HEAD source both sides, only the baked net
differing — measured gen6-net vs gen5-net at **+6 ±20: a wash.** Mechanism:
RFP *returns the raw static eval* where a search score is expected. At
datagen's fixed nodes:150000 the speed win that makes RFP +175 in play buys
nothing, so shallow subtrees resolve to the gen5 net's own opinions and the
labels teach the student its teacher's prejudices. The probe's "saturated"
verdict was the same fact seen from the data side. **Rule: labeller builds
get `-DSGR_RFP=0`** (LMR/NMP return searched scores and are safe; RFP is
uniquely toxic). Two pipeline bugs surfaced en route, both now fixed:
`stage_sprt` derived the baseline name from the *generation* number, naming
both engines "Sgurr-v5.0" once gen/version numbering diverged (fastchess
refused; baseline exe+name are now config keys, with a fail-fast collision
check), and the Elo regex also matched `nElo`, silently recording normalised
Elo (190.3 for a true 155.0 — anchored with `\bElo`, state corrected before
the ledger saw it).

## 2026-07-15 — v5.0 "Gillean" released (search-only); v6.0 package staged

**v5.0 = the factorial's `both` arm shipped:** LMP+RFP search on the
unchanged gen5 net, `sgr_v5_0.exe`, id "Sgurr 5.0" (binary rebuilt for the id
string after calibration; node-identity to the calibrated build re-verified
on four fixed-depth positions, selfcheck PASS). Calibration on pool-B:
**2724 ±36** (240 games @10+0.1, 47.5% — bracketed, not extrapolated; level
with Zahak-5.0, the old pool's ceiling). **+119 vs v4.0 same-solve** against
+176.4 ±15 self-play: the first large search gain the project has
pool-measured, and it expressed ~two-thirds — unlike malus (+33→~0) and the
v3.1 soft limit (+24.6→negative). Compression is category- and
magnitude-dependent; big pruning gains survive. White advantage −0.3 ±5.2 —
stays closed. Next: **v6.0 search-refinement candidates implemented behind
default-OFF toggles** (`SGR_IMPROVING`: static-eval stack, RFP margin −1 ply
when improving, LMP budget halved when not; `SGR_HISTLMR`: reduction nudged
±2 by butterfly+conthist — the interaction conthist has been waiting for;
`SGR_SINGULAR`: excluded-move test at depth ≥7, TT/NMP correctly disabled in
the helper search). Bare build verified node-identical to `sgr_v5_0`
(161334/252602/6224/104475 at depth 10); package-on build sane (fewer nodes
on quiet positions, more on the tactical one — extensions doing their job).
SPRT `sgr_x_all` vs `sgr_v5_0` next, then factorial decomposition only if
the package number warrants it. After that, the big lever: gen7
king-bucketed features, with the RFP-free labeller.

## 2026-07-15 — negative result: TT size buys nothing at blitz, and the tree was never bloated

Two speculations tested and killed, both cheap, both worth recording so they
are not re-run. **(1) "RFP's +176 means the tree is bloated."** It isn't: the
effective branching factor measured **1.2–2.9, mostly ~1.5–2.5** across
startpos/kiwipete/middlegame at depths 8–15 — healthy, well-pruned,
mature-engine territory. The likelier reading of RFP's outsized gain is
mundane: RFP leans on eval quality, and a strong NNUE with little overlapping
pruning to compete with harvests its full value, where the "+20–30" folklore
comes from mature engines adding it on top of everything else.
**(2) "The 64MB TT is thrashing."** A fixed-depth probe (2^21 vs 2^24, same
source, only the table size differing) showed *textbook threshold behaviour* —
**0% node savings below ~2M nodes, then up to 44% above it** (kiwipete d15
+28.7%, middlegame d14/d15 +35.4%/+43.9%; startpos noisy and sometimes
negative, since changing TT contents reshuffles move ordering chaotically).
So the table *is* undersized for deep searches. But at 8+0.08 the engine runs
~1.3M NPS and spends ~350k nodes per move — **an order of magnitude below the
threshold** — so the only available mechanism was cross-move reuse (the TT
survives `clear_for_new_position`; a game pushes ~14M cumulative nodes through
2M slots). SPRT tt24 vs tt21 settled it: **−12.0 ±15.7 after 1,270 games**,
LLR drifting to H0, stopped early. If anything the bigger table is *worse* at
this TC — plausibly the TLB/cache tax of randomly probing 512MB versus 64MB,
neither of which fits the 9MB L3 anyway. **Conclusion: keep 2^21. Node
savings are real but live at analysis depths, not blitz.** The build knob is
reverted; a proper `Hash` UCI option remains worth adding on standards
grounds (there is no `setoption` infra at all), not for Elo. Rule of thumb
banked: at ~2700 with a +150-class lever untouched, sub-20 Elo questions are
not worth the complexity they carry.

## 2026-07-15 — HL=512 on the gen6 8M: flat. Third witness against the labels

The gen4→gen5 playbook (same data, wider net) did not repeat. HL=512 trained
on the gen6 8M (12 epochs cosine, λ=1.0, loss 0.00475 vs gen6-384's 0.00522 —
loss ≠ Elo, and the step budgets differ), selfcheck PASS at 512 (4,468
checks), NPS tax ~20% (1.06M vs 1.32M). SPRT vs v5.0 stopped early at ~820
games: **−5.5 ±22**, LLR −0.26. The +40–60 the 256→384 precedent predicted
would have been visible by then; it is not there. Reading: the wider net's
eval gain roughly cancels its speed tax — the capacity finds nothing more in
these labels. That is now **three independent measurements agreeing the gen6
8M is exhausted** (probe "saturated" 0.441%, gen6-net A/B +6 ±20, HL=512
flat), which is the RFP-poisoned-labels diagnosis confirmed from a third
angle. Net kept as `nets/gen7_hl512_l10.nnue` (nothing deleted); engine
`sgr_hl512.exe`. Consequence: **no architecture work on this dataset — clean
RFP-free regen first, then king buckets (and re-test width on clean data).**

## 2026-07-16 — v6.0 "Banachdaich": the refinement package pools at +83, and pool-B pays off early

**2807 ±36** (240 games @10+0.1 vs pool-B, 56.7%), **+83 vs v5.0 same-solve** —
a new project high and the first Sgurr above Zahak-5.0 (2726). Shipped
`sgr_v6_0.exe`: gen5 net, `SGR_IMPROVING` + `SGR_HISTLMR` + `SGR_SINGULAR`
default-on, id "Sgurr 6.0", verified node-identical at fixed depth to the
`sgr_x_all` build that took the SPRT (+57.3 ±17.3, H1 at 1,139 games).

**Compression, second data point — and the category theory is wobbling.**
Self-play +57.3 ±17.3 → pooled +83 ±51. Indistinguishable, so the package
expressed *at least* fully; the point estimate is if anything higher.
Alongside RFP (+176 → +119, ~2/3), that is now two large-ish search gains
that survived the pool, against two small ones that did not (malus +33 → ~0;
v3.1 soft limit +24.6 → negative). The working rule shifts from "search
compresses, nets don't" to something closer to **"magnitude predicts
survival"** — small self-play deltas are the ones that evaporate, regardless
of category. Two points is not a curve and ±51 is wide; do not over-fit this.

**pool-2026-07-B was load-bearing within one release of being built.** The
morning's argument for adding anchors above Zahak-5.0 was insurance for
gen7-8; v6.0 needed it the same night. At 2807 on pool-A there would have
been nothing above the engine and the headline number would have been an
extrapolation with inflated bars. Instead Weiss-1.0 (2896) brackets it at
56.7% — measured. The re-anchor also keeps the whole ladder on one scale:
2376 → 2385 → 2468 → 2589 → 2604 → 2724 → 2807.

**Not decomposed.** The +57 is the package; leave-one-out builds (~3,600
games each) remain owed, and the live question is whether `SGR_HISTLMR` is
what finally makes continuation history pay after it measured ~0 alone on
07-10. A passenger left default-on is permanent complexity — but the machine
is now needed for the clean regen, and that outranks a diagnostic.

**Next: the datagen bottleneck, not the search.** Three measurements say the
gen6 8M is exhausted (probe "saturated", gen6-net A/B +6 ±20, HL=512 flat
−5.5 ±22), so both width and king buckets gate on an RFP-free regen. v6.0
shipping first is a bonus for it: the labeller becomes the new engine minus
RFP, and improving/histLMR/singular all return *searched* scores, so unlike
RFP they are labeller-safe and their depth gain lands in the labels for free.

## 2026-07-22 — NNUE inference was scalar the whole time: AVX2 int16 is +21% NPS, free

The evaluation had never been vectorised. `nnue.cpp` was plain scalar loops
with an **int32 accumulator**, leaning entirely on compiler auto-vectorisation
— which does not handle the output layer's horizontal reduction. On a Zen 4
box with AVX2 (and AVX-512) sitting idle, that is pure NPS left on the floor.

**Change (`-DSGR_SIMD`, default on).** Accumulator narrowed to **int16**; the
output layer hand-written as AVX2 clamp (`min/max_epi16`) + `vpmaddwd` +
horizontal sum. The int16 accumulator is provably overflow-safe *for every
legal position*, not just sampled ones: `train.py` clips feature weights to
±127, so the worst case (bias + 32 pieces) is bounded at ±~4100 — an 8–12.6×
margin under int16 across all deploy nets (gen1 8.0×, gen3 12.6×, gen5 11.7×,
gen6 10.8×, gen7-512 8.9×).

**Bit-identical, so no Elo risk of its own.** All integer arithmetic with no
reordering that changes the total, so the SIMD output *equals* the scalar
output exactly — verified two ways: (1) a cross-build eval checksum over
150k+ positions (selfcheck `evalsum`) matches to the integer between the
scalar and SIMD builds on gen5 and gen6; (2) full games are **node-identical
at fixed depth** — same search, same moves, just faster. The rebuilt v6.0
baseline is node-identical to the shipped `sgr_v6_0.exe`, so it is still v6.0.

**Measured NPS (gen5 net, depth-fixed, quiet 7800X3D):** startpos +20.0%,
midgame +18.2%, endgame +26.5% — **~+21% average**. At ~70 Elo/doubling that
is **≈ +13–19 Elo**, banked with a mechanical guarantee rather than an SPRT.

**Now default-on**, matching the search-toggle convention (`#ifndef SGR_SIMD
/ #define SGR_SIMD 1`); `-DSGR_SIMD=0` reverts to scalar. Compile-time guards:
`#error` without AVX2, `static_assert` on HL%16 and HL≤512 (the int32 lane
sums stay exact to the scalar int64 total only through 512; HL=1024 for the
width retest will need int64 widening — guarded, not silent).

**Consequences.** (a) The gen7 pipeline builds SIMD by default; its SPRT
baseline was rebuilt SIMD too, so the net stays the only variable. (b) Free
on both sides of the flywheel — a SIMD datagen build labels ~21% faster with
bit-identical labels, so rebuild `datagen.exe` with it before gen8. (c) More
is available later (AVX-512 width, vectorising the accumulator update loops,
int8 activations) but this clean, verified cut is banked first.

## 2026-07-22 — AVX-512 + vectorised update loops: +3% more, and the honest ceiling

Second SIMD pass, same evening. The inference now width-dispatches on the
compiler's target: **AVX-512** (32 int16 lanes) when `__AVX512BW__` is
defined, AVX2 otherwise, scalar with `-DSGR_SIMD=0`. The accumulator
**update loops** (`edit_feature`) are hand-vectorised at both widths, the
refresh bias-init became two `memcpy`s (AccT == the stored bias type), and
`g_acc` is 64-byte aligned.

**Result: +3.2% over the AVX2 forward-pass build** (start +4.1%, mid +3.8%,
end +1.7%; node counts identical throughout), total **~+22% vs scalar**.
Modest, and the reasons were predictable: Zen 4 double-pumps 512-bit ops
through 256-bit units, so AVX-512 buys instruction count, not width; and
clang's auto-vectoriser was already handling the simple int16 `+=` update
loops well — the hand-written forward pass (horizontal reduction, which
auto-vectorisation does not do) was always the real win. Banked because it
is free and verified, logged at its measured size: **≈ +2–3 Elo on top of
v1's +13–19.** The remaining SIMD headroom on this architecture is small;
int8 activations would be the next step-change and that is a
quantisation-scheme project, not an intrinsics evening.

**Verification, same bar as v1:** three-way eval checksum (avx512 / avx2 /
scalar selfcheck builds) identical to the integer on gen5 and gen6
(`evalsum=-230828` / `-334461`, 4,468 checks each, all PASS); engine
node-identical to the shipped `sgr_v6_0.exe` at fixed depth on
opening/middlegame/endgame. The SPRT baseline `sgr_v6_0_zen4.exe` was
rebuilt from the final source so tonight's gen7 candidate and its baseline
share identical inference speed.

**Observability:** every binary now self-reports its path — the startup line
reads `nnue: loaded <net> (avx512|avx2|scalar)` and selfcheck prints
`simd=<kind>` — so a build silently falling back to a slower path is visible
in any log, in keeping with the no-silent-config lesson from the migration.

## 2026-07-29 — gen8 A/B: king buckets flat on clean data; the flywheel turn is +105

The away-week harvest closed at **55,931,801 clean positions** (gen7-net
labeller, `-DSGR_RFP=0`, nodes:150000, ~7.9M/day over 7.06 days, zero torn
tails across ~5 auto-resume cycles). Two nets trained on it, identical
settings (λ=1.0, 8 epochs cosine): a 768×384 control and an 8-king-bucket
variant (v2 net format; map = back rank in file-pairs, then rank bands,
embedded in the file and read back by the engine — see commit c3c0e68).
Two 1,200-game net-isolated A/Bs at 8+0.08, search held constant.

**King buckets: −10.7 ±16.3 vs the control.** Flat, trending negative; the
CI excludes the whole +25–50 prior. This despite **12% lower training loss**
(0.00493 vs 0.00558) — the third loss≠Elo instance (gen6 net A/B, HL=512,
now k8) and the first on CLEAN labels, so the poisoned-label explanation is
unavailable. Reading: at 150k-node label depth, a 768×384 net already
absorbs essentially everything the labels contain; added capacity fits label
noise (lower loss) without adding chess (no Elo). Candidate co-factors, in
falling order of belief: label-information ceiling; 56M still thin for 8
buckets (~7M/bucket, skewed toward castled kings); untuned map. The v2
format, engine support, and selfcheck coverage are merged and verified, so
the retest is cheap when either labels deepen or data grows. Nets kept:
`nets/gen8-k8.nnue`, `nets/gen8-ctrl768.nnue`.

**The flywheel turn: +105.3 ±16.2** — gen8-ctrl beats the gen7 net directly,
the largest single-cycle net gain in the project's history (previous best:
gen5's +55.5). Honest decomposition note: this is NOT data volume alone —
it bundles 5× positions AND two generations of labeller upgrade (gen7's data
was labelled by the gen5 net; gen8's by the gen7 net). A volume-isolated
number would need a 768 net on an 11M subset of gen8; not run — the release
does not depend on it. The student beating its teacher by +105 is the
flywheel working as designed: search-amplified labels (150k nodes) carry far
more knowledge than the labeller's raw eval.

**Consequence for the roadmap: the binding constraint is now label quality,
not net capacity.** Both archs saturate the current labels; width retests
and bucket retests gate on better labels (deeper labelling search, or the
next flywheel turn), not on more of the same data.

**Release: v8.0 candidate = unbucketed 768×384 on the gen8 56M.**
`configs/pipeline_gen8.json` flipped accordingly. At the historical ~2/3 pool
compression for large gains, +105 self-play projects ~+70–90 pooled from
v7.0's 2903 ±6 — the 3000 target is plausibly inside this cycle.

## 2026-07-30 — mining the gen8 56M: λ is already optimal, width pays +9, buckets pay nothing even done properly

Four experiments on the **fixed** gen8 dataset, all net-isolated A/Bs at
8+0.08 with search held constant. The point was to exhaust what a week of
datagen can give before spending another week on gen9.

**λ sweep — 0.9 is the peak; no free gain.** vs the shipped λ=0.9 net:
λ=0.85 **−4.4 ±7.1**, λ=0.7 **−12.6 ±7.0**, λ=0.6 **−51.9 ±11.9** (l060
stopped at 3,030 games, direction unambiguous); gen8's own selection round
already had λ=1.0 losing to 0.9. The curve brackets a maximum at 0.9 from
both sides. Keep λ=0.9; stop tuning it.

**Width — HL 384→512 is +9.0 ±10.3** (3,000 games, one-sided ≈96% a real
gain, and this is NET of the ~20% NPS tax since the match is at fixed TC).
Notably HL=512 measured *flat* on gen6's RFP-poisoned data and pays here:
cleaner labels do support somewhat more capacity. Carry HL=512 into gen9.

**King buckets, take two: the factorizer.** The naive per-bucket net's
−10.7 was diagnosed as data starvation (8 buckets, each weight seeing ~⅛ of
the positions). Implemented the standard fix in `train.py`: a **shared base
table trained on ALL positions plus a small per-bucket delta**, deltas
zero-initialised so training starts from exactly the unbucketed model and
diverges only where a bucket's data supports it. Export **coalesces**
(`final[b][f] = shared[f] + delta[b][f]`) into the same v2 file, so engine
inference is untouched — verified by selfcheck PASS and a
Python-vs-engine golden match on the coalesced net.

**It worked as engineering and bought nothing as chess: +2.0 ±10.0.** The
factorizer moved buckets ~+13 Elo (−10.7 → +2.0), i.e. it removed the
starvation penalty exactly as intended — and the gain never materialised.
Two independent implementations now say **these labels carry no
king-zone-specific information beyond what shared weights already
capture**. Buckets are dropped for gen9; the code stays (verified, dormant,
zero cost) for retest when labels change.

**Sharpest loss≠Elo evidence yet — the ranking is inverted.** On identical
data: factorized-k8 **best loss 0.00471 → +2 Elo**; naive-k8 0.00493 →
**−10.7**; ctrl768 0.00558 → baseline; HL512 **worst loss 0.00661 → +9
Elo**. Training loss is not merely uninformative here, it is
*anti-correlated* with strength. Fourth instance in this log (gen6 net A/B,
HL=512-on-gen6, naive buckets, now this) — the rule is settled: **never
select an architecture on loss; only games decide.**

**Consequence.** The 56M is mined out: one +9 (width), one 0 (buckets), one
confirmed-optimal knob (λ). Capacity is not the constraint — **label
information is**, and the only lever that has ever moved this project by
+100 is a flywheel turn (a stronger labeller). gen9 = gen8 net as labeller,
HL=512, λ=0.9, buckets off.

> **Superseded 2026-08-01.** The "mined out / label-limited" reading above was
> wrong, and the +9 width result it rests on is inside a noise floor that had
> never been measured. See the next entry.

## 2026-08-01 — the noise floor: training is not reproducible, and half of last week's conclusions were never real

**Measured what had always been assumed.** Two nets, identical data (the gen8
56M), identical recipe (HL384, λ=0.9, 8 epochs cosine, val_frac 0), differing
**only in random seed**. Result: **+13.7 ±10.3** over 3,000 games — a 95% CI
of [+3.4, +24.0] that **excludes zero**. Two runs of the same recipe produce
measurably different engines.

**Consequences, applied honestly.** Every net A/B in this project quietly
assumed this number was ~0. Anything under roughly ±25 was never established:

| result | status |
|---|---|
| gen8 vs gen7 **+126** | survives |
| 14M vs 56M **−65** | survives |
| λ=0.6 **−52** | survives |
| gen7 vs gen6 **+44** | survives |
| **HL512 width +9.0** | **inside noise — withdrawn** |
| naive buckets −10.7 | inside noise |
| factorizer +2.0 | inside noise (conclusion unchanged; it was ~0) |
| λ=0.85 −4.4, λ=0.7 −12.6 | inside noise (curve *shape* survives on λ=0.6) |

The structural findings all stand. The architecture micro-results do not, and
the gen9 recommendation of "HL=512" is retracted — it was seed luck as much
as signal.

**More games cannot fix this.** The variance lives in the *training*, not the
measurement: 10,000 games shrinks the match error and leaves the seed error
untouched. Resolving sub-20 Elo effects requires training N seeds per
configuration and averaging — multiplying the cost of every architecture
experiment by 3–5×. This retroactively explains the "magnitude predicts
survival" rule from 07-16: small deltas evaporate partly because they were
never distinguishable from noise to begin with.

## 2026-08-01 — architecture × data: data volume dominates, and 56M is NOT saturated

Five points, 15,000 games, 12.5 h, all vs `nets/gen8.nnue` (HL384 @ 56M).

| | 14M | 28M | 56M |
|---|---|---|---|
| **HL256** | −75.8 ±10.5 | — | −6.9 ±10.0 |
| **HL384** | −65 (32ep) / −119.1 ±10.7 (8ep) | −48.5 ±10.4 | 0 (ref) |
| **HL512** | — | — | +9.0 ±10.3 |

**1. Data volume beats architecture by ~4×.** Across a 2× width range
(256→512) the whole spread is ~16 Elo, every point inside the ±14 noise
floor. Across a 4× data range it is **65 Elo**, far outside it. Width is a
rounding error; positions are the product.

**2. A smaller net is NOT more data-efficient** — the question this run was
built to answer. Each architecture's shortfall at 14M, measured against *its
own* 56M ceiling: HL384 65 Elo short, HL256 69 Elo short. Identical. The
hypothesis that a skinnier net could buy 2-day generations (trading ~15 Elo
for 3.5× more flywheel turns) is dead: at 14M you lose ~65–70 Elo whatever
the width, and that net is also the next generation's labeller, so the
deficit compounds instead of washing out.

**3. Returns are ACCELERATING, not diminishing.** 14M → 28M buys +17;
28M → 56M buys +48. The curve is convex over the measured range, so **56M is
not near the ceiling** and gen9 should collect *more*, not less. This is the
exact opposite of the plan that motivated the run.

**4. The probe stage's saturation verdict is worthless.** It called gen6,
gen7 *and* gen8 "saturated" (0.44%, 0.32%, 0.21% half→full val-loss gain).
Yet 14M→56M is worth 65 Elo. It is a loss-based signal in a project where
loss has now been wrong five times running; it should not be used as a
stopping rule, and the datagen target should not be cut on its say-so.

**5. The recipe confound, resolved.** 14M @ 8 epochs measured **−119.1**
against 14M @ 32 epochs' −65 — so the deficit was never an overfitting
artefact of step-matching; the step-matched net was the *better* arm and
still lost by 65. With less data you need more passes, and even then you
cannot recover. Undertraining hurts more than overfitting at this scale.

**gen9, revised:** gen8 net as labeller, λ=0.9, buckets off, width whatever
is convenient (it does not matter), and **as many positions as the calendar
allows — more than 56M.** Datagen time is the product; everything else is
noise around it.

## 2026-08-03 — speed is worth what the rule said; singular was carrying v6.0

Four jobs, 11,360 games, 9h 11m unattended on an idle 7800X3D, all at 8+0.08
with the gen8 net fixed. Predictions were registered in
`benchmarks/v60_decomp_predictions.md` and `benchmarks/v81_speed_prediction.md`
before a single game was played.

| job | measured | predicted | |
|---|---|---|---|
| v8.1 vs v8.0 | **+21.2 ±8.7** (4,000) | +18 to +19 | correct |
| remove singular | **−77.2 ±19.6** (H0, 750) | +5 to +25 | **wrong** |
| remove improving | **−19.6 ±10.5** (H0, 2,610) | −15 to −40 | correct |
| remove histLMR | **+1.1 ±8.7** (4,000) | 0 ±8 | correct |

### Speed converts to Elo at roughly the rate assumed

v8.1 is v8.0's search compiled better: PGO + ThinLTO, then nine node-identical
data-layout changes, ~20% NPS in total. The two binaries are
bench-fingerprint-identical (13,614,729 nodes at depth 13) and move-identical
at fixed depth, so speed is the only variable that exists between them.

**+21.2 ±8.7 over 4,000 games**, against +18.4 predicted from
70 × log₂(1.20). The interval is [+12.6, +29.9]; the prediction band was
[+10, +27].

This closes a gap that had been open since 2026-07-22. §5 of `METHODOLOGY.md`
listed the AVX-512 result as "~+22% NPS (≈+15 Elo, *inferred*)" and said so
explicitly — converted through a community rule of thumb, never checked in
games — and every speed gain since inherited the same caveat. The rule holds
for this engine at this control, and was if anything slightly conservative.

It was also the last chance to ask cleanly. Any search change confounds speed
with behaviour permanently.

### Singular extensions were carrying the v6.0 package, and the prediction was badly wrong

Removing singular measured **−77.2**, rejecting in 36 minutes. I had predicted
**positive**, at 60% confidence, with "anything below −5" as the stated
falsification condition.

The reasoning that failed: singular costs **+85% of the tree**
(13,614,729 → 7,351,781 nodes with it off), which at a fixed control is paid
out of the clock — about one ply, or ~60 Elo of free depth by the same
conversion rule validated above. I treated that cost as the dominant term, and
read the tight `SINGULAR_MARGIN` of 2 cp/ply as evidence of over-firing.

It is not close. Singular is worth more than a full ply of depth, and the
implementation is unrefined — no double extensions, no negative extensions, no
multicut return from the singular search, and three constants that have never
been tuned.

**The lesson is about the instrument, not the feature.** Node counts said the
three v6.0 components were wildly unequal, and they were — but the ordering
node counts implied was inverted for singular. Tree cost measures what a
feature *spends*, and carries almost no information about what it *buys*. A
60% confidence built on it was overstated; the honest figure was nearer 40%.

The composite claim from the pre-registration — "+57.3 was mostly the
improving flag, with singular break-even-to-negative" — is dead. Decomposed:

| component | Elo when removed | share of the +57.3 |
|---|---|---|
| singular extensions | −77.2 ±19.6 | dominant |
| improving flag | −19.6 ±10.5 | secondary |
| history-adjusted LMR | +1.1 ±8.7 | none |

The three do not sum to +57.3, and should not be expected to — they interact,
and leave-one-out on an interacting set measures marginal not additive
contribution. The ordering is the result.

### History-adjusted LMR is inert, and that is a tuning bug not a dead feature

**+1.1 ±8.7** — removing it costs nothing measurable, exactly as the mechanism
predicted on 2026-08-02. History earns `depth * depth` per cutoff (169 at
depth 13) and is halved every move, so `hist_score / 400'000` rounds to zero
almost always. `HistLmrMax = 0`, which disables the adjustment outright,
changes the bench tree not at all.

This is "worth nothing at `HistLmrDiv = 400'000`", not "the technique is
worthless". At a divisor where it functions the tree moves ~10% (5,000 →
12,239,286 nodes). It has been shipped switched off since v6.0. Do not delete
it; tune it.

### Consequences

* **Release v8.1.** +21.2 self-play on a node-identical binary. Pool
  calibration still owed before it earns a ledger row or a website rating —
  self-play gains have compressed against the pool before (§6), so the pooled
  figure is not simply 3006 + 21.
* **Singular is now a first-wave SPSA target, not a mid-tier one.** A feature
  worth ~+77 unrefined, with three untuned constants, has more headroom than
  anything else currently on the list.
* **Stop using tree size as a proxy for feature value.** It was useful for
  finding the inert one, and actively misleading about the valuable one.
