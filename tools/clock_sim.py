"""Check the time manager against rating-list time controls without playing.

Reads how much of its budget the engine really spent on each move in a
fastchess PGN, then plays that spending through whole games under other time
controls: CCRL 40/15 and 2'+1", fast repeating controls and sudden death, each
with extra latency on every move. Also reports the worst overrun of the hard
maximum in the PGN.

    python tools/clock_sim.py runs/sprt/batch_c/sprt.pgn new
    python tools/clock_sim.py runs/sprt/batch_c/sprt.pgn new --param tm_max_clock_pct=40

allocate() copies allocate_time() in sgurr_cpp/search.cpp and must be kept in
step with it. The copy was checked against the compiled function at 19,890
points. DEVLOG, 2026-09-27, has the results."""
import argparse
import random
import re
import statistics

DEFAULTS = dict(tm_horizon_start=30, tm_horizon_drop_x100=50, tm_horizon_min=18, tm_inc_pct=50,
                tm_budget_clock_pct=20, tm_optimum_pct=85, tm_max_budget_x10=50,
                tm_max_clock_pct=30)
OVERHEAD = 30   # Move Overhead default, ms


def allocate(p, time_left, inc, movestogo, fullmove, overhead=OVERHEAD):
    to_control = movestogo is not None and movestogo > 0
    inc = max(0.0, float(inc))
    later = float(movestogo - 1) if to_control else 60.0
    clock = max(1.0, float(time_left - overhead) - max(0.0, overhead - inc) * later)
    if to_control:
        horizon = float(movestogo) + 1.0
        budget_cap = max(p["tm_budget_clock_pct"] / 100.0, 1.0 / horizon)
        max_cap = max(p["tm_max_clock_pct"] / 100.0, min(0.8, 3.0 / horizon))
    else:
        horizon = max(float(p["tm_horizon_min"]),
                      p["tm_horizon_start"] - p["tm_horizon_drop_x100"] / 100.0 * (fullmove - 1))
        budget_cap = p["tm_budget_clock_pct"] / 100.0
        max_cap = p["tm_max_clock_pct"] / 100.0
    budget = min(clock / horizon + p["tm_inc_pct"] / 100.0 * inc, budget_cap * clock)
    maximum = max(min(budget * p["tm_max_budget_x10"] / 10.0, max_cap * clock), budget)
    return budget, min(budget * p["tm_optimum_pct"] / 100.0, maximum), maximum


def spending(p, path, engine):
    """Spend/budget per move, and the worst overrun of the maximum in ms."""
    ratios, worst = [], float("-inf")
    text = open(path, encoding="utf-8", errors="replace").read()
    for game in re.split(r"\n(?=\[Event )", text):
        tags = dict(re.findall(r'^\[(\w+) "([^"]*)"\]', game, re.M))
        if engine not in (tags.get("White"), tags.get("Black")) or "TimeControl" not in tags:
            continue
        base, inc = (float(x) * 1000 for x in tags["TimeControl"].split("+"))
        side = 0 if tags["White"] == engine else 1
        body = game.split("\n\n", 1)[-1]
        clock, fullmove, colour = base, 1, 0
        for num, comment, word in re.findall(r"(\d+)\.(?:\.\.)?|\{([^}]*)\}|([^\s{}]+)", body):
            if num:
                fullmove = int(num)
            elif word:
                last, colour = (fullmove, colour), colour ^ 1
            elif comment and last[1] == side and comment.strip() != "book":
                m = re.search(r"(\d+(?:\.\d+)?)s\b", comment)
                if m:
                    t = float(m.group(1)) * 1000
                    # fastchess sends the clock with this move's increment added.
                    budget, _, maximum = allocate(p, clock + inc, inc, None, last[0])
                    ratios.append(t / budget)
                    worst = max(worst, t - maximum)
                    clock += inc - t
    return ratios, worst


def play(p, rng, ratios, base, inc, per, moves, worst_case, latency):
    clock, in_control, lowest = float(base), 0, float(base)
    for i in range(moves):
        mtg = per - in_control if per else None
        budget, _, maximum = allocate(p, clock, inc, mtg, 9 + i)
        clock -= (maximum if worst_case else min(rng.choice(ratios) * budget, maximum)) + latency
        lowest = min(lowest, clock)
        if clock <= 0:
            return True, clock
        clock += inc
        in_control += 1
        if per and in_control == per:
            clock, in_control = clock + base, 0
    return False, lowest


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pgn")
    ap.add_argument("engine", help="the engine's name in the PGN")
    ap.add_argument("--param", action="append", default=[], metavar="NAME=VALUE")
    ap.add_argument("--games", type=int, default=2000)
    args = ap.parse_args()
    p = dict(DEFAULTS)
    for kv in args.param:
        name, value = kv.split("=")
        p[name] = int(value)

    ratios, worst = spending(p, args.pgn, args.engine)
    ratios.sort()
    print(f"{len(ratios)} moves: spend/budget median {statistics.median(ratios):.2f}, "
          f"99th percentile {ratios[int(0.99 * len(ratios))]:.2f}; "
          f"worst overrun of the maximum {worst:.1f} ms")

    controls = [("CCRL 40/15", 900000, 0, 40), ("CCRL 2'+1\"", 120000, 1000, 0),
                ("40 moves in 10 s", 10000, 0, 40), ("1'+0", 60000, 0, 0), ("5'+0", 300000, 0, 0)]
    for name, base, inc, per in controls:
        for worst_case in (False, True):
            for latency in (0, 20, 50):
                rng = random.Random(1)
                flags, lows = 0, []
                for _ in range(args.games):
                    flagged, low = play(p, rng, ratios, base, inc, per, rng.randint(40, 160),
                                        worst_case, latency)
                    flags += flagged
                    lows.append(low)
                lows.sort()
                print(f"{name:<18} {'every move at max' if worst_case else 'real spending':<17} "
                      f"latency {latency:>2} ms: flags {flags:>4}/{args.games}, "
                      f"lowest clock {max(lows[0], 0) / 1000:6.2f} s, "
                      f"1st percentile {max(lows[len(lows) // 100], 0) / 1000:6.2f} s")


if __name__ == "__main__":
    main()
