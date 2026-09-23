#!/usr/bin/env bash
# Sgurr-X X0: train 1024/768/512 on the public S1 data, export, SPRT each
# against v9.0, then restart the SPSA tune on a quiet machine.
#
# Self-contained on purpose: it must finish without supervision.
set -u

ROOT=/c/coding/Sgurr
LOG=$ROOT/runs/sgurr_x/overnight.log
BULLET=$ROOT/.tmp/bullet
DATA=$ROOT/data/sgurr_x/S1.bullet.bin
BOOK=$ROOT/testing/8moves_v3.pgn
FC=$ROOT/benchmarks/tools/fastchess.exe
PY=$ROOT/.venv/Scripts/python.exe

export CUDA_PATH="C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.4"
export PATH="/c/Users/green/.cargo/bin:/c/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v13.4/bin/x64:/c/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v13.4/bin:$PATH"
unset SGR_EVALFILE   # nets are baked in per binary; the env var would override both

say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

END_SB=$(grep -oE "end_superbatch: [0-9]+" $BULLET/examples/sgurr_x_1024.rs | grep -oE "[0-9]+")
say "=== sgurr-x overnight start (final superbatch = $END_SB) ==="

# 1. Wait for the decompressed data to stop growing.
say "waiting for $DATA"
last=0
while true; do
    [ -f "$DATA" ] || { sleep 20; continue; }
    cur=$(stat -c %s "$DATA")
    [ "$cur" -eq "$last" ] && [ "$cur" -gt 30000000000 ] && break
    last=$cur; sleep 20
done
say "data ready: $(( last / 1000000000 )) GB, $(( last / 32 )) positions"

# 2. Baseline: v9.0 search (HEAD defaults) with gen9 baked in.
if [ -f $ROOT/sgurr_cpp/sprt_base.exe ]; then
    say "baseline already built, reusing"
else
    say "building baseline (release, gen9)"
( cd $ROOT/sgurr_cpp && ./build.sh -r -o sprt_base.exe \
    -DSGR_DEFAULT_NET='"C:/coding/Sgurr/nets/gen9.nnue"' ) >>"$LOG" 2>&1
fi
$ROOT/sgurr_cpp/sprt_base.exe bench 8 2>&1 | grep -q "nnue: loaded" \
  || say "WARNING: baseline did not load gen9"

# 3. Train, export, build each width.
for HL in 1024 768 512; do
    if [ -f $ROOT/sgurr_cpp/sprt_x$HL.exe ]; then
        say "HL=$HL: engine already built, reusing"; continue
    fi
    say "--- HL=$HL: training ---"
    ( cd $BULLET && cargo r -r -j 4 --features cuda --example sgurr_x_$HL ) >>"$LOG" 2>&1
    CK=$ROOT/.tmp/bullet_ckpt/sgurr_x_hl$HL-$END_SB
    if [ ! -f "$CK/quantised.bin" ]; then
        say "HL=$HL: no FINAL checkpoint at superbatch $END_SB (training did not"
        say "         complete; partial checkpoints are deliberately not used)"
        continue
    fi
    say "HL=$HL: checkpoint $CK"

    "$PY" $ROOT/nnue/sgurr_x/export.py "$CK/quantised.bin" \
        $ROOT/nets/sgurr_x_$HL.nnue --hl $HL >>"$LOG" 2>&1 \
      || { say "HL=$HL: export failed"; continue; }

    ( cd $ROOT/sgurr_cpp && ./build.sh -r -o sprt_x$HL.exe -DSGR_HL=$HL \
        -DSGR_DEFAULT_NET="\"C:/coding/Sgurr/nets/sgurr_x_$HL.nnue\"" ) >>"$LOG" 2>&1
    if ! $ROOT/sgurr_cpp/sprt_x$HL.exe bench 8 2>&1 | grep -q "nnue: loaded"; then
        say "HL=$HL: engine did not load its net, skipping SPRT"; continue
    fi
    nps=$($ROOT/sgurr_cpp/sprt_x$HL.exe bench 11 2>&1 | grep -oE "nps [0-9]+" | awk '{print $2}')
    say "HL=$HL: built, $nps nps"
done

# 4. Fixed 1000-game screen per width. An SPRT at elo0=0/elo1=5 never crosses
#    a bound on a flat result and would burn its whole cap (~10h) per width.
for HL in 1024 768 512; do
    ENG=$ROOT/sgurr_cpp/sprt_x$HL.exe
    [ -f "$ENG" ] || continue
    say "--- HL=$HL: 1000-game screen vs v9.0 ---"
    OUT=$ROOT/runs/sgurr_x/match_hl$HL.txt
    "$FC" -engine cmd="$ENG" name=x$HL -engine cmd=$ROOT/sgurr_cpp/sprt_base.exe name=v90 \
        -each tc=8+0.08 option.Hash=256 -rounds 500 -repeat -concurrency 7 \
        -openings file="$BOOK" format=pgn order=random -recover \
        -sprt elo0=0 elo1=5 alpha=0.05 beta=0.05 >"$OUT" 2>&1
    say "HL=$HL: $(grep -aE 'Elo|Games:' "$OUT" | tail -2 | tr '\n' ' ')"
    taskkill //IM fastchess.exe //F >/dev/null 2>&1
    taskkill //IM sprt_x$HL.exe //F >/dev/null 2>&1
    taskkill //IM sprt_base.exe //F >/dev/null 2>&1
done

# 5. Machine is quiet now: restart the SPSA tune clean.
say "--- restarting SPSA clean ---"
rm -rf $ROOT/runs/spsa/v90_batch_gen9
( cd $ROOT && "$PY" testing/spsa.py --config testing/spsa_v90_batch_gen9.json ) \
    >>$ROOT/runs/sgurr_x/spsa_driver.log 2>&1 &
say "SPSA launched (pid $!)"
say "=== sgurr-x overnight done; SPSA now running ==="
