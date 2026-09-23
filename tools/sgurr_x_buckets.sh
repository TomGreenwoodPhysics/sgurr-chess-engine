#!/usr/bin/env bash
# Two questions: what is king-bucketed Sgurr-X actually worth against v9.0,
# and do more than 10 buckets pay now that 10 does?
set -u
ROOT=/c/coding/Sgurr
LOG=$ROOT/runs/sgurr_x/buckets.log
BULLET=$ROOT/.tmp/bullet
PY=$ROOT/.venv/Scripts/python.exe
FC=$ROOT/benchmarks/tools/fastchess.exe
BOOK=$ROOT/testing/8moves_v3.pgn
export CUDA_PATH="C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.4"
export PATH="/c/Users/green/.cargo/bin:/c/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v13.4/bin/x64:$PATH"
unset SGR_EVALFILE
say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

say "=== bucket sweep start ==="
taskkill //IM sgr_v90_batch_spsa.exe //F >/dev/null 2>&1
for p in $(powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -like '*spsa.py*' } | Select-Object -Expand ProcessId) -join ' '" 2>/dev/null); do
    taskkill //PID $p //T //F >/dev/null 2>&1
done
sleep 3
say "SPSA paused at iteration $("$PY" -c "import json;print(json.load(open('$ROOT/runs/spsa/v90_batch_gen9/state.json'))['iteration'])")"

for N in 16 32; do
    if [ -f $ROOT/sgurr_cpp/sprt_kb${N}.exe ]; then
        say "$N buckets: engine already built, skipping training"
        continue
    fi
    say "--- training $N buckets ---"
    ( cd $BULLET && cargo r -r -j 4 --features cuda --example sgurr_x_kb${N}_512 ) >>"$LOG" 2>&1
    CK=$ROOT/.tmp/bullet_ckpt/sgurr_x_kb${N}_512-40
    [ -f "$CK/quantised.bin" ] || { say "$N: no FINAL checkpoint, skipping"; continue; }
    "$PY" $ROOT/nnue/sgurr_x/export.py "$CK/quantised.bin" $ROOT/nets/sgurr_x_kb${N}.nnue \
        --hl 512 --bucket-map "$(cat $ROOT/.tmp/bucket_map${N}.txt)" >>"$LOG" 2>&1 \
      || { say "$N: export failed"; continue; }
    ( cd $ROOT/sgurr_cpp && ./build.sh -r -o sprt_kb${N}.exe -DSGR_HL=512 \
        -DSGR_DEFAULT_NET="\"C:/coding/Sgurr/nets/sgurr_x_kb${N}.nnue\"" ) >>"$LOG" 2>&1
    $ROOT/sgurr_cpp/sprt_kb${N}.exe bench 8 2>&1 | grep -q "nnue: loaded" \
      && say "$N buckets built: $($ROOT/sgurr_cpp/sprt_kb${N}.exe bench 8 2>&1 | grep -ao 'k=[0-9]*')" \
      || say "$N: net did not load"
done

run_match() {  # name, engine, rounds
    say "--- $1 vs v9.0 ($(( $3 * 2 )) games) ---"
    "$FC" -engine cmd="$2" name="$1" -engine cmd=$ROOT/sgurr_cpp/sprt_base.exe name=v90 \
        -each tc=8+0.08 option.Hash=256 -rounds $3 -repeat -concurrency 7 \
        -openings file="$BOOK" format=pgn order=random -recover \
        >$ROOT/runs/sgurr_x/match_$1_vs_v90.txt 2>&1
    say "$1 vs v9.0: $(grep -aE 'Elo:' $ROOT/runs/sgurr_x/match_$1_vs_v90.txt | tail -1)"
    taskkill //IM fastchess.exe //F >/dev/null 2>&1
    taskkill //IM $(basename "$2") //F >/dev/null 2>&1
    taskkill //IM sprt_base.exe //F >/dev/null 2>&1
}

# Headline first, at full precision, in case anything later fails.
run_match kb10 $ROOT/sgurr_cpp/sprt_xkb512.exe 500
[ -f $ROOT/sgurr_cpp/sprt_kb16.exe ] && run_match kb16 $ROOT/sgurr_cpp/sprt_kb16.exe 300
[ -f $ROOT/sgurr_cpp/sprt_kb32.exe ] && run_match kb32 $ROOT/sgurr_cpp/sprt_kb32.exe 300

say "--- resuming SPSA ---"
( cd $ROOT && "$PY" testing/spsa.py --config testing/spsa_v90_batch_gen9.json --resume ) \
    >>$ROOT/runs/sgurr_x/spsa_driver.log 2>&1 &
say "=== bucket sweep done; SPSA resumed ==="
