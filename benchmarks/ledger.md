# Sgurr results ledger (append-only)

Every absolute calibration run appends one row per Sgurr version measured.
Nothing is ever edited or deleted; corrections are new rows with a note.
Ratings are Ordo, anchored to the pool's published CCRL Blitz ratings
(see `pool.json` / `anchors.txt`); they are estimates on the CCRL Blitz
scale, not official CCRL ratings.

| date | engine | rating | ±95% | games | W-D-L | TC | pool | hardware | notes |
|------|--------|--------|------|-------|-------|----|------|----------|-------|
| 2026-07-10 | Sgurr v4.0 "MacKenzie" | 2627 | 27 | 420 | +216 =60 -144 | 10+0.1 | pool-2026-07-A | i5-9400F, 5 threads | Ordo, CCRL-Blitz-anchored, solved over all ~3,600 accumulated calibration games. gen5 net (768→384) + best-move stability + history malus/conthist. +63 vs v3.1 on the pool scale; statistically level with the pre-malus gen5-bmstab measurement (2635.5 ±25.5) — self-play search gains compress vs the pool. |
| 2026-07-10 | Sgurr v3.1 "Blackpeak" | 2564 | 27 | 420 | +140 =150 -130 | 10+0.1 | pool-2026-07-A | i5-9400F, 5 threads | Deferred debt from the 07-08 release, settled. **Below v3.0 (2613)**: the flat soft limit loses at 10+0.1 despite the +24.6 ±22.7 interim SPRT at 8+0.08 — TC-dependent; superseded by v4.0's stability scaling. Finding reproduced across three independent solves. |
| 2026-07-06 | Sgurr v3.0 "Blackpeak" | 2616 | 37 | 210 | +105 =29 -76 | 10+0.1 | pool-2026-07-A | i5-9400F, 5 threads | Ordo, CCRL-Blitz-anchored, solved over all accumulated calibration games. +125 vs v2.0 — reproduces the direct SPRT (+119.8 ±26.3), so the self-play gain was not inflated. Above Zahak-4.0 (2601). |
| 2026-07-04 | Sgurr v2.0 "Notches" | 2489 | 34 | 270 | +110 =33 -127 | 10+0.1 | pool-2026-07-A | i5-9400F, 5 threads | Ordo, CCRL-Blitz-anchored. +82 vs v1.0, +91 vs classical — matches the direct SPRT gaps, so the self-play +77.7 was not inflated. |
| 2026-07-04 | Sgurr v1.0 "Fox" | 2407 | 35 | 270 | +87 =22 -161 | 10+0.1 | pool-2026-07-A | i5-9400F, 5 threads | Ordo, CCRL-Blitz-anchored. +9 vs classical (parity, as SPRT found). |
| 2026-07-04 | Sgurr classical (HCE) | 2398 | 34 | 270 | +80 =30 -160 | 10+0.1 | pool-2026-07-A | i5-9400F, 5 threads | Ordo, CCRL-Blitz-anchored. Supersedes the old ~2520 SF-limited estimate (flawed method + different scale). |

## Run log

### 2026-07-10 — v4.0 release calibration + v3.1 debt settled

- **Tool:** fastchess 1.8.0-alpha. Three gauntlets this day, all 10+0.1,
  `testing/book.epd`, concurrency 5: v3.1 (420 games), gen5 two-seed
  soft/bmstab (900 games), and the release engine Sgurr-v4.0 (420 games,
  +216 =60 −144, 58.6%).
- **Solver:** Ordo 1.0 over ALL accumulated calibration PGNs (~3,600 games),
  `-m anchors.txt`, `-W`, `-s 1500`. One consistent scale; v3.0 drifted
  2616 → 2613 (inside its bars), v2.0/v1.0/classical moved ≤1.
- **Results:** **Sgurr v4.0 = 2627 ±27**; Sgurr v3.1 = 2564 ±27 (its 07-08
  debt settled); intermediate configs gen5-bmstab 2635.5 ±25.5 and
  gen5-soft 2618.9 ±24.0 (same solve, not ledgered as they are not
  releases).
- **Provenance:** v4.0 = `sgr_v4_0.exe`: gen5 net (`nets/gen5.nnue`,
  768→384→1, trained on data/v4.0) baked in, best-move stability + history
  malus + continuation history on; selfcheck PASS; verified node-identical
  to the pooled champion build before the gauntlet.
- **Cross-checks:** gen5-soft − v3.1 = +54 reproduces the +55.5 ±17.0 SPRT
  at a different TC. v3.1 below v3.0 reproduced across three solves (flat
  soft limit loses at 10+0.1 — see DEVLOG). v4.0 vs gen5-bmstab = −8.5
  (joint error ~±37): the self-play malus gain (+33) did not express against
  the pool.
- **Caveat resolved:** white advantage, flagged −23 ±10 (07-04) and −20 ±9
  (07-06), has washed out to **−2.3 ±5.3** over the full combined set —
  small-sample noise, not a book bias; the side-to-move question closes.

### 2026-07-08 — v3.1 shipped WITHOUT calibration (deferred)

No rating row above: **v3.1 has not been pool-calibrated.** It is a search-only
release (soft/hard time management) on the unchanged gen3 net, shipped for
immediate play on the strength of an interim head-to-head SPRT vs the v3.0
engine only — same gen3 net on both sides, 8+0.08, stopped early at 706 games:
**+24.6 ±22.7** (+300 =156 −250, LLR +0.84, no bound crossed). This is not a
completed measurement. A full gauntlet (a v3.1 row here, on the same
pool-2026-07-A scale) is planned before the next generation; until then v3.1
has no absolute CCRL figure of its own.

### 2026-07-06 — v3.0 calibration (pool-2026-07-A)

- **Tool:** fastchess 1.8.0-alpha, gauntlet (Sgurr v3.0 vs the 7-engine pool), 210 games, 15 openings × colours-reversed pairs, `testing/book.epd`, TC 10+0.1, concurrency 5.
- **Solver:** Ordo 1.0 over ALL accumulated calibration PGNs (930 games: the 2026-07-04 run + this gauntlet), `-m anchors.txt`, `-W`, `-s 1500` simulations. Re-solving over the combined set keeps every Sgurr version on one consistent scale; earlier versions moved by ≤2.4 points (v2.0 2489→2491, v1.0 2407→2408, classical 2398→2400), well inside error bars.
- **Result:** Sgurr v3.0 = **2616 ±37** (+105 =29 -76, 56.9%). Version gap +125 vs v2.0 independently reproduces the direct SPRT (+119.8 ±26.3, 618 games).
- **Provenance:** net = gen3 lambda=1.0 (search-score-only targets), picked by a 600-game round-robin over {0.6, 0.7, 0.8, 1.0}; trained on data/v3.0 (3.0M positions, gen2-labelled at nodes:150000) with cosine decay, 12 epochs; engine `sgr_gen3.exe`, selfcheck PASS.
- **Caveat — white advantage again negative (−20 ±9),** consistent with 2026-07-04's −23 ±10; colours balanced so ratings unbiased, but the book side-to-move question remains open.

### 2026-07-04 — first calibration (pool-2026-07-A)

- **Tool:** fastchess 1.8.0-alpha, gauntlet (3 Sgurr seeds vs 7-engine pool + seed-vs-seed), 720 games, 15 openings × colours-reversed pairs, `testing/book.epd`, TC 10+0.1, concurrency 5.
- **Solver:** Ordo 1.0, `-m anchors.txt` (all 7 pool engines pinned to published CCRL Blitz), `-W` (white advantage auto), `-s 2000` simulations for error bars.
- **Anchors:** approximate CCRL Blitz values from each engine's README/search (see `anchors.txt`); the absolute scale is only as accurate as these — internal gaps between Sgurr versions are anchor-independent and robust.
- **Pool ordered exactly as CCRL predicts** (Zahak-5.0 top → Blunder-6.1.0 bottom), validating the anchoring.
- **Caveat — white advantage came out −23 ±10** (black won 341 vs white 305 across the pool). Colours are balanced per opening, so this does not bias the ratings, but it hints the self-generated book may slightly favour the side to move; worth a look before the next pool run.
