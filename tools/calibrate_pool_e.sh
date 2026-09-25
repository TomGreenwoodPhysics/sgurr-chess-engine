#!/usr/bin/env bash
# Calibrate v9.1 on pool-2026-09-E to about +/-12, as the baseline later releases
# are compared against, with the binary and net it was calibrated with on pool-D.
# Why +/-12 and not tighter, and why v9.0 was dropped: benchmarks/pool_e_prediction.md.
#
#   tools/calibrate_pool_e.sh          start, or carry on after a pause
#   tools/calibrate_pool_e.sh --stop   pause: stop everything, keep every finished game
#
# A version that already has games carries on with a new opening seed, so no
# opening is replayed, and Ordo solves all of its games together. Results land
# in runs/pool_e/SUMMARY.txt.
set -u

ROOT=/c/coding/Sgurr
RUN=$ROOT/runs/pool_e
LOG=$RUN/driver.log
GAMES=$ROOT/benchmarks/games/pool-2026-09-E
TARGET=12         # Ordo +/- per version: enough to confirm a gain carries over
ROUNDS=230        # 18 games a round, so at most 4,140 games per version per run
SEED=1

mkdir -p "$RUN"
unset SGR_EVALFILE
say() { echo "[$(date '+%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
die() { say "STOP: $*"; say "=== stopped, needs a human ==="; exit 1; }

POOL_PROCS="sprt_bundle bit-genie-9 bitfox-2.5.0 monolith-3 drofa-4.1.0 mantissa-3.7.2 nalwald-19 counter-5.5 Lynx.Cli frozenight-6.0.0 ordo"

# Windows processes whose command line contains $1, minus this shell and any
# shell running --stop.
procs_matching() {
    local me
    me=$(cat /proc/$$/winpid 2>/dev/null || echo 0)
    powershell -NoProfile -Command "(Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -like '*$1*' -and \$_.CommandLine -notlike '*--stop*' -and \$_.ProcessId -ne $me -and \$_.Name -ne 'powershell.exe' } | Select-Object -Expand ProcessId) -join ' '" 2>/dev/null | tr -d '\r'
}

if [ "${1:-}" = "--stop" ]; then
    for pid in $(procs_matching calibrate_pool_e.sh) $(procs_matching run_calibrate.sh); do
        taskkill //PID "$pid" //T //F >/dev/null 2>&1
    done
    . "$ROOT/testing/gauntlet_lib.sh"
    # shellcheck disable=SC2086
    stop_gauntlet $POOL_PROCS
    # shellcheck disable=SC2086
    assert_engines_stopped $POOL_PROCS
    say "paused by --stop; $(cat "$GAMES"/calib-*.pgn 2>/dev/null | grep -c '^\[Event') pool-E games kept. Relaunch to carry on."
    exit 0
fi

calibrate() {  # version exe net
    if [ -f "$RUN/done_$1" ]; then
        say "$1 already finished, skipping"
        LAST_DIR=$(cat "$RUN/done_$1")
        return
    fi
    # Earlier partial runs of this version: carry on with a fresh seed so the
    # new games do not replay their openings.
    local prior seed
    prior=$(ls "$GAMES"/calib-"$1"-*.pgn 2>/dev/null | wc -l | tr -d ' ')
    seed=$((SEED + 1000 * prior))
    say "--- $1: $2 with $(basename "$3"), seed $seed ($prior earlier run(s)), target +/-$TARGET, up to $((ROUNDS * 18)) games"
    local t0=$SECONDS
    ( cd "$ROOT" && NET_FILE="$3" ./tools/run_calibrate.sh "$1" "$2" $seed $ROUNDS $TARGET ) \
        >>"$RUN/calibrate_$1.log" 2>&1
    local dir
    dir=$(ls -td "$ROOT"/runs/calibrate/${1}_* 2>/dev/null | head -1)
    [ -n "$dir" ] && [ -f "$dir/RESULT.txt" ] || die "$1 calibration did not finish, see $RUN/calibrate_$1.log"
    echo "$dir" > "$RUN/done_$1"
    # Endings across every pool-E game of this version, not just this run's.
    python "$ROOT/testing/pgn_endings.py" "$GAMES"/calib-"$1"-*.pgn | tr -d '\r' > "$RUN/endings_$1.txt"
    read -r total bad < "$RUN/endings_$1.txt"
    say "$1: $(grep -a "Sgurr-$1 " "$dir/RESULT.txt" | head -1 | tr -s ' ')"
    say "$1: this run $(( (SECONDS - t0) / 60 )) min; $total pool-E games in all, $bad abnormal endings"
    [ "$bad" -eq 0 ] || tail -n +2 "$RUN/endings_$1.txt" | head -20 | tee -a "$LOG"
    LAST_DIR=$dir
}

say "=== pool-E v9.1 baseline ==="
pool=$(python -c "import json;print(json.load(open(r'C:/coding/Sgurr/benchmarks/pool.json'))['pool_id'])" | tr -d '\r')
[ "$pool" = "pool-2026-09-E" ] || die "pool.json is $pool, not pool-2026-09-E"
busy=$(powershell -NoProfile -Command "(Get-Process fastchess,datagen -ErrorAction SilentlyContinue | Measure-Object).Count" 2>/dev/null | tr -d '\r ')
[ "${busy:-0}" = "0" ] || die "$busy fastchess/datagen process(es) already running"
spsa=$(powershell -NoProfile -Command "(Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -like '*spsa.py*' -and \$_.Name -ne 'powershell.exe' } | Measure-Object).Count" 2>/dev/null | tr -d '\r ')
[ "${spsa:-0}" = "0" ] || die "an SPSA tune is running"

calibrate v9.1 sprt_bundle.exe "$ROOT/nets/gen9_screlu.nnue"

ORDO="$LAST_DIR/ordo.txt"; [ -s "$ORDO" ] || ORDO="$LAST_DIR/ordo.new"
{
    echo "pool-2026-09-E v9.1 baseline, $(date '+%Y-%m-%d %H:%M')"
    echo "pool-D, same binary and net: v9.1 3206.2 +/-11.8 (systematic about +/-25)"
    echo
    sed -n '1,12p' "$ORDO"
    echo
    echo "endings: $(head -1 "$RUN/endings_v9.1.txt" | awk '{print $1" games, "$2" abnormal"}')"
} > "$RUN/SUMMARY.txt"
tee -a "$LOG" < "$RUN/SUMMARY.txt"
say "=== done ==="
