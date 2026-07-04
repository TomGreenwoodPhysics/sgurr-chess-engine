# Sgurr results ledger (append-only)

Every absolute calibration run appends one row per Sgurr version measured.
Nothing is ever edited or deleted; corrections are new rows with a note.
Ratings are Ordo, anchored to the pool's published CCRL Blitz ratings
(see `pool.json` / `anchors.txt`); they are estimates on the CCRL Blitz
scale, not official CCRL ratings.

| date | engine | rating | ±95% | games | W-D-L | TC | pool | hardware | notes |
|------|--------|--------|------|-------|-------|----|------|----------|-------|
| 2026-07-04 | Sgurr v2.0 "Notches" | 2489 | 34 | 270 | +110 =33 -127 | 10+0.1 | pool-2026-07-A | i5-9400F, 5 threads | Ordo, CCRL-Blitz-anchored. +82 vs v1.0, +91 vs classical — matches the direct SPRT gaps, so the self-play +77.7 was not inflated. |
| 2026-07-04 | Sgurr v1.0 "Fox" | 2407 | 35 | 270 | +87 =22 -161 | 10+0.1 | pool-2026-07-A | i5-9400F, 5 threads | Ordo, CCRL-Blitz-anchored. +9 vs classical (parity, as SPRT found). |
| 2026-07-04 | Sgurr classical (HCE) | 2398 | 34 | 270 | +80 =30 -160 | 10+0.1 | pool-2026-07-A | i5-9400F, 5 threads | Ordo, CCRL-Blitz-anchored. Supersedes the old ~2520 SF-limited estimate (flawed method + different scale). |

## Run log

### 2026-07-04 — first calibration (pool-2026-07-A)

- **Tool:** fastchess 1.8.0-alpha, gauntlet (3 Sgurr seeds vs 7-engine pool + seed-vs-seed), 720 games, 15 openings × colours-reversed pairs, `testing/book.epd`, TC 10+0.1, concurrency 5.
- **Solver:** Ordo 1.0, `-m anchors.txt` (all 7 pool engines pinned to published CCRL Blitz), `-W` (white advantage auto), `-s 2000` simulations for error bars.
- **Anchors:** approximate CCRL Blitz values from each engine's README/search (see `anchors.txt`); the absolute scale is only as accurate as these — internal gaps between Sgurr versions are anchor-independent and robust.
- **Pool ordered exactly as CCRL predicts** (Zahak-5.0 top → Blunder-6.1.0 bottom), validating the anchoring.
- **Caveat — white advantage came out −23 ±10** (black won 341 vs white 305 across the pool). Colours are balanced per opening, so this does not bias the ratings, but it hints the self-generated book may slightly favour the side to move; worth a look before the next pool run.
