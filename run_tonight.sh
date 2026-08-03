#!/usr/bin/env bash
#
# Unattended overnight run: the v6.0 decomposition, plus the v8.1 speed
# measurement. Four jobs, ~8-10 hours, safe to interrupt at any point.
#
# Supersedes run_v60_decomp.sh (one script rather than two that drift apart).
#
# ---------------------------------------------------------------------------
# JOBS 1, 2, 4 -- the v6.0 decomposition, owed since 2026-07-16 (ROADMAP.md)
# ---------------------------------------------------------------------------
# The v6.0 package (improving flag + history-adjusted LMR + singular
# extensions) shipped as one SPRT: +57.3 +/-17.3 vs v5.0, undecomposed. Which
# of the three earned it has never been established.
#
# Node counts say the components are wildly unequal, but node counts cannot say
# which of them is worth Elo:
#
#   build              bench 13 nodes    vs baseline
#   baseline              13,614,729           --
#   -DSGR_IMPROVING=0     17,373,703       +27.6%   real pruning work
#   -DSGR_HISTLMR=0       13,796,251        +1.3%   near-inert
#   -DSGR_SINGULAR=0       7,351,781       -46.0%   singular costs +85% of tree
#
# READ THIS BEFORE INTERPRETING JOB 4. History-adjusted LMR is effectively
# INERT as shipped: history earns depth*depth per cutoff (169 at depth 13) and
# is halved every move, so hist_score / 400000 rounds to zero nearly always --
# setting HistLmrMax to 0, which disables the adjustment outright, changes the
# bench tree not at all. A null result there means "worth nothing AT THIS
# DIVISOR", not "the technique is worthless". Do not delete the code on it.
#
# ---------------------------------------------------------------------------
# JOB 3 -- v8.1 vs v8.0: what is speed actually worth?
# ---------------------------------------------------------------------------
# The v8.1 candidate is NODE-IDENTICAL and MOVE-IDENTICAL to the released
# v8.0 binary. Verified at fixed depth on three positions: same node counts,
# same scores, same moves. The only difference between them is that v8.1 is
# about 20% faster (PGO + ThinLTO, then nine node-identical optimisations).
#
# That makes this the cleanest controlled experiment available here, on a
# question the project has never answered. METHODOLOGY.md 5 flags the SIMD
# result as *inferred* -- converted to Elo through the ~70-per-doubling rule
# rather than measured in games -- and every speed gain since has been valued
# the same way, without ever being checked.
#
# Prediction from the rule: +18 to +19 Elo. If that holds, the rule is
# validated and future speed work rests on something measured. If it comes
# back at +5, speed work has been systematically overvalued for months.
#
# Deliberately NOT an SPRT. An SPRT answers "is it better?"; the question here
# is "by how much?", which wants a confidence interval. Early stopping would
# save nothing anyway, since the machine is idle either way.
#
# ---------------------------------------------------------------------------
# Predictions were registered BEFORE this ran:
#   benchmarks/v60_decomp_predictions.md
#   benchmarks/v81_speed_prediction.md
# Read them before the logs.
#
# Job order is deliberate: the two early-stopping SPRTs first, then the
# release-relevant measurement, then the least surprising job last. Waking up
# to a half-finished job 4 costs the least.
#
# Nothing here writes to the ledger. It produces logs and PGNs for review.
#
# Stop any time with Ctrl+C, or:  taskkill /IM fastchess.exe /F
# Partial results stay in the logs and the PGNs remain valid.

set -u

ROOT=/c/Coding/Sgurr
CPP="$ROOT/sgurr_cpp"
FC="$ROOT/benchmarks/tools/fastchess.exe"
BOOK="$ROOT/testing/book.epd"
NET="C:/Coding/Sgurr/nets/gen8.nnue"

STAMP=$(date +%Y-%m-%d_%H%M)
OUT="$ROOT/runs/tonight/$STAMP"

# ---- knobs -----------------------------------------------------------------
# -repeat plays a colour-balanced PAIR per round, so games = rounds * 2.
CONCURRENCY=7          # 8 physical cores; leave headroom so timing stays valid
TC=8+0.08              # the project's standard control (METHODOLOGY 1)
JOB1_ROUNDS=3000       # cap 6,000 games. SPRT, usually stops well before.
JOB2_ROUNDS=3000       # cap 6,000 games. SPRT, expected to stop fast.
JOB3_ROUNDS=2000       # fixed 4,000 games -> ~+/-10 Elo at 95%
JOB4_ROUNDS=2000       # fixed 4,000 games -> ~+/-10 Elo at 95%
# ----------------------------------------------------------------------------

mkdir -p "$OUT"
export SGR_EVALFILE="$NET"

# shellcheck source=testing/gauntlet_lib.sh
. "$ROOT/testing/gauntlet_lib.sh"

# Killing fastchess orphans its engines mid-search rather than stopping them --
# 13 were once left spinning at 83% CPU after a run had "ended". With four jobs
# back to back that matters twice over: leftovers from one job would corrupt the
# timing of the next, and every result after it.
ENGINE_PROCS="ab_base ab_nosing ab_noimp ab_nohlmr ab_v81 sgr_gen8"

# shellcheck disable=SC2086
trap 'echo; echo "interrupted -- stopping engines"; stop_gauntlet $ENGINE_PROCS; assert_engines_stopped $ENGINE_PROCS; exit 130' INT TERM

echo "overnight run  ->  $OUT"
date
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

ENGINES="ab_base ab_nosing ab_noimp ab_nohlmr ab_v81 sgr_gen8"

PY="$ROOT/.venv/Scripts/python.exe"; [ -f "$PY" ] || PY=python
CHECK=""
for e in $ENGINES; do CHECK="$CHECK $CPP/$e.exe"; done
# shellcheck disable=SC2086
if ! "$PY" "$ROOT/testing/engine_check.py" $CHECK; then
    echo "ABORT: engine pre-flight failed (see above)." >&2
    exit 1
fi

# None of these binaries has a baked-in net, so a missing SGR_EVALFILE would
# silently drop them to the hand-crafted eval -- ~430 Elo, one info line, no
# error. That failure went undetected across 44 released binaries once.
for e in $ENGINES; do
    if ! printf 'uci\nquit\n' | "$CPP/$e.exe" 2>&1 >/dev/null | grep -q "nnue: loaded"; then
        echo "ABORT: $e is NOT loading the net -- it would play as HCE." >&2
        exit 1
    fi
done
echo "preflight: all six engines start, load the net, machine idle"
echo

# Self-describing logs: record exactly what was tested.
{
    echo "run     : $STAMP"
    echo "commit  : $(cd "$ROOT" && git rev-parse HEAD)"
    echo "net     : $NET"
    echo "tc      : $TC   concurrency $CONCURRENCY"
    echo
    echo "bench 13 fingerprints:"
    for e in $ENGINES; do
        printf '  %-12s %s\n' "$e" "$("$CPP/$e.exe" bench 13 2>/dev/null | grep '^nodes')"
    done
    echo
    echo "ab_v81 vs sgr_gen8 share a fingerprint: same search, speed is the"
    echo "only variable in job 3."
} | tee "$OUT/manifest.txt"
echo

run_match() {   # name, new_exe, new_label, base_exe, base_label, rounds, sprt(0|1)
    local tag="$1" nexe="$2" nlab="$3" bexe="$4" blab="$5" rounds="$6" sprt="$7"
    local args=()
    [ "$sprt" = "1" ] && args=(-sprt elo0=0 elo1=5 alpha=0.05 beta=0.05)
    "$FC" \
        -engine cmd="$CPP/$nexe" name="$nlab" \
        -engine cmd="$CPP/$bexe" name="$blab" \
        -each tc="$TC" \
        -rounds "$rounds" -repeat \
        -concurrency "$CONCURRENCY" \
        -openings file="$BOOK" format=epd order=random \
        "${args[@]}" \
        -pgnout file="$OUT/$tag.pgn" \
        -ratinginterval 100 \
        -recover \
        2>&1 | tee "$OUT/$tag.log"

    # Between jobs, not just at the end. A job that leaves engines running would
    # load the machine for every job after it, and timed results under load are
    # invalid (METHODOLOGY 8 rule 5) -- silently so.
    # shellcheck disable=SC2086
    stop_gauntlet $ENGINE_PROCS
}

echo "=== JOB 1/4  no-singular vs baseline   SPRT, cap $((JOB1_ROUNDS*2)) games ==="
echo "    H1 = removing singular extensions is an IMPROVEMENT"
date
run_match job1_nosingular ab_nosing.exe no-singular ab_base.exe baseline "$JOB1_ROUNDS" 1
echo "job 1 finished"; date; echo

echo "=== JOB 2/4  no-improving vs baseline  SPRT, cap $((JOB2_ROUNDS*2)) games ==="
echo "    H1 = removing the improving flag is an IMPROVEMENT"
echo "    Expected to reject fast: removing it inflates the tree 27.6%."
date
run_match job2_noimproving ab_noimp.exe no-improving ab_base.exe baseline "$JOB2_ROUNDS" 1
echo "job 2 finished"; date; echo

echo "=== JOB 3/4  v8.1 vs v8.0              fixed $((JOB3_ROUNDS*2)) games ==="
echo "    Same search, ~20% faster. Measures what speed is actually worth."
echo "    Prediction from the 70-Elo-per-doubling rule: +18 to +19."
date
run_match job3_v81_vs_v80 ab_v81.exe Sgurr-v8.1 sgr_gen8.exe Sgurr-v8.0 "$JOB3_ROUNDS" 0
echo "job 3 finished"; date; echo

echo "=== JOB 4/4  no-histLMR vs baseline    fixed $((JOB4_ROUNDS*2)) games ==="
echo "    A null here means 'worth nothing at HistLmrDiv=400000', NOT that the"
echo "    technique is worthless. See the header."
date
run_match job4_nohistlmr ab_nohlmr.exe no-histlmr ab_base.exe baseline "$JOB4_ROUNDS" 0
echo "job 4 finished"; date; echo

# ---- summary ---------------------------------------------------------------
# shellcheck disable=SC2086
stop_gauntlet $ENGINE_PROCS
# shellcheck disable=SC2086
assert_engines_stopped $ENGINE_PROCS
echo

echo "=============================================================="
echo "RESULTS  ->  $OUT"
date
for j in job1_nosingular job2_noimproving job3_v81_vs_v80 job4_nohistlmr; do
    echo
    echo "--- $j ---"
    grep -E "Elo|SPRT|H0 was|H1 was|Games" "$OUT/$j.log" 2>/dev/null | tail -6
done
cat <<'EOF'

Reading these
  job 1 POSITIVE   singular costs more than it gives -> consider removing, but
                   note its three constants have never been tuned, so a bad
                   setting can lose where a good one would win
  job 1 NEGATIVE   singular earns its +85% tree cost -> keep, and make those
                   constants an early SPSA target
  job 2 NEGATIVE   the improving flag is load-bearing, as expected
  job 2 POSITIVE   genuinely surprising; re-read before believing it
  job 3            the headline. ~+18 validates the 70-Elo-per-doubling rule
                   and justifies releasing v8.1. Much lower means speed work
                   has been overvalued across several versions
  job 4 near 0     expected; means "at this divisor", not "worthless"

Predictions registered before the run:
  benchmarks/v60_decomp_predictions.md
  benchmarks/v81_speed_prediction.md
==============================================================
EOF
