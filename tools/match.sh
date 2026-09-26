#!/usr/bin/env bash
# A fixed-length match between two builds under the project's standard
# conditions (Hash 256, 8moves_v3.pgn, concurrency 7) at any time control,
# for what an SPRT does not suit: a flag test at very short controls, or a
# look at a longer one.
#
#   tools/match.sh NAME NEW.exe NEW_NODES BASE.exe BASE_NODES TC GAMES
#   tools/match.sh --stop
#
# TC uses fastchess syntax: 8+0.08, or 40/5 for 40 moves in 5 seconds with the
# clock refilled after each 40. Both binaries live in sgurr_cpp/ with their
# nets baked in and are checked against their bench fingerprints, as in
# sprt.sh. The match exits 1 if any game ended abnormally, losses on time
# included, so a flag test is just a short match. MATCH_REPORT_ONLY=1 always
# exits 0, for a control where losses on time are expected and only counted.
# A finished match is never replayed. Results land in runs/match/NAME/summary.txt.
set -u

ROOT=/c/coding/Sgurr
CPP=$ROOT/sgurr_cpp
FC=$ROOT/benchmarks/tools/fastchess.exe
BOOK=$ROOT/testing/8moves_v3.pgn
PY=$ROOT/.venv/Scripts/python.exe
unset SGR_EVALFILE

procs_matching() {
    local me
    me=$(cat /proc/$$/winpid 2>/dev/null || echo 0)
    powershell -NoProfile -Command "(Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -like '*$1*' -and \$_.CommandLine -notlike '*--stop*' -and \$_.ProcessId -ne $me -and \$_.Name -ne 'powershell.exe' } | Select-Object -Expand ProcessId) -join ' '" 2>/dev/null | tr -d '\r'
}

if [ "${1:-}" = "--stop" ]; then
    for pid in $(procs_matching tools/match.sh); do
        taskkill //PID "$pid" //T //F >/dev/null 2>&1
    done
    . "$ROOT/testing/gauntlet_lib.sh"
    stop_gauntlet
    assert_engines_stopped
    exit 0
fi

[ $# -ge 7 ] || { sed -n '2,17p' "$0"; exit 2; }
NAME=$1; NEW=$2; NEW_NODES=$3; BASE=$4; BASE_NODES=$5; TC=$6; GAMES=$7
RUN=$ROOT/runs/match/$NAME
mkdir -p "$RUN"
LOG=$RUN/driver.log
say() { echo "[$(date '+%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
die() { say "STOP: $*"; exit 1; }

say "=== match $NAME: $NEW vs $BASE, $TC, $GAMES games ==="
if grep -aq 'Finished match' "$RUN/match.txt" 2>/dev/null; then
    say "already finished, not replaying it"
else
    busy=$(powershell -NoProfile -Command "(Get-Process fastchess,datagen -ErrorAction SilentlyContinue | Measure-Object).Count" 2>/dev/null | tr -d '\r ')
    [ "${busy:-0}" = "0" ] || die "$busy fastchess/datagen process(es) already running"
    for p in spsa.py calibrate_pool.sh run_calibrate.sh tools/sprt.sh; do
        [ -z "$(procs_matching $p)" ] || die "$p is running"
    done
    for pair in "$NEW $NEW_NODES" "$BASE $BASE_NODES"; do
        set -- $pair
        [ -f "$CPP/$1" ] || die "missing sgurr_cpp/$1"
        got=$("$CPP/$1" bench 2>/dev/null | grep -a '^nodes' | awk '{print $2}')
        [ "$got" = "$2" ] || die "$1 benches ${got:-nothing}, expected $2"
        printf 'uci\nquit\n' | "$CPP/$1" 2>&1 | grep -aq 'nnue: loaded' || die "$1 does not load a net"
    done
    "$PY" "$ROOT/testing/engine_gate.py" "$CPP/$NEW" "$CPP/$BASE" >>"$LOG" 2>&1 \
        || die "UCI rules gate failed, see $LOG"
    if [ -f "$RUN/match.txt" ]; then
        k=$(date +%H%M%S)
        mv "$RUN/match.txt" "$RUN/unfinished_$k.txt"
        mv -f "$RUN/match.pgn" "$RUN/unfinished_$k.pgn" 2>/dev/null
        say "an unfinished earlier attempt was moved aside as unfinished_$k"
    fi
    if [ -n "${MATCH_DRY_RUN:-}" ]; then
        say "dry run: verified both binaries, stopping before any game"
        exit 0
    fi
    say "verified both binaries; playing"
    "$FC" -engine cmd="$CPP/$NEW" name=new -engine cmd="$CPP/$BASE" name=base \
        -each tc="$TC" option.Hash=256 -rounds $((GAMES / 2)) -repeat -concurrency 7 \
        -openings file="$BOOK" format=pgn order=random -recover \
        -pgnout file="$(cygpath -m "$RUN/match.pgn")" \
        >"$RUN/match.txt" 2>&1
    taskkill //IM "$NEW" //F >/dev/null 2>&1
    taskkill //IM "$BASE" //F >/dev/null 2>&1
fi

grep -aq 'Finished match' "$RUN/match.txt" || die "the match did not finish, see $RUN/match.txt"
"$PY" "$ROOT/testing/pgn_endings.py" "$RUN/match.pgn" 2>/dev/null | tr -d '\r' > "$RUN/endings.txt"
read -r total bad < "$RUN/endings.txt"
# Losses on time by engine: fastchess tags them "time forfeit", and the
# result says who lost.
flags=$("$PY" -c "
import re, sys
text = open(sys.argv[1], encoding='utf-8', errors='replace').read()
lost = {'new': 0, 'base': 0}
for game in re.split(r'(?=\[Event )', text):
    tags = dict(re.findall(r'\[(\w+) \"([^\"]*)\"\]', game))
    if 'time' in tags.get('Termination', ''):
        loser = tags.get('Black') if tags.get('Result') == '1-0' else tags.get('White')
        lost[loser] = lost.get(loser, 0) + 1
print(lost['new'], lost['base'])
" "$(cygpath -m "$RUN/match.pgn")" | tr -d '\r')
read -r flags_new flags_base <<< "$flags"
{
    echo "match $NAME: $NEW (new) vs $BASE (base), $TC"
    echo "  $(grep -aE '^Elo:' "$RUN/match.txt" | tail -1)"
    echo "  $(grep -aE '^Games:' "$RUN/match.txt" | tail -1)"
    echo "  endings: $total games, $bad abnormal; losses on time: new $flags_new, base $flags_base"
    tail -n +2 "$RUN/endings.txt" | head -10
} > "$RUN/summary.txt"
tee -a "$LOG" < "$RUN/summary.txt"

[ -n "${MATCH_REPORT_ONLY:-}" ] || [ "$bad" -eq 0 ] || exit 1
exit 0
