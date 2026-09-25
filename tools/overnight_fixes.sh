#!/usr/bin/env bash
# Overnight 2026-09-25: SPRT the null-move eval gate and TT move keeping against
# v9.1, then carry on the pool-E v9.1 baseline.
# Prediction: benchmarks/v92_fixes_prediction.md.
#
#   tools/overnight_fixes.sh          run (a finished SPRT is not replayed)
#   tools/overnight_fixes.sh --stop   stop everything, keep every finished game
#
# Results land in runs/fixes/summary.txt and runs/pool_e/SUMMARY.txt.
set -u

ROOT=/c/coding/Sgurr
CPP=$ROOT/sgurr_cpp
RUN=$ROOT/runs/fixes
LOG=$RUN/driver.log
FC=$ROOT/benchmarks/tools/fastchess.exe
BOOK=$ROOT/testing/8moves_v3.pgn
NEW=sprt_fixes.exe
BASE=sprt_v91_ref.exe
ROUNDS=4000            # 8,000-game cap

mkdir -p "$RUN"
unset SGR_EVALFILE
say() { echo "[$(date '+%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
die() { say "STOP: $*"; say "=== stopped, needs a human ==="; exit 1; }

procs_matching() {
    local me
    me=$(cat /proc/$$/winpid 2>/dev/null || echo 0)
    powershell -NoProfile -Command "(Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -like '*$1*' -and \$_.CommandLine -notlike '*--stop*' -and \$_.ProcessId -ne $me -and \$_.Name -ne 'powershell.exe' } | Select-Object -Expand ProcessId) -join ' '" 2>/dev/null | tr -d '\r'
}

if [ "${1:-}" = "--stop" ]; then
    for pid in $(procs_matching overnight_fixes.sh); do
        taskkill //PID "$pid" //T //F >/dev/null 2>&1
    done
    taskkill //IM fastchess.exe //F >/dev/null 2>&1
    taskkill //IM $NEW //F >/dev/null 2>&1
    taskkill //IM $BASE //F >/dev/null 2>&1
    "$ROOT/tools/calibrate_pool_e.sh" --stop
    say "stopped by --stop"
    exit 0
fi

say "=== overnight: fixes SPRT, then the pool-E baseline ==="
busy=$(powershell -NoProfile -Command "(Get-Process fastchess,datagen -ErrorAction SilentlyContinue | Measure-Object).Count" 2>/dev/null | tr -d '\r ')
[ "${busy:-0}" = "0" ] || die "$busy fastchess/datagen process(es) already running"
[ -z "$(procs_matching calibrate_pool_e.sh)" ] || die "a pool-E calibration is already running"
[ -z "$(procs_matching spsa.py)" ] || die "an SPSA tune is running"

# Both sides must be the builds the prediction describes.
[ "$("$CPP/$BASE" bench 2>/dev/null | grep -a '^nodes' | awk '{print $2}')" = 2199384 ] || die "$BASE is not the v9.1 reference"
[ "$("$CPP/$NEW" bench 2>/dev/null | grep -a '^nodes' | awk '{print $2}')" = 1551144 ] || die "$NEW is not the candidate that was checked"
for e in $NEW $BASE; do
    printf 'uci\nquit\n' | "$CPP/$e" 2>&1 | grep -aq 'nnue: loaded .*gen9_screlu.nnue' || die "$e does not load gen9_screlu.nnue"
done

if grep -aq 'Finished match' "$RUN/sprt.txt" 2>/dev/null; then
    say "SPRT already finished, not replaying it"
else
    say "SPRT: fixes vs v9.1, 8+0.08, [0, 5], up to $((ROUNDS * 2)) games"
    "$FC" -engine cmd="$CPP/$NEW" name=fixes -engine cmd="$CPP/$BASE" name=v91 \
        -each tc=8+0.08 option.Hash=256 -rounds $ROUNDS -repeat -concurrency 7 \
        -openings file="$BOOK" format=pgn order=random -recover \
        -sprt elo0=0 elo1=5 alpha=0.05 beta=0.05 \
        -pgnout file="$(cygpath -m "$RUN/sprt.pgn")" \
        >"$RUN/sprt.txt" 2>&1
    taskkill //IM $NEW //F >/dev/null 2>&1
    taskkill //IM $BASE //F >/dev/null 2>&1
fi

if   grep -aq 'H1 was accepted' "$RUN/sprt.txt"; then v=H1
elif grep -aq 'H0 was accepted' "$RUN/sprt.txt"; then v=H0
else v="no decision"; fi
python "$ROOT/testing/pgn_endings.py" "$RUN/sprt.pgn" | tr -d '\r' > "$RUN/endings.txt"
{
    echo "Fixes (SGR_NMP_EVAL + SGR_TTMOVE_KEEP) vs v9.1, 8+0.08, [0, 5]: $v"
    echo "Prediction: benchmarks/v92_fixes_prediction.md (+10, band 0 to +25)"
    echo "  $(grep -aE '^Elo:' "$RUN/sprt.txt" | tail -1)"
    echo "  $(grep -aE '^Games:' "$RUN/sprt.txt" | tail -1)"
    echo "  endings: $(head -1 "$RUN/endings.txt" | awk '{print $1" games, "$2" abnormal"}')"
    tail -n +2 "$RUN/endings.txt" | head -10
} > "$RUN/summary.txt"
tee -a "$LOG" < "$RUN/summary.txt"

say "handing over to the pool-E v9.1 baseline"
"$ROOT/tools/calibrate_pool_e.sh" >>"$LOG" 2>&1
say "=== overnight done ==="
