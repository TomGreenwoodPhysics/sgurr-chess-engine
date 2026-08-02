#!/usr/bin/env bash
#
# v6.0 leave-one-out decomposition -- owed since 2026-07-16 (see ROADMAP.md).
#
# The v6.0 package (improving flag + history-adjusted LMR + singular extensions)
# shipped as one SPRT: +57.3 +/-17.3 vs v5.0, undecomposed. Nobody knows which
# of the three earned it.
#
# The 2026-08-02 bench decomposition made this worth measuring properly:
#
#   build              bench 13 nodes    vs baseline
#   baseline              13,614,729           --
#   -DSGR_IMPROVING=0     17,373,703       +27.6%   (doing real pruning work)
#   -DSGR_HISTLMR=0       13,796,251        +1.3%   (near-inert -- a passenger?)
#   -DSGR_SINGULAR=0       7,351,781       -46.0%   (singular costs +85% of tree)
#
# Three questions follow, and none can be answered by node counts:
#
#   JOB 1  Singular extensions nearly DOUBLE the tree. At a fixed time control
#          that depth is paid for out of the clock. Do they earn it back? If
#          removal measures POSITIVE, the feature is costing more than it gives
#          and deleting it is both a simplification and an Elo gain.
#
#   JOB 2  The improving flag inflates the tree 27.6% when removed, and feeds
#          two other mechanisms (RFP's margin, LMP's quiet budget). Expected to
#          be clearly load-bearing; this confirms it rather than assuming it.
#
#   JOB 3  History-adjusted LMR moves the tree 1.3%. Is it worth anything at
#          all? This one wants a tight confidence interval around zero rather
#          than an SPRT verdict, so it runs a fixed number of games.
#
#          NOTE, and it matters for reading the result: this feature is
#          effectively INERT as shipped. History earns depth*depth per cutoff
#          (169 at depth 13) and is halved every move, so hist_score / 400000
#          rounds to zero nearly always -- setting HistLmrMax to 0, which
#          disables the adjustment outright, changes the bench tree not at all.
#          A null result here therefore means "worth nothing AT THIS DIVISOR",
#          not "the technique is worthless". Do not delete the code on it.
#
# Predictions were registered BEFORE this ran, in
# benchmarks/v60_decomp_predictions.md. Read them before the logs.
#
# Jobs are ordered most-informative first, so stopping early still leaves the
# valuable answers in hand. Job 3 is the long fixed-length one and the least
# surprising; Ctrl+C after job 2 loses the least.
#
# All three are SEARCH changes on a FIXED net, so they carry no training-seed
# variance (METHODOLOGY.md 2) -- match noise is the only error, and games
# genuinely shrink it.
#
# Nothing here writes to the ledger. It produces logs and PGNs for review.
#
# Stop at any time with Ctrl+C, or:  taskkill /IM fastchess.exe /F
# Partial results stay in the logs and the PGNs remain valid.

set -u

ROOT=/c/Coding/Sgurr
CPP="$ROOT/sgurr_cpp"
FC="$ROOT/benchmarks/tools/fastchess.exe"
BOOK="$ROOT/testing/book.epd"
NET="C:/Coding/Sgurr/nets/gen8.nnue"

STAMP=$(date +%Y-%m-%d_%H%M)
OUT="$ROOT/runs/v60_decomp/$STAMP"

# ---- knobs -----------------------------------------------------------------
# -repeat plays a colour-balanced PAIR per round, so games = rounds * 2.
CONCURRENCY=7          # 8 physical cores; leave headroom so timing stays valid
TC=8+0.08              # the project's standard SPRT control (METHODOLOGY 1)
JOB1_ROUNDS=3000       # cap: 6,000 games. SPRT will usually stop well before.
JOB2_ROUNDS=3000       # cap: 6,000 games. Expected to stop fast (H0).
JOB3_ROUNDS=3000       # fixed: 6,000 games -> ~+/-8 Elo at 95%
# ----------------------------------------------------------------------------

mkdir -p "$OUT"
export SGR_EVALFILE="$NET"

echo "v6.0 decomposition  ->  $OUT"
echo

# ---- preflight -------------------------------------------------------------
# METHODOLOGY 8 rule 5: timed games are only valid on an idle machine. And a
# binary that cannot spawn does not crash a match -- it forfeits every game and
# still produces a complete, plausible result.

busy=$(powershell -c "(Get-Process datagen,fastchess -ErrorAction SilentlyContinue | Measure-Object).Count" 2>/dev/null | tr -d '\r')
if [ "${busy:-0}" != "0" ]; then
    echo "ABORT: $busy datagen/fastchess process(es) already running." >&2
    echo "Timed game results under CPU load are invalid." >&2
    exit 1
fi

PY="$ROOT/.venv/Scripts/python.exe"; [ -f "$PY" ] || PY=python
if ! "$PY" "$ROOT/testing/engine_check.py" \
        "$CPP/ab_base.exe" "$CPP/ab_nosing.exe" "$CPP/ab_nohlmr.exe" "$CPP/ab_noimp.exe"; then
    echo "ABORT: engine pre-flight failed (see above)." >&2
    exit 1
fi

# The binaries have no baked-in net, so a missing SGR_EVALFILE would silently
# drop them to the hand-crafted eval -- ~430 Elo, one info line, no error.
# That exact failure went undetected across 44 released binaries once.
for e in ab_base ab_nosing ab_nohlmr ab_noimp; do
    if ! printf 'uci\nquit\n' | "$CPP/$e.exe" 2>&1 >/dev/null | grep -q "nnue: loaded"; then
        echo "ABORT: $e is NOT loading the net -- it would play as HCE." >&2
        exit 1
    fi
done
echo "preflight: all four engines start, load the net, machine idle"

# Record which binaries were tested, so the logs are self-describing.
{
    echo "run          : $STAMP"
    echo "commit       : $(cd "$ROOT" && git rev-parse HEAD)"
    echo "net          : $NET"
    echo "tc           : $TC   concurrency $CONCURRENCY"
    echo
    echo "bench 13 fingerprints (proves each binary differs by ONE flag):"
    for e in ab_base ab_nosing ab_nohlmr ab_noimp; do
        printf '  %-10s %s\n' "$e" "$("$CPP/$e.exe" bench 13 2>/dev/null | grep '^nodes')"
    done
} | tee "$OUT/manifest.txt"
echo

# ---- job 1: singular extensions --------------------------------------------
echo "=== JOB 1/3  no-singular vs baseline  (SPRT, cap $((JOB1_ROUNDS * 2)) games) ==="
echo "    H1 = removing singular extensions is an IMPROVEMENT"
date
"$FC" \
    -engine cmd="$CPP/ab_nosing.exe" name=no-singular \
    -engine cmd="$CPP/ab_base.exe"   name=baseline \
    -each tc="$TC" \
    -rounds "$JOB1_ROUNDS" -repeat \
    -concurrency "$CONCURRENCY" \
    -openings file="$BOOK" format=epd order=random \
    -sprt elo0=0 elo1=5 alpha=0.05 beta=0.05 \
    -pgnout file="$OUT/job1_nosingular.pgn" \
    -ratinginterval 100 \
    -recover \
    2>&1 | tee "$OUT/job1_nosingular.log"
echo "job 1 finished"; date
echo

# ---- job 2: the improving flag ---------------------------------------------
echo "=== JOB 2/3  no-improving vs baseline  (SPRT, cap $((JOB2_ROUNDS * 2)) games) ==="
echo "    H1 = removing the improving flag is an IMPROVEMENT"
echo "    Expected to reject fast: removing it inflates the tree 27.6%."
date
"$FC" \
    -engine cmd="$CPP/ab_noimp.exe" name=no-improving \
    -engine cmd="$CPP/ab_base.exe"  name=baseline \
    -each tc="$TC" \
    -rounds "$JOB2_ROUNDS" -repeat \
    -concurrency "$CONCURRENCY" \
    -openings file="$BOOK" format=epd order=random \
    -sprt elo0=0 elo1=5 alpha=0.05 beta=0.05 \
    -pgnout file="$OUT/job2_noimproving.pgn" \
    -ratinginterval 100 \
    -recover \
    2>&1 | tee "$OUT/job2_noimproving.log"
echo "job 2 finished"; date
echo

# ---- job 3: history-adjusted LMR -------------------------------------------
echo "=== JOB 3/3  no-histLMR vs baseline  (fixed $((JOB3_ROUNDS * 2)) games) ==="
echo "    No SPRT: the question is 'is this worth ~nothing?', which wants a"
echo "    confidence interval, not an accept/reject verdict."
date
"$FC" \
    -engine cmd="$CPP/ab_nohlmr.exe" name=no-histlmr \
    -engine cmd="$CPP/ab_base.exe"   name=baseline \
    -each tc="$TC" \
    -rounds "$JOB3_ROUNDS" -repeat \
    -concurrency "$CONCURRENCY" \
    -openings file="$BOOK" format=epd order=random \
    -pgnout file="$OUT/job3_nohistlmr.pgn" \
    -ratinginterval 100 \
    -recover \
    2>&1 | tee "$OUT/job3_nohistlmr.log"
echo "job 3 finished"; date
echo

# ---- summary ---------------------------------------------------------------
echo "=============================================================="
echo "RESULTS  ->  $OUT"
echo
echo "--- job 1: removing singular extensions ---"
grep -E "Elo|SPRT|H0|H1|Games" "$OUT/job1_nosingular.log" | tail -6
echo
echo "--- job 2: removing the improving flag ---"
grep -E "Elo|SPRT|H0|H1|Games" "$OUT/job2_noimproving.log" | tail -6
echo
echo "--- job 3: removing history-adjusted LMR ---"
grep -E "Elo|Games" "$OUT/job3_nohistlmr.log" | tail -6
echo
echo "Reading these:"
echo "  job 1 POSITIVE  -> singular costs more than it gives; consider deleting"
echo "  job 1 NEGATIVE  -> singular earns its +85% tree cost; keep, and make its"
echo "                     three hand-set constants an early SPSA target"
echo "  job 2 NEGATIVE  -> the improving flag is load-bearing, as expected"
echo "  job 2 POSITIVE  -> genuinely surprising; re-read before believing it"
echo "  job 3 CI near 0 -> means 'worth nothing AT HistLmrDiv=400000', NOT that"
echo "                     the technique is worthless. The parameter is inert as"
echo "                     shipped (see the header). Retune it, do not delete it."
echo
echo "Predictions registered before this run: benchmarks/v60_decomp_predictions.md"
echo "=============================================================="
