import struct, sys
import chesslite as cl

PIECE_CHARS = "PNBRQKpnbrqk"

def unpack(rec):
    occ = struct.unpack_from("<Q", rec, 0)[0]
    nibbles = rec[8:24]
    stm, score, result = struct.unpack_from("<BhB", rec, 24)
    # Reconstruct the board.
    bd = list("." * 64)
    i = 0
    bb = occ
    sqs = []
    while bb:
        sq = (bb & -bb).bit_length() - 1
        sqs.append(sq); bb &= bb - 1
    for idx, sq in enumerate(sqs):
        byte = nibbles[idx >> 1]
        piece = (byte >> 4) if (idx & 1) else (byte & 0xF)
        bd[sq] = PIECE_CHARS[piece]
    return bd, stm, score, result

def to_fen(bd, stm):
    rows = []
    for r in range(7, -1, -1):
        row=""; e=0
        for f in range(8):
            c = bd[r*8+f]
            if c == ".": e += 1
            else:
                if e: row += str(e); e = 0
                row += c
        if e: row += str(e)
        rows.append(row)
    return "/".join(rows) + (" w " if stm == 0 else " b ") + "- - 0 1"

data = open(sys.argv[1], "rb").read()
n = len(data) // 32
bad = 0; checked = 0
score_min = 9999; score_max = -9999
res_counts = {0:0,1:0,2:0}
import random
random.seed(0)
idxs = list(range(n))
random.shuffle(idxs)
for k in idxs[:400]:                       # Validate a random sample of 400
    bd, stm, score, result = unpack(data[k*32:k*32+32])
    res_counts[result] = res_counts.get(result,0)+1
    score_min = min(score_min, score); score_max = max(score_max, score)
    # Check kings, metadata, and score bounds.
    if bd.count("K") != 1 or bd.count("k") != 1: bad += 1; continue
    if result not in (0,1,2) or stm not in (0,1): bad += 1; continue
    if abs(score) >= 2000: bad += 1; continue
    # The position must parse and be legal in chesslite.
    try:
        p = cl.Position.from_fen(to_fen(bd, stm))
        _ = cl.legal_moves(p)               # Must not raise
        # The side to move cannot already be checking its opponent.
        opp_white = (stm == 1)
        if cl.attacked(p.bd, cl.king_sq(p.bd, opp_white), not opp_white):
            bad += 1; continue
    except Exception:
        bad += 1; continue
    checked += 1

print(f"records={n}  validated={checked}/400  bad={bad}")
print(f"score range=[{score_min},{score_max}]  result counts L/D/W={res_counts}")
print("FORMAT + POSITIONS VALID" if bad == 0 else f"{bad} BAD RECORDS")
