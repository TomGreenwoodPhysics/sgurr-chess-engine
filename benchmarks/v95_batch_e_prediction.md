# Batch E: late move reductions, prediction registered before the run

Written 2026-09-27, before any games. Rule 7 of `docs/METHODOLOGY.md`.

## What changed

Five refinements to late move reductions, each behind its own toggle and all
on by default:

- `SGR_LMR_CUTNODE`: the search now tracks nodes expected to fail high. A
  child searched with a full window is a PV node, the first move of a cut node
  leads to an all node and the reverse, a later move's child is expected to
  fail high, and a re-search after a reduced search beat alpha, like a singular
  test, is expected to fail low. At an expected cut node a late move is
  reduced one ply more.
- `SGR_LMR_IMPROVING`: one ply more when the static eval is not improving.
- `SGR_LMR_CHECK`: one ply less for a move that gives check.
- `SGR_LMR_CAPTURES`: losing captures, which were never reduced, are reduced
  one ply less than a quiet in the same place. The picker says when a move
  came from its losing captures, so no extra SEE is needed.
- `SGR_LMR_RESEARCH`: after a reduced search beats alpha, the search again is
  a ply deeper if the move beat the best so far by 50 centipawns, a ply
  shallower if by less than 10, and skipped if that is no deeper than the
  reduced search already was.

## How it was checked

Every position of the 48 replay games was searched to 8 million nodes by
BlackCore 6.0, the strongest engine in the calibration pool at 3438 on CCRL
Blitz. Each design then replayed the games at 400,000 nodes a move, and the
measure is how often its move matched BlackCore's, paired on the same 3,036
positions.

First the measure was checked against changes with known results. It ranked
them in the right order but barely moved:

| version | agreement | against v9.4, paired | in games |
|---|---|---|---|
| v9.4 | 59.42% | | |
| batch F | 59.62% | +0.20 ±0.74 | +61.8 over v9.4 |
| batch G | 59.98% | +0.56 ±0.78 | +21.9 over batch F |
| batch E | 60.64% | +1.22 ±0.79 | |

A change worth 60 Elo moved it by a fifth of a point, so it can say that a
design does not choose worse moves, and little more. The five parts and their
sizes rest on that, on the depth each reaches, and on these refinements being
standard in strong engines. Leaving each part out of the batch, one at a time:

| left out | agreement | mean depth at 400,000 nodes |
|---|---|---|
| nothing | 60.64% | 21.69 |
| cut nodes | 59.26% | 21.60 |
| improving | 59.82% | 21.07 |
| checks | 58.93% | 21.71 |
| the re-search depth | 60.38% | 21.19 |
| losing captures | 60.34% | 21.65 |
| the whole batch (batch G) | 59.98% | 20.70 |

Doubling the cut-node or check adjustment, or reducing losing captures by the
full amount or two plies less, did no better, paired against the batch
(-1.25 ±0.77, -0.49 ±0.76, -0.26 ±0.78 and -0.53 ±0.76). Never searching
shallower did worse, -1.58 ±0.76. Quiescence fails hard, so a score just above
the best is the usual case and 82% of the re-searches go a ply shallower,
which for a move reduced by one ply means none at all. That saving is where
half a ply of the extra depth comes from.

## Checked before any games

| | batch G | batch E |
|---|---|---|
| bench, network | 1,659,605 | 1,217,196 |
| bench, hand-crafted eval | 2,696,345 | 1,691,613 |
| mean depth at 400,000 nodes, 3,036 replay searches | 20.70 | 21.69 |
| mean reduction of a reduced search | 2.18 plies | 2.68 plies |
| speed, bench 13, Hash 256 | | 3.2% faster |

The speed is the shape of the tree, not the code: the batch adds almost
nothing per node.

With the five toggles off the search is identical to batch G, with batch G's
toggles off as well it is identical to batch F, and with every toggle of both
batches and batch F off it is identical to v9.4. GCC and clang bench the same.
No compiler warnings in any build; perft 4 = 197,281; SEE 9/9; scalar and
vectorised benches identical; the NNUE self-check and the UCI protocol tests
pass; no crash in 1,488 replay searches.

## Measurement

`tools/sprt.sh batch_e sprt_batch_e.exe 1217196 sprt_batch_g.exe 1659605`:
8+0.08, [0, 5], capped at 5,000 games, against batch G. Both binaries have the
network compiled in. It may be stopped under rule 9.

## Prediction

**+15 Elo, band 0 to +35. About 75% that it is positive.**

The search reaches a ply deeper at the same node count and a few percent more
nodes a second, and the moves it chooses are no worse for it. Batch F gained a
similar depth through better ordering and measured +62. Depth from reducing
more is cheaper to come by than depth from ordering better, since each extra
reduction is a bet that the move does not matter, which is why the estimate
sits well below batch F's. All five parts, and their sizes, go to the tune
next.

## Falsification

A clearly negative result. Then switch the parts off by halves, with their UCI
options or, for losing captures, the toggle: the re-search depth and cut nodes
first, since they account for most of the extra depth.

## Result, 2026-09-27

Stopped under rule 9 at 516 games, with its minimum raised to 500 for this
run: **+16.1 ±16.0**, W 92 L 69 D 337 over the 498 games of the last report,
LLR 0.58 of 2.94. All 516 games ended normally. Close to the +15 predicted.

The interval cleared zero by 0.02 Elo, so this establishes that batch E is not
a regression and says little more about its size. The two sides spent the same
time, 177 ms a move against 178, and batch E's reported depth averaged 20.93
against 19.45: a ply and a half deeper, which matches the replays. The
release's pool run is the check on its size.
