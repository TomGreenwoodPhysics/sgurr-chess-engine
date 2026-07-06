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
