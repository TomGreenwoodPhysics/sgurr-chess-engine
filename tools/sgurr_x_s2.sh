#!/usr/bin/env bash
# S2 fine-tune: retrain the finished S1 512 net on Lc0-derived data, then
# measure what S2 alone added by racing it against the S1-only net.
set -u
ROOT=/c/coding/Sgurr
LOG=$ROOT/runs/sgurr_x/s2.log
BULLET=$ROOT/.tmp/bullet
PY=$ROOT/.venv/Scripts/python.exe
export CUDA_PATH="C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.4"
export PATH="/c/Users/green/.cargo/bin:/c/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v13.4/bin/x64:$PATH"
unset SGR_EVALFILE
say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

say "=== S2 fine-tune start ==="
last=0
while true; do
    [ -f $ROOT/data/sgurr_x/S2.bullet.bin ] || { sleep 15; continue; }
    cur=$(stat -c %s $ROOT/data/sgurr_x/S2.bullet.bin)
    [ "$cur" -eq "$last" ] && [ "$cur" -gt 15000000000 ] && break
    last=$cur; sleep 15
done
say "S2 ready: $(( last / 32 )) positions"

( cd $BULLET && cargo r -r -j 4 --features cuda --example sgurr_x_512_s2 ) >>"$LOG" 2>&1
CK=$ROOT/.tmp/bullet_ckpt/sgurr_x_hl512_s2-20
if [ ! -f "$CK/quantised.bin" ]; then say "no FINAL S2 checkpoint at -20, aborting"; exit 1; fi
say "S2 checkpoint ok"

"$PY" $ROOT/nnue/sgurr_x/export.py "$CK/quantised.bin" $ROOT/nets/sgurr_x_512_s2.nnue --hl 512 >>"$LOG" 2>&1
( cd $ROOT/sgurr_cpp && ./build.sh -r -o sprt_x512s2.exe -DSGR_HL=512 \
    -DSGR_DEFAULT_NET='"C:/coding/Sgurr/nets/sgurr_x_512_s2.nnue"' ) >>"$LOG" 2>&1
$ROOT/sgurr_cpp/sprt_x512s2.exe bench 8 2>&1 | grep -q "nnue: loaded" || { say "net did not load"; exit 1; }
say "built sprt_x512s2.exe"

# S2-finetuned vs S1-only, both HL=512: isolates what the Lc0 data added.
say "--- S2 vs S1-only (both 512) ---"
$ROOT/benchmarks/tools/fastchess.exe \
  -engine cmd=$ROOT/sgurr_cpp/sprt_x512s2.exe name=s2 \
  -engine cmd=$ROOT/sgurr_cpp/sprt_x512.exe name=s1 \
  -each tc=8+0.08 option.Hash=256 -rounds 500 -repeat -concurrency 7 \
  -openings file=$ROOT/testing/8moves_v3.pgn format=pgn order=random -recover \
  >$ROOT/runs/sgurr_x/match_s2_vs_s1.txt 2>&1
say "result: $(grep -aE 'Elo:' $ROOT/runs/sgurr_x/match_s2_vs_s1.txt | tail -1)"
taskkill //IM fastchess.exe //F >/dev/null 2>&1
taskkill //IM sprt_x512s2.exe //F >/dev/null 2>&1
taskkill //IM sprt_x512.exe //F >/dev/null 2>&1

say "--- resuming SPSA from iteration 721 ---"
( cd $ROOT && "$PY" testing/spsa.py --config testing/spsa_v90_batch_gen9.json --resume ) \
    >>$ROOT/runs/sgurr_x/spsa_driver.log 2>&1 &
say "=== S2 done; SPSA resumed ==="
