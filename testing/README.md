# Ruk engine match / SPRT testing

## Simplest: a plain match between two engines (`match.py`)

Point it at two compiled binaries, play N games, get a result. Either edit the
two paths at the top of `match.py` and run it, or pass them on the command line:

    python3 match.py ./engineA ./engineB --games 100 --tc 8+0.08 --concurrency 6

- `--tc 8+0.08` = 8s + 0.08s/move; or `--tc mt=0.1` for a flat 0.1s per move.
- `--book book.epd` gives opening variety (without it, two deterministic engines
  replay the same game); `--book ""` forces the start position.
- Prints running and final W/D/L, score%, and an Elo estimate with error bars,
  from engine A's perspective. No early stopping -- it just plays all N games.

That is all most day-to-day testing needs. The SPRT runner below is optional, for
when you want the test to stop automatically once a result is statistically
settled.

---


Tools for measuring whether a change to Ruk is a real improvement, using a
Sequential Probability Ratio Test (SPRT) instead of fixed-length matches. SPRT
plays only as many games as needed: it stops early once the evidence is
conclusive either way.

## The core workflow: new-vs-old

Every patch is tested against the *immediately previous* version, not against a
fixed opponent. Keep your last accepted binary as the baseline:

1. Build the current `main` as `ruk_base` and keep it.
2. Make one change. Build it as `ruk_new`.
3. Run SPRT `ruk_new` vs `ruk_base`.
4. If it passes (H1), `ruk_new` becomes the new `ruk_base`. If it fails (H0),
   discard the change. Test one idea at a time.

This is how engines climb: many small, individually-verified gains.

## Reading the result

- **H1 ACCEPTED (pass)** — the change is an improvement (by more than `elo0`).
- **H0 ACCEPTED (fail)** — the change is not an improvement; revert it.
- `elo0`/`elo1` are the hypothesis bounds. The classic non-regression test is
  `elo0=0 elo1=5`: H0 = "0 Elo or worse", H1 = "at least +5 Elo". `alpha=beta=0.05`
  gives 5% error each way, so the LLR runs between -2.94 and +2.94.
- For a big expected jump (e.g. NNUE) widen to `elo0=0 elo1=10` to resolve faster.

## Two ways to run it

### A) The included Python harness (zero dependencies)

Works immediately with just Python 3 — no install. Good for quick iteration and
as a dependency-free fallback.

    python3 sprt.py --new ./ruk_new --base ./ruk_base \
        --tc 8+0.08 --book book.epd --concurrency 8 \
        --elo0 0 --elo1 5 --alpha 0.05 --beta 0.05

Flags: `--tc base+inc` seconds (e.g. `8+0.08`); `--concurrency` parallel games;
`--rounds` cycles the book; `--min-games` guards tiny-sample variance (default 16).
The harness tracks every game independently and **checks every engine move for
legality**, so a movegen bug surfaces immediately as a forfeit + warning.

### B) fastchess (recommended for volume) — see `fastchess.md`

`fastchess`/`cutechess-cli` are the battle-tested C++ tournament managers the
engine community uses. Much higher throughput and a pentanomial SPRT. Use the
same book and bounds. `fastchess.md` has the exact command.

## The opening book

`book.epd` is a starter book of balanced positions (each ~8 plies in, filtered
to within ±70 cp by Ruk's own eval, so neither side starts ahead). Regenerate or
enlarge it any time:

    python3 book_gen.py --engine ./ruk_new --out book.epd --count 1000

For serious testing, switch to a large curated book such as UHO (unbalanced human
openings) or a Pohl book — a few thousand sharp-but-fair positions reduce
draw rates and variance.

## Time control

Test at the TC you care about. Fast TC (8+0.08) gives many games quickly and is
standard for iteration; verify big changes at a slower TC too, since some gains
(deeper search, time management) scale with thinking time. Avoid extremely fast
TC with the Python harness — its per-move overhead can cause spurious time
forfeits below ~1s base.

## Files

- `match.py`      — plain two-engine match (start here)
- `sprt.py`       — optional SPRT runner (auto-stops on a decision)
- `chesslite.py`  — perft-verified board/movegen used to arbitrate games
- `book_gen.py`   — balanced-book generator (uses the engine's eval)
- `book.epd`      — starter book (150 balanced positions)
- `fastchess.md`  — fastchess / cutechess-cli setup and command

## Scaling up later: OpenBench

When you want to test many patches in parallel across machines, OpenBench
(github.com/AndyGrant/OpenBench) is the distributed framework most engines use —
a web dashboard plus workers that run fastchess. It needs the engine to print a
`bench` node count (a fixed-position node total) for sanity-checking builds;
worth adding to Ruk when you get there.