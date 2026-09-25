# Batch A: TT in quiescence and PV-node handling, prediction registered before the run

Written 2026-09-25, before any games. Rule 7 of `docs/METHODOLOGY.md`.

## What changed

- `SGR_QS_TT`: quiescence probes the TT for a cutoff (null-window nodes only),
  tries a stored capture first, and stores its own fail-hard results at depth
  0. Its stores never evict a main-search entry for another position, and
  nothing is stored once the search is stopping.
- `SGR_PV_TTCUT`: principal-variation nodes, those with an open window, take no
  TT cutoff, so the line the engine plays is always searched.
- `SGR_PV_LMR`: principal-variation nodes reduce late moves one ply less.

All three default on.

## Checked before any games

| build | bench nodes |
|---|---|
| all three off | 1,681,306, identical to `sgr_v92rc.exe` |
| quiescence TT only | 1,629,683 |
| PV TT cutoffs only | 1,917,766 |
| PV LMR only | 2,195,979 |
| all three on | 2,390,227 (release build identical) |

Also checked: no compiler warnings, perft 4 = 197,281, SEE 9/9, repeat benches
identical, trace and datagen builds compile. Every mate claim on seven
positions was replayed to checkmate with python-chess, and no build made a
false one. On KQK the mated side reports the mate at depth 24 where v9.2-rc
did at 20; every build finds mate in 9 by depth 24. There were 80 searches
with legal moves and PVs at 1 MB and 256 MB hash, and speed was unchanged
(about 3.83M nps against 3.91M, inside run-to-run noise).

## Measurement

`tools/sprt.sh batch_a sprt_batch_a.exe 2390227 sgr_v92rc.exe 1681306`:
8+0.08, Hash 256, `8moves_v3.pgn`, [0, 5], capped at 5,000 games. Both builds
use the cosine seed-1 net, so the baseline is v9.2-rc exactly.

## Prediction

**+20 Elo, band +5 to +40. About 75% that H1 is accepted.**

Quiescence TT is standard and mostly saves work. The PV changes spend more
nodes on the line that decides the game, which is usually worth more than it
costs, but at a fixed clock they also mean less depth elsewhere. My last
prediction for a defect batch came in 40 Elo low, which is noted rather than
corrected for.

## Falsification

H0 accepted. Then split it: quiescence TT alone, then the two PV changes as a
pair.

## Result, 2026-09-25

Stopped by decision at 1,142 games, before a bound was crossed: **+16.4
±12.9**, LLR 1.09 of 2.94, W 288 L 234 D 620, 0 abnormal endings. Inside the
predicted band.
