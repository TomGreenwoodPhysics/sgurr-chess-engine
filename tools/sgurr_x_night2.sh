#!/usr/bin/env bash
# Two short experiments, then SPSA for the rest of the night.
#   1. Material scaling: a scalar term akimbo measured beating its own eight
#      output buckets by +4.34 over 24,720 games.
#   2. SCReLU at QA=181: Renegade got +26.4 +/- 12.5 from this retune alone,
#      more than switching activation gave them. Our screlu at QA=255 measured
#      +5.91 +/- 16.93, i.e. flat, which is what a bad QA would look like.
set -u
ROOT=/c/coding/Sgurr
LOG=$ROOT/runs/sgurr_x/night2.log
BULLET=$ROOT/.tmp/bullet
PY=$ROOT/.venv/Scripts/python.exe
FC=$ROOT/benchmarks/tools/fastchess.exe
BOOK=$ROOT/testing/8moves_v3.pgn
export CUDA_PATH="C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.4"
export PATH="/c/Users/green/.cargo/bin:/c/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v13.4/bin/x64:$PATH"
unset SGR_EVALFILE
say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

race() {  # name, engineA, engineB, rounds
    say "--- $1 ($(( $4 * 2 )) games) ---"
    "$FC" -engine cmd="$2" name=new -engine cmd="$3" name=base \
        -each tc=8+0.08 option.Hash=256 -rounds $4 -repeat -concurrency 7 \
        -openings file="$BOOK" format=pgn order=random -recover \
        >$ROOT/runs/sgurr_x/match_$1.txt 2>&1
    say "$1: $(grep -aE 'Elo:' $ROOT/runs/sgurr_x/match_$1.txt | tail -1)"
    taskkill //IM fastchess.exe //F >/dev/null 2>&1
    taskkill //IM $(basename "$2") //F >/dev/null 2>&1
    taskkill //IM $(basename "$3") //F >/dev/null 2>&1
}

say "=== night 2 start ==="

# --- 1. material scaling, search-side only, same net both sides ---
if [ ! -f $ROOT/sgurr_cpp/sprt_ms512.exe ]; then
    ( cd $ROOT/sgurr_cpp && ./build.sh -r -o sprt_ms512.exe -DSGR_HL=512 -DSGR_MATSCALE=1 \
        -DSGR_DEFAULT_NET='"C:/coding/Sgurr/nets/sgurr_x_512.nnue"' ) >>"$LOG" 2>&1
fi
if $ROOT/sgurr_cpp/sprt_ms512.exe bench 8 2>&1 | grep -q "nnue: loaded"; then
    race matscale $ROOT/sgurr_cpp/sprt_ms512.exe $ROOT/sgurr_cpp/sprt_x512.exe 500
else
    say "matscale build did not load its net, skipping"
fi

# --- 2. screlu at QA=181 ---
if [ ! -f $ROOT/sgurr_cpp/sprt_sc181.exe ]; then
    say "--- training screlu QA=181 ---"
    ( cd $BULLET && cargo r -r -j 4 --features cuda --example sgurr_x_sc181 ) >>"$LOG" 2>&1
    CK=$ROOT/.tmp/bullet_ckpt/sgurr_x_sc181-40
    if [ -f "$CK/quantised.bin" ]; then
        "$PY" $ROOT/nnue/sgurr_x/export.py "$CK/quantised.bin" \
            $ROOT/nets/sgurr_x_sc181.nnue --hl 512 --qa 181 >>"$LOG" 2>&1
        ( cd $ROOT/sgurr_cpp && ./build.sh -r -o sprt_sc181.exe -DSGR_HL=512 \
            -DSGR_SCRELU=1 -DSGR_QA=181 \
            -DSGR_DEFAULT_NET='"C:/coding/Sgurr/nets/sgurr_x_sc181.nnue"' ) >>"$LOG" 2>&1
    else
        say "no FINAL sc181 checkpoint at -40"
    fi
fi
if [ -f $ROOT/sgurr_cpp/sprt_sc181.exe ] && $ROOT/sgurr_cpp/sprt_sc181.exe bench 8 2>&1 | grep -q "nnue: loaded"; then
    say "sc181 nps $($ROOT/sgurr_cpp/sprt_sc181.exe bench 11 2>&1 | grep -oaE 'nps [0-9]+' | awk '{print $2}')"
    race screlu_qa181 $ROOT/sgurr_cpp/sprt_sc181.exe $ROOT/sgurr_cpp/sprt_x512.exe 500
else
    say "sc181 unusable -- likely the qa/header check; see the log above"
fi

say "--- resuming SPSA for the rest of the night ---"
( cd $ROOT && "$PY" testing/spsa.py --config testing/spsa_v90_batch_gen9.json --resume ) \
    >>$ROOT/runs/sgurr_x/spsa_driver.log 2>&1 &
say "=== night 2 done; SPSA running ==="
