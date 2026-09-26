#!/usr/bin/env python3
"""SPSA tuner for Sgurr's UCI search parameters.

    python testing/spsa.py --config CONFIG.json            start, or carry on
    python testing/spsa.py --config CONFIG.json --status   where it stands

SPSA nudges every parameter at once. Each game pair plays theta+ against
theta-, where every parameter is moved up or down by its perturbation c_k at
random, and the pair's result moves every parameter a little towards whichever
side did better. One pair says almost nothing about any one parameter; tens of
thousands of small nudges find the slope.

Step sizes follow fishtest and OpenBench. Each parameter has c_end, its
perturbation at the end of the run, and all share r_end, the learning rate
there, 0.002 unless set:

    c_k = c_end * (N / k) ** gamma
    a_k = r_end * c_end**2 * ((A + N) / (A + k)) ** alpha
    theta += a_k * (wins - losses) / (c_k * delta)

k counts game pairs and N is the length of the run in pairs. A is a tenth of N.
Choose c_end so that moving a parameter by c_end costs about 2 to 5 Elo.
The previous rule moved parameters about fifty times further per game, so its
last run was a random walk (METHODOLOGY 10).

Pairs run side by side, one fastchess process each, and every pair updates
theta as soon as it finishes, so no core waits for a slow game. Each
parameter's steps are totted up as the run goes: t = sum / sqrt(sum of
squares) stays within about 2 for a parameter that only noise is moving, and
keeps growing for one with a real slope.

A run lives in runs/spsa/<name>/ and carries on from state.json when started
again. Ctrl+C stops it and discards the pairs in flight. A config looks like

    {"name": "v95_search", "engine": "sgurr_cpp/sgr_tune.exe",
     "net": "nets/gen9_screlu_cos_s1.nnue", "book": "testing/8moves_v3.pgn",
     "tc": "8+0.08", "hash": 256, "concurrency": 7, "pairs": 30000, "seed": 1,
     "params": [{"name": "RfpMargin", "c_end": 6},
                {"name": "NullMoveReduction", "c_end": 0.5, "start": 3}]}

where start is optional and defaults to the engine's own value.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "testing"))
from engine_check import verify_all, EngineUnusable   # noqa: E402

STATE_VERSION = 2
OPTION_RE = re.compile(
    r"^option name (?P<name>.+?) type spin default (?P<default>-?\d+) "
    r"min (?P<min>-?\d+) max (?P<max>-?\d+)\s*$"
)
RESULT_RE = re.compile(r"Games: (\d+), Wins: (\d+), Losses: (\d+), Draws: (\d+)")


def read_spin_options(exe: Path, timeout: float = 20.0) -> dict:
    """The engine's own list of spin options, so the tuner cannot drift from it."""
    proc = subprocess.run([str(exe)], input="uci\nquit\n", capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
    out = {}
    for line in (proc.stdout or "").splitlines():
        m = OPTION_RE.match(line.strip())
        if m:
            out[m["name"]] = {"default": int(m["default"]), "min": int(m["min"]),
                              "max": int(m["max"])}
    return out


def round_half_up(x: float) -> int:
    # Python's round() sends halves to even, which can give theta+ and theta-
    # the same integer when c_k is 0.5. Rounding halves up keeps them apart.
    return int(math.floor(x + 0.5))


class Param:
    def __init__(self, name: str, lo: int, hi: int, c_end: float, theta: float):
        if c_end < 0.5:
            raise SystemExit(f"spsa: {name} has c_end {c_end}; below 0.5 both sides can round "
                             f"to the same integer and the pair says nothing about it")
        self.name, self.lo, self.hi, self.c_end = name, lo, hi, float(c_end)
        self.theta = float(theta)
        self.c = 0.0   # set by Core
        self.a = 0.0

    def clamp(self, x: float) -> float:
        return max(float(self.lo), min(float(self.hi), x))

    def value(self) -> int:
        return round_half_up(self.clamp(self.theta))


class Core:
    """The update rule on its own, so a test can drive it without an engine."""

    def __init__(self, params: list, pairs: int, r_end: float = 0.002,
                 alpha: float = 0.602, gamma: float = 0.101, a_frac: float = 0.1):
        self.params, self.pairs = params, int(pairs)
        self.alpha, self.gamma = alpha, gamma
        self.A = a_frac * self.pairs
        for p in params:
            p.c = p.c_end * self.pairs ** gamma
            p.a = r_end * p.c_end ** 2 * (self.A + self.pairs) ** alpha

    def c_k(self, p: Param, k: int) -> float:
        return p.c / k ** self.gamma

    def a_k(self, p: Param, k: int) -> float:
        return p.a / (self.A + k) ** self.alpha

    def perturb(self, k: int, rng: random.Random):
        """Signs, and the integer settings for theta+ and theta-, for pair k."""
        delta, plus, minus = {}, {}, {}
        for p in self.params:
            d = rng.choice((-1, 1))
            step = self.c_k(p, k) * d
            delta[p.name] = d
            plus[p.name] = round_half_up(p.clamp(p.theta + step))
            minus[p.name] = round_half_up(p.clamp(p.theta - step))
        return delta, plus, minus

    def update(self, k: int, delta: dict, plus: dict, minus: dict, result: int) -> dict:
        """Move theta by one pair's wins minus losses for theta+. Returns the steps."""
        steps = {}
        for p in self.params:
            if plus[p.name] == minus[p.name]:
                continue   # a bound flattened the perturbation, so nothing was learnt
            step = self.a_k(p, k) * result / (self.c_k(p, k) * delta[p.name])
            p.theta = p.clamp(p.theta + step)
            steps[p.name] = step
        return steps


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"version": STATE_VERSION, "pairs_done": 0, "games": 0, "failed": 0,
                "theta": {}, "drift": {}, "history": []}
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("version") != STATE_VERSION:
        raise SystemExit(
            f"spsa: {path} was written by the old tuner, whose steps were far too large "
            f"(METHODOLOGY 10). Do not resume it: start a new run under a new name.")
    return state


def save_state(path: Path, state: dict) -> None:
    # Written whole and then swapped in, so a kill mid-write cannot corrupt it.
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def drift_t(d: dict) -> float:
    return d["sum"] / math.sqrt(d["sumsq"]) if d.get("sumsq", 0) > 0 else 0.0


class Tuner:
    """Runs pairs side by side and applies each result as it arrives.

    play_pair(plus, minus, seed, worker) returns (wins, losses, draws) for
    theta+, or None if the pair failed. It is fastchess for a real run and a
    simulation in the tests.
    """

    def __init__(self, cfg: dict, run_dir: Path, options: dict, play_pair,
                 log=print, snapshot_every: int = 100, log_every: int = 250):
        for old in ("games_per_iter", "iterations"):
            if old in cfg:
                raise SystemExit(f"spsa: '{old}' belongs to the old tuner. Give 'pairs' and "
                                 f"a c_end for each parameter instead.")
        self.cfg, self.run_dir, self.play_pair = cfg, run_dir, play_pair
        self.log_line = log
        self.snapshot_every, self.log_every = snapshot_every, log_every
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = run_dir / "state.json"
        self.state = load_state(self.state_path)

        params = []
        for entry in cfg["params"]:
            name = entry["name"]
            if "c" in entry or "a" in entry:
                raise SystemExit(f"spsa: {name} uses the old 'c'/'a' keys. Give 'c_end'.")
            if name not in options:
                raise SystemExit(f"spsa: '{name}' is not a spin option of the engine. It "
                                 f"offers: {', '.join(sorted(options))}")
            info = options[name]
            start = self.state["theta"].get(name, entry.get("start", info["default"]))
            params.append(Param(name, info["min"], info["max"], entry["c_end"], start))
        self.options = options
        self.core = Core(params, cfg["pairs"], cfg.get("r_end", 0.002),
                         cfg.get("alpha", 0.602), cfg.get("gamma", 0.101),
                         cfg.get("a_frac", 0.1))
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.next_pair = self.state["pairs_done"]   # pairs in flight at a stop are redone
        self.in_flight = 0
        self.t0 = time.time()
        self.games_at_start = self.state["games"]

    def log(self, msg: str) -> None:
        self.log_line(f"[{time.strftime('%H:%M:%S')}] {msg}")

    def _claim(self):
        with self.lock:
            if self.stop.is_set() or self.state["pairs_done"] + self.in_flight >= self.core.pairs:
                return None
            self.in_flight += 1
            self.next_pair += 1
            k = self.next_pair
            rng = random.Random(int(self.cfg.get("seed", 1)) * 1_000_003 + k)
            delta, plus, minus = self.core.perturb(k, rng)
            return k, delta, plus, minus

    def _record(self, k, delta, plus, minus, result) -> None:
        with self.lock:
            self.in_flight -= 1
            if result is None:
                self.state["failed"] += 1
                tried = self.state["failed"] + self.state["pairs_done"]
                if self.state["failed"] >= 10 and self.state["failed"] > 0.05 * tried:
                    self.log(f"stopping: {self.state['failed']} of {tried} pairs failed, "
                             f"so something is wrong with the engine or fastchess")
                    self.stop.set()
                return
            wins, losses, draws = result
            steps = self.core.update(k, delta, plus, minus, wins - losses)
            for name, step in steps.items():
                d = self.state["drift"].setdefault(name, {"sum": 0.0, "sumsq": 0.0})
                d["sum"] += step
                d["sumsq"] += step * step
            self.state["pairs_done"] += 1
            self.state["games"] += wins + losses + draws
            self.state["theta"] = {p.name: p.theta for p in self.core.params}
            done = self.state["pairs_done"]
            if done % self.snapshot_every == 0:
                self.state["history"].append(
                    {"pairs": done, "theta": {p.name: round(p.theta, 3) for p in self.core.params}})
            save_state(self.state_path, self.state)
            if done % self.log_every == 0:
                self._progress()

    def _progress(self) -> None:
        s = self.state
        hours = max(1e-9, time.time() - self.t0) / 3600
        rate = (s["games"] - self.games_at_start) / hours
        self.log(f"pairs {s['pairs_done']}/{self.core.pairs}  games {s['games']}  "
                 f"({rate:.0f}/h)  failed {s['failed']}")
        self.log("    " + "  ".join(
            f"{p.name}={p.value()} (t {drift_t(s['drift'].get(p.name, {})):+.1f})"
            for p in self.core.params))

    def _worker(self, worker: int) -> None:
        while not self.stop.is_set():
            claim = self._claim()
            if claim is None:
                return
            k, delta, plus, minus = claim
            seed = int(self.cfg.get("seed", 1)) * 1_000_003 + k
            try:
                result = self.play_pair(plus, minus, seed, worker)
            except Exception as exc:   # one bad pair must not end the run
                self.log(f"  worker {worker}: pair {k} failed: {exc}")
                result = None
            if self.stop.is_set():
                return   # stopped mid-pair: the result may be cut short
            self._record(k, delta, plus, minus, result)

    def run(self, concurrency: int) -> None:
        self.log(f"SPSA {self.cfg['name']}: {len(self.core.params)} parameters, "
                 f"{self.core.pairs} pairs, {concurrency} at a time, "
                 f"from pair {self.state['pairs_done']}")
        threads = [threading.Thread(target=self._worker, args=(i,), daemon=True)
                   for i in range(concurrency)]
        for t in threads:
            t.start()
        try:
            while any(t.is_alive() for t in threads):
                for t in threads:
                    t.join(timeout=0.5)
        except KeyboardInterrupt:
            self.stop.set()
            self.log("stopping: pairs in flight are discarded")
            raise
        finally:
            with self.lock:
                save_state(self.state_path, self.state)
        if self.state["pairs_done"] >= self.core.pairs:
            self.report()

    def rows(self):
        for p in self.core.params:
            default = self.options[p.name]["default"]
            t = drift_t(self.state["drift"].get(p.name, {}))
            yield p.name, default, p.value(), t

    def report(self) -> None:
        self.log(f"SPSA {self.cfg['name']} finished: {self.state['pairs_done']} pairs, "
                 f"{self.state['games']} games, {self.state['failed']} failed")
        self.log(f"{'parameter':<24}{'default':>9}{'tuned':>9}{'change':>9}{'t':>7}")
        for name, default, tuned, t in self.rows():
            self.log(f"{name:<24}{default:>9}{tuned:>9}{tuned - default:>+9}{t:>7.1f}")
        self.log("Only an SPRT decides. Compile the tuned values in as defaults and test "
                 "that build against the base with tools/sprt.sh.")
        (self.run_dir / "tuned.json").write_text(
            json.dumps({name: tuned for name, _, tuned, _ in self.rows()}, indent=1),
            encoding="utf-8")


def uci_options(theta: dict) -> list:
    return [f"option.{name}={value}" for name, value in theta.items()]


class Fastchess:
    """Plays one pair, theta+ against theta-, in its own fastchess process."""

    def __init__(self, cfg: dict, exe: Path, run_dir: Path):
        self.cfg, self.exe, self.run_dir = cfg, exe, run_dir
        self.fastchess = ROOT / "benchmarks" / "tools" / "fastchess.exe"
        self.book = (ROOT / cfg.get("book", "testing/8moves_v3.pgn")).resolve()
        self.book_format = cfg.get("book_format",
                                   "pgn" if self.book.suffix.lower() == ".pgn" else "epd")
        self.procs = {}
        self.procs_lock = threading.Lock()

    def __call__(self, plus: dict, minus: dict, seed: int, worker: int):
        wdir = self.run_dir / f"w{worker}"   # fastchess saves state in its working directory
        wdir.mkdir(exist_ok=True)
        each = [f"tc={self.cfg.get('tc', '8+0.08')}"]
        if self.cfg.get("hash") is not None:
            each.append(f"option.Hash={int(self.cfg['hash'])}")
        cmd = [str(self.fastchess),
               "-engine", f"cmd={self.exe}", "name=plus", *uci_options(plus),
               "-engine", f"cmd={self.exe}", "name=minus", *uci_options(minus),
               "-each", *each, "-rounds", "1", "-repeat", "-concurrency", "1",
               "-srand", str(seed),
               "-openings", f"file={self.book}", f"format={self.book_format}", "order=random",
               "-recover", "-pgnout", f"file={self.run_dir / f'games-w{worker}.pgn'}"]
        proc = subprocess.Popen(cmd, cwd=wdir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace")
        with self.procs_lock:
            self.procs[worker] = proc
        try:
            out, _ = proc.communicate(timeout=float(self.cfg.get("pair_timeout", 600)))
        except subprocess.TimeoutExpired:
            self.kill(proc)
            return None
        finally:
            with self.procs_lock:
                self.procs.pop(worker, None)
        found = RESULT_RE.findall(out or "")
        if not found:
            return None
        games, wins, losses, draws = (int(x) for x in found[-1])
        return (wins, losses, draws) if games == 2 else None

    @staticmethod
    def kill(proc) -> None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        else:
            proc.kill()

    def kill_all(self) -> None:
        with self.procs_lock:
            for proc in list(self.procs.values()):
                self.kill(proc)


def busy() -> bool:
    if os.name != "nt":
        return False
    out = subprocess.run(["tasklist"], capture_output=True, text=True).stdout.lower()
    return "fastchess.exe" in out or "datagen.exe" in out


def main() -> int:
    ap = argparse.ArgumentParser(description="SPSA tuner for Sgurr's UCI parameters")
    ap.add_argument("--config", required=True)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--force", action="store_true", help="start even if fastchess is running")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if cfg.get("net"):
        os.environ["SGR_EVALFILE"] = str((ROOT / cfg["net"]).resolve())
    exe = (ROOT / cfg["engine"]).resolve()
    run_dir = ROOT / "runs" / "spsa" / cfg["name"]
    log_path = run_dir / "spsa.log"

    def log(line: str) -> None:
        print(line, flush=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    options = read_spin_options(exe)
    run_dir.mkdir(parents=True, exist_ok=True)
    player = Fastchess(cfg, exe, run_dir)
    tuner = Tuner(cfg, run_dir, options, player, log=log)

    if args.status:
        s = tuner.state
        print(f"SPSA {cfg['name']}: {s['pairs_done']}/{cfg['pairs']} pairs, {s['games']} games, "
              f"{s['failed']} failed")
        print(f"  {'parameter':<24}{'default':>9}{'current':>9}{'t':>7}")
        for name, default, current, t in tuner.rows():
            print(f"  {name:<24}{default:>9}{current:>9}{t:>7.1f}")
        pgns = sorted(run_dir.glob("games-w*.pgn"))
        if pgns:
            out = subprocess.run([sys.executable, str(ROOT / "testing" / "pgn_endings.py"),
                                  *map(str, pgns)], capture_output=True, text=True).stdout
            total, bad = (out.splitlines() or ["0 0"])[0].split()[:2]
            print(f"  endings: {total} games, {bad} abnormal")
        return 0

    if busy() and not args.force:
        raise SystemExit("spsa: fastchess or datagen is already running (--force to start anyway)")
    try:
        verify_all([exe])
    except EngineUnusable as exc:
        raise SystemExit(f"spsa: engine pre-flight failed:\n{exc}")
    try:
        tuner.run(int(cfg.get("concurrency", 7)))
    except KeyboardInterrupt:
        player.kill_all()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
