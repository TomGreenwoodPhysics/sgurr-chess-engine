#!/usr/bin/env bash
#
# Run four overnight jobs for the v6.0 decomposition and v8.1 speed test.
# The script is safe to interrupt and writes only logs and PGNs.
#
# Jobs 1, 2, and 4 isolate improving, singular extensions, and history LMR.
# The v6.0 package gained 57.3 Elo, but the components were not tested alone.
# A null history-LMR result applies only to the current divisor because the
# shipped adjustment is nearly inert.
#
# Job 3 compares node-identical and move-identical v8.0 and v8.1 builds.
# The only intended difference is about 20% more speed in v8.1.
# The fixed match reports a confidence interval, not an SPRT verdict.
# The expected gain of 18 to 19 Elo was recorded before the run in
# benchmarks/v81_speed_prediction.md.
# Component predictions are in benchmarks/v60_decomp_predictions.md.
#
# Early-stopping jobs run first and the least important fixed match runs last.
# Stop with Ctrl+C or `taskkill /IM fastchess.exe /F`.
# Partial logs and PGNs remain valid.

set -u

# Resolve the repository root from this script so clones work anywhere.
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CPP="$ROOT/sgurr_cpp"
FC="$ROOT/benchmarks/tools/fastchess.exe"
BOOK="$ROOT/testing/book.epd"
# SGR_EVALFILE needs a Windows path because the engine cannot open MSYS paths.
NET=$(cygpath -m "$ROOT/nets/gen8.nnue")

STAMP=$(date +%Y-%m-%d_%H%M)
OUT="$ROOT/runs/tonight/$STAMP"

# Run settings
# Each repeat is a colour-balanced pair, so games equal rounds times two.
CONCURRENCY=7          # Leave one core free for stable timing
TC=8+0.08              # Standard project time control
JOB1_ROUNDS=3000       # Cap at 6,000 games with an earlier SPRT stop
JOB2_ROUNDS=3000       # Cap at 6,000 games with an earlier SPRT stop
JOB3_ROUNDS=2000       # Fixed 4,000 games for roughly +/-10 Elo at 95%
JOB4_ROUNDS=2000       # Fixed 4,000 games for roughly +/-10 Elo at 95%

mkdir -p "$OUT"
export SGR_EVALFILE="$NET"

# shellcheck source=testing/gauntlet_lib.sh
. "$ROOT/testing/gauntlet_lib.sh"

# Sweep orphaned engines so one job cannot load the machine for later jobs.
ENGINE_PROCS="ab_base ab_nosing ab_noimp ab_nohlmr ab_v81 sgr_gen8"

# shellcheck disable=SC2086
trap 'echo; echo "interrupted -- stopping engines"; stop_gauntlet $ENGINE_PROCS; assert_engines_stopped $ENGINE_PROCS; exit 130' INT TERM

echo "overnight run  ->  $OUT"
date
echo

# Preflight
# Timed games need an idle machine, and launch failures must not become forfeits.

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

# SGR_EVALFILE is required; otherwise these binaries fall back to the HCE.
for e in $ENGINES; do
    if ! printf 'uci\nquit\n' | "$CPP/$e.exe" 2>&1 >/dev/null | grep -q "nnue: loaded"; then
        echo "ABORT: $e is NOT loading the net -- it would play as HCE." >&2
        exit 1
    fi
done
echo "preflight: all six engines start, load the net, machine idle"
echo

# Record the exact inputs in each log.
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

    # Clean up between jobs to keep later timings valid.
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

# Summary
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
