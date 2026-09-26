#!/usr/bin/env bash
# Run a list of jobs one after another, unattended.
#
#   tools/queue.sh QUEUE_FILE    run the queue, or carry on after a stop
#   tools/queue.sh --stop        stop the queue and the job it is running
#
# Each line of the queue file, apart from blank lines and # comments, is
#   NAME | NEEDS | COMMAND
# NAME is one word. NEEDS lists the jobs that must have succeeded first, or -.
# COMMAND runs under bash from the repository root, and succeeds if it exits
# 0. A job whose prerequisite failed or was skipped is skipped itself. Jobs
# that succeeded are recorded and never run again, so starting the queue a
# second time carries on where it stopped. Everything is logged under
# runs/queue/<queue file name>/.
#
# Unattended means nothing may stall the night or spoil the next job. Each job
# is killed if it runs past QUEUE_JOB_HOURS (default 7, above the longest
# legitimate job), and fastchess, Ordo and every engine the night uses are
# cleared away before and after each job.
set -u

ROOT=/c/coding/Sgurr
LOCK=$ROOT/runs/queue/running.pid   # Windows process id of the queue running now
JOB_HOURS=${QUEUE_JOB_HOURS:-7}

procs_matching() {
    local me
    me=$(cat /proc/$$/winpid 2>/dev/null || echo 0)
    powershell -NoProfile -Command "(Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -like '*$1*' -and \$_.CommandLine -notlike '*--stop*' -and \$_.ProcessId -ne $me -and \$_.Name -ne 'powershell.exe' } | Select-Object -Expand ProcessId) -join ' '" 2>/dev/null | tr -d '\r'
}

if [ "${1:-}" = "--stop" ]; then
    for pid in $(procs_matching tools/queue.sh); do
        taskkill //PID "$pid" //T //F >/dev/null 2>&1
    done
    # Each tool cleans up its own engines and knows what it started.
    "$ROOT/tools/sprt.sh" --stop >/dev/null 2>&1
    "$ROOT/tools/match.sh" --stop >/dev/null 2>&1
    "$ROOT/tools/calibrate_pool.sh" --stop
    rm -f "$LOCK"
    exit 0
fi

QUEUE=${1:?usage: tools/queue.sh QUEUE_FILE | --stop}
[ -f "$QUEUE" ] || { echo "no queue file $QUEUE" >&2; exit 2; }
QNAME=$(basename "$QUEUE"); QNAME=${QNAME%.*}
RUN=$ROOT/runs/queue/$QNAME
STATE=$RUN/state
LOG=$RUN/queue.log
mkdir -p "$RUN"
touch "$STATE"
say() { echo "[$(date '+%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
status_of() { awk -v n="$1" '$1 == n { s = $2 } END { print s }' "$STATE"; }
set_status() { echo "$1 $2" >> "$STATE"; }

# One queue at a time. A lock left by a queue that died is ignored.
me=$(cat /proc/$$/winpid)
if [ -f "$LOCK" ]; then
    other=$(tr -d '\r\n ' < "$LOCK")
    if [ -n "$other" ] && tasklist //FI "PID eq $other" 2>/dev/null | grep -q " $other "; then
        say "STOP: another queue is running (process $other)"
        exit 1
    fi
fi
echo "$me" > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

# Every engine the night can start: the pool's, and each binary the queue
# file names. Cleared by name, after fastchess and its children.
ENGINES="ordo $(python -c "import json, os; print(' '.join(os.path.splitext(os.path.basename(e['cmd']))[0] for e in json.load(open(r'C:/coding/Sgurr/benchmarks/pool.json'))['engines']))" | tr -d '\r')"
ENGINES="$ENGINES $(grep -v '^ *#' "$QUEUE" | grep -o '[A-Za-z0-9_.-]*\.exe' | sed 's/\.exe$//' | sort -u | tr '\n' ' ')"
. "$ROOT/testing/gauntlet_lib.sh"
clean_up() {
    # shellcheck disable=SC2086
    stop_gauntlet $ENGINES >/dev/null 2>&1
    # shellcheck disable=SC2086
    left=$(assert_engines_stopped $ENGINES 2>&1 >/dev/null)
    [ -z "$left" ] || say "WARNING: $left"
}
limit=$(awk -v h="$JOB_HOURS" 'BEGIN { print int(h * 3600) }')

say "=== queue $QNAME ==="
while IFS= read -r line || [ -n "$line" ]; do
    line=${line%$'\r'}
    case "$line" in ''|'#'*) continue ;; esac
    name=$(echo "${line%%|*}" | xargs)
    rest=${line#*|}
    needs=$(echo "${rest%%|*}" | xargs)
    cmd=$(echo "${rest#*|}" | sed 's/^ *//')

    if [ "$(status_of "$name")" = ok ]; then
        say "$name: already done"
        continue
    fi
    blocked=""
    if [ "$needs" != "-" ]; then
        for need in $needs; do
            [ "$(status_of "$need")" = ok ] || blocked="$blocked $need"
        done
    fi
    if [ -n "$blocked" ]; then
        say "$name: skipped, needs$blocked"
        set_status "$name" skipped
        continue
    fi

    clean_up
    say "$name: started: $cmd"
    t0=$SECONDS
    ( cd "$ROOT" && exec bash -c "$cmd" ) >"$RUN/$name.log" 2>&1 < /dev/null &
    job=$!
    timed_out=0
    while kill -0 "$job" 2>/dev/null; do
        if [ $((SECONDS - t0)) -ge "$limit" ]; then
            timed_out=1
            wpid=$(cat /proc/$job/winpid 2>/dev/null)
            [ -z "$wpid" ] || taskkill //PID "$wpid" //T //F >/dev/null 2>&1
            kill "$job" 2>/dev/null
            break
        fi
        sleep 5
    done
    wait "$job" 2>/dev/null
    rc=$?
    [ $timed_out -eq 0 ] || rc=124
    clean_up
    minutes=$(( (SECONDS - t0) / 60 ))
    if [ $rc -eq 0 ]; then
        set_status "$name" ok
        say "$name: ok after $minutes min"
    elif [ $timed_out -eq 1 ]; then
        set_status "$name" failed
        say "$name: KILLED after $JOB_HOURS h, see $RUN/$name.log"
    else
        set_status "$name" failed
        say "$name: FAILED (exit $rc) after $minutes min, see $RUN/$name.log"
    fi
done < "$QUEUE"
say "=== queue $QNAME finished ==="
