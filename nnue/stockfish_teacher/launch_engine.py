"""Transparent match launcher; both arms execute the same Sgurr search binary.

The C++ child inherits fastchess's pipes directly (no Python UCI proxy loop).
Only its network environment differs. Stockfish is not involved at runtime.
"""
import argparse
import os
from pathlib import Path
import subprocess
from common import sha256


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True, type=Path)
    ap.add_argument("--net", required=True, type=Path)
    ap.add_argument("--sha256", required=True)
    args = ap.parse_args()
    if sha256(args.net) != args.sha256:
        raise RuntimeError("Network checksum differs; refusing to launch")
    env = os.environ.copy()
    env["SGR_EVALFILE"] = str(args.net.resolve())
    child = subprocess.Popen([str(args.engine.resolve())], env=env)
    try:
        return child.wait()
    except BaseException:
        child.kill()
        child.wait()
        raise


if __name__ == "__main__":
    raise SystemExit(main())
