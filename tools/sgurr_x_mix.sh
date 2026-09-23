#!/usr/bin/env bash
# All the data in one go: interleave S1 + S2 and train once, instead of
# training S1 then fine-tuning on S2. The sequential version measured -19.5,
# which on a ~400k-parameter net most likely means the second pass overwrote
# the first rather than that S2 is bad data.
set -u
ROOT=/c/coding/Sgurr
LOG=$ROOT/runs/sgurr_x/mix.log
BULLET=$ROOT/.tmp/bullet
PY=$ROOT/.venv/Scripts/python.exe
D=$ROOT/data/sgurr_x
export CUDA_PATH="C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.4"
export PATH="/c/Users/green/.cargo/bin:/c/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v13.4/bin/x64:$PATH"
unset SGR_EVALFILE
say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

say "=== interleaved S1+S2 start ==="
say "waiting for the bucket sweep to finish"
while ! grep -aq "bucket sweep done" $ROOT/runs/sgurr_x/buckets.log 2>/dev/null; do sleep 30; done

say "pausing SPSA"
taskkill //IM sgr_v90_batch_spsa.exe //F >/dev/null 2>&1
for p in $(powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -like '*spsa.py*' } | Select-Object -Expand ProcessId) -join ' '" 2>/dev/null); do
    taskkill //PID $p //T //F >/dev/null 2>&1
done
sleep 3
say "SPSA paused at iteration $("$PY" -c "import json;print(json.load(open('$ROOT/runs/spsa/v90_batch_gen9/state.json'))['iteration'])")"

if [ -f $D/S1S2.bullet.bin ]; then
    say "interleaved file already present, reusing"
else
    say "interleaving S1 (1.23B) + S2 (0.55B)"
    $BULLET/target/release/bullet-utils.exe interleave \
        $D/S1.bullet.bin $D/S2.bullet.bin -o $D/S1S2.bullet.bin >>"$LOG" 2>&1 \
      || { say "interleave failed"; exit 1; }
fi
SZ=$(stat -c %s $D/S1S2.bullet.bin)
say "combined: $(( SZ / 32 )) positions ($(( SZ / 1000000000 )) GB)"

say "--- training on the combined set, 70 superbatches ---"
( cd $BULLET && cargo r -r -j 4 --features cuda --example sgurr_x_mix512 ) >>"$LOG" 2>&1
CK=$ROOT/.tmp/bullet_ckpt/sgurr_x_mix512-70
[ -f "$CK/quantised.bin" ] || { say "no FINAL checkpoint at -70, aborting"; exit 1; }

"$PY" $ROOT/nnue/sgurr_x/export.py "$CK/quantised.bin" $ROOT/nets/sgurr_x_mix512.nnue --hl 512 >>"$LOG" 2>&1
( cd $ROOT/sgurr_cpp && ./build.sh -r -o sprt_mix512.exe -DSGR_HL=512 \
    -DSGR_DEFAULT_NET='"C:/coding/Sgurr/nets/sgurr_x_mix512.nnue"' ) >>"$LOG" 2>&1
$ROOT/sgurr_cpp/sprt_mix512.exe bench 8 2>&1 | grep -q "nnue: loaded" || { say "net did not load"; exit 1; }
say "built sprt_mix512.exe"

# Direct paired comparison against S1-only: isolates the data change alone.
say "--- interleaved S1+S2 vs S1-only, both HL=512, 1000 games ---"
$ROOT/benchmarks/tools/fastchess.exe \
  -engine cmd=$ROOT/sgurr_cpp/sprt_mix512.exe name=mix \
  -engine cmd=$ROOT/sgurr_cpp/sprt_x512.exe name=s1only \
  -each tc=8+0.08 option.Hash=256 -rounds 500 -repeat -concurrency 7 \
  -openings file=$ROOT/testing/8moves_v3.pgn format=pgn order=random -recover \
  >$ROOT/runs/sgurr_x/match_mix_vs_s1.txt 2>&1
say "result: $(grep -aE 'Elo:' $ROOT/runs/sgurr_x/match_mix_vs_s1.txt | tail -1)"
taskkill //IM fastchess.exe //F >/dev/null 2>&1
taskkill //IM sprt_mix512.exe //F >/dev/null 2>&1
taskkill //IM sprt_x512.exe //F >/dev/null 2>&1

say "--- resuming SPSA ---"
( cd $ROOT && "$PY" testing/spsa.py --config testing/spsa_v90_batch_gen9.json --resume ) \
    >>$ROOT/runs/sgurr_x/spsa_driver.log 2>&1 &
say "=== interleaved run done; SPSA resumed ==="
