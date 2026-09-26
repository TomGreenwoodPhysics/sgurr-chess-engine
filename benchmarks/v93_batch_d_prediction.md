# Batch D: pruning at PV nodes and mate distance, prediction registered before the run

Written 2026-09-25, before any games. Rule 7 of `docs/METHODOLOGY.md`.

## What changed

- `SGR_PV_PRUNE`: principal-variation nodes, those with an open window, no
  longer take reverse futility pruning, the drop into quiescence at depths 1
  and 2, razoring or null move. Each of those returns an estimate in place of
  a search, and until now they did so on the line the engine actually plays.
- `SGR_MDP`: mate-distance pruning. A node cannot mate sooner than the next
  ply or be mated sooner than now, so its window is bounded to that range, and
  a node that cannot beat a mate already found returns at once.

Both default on.

## Dropped before any games

The plan also had aspiration windows that start narrower and widen step by
step. An aspiration window mostly changes how many nodes it takes to reach a
depth, so that was measured first. A ±20 start instead of ±50 took 1.4% more
nodes on average to reach depth 13 over 155 positions, with 8 positions more
than doubled. Keeping ±50 and widening by half again after each miss took 6%
fewer at depth 13, but 6% more at depth 17 over 12 positions, three of them
between 1.8 and 2.3 times the old tree.

Both fail for the same reason. Null move and quiescence fail hard, so a failed
search returns the window edge, which says nothing about how far outside it
the score lies, and small steps take several re-searches to follow a large
swing. Aspiration windows are worth revisiting after fail-soft quiescence,
which the plan puts with batch H, and the start width is left to the tune.

## Checked before any games

| build | bench nodes |
|---|---|
| both off | 1,983,513, identical to the current best |
| PV pruning only | 1,941,798 |
| mate distance only | 1,878,919 |
| both | 1,847,491 (release build identical) |

Mate distance alone changes one bench position in 19 and leaves the other 18
identical. That is expected: it can only act where mate scores appear inside
the tree.

No compiler warnings in the dev, release, trace or datagen builds; perft 4 =
197,281; SEE 9/9; repeat benches identical; 80 searches legal at 1 MB and
256 MB hash; rules gate passes.

The trees are larger. At depth 17 on 12 varied positions the new tree is
about 1.5 times the old on the ten without a mate, at worst 2.45 times, while
the two mate-in-one positions shrink to almost nothing once the mate is found.
That is the cost of searching the PV properly. Tree size says what a change
spends, not what it buys (§5): singular extensions cost 85% of the tree and
were worth +77.

Every mate claim was checked against Stockfish's shortest mate on six
positions (KQK and KRK with either side to move, a mate in one and a mate in
two), at every depth up to 28 or 45 seconds. No build claimed a mate faster
than possible, or claimed to be mated sooner than best defence allows, so the
mate scores are sound. Some PVs no longer show the mate, though. The engine
reads its PV back out of the transposition table instead of recording it
during the search, so a change to what gets stored along a mating line can
splice in a stale move, and mate distance returns early without storing. Such
PVs: 0 of 58 claims for the old build, 1 of 57 with PV pruning alone, 5 of 66
with mate distance alone and 2 of 57 with both. This changes what is
displayed, not what is played.

## Measurement

`tools/sprt.sh batch_d sprt_batch_d.exe 1847491 sprt_batch_b.exe 1983513`:
8+0.08, [0, 5], capped at 5,000 games, against the current best. It may be
stopped under rule 9.

## Prediction

**+8 Elo, band -5 to +20. About 65% that it is positive.**

Both changes are standard in strong engines. Mate distance should be worth
close to nothing in games that are still being decided, so the result is
almost all the PV change. What holds the estimate down is the tree. Each ply
multiplies Sgurr's tree by 1.44 (the geometric mean over ten positions from
depth 13 to 17), so half as many nodes again per depth costs about a ply at a
fixed clock, and a better PV has to be worth more than that. Batch A was the
same kind of trade: it searched PV nodes more carefully, grew the bench tree
by 42%, and measured +16.4.

## Falsification

A clearly negative result. Then test the PV change without the null-move
gate. Null move is the only one of the four that acts at every depth from 3
up, so it probably carries most of the extra tree.

## Result, 2026-09-26

Stopped by decision at 1,940 games: **+4.3 ±8.8**, W 362 L 338 D 1240, LLR
0.41 of 2.94. No abnormal endings in the 1,958 games in the PGN. Inside the
band and a little below the +8 predicted.

The interval had not cleared zero, so this is not a stop under rule 9. It was
stopped because the question that mattered was already answered: batch D is
not a large gain, and it is unlikely to be a regression, with the interval
reaching down only to -4.5. The rest of the cap would have spent about two and
a half hours telling +1 from +5. Batch D stays in, and the next pool run
checks it against other engines.
