"""Replay real games move by move, as in a match, and report how the search
orders and prunes. History and the TT carry over between moves, and each
search gets a fixed node budget, so the results do not depend on machine load.

    python tools/replay_stats.py base=sgurr_cpp/a.exe new=sgurr_cpp/b.exe
    python tools/replay_stats.py --set 2 --nodes 400000 \\
        new=sgurr_cpp/b.exe:HistLmrDiv=6000,HistPruneMargin=2000

Each NAME=EXE[:Option=value,...] runs in its own process, all in parallel.
Builds with -DSGR_ORDER_STATS=1 also print their ordering counters; others
report mean depth only. The games are testing/replay_games.txt, two sets of
24 from the v9.x pool calibrations. METHODOLOGY section 12 describes how this
is used."""
import argparse
import os
import subprocess
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAMES = os.path.join(ROOT, "testing", "replay_games.txt")


def load_games(which):
    games = []
    with open(GAMES) as fh:
        for line in fh:
            if not line.strip() or line.startswith("#"):
                continue
            head, _, moves = line.partition("|")
            parts = head.split()
            if which != "all" and parts[0] != which:
                continue
            games.append((int(parts[1]), " ".join(parts[2:]), moves.split()))
    return games


def replay(name, exe, opts, nodes, games, net, out):
    env = dict(os.environ, SGR_EVALFILE=net)
    p = subprocess.Popen([exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, bufsize=1, env=env,
                         cwd=os.path.dirname(exe))

    def send(line):
        p.stdin.write(line + "\n")
        p.stdin.flush()

    def read_until(prefix):
        lines = []
        while True:
            line = p.stdout.readline()
            if not line:
                raise RuntimeError(f"{name}: engine exited")
            lines.append(line.rstrip("\n"))
            if line.startswith(prefix):
                return lines

    send("uci")
    read_until("uciok")
    for key, value in opts:
        send(f"setoption name {key} value {value}")
    depths, seconds = [], 0.0
    for first, fen, moves in games:
        send("ucinewgame")
        for ply in range(first, len(moves), 2):
            send(f"position fen {fen} moves {' '.join(moves[:ply])}")
            start = time.perf_counter()
            send(f"go nodes {nodes}")
            depth = 0
            for line in read_until("bestmove"):
                parts = line.split()
                if parts[:1] == ["info"] and "depth" in parts and "nodes" in parts:
                    depth = int(parts[parts.index("depth") + 1])
            seconds += time.perf_counter() - start
            depths.append(depth)
    # A build without the counters ignores orderstats; isready ends either way.
    send("orderstats")
    send("isready")
    stats = [l for l in read_until("readyok")
             if (l.startswith("order") or l.startswith("  ")) and l != "orderstats done"]
    send("quit")
    p.wait(timeout=30)
    out[name] = (depths, seconds, stats)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("engines", nargs="+", metavar="NAME=EXE[:Opt=val,...]")
    ap.add_argument("--nodes", type=int, default=400000, help="node budget per move")
    ap.add_argument("--set", default="1", choices=["1", "2", "all"])
    ap.add_argument("--net", default=os.path.join(ROOT, "nets", "gen9_screlu_cos_s1.nnue"))
    args = ap.parse_args()

    games = load_games(args.set)
    specs = []
    for spec in args.engines:
        name, _, rest = spec.partition("=")
        exe, _, optstr = rest.partition(":")
        opts = [tuple(kv.split("=", 1)) for kv in optstr.split(",") if kv]
        specs.append((name, os.path.abspath(exe), opts))

    out = {}
    threads = [threading.Thread(target=replay, args=(n, e, o, args.nodes, games, args.net, out))
               for n, e, o in specs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    first = out[specs[0][0]][0] if specs[0][0] in out else []
    print(f"set {args.set}: {len(games)} games, {len(first)} searches of {args.nodes} nodes")
    for name, _, _ in specs:
        if name not in out:
            print(f"{name:>14}: failed")
            continue
        depths, seconds, _ = out[name]
        print(f"{name:>14}: mean depth {sum(depths) / len(depths):.3f}  time {seconds:7.1f}s")
    for name, _, _ in specs:
        if name in out and out[name][2]:
            print(f"--- {name}")
            print("\n".join(out[name][2]))


if __name__ == "__main__":
    main()
