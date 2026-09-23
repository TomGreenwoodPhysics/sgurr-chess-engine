#!/usr/bin/env bash
# Validate the 31-hour tune: same binary, tuned options against defaults.
# The earlier attempt failed because $ROOT is an MSYS path (/c/coding/...),
# which bash understands and Windows Python does not. Windows paths here.
set -u
ROOT=/c/coding/Sgurr
LOG=$ROOT/runs/sgurr_x/spsa_validate.log
say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

OPTS="option.HistLmrDiv=228 option.HistPruneMargin=75 option.CapHistMax=87 \
option.RazorMargin=500 option.FutMargin=144 option.SeeQuietMargin=46 \
option.SeeCapMargin=26 option.NmpEvalDiv=71 option.IirMinDepth=8 \
option.LmrDivX100=241"

export SGR_EVALFILE="C:/coding/Sgurr/nets/gen9.nnue"
say "=== SPSA validation: tuned vs default, 1000 games ==="
$ROOT/benchmarks/tools/fastchess.exe \
  -engine cmd=$ROOT/sgurr_cpp/sgr_v90_batch_spsa.exe name=tuned $OPTS \
  -engine cmd=$ROOT/sgurr_cpp/sgr_v90_batch_spsa.exe name=default \
  -each tc=8+0.08 option.Hash=256 -rounds 500 -repeat -concurrency 7 \
  -openings file=$ROOT/testing/8moves_v3.pgn format=pgn order=random -recover \
  >$ROOT/runs/sgurr_x/match_spsa_tuned.txt 2>&1
say "result: $(grep -aE 'Elo:' $ROOT/runs/sgurr_x/match_spsa_tuned.txt | tail -1)"
taskkill //IM fastchess.exe //F >/dev/null 2>&1
taskkill //IM sgr_v90_batch_spsa.exe //F >/dev/null 2>&1
say "=== done ==="
