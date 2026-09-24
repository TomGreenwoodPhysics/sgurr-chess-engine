#!/usr/bin/env bash
# Validate pool-2026-09-E: calibrate v9.1, then v9.0, with the binaries and nets
# they were calibrated with on pool-D and the same opening seed, then read the
# gap from one solve. Prediction: benchmarks/pool_e_prediction.md.
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
TARGET=8          # Ordo +/- per version
ROUNDS=230        # 18 games a round, so at most 4,140 games per version per run
SEED=1

mkdir -p "$RUN"
unset SGR_EVALFILE
say() { echo "[$(date '+%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
die() { say "STOP: $*"; say "=== stopped, needs a human ==="; exit 1; }

POOL_PROCS="sprt_bundle sgr_v9_0 bit-genie-9 bitfox-2.5.0 monolith-3 drofa-4.1.0 mantissa-3.7.2 nalwald-19 counter-5.5 Lynx.Cli frozenight-6.0.0 ordo"

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

# Games that did not end in a mate or a draw by rule: forfeits, time losses,
# crashes, disconnects. Prints "total abnormal".
endings() {
    local f=$1 tmp=$RUN/endings.tmp
    grep -aoE 'Finished game [0-9]+ \([^)]*\): [^{]*\{[^}]*\}' "$f" \
        | sed -E 's/.*\{(.*)\}$/\1/' > "$tmp"
    echo "$(wc -l < "$tmp" | tr -d ' ') $(grep -cvE 'mates$|^Draw by ' "$tmp")"
}

calibrate() {  # version exe net
    if [ -f "$RUN/done_$1" ]; then
        say "$1 already finished, skipping"
        LAST_DIR=$(cat "$RUN/done_$1")
        return
    fi
    # Earlier partial runs of this version: carry on with a fresh seed so the
    # new games do not replay their openings. The first run of every version
    # uses the same seed, which pairs v9.0 and v9.1 opening for opening.
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
    read -r total bad <<< "$(endings "$dir/gauntlet.log")"
    say "$1: $(grep -a "Sgurr-$1 " "$dir/RESULT.txt" | head -1 | tr -s ' ')"
    say "$1: $total games in $(( (SECONDS - t0) / 60 )) min, $bad abnormal endings"
    [ "$bad" -eq 0 ] || grep -aoE 'Finished game [0-9]+ \([^)]*\): [^{]*\{[^}]*\}' "$dir/gauntlet.log" \
        | grep -avE 'mates\}$|\{Draw by ' | head -20 | tee -a "$LOG"
    LAST_DIR=$dir
}

say "=== pool-E validation ==="
pool=$(python -c "import json;print(json.load(open(r'C:/coding/Sgurr/benchmarks/pool.json'))['pool_id'])" | tr -d '\r')
[ "$pool" = "pool-2026-09-E" ] || die "pool.json is $pool, not pool-2026-09-E"
busy=$(powershell -NoProfile -Command "(Get-Process fastchess,datagen -ErrorAction SilentlyContinue | Measure-Object).Count" 2>/dev/null | tr -d '\r ')
[ "${busy:-0}" = "0" ] || die "$busy fastchess/datagen process(es) already running"
spsa=$(powershell -NoProfile -Command "(Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -like '*spsa.py*' -and \$_.Name -ne 'powershell.exe' } | Measure-Object).Count" 2>/dev/null | tr -d '\r ')
[ "${spsa:-0}" = "0" ] || die "an SPSA tune is running"

calibrate v9.1 sprt_bundle.exe "$ROOT/nets/gen9_screlu.nnue"
calibrate v9.0 sgr_v9_0.exe "$ROOT/nets/gen9.nnue"

# The v9.0 run's final solve covers every pool-E game, so both versions are in it.
ORDO="$LAST_DIR/ordo.txt"; [ -s "$ORDO" ] || ORDO="$LAST_DIR/ordo.new"
{
    echo "pool-2026-09-E validation, $(date '+%Y-%m-%d %H:%M')"
    echo "Prediction: benchmarks/pool_e_prediction.md (gap +120, band +100 to +140)"
    echo "pool-D, same binaries: v9.1 3206.2 +/-11.8, v9.0 3081.2 +/-6.7, gap +124.5 +/-13.6"
    echo
    sed -n '1,14p' "$ORDO"
    echo
    awk '/ Sgurr-v9\.1 /{a=$4; ea=$5} / Sgurr-v9\.0 /{b=$4; eb=$5}
         END{ if (a && b) printf "pool-E gap v9.0 -> v9.1: %+.1f  (joint +/-%.1f)\n", a-b, sqrt(ea*ea+eb*eb) }' "$ORDO"
    echo
    grep -a 'v9\.[01]:' "$LOG" | grep -a 'games in'
} > "$RUN/SUMMARY.txt"
tee -a "$LOG" < "$RUN/SUMMARY.txt"
say "=== done ==="
