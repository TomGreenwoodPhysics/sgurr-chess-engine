#!/usr/bin/env python3
"""Generate a balanced opening book (EPD) using an engine's own evaluation.

Plays random legal opening lines a few plies deep, then keeps only positions
the engine scores as roughly equal -- so neither side starts with an edge.
"""
import argparse, random, sys, time
import chesslite as cl
from sprt import Engine

def shallow_eval(eng, fen, movetime_ms):
    eng._send(f"position fen {fen}")
    eng._send(f"go movetime {movetime_ms}")
    score = 0
    for line in eng.p.stdout:
        if line.startswith("info") and " score " in line:
            t = line.split()
            if "cp" in t:
                score = int(t[t.index("cp") + 1])
            elif "mate" in t:
                score = 100000
        if line.startswith("bestmove"):
            break
    return score

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True)
    ap.add_argument("--out", default="book.epd")
    ap.add_argument("--count", type=int, default=120)
    ap.add_argument("--plies", type=int, default=8)
    ap.add_argument("--threshold", type=int, default=70, help="max |cp| to accept")
    ap.add_argument("--movetime", type=int, default=120)
    ap.add_argument("--seed", type=int, default=20260621)
    args = ap.parse_args()

    random.seed(args.seed)
    eng = Engine(args.engine)
    seen, out = set(), []
    tries = 0
    t0 = time.time()
    while len(out) < args.count and tries < args.count * 60:
        tries += 1
        pos = cl.Position.from_fen(cl.START_FEN)
        ok = True
        for _ in range(args.plies):
            legal = cl.legal_moves(pos)
            if not legal:
                ok = False; break
            pos = cl.apply_move(pos, random.choice(legal))
        if not ok or not cl.legal_moves(pos):
            continue
        # build a FEN
        fen = to_fen(pos)
        epd = " ".join(fen.split()[:4])
        if epd in seen:
            continue
        sc = shallow_eval(eng, fen, args.movetime)
        if abs(sc) <= args.threshold:
            seen.add(epd)
            out.append(fen)
            if len(out) % 10 == 0:
                print(f"  {len(out)}/{args.count}  ({tries} tries, {time.time()-t0:.0f}s)",
                      flush=True)
    eng.quit()
    with open(args.out, "w") as f:
        for fen in out:
            f.write(fen + "\n")
    print(f"wrote {len(out)} balanced positions to {args.out}")

def to_fen(p):
    rows = []
    for r in range(7, -1, -1):
        row = ""; empty = 0
        for f in range(8):
            c = p.bd[cl.sq(f, r)]
            if c == ".":
                empty += 1
            else:
                if empty: row += str(empty); empty = 0
                row += c
        if empty: row += str(empty)
        rows.append(row)
    placement = "/".join(rows)
    side = "w" if p.white else "b"
    cr = "".join(x for x in "KQkq" if x in p.castle) or "-"
    ep = "-" if p.ep is None else chr(cl.fil(p.ep) + 97) + str(cl.rnk(p.ep) + 1)
    return f"{placement} {side} {cr} {ep} {p.half} {p.full}"

if __name__ == "__main__":
    main()