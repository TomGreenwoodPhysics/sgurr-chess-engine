# Sgurr results ledger (append-only)

Every absolute calibration run appends one row per Sgurr version measured.
Nothing is ever edited or deleted; corrections are new rows with a note.
Ratings are Ordo, anchored to the pool's published CCRL Blitz ratings
(see `pool.json` / `anchors.txt`); they are estimates on the CCRL Blitz
scale, not official CCRL ratings.

| date | engine | rating | ±95% | games | W-D-L | TC | pool | hardware | notes |
|------|--------|--------|------|-------|-------|----|------|----------|-------|
| 2026-07-16 | Sgurr v6.0 "Banachdaich" | 2807 | 36 | 240 | +117 =38 -85 | 10+0.1 | pool-2026-07-B | i5-9400F, 5 threads | Ordo, CCRL-Blitz-anchored, solved over all accumulated calibration games. Search-only release on the unchanged gen5 net: improving flag + history-adjusted LMR + singular extensions (SPRT vs v5.0 **+57.3 ±17.3**, H1 at 1,139 games, package undecomposed). **+83 vs v5.0 same-solve** (2724) — joint error ±51, so consistent with the self-play +57; no compression evident. New project high, first version above Zahak-5.0 (2726); bracketed from above by Weiss-1.0 (2896) at 56.7%, i.e. measured, not extrapolated — pool-B's new anchors were load-bearing here. |
| 2026-07-15 | Sgurr v5.0 "Gillean" | 2724 | 36 | 240 | +97 =34 -109 | 10+0.1 | pool-2026-07-B | i5-9400F, 5 threads | Ordo, CCRL-Blitz-anchored, solved over all accumulated calibration games (~2,900). Search-only release: LMP + RFP on the unchanged gen5 net — the gen6 net was a wash (+6 ±20, 1,200-game net-isolated A/B) and is not shipped. +119 vs v4.0 **same-solve** (2604); the +176.4 ±15 self-play factorial gain expressed ~2/3 against the pool. Level with Zahak-5.0 (2726). **Scale note: pool-B re-anchor — all rows sit ~22 below their published pool-A values; compare within one solve only.** |
| 2026-07-10 | Sgurr v4.0 "MacKenzie" | 2627 | 27 | 420 | +216 =60 -144 | 10+0.1 | pool-2026-07-A | i5-9400F, 5 threads | Ordo, CCRL-Blitz-anchored, solved over all ~3,600 accumulated calibration games. gen5 net (768→384) + best-move stability + history malus/conthist. +63 vs v3.1 on the pool scale; statistically level with the pre-malus gen5-bmstab measurement (2635.5 ±25.5) — self-play search gains compress vs the pool. |
| 2026-07-10 | Sgurr v3.1 "Blackpeak" | 2564 | 27 | 420 | +140 =150 -130 | 10+0.1 | pool-2026-07-A | i5-9400F, 5 threads | Deferred debt from the 07-08 release, settled. **Below v3.0 (2613)**: the flat soft limit loses at 10+0.1 despite the +24.6 ±22.7 interim SPRT at 8+0.08 — TC-dependent; superseded by v4.0's stability scaling. Finding reproduced across three independent solves. |
| 2026-07-06 | Sgurr v3.0 "Blackpeak" | 2616 | 37 | 210 | +105 =29 -76 | 10+0.1 | pool-2026-07-A | i5-9400F, 5 threads | Ordo, CCRL-Blitz-anchored, solved over all accumulated calibration games. +125 vs v2.0 — reproduces the direct SPRT (+119.8 ±26.3), so the self-play gain was not inflated. Above Zahak-4.0 (2601). |
| 2026-07-04 | Sgurr v2.0 "Notches" | 2489 | 34 | 270 | +110 =33 -127 | 10+0.1 | pool-2026-07-A | i5-9400F, 5 threads | Ordo, CCRL-Blitz-anchored. +82 vs v1.0, +91 vs classical — matches the direct SPRT gaps, so the self-play +77.7 was not inflated. |
| 2026-07-04 | Sgurr v1.0 "Fox" | 2407 | 35 | 270 | +87 =22 -161 | 10+0.1 | pool-2026-07-A | i5-9400F, 5 threads | Ordo, CCRL-Blitz-anchored. +9 vs classical (parity, as SPRT found). |
| 2026-07-04 | Sgurr classical (HCE) | 2398 | 34 | 270 | +80 =30 -160 | 10+0.1 | pool-2026-07-A | i5-9400F, 5 threads | Ordo, CCRL-Blitz-anchored. Supersedes the old ~2520 SF-limited estimate (flawed method + different scale). |

## Run log

### 2026-07-16 — v6.0 "Banachdaich" release calibration (search refinement package)

- **Tool:** fastchess 1.8.0-alpha gauntlet, 240 games (8 opponents × 30),
  10+0.1, `testing/book.epd`, concurrency 5, idle machine. Ordo 1.0 over ALL
  accumulated calibration PGNs, `-m anchors.txt`, `-W`, `-s 1500`.
- **Result:** **Sgurr v6.0 = 2807 ±36** (+117 =38 −85, 56.7%). **+83 vs v5.0
  in the same solve** (2724 ±36; joint error ±51). Ladder on the pool-B
  scale: 2376 → 2385 → 2468 → 2589 → 2604 → 2724 → **2807**.
- **Provenance:** `sgr_v6_0.exe` = gen5 net (`nets/gen5.nnue`) with
  `SGR_IMPROVING` / `SGR_HISTLMR` / `SGR_SINGULAR` now default-on, id
  "Sgurr 6.0"; verified node-identical at fixed depth to the exact
  `sgr_x_all` build that took the SPRT (133679 / 194912 / 4641 / 141838).
  Search-only release on the unchanged net, as v5.0 and v3.1 were.
- **Compression, second data point:** self-play **+57.3 ±17.3** → pooled
  **+83 ±51**. The two are statistically indistinguishable, so the package
  expressed *at least* fully. With RFP's +176 → +119 (~2/3), the pattern so
  far is that **large pruning gains and this refinement package both survive
  the pool**, unlike the small tweaks that vanished (malus +33 → ~0; v3.1
  soft limit +24.6 → negative). Magnitude, not category, looks like the
  predictor — but two points is not a curve, and ±51 is wide.
- **pool-B earned its keep immediately.** v6.0 is the first Sgurr version
  above Zahak-5.0 (2726) — pool-A's ceiling. On the old pool this number
  would have had no anchor above it and would have been an extrapolation;
  instead Weiss-1.0 (2896) brackets it at 56.7%. The upgrade was argued as
  insurance for gen7-8 and was needed one release later.
- **Package NOT decomposed.** The +57 is improving + histLMR + singular
  together; leave-one-out builds (~3,600 games each) would isolate them, and
  the open question is whether `SGR_HISTLMR` is what finally makes
  continuation history pay (it measured ~0 alone on 07-10). Deferred — a
  passenger left default-on is permanent complexity.
- **White advantage +2.5 ±4.9** — stays closed.

### 2026-07-15 — v5.0 "Gillean" release calibration on the re-anchored pool-2026-07-B

- **Pool supersession:** an audit against the live CCRL Blitz list found every
  pool-A anchor inflated by 12–50 (mean ≈31) — the values had come from each
  engine's README, not the list — and Blunder-7.2.0 has no CCRL Blitz rating
  at any version, so one "CCRL-anchored" anchor never was. pool-2026-07-B
  re-sources every anchor from the live list (2026-07-15), drops
  Blunder-6.1.0 from the roster (93% score, no signal; still pinned in
  anchors.txt at 2105 to bracket the historical rows), floats Blunder-7.2.0
  as a free node, and adds two families above the old ceiling: Weiss-1.0
  (2896), Igel-2.2.2 (2982), Weiss-1.2 (3055).
- **Tool:** fastchess 1.8.0-alpha gauntlet, 240 games (8 opponents × 30),
  10+0.1, `testing/book.epd`, concurrency 5, idle machine. Ordo 1.0 over ALL
  accumulated calibration PGNs, `-m anchors.txt`, `-W`, `-s 1500`.
- **Result:** **Sgurr v5.0 = 2724 ±36** (+97 =34 −109, 47.5%) — level with
  Zahak-5.0 (2726) and bracketed from above by the three new anchors, i.e.
  measured, not extrapolated. **+119 vs v4.0 on the same solve** (2604 ±27).
- **Provenance:** `sgr_v5_0.exe` = gen5 net (`nets/gen5.nnue`) baked into the
  current source (LMP + RFP on); selfcheck PASS; UCI-verified. A search-only
  release, as v3.1 was: **the gen6 net is not shipped.** The full gen6
  pipeline ran (8,000,353 positions, gen5 labeller @150k nodes; probe verdict
  "saturated" at 0.441% half→full; λ∈{0.9,1.0} trained; λ=1.0 won selection),
  but a 1,200-game net-isolated A/B (identical search, only the net swapped)
  measured the gen6 net at **+6 ±20 vs gen5 — a wash.**
- **Why the gen6 data was dead: RFP poisons fixed-node labels.** RFP returns
  the raw static eval where a search result is expected; under datagen's
  fixed nodes:150000 budget its speed benefit is worth nothing, so labels
  drifted toward the gen5 labeller's own opinions. The probe's "saturated"
  verdict caught this independently. Rule adopted: **the labeller build gets
  `-DSGR_RFP=0`; RFP belongs in the playing engine, not in the labeller.**
- **Cross-checks:** the self-play SPRT vs v4.0 (8+0.08, H1 accepted) was
  **+155.0 ±28.6** on the gen6-net build; the shipped configuration equals
  the 07-11 factorial's `both` arm, **+176.4 ±15** self-play. Pooled +119
  means the first large search gain this project has measured expressed
  ~two-thirds against a diverse pool — unlike malus (+33 → ~0) and the v3.1
  soft limit (+24.6 → negative), large pruning gains survive.
- **Re-anchor validation:** historical rows shifted uniformly (v4.0
  2627→2604, v3.0 2616→2590, v3.1 2564→2541, v2.0 2489→2467, v1.0 2407→2386,
  classical 2398→2377 — all −21 to −26, inside error), and unanchored
  Blunder-7.2.0 solved to 2430.6 ±31 vs its README 2425. White advantage
  −0.3 ±5.2 — stays closed.
- **Pipeline bugs found and fixed this run:** (1) the SPRT stage named both
  engines from the generation number ("Sgurr-v5.0" twice — gen and version
  numbering diverged at gen5/v4.0); baseline is now explicit in the config.
  (2) The Elo regex also matched fastchess's `nElo` and recorded the
  normalised value (190.3 for 155.0); anchored with `\bElo`, state corrected.

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
