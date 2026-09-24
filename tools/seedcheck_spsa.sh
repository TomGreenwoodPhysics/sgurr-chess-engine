#!/usr/bin/env bash
# Day run after the cosine overnight: check the second cosine seed against
# v9.1, then SPSA-tune the 17 untouched search parameters on whichever net won.
# Prediction: benchmarks/v91_seedcheck_spsa_prediction.md.
#
#   tools/seedcheck_spsa.sh           wait for the overnight run, then go
#   tools/seedcheck_spsa.sh --check   preflight only, no games
#   tools/seedcheck_spsa.sh --stop    stop this run and its engines; the tune resumes later
#
# The tune checkpoints every iteration. Relaunching picks it up where it stopped.
set -u

ROOT=/c/coding/Sgurr
CPP=$ROOT/sgurr_cpp
RUN=$ROOT/runs/cosine
LOG=$RUN/day.log
PY=$ROOT/.venv/Scripts/python.exe
FC=$ROOT/benchmarks/tools/fastchess.exe
BOOK=$ROOT/testing/8moves_v3.pgn

REF_EXE=sprt_v91_ref.exe
S1_EXE=sprt_v91_cos_s1.exe
SPSA_EXE=sgr_v91_spsa.exe
TEMPLATE=$ROOT/testing/spsa_v91_untuned.json
SPSA_DIR=$ROOT/runs/spsa/v91_untuned
SPSA_CFG=$SPSA_DIR/config.json
SEED_ROUNDS=1000                 # 2,000-game cap

mkdir -p "$RUN"
unset SGR_EVALFILE
say() { echo "[$(date '+%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
die() { say "STOP: $*"; say "=== day run stopped, needs a human ==="; exit 1; }

# Windows processes whose command line contains $1, minus this shell and
# whatever shell launched --stop (its command line names this script too).
procs_matching() {
    local me
    me=$(cat /proc/$$/winpid 2>/dev/null || echo 0)
    powershell -NoProfile -Command "(Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -like '*$1*' -and \$_.CommandLine -notlike '*--stop*' -and \$_.ProcessId -ne $me -and \$_.Name -ne 'powershell.exe' } | Select-Object -Expand ProcessId) -join ' '" 2>/dev/null | tr -d '\r'
}
stop_engines() {
    for p in fastchess.exe $REF_EXE $S1_EXE $SPSA_EXE; do
        taskkill //IM "$p" //F >/dev/null 2>&1
    done
    sleep 3
}

if [ "${1:-}" = "--stop" ]; then
    for pid in $(procs_matching seedcheck_spsa.sh) $(procs_matching spsa.py); do
        taskkill //PID "$pid" //T //F >/dev/null 2>&1
    done
    stop_engines
    say "stopped by --stop; relaunch to resume the tune"
    exit 0
fi

CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1
say "=== day run $([ $CHECK_ONLY = 1 ] && echo '(check only)') ==="

# --- wait for the overnight run, however it ended ------------------------
if [ $CHECK_ONLY = 0 ]; then
    if [ -n "$(procs_matching cosine_overnight.sh)" ]; then
        say "overnight run still going, waiting for it (checked every 10 min)"
        while [ -n "$(procs_matching cosine_overnight.sh)" ]; do sleep 600; done
        say "overnight run finished"
    fi
fi
busy=$(powershell -NoProfile -Command "(Get-Process fastchess,datagen -ErrorAction SilentlyContinue | Measure-Object).Count" 2>/dev/null | tr -d '\r ')
[ "${busy:-0}" = "0" ] || die "$busy fastchess/datagen process(es) still running"

# --- which net the tune uses ---------------------------------------------
# The cosine net only if it passed its SPRT: that is the net a v9.2 would ship.
if grep -aq 'H1 was accepted' "$RUN/sprt.txt" 2>/dev/null; then
    NET=nets/gen9_screlu_cos.nnue
    say "overnight SPRT accepted H1: tuning on the cosine net"
else
    NET=nets/gen9_screlu.nnue
    say "overnight SPRT did not accept H1 (or did not finish): tuning on the v9.1 net"
fi
[ -f "$ROOT/$NET" ] || die "missing $NET"

# --- SPSA engine and config ----------------------------------------------
if [ ! -f "$CPP/$SPSA_EXE" ]; then
    say "building $SPSA_EXE"
    ( cd "$CPP" && ./build.sh -r -o "$SPSA_EXE" --version 9.1-spsa \
        -DSGR_DEFAULT_NET='"C:/coding/Sgurr/nets/gen9_screlu.nnue"' ) >>"$LOG" 2>&1 \
        || die "build of $SPSA_EXE failed"
fi
# spsa.py hands the net over through SGR_EVALFILE, so check that exact route.
got=$(SGR_EVALFILE="$(cygpath -m "$ROOT/$NET")" sh -c "printf 'uci\nquit\n' | '$CPP/$SPSA_EXE' 2>&1" \
      | grep -ao 'nnue: loaded [^ ]*' | head -1)
case "$got" in
    *"$(basename "$NET")") say "$SPSA_EXE: $got" ;;
    *) die "$SPSA_EXE did not load $NET through SGR_EVALFILE (got '${got:-hand-crafted eval}')" ;;
esac

# --check validates a throwaway copy: writing the real config now would pin
# the tune to whichever net looks right before the overnight result exists.
[ $CHECK_ONLY = 1 ] && SPSA_CFG=$RUN/spsa_check_config.json && rm -f "$SPSA_CFG"
mkdir -p "$SPSA_DIR"
if [ -f "$SPSA_CFG" ]; then
    have=$("$PY" -c "import json,sys; print(json.load(open(sys.argv[1]))['net'])" "$(cygpath -m "$SPSA_CFG")")
    [ "$have" = "$NET" ] || die "the tune in progress uses $have, not $NET; one tune, one net"
    say "resuming the tune on $NET"
else
    "$PY" - "$(cygpath -m "$TEMPLATE")" "$(cygpath -m "$SPSA_CFG")" "$NET" <<'EOF' || die "could not write the tune config"
import json, sys
cfg = json.load(open(sys.argv[1]))
cfg["net"] = sys.argv[3]
json.dump(cfg, open(sys.argv[2], "w"), indent=2)
EOF
    say "wrote $SPSA_CFG with net $NET"
fi
( cd "$ROOT" && "$PY" testing/spsa.py --config "$(cygpath -m "$SPSA_CFG")" --status ) >>"$LOG" 2>&1 \
    || die "spsa.py rejected the config, see $LOG"

if [ $CHECK_ONLY = 1 ]; then
    say "=== check passed ==="
    exit 0
fi

# --- 1. second cosine seed against v9.1 ----------------------------------
if [ ! -f "$CPP/$S1_EXE" ]; then
    say "no $S1_EXE (overnight stopped early?): skipping the seed check"
elif grep -aq 'Finished match' "$RUN/seedcheck.txt" 2>/dev/null; then
    say "seed check already finished, reusing"
else
    say "seed check: cosine seed 1 vs v9.1, 8+0.08, [0, 5], up to $((SEED_ROUNDS * 2)) games"
    stop_engines
    "$FC" -engine cmd="$CPP/$S1_EXE" name=cosine_s1 -engine cmd="$CPP/$REF_EXE" name=v91 \
        -each tc=8+0.08 option.Hash=256 -rounds $SEED_ROUNDS -repeat -concurrency 7 \
        -openings file="$BOOK" format=pgn order=random -recover \
        -sprt elo0=0 elo1=5 alpha=0.05 beta=0.05 \
        -pgnout file="$(cygpath -m "$RUN/seedcheck.pgn")" \
        >"$RUN/seedcheck.txt" 2>&1
    stop_engines
fi
if [ -f "$RUN/seedcheck.txt" ]; then
    if   grep -aq 'H1 was accepted' "$RUN/seedcheck.txt"; then v=H1
    elif grep -aq 'H0 was accepted' "$RUN/seedcheck.txt"; then v=H0
    else v="no decision"; fi
    grep -aoE 'Finished game [0-9]+ \([^)]*\): [^{]*\{[^}]*\}' "$RUN/seedcheck.txt" \
        | sed -E 's/.*\{(.*)\}$/\1/' > "$RUN/endings.tmp"
    {
        echo "Seed check, cosine seed 1 vs v9.1, 8+0.08, [0, 5]: $v"
        echo "  $(grep -aE '^Elo:' "$RUN/seedcheck.txt" | tail -1)"
        echo "  $(grep -aE '^Games:' "$RUN/seedcheck.txt" | tail -1)"
        echo "  endings: $(wc -l < "$RUN/endings.tmp" | tr -d ' ') games, $(grep -cvE 'mates$|^Draw by ' "$RUN/endings.tmp") abnormal"
        echo "Seed 0 overnight: $(grep -aE '^Elo:' "$RUN/sprt.txt" 2>/dev/null | tail -1)"
    } > "$RUN/SEEDCHECK.txt"
    tee -a "$LOG" < "$RUN/SEEDCHECK.txt"
fi

# --- 2. SPSA, until it finishes or --stop --------------------------------
say "SPSA on $NET: 17 parameters, 5,000 iterations of 8 games. Resumable."
stop_engines
( cd "$ROOT" && "$PY" -u testing/spsa.py --config "$(cygpath -m "$SPSA_CFG")" ) >>"$SPSA_DIR/driver.log" 2>&1
say "spsa.py exited: $(tail -1 "$SPSA_DIR/driver.log")"
say "=== day run done ==="
