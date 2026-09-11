#!/usr/bin/env python3
"""Run the controlled Gen9 old-book versus new-book NNUE experiment.

This is deliberately separate from pipeline.py: it compares two matched pilot
datasets and must never promote a net or resume production datagen. It trains
two paired seeds per book, builds/gates all four engines, then runs fixed-size
paired matches on a pinned, training-disjoint Stockfish UHO book.

The script is safe to launch unattended. It records an atomic status file,
prevents system sleep while active, and waits for Trackmania/datagen/another
fastchess process to leave the machine before consuming the GPU or timing games.
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import json
import math
import os
import queue
import re
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import chess
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv/Scripts/python.exe"
CLANG = Path(r"C:\msys64\clang64\bin\clang++.exe")
FASTCHESS = ROOT / "benchmarks/tools/fastchess.exe"
DATA_MANIFEST = ROOT / "data/gen9_book_ab_2420781/manifest.json"
OFFICIAL_ARCHIVE = ROOT / "runs/gen9_book_ab_inputs/UHO_4060_v4.epd.zip"
OFFICIAL_BOOK = ROOT / "runs/gen9_book_ab_inputs/UHO_4060_v4/UHO_4060_v4.epd"
OLD_BOOK = ROOT / "testing/book.epd"
NEW_BOOK = ROOT / "testing/datagen_gen9.epd"

STOCKFISH_BOOKS_COMMIT = "65815ccdbc7727cd4f6aee252ba8f67fb740e92f"
OFFICIAL_ARCHIVE_SHA256 = (
    "a97424c5b98b42f8c27ff450f0681ad11696148548c975752350e98417ead11d"
)
OFFICIAL_CONTENT_SHA256 = (
    "3f499996ff0b674a04f85f2634811d102dd53b5115841e8f11d18e1f550ba2ca"
)
OFFICIAL_CONTENT_SHA384_B64 = (
    "MwywsnSV4YzSj5Q9DI2dUcPcRFMf4LtaOnj4igKRxcGxiSN2HdQPvq/M48kuqz+U"
)
OFFICIAL_POSITIONS = 241_670
RECORD_BYTES = 32
SEEDS = (0, 1)
MATCH_SEED = 20260902

ENGINE_SOURCES = ["main.cpp", "board.cpp", "evaluation.cpp", "search.cpp", "nnue.cpp"]
SOURCE_PATHS = [
    ROOT / "nnue/train.py",
    ROOT / "nnue/nnue_tools.py",
    ROOT / "testing/engine_check.py",
    ROOT / "testing/engine_gate.py",
    ROOT / "testing/chesslite.py",
    Path(__file__).resolve(),
]
SOURCE_PATHS.extend(sorted((ROOT / "sgurr_cpp").glob("*.hpp")))
SOURCE_PATHS.extend(ROOT / "sgurr_cpp" / name for name in ENGINE_SOURCES)


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def sha256(path: Path, chunk_size: int = 4 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk_size):
            digest.update(block)
    return digest.hexdigest()


def sha384_b64(path: Path, chunk_size: int = 4 << 20) -> str:
    digest = hashlib.sha384()
    with path.open("rb") as handle:
        while block := handle.read(chunk_size):
            digest.update(block)
    return base64.b64encode(digest.digest()).decode("ascii")


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(partial, path)


def git_text(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=ROOT, text=True, capture_output=True, check=False
    )
    return proc.stdout.strip()


def process_names() -> set[str]:
    proc = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "Get-Process | Select-Object -ExpandProperty ProcessName",
        ],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if proc.returncode:
        raise RuntimeError(f"Get-Process failed: {proc.stderr.strip()}")
    return {
        line.strip().lower() + ".exe"
        for line in proc.stdout.splitlines()
        if line.strip()
    }


class FileTime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

    def value(self) -> int:
        return (self.high << 32) | self.low


def cpu_sample(seconds: float = 1.0) -> float:
    if os.name != "nt":
        return 0.0
    kernel32 = ctypes.windll.kernel32

    def sample() -> tuple[int, int, int]:
        idle, kernel, user = FileTime(), FileTime(), FileTime()
        if not kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        ):
            raise ctypes.WinError()
        return idle.value(), kernel.value(), user.value()

    idle0, kernel0, user0 = sample()
    time.sleep(seconds)
    idle1, kernel1, user1 = sample()
    idle_delta = idle1 - idle0
    total_delta = (kernel1 - kernel0) + (user1 - user0)
    if total_delta <= 0:
        return 0.0
    return max(0.0, min(100.0, 100.0 * (total_delta - idle_delta) / total_delta))


def gpu_utilization() -> int | None:
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        return int(proc.stdout.strip().splitlines()[0]) if proc.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired, IndexError):
        return None


class Experiment:
    def __init__(self, run_dir: Path, rounds: int, idle_grace: int):
        self.run_dir = run_dir.resolve()
        self.rounds = rounds
        self.idle_grace = idle_grace
        self.status_path = self.run_dir / "status.json"
        self.manifest_path = self.run_dir / "manifest.json"
        self.state: dict[str, object] = {
            "schema_version": 1,
            "pid": os.getpid(),
            "started_at": now(),
            "state": "starting",
            "stage": "preflight",
            "datagen_will_resume": False,
        }
        self.source_snapshot: dict[str, str] = {}

    def update(self, **values: object) -> None:
        self.state.update(values)
        self.state["updated_at"] = now()
        atomic_json(self.status_path, self.state)

    @staticmethod
    def command_text(cmd: list[object]) -> str:
        return subprocess.list2cmdline([str(x) for x in cmd])

    def run_logged(
        self,
        cmd: list[object],
        log_path: Path,
        *,
        cwd: Path = ROOT,
        env: dict[str, str] | None = None,
        label: str,
    ) -> str:
        actual_env = os.environ.copy()
        if env:
            actual_env.update(env)
        actual_env["PYTHONUNBUFFERED"] = "1"
        command = [str(x) for x in cmd]
        log_path.parent.mkdir(parents=True, exist_ok=True)
        collected: list[str] = []
        with log_path.open("a", encoding="utf-8", buffering=1) as log:
            log.write(f"\n[{now()}] $ {self.command_text(command)}\n")
            proc = subprocess.Popen(
                command,
                cwd=cwd,
                env=actual_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            lines: queue.Queue[str | None] = queue.Queue()

            def reader() -> None:
                assert proc.stdout is not None
                for line in proc.stdout:
                    lines.put(line)
                lines.put(None)

            thread = threading.Thread(target=reader, daemon=True)
            thread.start()
            finished_output = False
            last_status = 0.0
            while proc.poll() is None or not finished_output:
                try:
                    line = lines.get(timeout=1.0)
                    if line is None:
                        finished_output = True
                    else:
                        collected.append(line)
                        log.write(line)
                        if "Games:" in line or line.lstrip().startswith("epoch"):
                            self.update(last_output=line.strip())
                except queue.Empty:
                    pass
                if time.monotonic() - last_status >= 15:
                    self.update(child_pid=proc.pid, heartbeat=now(), activity=label)
                    last_status = time.monotonic()
            thread.join(timeout=5)
            code = proc.wait()
        self.update(child_pid=None)
        output = "".join(collected)
        if code:
            raise RuntimeError(
                f"{label} exited {code}; see {log_path.relative_to(ROOT)}"
            )
        return output

    def snapshot_sources(self) -> dict[str, str]:
        missing = [path for path in SOURCE_PATHS if not path.is_file()]
        if missing:
            raise RuntimeError(f"missing source inputs: {missing}")
        return {
            str(path.resolve().relative_to(ROOT)): sha256(path)
            for path in sorted(set(SOURCE_PATHS))
        }

    def assert_sources_unchanged(self) -> None:
        current = self.snapshot_sources()
        if current != self.source_snapshot:
            changed = sorted(
                key
                for key in set(current) | set(self.source_snapshot)
                if current.get(key) != self.source_snapshot.get(key)
            )
            raise RuntimeError(
                "experiment source changed after preflight: " + ", ".join(changed)
            )

    @staticmethod
    def epd_key(line: str) -> str:
        fields = line.strip().split()
        if len(fields) < 4:
            raise RuntimeError(f"invalid EPD/FEN line: {line[:120]!r}")
        return " ".join(fields[:4])

    def load_epd_keys(self, path: Path) -> set[str]:
        return {
            self.epd_key(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

    def prepare_holdout(self) -> dict[str, object]:
        if sha256(OFFICIAL_ARCHIVE) != OFFICIAL_ARCHIVE_SHA256:
            raise RuntimeError("official UHO archive SHA-256 mismatch")
        if sha256(OFFICIAL_BOOK) != OFFICIAL_CONTENT_SHA256:
            raise RuntimeError("official UHO content SHA-256 mismatch")
        if sha384_b64(OFFICIAL_BOOK) != OFFICIAL_CONTENT_SHA384_B64:
            raise RuntimeError("official UHO content does not match books.json SRI")

        old_keys = self.load_epd_keys(OLD_BOOK)
        new_keys = self.load_epd_keys(NEW_BOOK)
        source_lines = [
            line.strip()
            for line in OFFICIAL_BOOK.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        if len(source_lines) != OFFICIAL_POSITIONS:
            raise RuntimeError(
                f"UHO count mismatch: {len(source_lines)} != {OFFICIAL_POSITIONS}"
            )

        official_keys: set[str] = set()
        invalid: list[int] = []
        for number, line in enumerate(source_lines, 1):
            board = chess.Board(line)
            if not board.is_valid() or board.turn != chess.WHITE:
                invalid.append(number)
            official_keys.add(self.epd_key(line))
        if invalid:
            raise RuntimeError(f"invalid UHO positions at lines {invalid[:10]}")
        if len(official_keys) != OFFICIAL_POSITIONS:
            raise RuntimeError("UHO contains duplicate board states")

        overlap_old = official_keys & old_keys
        overlap_new = official_keys & new_keys
        excluded = overlap_old | overlap_new
        kept = [line for line in source_lines if self.epd_key(line) not in excluded]
        holdout = self.run_dir / "UHO_4060_v4_training_disjoint.epd"
        payload = ("\n".join(kept) + "\n").encode("utf-8")
        holdout.write_bytes(payload)

        return {
            "path": str(holdout),
            "source": "official-stockfish/books UHO_4060_v4.epd",
            "source_commit": STOCKFISH_BOOKS_COMMIT,
            "source_url": (
                "https://github.com/official-stockfish/books/blob/"
                f"{STOCKFISH_BOOKS_COMMIT}/UHO_4060_v4.epd.zip"
            ),
            "official_positions": len(source_lines),
            "official_unique_board_states": len(official_keys),
            "invalid_positions": len(invalid),
            "exact_overlap_removed": {
                "old_book": len(overlap_old),
                "new_book": len(overlap_new),
            },
            "positions": len(kept),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "all_white_to_move": True,
            "opening_plies": 16,
        }

    def profile_dataset(self, path: Path) -> dict[str, object]:
        dtype = np.dtype(
            {
                "names": ["stm", "score", "result"],
                "formats": ["u1", "<i2", "u1"],
                "offsets": [24, 25, 27],
                "itemsize": RECORD_BYTES,
            }
        )
        records = np.memmap(path, dtype=dtype, mode="r")
        score = records["score"]
        return {
            "path": str(path),
            "records": int(records.size),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "stm_counts": np.bincount(records["stm"], minlength=2).tolist(),
            "result_counts": np.bincount(records["result"], minlength=3).tolist(),
            "score_mean": float(np.mean(score)),
            "score_std": float(np.std(score)),
            "score_min": int(np.min(score)),
            "score_max": int(np.max(score)),
            "score_quantiles_01_50_99": [
                float(value) for value in np.quantile(score, [0.01, 0.5, 0.99])
            ],
        }

    def verify_packed_data(self, path: Path, label: str) -> str:
        proc = subprocess.run(
            [str(PYTHON), str(ROOT / "nnue/verify_data.py"), str(path)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        output = proc.stdout + proc.stderr
        if proc.returncode or "FORMAT + POSITIONS VALID" not in output:
            raise RuntimeError(f"packed-data check failed for {label}:\n{output}")
        return output.strip()

    def initialise(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self.source_snapshot = self.snapshot_sources()
        atomic_json(
            ROOT / "runs/gen9_book_ab/active.json",
            {"run_dir": str(self.run_dir), "pid": os.getpid(), "started_at": now()},
        )
        self.update(state="initialised", stage="waiting_for_idle")

    def preflight(self) -> tuple[dict[str, Path], Path]:
        self.assert_sources_unchanged()
        required = [
            PYTHON, CLANG, FASTCHESS, DATA_MANIFEST, OFFICIAL_ARCHIVE,
            OFFICIAL_BOOK, OLD_BOOK, NEW_BOOK,
        ]
        missing = [path for path in required if not path.is_file()]
        if missing:
            raise RuntimeError(f"missing required experiment inputs: {missing}")

        data_manifest = json.loads(DATA_MANIFEST.read_text(encoding="utf-8"))
        if data_manifest.get("positions_per_arm") != 2_420_781:
            raise RuntimeError("matched-data manifest has an unexpected position count")

        datasets: dict[str, Path] = {}
        profiles: dict[str, object] = {}
        packed_checks: dict[str, str] = {}
        for arm in ("old", "new"):
            entry = data_manifest["outputs"][arm]
            path = Path(entry["path"])
            if not path.is_file():
                raise RuntimeError(f"missing matched {arm} dataset: {path}")
            if path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
                raise RuntimeError(f"matched {arm} dataset no longer matches its manifest")
            if entry["records"] != data_manifest["positions_per_arm"]:
                raise RuntimeError(f"{arm} dataset count is not matched")
            datasets[arm] = path
            profiles[arm] = self.profile_dataset(path)
            packed_checks[arm] = self.verify_packed_data(path, arm)

        holdout_info = self.prepare_holdout()
        holdout = Path(str(holdout_info["path"]))
        manifest: dict[str, object] = {
            "schema_version": 1,
            "created_at": now(),
            "purpose": "measure the causal effect of the Gen9 datagen opening book",
            "design": {
                "arms": ["old 150-root book", "new 15,000-root book"],
                "positions_per_arm": 2_420_781,
                "paired_training_seeds": list(SEEDS),
                "counterbalanced_training_order": ["old-0", "new-0", "new-1", "old-1"],
                "training": {
                    "architecture": "768x384 unbucketed NNUE",
                    "epochs": 14,
                    "steps_per_epoch": math.ceil(2_420_781 / 16_384),
                    "optimizer_steps": 14 * math.ceil(2_420_781 / 16_384),
                    "batch": 16_384,
                    "lr": 1e-3,
                    "schedule": "cosine",
                    "lr_min": 1e-5,
                    "lambda": 0.9,
                    "val_frac": 0,
                    "loader": "memory",
                },
                "matches": {
                    "one_fixed_match_per_paired_training_seed": True,
                    "rounds_per_seed": self.rounds,
                    "games_per_round": 2,
                    "games_per_seed": self.rounds * 2,
                    "time_control": "8+0.08",
                    "concurrency": 7,
                    "opening_seed": MATCH_SEED,
                    "same_opening_sample_for_both_training_seeds": True,
                    "restart_engine_each_game": True,
                    "fixed_sample_no_sprt": True,
                },
            },
            "matched_data_manifest": str(DATA_MANIFEST),
            "dataset_profiles": profiles,
            "packed_data_checks": packed_checks,
            "holdout": holdout_info,
            "toolchain": {
                "python": sys.version,
                "python_executable": sys.executable,
                "clang": str(CLANG),
                "fastchess": str(FASTCHESS),
            },
            "repository": {
                "commit": git_text("rev-parse", "HEAD"),
                "dirty": bool(git_text("status", "--porcelain")),
                "source_sha256": self.source_snapshot,
            },
            "safety": {
                "wait_for_processes": ["Trackmania.exe", "datagen.exe", "fastchess.exe"],
                "idle_grace_seconds": self.idle_grace,
                "production_datagen_remains_paused": True,
            },
        }
        atomic_json(self.manifest_path, manifest)
        return datasets, holdout

    def wait_for_idle(self, stage: str) -> None:
        stable_since: float | None = None
        self.update(state="waiting_for_idle", stage=stage)
        while True:
            names = process_names()
            blockers = sorted(
                name
                for name in ("trackmania.exe", "datagen.exe", "fastchess.exe")
                if name in names
            )
            cpu = cpu_sample()
            gpu = gpu_utilization()
            quiet = not blockers and cpu < 25.0 and (gpu is None or gpu < 30)
            if quiet:
                stable_since = stable_since or time.monotonic()
            else:
                stable_since = None
            quiet_for = 0 if stable_since is None else int(time.monotonic() - stable_since)
            self.update(
                blockers=blockers,
                cpu_percent=round(cpu, 1),
                gpu_percent=gpu,
                quiet_seconds=quiet_for,
                required_quiet_seconds=self.idle_grace,
            )
            if stable_since is not None and quiet_for >= self.idle_grace:
                break
            time.sleep(14)
        self.update(blockers=[], state="running", stage=stage)

    def train(self, datasets: dict[str, Path]) -> dict[str, dict[str, object]]:
        results: dict[str, dict[str, object]] = {"old": {}, "new": {}}
        order = [("old", 0), ("new", 0), ("new", 1), ("old", 1)]
        nets_dir = self.run_dir / "nets"
        nets_dir.mkdir()
        for arm, seed in order:
            self.wait_for_idle(f"train_{arm}_seed{seed}")
            self.assert_sources_unchanged()
            net = nets_dir / f"{arm}_seed{seed}.nnue"
            log = self.run_dir / "logs" / f"train_{arm}_seed{seed}.log"
            cmd: list[object] = [
                PYTHON, "-u", ROOT / "nnue/train.py",
                "--data", datasets[arm], "--out", net,
                "--hl", "384", "--epochs", "14", "--batch", "16384",
                "--lr", "0.001", "--schedule", "cosine", "--lr_min", "1e-5",
                "--lambda_", "0.9", "--val_frac", "0", "--loader", "memory",
                "--seed", str(seed),
            ]
            self.update(stage=f"train_{arm}_seed{seed}", activity="training")
            output = self.run_logged(
                cmd,
                log,
                cwd=ROOT / "nnue",
                env={"KMP_DUPLICATE_LIB_OK": "TRUE"},
                label=f"train {arm} seed {seed}",
            )
            losses = [
                float(value)
                for value in re.findall(r"epoch\s+\d+/\d+\s+loss\s+([\d.]+)", output)
            ]
            if len(losses) != 14 or not math.isfinite(losses[-1]) or losses[-1] > 0.1:
                raise RuntimeError(f"implausible training curve for {arm} seed {seed}")
            results[arm][str(seed)] = {
                "net": str(net),
                "sha256": sha256(net),
                "loss_curve": losses,
                "final_loss": losses[-1],
                "log": str(log),
            }
            self.update(training=results)
        return results

    def build_and_gate(
        self, training: dict[str, dict[str, object]]
    ) -> dict[str, dict[str, object]]:
        self.wait_for_idle("build_and_gate")
        self.assert_sources_unchanged()
        engine_dir = self.run_dir / "engines"
        engine_dir.mkdir()
        build_log = self.run_dir / "logs/build_and_gate.log"
        selfcheck = engine_dir / "nnue_selfcheck.exe"
        self.run_logged(
            [
                CLANG, "-std=c++20", "-O3", "-march=native", "-DNDEBUG", "-static",
                "nnue_selfcheck.cpp", "board.cpp", "evaluation.cpp", "search.cpp",
                "nnue.cpp", "-o", selfcheck,
            ],
            build_log,
            cwd=ROOT / "sgurr_cpp",
            label="build NNUE selfcheck",
        )

        builds: dict[str, dict[str, object]] = {}
        paths: list[Path] = []
        for seed in SEEDS:
            for arm in ("old", "new"):
                key = f"{arm}_seed{seed}"
                net = Path(str(training[arm][str(seed)]["net"]))
                exe = engine_dir / f"sgr_{key}.exe"
                define = f'-DSGR_DEFAULT_NET="{net.as_posix()}"'
                self.run_logged(
                    [
                        CLANG, "-std=c++20", "-O3", "-march=native", "-DNDEBUG",
                        "-static", define, *ENGINE_SOURCES, "-o", exe,
                    ],
                    build_log,
                    cwd=ROOT / "sgurr_cpp",
                    label=f"build {key}",
                )
                check_output = self.run_logged(
                    [selfcheck, net],
                    build_log,
                    cwd=ROOT / "sgurr_cpp",
                    label=f"selfcheck {key}",
                )
                if "-> PASS" not in check_output:
                    raise RuntimeError(f"NNUE selfcheck failed for {key}")
                builds[key] = {
                    "engine": str(exe),
                    "engine_sha256": sha256(exe),
                    "net": str(net),
                    "net_sha256": sha256(net),
                    "selfcheck": "PASS",
                }
                paths.append(exe)

        check = self.run_logged(
            [PYTHON, ROOT / "testing/engine_check.py", *paths],
            build_log,
            label="UCI handshake gate",
        )
        gate = self.run_logged(
            [PYTHON, ROOT / "testing/engine_gate.py", *paths],
            build_log,
            label="legality and FEN gate",
        )
        if check.count("OK ") < 4 or gate.count("OK") < 4:
            raise RuntimeError("engine gates did not report four passing engines")
        self.assert_sources_unchanged()
        self.update(builds=builds, stage="build_and_gate_complete")
        return builds

    @staticmethod
    def parse_match(output: str, expected_games: int) -> dict[str, object]:
        elo_matches = re.findall(
            r"(?m)^Elo:\s*([-+]?\d+(?:\.\d+)?)\s*\+/-\s*(\d+(?:\.\d+)?)",
            output,
        )
        game_matches = re.findall(
            r"Games:\s*(\d+),\s*Wins:\s*(\d+),\s*Losses:\s*(\d+),\s*Draws:\s*(\d+)",
            output,
        )
        penta_matches = re.findall(r"Ptnml\(0-2\):\s*\[([^\]]+)\]", output)
        if not elo_matches or not game_matches or not penta_matches:
            raise RuntimeError("could not parse final fastchess result")
        elo, error = map(float, elo_matches[-1])
        games, wins, losses, draws = map(int, game_matches[-1])
        penta = [int(value.strip()) for value in penta_matches[-1].split(",")]
        if games != expected_games or wins + losses + draws != games:
            raise RuntimeError(f"match ended at {games} games, expected {expected_games}")
        if len(penta) != 5 or sum(penta) * 2 != games:
            raise RuntimeError("invalid pentanomial result")
        bad_patterns = [
            r"Warning;",
            r"illegal move",
            r"disconnect",
            r"stalled connection",
            r"doesn't have time to make a move",
            r"engine.*crash",
        ]
        bad_lines = [
            line
            for line in output.splitlines()
            if any(re.search(pattern, line, re.IGNORECASE) for pattern in bad_patterns)
        ]
        if bad_lines:
            raise RuntimeError("fastchess reported a forfeit/crash: " + bad_lines[0])
        return {
            "elo_new_minus_old": elo,
            "match_95ci_half_width": error,
            "games": games,
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "pentanomial": penta,
        }

    def match_seed(
        self, seed: int, builds: dict[str, dict[str, object]], holdout: Path
    ) -> dict[str, object]:
        self.wait_for_idle(f"match_seed{seed}")
        self.assert_sources_unchanged()
        match_dir = self.run_dir / f"match_seed{seed}"
        match_dir.mkdir()
        new = Path(str(builds[f"new_seed{seed}"]["engine"]))
        old = Path(str(builds[f"old_seed{seed}"]["engine"]))
        log = match_dir / "match.log"
        pgn = match_dir / "games.pgn"
        cmd: list[object] = [
            FASTCHESS,
            "-engine", f"cmd={new}", f"name=new_seed{seed}",
            "-engine", f"cmd={old}", f"name=old_seed{seed}",
            "-each", "tc=8+0.08", "restart=on",
            "-rounds", str(self.rounds), "-repeat", "-concurrency", "7",
            "-openings", f"file={holdout}", "format=epd", "order=random",
            "-srand", str(MATCH_SEED),
            "-ratinginterval", "100",
            "-pgnout", f"file={pgn}", "notation=san", "append=false",
            "-event", f"Sgurr Gen9 opening-book A/B seed {seed}",
            "-site", "local",
        ]
        self.update(stage=f"match_seed{seed}", activity="timed games")
        output = self.run_logged(cmd, log, cwd=match_dir, label=f"fixed match seed {seed}")
        result = self.parse_match(output, self.rounds * 2)
        event_count = sum(
            line.startswith("[Event ")
            for line in pgn.read_text(encoding="utf-8", errors="replace").splitlines()
        )
        if event_count != self.rounds * 2:
            raise RuntimeError(f"PGN has {event_count} games, expected {self.rounds * 2}")
        result.update(
            {
                "training_seed": seed,
                "opening_seed": MATCH_SEED,
                "book_sha256": sha256(holdout),
                "log": str(log),
                "pgn": str(pgn),
                "pgn_sha256": sha256(pgn),
            }
        )
        return result

    def summarize(self, matches: list[dict[str, object]]) -> dict[str, object]:
        elos = [float(match["elo_new_minus_old"]) for match in matches]
        mean = sum(elos) / len(elos)
        spread = abs(elos[0] - elos[1]) if len(elos) == 2 else None
        if mean >= 25 and all(elo > 0 for elo in elos):
            verdict = "supports the new book"
            action = "keep the new book for Gen9 production"
        elif mean <= -25 and all(elo < 0 for elo in elos):
            verdict = "evidence the new book is harmful at this data scale"
            action = "investigate before resuming Gen9 with the new book"
        else:
            verdict = "inconclusive at the 2.4M-position scale"
            action = "keep the broader book on prior grounds; do not claim an Elo gain"
        return {
            "completed_at": now(),
            "effect_definition": "positive Elo means new-book-trained net is stronger",
            "per_seed": matches,
            "mean_of_two_paired_seed_elos": mean,
            "absolute_between_seed_elo_difference": spread,
            "verdict": verdict,
            "recommended_action": action,
            "uncertainty_note": (
                "The same opening sample is reused across seeds, so the two match "
                "confidence intervals must not be naively combined. Two training seeds "
                "test direction consistency but do not fully characterize seed noise."
            ),
            "production_datagen_resumed": False,
        }

    def run(self) -> None:
        self.initialise()
        self.wait_for_idle("preflight")
        datasets, holdout = self.preflight()
        self.update(state="preflight_complete", stage="training")
        training = self.train(datasets)
        builds = self.build_and_gate(training)
        matches: list[dict[str, object]] = []
        for seed in SEEDS:
            matches.append(self.match_seed(seed, builds, holdout))
            self.update(matches=matches)
        summary = self.summarize(matches)
        atomic_json(self.run_dir / "results.json", summary)
        self.update(
            state="complete",
            stage="complete",
            completed_at=now(),
            result=summary,
            activity=None,
            last_output=None,
        )


def set_awake(enable: bool) -> None:
    if os.name != "nt":
        return
    es_continuous = 0x80000000
    es_system_required = 0x00000001
    flags = es_continuous | es_system_required if enable else es_continuous
    ctypes.windll.kernel32.SetThreadExecutionState(flags)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=1000)
    parser.add_argument("--idle-grace", type=int, default=90)
    args = parser.parse_args()
    if args.rounds <= 0 or args.idle_grace < 0:
        parser.error("rounds must be positive and idle-grace non-negative")

    experiment = Experiment(args.run_dir, args.rounds, args.idle_grace)
    set_awake(True)
    try:
        experiment.run()
        return 0
    except Exception as exc:
        failure = traceback.format_exc()
        try:
            experiment.run_dir.mkdir(parents=True, exist_ok=True)
            (experiment.run_dir / "failure.log").write_text(failure, encoding="utf-8")
            experiment.update(
                state="failed",
                stage="failed",
                failed_at=now(),
                error=str(exc),
                traceback=str(experiment.run_dir / "failure.log"),
            )
        except Exception:
            pass
        print(failure, file=sys.stderr, flush=True)
        return 1
    finally:
        set_awake(False)


if __name__ == "__main__":
    raise SystemExit(main())
