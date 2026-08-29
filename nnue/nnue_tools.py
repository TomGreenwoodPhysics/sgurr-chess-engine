"""NNUE network I/O, a random-net generator, and a numpy reference forward pass
that mirrors the C++ integer math exactly -- used to verify the engine's NNUE.
"""
import struct, sys
import numpy as np

INPUT, HL, QA, QB, SCALE = 768, 384, 255, 64, 400   # HL has been 384 since v4.0
MAGIC = b"RUKN"

# King buckets for version 2 nets
# Each view uses its own king's relative square, with black mirrored by sq ^ 56.
# Back-rank buckets are finer than those on higher ranks. The map is embedded in
# each net so the trainer and engine use the same bucket assignment.
def _build_king_bucket_map():
    m = np.zeros(64, np.uint8)
    for sq in range(64):
        r, f = sq // 8, sq % 8
        if r == 0:
            m[sq] = f // 2        # a1b1=0  c1d1=1  e1f1=2  g1h1=3
        elif r == 1:
            m[sq] = 4             # Rank 2
        elif r <= 3:
            m[sq] = 5             # Ranks 3 and 4
        elif r <= 5:
            m[sq] = 6             # Ranks 5 and 6
        else:
            m[sq] = 7             # Ranks 7 and 8
    return m

KING_BUCKET_MAP = _build_king_bucket_map()
BUCKETS = int(KING_BUCKET_MAP.max()) + 1          # 8

def gen_random(path, seed=20260621, buckets=1):
    """Random net for engine verification. buckets>1 writes a version-2 file
    with KING_BUCKET_MAP, exercising the engine's bucketed load/index path."""
    rng = np.random.default_rng(seed)
    n_features = INPUT * buckets
    ftw = rng.integers(-64, 65, size=n_features * HL, dtype=np.int16)
    ftb = rng.integers(-64, 65, size=HL, dtype=np.int16)
    ow  = rng.integers(-64, 65, size=2 * HL, dtype=np.int16)
    ob  = int(rng.integers(-4096, 4097))
    with open(path, "wb") as f:
        f.write(MAGIC)
        if buckets == 1:
            f.write(struct.pack("<6I", 1, INPUT, HL, QA, QB, SCALE))
        else:
            assert buckets == BUCKETS, "random v2 nets use KING_BUCKET_MAP"
            f.write(struct.pack("<6I", 2, n_features, HL, QA, QB, SCALE))
            f.write(KING_BUCKET_MAP.tobytes())
        f.write(ftw.tobytes()); f.write(ftb.tobytes())
        f.write(ow.tobytes());  f.write(struct.pack("<i", ob))

def load(path):
    """-> (ftw, ftb, ow, ob, buckets, bucket_map). v1 files load as buckets=1
    with an all-zero map, so callers can treat every net uniformly."""
    with open(path, "rb") as f:
        assert f.read(4) == MAGIC
        ver, inp, hl, qa, qb, sc = struct.unpack("<6I", f.read(24))
        assert (hl, qa, qb, sc) == (HL, QA, QB, SCALE)
        if ver == 1:
            assert inp == INPUT
            buckets, bmap = 1, np.zeros(64, np.uint8)
        elif ver == 2:
            assert inp % INPUT == 0, f"v2 input {inp} not a multiple of {INPUT}"
            buckets = inp // INPUT
            bmap = np.frombuffer(f.read(64), dtype=np.uint8).copy()
            assert int(bmap.max()) < buckets, "bucket map entry out of range"
        else:
            raise AssertionError(f"unknown net version {ver}")
        ftw = np.frombuffer(f.read(inp*HL*2), dtype=np.int16).astype(np.int64).reshape(inp, HL)
        ftb = np.frombuffer(f.read(HL*2), dtype=np.int16).astype(np.int64)
        ow  = np.frombuffer(f.read(2*HL*2), dtype=np.int16).astype(np.int64)
        ob  = struct.unpack("<i", f.read(4))[0]
    return ftw, ftb, ow, ob, buckets, bmap

def pieces_from_fen(fen):
    """yield (colour, ptype, sq) for each piece. a1=0, sq=rank*8+file."""
    placement, side = fen.split()[0], fen.split()[1]
    letter = {"P":0,"N":1,"B":2,"R":3,"Q":4,"K":5}
    rows = placement.split("/")
    out = []
    for r, row in enumerate(rows):          # Row 0 is rank 8
        rank = 7 - r
        file = 0
        for ch in row:
            if ch.isdigit():
                file += int(ch)
            else:
                colour = 0 if ch.isupper() else 1
                ptype = letter[ch.upper()]
                out.append((colour, ptype, rank*8 + file))
                file += 1
    return out, (0 if side == "w" else 1)

def feat(persp, colour, ptype, sq):
    rel_sq = sq if persp == 0 else (sq ^ 56)
    rel_colour = 0 if colour == persp else 1
    return rel_colour*384 + ptype*64 + rel_sq

def trunc_div(num, den):
    q = abs(num) // abs(den)
    return -q if (num < 0) != (den < 0) else q

def forward(net, fen):
    ftw, ftb, ow, ob, buckets, bmap = net
    plist, stm = pieces_from_fen(fen)
    # Find each view's bucket from its own king.
    off = [0, 0]
    if buckets > 1:
        kings = {c: sq for (c, pt, sq) in plist if pt == 5}
        off[0] = int(bmap[kings[0]]) * INPUT
        off[1] = int(bmap[kings[1] ^ 56]) * INPUT
    acc = [ftb.copy(), ftb.copy()]          # [white_pov, black_pov], int64
    for colour, ptype, sq in plist:
        for persp in (0, 1):
            acc[persp] += ftw[off[persp] + feat(persp, colour, ptype, sq)]
    us, them = acc[stm], acc[1-stm]
    cu = np.clip(us, 0, QA)
    ct = np.clip(them, 0, QA)
    out = int(np.dot(cu, ow[:HL]) + np.dot(ct, ow[HL:]))
    output = out + int(ob)
    cp = trunc_div(output * SCALE, QA * QB)
    cp = max(-29000, min(29000, cp))
    return output, cp

if __name__ == "__main__":
    if sys.argv[1] == "gen":            # gen <path> [buckets]
        k = int(sys.argv[3]) if len(sys.argv) > 3 else 1
        gen_random(sys.argv[2], buckets=k)
        print(f"wrote random net {sys.argv[2]} (buckets={k})")
    elif sys.argv[1] == "fwd":     # fwd <net> <fen...>
        net = load(sys.argv[2])
        fen = " ".join(sys.argv[3:])
        output, cp = forward(net, fen)
        print(output, cp)


# Quantise and export a net for the engine.
def export(path, ftw, ftb, ow, ob, bucket_map=None):
    """ftw: (n_features,HL) float; ftb: (HL,) float; ow: (2*HL,) float; ob: scalar.
    Quantises with the engine's QA/QB scales and writes the RUKN format.
    bucket_map None -> version-1 (n_features must be INPUT); otherwise a
    64-entry uint8 map -> version-2 with the map embedded after the header."""
    ftw = np.asarray(ftw)
    n_features = ftw.shape[0] if ftw.ndim == 2 else ftw.size // HL
    ftw_q = np.clip(np.round(ftw * QA), -32768, 32767).astype(np.int16).reshape(n_features, HL)
    ftb_q = np.clip(np.round(np.asarray(ftb) * QA), -32768, 32767).astype(np.int16)
    ow_q  = np.clip(np.round(np.asarray(ow)  * QB), -32768, 32767).astype(np.int16)
    ob_q  = int(round(float(ob) * QA * QB))
    with open(path, "wb") as f:
        f.write(MAGIC)
        if bucket_map is None:
            assert n_features == INPUT, f"v1 export needs {INPUT} features, got {n_features}"
            f.write(struct.pack("<6I", 1, INPUT, HL, QA, QB, SCALE))
        else:
            bmap = np.asarray(bucket_map, np.uint8)
            assert bmap.size == 64
            assert n_features == (int(bmap.max()) + 1) * INPUT, \
                f"features {n_features} disagree with map buckets {int(bmap.max())+1}"
            f.write(struct.pack("<6I", 2, n_features, HL, QA, QB, SCALE))
            f.write(bmap.tobytes())
        f.write(ftw_q.tobytes()); f.write(ftb_q.tobytes())
        f.write(ow_q.tobytes());  f.write(struct.pack("<i", ob_q))

def forward_float(ftw, ftb, ow, ob, fen):
    """Reference float forward (what the trainer's model computes), in centipawns."""
    plist, stm = pieces_from_fen(fen)
    acc = [np.array(ftb, dtype=np.float64), np.array(ftb, dtype=np.float64)]
    for colour, ptype, sq in plist:
        for persp in (0, 1):
            acc[persp] = acc[persp] + ftw[feat(persp, colour, ptype, sq)]
    us, them = acc[stm], acc[1-stm]
    cu = np.clip(us, 0, 1); ct = np.clip(them, 0, 1)     # Float CReLU with QA mapped to 1.0
    out = float(np.dot(cu, ow[:HL]) + np.dot(ct, ow[HL:]) + ob)
    return out * SCALE


def decode_record(rec):
    """Decode one 32-byte datagen record -> (pieces, stm, score, result).
    pieces is a list of (colour, ptype, sq). Mirrors datagen.cpp packing."""
    occ = struct.unpack_from("<Q", rec, 0)[0]
    nibbles = rec[8:24]
    stm, score, result = struct.unpack_from("<BhB", rec, 24)
    pieces = []
    bb = occ; i = 0
    while bb:
        sq = (bb & -bb).bit_length() - 1
        bb &= bb - 1
        byte = nibbles[i >> 1]
        pc = (byte >> 4) if (i & 1) else (byte & 0xF)
        pieces.append((pc // 6, pc % 6, sq))   # (colour, ptype, sq)
        i += 1
    return pieces, stm, score, result
