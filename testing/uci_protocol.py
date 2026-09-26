"""Check that an engine binary follows the UCI protocol a GUI relies on.

    python testing/uci_protocol.py ENGINE [--net NET | --embedded] [--public]

Runs single searches only, never games, in under a minute. It checks:
stop, isready and quit while searching; go infinite, which may only report
once stopped; end of input; clock, movetime and movestogo searches; malformed
input; and positions with a forced mate or no legal move. --net loads a network
file through SGR_EVALFILE, --embedded requires the network compiled into the
binary, and --public requires the short option list of a release build.
Exits 1 if any check fails.
"""
import argparse
import os
import queue
import subprocess
import sys
import threading
import time

MATE_IN_ONE = "position fen 6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1"
NO_LEGAL_MOVE = "position fen 7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"
PUBLIC_OPTIONS = {"Hash", "Clear Hash", "Move Overhead", "Threads"}
PROMPT = 0.5   # seconds allowed for an answer that should be immediate


class Engine:
    def __init__(self, exe, net):
        env = dict(os.environ)
        env.pop("SGR_EVALFILE", None)
        if net:
            env["SGR_EVALFILE"] = net
        # Start from another directory, as a GUI may.
        self.p = subprocess.Popen([exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, bufsize=1, env=env,
                                  cwd=os.path.dirname(os.path.dirname(exe)) or None)
        self.lines = queue.Queue()
        self.stderr = []
        self.t0 = time.perf_counter()
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read(self):
        for line in self.p.stdout:
            self.lines.put((self.now(), line.rstrip("\n")))
        self.lines.put((self.now(), None))

    def _read_stderr(self):
        for line in self.p.stderr:
            self.stderr.append(line.rstrip("\n"))

    def now(self):
        return time.perf_counter() - self.t0

    def send(self, text):
        self.p.stdin.write(text + "\n")
        self.p.stdin.flush()
        return self.now()

    def read(self, seconds, until=None):
        """Lines for up to `seconds`, stopping after one that starts with `until`."""
        seen = []
        end = time.perf_counter() + seconds
        while (left := end - time.perf_counter()) > 0:
            try:
                t, line = self.lines.get(timeout=left)
            except queue.Empty:
                break
            if line is None:
                break
            seen.append((t, line))
            if until and line.startswith(until):
                return seen, (t, line)
        return seen, None

    def handshake(self):
        self.send("uci")
        return self.read(5, "uciok")

    def close(self):
        try:
            self.send("quit")
            self.p.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            self.p.kill()


class Report:
    def __init__(self):
        self.failed = []

    def check(self, name, ok, detail=""):
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
        if not ok:
            self.failed.append(name)


def ms(seconds):
    return f"{seconds * 1000:.0f} ms"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("engine")
    ap.add_argument("--net", help="network file, passed through SGR_EVALFILE")
    ap.add_argument("--embedded", action="store_true", help="require the embedded network")
    ap.add_argument("--public", action="store_true", help="require the release option list")
    args = ap.parse_args()
    exe = os.path.abspath(args.engine)
    net = os.path.abspath(args.net) if args.net else None
    r = Report()

    # Identity, options and network.
    e = Engine(exe, net)
    seen, hit = e.handshake()
    lines = [line for _, line in seen]
    r.check("uci answers uciok", hit is not None)
    name = next((line for line in lines if line.startswith("id name ")), "")
    r.check("id name", name.startswith("id name Sgurr "), name or "missing")
    r.check("id author", "id author Tom Greenwood" in lines)
    options = {line[len("option name "):].split(" type ")[0]
               for line in lines if line.startswith("option name ")}
    r.check("standard options", PUBLIC_OPTIONS <= options, ", ".join(sorted(PUBLIC_OPTIONS - options)))
    if args.public:
        r.check("release option list", options == PUBLIC_OPTIONS, f"{len(options)} options")
    e.send("isready")
    r.check("isready answers readyok", e.read(5, "readyok")[1] is not None)
    time.sleep(0.2)
    loaded = next((line for line in e.stderr if "nnue:" in line), "")
    r.check("network loaded", "nnue: loaded" in loaded, loaded)
    if args.embedded:
        r.check("network is embedded", "<embedded>" in loaded)
    e.close()

    # go infinite streams info, waits for stop, and answers stop at once.
    e = Engine(exe, net)
    e.handshake()
    e.send("position startpos")
    e.send("go infinite")
    seen, _ = e.read(1.5)
    infos = [t for t, line in seen if line.startswith("info depth")]
    r.check("infinite: no bestmove before stop", not any(l.startswith("bestmove") for _, l in seen))
    r.check("infinite: info lines stream as the search runs",
            len(infos) >= 3 and infos[-1] - infos[0] > 0.2,
            f"{len(infos)} lines over {infos[-1] - infos[0]:.2f} s" if infos else "none")
    t = e.send("stop")
    _, hit = e.read(3, "bestmove")
    r.check("infinite: stop answered", hit is not None and hit[0] - t < PROMPT,
            ms(hit[0] - t) if hit else "no bestmove")
    e.close()

    # isready during a search is answered without stopping it.
    e = Engine(exe, net)
    e.handshake()
    e.send("position startpos")
    e.send("go infinite")
    e.read(0.5)
    t = e.send("isready")
    seen, hit = e.read(3, "readyok")
    r.check("isready while searching answered", hit is not None and hit[0] - t < PROMPT,
            ms(hit[0] - t) if hit else "no readyok")
    after, _ = e.read(0.8)
    r.check("the search went on",
            not any(l.startswith("bestmove") for _, l in seen + after)
            and any(l.startswith("info depth") for _, l in after))
    e.send("stop")
    r.check("stop after isready", e.read(3, "bestmove")[1] is not None)
    e.close()

    # An infinite search that ends early still waits for stop.
    e = Engine(exe, net)
    e.handshake()
    e.send(MATE_IN_ONE)
    e.send("go infinite")
    seen, _ = e.read(1.5)
    r.check("infinite with a forced mate still waits", not any(l.startswith("bestmove") for _, l in seen))
    e.send("stop")
    _, hit = e.read(3, "bestmove")
    r.check("mate found", hit is not None and hit[1] == "bestmove d1d8", hit[1] if hit else "none")
    e.close()

    # quit and a closed input end a search and the process.
    for how in ("quit", "end of input"):
        e = Engine(exe, net)
        e.handshake()
        e.send("position startpos")
        e.send("go infinite")
        e.read(0.4)
        t = time.perf_counter()
        if how == "quit":
            e.send("quit")
        else:
            e.p.stdin.close()
        try:
            e.p.wait(timeout=3)
            r.check(f"{how} while searching exits", time.perf_counter() - t < 2 * PROMPT,
                    ms(time.perf_counter() - t))
        except subprocess.TimeoutExpired:
            r.check(f"{how} while searching exits", False, "still running after 3 s")
            e.p.kill()

    e = Engine(exe, net)
    e.handshake()

    # A stop sent while idle does not cut the next search short.
    e.send("stop")
    e.send("isready")
    e.read(3, "readyok")
    e.send("position startpos")
    e.send("go depth 9")
    seen, hit = e.read(30, "bestmove")
    depths = [int(line.split()[2]) for _, line in seen if line.startswith("info depth")]
    r.check("an idle stop is ignored", hit is not None and depths and max(depths) == 9,
            f"reached depth {max(depths) if depths else 0}")

    # go followed at once by stop gives a legal move quickly.
    t = e.send("go depth 60")
    e.send("stop")
    _, hit = e.read(3, "bestmove")
    r.check("go then stop at once", hit is not None and hit[0] - t < PROMPT and hit[1] != "bestmove 0000",
            f"{hit[1]} after {ms(hit[0] - t)}" if hit else "no bestmove")

    # Clock searches stay inside their time.
    e.send("ucinewgame")
    e.send("position startpos moves e2e4 e7e5")
    t = e.send("go wtime 2000 btime 2000 winc 20 binc 20")
    _, hit = e.read(3, "bestmove")
    r.check("clock search", hit is not None and hit[0] - t < 1.0, ms(hit[0] - t) if hit else "no bestmove")
    t = e.send("go movetime 300")
    _, hit = e.read(3, "bestmove")
    r.check("movetime", hit is not None and 0.25 < hit[0] - t < 0.3 + PROMPT,
            ms(hit[0] - t) if hit else "no bestmove")
    t = e.send("go wtime 30000 btime 30000 movestogo 40")
    _, hit = e.read(5, "bestmove")
    r.check("movestogo", hit is not None and hit[0] - t < 2.0, ms(hit[0] - t) if hit else "no bestmove")

    # Malformed input is survived, and options apply in order.
    e.send("go wtime abc btime 1000")
    r.check("malformed number survived", e.read(5, "bestmove")[1] is not None)
    e.send("setoption name Hash value 64")
    e.send("setoption name NoSuchOption value 3")
    e.send("isready")
    r.check("setoption then isready", e.read(5, "readyok")[1] is not None)

    # A forced mate, and a position with no legal move.
    e.send(MATE_IN_ONE)
    e.send("go depth 3")
    _, hit = e.read(5, "bestmove")
    r.check("mate in one", hit is not None and hit[1] == "bestmove d1d8", hit[1] if hit else "none")
    e.send(NO_LEGAL_MOVE)
    e.send("go depth 3")
    _, hit = e.read(5, "bestmove")
    r.check("no legal move gives bestmove 0000", hit is not None and hit[1] == "bestmove 0000",
            hit[1] if hit else "none")
    e.close()

    print("\nall checks passed" if not r.failed else f"\n{len(r.failed)} failed: {', '.join(r.failed)}")
    return 1 if r.failed else 0


if __name__ == "__main__":
    sys.exit(main())
