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
import argparse, os, time
import numpy as np
import nnue_tools as nt
import torch
import torch.nn as nn

INPUT, HL, SCALE = nt.INPUT, nt.HL, nt.SCALE
PAD = INPUT            # Padding feature with a forced-zero embedding row
MAXP = 32             # Maximum pieces on the board

# Little-endian record layout from datagen.cpp
#   Bytes  0..7   occ      u64 with a1 as bit 0
#   Bytes  8..23  nibbles  piece codes in ascending-square order
#                          with the low nibble first
#   Byte   24     stm      u8 where 0 is white and 1 is black
#   Bytes  25..26 score    i16 in centipawns relative to the side to move
#   Byte   27     result   u8 where 0 is loss, 1 draw, and 2 win
#   Bytes  28..31 padding
#
# Feature index matching nnue_tools.feat and the C++ feature_index
#   rel_sq     = sq            if persp==0 else sq ^ 56
#   rel_colour = 0 if colour==persp else 1
#   index      = rel_colour*384 + ptype*64 + rel_sq
#
# Only rel_sq depends on the square. Precompute the base for each piece code,
# then add the possibly mirrored square while decoding.
_pc = np.arange(12)
_colour = _pc // 6
_ptype = _pc % 6
_W_BASE = (_colour * 384 + _ptype * 64).astype(np.int64)          # White view
_B_BASE = ((1 - _colour) * 384 + _ptype * 64).astype(np.int64)    # Black view


def _decode_chunk(arr, bmap=None, pad=PAD):
    """arr: (m, 32) uint8 contiguous -> (wf, bf, stm, score, result) for the
    chunk, wf/bf shape (m, MAXP). Operates on the flat list of occupied cells
    (~24 per record) so no (m, 64) int64 grid is ever materialised.

    bmap (64-entry king-bucket map) shifts each perspective's features into
    the bucket of that perspective's OWN king: index += map[rel_king]*768.

    Features are returned as int16: the largest index is buckets*768 (the pad
    row), far under 32767, and at gen8 scale (56M positions) int64 feature
    arrays alone would be ~29 GB -- more than the machine's RAM. int16 keeps
    the dataset ~7 GB; batches are widened to int64 on the GPU."""
    m = arr.shape[0]

    stm = arr[:, 24].astype(np.int8)
    score = arr[:, 25:27].copy().view(np.int16).reshape(m).astype(np.float32)
    result = (arr[:, 27].astype(np.float32)) / 2.0

    # Decode occupancy into an (m, 64) bit matrix ordered from the LSB.
    occ_bytes = np.ascontiguousarray(arr[:, 0:8])
    occ_bits = np.unpackbits(occ_bytes, axis=1, bitorder="little")  # (m,64)

    # Decode nibbles into (m, 32) piece codes with the low nibble first.
    nib = arr[:, 8:24]
    codes = np.empty((m, 32), np.uint8)
    codes[:, 0::2] = nib & 0x0F
    codes[:, 1::2] = nib >> 4

    # Map each square to its occupied slot, using -1 before the first piece.
    ranks = np.cumsum(occ_bits, axis=1, dtype=np.uint8).astype(np.int16) - 1

    # Flatten occupied cells in ascending square order within each row.
    rows, cols = np.nonzero(occ_bits)
    slot = ranks[rows, cols].astype(np.intp)
    code_flat = codes[rows, slot].astype(np.intp)                 # (L,) 0..11

    wf_flat = _W_BASE[code_flat] + cols
    bf_flat = _B_BASE[code_flat] + (cols ^ np.int64(56))

    if bmap is not None:
        # Require one king of each colour to catch corrupt input before training.
        m5, m11 = code_flat == 5, code_flat == 11        # WK, BK codes
        assert int(m5.sum()) == m and int(m11.sum()) == m, \
            "record without exactly one king per side"
        bmap64 = np.asarray(bmap, np.int64)
        wk = np.zeros(m, np.int64); bk = np.zeros(m, np.int64)
        wk[rows[m5]] = cols[m5]
        bk[rows[m11]] = cols[m11]
        woff = bmap64[wk] * 768                # White king without mirroring
        boff = bmap64[bk ^ np.int64(56)] * 768 # Mirrored black king
        wf_flat = wf_flat + woff[rows]
        bf_flat = bf_flat + boff[rows]

    wf = np.full((m, MAXP), pad, np.int16)
    bf = np.full((m, MAXP), pad, np.int16)
    wf[rows, slot] = wf_flat
    bf[rows, slot] = bf_flat
    return wf, bf, stm, score, result


def load_dataset(path, chunk=1_000_000, buckets=1):
    """Chunked vectorised loader -> (wf, bf, stm, score, result, n).
    buckets>1 applies the shared king-bucket map (nt.KING_BUCKET_MAP).

    Decodes the WHOLE file into RAM. Kept for small datasets and for the
    equivalence test against StreamingDataset; see that class for why anything
    past ~100M positions must not use this path.
    """
    bmap = nt.KING_BUCKET_MAP if buckets > 1 else None
    pad = INPUT * buckets
    raw = np.fromfile(path, dtype=np.uint8)
    n = raw.size // 32
    arr = raw[: n * 32].reshape(n, 32)

    wf = np.empty((n, MAXP), np.int16)
    bf = np.empty((n, MAXP), np.int16)
    stm = np.empty(n, np.int8)
    score = np.empty(n, np.float32)
    result = np.empty(n, np.float32)

    for lo in range(0, n, chunk):
        hi = min(lo + chunk, n)
        w, b, s, sc, r = _decode_chunk(np.ascontiguousarray(arr[lo:hi]), bmap, pad)
        wf[lo:hi] = w; bf[lo:hi] = b
        stm[lo:hi] = s; score[lo:hi] = sc; result[lo:hi] = r
    return wf, bf, stm, score, result, n


class StreamingDataset:
    """Memory-mapped dataset that decodes each batch on demand.

    load_dataset() materialises the decoded form of every position up front:
    wf and bf are (n, 32) int16, so 128 bytes per position, plus 9 for
    stm/score/result -- about 137 B/position steady, and the raw array is live
    alongside during the load, peaking near 169 B/position.

    On the 32 GB development machine that is fine at gen8's 56M (7.7 GB) and
    breaks somewhere around 130-150M:

        56M   ->  7.7 GB steady,  9.5 GB peak
        110M  -> 15.1 GB steady, 18.6 GB peak
        200M  -> 27.4 GB steady, 33.8 GB peak   -- exceeds RAM

    That matters because the datagen script caps at 200M and the 2026-08-01
    data study found returns still ACCELERATING at 56M (14M->28M +17 Elo,
    28M->56M +48). The single most valuable lever in this project was gated by
    a loader that could not open the file it was going to produce.

    This holds only the raw 32-byte records, memory-mapped, and runs the same
    _decode_chunk per batch. Resident memory becomes evictable page cache
    rather than a hard allocation, so the ceiling is disk size, not RAM. The
    cost is re-decoding each position once per epoch -- vectorised numpy over a
    16k batch, minutes per epoch against a run measured in hours.
    """

    def __init__(self, path, buckets=1):
        self.bmap = nt.KING_BUCKET_MAP if buckets > 1 else None
        self.pad = INPUT * buckets
        size = os.path.getsize(path)
        self.n = size // 32
        self.raw = np.memmap(path, dtype=np.uint8, mode="r",
                             shape=(self.n, 32))

    def __len__(self):
        return self.n

    def batch(self, idx):
        """Decode the positions at `idx` (a 1-D index array)."""
        rows = np.ascontiguousarray(self.raw[idx])
        return _decode_chunk(rows, self.bmap, self.pad)


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


class FactorizedNNUE(nn.Module):
    """King-bucketed feature transformer as a SHARED base plus a small
    per-bucket DELTA: contribution(feature f in bucket b) = shared[f] +
    delta[b*768+f].

    This is the standard fix for bucket data starvation (cf. Stockfish's
    "factorizer"): the naive per-bucket net (-10.7 +/-16 on gen8) gives every
    bucket its own weights but only ~1/K of the data each; here the shared
    table trains on ALL positions and each delta only learns its bucket's
    correction. Deltas start at ZERO, so training begins from exactly the
    unbucketed model and diverges only where the data supports it.

    Exported COALESCED (final[b][f] = shared[f] + delta[b][f]) into the same
    v2 net file, so engine inference is completely unchanged."""
    def __init__(self, buckets):
        super().__init__()
        n_delta = INPUT * buckets
        self.pad = n_delta                    # Loader padding index
        self.ft_shared = nn.Embedding(INPUT + 1, HL, padding_idx=INPUT)
        self.ft_delta = nn.Embedding(n_delta + 1, HL, padding_idx=n_delta)
        self.ftb = nn.Parameter(torch.zeros(HL))
        self.out = nn.Linear(2 * HL, 1)
        nn.init.normal_(self.ft_shared.weight, 0, 0.05)
        nn.init.zeros_(self.ft_delta.weight)
        with torch.no_grad():
            self.ft_shared.weight[INPUT].zero_()
        nn.init.normal_(self.out.weight, 0, 0.05)

    def _acc(self, f):
        # Map padding to the shared table's padding row.
        base = torch.where(f == self.pad, torch.full_like(f, INPUT), f % INPUT)
        return (self.ft_shared(base) + self.ft_delta(f)).sum(dim=1) + self.ftb

    def forward(self, wf, bf, stm):
        accw = self._acc(wf)
        accb = self._acc(bf)
        m = (stm == 0).unsqueeze(1)
        us = torch.where(m, accw, accb)
        them = torch.where(m, accb, accw)
        x = torch.cat([torch.clamp(us, 0, 1), torch.clamp(them, 0, 1)], dim=1)
        return self.out(x).squeeze(1)


class NNUE(nn.Module):
    def __init__(self, n_features=INPUT):
        super().__init__()
        # Add one forced-zero padding row.
        # King-bucketed nets use INPUT * buckets features.
        self.ft = nn.Embedding(n_features + 1, HL, padding_idx=n_features)
        self.ftb = nn.Parameter(torch.zeros(HL))
        self.out = nn.Linear(2 * HL, 1)
        nn.init.normal_(self.ft.weight, 0, 0.05)
        with torch.no_grad():
            self.ft.weight[n_features].zero_()
        nn.init.normal_(self.out.weight, 0, 0.05)

    def forward(self, wf, bf, stm):
        accw = self.ft(wf).sum(dim=1) + self.ftb       # (B, HL)
        accb = self.ft(bf).sum(dim=1) + self.ftb
        m = (stm == 0).unsqueeze(1)
        us = torch.where(m, accw, accb)
        them = torch.where(m, accb, accw)
        x = torch.cat([torch.clamp(us, 0, 1), torch.clamp(them, 0, 1)], dim=1)
        return self.out(x).squeeze(1)                  # Multiply by SCALE for centipawns


def batch_loss(model, fetch, sel, dev, lambda_):
    """Forward + MSE-in-sigmoid-space loss for one batch of indices `sel`.

    `fetch` returns the five CPU tensors for those indices -- either sliced
    from RAM or decoded on the fly from the memory map. Features are int16 on
    the host and widened to int64 only after the device copy, so the PCIe
    transfer stays half-width either way."""
    wf_c, bf_c, stm_c, sc_c, res_c = fetch(sel)
    wfb = wf_c.to(dev, non_blocking=True).long()
    bfb = bf_c.to(dev, non_blocking=True).long()
    stmb = stm_c.to(dev, non_blocking=True)
    scb = sc_c.to(dev, non_blocking=True)
    resb = res_c.to(dev, non_blocking=True)
    pred = model(wfb, bfb, stmb)
    target = lambda_ * torch.sigmoid(scb / SCALE) + (1 - lambda_) * resb
    return ((torch.sigmoid(pred) - target) ** 2).mean()


def eval_loss(model, fetch, idx, batch, dev, lambda_):
    """Mean loss over the positions in idx, no grad / no weight updates."""
    if idx.numel() == 0:
        return float("nan")
    model.eval()
    total = 0.0
    with torch.no_grad():
        for i in range(0, idx.numel(), batch):
            sel = idx[i:i + batch]
            total += batch_loss(model, fetch, sel, dev, lambda_).item() * sel.numel()
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
    ap.add_argument("--buckets", type=int, default=1, choices=[1, nt.BUCKETS],
                    help=f"king-bucketed inputs: 1 = classic 768 net (v1 file), "
                         f"{nt.BUCKETS} = nt.KING_BUCKET_MAP (v2 file with the "
                         f"map embedded). Other counts need a new map in "
                         f"nnue_tools first.")
    ap.add_argument("--factorize", action="store_true",
                    help="train buckets as shared base + per-bucket delta "
                         "(fixes bucket data starvation); export is coalesced "
                         "so the engine sees an ordinary v2 net. Requires "
                         "--buckets > 1.")
    ap.add_argument("--val_frac", type=float, default=0.05,
                    help="held-out validation fraction (0 = train on everything)")
    ap.add_argument("--loader", choices=["auto", "memory", "stream"], default="auto",
                    help="auto switches to the memory map past --stream_threshold "
                         "positions; the in-memory path is faster but holds "
                         "~137 bytes per position")
    ap.add_argument("--stream_threshold", type=int, default=60_000_000,
                    help="positions above which auto picks the streaming loader")
    ap.add_argument("--seed", type=int, default=0,
                    help="seed for the train/val split and weight init")
    args = ap.parse_args()

    # Set the module value before construction and export so --hl stays consistent.
    global HL
    HL = args.hl
    nt.HL = args.hl
    print(f"HL = {HL}")

    n_features = INPUT * args.buckets
    if args.factorize and args.buckets <= 1:
        ap.error("--factorize requires --buckets > 1")
    print(f"king buckets = {args.buckets}  (features = {n_features})"
          + ("  [factorized: shared + delta]" if args.factorize else ""))

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print("device:", dev)
    t0 = time.time()

    # Decoded positions use about 137 bytes each, versus 32 bytes for raw data.
    # Auto mode uses a memory map beyond roughly 60 million positions.
    n_positions = os.path.getsize(args.data) // 32
    kind = args.loader
    if kind == "auto":
        kind = "stream" if n_positions > args.stream_threshold else "memory"

    if kind == "memory":
        wf, bf, stm, score, result, n = load_dataset(args.data, buckets=args.buckets)
        # from_numpy shares the buffer without copying it.
        WF = torch.from_numpy(wf); BF = torch.from_numpy(bf)
        STM = torch.from_numpy(stm)
        SC = torch.from_numpy(score); RES = torch.from_numpy(result)

        def fetch(sel):
            return WF[sel], BF[sel], STM[sel], SC[sel], RES[sel]

        gb = (wf.nbytes + bf.nbytes + stm.nbytes + score.nbytes + result.nbytes) / 1e9
        print(f"loaded {n} positions in memory, {gb:.1f} GB  ({time.time()-t0:.1f}s)")
    else:
        ds = StreamingDataset(args.data, buckets=args.buckets)
        n = len(ds)

        def fetch(sel):
            w, b, st, sc_, r = ds.batch(sel.numpy())
            return (torch.from_numpy(w), torch.from_numpy(b), torch.from_numpy(st),
                    torch.from_numpy(sc_), torch.from_numpy(r))

        print(f"streaming {n} positions from a memory map, "
              f"{os.path.getsize(args.data)/1e9:.1f} GB on disk  "
              f"({time.time()-t0:.1f}s)")

    # Training and validation split
    torch.manual_seed(args.seed)
    train_idx_np, val_idx_np = make_split(n, args.val_frac, args.seed)
    train_idx = torch.from_numpy(train_idx_np)
    val_idx = torch.from_numpy(val_idx_np)
    n_train = int(train_idx.numel())
    print(f"split: {n_train} train, {int(val_idx.numel())} val "
          f"(val_frac={args.val_frac}, seed={args.seed})")

    model = (FactorizedNNUE(args.buckets) if args.factorize
             else NNUE(n_features)).to(dev)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    sched = None
    if args.schedule == "cosine":
        steps_per_epoch = (n_train + args.batch - 1) // args.batch
        sched = torch.optim.lr_scheduler.CosineAnnealingLR(
            opt, T_max=args.epochs * steps_per_epoch, eta_min=args.lr_min)

    for epoch in range(args.epochs):
        order = torch.randperm(n_train)        # Shuffle only training indices
        ti = train_idx[order]
        total = 0.0; t0 = time.time()
        model.train()
        for i in range(0, n_train, args.batch):
            sel = ti[i:i + args.batch]
            loss = batch_loss(model, fetch, sel, dev, args.lambda_)
            opt.zero_grad(); loss.backward(); opt.step()
            if sched is not None:
                sched.step()
            with torch.no_grad():
                if args.factorize:
                    # Keep shared plus delta within wclip for int16 safety.
                    # Give most of the range to the shared weights.
                    model.ft_shared.weight[:INPUT].clamp_(-args.wclip * 0.75, args.wclip * 0.75)
                    model.ft_delta.weight[:n_features].clamp_(-args.wclip * 0.25, args.wclip * 0.25)
                else:
                    model.ft.weight[:n_features].clamp_(-args.wclip, args.wclip)
            total += loss.item() * sel.numel()
        train_loss = total / n_train

        if val_idx.numel() > 0:
            val = eval_loss(model, fetch, val_idx, args.batch, dev, args.lambda_)
            print(f"epoch {epoch+1:3d}/{args.epochs}  train {train_loss:.5f}  "
                  f"val {val:.5f}  ({time.time()-t0:.1f}s)")
        else:
            print(f"epoch {epoch+1:3d}/{args.epochs}  loss {train_loss:.5f}  "
                  f"({time.time()-t0:.1f}s)")

    if args.factorize:
        # Coalesce each bucket as shared[f] + delta[b * 768 + f].
        # Reclip the ordinary v2 table to keep it safe for int16 accumulators.
        import numpy as _np
        shared = model.ft_shared.weight[:INPUT].detach().cpu().numpy()          # (768, HL)
        delta = model.ft_delta.weight[:n_features].detach().cpu().numpy()       # (768*K, HL)
        ftw = delta + _np.tile(shared, (args.buckets, 1))                        # Broadcast per bucket
        ftw = _np.clip(ftw, -args.wclip, args.wclip)
    else:
        ftw = model.ft.weight[:n_features].detach().cpu().numpy()   # (n_features, HL)
    ftb = model.ftb.detach().cpu().numpy()                      # (HL,)
    ow = model.out.weight.detach().cpu().numpy().reshape(-1)    # (2*HL,)
    ob = float(model.out.bias.detach().cpu().numpy()[0])
    nt.export(args.out, ftw, ftb, ow, ob,
              bucket_map=(nt.KING_BUCKET_MAP if args.buckets > 1 else None))
    print("wrote", args.out)


if __name__ == "__main__":
    main()
