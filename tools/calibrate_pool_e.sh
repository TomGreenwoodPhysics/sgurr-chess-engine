#!/usr/bin/env bash
# Calibrate one Sgurr version on pool-2026-09-E to about +/-12. That is enough
# to confirm a gain carries over to other engines; SPRTs decide and size gains.
# Why +/-12 and not tighter: benchmarks/pool_e_prediction.md.
#
#   tools/calibrate_pool_e.sh [version exe net]   start, or carry on after a pause
#       default: v9.1 sprt_bundle.exe nets/gen9_screlu.nnue (its pool-D binary and net)
#   tools/calibrate_pool_e.sh --stop              pause: stop everything, keep every game
#
# A version that already has games carries on with a new opening seed, so no
# opening is replayed, and Ordo solves all of its games together. A version's
# first run uses seed 1, so every version starts on the same openings.
# Results land in runs/pool_e/SUMMARY_<version>.txt.
set -u

ROOT=/c/coding/Sgurr
RUN=$ROOT/runs/pool_e
LOG=$RUN/driver.log
GAMES=$ROOT/benchmarks/games/pool-2026-09-E
TARGET=12         # Ordo +/- per version
ROUNDS=230        # 18 games a round, so at most 4,140 games per run
SEED=1

mkdir -p "$RUN"
unset SGR_EVALFILE
say() { echo "[$(date '+%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
die() { say "STOP: $*"; say "=== stopped, needs a human ==="; exit 1; }

POOL_PROCS="sprt_bundle sgr_v92rc bit-genie-9 bitfox-2.5.0 monolith-3 drofa-4.1.0 mantissa-3.7.2 nalwald-19 counter-5.5 Lynx.Cli frozenight-6.0.0 ordo"

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

VERSION=${1:-v9.1}
EXE=${2:-sprt_bundle.exe}
NET=${3:-$ROOT/nets/gen9_screlu.nnue}
case "$NET" in /*) ;; *) NET=$ROOT/$NET ;; esac

say "=== pool-E: $VERSION ==="
if [ -f "$RUN/done_$VERSION" ]; then
    say "$VERSION already finished: $(cat "$RUN/done_$VERSION")"
    exit 0
fi
pool=$(python -c "import json;print(json.load(open(r'C:/coding/Sgurr/benchmarks/pool.json'))['pool_id'])" | tr -d '\r')
[ "$pool" = "pool-2026-09-E" ] || die "pool.json is $pool, not pool-2026-09-E"
[ -f "$ROOT/sgurr_cpp/$EXE" ] || die "missing sgurr_cpp/$EXE"
[ -f "$NET" ] || die "missing $NET"
busy=$(powershell -NoProfile -Command "(Get-Process fastchess,datagen -ErrorAction SilentlyContinue | Measure-Object).Count" 2>/dev/null | tr -d '\r ')
[ "${busy:-0}" = "0" ] || die "$busy fastchess/datagen process(es) already running"
[ -z "$(procs_matching spsa.py)" ] || die "an SPSA tune is running"

# Earlier partial runs of this version: carry on with a fresh seed so the new
# games do not replay their openings.
prior=$(ls "$GAMES"/calib-"$VERSION"-*.pgn 2>/dev/null | wc -l | tr -d ' ')
seed=$((SEED + 1000 * prior))
say "$VERSION: $EXE with $(basename "$NET"), seed $seed ($prior earlier run(s)), target +/-$TARGET, up to $((ROUNDS * 18)) games"
if [ -n "${CALIB_DRY_RUN:-}" ]; then
    say "dry run: would call NET_FILE=$NET tools/run_calibrate.sh $VERSION $EXE $seed $ROUNDS $TARGET"
    exit 0
fi
t0=$SECONDS
( cd "$ROOT" && NET_FILE="$NET" ./tools/run_calibrate.sh "$VERSION" "$EXE" $seed $ROUNDS $TARGET ) \
    >>"$RUN/calibrate_$VERSION.log" 2>&1
dir=$(ls -td "$ROOT"/runs/calibrate/${VERSION}_* 2>/dev/null | head -1)
[ -n "$dir" ] && [ -f "$dir/RESULT.txt" ] || die "$VERSION calibration did not finish, see $RUN/calibrate_$VERSION.log"
echo "$dir" > "$RUN/done_$VERSION"

# Endings across every pool-E game of this version, not just this run's.
python "$ROOT/testing/pgn_endings.py" "$GAMES"/calib-"$VERSION"-*.pgn | tr -d '\r' > "$RUN/endings_$VERSION.txt"
read -r total bad < "$RUN/endings_$VERSION.txt"
say "$VERSION: $(grep -a "Sgurr-$VERSION " "$dir/RESULT.txt" | head -1 | tr -s ' ')"
say "$VERSION: this run $(( (SECONDS - t0) / 60 )) min; $total pool-E games in all, $bad abnormal endings"
[ "$bad" -eq 0 ] || tail -n +2 "$RUN/endings_$VERSION.txt" | head -20 | tee -a "$LOG"

ORDO="$dir/ordo.txt"; [ -s "$ORDO" ] || ORDO="$dir/ordo.new"
{
    echo "pool-2026-09-E, $VERSION, $(date '+%Y-%m-%d %H:%M')"
    echo "(pool-D, v9.1 with the same binary and net: 3206.2 +/-11.8, systematic about +/-25)"
    echo
    sed -n '1,14p' "$ORDO"
    echo
    echo "endings: $total games, $bad abnormal"
} > "$RUN/SUMMARY_$VERSION.txt"
tee -a "$LOG" < "$RUN/SUMMARY_$VERSION.txt"
say "=== pool-E: $VERSION done ==="
