#!/usr/bin/env python3
"""Build and admit matched Gen9-102M and Gen8 engines for strength testing."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "sgurr_cpp"
RUN = ROOT / "runs/gen9_102m"
OUT = RUN / "engines"
CLANG = Path(r"C:\msys64\clang64\bin\clang++.exe")
SOURCES = ["main.cpp", "board.cpp", "evaluation.cpp", "search.cpp", "nnue.cpp"]
COMMON = ["-std=c++20", "-O3", "-march=native", "-DNDEBUG", "-static"]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 << 20):
            value.update(chunk)
    return value.hexdigest()


def run(
    command: list[str | Path], *, cwd: Path = ROOT, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(
        [str(value) for value in command],
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        env=os.environ,
        input=input_text,
    )
    with (RUN / "build_and_gate.log").open("a", encoding="utf-8") as log:
        log.write("\n$ " + subprocess.list2cmdline([str(value) for value in command]) + "\n")
        log.write(process.stdout)
        log.write(process.stderr)
        log.write(f"[exit {process.returncode}]\n")
    return process


def compile_engine(net: Path, output: Path) -> None:
    define = f'-DSGR_DEFAULT_NET="{net.as_posix()}"'
    for attempt in range(1, 7):
        process = run([CLANG, *COMMON, define, *SOURCES, "-o", output], cwd=CPP)
        if process.returncode:
            raise RuntimeError(f"compile failed for {output.name}; see build_and_gate.log")
        handshake = run([output], input_text="uci\nisready\nquit\n")
        combined = handshake.stdout + handshake.stderr
        loaded = net.as_posix().lower() in combined.replace("\\", "/").lower()
        if handshake.returncode == 0 and "uciok" in handshake.stdout and loaded:
            return
        output.unlink(missing_ok=True)
        with (RUN / "build_and_gate.log").open("a", encoding="utf-8") as log:
            log.write(f"relinking {output.name} after failed startup attempt {attempt}\n")
    raise RuntimeError(f"{output.name} did not pass startup after six links")


def require_ok(process: subprocess.CompletedProcess[str], label: str, marker: str) -> None:
    combined = process.stdout + process.stderr
    if process.returncode or marker not in combined:
        raise RuntimeError(f"{label} failed; see build_and_gate.log")


def main() -> None:
    global RUN, OUT

    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-net", default="nets/gen9-102m-s0.nnue")
    parser.add_argument("--reference-net", default="nets/gen8.nnue")
    parser.add_argument("--run-dir", default="runs/gen9_102m")
    parser.add_argument("--candidate-engine", default="sgr_gen9_102m_s0.exe")
    parser.add_argument("--reference-engine", default="sgr_gen8_ref.exe")
    parser.add_argument(
        "--description",
        default="Gen9 102,011,689-position seed-0 net versus canonical Gen8 net",
    )
    args = parser.parse_args()

    def under_root(value: str) -> Path:
        path = Path(value)
        return path.resolve() if path.is_absolute() else (ROOT / path).resolve()

    RUN = under_root(args.run_dir)
    OUT = RUN / "engines"
    OUT.mkdir(parents=True, exist_ok=True)
    temp = RUN / "tmp"
    temp.mkdir(parents=True, exist_ok=True)
    os.environ["TMP"] = str(temp)
    os.environ["TEMP"] = str(temp)

    log = RUN / "build_and_gate.log"
    log.write_text("", encoding="utf-8")
    candidate_net = under_root(args.candidate_net)
    reference_net = under_root(args.reference_net)
    if not candidate_net.is_file() or not reference_net.is_file():
        raise RuntimeError("candidate or reference network is missing")

    candidate = OUT / args.candidate_engine
    reference = OUT / args.reference_engine
    compile_engine(candidate_net, candidate)
    compile_engine(reference_net, reference)

    selfcheck = OUT / "nnue_selfcheck.exe"
    built = run(
        [
            CLANG,
            *COMMON,
            "nnue_selfcheck.cpp",
            "board.cpp",
            "evaluation.cpp",
            "search.cpp",
            "nnue.cpp",
            "-o",
            selfcheck,
        ],
        cwd=CPP,
    )
    if built.returncode:
        raise RuntimeError("selfcheck compile failed; see build_and_gate.log")
    require_ok(run([selfcheck, candidate_net]), "candidate selfcheck", "-> PASS")
    require_ok(run([selfcheck, reference_net]), "reference selfcheck", "-> PASS")

    require_ok(
        run([sys.executable, ROOT / "testing/engine_check.py", candidate, reference]),
        "UCI handshake gate",
        "OK ",
    )
    require_ok(
        run([sys.executable, ROOT / "testing/engine_gate.py", candidate, reference]),
        "legality/FEN gate",
        "OK",
    )

    compiler = run([CLANG, "--version"])
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(),
        "comparison": args.description,
        "search_source_identical": True,
        "flags": COMMON,
        "compiler": compiler.stdout.splitlines()[0],
        "sources": {name: digest(CPP / name) for name in SOURCES},
        "candidate": {
            "net": str(candidate_net),
            "net_sha256": digest(candidate_net),
            "engine": str(candidate),
            "engine_sha256": digest(candidate),
        },
        "reference": {
            "net": str(reference_net),
            "net_sha256": digest(reference_net),
            "engine": str(reference),
            "engine_sha256": digest(reference),
        },
        "gates": {
            "candidate_selfcheck": "PASS",
            "reference_selfcheck": "PASS",
            "uci_handshake": "PASS",
            "legality_and_fen": "PASS",
        },
        "log": str(log),
    }
    (RUN / "build.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
