# Sgurr engine match / SPRT testing

## Plain match between two engines (`match.py`)

Point it at two compiled binaries, play N games, get a result. Either edit the
two paths at the top of `match.py` and run it, or pass them on the command
line:

    python3 match.py ./engineA ./engineB --games 100 --tc 8+0.08 --concurrency 6

- `--tc 8+0.08` = 8s + 0.08s/move; or `--tc mt=0.1` for a flat 0.1s per move.
- `--book book.epd` gives opening variety (without it, two deterministic
  engines replay the same game); `--book ""` forces the start position.
- Prints running and final W/D/L, score%, and an Elo estimate with error bars,
  from engine A's perspective. No early stopping; it plays all N games.

This covers most day-to-day testing. The SPRT runner below stops automatically
once a result is statistically settled.

## SPRT: new-vs-old

Each patch is tested against the previous accepted version, not a fixed
opponent:

1. Build the current `main` as `sgr_base` and keep it.
2. Make one change. Build it as `sgr_new`.
3. Run SPRT `sgr_new` vs `sgr_base`.
4. If it passes (H1), `sgr_new` becomes the new `sgr_base`. If it fails (H0),
   discard the change. One idea per test.

### Reading the result

- **H1 ACCEPTED (pass)**: the change is an improvement (by more than `elo0`).
- **H0 ACCEPTED (fail)**: the change is not an improvement; revert it.
- `elo0`/`elo1` are the hypothesis bounds. The standard non-regression test is
  `elo0=0 elo1=5`: H0 = "0 Elo or worse", H1 = "at least +5 Elo".
  `alpha=beta=0.05` gives 5% error each way, so the LLR runs between -2.94 and
  +2.94.
- For a large expected jump (e.g. NNUE), widening to `elo0=0 elo1=10` resolves
  faster.

### A) The included Python harness

No dependencies beyond Python 3:

    python3 sprt.py --new ./sgr_new --base ./sgr_base \
        --tc 8+0.08 --book book.epd --concurrency 8 \
        --elo0 0 --elo1 5 --alpha 0.05 --beta 0.05

Flags: `--tc base+inc` seconds (e.g. `8+0.08`); `--concurrency` parallel games;
`--rounds` cycles the book; `--min-games` guards against tiny-sample variance
(default 16). The harness tracks every game independently and checks every
engine move for legality, so a movegen bug surfaces immediately as a forfeit
plus a warning.

### B) fastchess (higher volume)

`fastchess`/`cutechess-cli` are the standard C++ tournament managers: much
higher throughput and a pentanomial SPRT. Use the same book and bounds.
`fastchess.md` has the exact command.

## The opening book

`book.epd` is a starter book of balanced positions (each ~8 plies in, filtered
to within +/-70 cp by Sgurr's own eval). Regenerate or enlarge it with:

    python3 book_gen.py --engine ./sgr_new --out book.epd --count 1000

For serious testing, a large curated book such as UHO (unbalanced human
openings) or a Pohl book reduces draw rates and variance.

## Time control

Test at the TC that matters. Fast TC (8+0.08) gives many games quickly and is
standard for iteration; big changes are worth verifying at a slower TC too,
since some gains (deeper search, time management) scale with thinking time.
Avoid extremely fast TC with the Python harness: its per-move overhead can
cause spurious time forfeits below ~1s base.

## Files

- `match.py`      plain two-engine match
- `sprt.py`       SPRT runner (stops on a decision)
- `chesslite.py`  perft-verified board/movegen used to arbitrate games
- `book_gen.py`   balanced-book generator (uses the engine's eval)
- `book.epd`      starter book (150 balanced positions)
- `fastchess.md`  fastchess / cutechess-cli setup and command
