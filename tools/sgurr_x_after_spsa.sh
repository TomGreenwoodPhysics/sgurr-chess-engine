#!/usr/bin/env bash
# Waits for the SPSA tune to finish, then runs the three measurements that are
# owed, hardest-won first. Nothing here needs the GPU.
set -u
ROOT=/c/coding/Sgurr
LOG=$ROOT/runs/sgurr_x/after_spsa.log
PY=$ROOT/.venv/Scripts/python.exe
FC=$ROOT/benchmarks/tools/fastchess.exe
BOOK=$ROOT/testing/8moves_v3.pgn
TUNED=$ROOT/runs/spsa/v90_batch_gen9/tuned.json
unset SGR_EVALFILE
say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

race() {  # label, engineA, optsA, engineB, optsB, rounds
    say "--- $1 ($(( $6 * 2 )) games) ---"
    "$FC" -engine cmd="$2" name=new $3 -engine cmd="$4" name=base $5 \
        -each tc=8+0.08 option.Hash=256 -rounds $6 -repeat -concurrency 7 \
        -openings file="$BOOK" format=pgn order=random -recover \
        >$ROOT/runs/sgurr_x/match_$1.txt 2>&1
    say "$1: $(grep -aE 'Elo:' $ROOT/runs/sgurr_x/match_$1.txt | tail -1)"
    taskkill //IM fastchess.exe //F >/dev/null 2>&1
    taskkill //IM "$(basename "$2")" //F >/dev/null 2>&1
    taskkill //IM "$(basename "$4")" //F >/dev/null 2>&1
}

say "=== waiting for SPSA to finish ==="
while [ ! -f "$TUNED" ]; do sleep 120; done
sleep 30
say "SPSA done. tuned.json: $(cat "$TUNED" | tr -d '\n ' | cut -c1-160)"

# Make sure the tune's own driver has exited before we take the machine.
for p in $(powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -like '*spsa.py*' } | Select-Object -Expand ProcessId) -join ' '" 2>/dev/null); do
    taskkill //PID $p //T //F >/dev/null 2>&1
done
taskkill //IM sgr_v90_batch_spsa.exe //F >/dev/null 2>&1
sleep 3

# --- 1. Did 31 hours of tuning buy anything? Same binary, options only. ---
OPTS=$("$PY" -c "
import json
d = json.load(open(r'$TUNED'))
print(' '.join(f'option.{k}={int(round(v))}' for k, v in d.items()))
" 2>/dev/null)
if [ -n "$OPTS" ]; then
    say "tuned options: $OPTS"
    race spsa_tuned $ROOT/sgurr_cpp/sgr_v90_batch_spsa.exe "$OPTS" \
                    $ROOT/sgurr_cpp/sgr_v90_batch_spsa.exe "" 500
else
    say "could not read tuned.json, skipping the SPSA validation"
fi

# --- 2. Correction history, on top of the best net we have. ---
if [ ! -f $ROOT/sgurr_cpp/sprt_sc181_ch.exe ]; then
    ( cd $ROOT/sgurr_cpp && ./build.sh -r -o sprt_sc181_ch.exe -DSGR_HL=512 \
        -DSGR_SCRELU=1 -DSGR_QA=181 -DSGR_CORRHIST=1 \
        -DSGR_DEFAULT_NET='"C:/coding/Sgurr/nets/sgurr_x_sc181.nnue"' ) >>"$LOG" 2>&1
fi
if $ROOT/sgurr_cpp/sprt_sc181_ch.exe bench 8 2>&1 | grep -q "nnue: loaded"; then
    race corrhist $ROOT/sgurr_cpp/sprt_sc181_ch.exe "" $ROOT/sgurr_cpp/sprt_sc181.exe "" 500
else
    say "corrhist build did not load its net, skipping"
fi

# --- 3. The headline: best Sgurr-X against the shipped engine. ---
race sc181_vs_v90 $ROOT/sgurr_cpp/sprt_sc181.exe "" $ROOT/sgurr_cpp/sprt_base.exe "" 500

say "=== all three done ==="
