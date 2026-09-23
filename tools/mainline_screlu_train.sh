#!/usr/bin/env bash
# Retrain the gen9 net with SCReLU, for a like-for-like comparison against the
# shipped crelu net: same 102,011,689 positions, same lambda 0.8.
set -u
ROOT=/c/coding/Sgurr
LOG=$ROOT/runs/sgurr_x/mainline_screlu.log
say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

# --loader memory, not auto. At 102M positions auto picks the streaming path
# (--stream_threshold 60M), which ran at roughly one core and had not finished
# 22 epochs in 46 minutes. The in-memory path needs ~14 GB of the 31 available.
say "=== gen9 retrain with screlu (QA=181), memory loader ==="
say "unbuffered so epoch progress is visible while it runs"
cd $ROOT || exit 1
./.venv/Scripts/python.exe -u nnue/train.py \
    --data data/gen9_102m/all.bin \
    --out nets/gen9_screlu.nnue \
    --screlu --lambda_ 0.8 --epochs 22     --loader memory >>"$LOG" 2>&1
if [ -f nets/gen9_screlu.nnue ]; then
    say "trained: $(ls -l nets/gen9_screlu.nnue | awk '{print $5}') bytes"
    ( cd sgurr_cpp && ./build.sh -r -o sprt_main_sc.exe -DSGR_SCRELU=1 -DSGR_QA=181 \
        -DSGR_DEFAULT_NET='"C:/coding/Sgurr/nets/gen9_screlu.nnue"' ) >>"$LOG" 2>&1
    if $ROOT/sgurr_cpp/sprt_main_sc.exe bench 8 2>&1 | grep -q "nnue: loaded"; then
        say "built sprt_main_sc.exe, nps $($ROOT/sgurr_cpp/sprt_main_sc.exe bench 11 2>&1 | grep -oaE 'nps [0-9]+' | awk '{print $2}')"
    else
        say "net rejected at load -- check the QA/int16 guard above"
    fi
else
    say "training produced no net"
fi
say "=== retrain done ==="
