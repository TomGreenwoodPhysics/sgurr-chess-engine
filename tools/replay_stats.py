"""Replay real games move by move, as in a match, and report how the search
orders and prunes. History and the TT carry over between moves, and each
search gets a fixed node budget, so the results do not depend on machine load.

    python tools/replay_stats.py base=sgurr_cpp/a.exe new=sgurr_cpp/b.exe
    python tools/replay_stats.py --set 2 --nodes 400000 \\
        new=sgurr_cpp/b.exe:HistLmrDiv=6000,HistPruneMargin=2000

Each NAME=EXE[:Option=value,...] runs in its own process, all in parallel.
Builds with -DSGR_ORDER_STATS=1 also print their ordering counters; others
report mean depth only. The games are testing/replay_games.txt, two sets of
24 from the v9.x pool calibrations.

To judge a change to the static eval, first record a deep search of every
position with an engine the change does not touch, then score the root evals
of stats builds against it:

    python tools/replay_stats.py --set all --nodes 4000000 --workers 6 \\
        --write-reference ref.json ref=sgurr_cpp/without.exe
    python tools/replay_stats.py --set all --reference ref.json new=sgurr_cpp/stats.exe

METHODOLOGY section 12 describes how this is used."""
import argparse
import json
import os
import statistics
import subprocess
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAMES = os.path.join(ROOT, "testing", "replay_games.txt")


def load_games(which):
    """(key, first ply searched, start FEN, moves) for each game in the set."""
    games = []
    with open(GAMES) as fh:
        lines = [l for l in fh if l.strip() and not l.startswith("#")]
    for index, line in enumerate(lines):
        head, _, moves = line.partition("|")
        parts = head.split()
        if which == "all" or parts[0] == which:
            games.append((f"{parts[0]}:{index}", int(parts[1]), " ".join(parts[2:]), moves.split()))
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
    depths, seconds, scores, roots = [], 0.0, {}, {}
    for key, first, fen, moves in games:
        send("ucinewgame")
        for ply in range(first, len(moves), 2):
            send(f"position fen {fen} moves {' '.join(moves[:ply])}")
            start = time.perf_counter()
            send(f"go nodes {nodes}")
            depth = 0
            for line in read_until("bestmove"):
                parts = line.split()
                if line.startswith("info string rooteval"):
                    roots[f"{key}:{ply}"] = (int(parts[3]), int(parts[4]))
                elif parts[:1] == ["info"] and "depth" in parts and "nodes" in parts:
                    depth = int(parts[parts.index("depth") + 1])
                    if "score" in parts:
                        i = parts.index("score")
                        scores[f"{key}:{ply}"] = int(parts[i + 2]) if parts[i + 1] == "cp" else None
            seconds += time.perf_counter() - start
            depths.append(depth)
    # A build without the counters ignores orderstats; isready ends either way.
    send("orderstats")
    send("isready")
    stats = [l for l in read_until("readyok")
             if not l.startswith(("info", "bestmove", "readyok", "orderstats done"))]
    send("quit")
    p.wait(timeout=30)
    out[name] = (depths, seconds, stats, scores, roots)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("engines", nargs="+", metavar="NAME=EXE[:Opt=val,...]")
    ap.add_argument("--nodes", type=int, default=400000, help="node budget per move")
    ap.add_argument("--set", default="1", choices=["1", "2", "all"])
    ap.add_argument("--net", default=os.path.join(ROOT, "nets", "gen9_screlu_cos_s1.nnue"))
    ap.add_argument("--workers", type=int, default=1,
                    help="split the games over this many processes (one engine only)")
    ap.add_argument("--write-reference", metavar="FILE", help="save each position's search score")
    ap.add_argument("--reference", metavar="FILE", help="score root evals against saved scores")
    args = ap.parse_args()

    games = load_games(args.set)
    specs = []
    for spec in args.engines:
        name, _, rest = spec.partition("=")
        exe, _, optstr = rest.partition(":")
        opts = [tuple(kv.split("=", 1)) for kv in optstr.split(",") if kv]
        specs.append((name, os.path.abspath(exe), opts))
    if args.workers > 1:
        if len(specs) != 1:
            ap.error("--workers takes one engine")
        name, exe, opts = specs[0]
        specs = [(f"{name}/{i}", exe, opts) for i in range(args.workers)]
        slices = [games[i::args.workers] for i in range(args.workers)]
    else:
        slices = [games] * len(specs)

    out = {}
    threads = [threading.Thread(target=replay, args=(n, e, o, args.nodes, g, args.net, out))
               for (n, e, o), g in zip(specs, slices)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    if args.write_reference:
        scores = {}
        for result in out.values():
            scores.update(result[3])
        json.dump(scores, open(args.write_reference, "w"))
        print(f"{len(scores)} reference scores written to {args.write_reference}")
        return

    reference = json.load(open(args.reference)) if args.reference else None
    first = out[specs[0][0]][0] if specs[0][0] in out else []
    print(f"set {args.set}: {len(games)} games, {len(first)} searches of {args.nodes} nodes")
    for name, _, _ in specs:
        if name not in out:
            print(f"{name:>14}: failed")
            continue
        depths, seconds, _, _, roots = out[name]
        line = f"{name:>14}: mean depth {sum(depths) / len(depths):.3f}  time {seconds:7.1f}s"
        if reference is not None:
            raw_errors, corrected_errors = [], []
            for key, (raw, corrected) in roots.items():
                target = reference.get(key)
                if target is not None and abs(target) <= 2000:
                    raw_errors.append(abs(raw - target))
                    corrected_errors.append(abs(corrected - target))
            if raw_errors:
                line += (f"  root eval against the reference: raw {statistics.mean(raw_errors):.1f},"
                         f" corrected {statistics.mean(corrected_errors):.1f}"
                         f" over {len(raw_errors)} positions")
        print(line)
    for name, _, _ in specs:
        if name in out and out[name][2]:
            print(f"--- {name}")
            print("\n".join(out[name][2]))


if __name__ == "__main__":
    main()
