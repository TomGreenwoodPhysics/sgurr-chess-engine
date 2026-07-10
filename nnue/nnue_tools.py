"""NNUE network I/O, a random-net generator, and a numpy reference forward pass
that mirrors the C++ integer math exactly -- used to verify the engine's NNUE.
"""
import struct, sys
import numpy as np

INPUT, HL, QA, QB, SCALE = 768, 384, 255, 64, 400   # HL=384 since v4.0 (gen5)
MAGIC = b"RUKN"

def gen_random(path, seed=20260621):
    rng = np.random.default_rng(seed)
    ftw = rng.integers(-64, 65, size=INPUT * HL, dtype=np.int16)
    ftb = rng.integers(-64, 65, size=HL, dtype=np.int16)
    ow  = rng.integers(-64, 65, size=2 * HL, dtype=np.int16)
    ob  = int(rng.integers(-4096, 4097))
    with open(path, "wb") as f:
        f.write(MAGIC)
        f.write(struct.pack("<6I", 1, INPUT, HL, QA, QB, SCALE))
        f.write(ftw.tobytes()); f.write(ftb.tobytes())
        f.write(ow.tobytes());  f.write(struct.pack("<i", ob))

def load(path):
    with open(path, "rb") as f:
        assert f.read(4) == MAGIC
        ver, inp, hl, qa, qb, sc = struct.unpack("<6I", f.read(24))
        assert (inp, hl, qa, qb, sc) == (INPUT, HL, QA, QB, SCALE)
        ftw = np.frombuffer(f.read(INPUT*HL*2), dtype=np.int16).astype(np.int64).reshape(INPUT, HL)
        ftb = np.frombuffer(f.read(HL*2), dtype=np.int16).astype(np.int64)
        ow  = np.frombuffer(f.read(2*HL*2), dtype=np.int16).astype(np.int64)
        ob  = struct.unpack("<i", f.read(4))[0]
    return ftw, ftb, ow, ob

def pieces_from_fen(fen):
    """yield (colour, ptype, sq) for each piece. a1=0, sq=rank*8+file."""
    placement, side = fen.split()[0], fen.split()[1]
    letter = {"P":0,"N":1,"B":2,"R":3,"Q":4,"K":5}
    rows = placement.split("/")
    out = []
    for r, row in enumerate(rows):          # r=0 is rank 8 (top)
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
    ftw, ftb, ow, ob = net
    plist, stm = pieces_from_fen(fen)
    acc = [ftb.copy(), ftb.copy()]          # [white_pov, black_pov], int64
    for colour, ptype, sq in plist:
        for persp in (0, 1):
            acc[persp] += ftw[feat(persp, colour, ptype, sq)]
    us, them = acc[stm], acc[1-stm]
    cu = np.clip(us, 0, QA)
    ct = np.clip(them, 0, QA)
    out = int(np.dot(cu, ow[:HL]) + np.dot(ct, ow[HL:]))
    output = out + int(ob)
    cp = trunc_div(output * SCALE, QA * QB)
    cp = max(-29000, min(29000, cp))
    return output, cp

if __name__ == "__main__":
    if sys.argv[1] == "gen":
        gen_random(sys.argv[2])
        print("wrote random net", sys.argv[2])
    elif sys.argv[1] == "fwd":     # fwd <net> <fen...>
        net = load(sys.argv[2])
        fen = " ".join(sys.argv[3:])
        output, cp = forward(net, fen)
        print(output, cp)


# --- quantise + export: the trainer calls this to write a .nnue the engine loads ---
def export(path, ftw, ftb, ow, ob):
    """ftw: (INPUT,HL) float; ftb: (HL,) float; ow: (2*HL,) float; ob: float scalar.
    Quantises with the engine's QA/QB scales and writes the RUKN format."""
    ftw_q = np.clip(np.round(np.asarray(ftw) * QA), -32768, 32767).astype(np.int16).reshape(INPUT, HL)
    ftb_q = np.clip(np.round(np.asarray(ftb) * QA), -32768, 32767).astype(np.int16)
    ow_q  = np.clip(np.round(np.asarray(ow)  * QB), -32768, 32767).astype(np.int16)
    ob_q  = int(round(float(ob) * QA * QB))
    with open(path, "wb") as f:
        f.write(MAGIC)
        f.write(struct.pack("<6I", 1, INPUT, HL, QA, QB, SCALE))
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
    cu = np.clip(us, 0, 1); ct = np.clip(them, 0, 1)     # float CReLU (QA -> 1.0)
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