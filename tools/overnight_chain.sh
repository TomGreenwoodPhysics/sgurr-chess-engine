#!/usr/bin/env bash
# Overnight chain, planned 2026-09-25:
#   1. v9.1 on pool-E to +/-12, carrying on from its first 541 games
#   2. SPRT: null-move eval gate + TT move keeping against v9.1, 8+0.08, [0, 5],
#      capped at 5,000 games (benchmarks/v92_fixes_prediction.md)
#   3. v9.2-rc (both fixes + the cosine seed-1 net) on pool-E to +/-12
#      (benchmarks/v92rc_prediction.md)
#
#   tools/overnight_chain.sh --check   verify everything the night needs, play no games
#   tools/overnight_chain.sh           run; finished steps are skipped
#   tools/overnight_chain.sh --stop    stop everything, keep every finished game
#
# Steps are independent. One that fails is retried once, then the chain moves
# on, so a single failure cannot idle the machine for the rest of the night.
# Results land in runs/overnight_0925/summary.txt.
set -u

ROOT=/c/coding/Sgurr
CPP=$ROOT/sgurr_cpp
BM=$ROOT/benchmarks
RUN=$ROOT/runs/overnight_0925
LOG=$RUN/chain.log
FC=$BM/tools/fastchess.exe
BOOK=$ROOT/testing/8moves_v3.pgn
PY=$ROOT/.venv/Scripts/python.exe
SPRT_ROUNDS=2500                 # 5,000-game cap

mkdir -p "$RUN"
unset SGR_EVALFILE
say()  { echo "[$(date '+%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
fail() { say "CHECK FAILED: $*"; FAILED=1; }

procs_matching() {
    local me
    me=$(cat /proc/$$/winpid 2>/dev/null || echo 0)
    powershell -NoProfile -Command "(Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -like '*$1*' -and \$_.CommandLine -notlike '*--stop*' -and \$_.CommandLine -notlike '*--check*' -and \$_.ProcessId -ne $me -and \$_.Name -ne 'powershell.exe' } | Select-Object -Expand ProcessId) -join ' '" 2>/dev/null | tr -d '\r'
}

if [ "${1:-}" = "--stop" ]; then
    for pid in $(procs_matching overnight_chain.sh); do
        taskkill //PID "$pid" //T //F >/dev/null 2>&1
    done
    taskkill //IM fastchess.exe //F >/dev/null 2>&1
    taskkill //IM sprt_fixes.exe //F >/dev/null 2>&1
    taskkill //IM sprt_v91_ref.exe //F >/dev/null 2>&1
    "$ROOT/tools/calibrate_pool_e.sh" --stop
    say "stopped by --stop"
    exit 0
fi

# --- verification: every input the night depends on ----------------------
FAILED=0
verify() {
    say "verifying"
    local n
    n=$(powershell -NoProfile -Command "(Get-Process fastchess,datagen -ErrorAction SilentlyContinue | Measure-Object).Count" 2>/dev/null | tr -d '\r ')
    [ "${n:-0}" = "0" ] || fail "$n fastchess/datagen process(es) running"
    for p in spsa.py calibrate_pool_e.sh run_calibrate.sh overnight_fixes.sh; do
        [ -z "$(procs_matching $p)" ] || fail "$p is running"
    done
    for f in "$FC" "$BM/tools/ordo.exe" "$PY" "$ROOT/testing/pgn_endings.py" "$ROOT/tools/calibrate_pool_e.sh" "$ROOT/tools/run_calibrate.sh"; do
        [ -e "$f" ] || fail "missing $f"
    done
    [ "$(sha256sum "$BOOK" | cut -c1-64)" = 5835239f88cc2c7511b177c32392a69f3ede21819cf0616f80a7f907cd21d17e ] || fail "book hash"
    [ "$(sha256sum "$ROOT/nets/gen9_screlu.nnue" | cut -c1-64)" = 966b06143d67ad18fb48325d06cff152b35d11dfd52533df232f7ecde46eef0e ] || fail "gen9_screlu.nnue hash"
    [ "$(sha256sum "$ROOT/nets/gen9_screlu_cos_s1.nnue" | cut -c1-64)" = e733e437ad3fbe7cb8b8ab0dbeeaa6f8c29d1bebdbf36f76a8e1851d1bd4642b ] || fail "gen9_screlu_cos_s1.nnue hash"

    # Pool engines: present, byte-identical to pool.json.
    "$PY" - "$(cygpath -m "$BM/pool.json")" <<'EOF' | tr -d '\r' > "$RUN/pool_check.txt"
import hashlib, json, os, sys
p = json.load(open(sys.argv[1]))
root = os.path.dirname(sys.argv[1])
print(p["pool_id"])
for e in p["engines"]:
    f = os.path.join(root, e["cmd"])
    ok = os.path.exists(f) and hashlib.sha256(open(f, "rb").read()).hexdigest() == e["sha256"]
    print(("OK " if ok else "BAD ") + e["name"])
EOF
    [ "$(head -1 "$RUN/pool_check.txt")" = pool-2026-09-E ] || fail "pool.json is not pool-2026-09-E"
    grep -q '^BAD' "$RUN/pool_check.txt" && fail "pool engine missing or changed: $(grep '^BAD' "$RUN/pool_check.txt" | tr '\n' ' ')"

    # Sgurr binaries: each searches exactly the tree it was checked with and
    # loads the net it is meant to.
    local want exe got
    for want in "sprt_bundle.exe 2199384" "sprt_v91_ref.exe 2199384" "sprt_fixes.exe 1551144" "sgr_v92rc.exe 1681306"; do
        set -- $want; exe=$1
        got=$("$CPP/$exe" bench 2>/dev/null | grep -a '^nodes' | awk '{print $2}')
        [ "$got" = "$2" ] || fail "$exe benches ${got:-nothing}, expected $2"
    done
    printf 'uci\nquit\n' | SGR_EVALFILE="$(cygpath -m "$ROOT/nets/gen9_screlu.nnue")" "$CPP/sprt_bundle.exe" 2>&1 | grep -aq 'loaded .*/gen9_screlu.nnue' || fail "sprt_bundle does not load gen9_screlu"
    printf 'uci\nquit\n' | SGR_EVALFILE="$(cygpath -m "$ROOT/nets/gen9_screlu_cos_s1.nnue")" "$CPP/sgr_v92rc.exe" 2>&1 | grep -aq 'loaded .*/gen9_screlu_cos_s1.nnue' || fail "sgr_v92rc does not load gen9_screlu_cos_s1"
    for exe in sprt_v91_ref.exe sprt_fixes.exe; do
        printf 'uci\nquit\n' | "$CPP/$exe" 2>&1 | grep -aq 'loaded .*/gen9_screlu.nnue' || fail "$exe does not load gen9_screlu"
    done

    # Start, UCI handshake and rules gate for every engine that plays tonight.
    local all="$CPP/sprt_bundle.exe $CPP/sprt_v91_ref.exe $CPP/sprt_fixes.exe $CPP/sgr_v92rc.exe"
    all="$all $(grep -oE '"cmd": *"[^"]+"' "$BM/pool.json" | sed -E 's/.*"cmd": *"([^"]+)"/\1/' | sed "s|^|$BM/|" | tr '\n' ' ')"
    # shellcheck disable=SC2086
    "$PY" "$ROOT/testing/engine_gate.py" $all > "$RUN/gate.txt" 2>&1 || fail "UCI rules gate, see $RUN/gate.txt"

    local free
    free=$(df -BG /c | awk 'NR==2{gsub("G","",$4); print $4}')
    [ "${free:-0}" -gt 20 ] || fail "only ${free}G free on C:"

    [ "$FAILED" = 0 ] && say "verified: pool, nets, four Sgurr binaries, rules gate, disk" || return 1
}

if [ "${1:-}" = "--check" ]; then
    verify && say "=== check passed: ready ===" || { say "=== check FAILED, do not launch ==="; exit 1; }
    say "step 1: $([ -f "$ROOT/runs/pool_e/done_v9.1" ] && echo done || echo "to run ($(cat "$BM"/games/pool-2026-09-E/calib-v9.1-*.pgn 2>/dev/null | grep -c '^\[Event') games so far)")"
    say "step 2: $(grep -aq 'Finished match' "$RUN/sprt.txt" 2>/dev/null && echo done || echo 'to run')"
    say "step 3: $([ -f "$ROOT/runs/pool_e/done_v9.2-rc" ] && echo done || echo 'to run')"
    exit 0
fi

say "=== overnight chain ==="
verify || { say "=== verification failed, nothing started ==="; exit 1; }

# --- 1. v9.1 on pool-E ------------------------------------------------------
for attempt in 1 2; do
    [ -f "$ROOT/runs/pool_e/done_v9.1" ] && break
    say "step 1, attempt $attempt: v9.1 on pool-E"
    "$ROOT/tools/calibrate_pool_e.sh" v9.1 sprt_bundle.exe nets/gen9_screlu.nnue >>"$LOG" 2>&1
done
[ -f "$ROOT/runs/pool_e/done_v9.1" ] && say "step 1 done" || say "step 1 FAILED twice, moving on"

# --- 2. SPRT: fixes vs v9.1 -------------------------------------------------
for attempt in 1 2; do
    grep -aq 'Finished match' "$RUN/sprt.txt" 2>/dev/null && break
    # A broken attempt is kept aside, never appended to: an SPRT restarts clean.
    [ -f "$RUN/sprt.txt" ] && mv "$RUN/sprt.txt" "$RUN/sprt_broken_$attempt.txt" && mv -f "$RUN/sprt.pgn" "$RUN/sprt_broken_$attempt.pgn" 2>/dev/null
    say "step 2, attempt $attempt: SPRT fixes vs v9.1, 8+0.08, [0, 5], up to $((SPRT_ROUNDS * 2)) games"
    taskkill //IM fastchess.exe //F >/dev/null 2>&1
    "$FC" -engine cmd="$CPP/sprt_fixes.exe" name=fixes -engine cmd="$CPP/sprt_v91_ref.exe" name=v91 \
        -each tc=8+0.08 option.Hash=256 -rounds $SPRT_ROUNDS -repeat -concurrency 7 \
        -openings file="$BOOK" format=pgn order=random -recover \
        -sprt elo0=0 elo1=5 alpha=0.05 beta=0.05 \
        -pgnout file="$(cygpath -m "$RUN/sprt.pgn")" \
        >"$RUN/sprt.txt" 2>&1
    taskkill //IM sprt_fixes.exe //F >/dev/null 2>&1
    taskkill //IM sprt_v91_ref.exe //F >/dev/null 2>&1
done
if grep -aq 'Finished match' "$RUN/sprt.txt" 2>/dev/null; then
    if   grep -aq 'H1 was accepted' "$RUN/sprt.txt"; then v=H1
    elif grep -aq 'H0 was accepted' "$RUN/sprt.txt"; then v=H0
    else v="no decision at the cap"; fi
    "$PY" "$ROOT/testing/pgn_endings.py" "$RUN/sprt.pgn" | tr -d '\r' > "$RUN/sprt_endings.txt"
    say "step 2 done: $v | $(grep -aE '^Elo:' "$RUN/sprt.txt" | tail -1) | $(grep -aE '^Games:' "$RUN/sprt.txt" | tail -1)"
else
    v="FAILED twice"; say "step 2 FAILED twice, moving on"
fi
sleep 5

# --- 3. v9.2-rc on pool-E ---------------------------------------------------
for attempt in 1 2; do
    [ -f "$ROOT/runs/pool_e/done_v9.2-rc" ] && break
    say "step 3, attempt $attempt: v9.2-rc on pool-E"
    "$ROOT/tools/calibrate_pool_e.sh" v9.2-rc sgr_v92rc.exe nets/gen9_screlu_cos_s1.nnue >>"$LOG" 2>&1
done
[ -f "$ROOT/runs/pool_e/done_v9.2-rc" ] && say "step 3 done" || say "step 3 FAILED twice"

# --- summary ------------------------------------------------------------------
{
    echo "Overnight chain, finished $(date '+%Y-%m-%d %H:%M')"
    echo
    echo "1. v9.1 on pool-E"
    sed -n '/Sgurr-v9.1 /p' "$ROOT/runs/pool_e/SUMMARY_v9.1.txt" 2>/dev/null | head -1
    grep -a '^endings' "$ROOT/runs/pool_e/SUMMARY_v9.1.txt" 2>/dev/null
    echo
    echo "2. SPRT fixes vs v9.1, 8+0.08, [0, 5]: $v   (predicted +10, band 0 to +25)"
    echo "   $(grep -aE '^Elo:' "$RUN/sprt.txt" 2>/dev/null | tail -1)"
    echo "   $(grep -aE '^Games:' "$RUN/sprt.txt" 2>/dev/null | tail -1)"
    echo "   endings: $(head -1 "$RUN/sprt_endings.txt" 2>/dev/null | awk '{print $1" games, "$2" abnormal"}')"
    echo
    echo "3. v9.2-rc on pool-E (same solve as v9.1)"
    if [ -f "$ROOT/runs/pool_e/done_v9.2-rc" ]; then
        o="$(cat "$ROOT/runs/pool_e/done_v9.2-rc")/ordo.txt"; [ -s "$o" ] || o="${o%.txt}.new"
        grep -aE 'Sgurr-v9\.(1|2-rc) ' "$o"
        awk '/ Sgurr-v9\.2-rc /{a=$4; ea=$5} / Sgurr-v9\.1 /{b=$4; eb=$5}
             END{ if (a && b) printf "   gap v9.1 -> v9.2-rc: %+.1f  (joint +/-%.1f)\n", a-b, sqrt(ea*ea+eb*eb) }' "$o"
        grep -a '^endings' "$ROOT/runs/pool_e/SUMMARY_v9.2-rc.txt" 2>/dev/null
    fi
} > "$RUN/summary.txt"
tee -a "$LOG" < "$RUN/summary.txt"
say "=== overnight chain finished ==="
