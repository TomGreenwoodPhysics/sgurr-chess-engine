# Batch G: correction history, prediction registered before the run

Written 2026-09-27, before any games. Rule 7 of `docs/METHODOLOGY.md`.

## The earlier attempt

Correction history was tried on 2026-09-23: one table keyed by the pawns,
measured at **-1.4 ±16.3** over 1,000 games on the SCReLU build that became
v9.1, and left off. That test could not have seen a gain of +10, and the code
had four faults:

- It learnt only half the error. It measured the error against the already
  corrected eval, then blended the entry towards that remainder, so an entry
  settled at half the true error.
- It learnt from every node's score as if exact. At a fail-low node the score
  is only a ceiling, often just alpha, so the corrections were biased.
- It capped a correction at 32 centipawns, 16 in effect after the halving.
- Quiescence stood pat on the raw eval, so the two searches disagreed.

## What changed

- `SGR_CORRHIST`, now on: five tables by side to move, keyed by the pawns,
  by each side's pieces with its king (two tables), by the minor pieces and by
  the major pieces. The correction is their weighted sum, up to 128
  centipawns a table.
- Every table moves by the same step towards the remaining error, so together
  they close the full error. The step grows with depth and is bounded by
  gravity, as history is.
- A node teaches the tables only when its score says something about the
  error: an exact score, or a bound on the far side of the eval. A capture as
  best move, check and mate scores teach nothing, as before.
- `SGR_CORR_QS`, on: quiescence stands pat on the corrected eval, as every
  pruning decision in the main search already does.
- The keys are kept up to date by make and unmake like the position's hash,
  and the entries are prefetched when the move is made.

## How the design was chosen

The first measure was the one the old code would have used: how far the eval
is from its own node's search score. It misled. With the corrections on, the
raw eval's error doubled, from 128 to 262 centipawns, because the search scores
themselves now came from corrected evals. A correction can look good on that
measure by agreeing with itself.

So the choice rests on an independent target. Every position of 48 replayed
games was searched to 4 million nodes by batch F, which has no correction.
Then each design replayed the same games at 400,000 nodes a move, and the
correction it had learnt from the game so far was applied to the static eval
of the next position. Error against the deep search, in centipawns:

| | set 1 | set 2 | error in its own search |
|---|---|---|---|
| no correction | 243.0 | 282.3 | 127.6 |
| five tables, weight 256 | 190.2 | | 113.6 |
| weight 384 | 179.9 | 191.9 | 111.2, 120.7 |
| weight 512, chosen | 169.2 | 183.0 | 112.7, 113.6 |
| weight 256 plus two tables keyed by the previous moves | 190.3 | | 119.1 |

Leaving out any one table at weight 512 made set 1 worse by 6 to 18: the
per-side tables by 18, the pawns by 12, the major and minor pieces by 7 and 6. The tables keyed by moves never helped and made the search
error worse, so they were dropped. Larger weights still improved the deep
comparison at 640 and 768, but the error in search stopped following, and
corrections averaged 140 centipawns and more. The learning rate made little
difference between half and twice the chosen one. Tables of 8,192 entries a
side were 1.9% faster than 16,384 but consistently about 4 centipawns worse in
search, on both sets.

## Found on the way

The first builds crashed in the replays with a stack overflow. The engine
object lives on the main thread's stack, which Windows sizes at 1 MB, and the
new tables took it from 54 KB to 388 KB. The tables now sit on the heap and
the object is back to 54 KB. Separately, `build.sh` now reserves 16 MB: the
search can recurse 128 plies with a 7 KB frame each, plus a frame for each
singular test on the way, which could overflow 1 MB in a deep search at long
time controls in any earlier version too.

## Checked before any games

| | batch F | batch G |
|---|---|---|
| bench, network | 1,662,243 | 1,659,605 |
| bench, hand-crafted eval | 2,510,445 | 2,696,345 |
| mean depth at 400,000 nodes, 3,036 replay searches | 20.65 | 20.70 |
| reverse futility, share of tested nodes pruned | 58.2% | 59.8% |
| null move tried, per 1,000 nodes | 92 | 97 |
| null move succeeded | 50.2% | 46.1% |
| speed, bench 13, Hash 256 | | 4.5% slower |

The speed cost is the table lookups, 6.1% before the prefetch. Keeping the
keys up to date costs under 1%, and the changed tree none.

With `SGR_CORRHIST=0` the search is identical to batch F, and with all batch
F and G toggles off it is identical to v9.4. The GCC build benches the same as
clang. A debug build asserted after every make and unmake, through perft,
bench and 1,488 replay searches, that the kept keys match keys computed from
scratch. No compiler warnings in any build; perft 4 = 197,281; SEE 9/9;
scalar and vectorised benches identical; the NNUE self-check and the UCI
protocol tests pass; no crash in 1,488 replay searches with the default 1 MB
stack.

## Measurement

`tools/sprt.sh batch_g sprt_batch_g.exe 1659605 sprt_batch_f.exe 1662243`:
8+0.08, [0, 5], capped at 5,000 games, against batch F. Both binaries have the
network compiled in. It may be stopped under rule 9.

## Prediction

**+12 Elo, band -5 to +30. About 75% that it is positive.**

The static eval now lands about 30% closer to a deep search, and every pruning
decision and every quiescence leaf reads it. Against that, the search runs
4.5% slower, and the weights were chosen by a proxy, not by games: larger
corrections kept improving the proxy past the point where I trusted them.
Batch F beat its prediction by 44 Elo, which says my estimates for this kind
of change run low, but this one also carries the most new risk.

## Falsification

A clearly negative result. Then halve the weights with the UCI options, then
turn off the correction in quiescence (`SGR_CORR_QS=0`), before doubting the
tables themselves.
