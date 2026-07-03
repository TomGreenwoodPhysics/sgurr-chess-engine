#!/usr/bin/env python3
"""Self-contained SPRT match runner for UCI engines (no dependencies).

Plays NEW vs BASE in colour-balanced pairs from an opening book under a real
time control, tracks each game independently (every engine move is checked for
legality), and runs a sequential probability ratio test, stopping as soon as
the log-likelihood ratio crosses an acceptance bound.

Example:
  python3 sprt.py --new ./sgr_new --base ./sgr_old \\
      --tc 8+0.08 --book book.epd --concurrency 6 \\
      --elo0 0 --elo1 5 --alpha 0.05 --beta 0.05
"""

import argparse, math, os, queue, subprocess, sys, threading, time
import chesslite as cl


# ----------------------------- SPRT statistics -----------------------------

def sprt_llr(w, d, l, elo0, elo1):
    n = w + d + l
    if n == 0:
        return 0.0
    s0 = 1.0 / (1.0 + 10 ** (-elo0 / 400.0))
    s1 = 1.0 / (1.0 + 10 ** (-elo1 / 400.0))
    xbar = (w + 0.5 * d) / n
    var = (w * (1 - xbar) ** 2 + d * (0.5 - xbar) ** 2 + l * (0 - xbar) ** 2) / n
    var = max(var, 1e-9)
    # Normal-approximation LLR (the trinomial SPRT cutechess-cli uses).
    return (s1 - s0) * (2 * xbar - s0 - s1) * n / (2 * var)

def elo_with_ci(w, d, l):
    n = w + d + l
    if n == 0:
        return 0.0, 0.0
    xbar = (w + 0.5 * d) / n
    if xbar <= 0:
        return -800.0, 0.0
    if xbar >= 1:
        return 800.0, 0.0
    elo = -400 * math.log10((1 - xbar) / xbar)
    var = (w * (1 - xbar) ** 2 + d * (0.5 - xbar) ** 2 + l * (0 - xbar) ** 2) / n
    se = math.sqrt(var / n) if n > 0 else 0
    lo_x, hi_x = max(1e-6, xbar - 1.96 * se), min(1 - 1e-6, xbar + 1.96 * se)
    lo = -400 * math.log10((1 - lo_x) / lo_x)
    hi = -400 * math.log10((1 - hi_x) / hi_x)
    return elo, (hi - lo) / 2


# ----------------------------- UCI engine ----------------------------------

class Engine:
    def __init__(self, path):
        self.path = path
        self.p = subprocess.Popen(
            [path, "uci"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, bufsize=1,
        )
        self._send("uci"); self._wait("uciok")
        self._send("isready"); self._wait("readyok")

    def _send(self, c):
        self.p.stdin.write(c + "\n"); self.p.stdin.flush()

    def _wait(self, tok):
        for line in self.p.stdout:
            if line.strip() == tok or line.startswith(tok):
                return

    def newgame(self):
        self._send("ucinewgame"); self._send("isready"); self._wait("readyok")

    def bestmove(self, start, moves, wt, bt, wi, bi):
        if start == "startpos":
            pos = "position startpos"
        else:
            pos = "position fen " + start
        if moves:
            pos += " moves " + " ".join(moves)
        self._send(pos)
        self._send(f"go wtime {int(wt)} btime {int(bt)} winc {int(wi)} binc {int(bi)}")
        t0 = time.perf_counter()
        mv = None
        for line in self.p.stdout:
            if line.startswith("bestmove"):
                toks = line.split()
                mv = toks[1] if len(toks) > 1 else "0000"
                break
        dt = (time.perf_counter() - t0) * 1000.0
        return mv, dt

    def quit(self):
        try:
            self._send("quit"); self.p.wait(timeout=2)
        except Exception:
            self.p.kill()


# ------------------------------- one game ----------------------------------
# result is from WHITE's perspective: 1.0 win, 0.5 draw, 0.0 loss

def play_game(white, black, start_fen, opening_moves, tc):
    base_ms, inc_ms = tc
    pos = cl.Position.from_fen(start_fen)
    moves = []
    # replay opening line
    for um in opening_moves:
        legal = {cl.move_to_uci(m): m for m in cl.legal_moves(pos)}
        if um not in legal:
            break
        pos = cl.apply_move(pos, legal[um])
        moves.append(um)

    wt = bt = float(base_ms)
    seen = {}
    white.newgame(); black.newgame()

    for _ply in range(600):
        legal = cl.legal_moves(pos)
        if not legal:
            if cl.in_check(pos):
                return 0.0 if pos.white else 1.0   # side to move is mated
            return 0.5                              # stalemate
        if pos.half >= 100 or cl.insufficient_material(pos.bd):
            return 0.5
        k = pos.key()
        seen[k] = seen.get(k, 0) + 1
        if seen[k] >= 3:
            return 0.5

        eng = white if pos.white else black
        mv, dt = eng.bestmove(start_fen, moves, wt, bt, inc_ms, inc_ms)

        if pos.white:
            wt -= dt
            if wt < 0:
                return 0.0   # white forfeits on time
            wt += inc_ms
        else:
            bt -= dt
            if bt < 0:
                return 1.0   # black forfeits on time
            bt += inc_ms

        legal_uci = {cl.move_to_uci(m): m for m in legal}
        if mv not in legal_uci:
            # illegal or null move: the offending side loses
            sys.stderr.write(f"[illegal '{mv}' by {'white' if pos.white else 'black'} "
                             f"({eng.path})]\n")
            return 0.0 if pos.white else 1.0
        pos = cl.apply_move(pos, legal_uci[mv])
        moves.append(mv)

    return 0.5   # ply cap


# ------------------------------ orchestration ------------------------------

def load_book(path):
    lines = []
    if path and os.path.exists(path):
        for raw in open(path):
            s = raw.strip()
            if not s or s.startswith("#"):
                continue
            if "/" in s:                      # FEN (EPD: first 4-6 fields)
                lines.append(("fen", s))
            else:                             # UCI opening line from startpos
                lines.append(("moves", s.split()))
    if not lines:
        lines.append(("moves", []))           # fall back to bare startpos
    return lines

def opening_for(entry):
    kind, val = entry
    if kind == "fen":
        # normalise EPD to a full FEN if move counters are missing
        f = val.split()
        while len(f) < 6:
            f.append("0" if len(f) == 4 else "1")
        return " ".join(f[:6]), []
    return cl.START_FEN, val


class Tally:
    def __init__(self, args):
        self.w = self.d = self.l = 0
        self.pairs_done = 0
        self.lock = threading.Lock()
        self.args = args
        self.min_games = args.min_games
        self.upper = math.log((1 - args.beta) / args.alpha)
        self.lower = math.log(args.beta / (1 - args.alpha))
        self.decided = None

    def record_pair(self, r1, r2):
        # r1,r2 are NEW's score in the two colour-swapped games
        with self.lock:
            for r in (r1, r2):
                if r == 1.0: self.w += 1
                elif r == 0.5: self.d += 1
                else: self.l += 1
            self.pairs_done += 1
            llr = sprt_llr(self.w, self.d, self.l, self.args.elo0, self.args.elo1)
            elo, ci = elo_with_ci(self.w, self.d, self.l)
            n = self.w + self.d + self.l
            print(f"  games {n:4d}  +{self.w} ={self.d} -{self.l}   "
                  f"Elo {elo:+6.1f} +/-{ci:4.1f}   LLR {llr:+.2f} "
                  f"[{self.lower:.2f}, {self.upper:.2f}]", flush=True)
            if self.decided is None and n >= self.min_games:
                if llr >= self.upper:
                    self.decided = "H1 ACCEPTED  (new engine is stronger: pass)"
                elif llr <= self.lower:
                    self.decided = "H0 ACCEPTED  (not an improvement: fail)"
            return self.decided is not None


def worker(tally, jobs, args):
    new_eng = Engine(args.new)
    base_eng = Engine(args.base)
    try:
        while True:
            if tally.decided is not None:
                break
            try:
                entry = jobs.get_nowait()
            except queue.Empty:
                break
            start_fen, omoves = opening_for(entry)
            # game 1: NEW is white ; game 2: NEW is black
            r1 = play_game(new_eng, base_eng, start_fen, omoves, args.tc)
            r2 = play_game(base_eng, new_eng, start_fen, omoves, args.tc)
            new_r2 = 1.0 - r2   # convert white-perspective to NEW-perspective
            if tally.record_pair(r1, new_r2):
                break
    finally:
        new_eng.quit(); base_eng.quit()


def parse_tc(s):
    # "8+0.08" -> (8000 ms, 80 ms) ; "0.5" -> (500 ms, 0)
    if "+" in s:
        base, inc = s.split("+")
    else:
        base, inc = s, "0"
    return (int(float(base) * 1000), int(float(inc) * 1000))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--new", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--tc", default="8+0.08", help="base+increment seconds, e.g. 8+0.08")
    ap.add_argument("--book", default="book.epd")
    ap.add_argument("--concurrency", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--elo0", type=float, default=0.0)
    ap.add_argument("--elo1", type=float, default=5.0)
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--beta", type=float, default=0.05)
    ap.add_argument("--max-pairs", type=int, default=20000)
    ap.add_argument("--min-games", type=int, default=16,
                    help="don't decide before this many games (guards tiny-sample variance)")
    ap.add_argument("--rounds", type=int, default=1, help="times to cycle the book")
    args = ap.parse_args()
    args.tc = parse_tc(args.tc)

    book = load_book(args.book)
    jobs = queue.Queue()
    n_pairs = 0
    for _ in range(args.rounds):
        for e in book:
            if n_pairs >= args.max_pairs:
                break
            jobs.put(e); n_pairs += 1

    print(f"SPRT  new={args.new}  base={args.base}")
    print(f"TC={args.tc[0]/1000:g}+{args.tc[1]/1000:g}s  book={args.book} "
          f"({len(book)} lines)  concurrency={args.concurrency}")
    print(f"H0: Elo<={args.elo0}   H1: Elo>={args.elo1}   "
          f"alpha={args.alpha} beta={args.beta}   up-to {n_pairs} pairs\n")

    tally = Tally(args)
    threads = [threading.Thread(target=worker, args=(tally, jobs, args))
               for _ in range(args.concurrency)]
    t0 = time.time()
    for t in threads: t.start()
    for t in threads: t.join()

    print()
    if tally.decided:
        print(">>> " + tally.decided)
    else:
        llr = sprt_llr(tally.w, tally.d, tally.l, args.elo0, args.elo1)
        print(f">>> inconclusive after {tally.w+tally.d+tally.l} games (LLR {llr:+.2f})")
    elo, ci = elo_with_ci(tally.w, tally.d, tally.l)
    print(f"    final: +{tally.w} ={tally.d} -{tally.l}   Elo {elo:+.1f} +/- {ci:.1f}   "
          f"({time.time()-t0:.0f}s)")

if __name__ == "__main__":
    main()