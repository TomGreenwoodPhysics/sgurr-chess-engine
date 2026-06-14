#!/bin/bash
# Full Texel tuning pipeline for Bitfish.
#
# Run from the bitfish source directory after placing benchmark.pgn here
# (optional). Edit the CONFIG block, then: ./run_tuning.sh
#
# Stages:
#   1. Build selfplay, texel_tune, pgn_extract.
#   2. Generate self-play games across all CPU cores.
#   3. Extract positions from benchmark.pgn if present.
#   4. Merge into one position file.
#   5. Run the tuner; tuned constants land in tuned_params.txt.

set -e

# ---------------- CONFIG ----------------
GAMES_PER_CORE=280      # games each worker plays; total = this * cores
DEPTH=6                 # fixed search depth per move during self-play
MODE=scalars            # "scalars" (robust, do this first) or "all" (+ PSTs; needs 300k+ positions)
# ----------------------------------------

CORES=$(nproc)
echo "detected $CORES CPU cores"

echo "[1/5] building tools..."
g++ -std=c++20 -O2 selfplay.cpp board.cpp evaluation.cpp search.cpp -o selfplay
g++ -std=c++20 -O2 pgn_extract.cpp board.cpp evaluation.cpp -o pgn_extract
g++ -std=c++20 -O2 texel_tune.cpp board.cpp -o texel_tune

mkdir -p texel_data
rm -f texel_data/*.csv

echo "[2/5] generating self-play ($GAMES_PER_CORE games x $CORES cores at depth $DEPTH)..."
pids=()
for c in $(seq 1 "$CORES"); do
    seed=$((1000 + c))
    ./selfplay selfplay "$GAMES_PER_CORE" "$DEPTH" "$seed" \
        "texel_data/sp_$seed.csv" >/dev/null 2>"texel_data/sp_$seed.log" &
    pids+=($!)
done
for p in "${pids[@]}"; do wait "$p"; done
echo "self-play done: $(cat texel_data/sp_*.csv | wc -l) positions"

echo "[3/5] extracting PGN positions..."
if [ -f benchmark.pgn ]; then
    ./pgn_extract benchmark.pgn texel_data/pgn.csv
else
    echo "  (no benchmark.pgn found; skipping)"
    : > texel_data/pgn.csv
fi

echo "[4/5] merging..."
cat texel_data/sp_*.csv texel_data/pgn.csv > texel_data/all_positions.csv
echo "total positions: $(wc -l < texel_data/all_positions.csv)"

echo "[5/5] tuning (mode: $MODE)..."
./texel_tune texel_data/all_positions.csv "$MODE" | tee tuned_params.txt

echo
echo "Done. Tuned constants are in tuned_params.txt."
echo "Next: paste them into evaluation.cpp, rebuild, and A/B test before benchmarking."
