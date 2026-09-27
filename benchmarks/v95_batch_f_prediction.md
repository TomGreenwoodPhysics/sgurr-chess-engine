# Batch F: move ordering, prediction registered before the run

Written 2026-09-27, before any games. Rule 7 of `docs/METHODOLOGY.md`.

## What changed

Five parts, each behind its own toggle and all on by default:

- `SGR_HIST_COLOUR`: one butterfly history table per side to move. Both
  sides used to share one.
- `SGR_HIST_GRAVITY`: a history update pulls the entry towards a bound of
  16,384 instead of adding to it without limit, so entries stay bounded and
  recent results outweigh old ones. The bonus is `200 * depth - 100`, capped
  at 2,000, where it was `depth * depth`.
- `SGR_CONTHIST_24`: continuation history from our own moves two and four
  plies back, as well as from the opponent's last move.
- `SGR_CAPHIST_FULL`: captures ordered by `16 * victim - attacker` plus
  capture history at full weight. Before, history could only nudge a capture
  within its victim's tier. Captures tried before a quiet cutoff are now
  penalised too.
- `SGR_PICKER2`: a new picker. It scores quiets only when it reaches them
  and runs SEE only on the capture it is about to return. It also sorts only
  the quiets likely to be searched. Its order is TT move, winning captures,
  killers, quiets with strong history, losing captures and underpromotions,
  then the other quiets.

History pruning and the history adjustment to reductions read the new, larger
history, so their settings had to move to a new scale:
`HistLmrDiv` 228 to 6,200 and `HistPruneMargin` 75 to 2,000.

## How the settings were chosen

The first calibration used bench, and bench misled. The base's history grows
without limit over a search, so how often it prunes and adjusts reductions
depends on how long the search runs. With history cleared before each of 400
positions searched to depth 12, the base pruned 5.6% of the quiets it tested
and changed 9% of reductions. In bench 14 those were 13.4% and 20%.

Games are what the old settings were tuned in, so the calibration replays
real games instead. 24 games from the v9.x calibration runs are replayed move
by move for one side, with history and the TT carried between moves as in a
match, at 400,000 nodes a move. There the base reduces 18.6% of reduced
quiets further and 14.4% less, and prunes 19.8% of the quiets it tests. The
new settings reduce 18.9% further and prune 20.0%. Bounded history cannot put
as many quiets in the reduce-less tail (6.7%), and no single divisor matches
both sides.

The new picker first tried promising quiets, those with history above -4,000,
before losing captures. Replays said that was worse. Moving losing captures
ahead of more quiets brought cutoffs sooner, flattening out once only quiets
with history above about 4,000 go first:

| quiets ahead of losing captures | mean position of the cutoff move |
|---|---|
| nearly all (history above -30,000) | 1.32 |
| history above -4,000 | 1.31 |
| above 0 | 1.29 |
| above 4,000 | 1.28 |
| above 16,000 (chosen) | 1.27 |
| none, as the old picker did | 1.28 |

A second, separate set of 24 games agreed (1.28 at -4,000, 1.26 from 4,000
up). The history bonus size and the victim's weight in capture order made no
difference to ordering over the ranges tried, so they keep their starting
values for the tune.

## Checked before any games

With all five toggles off the search is identical to v9.4: bench 1,847,491,
and 2,565,625 on the hand-crafted eval.

| | v9.4 | batch F |
|---|---|---|
| bench, network | 1,847,491 | 1,662,243 |
| bench, hand-crafted eval | 2,565,625 | 2,510,445 |
| cutoffs on the first move, replays | 85.43% | 86.53% |
| mean position of the cutoff move | 1.33 | 1.27 |
| mean depth at 400,000 nodes a move | 19.64 | 20.45 |
| same three on the second set of games | 86.21%, 1.31, 20.22 | 86.95%, 1.26, 20.85 |
| speed, bench 13, Hash 256 | | 1.2% slower |

The speed is the pinned paired comparison run in both orders on the final
binary (-1.4% ±0.7 and -0.9% ±0.5). The extra continuation history costs
more than the lazier picker saves.

Leaving one part out at a time, on the first set of games and before the
picker order above was settled:

| left out | first move | mean position | mean depth |
|---|---|---|---|
| nothing | 86.18% | 1.31 | 20.45 |
| colour | 86.16% | 1.31 | 20.11 |
| gravity | 84.77% | 1.36 | 19.69 |
| plies 2 and 4 | 86.09% | 1.32 | 19.85 |
| full capture history | 85.84% | 1.31 | 20.28 |
| new picker | 86.46% | 1.28 | 20.45 |

Gravity carries the batch: without it the ordering is worse than v9.4's. The
"plies 2 and 4" row is not a fair test, because its history has two terms
where the settings expect four, so it prunes and reduces far less. The new
picker's deficit came from the quiet threshold fixed above. With the chosen
threshold it orders as well as the old picker on both sets of games, and in
the replays it took about 9% less time per node than the old picker on the
same history.

A test build that aborts if the picker repeats, invents or loses a move ran
bench 12 and 14 on the network, bench 13 on the hand-crafted eval, 400
positions to depth 10 and every replay search, without a fault. No compiler
warnings in the release, dev, scalar, GCC, trace, datagen or measurement
builds; perft 4 = 197,281; SEE 9/9; scalar and vectorised benches identical;
the NNUE self-check and the UCI protocol tests pass.

The fingerprint is now the same under GCC and clang: 1,662,243 and 2,510,445
on both. The old picker's `std::sort` ordered tied moves differently in each
standard library (1,850,702 under GCC against 1,847,491), which is why CI has
only compared fingerprints within one toolchain. The new picker does its own
sorting.

## Measurement

`tools/sprt.sh batch_f sprt_batch_f.exe 1662243 sprt_f_base.exe 1847491`:
8+0.08, [0, 5], capped at 5,000 games, against the current best built from
2c550cb, whose search is v9.4's. Both binaries have the network compiled in.
It may be stopped under rule 9.

## Prediction

**+18 Elo, band +3 to +35. About 80% that it is positive.**

Every part is standard in strong engines, and the replays point the same
way: cutoffs come sooner and the search is most of a ply deeper at the same
node count. Depth at a fixed node count is not strength, though (§5), and
some of that depth may be reductions landing on different moves. What holds
the estimate down is calibration. Two settings were moved to a new scale by
matching rates, not by games, and the other new settings are starting values
for the tune.

## Falsification

A clearly negative result. Then bisect by halves with the toggles, gravity
and the new settings kept together, since neither makes sense without the
other. A result near zero would point at the calibration first: try the
divisor and margin a step either side before blaming the ordering.
