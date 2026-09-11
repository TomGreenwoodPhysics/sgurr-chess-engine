"""Fixed-size paired matches, resumable at complete ten-opening batches."""
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import chess.pgn

from common import ROOT, HERE, atomic_json, read_json, sha256, require_idle, busy_processes, idle_load_sample, terminate_owned
from verification import gate


def audit_pgn(path, expected_games, candidate_name="TeacherPilot", baseline_name="Gen8"):
    counts = Counter()
    terminations = Counter()
    games = []
    with Path(path).open(encoding="utf-8") as f:
        while game := chess.pgn.read_game(f):
            if game.errors:
                raise RuntimeError(f"PGN parse/illegal move error: {game.errors}")
            if {game.headers.get("White"), game.headers.get("Black")} != {candidate_name, baseline_name}:
                raise RuntimeError("Unexpected PGN engine names")
            outcome = game.headers.get("Result")
            if outcome not in ("1-0", "0-1", "1/2-1/2"):
                raise RuntimeError("Incomplete PGN result")
            termination = game.headers.get("Termination", "unspecified")
            if re.search(r"illegal|forfeit|stall|disconnect|abandon|crash|time", termination, re.I):
                raise RuntimeError(f"Abnormal PGN termination: {termination}")
            terminations[termination] += 1
            candidate_white = game.headers["White"] == candidate_name
            score = .5 if outcome == "1/2-1/2" else float((outcome == "1-0") == candidate_white)
            counts["draw" if outcome == "1/2-1/2" else "win" if (outcome == "1-0") == candidate_white else "loss"] += 1
            games.append((game.headers.get("Round"), game.headers.get("FEN"), candidate_white, score))
    if len(games) != expected_games:
        raise RuntimeError(f"Expected {expected_games} games; found {len(games)}")
    # Pair openings by FEN: each selected position must occur in both colours.
    openings = {}
    pair_scores = {}
    for _, fen, white, score in games:
        if not fen:
            raise RuntimeError("Opening FEN missing in PGN")
        openings.setdefault(fen, Counter())[white] += 1
        pair_scores.setdefault(fen, []).append(score)
    if any(c[True] != c[False] for c in openings.values()):
        raise RuntimeError("Opening colours were not reversed in pairs")
    result = {"games": len(games), "wdl": dict(counts), "terminations": dict(terminations), "pgn_sha256": sha256(path)}
    if all(len(scores) == 2 for scores in pair_scores.values()):
        result["pair_scores"] = [sum(scores) / 2 for scores in pair_scores.values()]
    return result


def paired_estimate(scores):
    """Approximate 95% match interval, with opening pairs as sampling units.

    This excludes training-seed uncertainty and is not an SPRT decision.
    """
    n = len(scores)
    if n < 2:
        raise ValueError("Need at least two opening pairs")
    mean = sum(scores) / n
    se = math.sqrt(sum((x - mean) ** 2 for x in scores) / (n * (n - 1)))
    elo = lambda p: 400 * math.log10(p / (1 - p)) if 0 < p < 1 else None
    lo, hi = max(0, mean - 1.96 * se), min(1, mean + 1.96 * se)
    return {"opening_pairs": n, "score_fraction": mean, "elo": elo(mean),
            "score_95": [lo, hi], "elo_95": [elo(lo), elo(hi)],
            "method": "Normal approximation over independent colour-reversed opening pairs; excludes training-seed variance"}


def audit_log(text):
    bad = []
    for line in text.splitlines():
        warning = "Warning;" in line
        benign = warning and ("PV" in line or "pv" in line) and ("threefold" in line.lower() or "fifty" in line.lower() or "50-move" in line.lower())
        if (warning and not benign) or re.search(r"illegal move|disconnect|stall|forfeit|crashed|failed to start|does not respond", line, re.I):
            bad.append(line)
    if bad:
        raise RuntimeError("Match log contains abnormal termination/warning: " + bad[0])


def launch(w, opponent=None):
    require_idle()
    if not w.net.exists():
        raise RuntimeError("No trained pilot exists; fixture matches are prohibited")
    verified = read_json(w.run / "verification.json")
    if verified["network_sha256"] != sha256(w.net):
        raise RuntimeError("Verified pilot changed")
    exe = w.run / "build/external.exe"
    build = read_json(w.run / "build/build.json")
    if sha256(exe) != build["binary_sha256"]["external.exe"]:
        raise RuntimeError("Verified engine changed")
    base = ROOT / "nets/gen8.nnue"
    from workflow import GEN8_SHA
    if sha256(base) != GEN8_SHA:
        raise RuntimeError("Canonical Gen8 differs")
    baseline_sha = GEN8_SHA
    candidate_name, baseline_name = "TeacherPilot", "Gen8"
    match_root = w.run
    if opponent is not None:
        baseline_name = opponent["name"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", baseline_name):
            raise ValueError("Invalid opponent name")
        candidate_name = "Sgurr-X-Candidate"
        if baseline_name == candidate_name:
            raise ValueError("Opponent and candidate names must differ")
        base = ROOT / opponent["net"]
        baseline_sha = opponent["sha256"]
        if sha256(base) != baseline_sha:
            raise RuntimeError("Pinned opponent network changed")
        match_root = w.run / ("vs-" + baseline_name)
        match_root.mkdir(exist_ok=True)
        from verification import invoke
        check = invoke(w.run / "build/selfcheck.exe", [base])
        if check["returncode"] or "-> PASS" not in check["stdout"]:
            raise RuntimeError("Opponent NNUE selfcheck failed")
    for net in (base, w.net):
        gate(exe, net, w.config["edition"])
    cfg = w.config["match"]
    if (cfg["tc"], cfg["concurrency"], cfg["hash_mb"], cfg["threads"]) != ("8+0.08", 7, 256, 1):
        raise ValueError("Match conditions differ from established fair procedure")
    book = ROOT / cfg["book"]
    if sha256(book) != cfg["book_sha256"]:
        raise RuntimeError("Book changed")
    lines = [x.strip() for x in book.read_text().splitlines() if x.strip()]
    if len(set(lines)) != len(lines):
        raise RuntimeError("Pinned opening book contains duplicate lines")
    rank = lambda line: hashlib.sha256(f"teacher-match:{cfg['seed']}:{line}".encode()).digest()
    chosen = sorted(lines, key=rank)[:cfg["pairs"]]
    if len(chosen) != cfg["pairs"]:
        raise ValueError("Not enough opening positions")
    fastchess = ROOT / "benchmarks/tools/fastchess.exe"
    identity = {"config": cfg, "engine_sha256": sha256(exe), "candidate_sha256": sha256(w.net),
                "baseline_sha256": baseline_sha, "fastchess_sha256": sha256(fastchess),
                "launcher_sha256": sha256(HERE / "launch_engine.py"), "same_binary": str(exe)}
    if opponent is not None:
        identity["opponent"] = opponent
        identity["harness_sha256"] = sha256(Path(__file__))
    all_results = []
    for batch_id, offset in enumerate(range(0, len(chosen), 10)):
        folder = match_root / f"match-{batch_id:03d}"
        folder.mkdir(exist_ok=True)
        binding = folder / "inputs.json"
        if binding.exists() and read_json(binding) != identity:
            raise RuntimeError("Match inputs changed; use a new run ID")
        atomic_json(binding, identity)
        if (folder / "result.json").exists():
            result = read_json(folder / "result.json")
            if sha256(Path(result["pgn"])) != result["pgn_sha256"]:
                raise RuntimeError("Completed match PGN changed")
            all_results.append(result)
            continue
        require_idle()
        idle_load = idle_load_sample()
        # Preserve incomplete attempts; replay the entire batch so pairs stay
        # balanced. Never add selectively completed games to the final score.
        number = len(list(folder.glob("attempt-*"))) + 1
        attempt = folder / f"attempt-{number:03d}"
        attempt.mkdir()
        batch = chosen[offset:offset + 10]
        opening_file = attempt / "openings.epd"
        opening_file.write_text("\n".join(batch) + "\n")
        pgn = attempt / "games.pgn"
        cmd = [str(fastchess)]
        for net, name in ((w.net, candidate_name), (base, baseline_name)):
            args = subprocess.list2cmdline([str(HERE / "launch_engine.py"), "--engine", str(exe), "--net", str(net), "--sha256", sha256(net)])
            cmd += ["-engine", f"cmd={sys.executable}", f"args={args}", f"name={name}"]
        cmd += ["-each", "proto=uci", f"tc={cfg['tc']}", "option.Hash=256", "option.Threads=1",
                "-rounds", str(len(batch)), "-repeat", "-concurrency", "7", "-srand", str(cfg["seed"]),
                "-openings", f"file={opening_file}", "format=epd", "order=sequential",
                "-pgnout", f"file={pgn}", "-ratinginterval", "20", "-maxmoves", "250"]
        atomic_json(attempt / "command.json", {"command": cmd, "cwd": str(attempt), "identity": identity, "pre_match_load": idle_load})
        log = attempt / "fastchess.log"
        print(subprocess.list2cmdline(cmd), flush=True)
        env = os.environ.copy(); env.pop("SGR_EVALFILE", None)
        with log.open("w", encoding="utf-8") as out:
            p = subprocess.Popen(cmd, cwd=attempt, env=env, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            atomic_json(folder / "status.json", {"pid": p.pid, "attempt": str(attempt), "state": "running"})
            try:
                while p.poll() is None:
                    time.sleep(2)
                    busy = busy_processes()
                    if any(n.lower() != "fastchess.exe" for n in busy) or sum(n.lower() == "fastchess.exe" for n in busy) > 1:
                        raise RuntimeError("Machine became busy; this incomplete batch will be replayed")
            except BaseException:
                terminate_owned(p)
                atomic_json(folder / "status.json", {"state": "interrupted", "attempt": str(attempt)})
                raise
        if p.returncode:
            raise RuntimeError(f"fastchess exited {p.returncode}; see {log}")
        audit_log(log.read_text())
        result = {**audit_pgn(pgn, 2 * len(batch), candidate_name, baseline_name), "pgn": str(pgn), "log": str(log), "identity": identity}
        atomic_json(folder / "result.json", result)
        atomic_json(folder / "status.json", {"state": "complete", "games": result["games"]})
        all_results.append(result)
    totals = Counter()
    for result in all_results:
        totals.update(result["wdl"])
    n = sum(totals.values())
    report = {"games": n, "wdl": dict(totals), "score_fraction": (totals["win"] + .5 * totals["draw"]) / n,
              "scope": "Bounded sanity match only; not a precise Elo claim or promotion", "identity": identity}
    if all("pair_scores" in result for result in all_results):
        report["estimate"] = paired_estimate([score for result in all_results for score in result["pair_scores"]])
    if opponent is not None:
        report["scope"] = "Predeclared fixed-size experiment, one training seed; no automatic promotion or SPRT claim"
    atomic_json(match_root / "match-result.json", report)
    print(json.dumps(report, indent=2), flush=True)
    return report
