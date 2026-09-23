#!/usr/bin/env bash
# King buckets at 1.23B positions. The roadmap deferred this retest until the
# dataset was an order of magnitude bigger; it now is (~123M positions per
# bucket against ~7M when it last measured ~0).
set -u
ROOT=/c/coding/Sgurr
LOG=$ROOT/runs/sgurr_x/kb.log
BULLET=$ROOT/.tmp/bullet
PY=$ROOT/.venv/Scripts/python.exe
MAP=$(cat $ROOT/.tmp/bucket_map64.txt)
export CUDA_PATH="C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.4"
export PATH="/c/Users/green/.cargo/bin:/c/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v13.4/bin/x64:$PATH"
unset SGR_EVALFILE
say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

say "=== king buckets start ==="
say "waiting for the S2 chain to finish"
while ! grep -aq "S2 done" $ROOT/runs/sgurr_x/s2.log 2>/dev/null; do sleep 30; done
say "S2 chain finished; pausing SPSA for the GPU + match work"
taskkill //IM sgr_v90_batch_spsa.exe //F >/dev/null 2>&1
for p in $(powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -like '*spsa.py*' } | Select-Object -Expand ProcessId) -join ' '" 2>/dev/null); do
    taskkill //PID $p //T //F >/dev/null 2>&1
done
sleep 3
say "SPSA paused at $($PY -c "import json;print(json.load(open(r'$ROOT/runs/spsa/v90_batch_gen9/state.json'))['iteration'])" 2>/dev/null)"

( cd $BULLET && cargo r -r -j 4 --features cuda --example sgurr_x_kb512 ) >>"$LOG" 2>&1
CK=$ROOT/.tmp/bullet_ckpt/sgurr_x_kb512-40
if [ ! -f "$CK/quantised.bin" ]; then say "no FINAL kb checkpoint at -40, aborting"; exit 1; fi

"$PY" $ROOT/nnue/sgurr_x/export.py "$CK/quantised.bin" $ROOT/nets/sgurr_x_kb512.nnue \
    --hl 512 --bucket-map "$MAP" >>"$LOG" 2>&1 || { say "export failed"; exit 1; }
say "exported: $(tail -2 "$LOG" | head -1)"

( cd $ROOT/sgurr_cpp && ./build.sh -r -o sprt_xkb512.exe -DSGR_HL=512 \
    -DSGR_DEFAULT_NET='"C:/coding/Sgurr/nets/sgurr_x_kb512.nnue"' ) >>"$LOG" 2>&1
if ! $ROOT/sgurr_cpp/sprt_xkb512.exe bench 8 2>&1 | grep -q "nnue: loaded"; then
    say "kb net did not load, aborting"; exit 1
fi
say "kb engine built: $($ROOT/sgurr_cpp/sprt_xkb512.exe bench 8 2>&1 | grep -a 'nnue: loaded')"

# Against the plain-768 512 net on the same data: isolates king buckets alone.
say "--- king buckets vs plain 768, both HL=512, same S1 data ---"
$ROOT/benchmarks/tools/fastchess.exe \
  -engine cmd=$ROOT/sgurr_cpp/sprt_xkb512.exe name=kb \
  -engine cmd=$ROOT/sgurr_cpp/sprt_x512.exe name=plain \
  -each tc=8+0.08 option.Hash=256 -rounds 500 -repeat -concurrency 7 \
  -openings file=$ROOT/testing/8moves_v3.pgn format=pgn order=random -recover \
  >$ROOT/runs/sgurr_x/match_kb_vs_plain.txt 2>&1
say "result: $(grep -aE 'Elo:' $ROOT/runs/sgurr_x/match_kb_vs_plain.txt | tail -1)"
taskkill //IM fastchess.exe //F >/dev/null 2>&1
taskkill //IM sprt_xkb512.exe //F >/dev/null 2>&1
taskkill //IM sprt_x512.exe //F >/dev/null 2>&1

say "--- resuming SPSA ---"
( cd $ROOT && "$PY" testing/spsa.py --config testing/spsa_v90_batch_gen9.json --resume ) \
    >>$ROOT/runs/sgurr_x/spsa_driver.log 2>&1 &
say "=== king buckets done; SPSA resumed ==="
