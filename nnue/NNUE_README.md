# Ruk NNUE pipeline

Replaces the hand-crafted evaluation with a trained network while keeping all
of the search. The engine side (loading and running nets) lives in
`Ruk_cpp/nnue.cpp`; this folder is the tooling for producing a net.

## The loop

    1. datagen   -> self-play positions labelled with search score + result
    2. train     -> a network file the engine loads
    3. test      -> SPRT the NNUE build vs the HCE baseline
    4. iterate   -> regenerate data with the new net, retrain

## 1. Generate data

Build the generator against the engine (use clang, not the broken ucrt64 gcc,
see `../Ruk_cpp/BUILD.md`):

    /c/msys64/clang64/bin/clang++ -std=c++20 -O3 -march=native -DNDEBUG -static \
        datagen.cpp board.cpp evaluation.cpp search.cpp nnue.cpp -o datagen.exe

The generator is resumable: it appends to an auto-numbered shard in an output
directory and stops on a position target or Ctrl+C, so it can be run in short
sessions.

    datagen <out_dir> <target_positions> <depth|nodes:N> [book.epd|-] [net.nnue|-]

    # gen2: NNUE-labelled, node-budget labels, into ../data
    ./datagen.exe ../data 25000000 nodes:25000 ../testing/book.epd ../nets/gen1.nnue

Each run writes a fresh `data_NNNN_TAG.bin` (never overwrites), uses a new
random seed, and reports total-vs-target by summing the shards on disk. Only
quiet positions are recorded (not in check, best move not a capture/promo,
|score| < 2000), each tagged with the game result. With a `net.nnue` argument
the labels come from the NNUE evaluation; omit it (or pass `-`) to label with
the hand-crafted eval, which is how the first net is bootstrapped.

Throughput is roughly 38 positions/sec/core at `nodes:25000`, so run several
processes in parallel; the per-run TAG keeps their shards from colliding. The
trainer takes a single file, so concatenate the shards first
(`cat ../data/*.bin > all.bin`). `python3 verify_data.py <shard>.bin` sanity
checks a file.

## 2. Train

    pip install torch numpy
    python3 train.py --data data.bin --out ruk.nnue --epochs 40

CUDA is used automatically if present (CPU works but is slow). Key options:
`--lambda_` blends the eval-score target with the game result (0.7 = mostly
eval), plus `--batch`, `--lr`, `--epochs`. The output `ruk.nnue` is the file
the engine loads.

## 3. Test

Point the engine at the net and SPRT it against the HCE baseline (same binary,
no net = HCE):

    RUK_EVALFILE=ruk.nnue ./ruk_nnue        # uses the net
    ./ruk_hce                               # no net found, hand-crafted eval

    python3 ../testing/sprt.py --new ./ruk_nnue --base ./ruk_hce \
        --tc 8+0.08 --book ../testing/book.epd --elo0 0 --elo1 5

## Notes

- The first net is unlikely to beat a mature HCE: NNUE strength comes from
  data scale and iteration. A few hundred thousand shallow positions train a
  coherent net that still loses to a tuned hand-crafted eval; tens of millions
  of positions, then regenerating data with the NNUE engine and retraining, is
  where it overtakes.
- Bigger `HL` (in `nnue.hpp` / `nnue_tools.py`, currently 256) is stronger but
  has to match between engine and trainer, and needs a rebuild and retrain.
- The incremental accumulator is implemented (`nnue.cpp`: refresh at the search
  root, per-move deltas on make/unmake) and took NNUE from ~63% to ~104% of
  HCE NPS. `nnue_selfcheck.cpp` verifies it bit-for-bit against a full
  refresh. Remaining speed ideas: bigger `HL`, SIMD on the accumulator loops.
- The C++ forward pass matches the numpy reference exactly, datagen positions
  reconstruct to legal boards, and a quantised export reloads into the engine
  within ~16 cp of the float model.

## Files

- `datagen.cpp`     self-play data generator (build against the engine)
- `train.py`        PyTorch trainer, writes a .nnue
- `nnue_tools.py`   format I/O, feature indexing, quantise + export, references
- `verify_data.py`  sanity-checks a datagen file
- `ruk.nnue`        random placeholder net (tests the loading path only)
