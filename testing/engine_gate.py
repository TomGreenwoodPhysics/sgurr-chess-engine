"""Admission gate for calibration pool engines.

Three things a UCI handshake does not prove, each of which silently corrupts a
rating rather than failing loudly:

1. The engine emits UCI-legal promotion moves. The spec requires a lowercase
   promotion piece (a7a8q). fastchess enforces it; Jet 1.2 and Simbelmyne
   1.10.0 emit "a7a8Q" and therefore forfeit every game in which they promote.
   That was 23.9% and 17.6% of their games on 2026-08-09, and it inflated the
   engine under test while looking like a normal result.

2. The engine actually reads `position fen`. StockNemo 5.7.0.0 replied "e1g1"
   to three different endgames, none of which has a king on e1. Checking only
   the move FORMAT passes that; checking legality in the position catches it.

3. The engine returns a move at all under clock-based `go`, which is what a
   gauntlet sends.

Usage:  python engine_gate.py <engine.exe> [more.exe ...]
Exit 0 only if every engine passes every case.
"""
import re
import subprocess
import sys
import threading

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chesslite as cl  # noqa: E402

CASES = [
    ("8/P7/8/8/8/8/8/K6k w - - 0 1", "white promotes"),
    ("8/1P6/8/8/8/8/8/K5k1 w - - 0 1", "white promotes, kings apart"),
    ("6K1/8/8/8/8/8/1p6/k7 b - - 0 1", "black promotes"),
    ("r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4", "normal middlegame"),
]
FORMAT = re.compile(r"^[a-h][1-8][a-h][1-8][qrbn]?$")


def bestmove(path, fen, timeout=25):
    # Absolute: a relative forward-slash path does not resolve through
    # CreateProcess on Windows, and the failure is a bare FileNotFoundError
    # that reads like a missing engine rather than a path problem.
    path = os.path.abspath(path)
    p = subprocess.Popen([path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True, bufsize=1)
    got = {}

    def read():
        for line in p.stdout:
            if line.startswith("bestmove"):
                parts = line.split()
                got["mv"] = parts[1] if len(parts) > 1 else ""
                return

    t = threading.Thread(target=read, daemon=True)
    t.start()
    try:
        p.stdin.write("uci\nisready\nucinewgame\nisready\n")
        p.stdin.write(f"position fen {fen}\n")
        p.stdin.write("go wtime 8000 btime 8000 winc 100 binc 100\n")
        p.stdin.flush()
        t.join(timeout)
        p.stdin.write("quit\n")
        p.stdin.flush()
    except (BrokenPipeError, OSError):
        pass
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        p.kill()
    return got.get("mv", "")


def check(path):
    problems = []
    for fen, label in CASES:
        mv = bestmove(path, fen)
        if not mv:
            problems.append(f"{label}: no bestmove")
            continue
        if not FORMAT.match(mv):
            problems.append(f"{label}: '{mv}' is not UCI format (uppercase promotion?)")
            continue
        legal = {cl.move_to_uci(m) for m in cl.legal_moves(cl.Position.from_fen(fen))}
        if mv not in legal:
            problems.append(f"{label}: '{mv}' is not legal here (ignoring the FEN?)")
    return problems


failed = 0
for path in sys.argv[1:]:
    name = path.replace("\\", "/").split("/")[-1]
    problems = check(path)
    if problems:
        failed = 1
        print(f"  FAIL {name}")
        for p in problems:
            print(f"         {p}")
    else:
        print(f"  OK   {name}")

sys.exit(failed)
