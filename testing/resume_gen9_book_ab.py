#!/usr/bin/env python3
"""Recover a Gen9 book A/B run stopped by Windows Application Control.

Training artefacts are reused only after their recorded hashes and every
experiment source hash are rechecked. Blocked engine wrappers are relinked to
fresh filenames, individually handshaken, then all four engines repeat the
NNUE, UCI and legal-move gates before match play begins.
"""

from __future__ import annotations

import argparse
import json
import os
import traceback
from pathlib import Path

from run_gen9_book_ab import (
    CLANG,
    ENGINE_SOURCES,
    MATCH_SEED,
    PYTHON,
    ROOT,
    SEEDS,
    Experiment,
    atomic_json,
    now,
    set_awake,
    sha256,
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class RecoveryExperiment(Experiment):
    @staticmethod
    def parse_match(output: str, expected_games: int) -> dict[str, object]:
        benign_warnings = {
            "threefold_repetition": "Warning; PV continues after threefold repetition",
            "fifty_move_rule": "Warning; PV continues after fifty-move rule",
        }
        counts = {
            name: sum(text in line for line in output.splitlines())
            for name, text in benign_warnings.items()
        }
        filtered = "\n".join(
            line
            for line in output.splitlines()
            if not any(text in line for text in benign_warnings.values())
        )
        result = Experiment.parse_match(filtered, expected_games)
        result["benign_pv_warnings"] = counts
        return result

    def completed_match_from_disk(
        self, seed: int, holdout: Path
    ) -> dict[str, object] | None:
        """Return a fully validated completed match, or None for a partial."""
        match_dir = self.run_dir / f"match_seed{seed}"
        log = match_dir / "match.log"
        pgn = match_dir / "games.pgn"
        if not log.is_file() or not pgn.is_file():
            return None
        try:
            result = self.parse_match(
                log.read_text(encoding="utf-8", errors="replace"),
                self.rounds * 2,
            )
        except RuntimeError:
            return None
        event_count = sum(
            line.startswith("[Event ")
            for line in pgn.read_text(encoding="utf-8", errors="replace").splitlines()
        )
        if event_count != self.rounds * 2:
            return None
        result.update(
            {
                "training_seed": seed,
                "opening_seed": MATCH_SEED,
                "book_sha256": sha256(holdout),
                "log": str(log),
                "pgn": str(pgn),
                "pgn_sha256": sha256(pgn),
                "reused_after_parser_false_positive": True,
            }
        )
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--idle-grace", type=int, default=90)
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    status_path = run_dir / "status.json"
    manifest_path = run_dir / "manifest.json"
    if not status_path.is_file() or not manifest_path.is_file():
        parser.error("run directory must contain status.json and manifest.json")

    status = load_json(status_path)
    manifest = load_json(manifest_path)
    if status.get("state") != "failed":
        parser.error(f"refusing to recover run in state {status.get('state')!r}")
    if "Application Control" not in (run_dir / "logs/build_and_gate.log").read_text(
        encoding="utf-8", errors="replace"
    ):
        parser.error("recorded failure is not a Windows Application Control block")

    experiment = RecoveryExperiment(run_dir, rounds=1000, idle_grace=args.idle_grace)
    experiment.state = status
    experiment.source_snapshot = manifest["repository"]["source_sha256"]
    recovery: dict[str, object] = {
        "started_at": now(),
        "reason": "WinError 4551 blocked both new-book engine wrappers",
        "training_reused": True,
        "relink_attempts": {},
    }
    previous_recovery = run_dir / "recovery.json"
    if previous_recovery.is_file():
        recovery["previous_recovery_attempt"] = load_json(previous_recovery)

    set_awake(True)
    try:
        experiment.assert_sources_unchanged()
        training = status["training"]
        for arm in ("old", "new"):
            for seed in SEEDS:
                entry = training[arm][str(seed)]
                net = Path(entry["net"])
                if not net.is_file() or sha256(net) != entry["sha256"]:
                    raise RuntimeError(f"trained net changed or missing: {net}")

        holdout = Path(manifest["holdout"]["path"])
        if not holdout.is_file() or sha256(holdout) != manifest["holdout"]["sha256"]:
            raise RuntimeError("training-disjoint UHO holdout changed or is missing")

        atomic_json(
            ROOT / "runs/gen9_book_ab/active.json",
            {"run_dir": str(run_dir), "pid": os.getpid(), "resumed_at": now()},
        )
        experiment.update(
            pid=os.getpid(),
            state="waiting_for_idle",
            stage="application_control_recovery",
            resumed_at=now(),
            error=None,
        )
        experiment.wait_for_idle("application_control_recovery")

        engine_dir = run_dir / "engines"
        selfcheck = engine_dir / "nnue_selfcheck.exe"
        if not selfcheck.is_file():
            raise RuntimeError("the previously passing NNUE self-check binary is missing")
        recovery_log = run_dir / "logs/application_control_recovery.log"
        builds: dict[str, dict[str, object]] = {}

        recorded_builds = status.get("builds")
        if isinstance(recorded_builds, dict):
            expected_keys = {
                f"{arm}_seed{seed}" for seed in SEEDS for arm in ("old", "new")
            }
            if set(recorded_builds) != expected_keys:
                raise RuntimeError("recorded recovery build set is incomplete")
            for key, entry in recorded_builds.items():
                engine = Path(entry["engine"])
                net = Path(entry["net"])
                if not engine.is_file() or sha256(engine) != entry["engine_sha256"]:
                    raise RuntimeError(f"recorded engine changed or is missing: {engine}")
                if not net.is_file() or sha256(net) != entry["net_sha256"]:
                    raise RuntimeError(f"recorded engine net changed or is missing: {net}")
                builds[key] = dict(entry)
            recovery["engine_wrappers_reused"] = True

        for seed in SEEDS:
            old_key = f"old_seed{seed}"
            old_net = Path(training["old"][str(seed)]["net"])
            old_exe = engine_dir / f"sgr_{old_key}.exe"
            if not old_exe.is_file():
                raise RuntimeError(f"previously passing old-book engine is missing: {old_exe}")
            builds[old_key] = {
                "engine": str(old_exe),
                "engine_sha256": sha256(old_exe),
                "net": str(old_net),
                "net_sha256": sha256(old_net),
                "selfcheck": "pending repeat",
                "relinked": False,
            }

            new_key = f"new_seed{seed}"
            if new_key in builds:
                continue
            new_net = Path(training["new"][str(seed)]["net"])
            attempts: list[dict[str, object]] = []
            chosen: Path | None = None
            for attempt in range(2, 9):
                candidate = engine_dir / f"sgr_{new_key}_r{attempt}.exe"
                define = f'-DSGR_DEFAULT_NET="{new_net.as_posix()}"'
                experiment.run_logged(
                    [
                        CLANG,
                        "-std=c++20",
                        "-O3",
                        "-march=native",
                        "-DNDEBUG",
                        "-static",
                        define,
                        *ENGINE_SOURCES,
                        "-o",
                        candidate,
                    ],
                    recovery_log,
                    cwd=ROOT / "sgurr_cpp",
                    label=f"relink {new_key} attempt {attempt}",
                )
                record: dict[str, object] = {
                    "attempt": attempt,
                    "path": str(candidate),
                    "sha256": sha256(candidate),
                }
                try:
                    experiment.run_logged(
                        [PYTHON, ROOT / "testing/engine_check.py", candidate],
                        recovery_log,
                        label=f"handshake {new_key} attempt {attempt}",
                    )
                    record["handshake"] = "PASS"
                    attempts.append(record)
                    chosen = candidate
                    break
                except RuntimeError as exc:
                    record["handshake"] = "BLOCKED"
                    record["error"] = str(exc)
                    attempts.append(record)
            recovery["relink_attempts"][new_key] = attempts
            if chosen is None:
                raise RuntimeError(f"all fresh relinks were blocked for {new_key}")
            builds[new_key] = {
                "engine": str(chosen),
                "engine_sha256": sha256(chosen),
                "net": str(new_net),
                "net_sha256": sha256(new_net),
                "selfcheck": "pending repeat",
                "relinked": True,
            }

        paths: list[Path] = []
        for seed in SEEDS:
            for arm in ("old", "new"):
                key = f"{arm}_seed{seed}"
                net = Path(builds[key]["net"])
                output = experiment.run_logged(
                    [selfcheck, net],
                    recovery_log,
                    cwd=ROOT / "sgurr_cpp",
                    label=f"repeat selfcheck {key}",
                )
                if "-> PASS" not in output:
                    raise RuntimeError(f"repeat NNUE self-check failed for {key}")
                builds[key]["selfcheck"] = "PASS"
                paths.append(Path(builds[key]["engine"]))

        check = experiment.run_logged(
            [PYTHON, ROOT / "testing/engine_check.py", *paths],
            recovery_log,
            label="repeat four-engine UCI handshake gate",
        )
        gate = experiment.run_logged(
            [PYTHON, ROOT / "testing/engine_gate.py", *paths],
            recovery_log,
            label="repeat four-engine legality and FEN gate",
        )
        if check.count("OK ") < 4 or gate.count("OK") < 4:
            raise RuntimeError("recovery gates did not report four passing engines")
        experiment.assert_sources_unchanged()

        recovery["gates"] = {
            "nnue_selfcheck": "PASS x4",
            "uci_handshake": "PASS x4",
            "legality_and_fen": "PASS x4",
        }
        recovery["builds"] = builds
        recovery["gates_completed_at"] = now()
        atomic_json(run_dir / "recovery.json", recovery)
        experiment.update(
            state="running",
            stage="application_control_recovery_complete",
            builds=builds,
            recovery=str(run_dir / "recovery.json"),
        )

        discarded: list[dict[str, object]] = []
        completed: dict[int, dict[str, object]] = {}
        for seed in SEEDS:
            partial = run_dir / f"match_seed{seed}"
            if partial.exists():
                reusable = experiment.completed_match_from_disk(seed, holdout)
                if reusable is not None:
                    completed[seed] = reusable
                    continue
                destination = (
                    run_dir
                    / "discarded_partials"
                    / f"match_seed{seed}_{now().replace(':', '').replace('+', '_')}"
                )
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(partial, destination)
                discarded.append(
                    {
                        "seed": seed,
                        "path": str(destination),
                        "reason": "interrupted before completion; excluded from results",
                    }
                )
        recovery["discarded_partials"] = discarded
        recovery["reused_completed_matches"] = sorted(completed)
        atomic_json(run_dir / "recovery.json", recovery)

        matches: list[dict[str, object]] = []
        for seed in SEEDS:
            match = completed.get(seed)
            if match is None:
                match = experiment.match_seed(seed, builds, holdout)
            matches.append(match)
            experiment.update(matches=matches)

        result = experiment.summarize(matches)
        result["application_control_recovery"] = str(run_dir / "recovery.json")
        atomic_json(run_dir / "results.json", result)
        recovery["completed_at"] = now()
        recovery["matches_completed"] = True
        atomic_json(run_dir / "recovery.json", recovery)
        experiment.update(
            state="complete",
            stage="complete",
            completed_at=now(),
            result=result,
            activity=None,
            last_output=None,
        )
        return 0
    except Exception as exc:
        failure = traceback.format_exc()
        (run_dir / "recovery_failure.log").write_text(failure, encoding="utf-8")
        recovery["failed_at"] = now()
        recovery["error"] = str(exc)
        atomic_json(run_dir / "recovery.json", recovery)
        experiment.update(
            state="failed",
            stage="recovery_failed",
            failed_at=now(),
            error=str(exc),
            traceback=str(run_dir / "recovery_failure.log"),
        )
        print(failure, flush=True)
        return 1
    finally:
        set_awake(False)


if __name__ == "__main__":
    raise SystemExit(main())
