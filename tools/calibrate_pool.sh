#!/usr/bin/env bash
# Calibrate one Sgurr version on the pool in benchmarks/pool.json to about
# +/-12. That is enough to confirm a gain carries over to other engines; SPRTs
# decide and size gains. Why +/-12 and not tighter: benchmarks/pool_e_prediction.md.
#
#   tools/calibrate_pool.sh VERSION EXE NET    start, or carry on after a pause
#   tools/calibrate_pool.sh --stop             pause: stop everything, keep every game
#
# To top up a version against some engines only, for example after engines
# join the pool, name them and fix the games per engine. That plays a fixed
# number of games instead of stopping at the error target:
#   CALIB_OPPONENTS=Onyx-2.0,Svart-6 CALIB_GAMES_PER_ENGINE=210 tools/calibrate_pool.sh ...
#
# A version that already has games carries on with a new opening seed, so no
# opening is replayed, and Ordo solves all of its games together. A version's
# first run uses seed 1, so every version starts on the same openings.
# Results land in runs/<pool id>/SUMMARY_<version>.txt.
set -u

ROOT=/c/coding/Sgurr
POOL_JSON='C:/coding/Sgurr/benchmarks/pool.json'
TARGET=12         # Ordo +/- per version
MAX_GAMES=4140    # cap on a run to the target
SEED=1

unset SGR_EVALFILE
pool_py() { python -c "import json, os; p = json.load(open(r'$POOL_JSON')); $1" | tr -d '\r'; }
POOL=$(pool_py "print(p['pool_id'])")
# Every games directory the solve reads: this pool's, and any it includes.
SOLVE_DIRS=$(pool_py "print(' '.join(r'$ROOT/benchmarks/' + d for d in [p['games_dir']] + p.get('include_games', [])))")
POOL_PROCS="$(pool_py "print(' '.join(os.path.splitext(os.path.basename(e['cmd']))[0] for e in p['engines']))") ordo"
N_POOL=$(pool_py "print(len(p['engines']))")

RUN=$ROOT/runs/$POOL
LOG=$RUN/driver.log
mkdir -p "$RUN"
say() { echo "[$(date '+%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
die() { say "STOP: $*"; say "=== stopped, needs a human ==="; exit 1; }

# Windows processes whose command line contains $1, minus this shell and any
# shell running --stop.
procs_matching() {
    local me
    me=$(cat /proc/$$/winpid 2>/dev/null || echo 0)
    powershell -NoProfile -Command "(Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -like '*$1*' -and \$_.CommandLine -notlike '*--stop*' -and \$_.ProcessId -ne $me -and \$_.Name -ne 'powershell.exe' } | Select-Object -Expand ProcessId) -join ' '" 2>/dev/null | tr -d '\r'
}

count_games() {
    local d
    for d in $SOLVE_DIRS; do cat "$d"/calib-"$1"*.pgn 2>/dev/null; done | grep -c '^\[Event'
}

if [ "${1:-}" = "--stop" ]; then
    for pid in $(procs_matching calibrate_pool.sh) $(procs_matching run_calibrate.sh); do
        taskkill //PID "$pid" //T //F >/dev/null 2>&1
    done
    . "$ROOT/testing/gauntlet_lib.sh"
    # shellcheck disable=SC2086
    stop_gauntlet $POOL_PROCS
    # shellcheck disable=SC2086
    assert_engines_stopped $POOL_PROCS
    say "paused by --stop; $(count_games "") $POOL games kept. Relaunch to carry on."
    exit 0
fi

VERSION=${1:?usage: tools/calibrate_pool.sh VERSION EXE NET}
EXE=${2:?usage: tools/calibrate_pool.sh VERSION EXE NET}
NET=${3:?usage: tools/calibrate_pool.sh VERSION EXE NET}
case "$NET" in /*) ;; *) NET=$ROOT/$NET ;; esac

say "=== $POOL: $VERSION ==="
if [ -f "$RUN/done_$VERSION" ]; then
    say "$VERSION already finished: $(cat "$RUN/done_$VERSION")"
    exit 0
fi
[ -f "$ROOT/sgurr_cpp/$EXE" ] || die "missing sgurr_cpp/$EXE"
[ -f "$NET" ] || die "missing $NET"
busy=$(powershell -NoProfile -Command "(Get-Process fastchess,datagen -ErrorAction SilentlyContinue | Measure-Object).Count" 2>/dev/null | tr -d '\r ')
[ "${busy:-0}" = "0" ] || die "$busy fastchess/datagen process(es) already running"
[ -z "$(procs_matching spsa.py)" ] || die "an SPSA tune is running"

# Earlier runs of this version: carry on with a fresh seed so the new games
# do not replay their openings.
prior=$(for d in $SOLVE_DIRS; do ls "$d"/calib-"$VERSION"-*.pgn 2>/dev/null; done | wc -l | tr -d ' ')
seed=$((SEED + 1000 * prior))

if [ -n "${CALIB_OPPONENTS:-}" ]; then
    n_opp=$(tr ',' '\n' <<< "$CALIB_OPPONENTS" | grep -c .)
else
    n_opp=$N_POOL
fi
if [ -n "${CALIB_GAMES_PER_ENGINE:-}" ]; then
    rounds=$(( (CALIB_GAMES_PER_ENGINE + 1) / 2 ))
    target=1   # no early stop: play every game
    plan="$((rounds * 2 * n_opp)) games, $((rounds * 2)) against each of $n_opp engines"
else
    rounds=$(( MAX_GAMES / (2 * n_opp) ))
    target=$TARGET
    plan="to +/-$TARGET, at most $((rounds * 2 * n_opp)) games against $n_opp engines"
fi
say "$VERSION: $EXE with $(basename "$NET"), seed $seed ($prior earlier run(s)), $plan"
[ -z "${CALIB_OPPONENTS:-}" ] || say "$VERSION: opponents $CALIB_OPPONENTS"
if [ -n "${CALIB_DRY_RUN:-}" ]; then
    say "dry run: would call NET_FILE=$NET CALIB_OPPONENTS=${CALIB_OPPONENTS:-} tools/run_calibrate.sh $VERSION $EXE $seed $rounds $target"
    exit 0
fi
t0=$SECONDS
( cd "$ROOT" && NET_FILE="$NET" CALIB_OPPONENTS="${CALIB_OPPONENTS:-}" \
    ./tools/run_calibrate.sh "$VERSION" "$EXE" $seed $rounds $target ) >>"$RUN/calibrate_$VERSION.log" 2>&1
dir=$(ls -td "$ROOT"/runs/calibrate/${VERSION}_* 2>/dev/null | head -1)
[ -n "$dir" ] && [ -f "$dir/RESULT.txt" ] || die "$VERSION calibration did not finish, see $RUN/calibrate_$VERSION.log"
echo "$dir" > "$RUN/done_$VERSION"

# Endings across every game of this version the solve reads, not just this run's.
# shellcheck disable=SC2046
python "$ROOT/testing/pgn_endings.py" $(for d in $SOLVE_DIRS; do ls "$d"/calib-"$VERSION"-*.pgn 2>/dev/null; done) \
    | tr -d '\r' > "$RUN/endings_$VERSION.txt"
read -r total bad < "$RUN/endings_$VERSION.txt"
say "$VERSION: $(grep -a "Sgurr-$VERSION " "$dir/RESULT.txt" | head -1 | tr -s ' ')"
say "$VERSION: this run $(( (SECONDS - t0) / 60 )) min; $total games in the solve, $bad abnormal endings"
[ "$bad" -eq 0 ] || tail -n +2 "$RUN/endings_$VERSION.txt" | head -20 | tee -a "$LOG"

ORDO="$dir/ordo.txt"; [ -s "$ORDO" ] || ORDO="$dir/ordo.new"
{
    echo "$POOL, $VERSION, $(date '+%Y-%m-%d %H:%M')"
    echo
    sed -n '1,30p' "$ORDO"
    echo
    echo "endings: $total games, $bad abnormal"
} > "$RUN/SUMMARY_$VERSION.txt"
tee -a "$LOG" < "$RUN/SUMMARY_$VERSION.txt"
say "=== $POOL: $VERSION done ==="
