#!/usr/bin/env bash
# One SPRT under the project's standard conditions: 8+0.08, Hash 256,
# 8moves_v3.pgn, concurrency 7, elo0=0 elo1=5, alpha=beta=0.05.
#
#   tools/sprt.sh NAME NEW.exe NEW_NODES BASE.exe BASE_NODES [MAX_GAMES]
#   tools/sprt.sh --stop
#
# Both binaries live in sgurr_cpp/ with their nets baked in. NEW_NODES and
# BASE_NODES are their bench fingerprints: the run refuses to start unless each
# binary is the one that was checked. MAX_GAMES defaults to 5,000.
# A finished SPRT is never replayed; an unfinished one is moved aside and
# restarted clean. Results land in runs/sprt/NAME/summary.txt.
set -u

ROOT=/c/coding/Sgurr
CPP=$ROOT/sgurr_cpp
FC=$ROOT/benchmarks/tools/fastchess.exe
BOOK=$ROOT/testing/8moves_v3.pgn
unset SGR_EVALFILE

procs_matching() {
    local me
    me=$(cat /proc/$$/winpid 2>/dev/null || echo 0)
    powershell -NoProfile -Command "(Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -like '*$1*' -and \$_.CommandLine -notlike '*--stop*' -and \$_.ProcessId -ne $me -and \$_.Name -ne 'powershell.exe' } | Select-Object -Expand ProcessId) -join ' '" 2>/dev/null | tr -d '\r'
}

if [ "${1:-}" = "--stop" ]; then
    for pid in $(procs_matching tools/sprt.sh); do
        taskkill //PID "$pid" //T //F >/dev/null 2>&1
    done
    . "$ROOT/testing/gauntlet_lib.sh"
    stop_gauntlet
    assert_engines_stopped
    exit 0
fi

[ $# -ge 5 ] || { sed -n '2,12p' "$0"; exit 2; }
NAME=$1; NEW=$2; NEW_NODES=$3; BASE=$4; BASE_NODES=$5; MAX=${6:-5000}
RUN=$ROOT/runs/sprt/$NAME
mkdir -p "$RUN"
LOG=$RUN/driver.log
say() { echo "[$(date '+%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
die() { say "STOP: $*"; exit 1; }

say "=== SPRT $NAME: $NEW vs $BASE, up to $MAX games ==="
if grep -aq 'Finished match' "$RUN/sprt.txt" 2>/dev/null; then
    say "already finished, not replaying it"
else
    busy=$(powershell -NoProfile -Command "(Get-Process fastchess,datagen -ErrorAction SilentlyContinue | Measure-Object).Count" 2>/dev/null | tr -d '\r ')
    [ "${busy:-0}" = "0" ] || die "$busy fastchess/datagen process(es) already running"
    for p in spsa.py calibrate_pool_e.sh run_calibrate.sh overnight_chain.sh; do
        [ -z "$(procs_matching $p)" ] || die "$p is running"
    done
    for pair in "$NEW $NEW_NODES" "$BASE $BASE_NODES"; do
        set -- $pair
        [ -f "$CPP/$1" ] || die "missing sgurr_cpp/$1"
        got=$("$CPP/$1" bench 2>/dev/null | grep -a '^nodes' | awk '{print $2}')
        [ "$got" = "$2" ] || die "$1 benches ${got:-nothing}, expected $2"
        printf 'uci\nquit\n' | "$CPP/$1" 2>&1 | grep -aq 'nnue: loaded' || die "$1 does not load a net"
    done
    "$ROOT/.venv/Scripts/python.exe" "$ROOT/testing/engine_gate.py" "$CPP/$NEW" "$CPP/$BASE" >>"$LOG" 2>&1 \
        || die "UCI rules gate failed, see $LOG"
    if [ -f "$RUN/sprt.txt" ]; then
        k=$(date +%H%M%S)
        mv "$RUN/sprt.txt" "$RUN/unfinished_$k.txt"
        mv -f "$RUN/sprt.pgn" "$RUN/unfinished_$k.pgn" 2>/dev/null
        say "an unfinished earlier attempt was moved aside as unfinished_$k"
    fi
    if [ -n "${SPRT_DRY_RUN:-}" ]; then
        say "dry run: verified both binaries, stopping before any game"
        exit 0
    fi
    say "verified both binaries; playing"
    "$FC" -engine cmd="$CPP/$NEW" name=new -engine cmd="$CPP/$BASE" name=base \
        -each tc=8+0.08 option.Hash=256 -rounds $((MAX / 2)) -repeat -concurrency 7 \
        -openings file="$BOOK" format=pgn order=random -recover \
        -sprt elo0=0 elo1=5 alpha=0.05 beta=0.05 \
        -pgnout file="$(cygpath -m "$RUN/sprt.pgn")" \
        >"$RUN/sprt.txt" 2>&1
    taskkill //IM "$NEW" //F >/dev/null 2>&1
    taskkill //IM "$BASE" //F >/dev/null 2>&1
fi

if   grep -aq 'H1 was accepted' "$RUN/sprt.txt"; then v=H1
elif grep -aq 'H0 was accepted' "$RUN/sprt.txt"; then v=H0
elif grep -aq 'Finished match' "$RUN/sprt.txt"; then v="no decision at the cap"
else v="DID NOT FINISH"; fi
"$ROOT/.venv/Scripts/python.exe" "$ROOT/testing/pgn_endings.py" "$RUN/sprt.pgn" 2>/dev/null | tr -d '\r' > "$RUN/endings.txt"
{
    echo "SPRT $NAME: $NEW vs $BASE, 8+0.08, [0, 5]: $v"
    echo "  $(grep -aE '^Elo:' "$RUN/sprt.txt" | tail -1)"
    echo "  $(grep -aE '^Games:' "$RUN/sprt.txt" | tail -1)"
    echo "  endings: $(head -1 "$RUN/endings.txt" | awk '{print $1" games, "$2" abnormal"}')"
    tail -n +2 "$RUN/endings.txt" | head -10
} > "$RUN/summary.txt"
tee -a "$LOG" < "$RUN/summary.txt"
