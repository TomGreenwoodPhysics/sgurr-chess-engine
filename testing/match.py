#!/usr/bin/env python3
"""Plain head-to-head match between two pre-compiled UCI engines.

Default setup:
  A = Ruk NNUE executable, loading nets/gen1.nnue
  B = classical/base Ruk executable, forced to HCE

Run:
  python3 match.py

Or override:
  python3 match.py ./engines/ruk_gen1.exe ./engines/baselines/ruk_base.exe --games 200
"""

# ---------------------------------------------------------------------------
ENGINE_A = "../engines/ruk_gen1.exe"
ENGINE_A_NET = "../nets/gen1.nnue"

ENGINE_B = "../engines/baselines/ruk_base.exe"
ENGINE_B_NET = ""

NO_NET_PATH = "../nets/__no_net__.nnue"          # intentionally absent
GAMES = 2                                      # total games, colour-swapped pairs
TC = "8+0.08"                                  # base+increment, or "mt=0.1"
BOOK = "book.epd"                              # EPD/FEN per line. "" = startpos
CONCURRENCY = 6
# ---------------------------------------------------------------------------

import argparse
import math
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass

import chesslite as cl


@dataclass(frozen=True)
class EngineSpec:
    path: str
    net_path: str | None = None
    name: str = "engine"


class Engine:
    def __init__(self, spec: EngineSpec):
        self.spec = spec
        self.path = spec.path

        if not os.path.exists(self.path):
            raise FileNotFoundError(f"engine executable not found: {self.path}")

        if spec.net_path is not None and spec.net_path != NO_NET_PATH:
            if not os.path.exists(spec.net_path):
                raise FileNotFoundError(f"NNUE file not found: {spec.net_path}")

        env = dict(os.environ)

        # RUK_EVALFILE selects the eval: a real net path for NNUE, or a
        # missing path so an NNUE-capable binary falls back to HCE.
        if spec.net_path is not None:
            env["RUK_EVALFILE"] = spec.net_path

        self.p = subprocess.Popen(
            [self.path, "uci"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )

        self._send("uci")
        self._wait("uciok")
        self._send("isready")
        self._wait("readyok")

    def _send(self, c):
        self.p.stdin.write(c + "\n")
        self.p.stdin.flush()

    def _wait(self, tok):
        for line in self.p.stdout:
            if line.strip() == tok or line.startswith(tok):
                return

    def newgame(self):
        self._send("ucinewgame")
        self._send("isready")
        self._wait("readyok")

    def bestmove(self, start, moves, wt, bt, wi, bi, movetime):
        pos = "position startpos" if start == "startpos" else "position fen " + start
        if moves:
            pos += " moves " + " ".join(moves)

        self._send(pos)

        if movetime is not None:
            self._send(f"go movetime {int(movetime)}")
        else:
            self._send(
                f"go wtime {int(wt)} btime {int(bt)} "
                f"winc {int(wi)} binc {int(bi)}"
            )

        t0 = time.perf_counter()
        mv = None

        for line in self.p.stdout:
            if line.startswith("bestmove"):
                t = line.split()
                mv = t[1] if len(t) > 1 else "0000"
                break

        return mv, (time.perf_counter() - t0) * 1000.0

    def quit(self):
        try:
            self._send("quit")
            self.p.wait(timeout=2)
        except Exception:
            self.p.kill()


def play_game(white, black, start_fen, opening_moves, tc):
    base_ms, inc_ms, movetime = tc
    pos = cl.Position.from_fen(start_fen)
    moves = []

    for um in opening_moves:
        legal = {cl.move_to_uci(m): m for m in cl.legal_moves(pos)}
        if um not in legal:
            break
        pos = cl.apply_move(pos, legal[um])
        moves.append(um)

    wt = bt = float(base_ms)
    seen = {}

    white.newgame()
    black.newgame()

    for _ in range(600):
        legal = cl.legal_moves(pos)

        if not legal:
            return (0.0 if pos.white else 1.0) if cl.in_check(pos) else 0.5

        if pos.half >= 100 or cl.insufficient_material(pos.bd):
            return 0.5

        k = pos.key()
        seen[k] = seen.get(k, 0) + 1
        if seen[k] >= 3:
            return 0.5

        eng = white if pos.white else black
        mv, dt = eng.bestmove(start_fen, moves, wt, bt, inc_ms, inc_ms, movetime)

        if movetime is None:
            if pos.white:
                wt -= dt
                if wt < 0:
                    return 0.0
                wt += inc_ms
            else:
                bt -= dt
                if bt < 0:
                    return 1.0
                bt += inc_ms

        legal_uci = {cl.move_to_uci(m): m for m in legal}

        if mv not in legal_uci:
            sys.stderr.write(
                f"[illegal '{mv}' by {'white' if pos.white else 'black'} "
                f"({eng.spec.name}: {eng.path})]\n"
            )
            return 0.0 if pos.white else 1.0

        pos = cl.apply_move(pos, legal_uci[mv])
        moves.append(mv)

    return 0.5


def load_book(path):
    out = []

    if path and os.path.exists(path):
        for raw in open(path):
            s = raw.strip()
            if s and not s.startswith("#"):
                out.append(s if "/" in s else None)

        out = [x for x in out if x]

    return out or [None]


def opening_for(entry):
    if entry is None:
        return cl.START_FEN, []

    f = entry.split()

    while len(f) < 6:
        f.append("0" if len(f) == 4 else "1")

    return " ".join(f[:6]), []


class Tally:
    def __init__(self, name_a):
        self.w = self.d = self.l = 0
        self.lock = threading.Lock()
        self.name_a = name_a

    def record_pair(self, ra, rb_white):
        # ra = A's score as white
        # rb_white = white's score in game 2, where B was white
        a2 = 1.0 - rb_white

        with self.lock:
            for r in (ra, a2):
                if r == 1.0:
                    self.w += 1
                elif r == 0.5:
                    self.d += 1
                else:
                    self.l += 1

            n = self.w + self.d + self.l
            elo, ci = elo_with_ci(self.w, self.d, self.l)
            pct = 100.0 * (self.w + 0.5 * self.d) / n

            print(
                f"  after {n:4d}:  {self.name_a} "
                f"+{self.w} ={self.d} -{self.l}   "
                f"{pct:5.1f}%   Elo {elo:+.0f} +/-{ci:.0f}",
                flush=True,
            )


def elo_with_ci(w, d, l):
    n = w + d + l

    if n == 0:
        return 0.0, 0.0

    x = (w + 0.5 * d) / n

    if x <= 0:
        return -800.0, 0.0

    if x >= 1:
        return 800.0, 0.0

    elo = -400 * math.log10((1 - x) / x)

    var = (
        w * (1 - x) ** 2
        + d * (0.5 - x) ** 2
        + l * x ** 2
    ) / n

    se = math.sqrt(var / n)

    x_hi = min(1 - 1e-6, x + 1.96 * se)
    x_lo = max(1e-6, x - 1.96 * se)

    elo_hi = -400 * math.log10((1 - x_hi) / x_hi)
    elo_lo = -400 * math.log10((1 - x_lo) / x_lo)

    return elo, max(abs(elo_hi - elo), abs(elo - elo_lo))


def worker(tally, jobs, a_spec, b_spec, tc):
    a = Engine(a_spec)
    b = Engine(b_spec)

    try:
        while True:
            try:
                entry = jobs.get_nowait()
            except queue.Empty:
                break

            fen, om = opening_for(entry)

            ra = play_game(a, b, fen, om, tc)  # A white, B black
            rb = play_game(b, a, fen, om, tc)  # B white, A black

            tally.record_pair(ra, rb)
    finally:
        a.quit()
        b.quit()


def parse_tc(s):
    if s.startswith("mt="):
        return 0, 0, int(float(s[3:]) * 1000)

    base, inc = (s.split("+") + ["0"])[:2]
    return int(float(base) * 1000), int(float(inc) * 1000), None


def normalise_net_arg(value):
    if value is None:
        return None

    if value == "":
        return NO_NET_PATH

    lowered = value.lower()

    if lowered in ("none", "hce", "classical", "no_net", "no-net"):
        return NO_NET_PATH

    return value


def main():
    ap = argparse.ArgumentParser(
        description="Head-to-head match between two UCI engines."
    )

    ap.add_argument("engine_a", nargs="?", default=ENGINE_A)
    ap.add_argument("engine_b", nargs="?", default=ENGINE_B)

    ap.add_argument("--engine-a-net", default=ENGINE_A_NET)
    ap.add_argument("--engine-b-net", default=ENGINE_B_NET)

    ap.add_argument("--games", type=int, default=GAMES)
    ap.add_argument(
        "--tc",
        default=TC,
        help="base+inc seconds, e.g. 8+0.08, or mt=0.1 for fixed time/move",
    )
    ap.add_argument("--book", default=BOOK)
    ap.add_argument("--concurrency", type=int, default=CONCURRENCY)

    args = ap.parse_args()

    a_net = normalise_net_arg(args.engine_a_net)
    b_net = normalise_net_arg(args.engine_b_net)

    a_spec = EngineSpec(args.engine_a, a_net, "A")
    b_spec = EngineSpec(args.engine_b, b_net, "B")

    tc = parse_tc(args.tc)
    book = load_book(args.book)
    n_pairs = max(1, args.games // 2)

    jobs = queue.Queue()

    for i in range(n_pairs):
        jobs.put(book[i % len(book)])

    tcdesc = (
        f"{tc[2] / 1000:g}s/move"
        if tc[2] is not None
        else f"{tc[0] / 1000:g}+{tc[1] / 1000:g}s"
    )

    print(f"match:")
    print(f"  A exe: {a_spec.path}")
    print(f"  A net: {a_spec.net_path if a_spec.net_path != NO_NET_PATH else 'HCE fallback'}")
    print(f"  B exe: {b_spec.path}")
    print(f"  B net: {b_spec.net_path if b_spec.net_path != NO_NET_PATH else 'HCE fallback'}")
    print(
        f"TC={tcdesc}  book={args.book or 'startpos'}  "
        f"games={n_pairs * 2}  concurrency={args.concurrency}\n"
    )

    tally = Tally(name_a="A")
    threads = [
        threading.Thread(
            target=worker,
            args=(tally, jobs, a_spec, b_spec, tc),
        )
        for _ in range(args.concurrency)
    ]

    t0 = time.time()

    for t in threads:
        t.start()

    for t in threads:
        t.join()

    n = tally.w + tally.d + tally.l
    elo, ci = elo_with_ci(tally.w, tally.d, tally.l)
    pct = 100.0 * (tally.w + 0.5 * tally.d) / n if n else 0

    print(f"\nfinal ({n} games, A's perspective):")
    print(
        f"  A: +{tally.w} ={tally.d} -{tally.l}   "
        f"{pct:.1f}%   Elo {elo:+.0f} +/- {ci:.0f}   "
        f"({time.time() - t0:.0f}s)"
    )

    if elo > 0:
        print(f"  => A ({args.engine_a}) is stronger")
    elif elo < 0:
        print(f"  => B ({args.engine_b}) is stronger")
    else:
        print("  => dead even")


if __name__ == "__main__":
    main()