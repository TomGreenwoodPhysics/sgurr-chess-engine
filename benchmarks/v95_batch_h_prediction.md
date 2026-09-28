# Batch H: transposition table buckets with ageing, prediction registered before the run

Written 2026-09-27, before any games. Rule 7 of `docs/METHODOLOGY.md`.

## What was wrong

Each position had one slot, and a store for a different position always took
it. A depth-1 result could evict a depth-20 one, and nothing knew which search
an entry came from, so late in a game the table was full of entries from
earlier moves that were no easier to replace than new ones.

## What changed

- `SGR_TT_BUCKETS`: four 16-byte entries share a 64-byte bucket, one cache
  line, still with full 64-bit keys. A new position takes the bucket's least
  valuable entry. An entry for the same position is overwritten unless it is 7
  or more plies deeper, fresh and the new result is not exact. Quiescence still
  stores only where it costs nothing: its own entry, or an empty, quiescence or
  stale slot.
- `SGR_TT_AGE`: each entry records which search stored it, in the six spare
  bits of its flag byte. An entry loses 4 plies of worth for each search since,
  a probe that finds it renews it, and hashfull counts only the current search.

## How the settings were chosen

A table only matters under pressure, so the replays ran at 400,000 nodes a
move with a 16 MB table kept between moves, about the pressure a 256 MB table
meets at CCRL 40/15. The measure is the mean depth reached at that node count.

| 16 MB table | mean depth |
|---|---|
| one slot a position | 21.64 |
| buckets, no ageing | 21.89 |
| buckets and ageing, keep margin 3 | 21.97 |
| ageing weight 2 | 21.99 |
| ageing weight 8 | 21.87 |
| keep margin 6, chosen | 22.03 |
| keep margin 9 | 22.01 |
| keep margins 12 and 16 | 21.97 |

The buckets give most of the gain and ageing adds about 0.08 of a ply. A same
position's deeper entry is worth protecting, up to a margin of about 6. The
chosen table gained at every size tried, including the 256 MB of the SPRT,
because the old rule let any colliding store evict a deep entry:

| table | one slot | buckets and ageing |
|---|---|---|
| 4 MB | 21.71 | 21.99 |
| 16 MB | 21.64 | 22.03 |
| 64 MB | 21.59 | 21.94 |
| 256 MB | 21.72 | 22.00 |

Agreement with BlackCore's moves stayed within its noise throughout, as it
does for any change of this size (METHODOLOGY §12).

## Checked before any games

| | batch E | batch H |
|---|---|---|
| bench, network | 1,217,196 | 1,149,339 |
| bench, hand-crafted eval | 1,691,613 | 1,771,369 |
| bench to depth 16, 48 MB table | 10,384,164 | 9,320,613 |
| speed, bench 13, Hash 256 | | 1.8% slower |

The speed cost is the bucket scans; the refactor alone, run with the old
rules, measured +0.7 ±1.0. A probe renews an entry's search only when it has
changed, which saved 0.4 of a point. Buckets start on a cache line at every
size tried.

With the two toggles off the search is identical to batch E, and every
earlier identity still holds down to v9.4. GCC and clang bench the same. The
mate checks from batch D pass: both mates are confirmed at their claimed
length and every PV is legal. No compiler warnings in any build; perft 4 =
197,281; SEE 9/9; scalar and vectorised benches identical; the NNUE
self-check and the UCI protocol tests pass; no crash in 1,488 replay searches.

## Measurement

`tools/sprt.sh batch_h sprt_batch_h.exe 1149339 sprt_batch_e.exe 1217196`:
8+0.08, [0, 5], capped at 5,000 games, against batch E. Both binaries have the
network compiled in. It may be stopped under rule 9.

## Prediction

**+10 Elo, band -3 to +25. About 80% that it is positive.**

About a third of a ply at the same node count, for 1.8% in speed, and unlike
batch E the depth costs no accuracy: the table keeps more of what the search
has already proved. At 8+0.08 the table is under little pressure, so the gain
here should be the smallest this change makes. At 40/15 a move searches about
a hundred times more nodes into the same 256 MB, which is where it should
count most.

## Falsification

A clearly negative result. Then run with ageing off (`SGR_TT_AGE=0`), then
the old table, and suspect the same-position rule first: the old table never
let a shallower result replace a deeper entry, and this one does, up to six
plies deeper. `TtKeepDepth` at 0 brings it close to the old rule.

## Result, 2026-09-27

Stopped under rule 9 at 720 games, with its minimum raised to 500: **+14.5
±13.5**, W 121 L 92 D 483 over the 696 games of the last report, LLR 0.72 of
2.94. All 720 games ended normally. Inside the band, a little above the +10
predicted.

The interval did not clear zero at 500 or 600 games and cleared by one Elo at
700, so the size is soft. Batch H spent slightly less time, 179 ms a move
against 182, and its reported depth averaged 20.67 against 20.44: about a
quarter of a ply deeper, as the replays measured once the speed cost is taken
off. The release's pool run is the check on its size, and a long time control
is where it should matter more.

**Pool-F, 2026-09-28:** v9.5, batches F to H together, measured 3423.6 ±9.7
over 2,943 games, +101.0 ±15.1 over v9.4 in the same solve, against +114.3
summed in self-play.
