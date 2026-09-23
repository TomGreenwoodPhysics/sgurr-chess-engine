#!/usr/bin/env bash
# Two isolated SPRTs against shipped v9.0, in the order asked for:
#   1. batch features at SPSA-tuned settings   (search only, gen9 net both sides)
#   2. screlu at QA=181                        (net only, stock v9.0 search)
# Bundling only happens if both are positive.
set -u
ROOT=/c/coding/Sgurr
LOG=$ROOT/runs/sgurr_x/mainline_sprts.log
FC=$ROOT/benchmarks/tools/fastchess.exe
BOOK=$ROOT/testing/8moves_v3.pgn
say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

TUNED="option.HistLmrDiv=228 option.HistPruneMargin=75 option.CapHistMax=87 \
option.RazorMargin=500 option.FutMargin=144 option.SeeQuietMargin=46 \
option.SeeCapMargin=26 option.NmpEvalDiv=71 option.IirMinDepth=8 \
option.LmrDivX100=241"

# gen9 for both sides: the batch binary reads the env, sprt_base has the same
# net baked, so this is one net and one variable.
export SGR_EVALFILE="C:/coding/Sgurr/nets/gen9.nnue"

say "=== 1. batch + SPSA tuned vs v9.0 (1000 games) ==="
"$FC" -engine cmd=$ROOT/sgurr_cpp/sgr_v90_batch_spsa.exe name=tuned $TUNED \
      -engine cmd=$ROOT/sgurr_cpp/sprt_base.exe name=v90 \
  -each tc=8+0.08 option.Hash=256 -rounds 500 -repeat -concurrency 7 \
  -openings file="$BOOK" format=pgn order=random -recover \
  >$ROOT/runs/sgurr_x/match_main_tuned.txt 2>&1
say "1. batch+tuned vs v9.0: $(grep -aE 'Elo:' $ROOT/runs/sgurr_x/match_main_tuned.txt | tail -1)"
taskkill //IM fastchess.exe //F >/dev/null 2>&1
taskkill //IM sgr_v90_batch_spsa.exe //F >/dev/null 2>&1

say "waiting for the screlu retrain"
while [ ! -f $ROOT/sgurr_cpp/sprt_main_sc.exe ]; do
    grep -aq "retrain done" $ROOT/runs/sgurr_x/mainline_screlu.log 2>/dev/null && break
    sleep 60
done
if [ ! -f $ROOT/sgurr_cpp/sprt_main_sc.exe ]; then
    say "no screlu engine was produced; stopping here"; exit 1
fi

# screlu net is baked into its binary; unset so it is not overridden by gen9.
unset SGR_EVALFILE
say "=== 2. screlu QA=181 vs v9.0 (1000 games) ==="
"$FC" -engine cmd=$ROOT/sgurr_cpp/sprt_main_sc.exe name=screlu \
      -engine cmd=$ROOT/sgurr_cpp/sprt_base.exe name=v90 \
  -each tc=8+0.08 option.Hash=256 -rounds 500 -repeat -concurrency 7 \
  -openings file="$BOOK" format=pgn order=random -recover \
  >$ROOT/runs/sgurr_x/match_main_screlu.txt 2>&1
say "2. screlu vs v9.0: $(grep -aE 'Elo:' $ROOT/runs/sgurr_x/match_main_screlu.txt | tail -1)"
taskkill //IM fastchess.exe //F >/dev/null 2>&1
taskkill //IM sprt_main_sc.exe //F >/dev/null 2>&1

say "=== both SPRTs done -- bundle and calibrate only if both are positive ==="
