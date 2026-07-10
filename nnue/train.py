#!/usr/bin/env python3
"""Train a Sgurr NNUE ((768 -> HL) x2 -> 1) from datagen output and export a .nnue.

  pip install torch numpy
  python3 train.py --data data.bin --out sgurr.nnue --epochs 40

Runs on CPU or GPU (CUDA auto-detected). The exported file is the format the
engine loads; the format and feature indexing are shared with nnue_tools.py.

The 32-byte datagen records are decoded in bulk with numpy rather than in a
per-record Python loop. A held-out validation split (--val_frac, default 0.05)
is scored each epoch under no_grad; --val_frac 0 trains on everything. The
holdout is by contiguous block (~whole games), not by random position -- see
make_split for why a per-position split silently inflates val accuracy.
"""
import argparse, time
import numpy as np
import nnue_tools as nt
import torch
import torch.nn as nn

INPUT, HL, SCALE = nt.INPUT, nt.HL, nt.SCALE
PAD = INPUT            # padding feature index -> a forced-zero embedding row
MAXP = 32             # at most 32 pieces on the board

# Record layout (little-endian), from datagen.cpp:
#   bytes  0..7   occ      u64 (set bit = occupied, LSB = a1 = sq 0)
#   bytes  8..23  nibbles  16 bytes; piece code per occupied square in
#                          ascending-square order, low nibble of each byte first
#   byte   24     stm      u8  (0 white, 1 black)
#   bytes  25..26 score    i16 (centipawns, stm-relative)
#   byte   27     result   u8  (0 loss, 1 draw, 2 win for stm)
#   bytes  28..31 padding
#
# Feature index (mirrors nnue_tools.feat / the C++ feature_index):
#   rel_sq     = sq            if persp==0 else sq ^ 56
#   rel_colour = 0 if colour==persp else 1
#   index      = rel_colour*384 + ptype*64 + rel_sq
#
# rel_sq is the only square-dependent term and is additive, so the constant
# base per piece code (colour = pc//6, ptype = pc%6) is precomputed and the
# (possibly mirrored) square added at decode time.
_pc = np.arange(12)
_colour = _pc // 6
_ptype = _pc % 6
_W_BASE = (_colour * 384 + _ptype * 64).astype(np.int64)          # white persp
_B_BASE = ((1 - _colour) * 384 + _ptype * 64).astype(np.int64)    # black persp


def _decode_chunk(arr):
    """arr: (m, 32) uint8 contiguous -> (wf, bf, stm, score, result) for the
    chunk, wf/bf shape (m, MAXP). Operates on the flat list of occupied cells
    (~24 per record) so no (m, 64) int64 grid is ever materialised."""
    m = arr.shape[0]

    stm = arr[:, 24].astype(np.int64)
    score = arr[:, 25:27].copy().view(np.int16).reshape(m).astype(np.float32)
    result = (arr[:, 27].astype(np.float32)) / 2.0

    # occupancy -> (m,64) uint8 bit matrix; column = sq, ascending (LSB first).
    occ_bytes = np.ascontiguousarray(arr[:, 0:8])
    occ_bits = np.unpackbits(occ_bytes, axis=1, bitorder="little")  # (m,64)

    # nibbles -> (m,32) piece codes in stored order (low nibble of each byte first)
    nib = arr[:, 8:24]
    codes = np.empty((m, 32), np.uint8)
    codes[:, 0::2] = nib & 0x0F
    codes[:, 1::2] = nib >> 4

    # slot (rank among occupied squares) per square; -1 on a leading empty run.
    ranks = np.cumsum(occ_bits, axis=1, dtype=np.uint8).astype(np.int16) - 1

    # flat occupied cells, ascending square within each row.
    rows, cols = np.nonzero(occ_bits)
    slot = ranks[rows, cols].astype(np.intp)
    code_flat = codes[rows, slot].astype(np.intp)                 # (L,) 0..11

    wf_flat = _W_BASE[code_flat] + cols
    bf_flat = _B_BASE[code_flat] + (cols ^ np.int64(56))

    wf = np.full((m, MAXP), PAD, np.int64)
    bf = np.full((m, MAXP), PAD, np.int64)
    wf[rows, slot] = wf_flat
    bf[rows, slot] = bf_flat
    return wf, bf, stm, score, result


def load_dataset(path, chunk=1_000_000):
    """Chunked vectorised loader -> (wf, bf, stm, score, result, n)."""
    raw = np.fromfile(path, dtype=np.uint8)
    n = raw.size // 32
    arr = raw[: n * 32].reshape(n, 32)

    wf = np.empty((n, MAXP), np.int64)
    bf = np.empty((n, MAXP), np.int64)
    stm = np.empty(n, np.int64)
    score = np.empty(n, np.float32)
    result = np.empty(n, np.float32)

    for lo in range(0, n, chunk):
        hi = min(lo + chunk, n)
        w, b, s, sc, r = _decode_chunk(np.ascontiguousarray(arr[lo:hi]))
        wf[lo:hi] = w; bf[lo:hi] = b
        stm[lo:hi] = s; score[lo:hi] = sc; result[lo:hi] = r
    return wf, bf, stm, score, result, n


def make_split(n, val_frac, seed, block=65536):
    """Disjoint split of range(n) into (train_idx, val_idx), holding out
    CONTIGUOUS blocks of positions rather than single random positions.

    Datagen writes each game's ~50-130 positions consecutively, so a random
    per-position split puts same-game siblings of nearly every val position in
    the train set: val loss then partly measures memorisation of the training
    games, not generalisation (~0.003 of flattery at 5M positions -- enough to
    invert data-scaling comparisons). Block-level holdout keeps games together;
    only the ~1 game straddling each block edge leaks, which is negligible.

    Seeded numpy permutation of blocks, so it is reproducible. val_frac == 0
    (or n < 2) gives an empty validation set."""
    if val_frac <= 0 or n < 2:
        return np.arange(n), np.array([], dtype=np.int64)
    rng = np.random.default_rng(seed)
    n_blocks = (n + block - 1) // block
    order = rng.permutation(n_blocks)
    target = max(1, int(round(n * val_frac)))
    val_mask = np.zeros(n, dtype=bool)
    taken = 0
    for b in order:
        if taken >= target:
            break
        lo = b * block
        hi = min(lo + block, n)
        val_mask[lo:hi] = True
        taken += hi - lo
    val_idx = np.nonzero(val_mask)[0]
    train_idx = np.nonzero(~val_mask)[0]
    return train_idx, val_idx


class NNUE(nn.Module):
    def __init__(self):
        super().__init__()
        # +1 row for padding (forced to zero, contributes nothing to the sum)
        self.ft = nn.Embedding(INPUT + 1, HL, padding_idx=PAD)
        self.ftb = nn.Parameter(torch.zeros(HL))
        self.out = nn.Linear(2 * HL, 1)
        nn.init.normal_(self.ft.weight, 0, 0.05)
        with torch.no_grad():
            self.ft.weight[PAD].zero_()
        nn.init.normal_(self.out.weight, 0, 0.05)

    def forward(self, wf, bf, stm):
        accw = self.ft(wf).sum(dim=1) + self.ftb       # (B, HL)
        accb = self.ft(bf).sum(dim=1) + self.ftb
        m = (stm == 0).unsqueeze(1)
        us = torch.where(m, accw, accb)
        them = torch.where(m, accb, accw)
        x = torch.cat([torch.clamp(us, 0, 1), torch.clamp(them, 0, 1)], dim=1)
        return self.out(x).squeeze(1)                  # output; *SCALE = centipawns


def batch_loss(model, WF, BF, STM, SC, RES, sel, dev, lambda_):
    """Forward + MSE-in-sigmoid-space loss for one batch of indices `sel`."""
    wfb = WF[sel].to(dev, non_blocking=True)
    bfb = BF[sel].to(dev, non_blocking=True)
    stmb = STM[sel].to(dev, non_blocking=True)
    scb = SC[sel].to(dev, non_blocking=True)
    resb = RES[sel].to(dev, non_blocking=True)
    pred = model(wfb, bfb, stmb)
    target = lambda_ * torch.sigmoid(scb / SCALE) + (1 - lambda_) * resb
    return ((torch.sigmoid(pred) - target) ** 2).mean()


def eval_loss(model, WF, BF, STM, SC, RES, idx, batch, dev, lambda_):
    """Mean loss over the positions in idx, no grad / no weight updates."""
    if idx.numel() == 0:
        return float("nan")
    model.eval()
    total = 0.0
    with torch.no_grad():
        for i in range(0, idx.numel(), batch):
            sel = idx[i:i + batch]
            total += batch_loss(model, WF, BF, STM, SC, RES, sel, dev, lambda_).item() * sel.numel()
    model.train()
    return total / idx.numel()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="sgurr.nnue")
    ap.add_argument("--hl", type=int, default=nt.HL,
                    help="hidden-layer width; must match the engine's nnue::HL "
                         "at deploy time (default 256). Overrides nt.HL so the "
                         "model AND the exported file header agree.")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--batch", type=int, default=16384)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--schedule", choices=["constant", "cosine"], default="constant",
                    help="cosine decays lr to --lr_min over the whole run; "
                         "constant lr degrades the net past ~2k steps")
    ap.add_argument("--lr_min", type=float, default=1e-5,
                    help="final lr for --schedule cosine")
    ap.add_argument("--lambda_", type=float, default=0.7,
                    help="target = lambda*eval_winprob + (1-lambda)*game_result")
    ap.add_argument("--wclip", type=float, default=127.0 / nt.QA,
                    help="clamp |ft weights| so the int16 accumulator can't overflow")
    ap.add_argument("--val_frac", type=float, default=0.05,
                    help="held-out validation fraction (0 = train on everything)")
    ap.add_argument("--seed", type=int, default=0,
                    help="seed for the train/val split and weight init")
    args = ap.parse_args()

    # HL is read at model-construction time (NNUE.__init__ looks up the module
    # global) and by nt.export for the file header; set both so a --hl override
    # produces a self-consistent net.
    global HL
    HL = args.hl
    nt.HL = args.hl
    print(f"HL = {HL}")

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print("device:", dev)
    t0 = time.time()
    wf, bf, stm, score, result, n = load_dataset(args.data)
    print(f"loaded {n} positions  ({time.time()-t0:.1f}s)")

    # The dataset stays in CPU memory and each batch is copied to the device
    # inside the loop: 20M positions of int64 features is ~10 GB, too much to
    # hold on most GPUs. from_numpy shares the buffer, so nothing is copied.
    WF = torch.from_numpy(wf); BF = torch.from_numpy(bf)
    STM = torch.from_numpy(stm)
    SC = torch.from_numpy(score); RES = torch.from_numpy(result)

    # train/val split
    torch.manual_seed(args.seed)
    train_idx_np, val_idx_np = make_split(n, args.val_frac, args.seed)
    train_idx = torch.from_numpy(train_idx_np)
    val_idx = torch.from_numpy(val_idx_np)
    n_train = int(train_idx.numel())
    print(f"split: {n_train} train, {int(val_idx.numel())} val "
          f"(val_frac={args.val_frac}, seed={args.seed})")

    model = NNUE().to(dev)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    sched = None
    if args.schedule == "cosine":
        steps_per_epoch = (n_train + args.batch - 1) // args.batch
        sched = torch.optim.lr_scheduler.CosineAnnealingLR(
            opt, T_max=args.epochs * steps_per_epoch, eta_min=args.lr_min)

    for epoch in range(args.epochs):
        order = torch.randperm(n_train)        # shuffle the train indices only
        ti = train_idx[order]
        total = 0.0; t0 = time.time()
        model.train()
        for i in range(0, n_train, args.batch):
            sel = ti[i:i + args.batch]
            loss = batch_loss(model, WF, BF, STM, SC, RES, sel, dev, args.lambda_)
            opt.zero_grad(); loss.backward(); opt.step()
            if sched is not None:
                sched.step()
            with torch.no_grad():
                model.ft.weight[:INPUT].clamp_(-args.wclip, args.wclip)
            total += loss.item() * sel.numel()
        train_loss = total / n_train

        if val_idx.numel() > 0:
            val = eval_loss(model, WF, BF, STM, SC, RES, val_idx, args.batch, dev, args.lambda_)
            print(f"epoch {epoch+1:3d}/{args.epochs}  train {train_loss:.5f}  "
                  f"val {val:.5f}  ({time.time()-t0:.1f}s)")
        else:
            print(f"epoch {epoch+1:3d}/{args.epochs}  loss {train_loss:.5f}  "
                  f"({time.time()-t0:.1f}s)")

    ftw = model.ft.weight[:INPUT].detach().cpu().numpy()        # (INPUT, HL)
    ftb = model.ftb.detach().cpu().numpy()                      # (HL,)
    ow = model.out.weight.detach().cpu().numpy().reshape(-1)    # (2*HL,)
    ob = float(model.out.bias.detach().cpu().numpy()[0])
    nt.export(args.out, ftw, ftb, ow, ob)
    print("wrote", args.out)


if __name__ == "__main__":
    main()