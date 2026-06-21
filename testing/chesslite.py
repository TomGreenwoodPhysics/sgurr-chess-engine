"""Minimal, perft-verified chess core for the SPRT harness.

Only what a match referee needs: apply UCI moves, generate legal moves,
and detect terminal states (checkmate / stalemate / draws). Not built for
speed -- the engines do the thinking; this just arbitrates the game.
"""

WP, BP = "P", "p"
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

def sq(f, r): return r * 8 + f
def fil(s): return s % 8
def rnk(s): return s // 8

class Position:
    __slots__ = ("bd", "white", "castle", "ep", "half", "full")

    def __init__(self):
        self.bd = list("." * 64)
        self.white = True
        self.castle = set()
        self.ep = None
        self.half = 0
        self.full = 1

    def copy(self):
        p = Position.__new__(Position)
        p.bd = self.bd[:]
        p.white = self.white
        p.castle = set(self.castle)
        p.ep = self.ep
        p.half = self.half
        p.full = self.full
        return p

    @staticmethod
    def from_fen(fen):
        p = Position()
        parts = fen.split()
        rows = parts[0].split("/")
        for r in range(8):
            f = 0
            for c in rows[7 - r]:
                if c.isdigit():
                    f += int(c)
                else:
                    p.bd[sq(f, r)] = c
                    f += 1
        p.white = (parts[1] == "w")
        p.castle = set(ch for ch in parts[2] if ch in "KQkq")
        p.ep = None if parts[3] == "-" else sq(ord(parts[3][0]) - 97, int(parts[3][1]) - 1)
        p.half = int(parts[4]) if len(parts) > 4 else 0
        p.full = int(parts[5]) if len(parts) > 5 else 1
        return p

    def key(self):
        # repetition key: placement + side + castling + ep
        return ("".join(self.bd), self.white, frozenset(self.castle), self.ep)

KN = [(1,2),(2,1),(2,-1),(1,-2),(-1,-2),(-2,-1),(-2,1),(-1,2)]
KG = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
DIAG = [(-1,-1),(-1,1),(1,-1),(1,1)]
ORTH = [(-1,0),(1,0),(0,-1),(0,1)]

def attacked(bd, s, by_white):
    tf, tr = fil(s), rnk(s)
    pr = -1 if by_white else 1
    for df in (-1, 1):
        f, r = tf + df, tr + pr
        if 0 <= f < 8 and 0 <= r < 8 and bd[sq(f, r)] == ("P" if by_white else "p"):
            return True
    for df, dr in KN:
        f, r = tf + df, tr + dr
        if 0 <= f < 8 and 0 <= r < 8 and bd[sq(f, r)] == ("N" if by_white else "n"):
            return True
    for df, dr in KG:
        f, r = tf + df, tr + dr
        if 0 <= f < 8 and 0 <= r < 8 and bd[sq(f, r)] == ("K" if by_white else "k"):
            return True
    for dirs, pcs in ((DIAG, "BQ"), (ORTH, "RQ")):
        tgt = pcs if by_white else pcs.lower()
        for df, dr in dirs:
            f, r = tf + df, tr + dr
            while 0 <= f < 8 and 0 <= r < 8:
                c = bd[sq(f, r)]
                if c != ".":
                    if c in tgt:
                        return True
                    break
                f += df; r += dr
    return False

def king_sq(bd, white):
    return bd.index("K" if white else "k")

def pseudo_moves(p):
    bd = p.bd
    white = p.white
    own = str.isupper if white else str.islower
    opp = str.islower if white else str.isupper
    moves = []
    for s in range(64):
        c = bd[s]
        if c == "." or not own(c):
            continue
        f, r = fil(s), rnk(s)
        u = c.upper()
        if u == "P":
            d = 1 if white else -1
            start = 1 if white else 6
            promo = 7 if white else 0
            one = sq(f, r + d)
            if 0 <= r + d < 8 and bd[one] == ".":
                if r + d == promo:
                    for pc in "qrbn":
                        moves.append((s, one, pc))
                else:
                    moves.append((s, one, None))
                    if r == start and bd[sq(f, r + 2 * d)] == ".":
                        moves.append((s, sq(f, r + 2 * d), None))
            for df in (-1, 1):
                nf, nr = f + df, r + d
                if 0 <= nf < 8 and 0 <= nr < 8:
                    t = sq(nf, nr)
                    if bd[t] != "." and opp(bd[t]):
                        if nr == promo:
                            for pc in "qrbn":
                                moves.append((s, t, pc))
                        else:
                            moves.append((s, t, None))
                    elif p.ep is not None and t == p.ep:
                        moves.append((s, t, None))
        elif u == "N":
            for df, dr in KN:
                nf, nr = f + df, r + dr
                if 0 <= nf < 8 and 0 <= nr < 8:
                    t = sq(nf, nr)
                    if bd[t] == "." or opp(bd[t]):
                        moves.append((s, t, None))
        elif u == "K":
            for df, dr in KG:
                nf, nr = f + df, r + dr
                if 0 <= nf < 8 and 0 <= nr < 8:
                    t = sq(nf, nr)
                    if bd[t] == "." or opp(bd[t]):
                        moves.append((s, t, None))
            # castling
            if white and s == 4:
                if "K" in p.castle and bd[5] == "." and bd[6] == "." and bd[7] == "R" \
                   and not attacked(bd, 4, False) and not attacked(bd, 5, False) and not attacked(bd, 6, False):
                    moves.append((4, 6, None))
                if "Q" in p.castle and bd[3] == "." and bd[2] == "." and bd[1] == "." and bd[0] == "R" \
                   and not attacked(bd, 4, False) and not attacked(bd, 3, False) and not attacked(bd, 2, False):
                    moves.append((4, 2, None))
            if (not white) and s == 60:
                if "k" in p.castle and bd[61] == "." and bd[62] == "." and bd[63] == "r" \
                   and not attacked(bd, 60, True) and not attacked(bd, 61, True) and not attacked(bd, 62, True):
                    moves.append((60, 62, None))
                if "q" in p.castle and bd[59] == "." and bd[58] == "." and bd[57] == "." and bd[56] == "r" \
                   and not attacked(bd, 60, True) and not attacked(bd, 59, True) and not attacked(bd, 58, True):
                    moves.append((60, 58, None))
        else:
            dirs = DIAG if u == "B" else ORTH if u == "R" else DIAG + ORTH
            for df, dr in dirs:
                nf, nr = f + df, r + dr
                while 0 <= nf < 8 and 0 <= nr < 8:
                    t = sq(nf, nr)
                    if bd[t] == ".":
                        moves.append((s, t, None))
                    else:
                        if opp(bd[t]):
                            moves.append((s, t, None))
                        break
                    nf += df; nr += dr
    return moves

def apply_move(p, m):
    """Return a new Position after move m=(from,to,promo). Assumes legal/pseudo."""
    n = p.copy()
    bd = n.bd
    s, t, promo = m
    c = bd[s]
    u = c.upper()
    n.ep = None
    n.half = p.half + 1
    if u == "P" or bd[t] != ".":
        n.half = 0
    # en passant capture
    if u == "P" and fil(s) != fil(t) and bd[t] == ".":
        cap = t - 8 if c == "P" else t + 8
        bd[cap] = "."
    # double push sets ep
    if u == "P" and abs(rnk(t) - rnk(s)) == 2:
        n.ep = (s + t) // 2
    # castling rook move
    if u == "K" and abs(fil(s) - fil(t)) == 2:
        if t == 6: bd[5], bd[7] = bd[7], "."
        elif t == 2: bd[3], bd[0] = bd[0], "."
        elif t == 62: bd[61], bd[63] = bd[63], "."
        elif t == 58: bd[59], bd[56] = bd[56], "."
    bd[t] = c
    bd[s] = "."
    if promo:
        bd[t] = promo.upper() if c.isupper() else promo.lower()
    # update castling rights
    for srt, ch in ((4,"KQ"),(60,"kq")):
        if s == srt:
            for x in ch: n.castle.discard(x)
    for corner, ch in ((0,"Q"),(7,"K"),(56,"q"),(63,"k")):
        if s == corner or t == corner:
            n.castle.discard(ch)
    if not p.white:
        n.full = p.full + 1
    n.white = not p.white
    return n

def legal_moves(p):
    out = []
    for m in pseudo_moves(p):
        n = apply_move(p, m)
        if not attacked(n.bd, king_sq(n.bd, p.white), n.white):
            out.append(m)
    return out

def in_check(p):
    return attacked(p.bd, king_sq(p.bd, p.white), not p.white)

def move_to_uci(m):
    s, t, promo = m
    a = chr(fil(s) + 97) + str(rnk(s) + 1)
    b = chr(fil(t) + 97) + str(rnk(t) + 1)
    return a + b + (promo if promo else "")

def insufficient_material(bd):
    pieces = [c for c in bd if c not in ".Kk"]
    if not pieces:
        return True
    if len(pieces) == 1 and pieces[0].upper() in "BN":
        return True
    if len(pieces) == 2 and all(x.upper() == "B" for x in pieces):
        # both bishops same colour square -> draw (approx: treat KBKB as draw-ish only if same colour)
        bsq = [i for i, c in enumerate(bd) if c.upper() == "B"]
        if len(bsq) == 2 and ((fil(bsq[0]) + rnk(bsq[0])) % 2) == ((fil(bsq[1]) + rnk(bsq[1])) % 2):
            return True
    return False

def perft(p, d):
    if d == 0:
        return 1
    total = 0
    for m in legal_moves(p):
        total += perft(apply_move(p, m), d - 1)
    return total

if __name__ == "__main__":
    tests = [
        (START_FEN, 3, 8902),
        ("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", 3, 97862),
        ("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", 4, 43238),
        ("r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", 3, 9467),
        ("rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", 3, 62379),
        (START_FEN, 4, 197281),
        ("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", 5, 674624),
    ]
    ok = True
    for fen, d, exp in tests:
        got = perft(Position.from_fen(fen), d)
        status = "OK " if got == exp else "BAD"
        if got != exp: ok = False
        print(f"{status} perft({d})={got} exp={exp}  {fen[:32]}")
    print("ALL PASS" if ok else "FAILURES")