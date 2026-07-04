#!/usr/bin/env python3
"""Data-sufficiency probe: is the dataset past the net's saturation point?

Trains the production architecture quickly at HALF and FULL dataset size and
compares validation loss on held-out WHOLE SHARDS (each shard is one datagen
process's games, so the validation set shares no games with training -- a
random position split would leak same-game siblings and flatter the numbers,
see train.py:make_split).

If the half->full step still improves validation meaningfully, the dataset is
not yet saturating the net and more data would help; if it's flat, more of the
same data is pointless and training should proceed.

    python probe_scaling.py --raw-dir ../data/gen3_raw [--epochs 15]

Prints one JSON line as the final stdout line, e.g.
    {"n_half": ..., "n_full": ..., "val_half": ..., "val_full": ...,
     "rel_improvement_pct": 1.23, "verdict": "data-limited"}
"""
import argparse
import glob
import json
import os
import sys

import numpy as np
import torch

import train as T

BATCH = 16384
LR = 1e-3
LAMBDA = 0.7
SEED = 0
WCLIP = 127.0 / T.nt.QA


def train_once(WF, BF, STM, SC, RES, train_idx, val_idx, epochs, dev):
    torch.manual_seed(SEED)
    model = T.NNUE().to(dev)
    opt = torch.optim.Adam(model.parameters(), lr=LR)
    ti_all = torch.from_numpy(train_idx)
    n = int(ti_all.numel())
    for _ in range(epochs):
        order = torch.randperm(n)
        ti = ti_all[order]
        model.train()
        for i in range(0, n, BATCH):
            sel = ti[i:i + BATCH]
            loss = T.batch_loss(model, WF, BF, STM, SC, RES, sel, dev, LAMBDA)
            opt.zero_grad(); loss.backward(); opt.step()
            with torch.no_grad():
                model.ft.weight[:T.INPUT].clamp_(-WCLIP, WCLIP)
    return T.eval_loss(model, WF, BF, STM, SC, RES,
                       torch.from_numpy(val_idx), BATCH, dev, LAMBDA)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--epochs", type=int, default=25)
    ap.add_argument("--threshold-pct", type=float, default=0.75,
                    help="half->full relative val improvement above which the "
                         "dataset is judged still data-limited")
    args = ap.parse_args()

    shards = sorted(glob.glob(os.path.join(args.raw_dir, "data_*.bin")))
    if len(shards) < 4:
        print(json.dumps({"error": "need >=4 shards for a game-disjoint probe"}))
        sys.exit(1)

    sizes = [os.path.getsize(p) // 32 for p in shards]
    edges = np.concatenate([[0], np.cumsum(sizes)])
    total = int(edges[-1])

    # hold out whole shards (game-disjoint val) from BOTH ends of the shard
    # list: two different writer processes, and where sessions differ, two
    # different sessions. A single-shard val is one process's correlated games
    # and proved too noisy to rank half-vs-full reliably.
    val_shard_idx = [0, len(sizes) - 1]
    val_rows, pool_rows = [], []
    for i in range(len(sizes)):
        rows = np.arange(edges[i], edges[i + 1])
        (val_rows if i in val_shard_idx else pool_rows).append(rows)
    val_idx = np.concatenate(val_rows)
    pool = np.concatenate(pool_rows)

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    concat = os.path.join(args.raw_dir, "all.bin")
    if not os.path.exists(concat) or os.path.getsize(concat) != total * 32:
        # copy EXACTLY the byte counts measured above: live datagen may still be
        # appending, and copying grown files would shift every later shard's
        # rows off the boundaries used for the game-disjoint split
        with open(concat, "wb") as out:
            for p, n_pos in zip(shards, sizes):
                remaining = n_pos * 32
                with open(p, "rb") as f:
                    while remaining > 0:
                        chunk = f.read(min(1 << 22, remaining))
                        if not chunk:
                            raise RuntimeError(f"short read on {p}")
                        out.write(chunk)
                        remaining -= len(chunk)

    wf, bf, stm, score, result, n = T.load_dataset(concat)
    WF = torch.from_numpy(wf); BF = torch.from_numpy(bf)
    STM = torch.from_numpy(stm); SC = torch.from_numpy(score)
    RES = torch.from_numpy(result)

    rng = np.random.default_rng(SEED)
    pool_shuffled = rng.permutation(pool)
    half = np.sort(pool_shuffled[: pool.size // 2])
    full = np.sort(pool_shuffled)

    print(f"probe: device={dev} pool={pool.size:,} val={val_idx.size:,} "
          f"(shards held out: {val_shard_idx})", flush=True)
    v_half = train_once(WF, BF, STM, SC, RES, half, val_idx, args.epochs, dev)
    print(f"probe: half ({half.size:,}) val={v_half:.5f}", flush=True)
    v_full = train_once(WF, BF, STM, SC, RES, full, val_idx, args.epochs, dev)
    print(f"probe: full ({full.size:,}) val={v_full:.5f}", flush=True)

    rel = (v_half - v_full) / v_half * 100.0
    # tri-state: full clearly BETTER -> more data still pays; roughly flat ->
    # saturated; full clearly WORSE -> physically implausible for same-
    # distribution data, so the measurement itself is unstable ("anomalous")
    # and must not be read as saturation.
    if rel >= args.threshold_pct:
        verdict = "data-limited"
    elif rel > -args.threshold_pct:
        verdict = "saturated"
    else:
        verdict = "anomalous"
    print(json.dumps({
        "n_half": int(half.size), "n_full": int(full.size),
        "n_val": int(val_idx.size), "epochs": args.epochs,
        "val_half": round(v_half, 6), "val_full": round(v_full, 6),
        "rel_improvement_pct": round(rel, 3),
        "threshold_pct": args.threshold_pct, "verdict": verdict,
    }))


if __name__ == "__main__":
    main()
