"""The SPSA tuner, tested against a simulated engine with a known optimum.

No engine or fastchess is started, so these run in milliseconds with the other
harness tests. Strength falls off quadratically around a known best setting,
three Elo for every c_end away from it, and 60% of games between equals are
drawn. The tuner has to find that setting from three c_end away, and leave a
parameter that changes nothing close to where it started. The previous step
rule failed both on this problem: its worst parameter ended 2.9 c_end from the
optimum and a do-nothing parameter drifted up to 14 (METHODOLOGY 10).
"""
import json
import math
import random
import tempfile
import threading
import unittest
from pathlib import Path

import spsa

DRAW_ELO = 400 * math.log10(4)   # 60% draws between equals

# name: (min, max, c_end, start, optimum, Elo lost one c_end from the optimum)
SPEC = {
    "Alpha": (0, 400, 10, 130, 100, 3),
    "Beta": (0, 200, 5, 35, 50, 3),
    "Gamma": (1, 10, 1, 6, 3, 3),
    "Delta": (0, 1000, 20, 190, 250, 3),
    "Noise1": (0, 100, 4, 40, 40, 0),
    "Noise2": (1, 20, 1, 7, 7, 0),
}
OPTIONS = {n: {"default": s[3], "min": s[0], "max": s[1]} for n, s in SPEC.items()}


def elo(theta):
    return -sum(cost * ((theta[n] - opt) / c_end) ** 2
                for n, (_, _, c_end, _, opt, cost) in SPEC.items())


def game(diff, rng):
    """+1, 0 or -1 for the side diff Elo stronger."""
    win = 1 / (1 + 10 ** ((-diff + DRAW_ELO) / 400))
    loss = 1 / (1 + 10 ** ((diff + DRAW_ELO) / 400))
    r = rng.random()
    return 1 if r < win else (-1 if r < win + loss else 0)


def params():
    return [spsa.Param(n, lo, hi, c_end, start) for n, (lo, hi, c_end, start, _, _) in SPEC.items()]


def config(pairs):
    return {"name": "test", "pairs": pairs, "seed": 1,
            "params": [{"name": n, "c_end": s[2]} for n, s in SPEC.items()]}


class Schedule(unittest.TestCase):
    def test_ends_at_c_end_and_r_end(self):
        ps = params()
        core = spsa.Core(ps, 20000, r_end=0.002)
        for p in ps:
            self.assertAlmostEqual(core.c_k(p, 20000), p.c_end)
            self.assertAlmostEqual(core.a_k(p, 20000) / core.c_k(p, 20000) ** 2, 0.002)

    def test_rounding_keeps_the_sides_apart(self):
        # At c_k = 0.5 Python's round() would send 2.5 and 3.5 to 2 and 4 but
        # 1.5 and 2.5 both to 2. Rounding halves up never merges the sides.
        for theta in (1.0, 2.0, 2.25, 2.5, 2.75, 3.0):
            p = spsa.Param("X", 0, 10, 0.5, theta)
            core = spsa.Core([p], 1)   # one pair, so c_k is c_end
            _, plus, minus = core.perturb(1, random.Random(0))
            self.assertNotEqual(plus["X"], minus["X"], theta)

    def test_small_c_end_is_refused(self):
        with self.assertRaises(SystemExit):
            spsa.Param("X", 0, 10, 0.4, 5)


class KnownOptimum(unittest.TestCase):
    def test_finds_the_optimum_and_leaves_noise_alone(self):
        pairs = 20000
        ps = params()
        core = spsa.Core(ps, pairs)
        rng = random.Random(1)
        for k in range(1, pairs + 1):
            delta, plus, minus = core.perturb(k, rng)
            diff = elo(plus) - elo(minus)
            core.update(k, delta, plus, minus, game(diff, rng) + game(diff, rng))

        theta = {p.name: p.theta for p in ps}
        for n, (_, _, c_end, _, opt, cost) in SPEC.items():
            error = abs(theta[n] - opt) / c_end
            limit = 0.75 if cost else 1.5   # 20 seeds: worst 0.50 and 1.06
            self.assertLess(error, limit, f"{n} ended {error:.2f} c_end from {opt}")
        self.assertLess(-elo(theta), 3.0)   # it started 108 Elo down


class Runner(unittest.TestCase):
    """The threaded runner: pairs side by side, a stop, and carrying on."""

    def simulated(self, holder, stop_after=None):
        lock = threading.Lock()
        count = [0]

        def play(plus, minus, seed, worker):
            rng = random.Random(seed)
            diff = elo(plus) - elo(minus)
            with lock:
                count[0] += 1
                if stop_after is not None and count[0] >= stop_after:
                    holder[0].stop.set()
            return (lambda r: (r.count(1), r.count(-1), r.count(0)))(
                [game(diff, rng), game(diff, rng)])
        return play

    def test_runs_stops_and_carries_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            holder = [None]
            first = spsa.Tuner(config(400), run_dir, OPTIONS, self.simulated(holder, 150),
                               log=lambda line: None)
            holder[0] = first
            first.run(concurrency=4)
            stopped_at = json.loads((run_dir / "state.json").read_text())["pairs_done"]
            self.assertLess(stopped_at, 400)
            self.assertFalse((run_dir / "tuned.json").exists())

            holder = [None]
            second = spsa.Tuner(config(400), run_dir, OPTIONS, self.simulated(holder),
                                log=lambda line: None)
            holder[0] = second
            self.assertEqual(second.state["pairs_done"], stopped_at)
            second.run(concurrency=4)

            state = json.loads((run_dir / "state.json").read_text())
            self.assertEqual(state["version"], spsa.STATE_VERSION)
            self.assertEqual(state["pairs_done"], 400)
            self.assertEqual(state["games"], 800)
            self.assertEqual(set(state["drift"]), set(SPEC))
            self.assertEqual(len(state["history"]), 4)
            self.assertEqual(set(json.loads((run_dir / "tuned.json").read_text())), set(SPEC))

    def test_failed_pairs_are_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            calls = [0]
            lock = threading.Lock()

            def flaky(plus, minus, seed, worker):
                with lock:
                    calls[0] += 1
                    fail = calls[0] % 50 == 0
                return None if fail else (1, 0, 1)
            tuner = spsa.Tuner(config(300), run_dir, OPTIONS, flaky, log=lambda line: None)
            tuner.run(concurrency=3)
            self.assertEqual(tuner.state["pairs_done"], 300)
            self.assertGreater(tuner.state["failed"], 0)

    def test_stops_when_pairs_keep_failing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tuner = spsa.Tuner(config(300), Path(tmp) / "run", OPTIONS,
                               lambda *args: None, log=lambda line: None)
            tuner.run(concurrency=3)
            self.assertEqual(tuner.state["pairs_done"], 0)
            self.assertLess(tuner.state["failed"], 20)


class OldRuns(unittest.TestCase):
    def test_old_state_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text(json.dumps({"iteration": 626, "games": 5008, "values": {}}))
            with self.assertRaises(SystemExit):
                spsa.load_state(path)

    def test_old_config_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = config(100) | {"games_per_iter": 8}
            with self.assertRaises(SystemExit):
                spsa.Tuner(old, Path(tmp) / "run", OPTIONS, None, log=lambda line: None)
            old = config(100)
            old["params"][0] = {"name": "Alpha", "c": 10}
            with self.assertRaises(SystemExit):
                spsa.Tuner(old, Path(tmp) / "run2", OPTIONS, None, log=lambda line: None)


if __name__ == "__main__":
    unittest.main()
