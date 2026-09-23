#!/usr/bin/env bash
# Measure the bundle as a unit before calibrating it.
#
# Batch pruning compares the STATIC EVAL against tuned margins (RazorMargin=500,
# FutMargin=144, NmpEvalDiv=71). Those were fitted against the crelu eval
# distribution. SCReLU changes that distribution, so the two changes can
# interfere even though each is positive alone. This is the test for that.
set -u
ROOT=/c/coding/Sgurr
LOG=$ROOT/runs/sgurr_x/bundle.log
FC=$ROOT/benchmarks/tools/fastchess.exe
BOOK=$ROOT/testing/8moves_v3.pgn
unset SGR_EVALFILE
say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

say "=== waiting for SPRT 2 ==="
while ! grep -aq "2. screlu vs v9.0:" $ROOT/runs/sgurr_x/mainline_sprts.log 2>/dev/null; do sleep 60; done
sleep 20
SC=$(grep -a "2. screlu vs v9.0:" $ROOT/runs/sgurr_x/mainline_sprts.log | tail -1)
say "SPRT 2 was: $SC"

# Tuned values are compiled in as defaults now, so the gauntlet gets them too.
say "building the bundle: batch toggles + screlu QA=181 + tuned defaults"
( cd $ROOT/sgurr_cpp && ./build.sh -r -o sprt_bundle.exe \
    -DSGR_IIR=1 -DSGR_NMPSCALE=1 -DSGR_RAZOR=1 -DSGR_FUTILITY=1 -DSGR_SEEPRUNE=1 \
    -DSGR_HISTPRUNE=1 -DSGR_CAPHIST=1 -DSGR_ROOTPVS=1 -DSGR_EVALSCALE=1 \
    -DSGR_SCRELU=1 -DSGR_QA=181 \
    -DSGR_DEFAULT_NET='"C:/coding/Sgurr/nets/gen9_screlu.nnue"' ) >>"$LOG" 2>&1
if ! $ROOT/sgurr_cpp/sprt_bundle.exe bench 8 2>&1 | grep -q "nnue: loaded"; then
    say "bundle did not load its net, stopping"; exit 1
fi
# Confirm the tuned defaults actually compiled in.
say "defaults check: $(printf 'uci\nquit\n' | $ROOT/sgurr_cpp/sprt_bundle.exe 2>/dev/null | grep -aE 'HistLmrDiv|RazorMargin' | grep -aoE 'default [0-9]+' | tr '\n' ' ')"

say "=== bundle vs v9.0 (1000 games) ==="
"$FC" -engine cmd=$ROOT/sgurr_cpp/sprt_bundle.exe name=bundle \
      -engine cmd=$ROOT/sgurr_cpp/sprt_base.exe name=v90 \
  -each tc=8+0.08 option.Hash=256 -rounds 500 -repeat -concurrency 7 \
  -openings file="$BOOK" format=pgn order=random -recover \
  >$ROOT/runs/sgurr_x/match_bundle.txt 2>&1
RES=$(grep -aE 'Elo:' $ROOT/runs/sgurr_x/match_bundle.txt | tail -1)
say "bundle vs v9.0: $RES"
taskkill //IM fastchess.exe //F >/dev/null 2>&1
taskkill //IM sprt_bundle.exe //F >/dev/null 2>&1
taskkill //IM sprt_base.exe //F >/dev/null 2>&1

# Only calibrate something that measured clearly positive.
ELO=$(echo "$RES" | grep -aoE 'Elo: -?[0-9]+' | grep -aoE '\-?[0-9]+' | head -1)
if [ -n "$ELO" ] && [ "$ELO" -ge 40 ]; then
    say "bundle is +$ELO: starting the pool calibration at target +/-10"
    cd $ROOT && ./tools/run_calibrate.sh v9.1 sprt_bundle.exe 1 500 10 \
        >>$ROOT/runs/sgurr_x/calibrate_v91.log 2>&1
    say "calibration finished"
else
    say "bundle measured '$ELO' -- below the +40 bar. That is the interference"
    say "signal: compare against +90.2 (SPRT 1) and SPRT 2."
    say "Falling back to calibrating batch+tuned alone, which measured +90.2."
    ( cd $ROOT/sgurr_cpp && ./build.sh -r -o sprt_v91.exe         -DSGR_IIR=1 -DSGR_NMPSCALE=1 -DSGR_RAZOR=1 -DSGR_FUTILITY=1 -DSGR_SEEPRUNE=1         -DSGR_HISTPRUNE=1 -DSGR_CAPHIST=1 -DSGR_ROOTPVS=1 -DSGR_EVALSCALE=1         -DSGR_DEFAULT_NET='"C:/coding/Sgurr/nets/gen9.nnue"' ) >>"$LOG" 2>&1
    if $ROOT/sgurr_cpp/sprt_v91.exe bench 8 2>&1 | grep -q "nnue: loaded"; then
        say "calibrating batch+tuned (no screlu) at target +/-10"
        cd $ROOT && ./tools/run_calibrate.sh v9.1 sprt_v91.exe 1 500 10             >>$ROOT/runs/sgurr_x/calibrate_v91.log 2>&1
        say "fallback calibration finished"
    else
        say "fallback build failed too -- machine is idle, needs a human"
    fi
fi
say "=== done ==="
