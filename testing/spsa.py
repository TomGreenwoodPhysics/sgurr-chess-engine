#!/usr/bin/env python3
"""SPSA tuner for Sgurr's UCI search parameters.

Why this exists
---------------
Every margin, divisor and threshold in the search was hand-set, and three
separate comments in search.hpp admitted they had never been swept. v8.2
exposed 47 of them as UCI options, which made tuning possible for the first
time -- but fastchess has no SPSA of its own, so the loop has to live here.

It matters more than "some free Elo". The v9.0 batch measured -1.0 +/-21.1
against v8.1 despite adding ten standard techniques, and three of those ten
carry parameters chosen by *reasoning* rather than by games, because sweeping
them returned non-monotonic noise (HistLmrDiv, the history-prune margin, the
capture-history clamp). A package of good ideas at guessed settings landing on
zero is exactly what a tuner is for.

How SPSA works, briefly
-----------------------
Gradient descent needs one measurement per parameter per step, which is
hopeless when a "measurement" is a few hundred games. SPSA perturbs EVERY
parameter at once by a random +/-1 pattern, plays theta+ against theta-, and
uses that single result to estimate the gradient for all of them:

    ghat_i = (score_of_plus - 0.5) / (c_k * delta_i)
    theta_i += a_k * ghat_i

Each iteration costs one small match regardless of how many parameters are
being tuned. The noise is enormous per step and averages out over thousands of
them.

Usage
-----
    python testing/spsa.py --config testing/spsa_v90.json
    python testing/spsa.py --config testing/spsa_v90.json --status
    python testing/spsa.py --config testing/spsa_v90.json --resume

Resumable by design, like everything else in this project: state is
checkpointed every iteration, and a run killed mid-match picks up from the last
completed one.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "testing"))
from engine_check import verify_all, EngineUnusable   # noqa: E402


# --------------------------------------------------------------------------
# engine option discovery
# --------------------------------------------------------------------------

OPTION_RE = re.compile(
    r"^option name (?P<name>.+?) type spin default (?P<default>-?\d+) "
    r"min (?P<min>-?\d+) max (?P<max>-?\d+)\s*$"
)


def read_spin_options(exe: Path, timeout: float = 20.0) -> dict:
    """Ask the engine what it exposes, rather than duplicating the list here.

    The engine is the single source of truth for names, defaults and bounds, so
    the tuner cannot drift out of sync with it -- a tuner setting an option the
    engine silently ignores would produce a beautifully converged run of pure
    noise.
    """
    proc = subprocess.run(
        [str(exe)],
        input="uci\nquit\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )

    out = {}
    for line in (proc.stdout or "").splitlines():
        m = OPTION_RE.match(line.strip())
        if m:
            out[m.group("name")] = {
                "default": int(m.group("default")),
                "min": int(m.group("min")),
                "max": int(m.group("max")),
            }
    return out


# --------------------------------------------------------------------------
# the tuner
# --------------------------------------------------------------------------

class Spsa:
    def __init__(self, cfg: dict, cfg_path: Path):
        self.cfg = cfg
        self.cfg_path = cfg_path
        self.exe = (ROOT / cfg["engine"]).resolve()
        self.book = (ROOT / cfg.get("book", "testing/book.epd")).resolve()
        self.fastchess = (ROOT / "benchmarks/tools/fastchess.exe").resolve()
        self.net = cfg.get("net")

        self.run_dir = (ROOT / "runs" / "spsa" / cfg["name"]).resolve()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.run_dir / "state.json"
        self.log_path = self.run_dir / "spsa.log"

        self.tc = cfg.get("tc", "8+0.08")
        self.concurrency = int(cfg.get("concurrency", 7))
        self.games_per_iter = int(cfg.get("games_per_iter", 8))
        self.iterations = int(cfg.get("iterations", 3000))

        # Standard SPSA decay exponents. These are the values the literature
        # settled on and there is no reason to be creative here.
        self.alpha = float(cfg.get("alpha", 0.602))
        self.gamma = float(cfg.get("gamma", 0.101))
        # A dampens the early steps so a wild first gradient cannot throw the
        # parameters across their whole range; 10% of the run is conventional.
        self.A = float(cfg.get("A", 0.1 * self.iterations))

        self.available = read_spin_options(self.exe)
        self.params = self._build_params()
        self.state = self._load_state()

    # ---- parameter setup -------------------------------------------------
    def _build_params(self) -> list:
        params = []
        for entry in self.cfg["params"]:
            name = entry["name"]
            if name not in self.available:
                raise SystemExit(
                    f"spsa: '{name}' is not a spin option on {self.exe.name}.\n"
                    f"      The engine advertises: {', '.join(sorted(self.available))}"
                )
            info = self.available[name]
            lo, hi = info["min"], info["max"]

            # c is the perturbation size. Default to a twentieth of the range,
            # which is small enough not to leave the sensible region in one step
            # and large enough to move an integer option at all -- a c below 0.5
            # rounds to no change and the parameter would sit frozen while
            # appearing to be tuned.
            c = float(entry.get("c", max(1.0, (hi - lo) / 20.0)))

            # a sets how far one gradient estimate can move the value, and it
            # has to be derived rather than guessed -- the first version of this
            # line had c cancel out of its own formula, leaving every parameter
            # frozen while the run looked healthy.
            #
            #   step = a_k * ghat = [a / (A+k)^alpha] * (s - 0.5) / c_k
            #
            # With games_per_iter games the score is granular and |s - 0.5|
            # averages around 0.15. Solving for a step of about c/5 in the early
            # iterations gives a = c^2 * (A+1)^alpha / (5 * 0.15).
            #
            # c/5 is deliberately modest: SPSA's per-step signal is almost all
            # noise, and the convergence comes from averaging thousands of them,
            # not from any one step being decisive.
            typical_signal = 0.15
            a = float(entry.get(
                "a",
                (c * c) / (5.0 * typical_signal) * (self.A + 1) ** self.alpha))

            params.append({
                "name": name,
                "min": lo,
                "max": hi,
                "c": c,
                "a": a,
                "value": float(entry.get("start", info["default"])),
            })
        return params

    # ---- persistence -----------------------------------------------------
    def _load_state(self) -> dict:
        if self.state_path.exists():
            s = json.loads(self.state_path.read_text(encoding="utf-8"))
            for p in self.params:
                if p["name"] in s.get("values", {}):
                    p["value"] = s["values"][p["name"]]
            return s
        return {"iteration": 0, "games": 0, "values": {}, "history": []}

    def _save_state(self) -> None:
        self.state["values"] = {p["name"]: p["value"] for p in self.params}
        self.state_path.write_text(json.dumps(self.state, indent=1), encoding="utf-8")

    def log(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    # ---- one match -------------------------------------------------------
    def _opts(self, theta: dict) -> list:
        return [f"option.{k}={v}" for k, v in theta.items()]

    def play(self, plus: dict, minus: dict) -> float | None:
        """theta+ against theta-. Returns theta+'s score in [0,1], or None."""
        rounds = max(1, self.games_per_iter // 2)
        cmd = [
            str(self.fastchess),
            "-engine", f"cmd={self.exe}", "name=plus", *self._opts(plus),
            "-engine", f"cmd={self.exe}", "name=minus", *self._opts(minus),
            "-each", f"tc={self.tc}",
            "-rounds", str(rounds), "-repeat",
            "-concurrency", str(self.concurrency),
            "-openings", f"file={self.book}", "format=epd", "order=random",
            "-recover",
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True,
                                 encoding="utf-8", errors="replace",
                                 timeout=self.cfg.get("match_timeout", 900))
        except subprocess.TimeoutExpired:
            self.log("  match timed out -- skipping iteration")
            return None
        finally:
            # fastchess shuts its engines down by sending `quit`; anything that
            # kills it instead orphans them mid-search. Sweep unconditionally --
            # thousands of iterations means one leaked pair per hundred would
            # eventually saturate the machine and silently invalidate every
            # timed result after it.
            self._sweep()

        out = res.stdout or ""
        m = None
        for m2 in re.finditer(
                r"Games: (\d+), Wins: (\d+), Losses: (\d+), Draws: (\d+)", out):
            m = m2
        if not m:
            self.log("  no result parsed from fastchess -- skipping iteration")
            return None

        n, w, l_, d = (int(m.group(i)) for i in range(1, 5))
        if n == 0:
            return None
        return (w + 0.5 * d) / n

    def _sweep(self) -> None:
        subprocess.run(["taskkill", "/IM", self.exe.name, "/F"],
                       capture_output=True, text=True)

    # ---- the loop --------------------------------------------------------
    def run(self) -> None:
        try:
            verify_all([self.exe])
        except EngineUnusable as exc:
            raise SystemExit(f"spsa: engine pre-flight failed:\n{exc}")

        self.log(f"SPSA {self.cfg['name']}: {len(self.params)} params, "
                 f"{self.iterations} iterations, {self.games_per_iter} games each, "
                 f"tc={self.tc}")
        self.log(f"  starting at iteration {self.state['iteration']}")

        rng = random.Random(self.cfg.get("seed", 0) + self.state["iteration"])
        t0 = time.time()

        while self.state["iteration"] < self.iterations:
            k = self.state["iteration"] + 1
            ck_scale = 1.0 / (k ** self.gamma)
            ak_scale = 1.0 / ((self.A + k) ** self.alpha)

            deltas = {p["name"]: rng.choice((-1, 1)) for p in self.params}
            plus, minus = {}, {}
            for p in self.params:
                step = p["c"] * ck_scale * deltas[p["name"]]
                plus[p["name"]] = self._clamped(p, p["value"] + step)
                minus[p["name"]] = self._clamped(p, p["value"] - step)

            score = self.play(plus, minus)
            if score is None:
                self.state["iteration"] = k
                self._save_state()
                continue

            # One match result updates every parameter at once -- the whole
            # point of SPSA. Sign only: a delta of +1 means the plus side had
            # the higher value, so a plus-side win pushes the value up.
            for p in self.params:
                ck = p["c"] * ck_scale
                if ck <= 0:
                    continue
                ghat = (score - 0.5) / (ck * deltas[p["name"]])
                p["value"] = self._clamp_float(p, p["value"] + p["a"] * ak_scale * ghat)

            self.state["iteration"] = k
            self.state["games"] += self.games_per_iter
            self.state["history"].append(
                {"k": k, "score": round(score, 4),
                 "values": {p["name"]: round(p["value"], 2) for p in self.params}})
            self.state["history"] = self.state["history"][-500:]
            self._save_state()

            if k % 25 == 0 or k == 1:
                rate = self.state["games"] / max(1e-9, time.time() - t0) * 3600
                vals = "  ".join(f"{p['name']}={self._clamped(p, p['value'])}"
                                 for p in self.params)
                self.log(f"iter {k}/{self.iterations}  games {self.state['games']}  "
                         f"({rate:.0f}/h)  last={score:.3f}")
                self.log(f"    {vals}")

        self.report()

    @staticmethod
    def _clamp_float(p: dict, v: float) -> float:
        return max(float(p["min"]), min(float(p["max"]), v))

    @staticmethod
    def _clamped(p: dict, v: float | None = None) -> int:
        v = p["value"] if v is None else v
        return int(round(max(float(p["min"]), min(float(p["max"]), v))))

    # ---- output ----------------------------------------------------------
    def report(self) -> None:
        self.log("")
        self.log("=" * 62)
        self.log(f"SPSA {self.cfg['name']} finished: "
                 f"{self.state['iteration']} iterations, {self.state['games']} games")
        self.log("=" * 62)
        self.log("")
        self.log(f"{'parameter':<24}{'default':>9}{'tuned':>9}{'change':>9}")
        moved = []
        for p in self.params:
            d = self.available[p["name"]]["default"]
            t = self._clamped(p)
            self.log(f"{p['name']:<24}{d:>9}{t:>9}{t - d:>+9}")
            if t != d:
                moved.append((p["name"], t))

        self.log("")
        self.log("VALIDATE BEFORE BELIEVING. SPSA optimises its own objective and")
        self.log("will happily converge on noise; only an SPRT decides. Run tuned")
        self.log("against default with:")
        self.log("")
        opts = " ".join(f"option.{n}={v}" for n, v in moved) or "(nothing moved)"
        self.log(f"  -engine cmd=<exe> name=tuned {opts} \\")
        self.log(f"  -engine cmd=<exe> name=default \\")
        self.log(f"  -each tc={self.tc} -rounds 3000 -repeat -concurrency {self.concurrency} \\")
        self.log(f"  -sprt elo0=0 elo1=5 alpha=0.05 beta=0.05")
        (self.run_dir / "tuned.json").write_text(
            json.dumps({n: v for n, v in moved}, indent=1), encoding="utf-8")
        self.log("")
        self.log(f"tuned values -> {self.run_dir / 'tuned.json'}")

    def status(self) -> None:
        s = self.state
        print(f"SPSA {self.cfg['name']}")
        print(f"  iteration {s['iteration']}/{self.iterations}   games {s['games']}")
        print(f"  {'parameter':<24}{'default':>9}{'current':>9}")
        for p in self.params:
            print(f"  {p['name']:<24}{self.available[p['name']]['default']:>9}"
                  f"{self._clamped(p):>9}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--resume", action="store_true",
                    help="accepted for symmetry; runs always resume from state.json")
    args = ap.parse_args()

    cfg_path = Path(args.config)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    if cfg.get("net"):
        import os
        os.environ["SGR_EVALFILE"] = str((ROOT / cfg["net"]).resolve())

    tuner = Spsa(cfg, cfg_path)
    if args.status:
        tuner.status()
        return 0
    tuner.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
