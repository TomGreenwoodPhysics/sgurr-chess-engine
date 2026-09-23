#!/usr/bin/env bash
# SCReLU: square the clipped activation instead of using it directly. Every
# modern engine does this and Sgurr does not, so it is the clearest remaining
# gap. Trained on the same S1 data at the same budget as the crelu net, so the
# match isolates the activation alone.
set -u
ROOT=/c/coding/Sgurr
LOG=$ROOT/runs/sgurr_x/screlu.log
BULLET=$ROOT/.tmp/bullet
PY=$ROOT/.venv/Scripts/python.exe
export CUDA_PATH="C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.4"
export PATH="/c/Users/green/.cargo/bin:/c/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v13.4/bin/x64:$PATH"
unset SGR_EVALFILE
say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

say "=== screlu start ==="
say "pausing SPSA"
taskkill //IM sgr_v90_batch_spsa.exe //F >/dev/null 2>&1
for p in $(powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -like '*spsa.py*' } | Select-Object -Expand ProcessId) -join ' '" 2>/dev/null); do
    taskkill //PID $p //T //F >/dev/null 2>&1
done
sleep 3

( cd $BULLET && cargo r -r -j 4 --features cuda --example sgurr_x_sc512 ) >>"$LOG" 2>&1
CK=$ROOT/.tmp/bullet_ckpt/sgurr_x_sc512-40
[ -f "$CK/quantised.bin" ] || { say "no FINAL checkpoint at -40, aborting"; exit 1; }

"$PY" $ROOT/nnue/sgurr_x/export.py "$CK/quantised.bin" $ROOT/nets/sgurr_x_sc512.nnue --hl 512 >>"$LOG" 2>&1

# -DSGR_SCRELU=1 is mandatory here. A crelu build loads this net happily and
# plays badly, with nothing in the logs to say why.
( cd $ROOT/sgurr_cpp && ./build.sh -r -o sprt_sc512.exe -DSGR_HL=512 -DSGR_SCRELU=1 \
    -DSGR_DEFAULT_NET='"C:/coding/Sgurr/nets/sgurr_x_sc512.nnue"' ) >>"$LOG" 2>&1
if ! $ROOT/sgurr_cpp/sprt_sc512.exe bench 8 2>&1 | grep -q "nnue: loaded"; then
    say "screlu net rejected at load -- check the int16 a*w bound"; exit 1
fi
say "built sprt_sc512.exe, nps $($ROOT/sgurr_cpp/sprt_sc512.exe bench 11 2>&1 | grep -oaE 'nps [0-9]+' | awk '{print $2}')"

say "--- screlu vs crelu, both HL=512, same S1 data, 1000 games ---"
$ROOT/benchmarks/tools/fastchess.exe \
  -engine cmd=$ROOT/sgurr_cpp/sprt_sc512.exe name=screlu \
  -engine cmd=$ROOT/sgurr_cpp/sprt_x512.exe name=crelu \
  -each tc=8+0.08 option.Hash=256 -rounds 500 -repeat -concurrency 7 \
  -openings file=$ROOT/testing/8moves_v3.pgn format=pgn order=random -recover \
  >$ROOT/runs/sgurr_x/match_screlu_vs_crelu.txt 2>&1
say "result: $(grep -aE 'Elo:' $ROOT/runs/sgurr_x/match_screlu_vs_crelu.txt | tail -1)"
taskkill //IM fastchess.exe //F >/dev/null 2>&1
taskkill //IM sprt_sc512.exe //F >/dev/null 2>&1
taskkill //IM sprt_x512.exe //F >/dev/null 2>&1

say "--- resuming SPSA ---"
( cd $ROOT && "$PY" testing/spsa.py --config testing/spsa_v90_batch_gen9.json --resume ) \
    >>$ROOT/runs/sgurr_x/spsa_driver.log 2>&1 &
say "=== screlu done; SPSA resumed ==="
