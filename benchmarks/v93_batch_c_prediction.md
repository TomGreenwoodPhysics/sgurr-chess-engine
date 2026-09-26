# Batch C: time management rebuilt, prediction registered before the run

Written 2026-09-26, before any games. Rule 7 of `docs/METHODOLOGY.md`.

## Why

On pool-E, v9.3-rc1 finished its games with a median 5.3 s of its 10 s base
unused, where the nine anchors finished with 1.4 to 2.4 s. In moves 10 to 29,
where games are decided, Sgurr spent 0.22 to 0.26 s a move against the
anchors' 0.30 to 0.50. The old rule gave each move a thirtieth of the clock,
stopped starting iterations at 60% of that, and could never go past it.

## What changed

`SGR_TM2`, on by default, for clock searches only. Movetime, node and depth
searches are untouched, so datagen, the web app and bench do not change.

- **Budget.** The clock is spread over an estimate of the moves still to play:
  30 at move 1, falling by half a move per move played to a floor of 18. Half
  the increment is added, and a budget never exceeds 20% of the clock. In a
  model of the pool's own game lengths this matches the anchors' spending at
  each stage of the game and finishes with about 1.2 s left. The same model
  reproduces Sgurr's measured spending under the old rule to within 0.02 s a
  move.
- **When to stop.** No new iteration starts past 85% of the budget, scaled
  after each iteration by three things: best-move stability (the existing
  table); the share of root nodes spent under the best move (factor 0.5 plus
  1.5 times the share spent elsewhere, kept within 0.5 to 1.6); and the fall
  in score since the last iteration and since the previous move (100 cp
  doubles the time, kept within 0.8 to 1.6).
- **Hard limit.** Five budgets, and never more than 30% of the clock.
- **Cut-short iterations.** A move searched in full at the new depth that
  beat the window is kept, where the whole iteration used to be thrown away.
- **One legal move** is played after the first iteration.
- **movestogo** is honoured: the clock is spread over the moves until it is
  refilled.
- Every constant is a UCI option, for the tune.

The code is Sgurr's own. The ideas are standard; no other engine's code or
fitted formulas were copied.

## Checked before any games

- Bench 1,847,491 with the toggle on and off, identical to batch D, and the
  release build identical. No warnings in the dev, release, trace or datagen
  builds. Rules gate passes.
- Node- and depth-limited searches give identical output with the toggle on
  and off.
- Clocks from 1+0.01 to 120+0, 0.3 s with a 2 s increment, movestogo 40, 5
  and 1, and 25 ms, zero and negative clocks: the search never ran past its
  maximum and always returned a legal move.
- Over 40 opening positions at 10+0.1 the best move took a median 70% of the
  root nodes, a factor of 0.95, and the search spent 1.04 times its budget.
- With every search forced into the hard limit, all 40 moves were legal, and
  2 were better moves kept from the cut-short iteration.
- With one legal move, the move is played after one iteration.

## Measurement

1. A flag test first: fast self-play at 1+0.01, 2+0 and 40 moves in 5 s,
   checked for losses on time.
2. `tools/sprt.sh batch_c sprt_batch_c.exe 1847491 sprt_batch_d.exe 1847491`:
   8+0.08, [0, 5], against the current best.
3. Pool-F at 10+0.1, in the same solve as v9.3-rc1.

## Prediction

**+40 Elo, band +15 to +70. About 90% that it is positive.**

The middlegame gets roughly 1.6 times the thinking time it had, which by
Sgurr's own speed releases (+21 for 20% more speed, +31 for 15%) is worth a
lot. The endgame gets a little less than before, which gives some of it back,
and the stopping signals should add a few Elo on top. On the pool the gain
should hold up in full, as it did for the speed releases, since more
thinking time is not a change in behaviour that self-play can flatter.

## Falsification

Any loss on time, in the flag test or on the pool: the hard limit or the
reserve is too aggressive. A gain below +15 with its interval excluding +40:
the extra time is not converting, and the allocation and the stopping
signals are then tested apart, allocation first.
