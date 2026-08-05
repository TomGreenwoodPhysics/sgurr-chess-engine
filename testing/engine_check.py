#!/usr/bin/env python3
"""Pre-flight check that a UCI engine binary actually runs.

Why this exists
---------------
`Path.exists()` is not the same as "this binary will execute". On this machine
Smart App Control is enforced (`VerifiedAndReputablePolicyState = 1`) and
intermittently blocks freshly linked unsigned binaries at first execution --
observed at roughly 2 in 6 builds, with the block landing on the *file*, not
the code: two byte-identical binaries under different names, one blocked and
one not. Windows Defender re-scans have caused the same class of failure
before (DEVLOG 2026-07-29 lost a calibration gauntlet to a transient block
32 seconds in).

The dangerous part is not the failure, it is its shape. A dead engine driven
by testing/sprt.py used to produce a *complete, plausible SPRT result*:
`_wait()` fell out of its loop at EOF and returned silently, `bestmove()`
returned None, and the game loop scored None as an illegal move -- i.e. a loss.
An engine that cannot start looked exactly like an engine that is catastrophically
weak, and the match still reported a verdict. That is precisely the
"silent failure produces plausible output" pattern METHODOLOGY.md 7 records as
this project's most expensive class of bug.

So: verify before spending hours, and fail loudly with a specific diagnosis.

Usage as a module:
    from engine_check import verify_engine, EngineUnusable
    verify_engine("path/to/sgr.exe")            # raises EngineUnusable on failure

Usage from the shell:
    python testing/engine_check.py a.exe b.exe  # exit 0 if all usable, 1 if not
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

DEFAULT_TIMEOUT = 20.0

# Shown whenever the operating system refuses to start the binary at all. The
# rebuild advice is the actual remedy: a blocked binary stays blocked, but a
# fresh link is usually allowed, and once a binary has run it keeps running.
_BLOCKED_HINT = (
    "The OS refused to start this file. On this machine that is usually Smart "
    "App Control, which is ENFORCED and intermittently blocks freshly linked "
    "unsigned binaries. It has no exclusion mechanism, so the remedy is to "
    "rebuild (a new link is normally allowed) and re-verify. Note that "
    "disabling Smart App Control is a ONE-WAY switch -- Windows cannot "
    "re-enable it without an OS reset -- so rebuilding is the cheap fix. "
    "Confirm the diagnosis with:  powershell -c \"& '<path>' \""
)


class EngineUnusable(RuntimeError):
    """A binary that cannot be trusted to play games, with the reason why."""


def verify_engine(path, timeout: float = DEFAULT_TIMEOUT,
                  attempts: int = 3, retry_delay: float = 3.0) -> str:
    """Launch `path` and complete a UCI handshake.

    Returns the engine's advertised `id name` on success. Raises
    EngineUnusable, with a diagnosis specific enough to act on, otherwise.

    Retries on a spawn failure, and that is not belt-and-braces. Smart App
    Control blocks were assumed to be sticky -- once a binary ran, it kept
    running -- and on 2026-08-04 zahak-4.0.exe, an unchanged third-party pool
    engine that had passed this same check three hours earlier, was refused
    once and then started immediately on the next attempt. A single-attempt
    preflight would have aborted an overnight calibration over a momentary
    reputation lookup.

    Deterministic failures (missing, empty, a directory) are not retried; there
    is nothing for a second attempt to change.
    """
    p = Path(path)

    if not p.exists():
        raise EngineUnusable(f"{p}: file does not exist")

    if p.is_dir():
        raise EngineUnusable(f"{p}: is a directory, not an engine binary")

    if p.stat().st_size == 0:
        raise EngineUnusable(f"{p}: file is empty (a truncated or failed link?)")

    last = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return _try_handshake(p, timeout)
        except EngineUnusable as exc:
            last = exc
            if attempt < attempts:
                time.sleep(retry_delay)
    raise last if last else EngineUnusable(f"{p}: unusable")


def _try_handshake(p: Path, timeout: float) -> str:
    """One launch-and-handshake attempt. See verify_engine for the retry policy."""

    # A real UCI handshake, not a batch write.
    #
    # Two things here are load-bearing, and both were learned the hard way when
    # this check declared three healthy pool engines broken:
    #
    #  1. Launch with NO arguments and keep stdin OPEN. Writing the whole
    #     handshake and closing the pipe looks equivalent and is not: Blunder
    #     7.4/7.6/8.0 print their banner and exit without ever sending uciok
    #     once stdin is at EOF, while playing perfectly under fastchess, which
    #     holds the pipe open. Passing "uci" as argv is also Sgurr-specific.
    #  2. errors="replace". Engines print banners in whatever encoding they
    #     like, and one stray byte (0x90, in Blunder's) otherwise raises inside
    #     subprocess's reader THREAD -- killing the reader, losing the
    #     handshake, and surfacing as a bogus timeout on a healthy engine.
    try:
        proc = subprocess.Popen(
            [str(p)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except (OSError, ValueError) as exc:
        # PermissionError / OSError is what a security-policy block surfaces as.
        raise EngineUnusable(f"{p}: could not be started ({exc}).\n{_BLOCKED_HINT}") from None

    collected: list[str] = []

    def _reader() -> None:
        try:
            for line in proc.stdout:                       # type: ignore[union-attr]
                collected.append(line)
        except Exception:                                  # pipe closed under us
            pass

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()

    def _seen(token: str) -> bool:
        return any(line.strip().startswith(token) for line in list(collected))

    def _await(token: str, deadline: float) -> bool:
        while time.monotonic() < deadline:
            if _seen(token):
                return True
            if proc.poll() is not None:                    # died before answering
                return _seen(token)
            time.sleep(0.02)
        return _seen(token)

    deadline = time.monotonic() + timeout
    try:
        proc.stdin.write("uci\n"); proc.stdin.flush()      # type: ignore[union-attr]
        if _await("uciok", deadline):
            proc.stdin.write("isready\n"); proc.stdin.flush()   # type: ignore[union-attr]
            _await("readyok", deadline)
        proc.stdin.write("quit\n"); proc.stdin.flush()     # type: ignore[union-attr]
    except (BrokenPipeError, OSError):
        pass                                               # died mid-handshake

    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    reader.join(timeout=1)

    out = "".join(collected)

    if "uciok" not in out:
        detail = out.strip().splitlines()
        tail = detail[-3:] if detail else ["<no output at all>"]
        raise EngineUnusable(
            f"{p}: started but never sent 'uciok' (exit code {proc.returncode}).\n"
            f"  last output: {tail}\n"
            f"  Either this is not a UCI engine, or it died during startup. "
            f"A binary that produces NO output at all and exits immediately is "
            f"the signature of a security-policy block.\n{_BLOCKED_HINT}"
        )

    if "readyok" not in out:
        raise EngineUnusable(
            f"{p}: answered 'uciok' but never 'readyok' -- it is not completing "
            f"initialisation, so it would stall or forfeit in a real game."
        )

    name = ""
    for line in out.splitlines():
        if line.startswith("id name"):
            name = line[len("id name"):].strip()
            break

    return name or p.name


def verify_all(paths, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Verify several engines, reporting EVERY failure rather than the first.

    Returns {path: id_name}. Raises EngineUnusable listing all failures, so a
    gauntlet with a broken pool engine names all of them in one pass instead of
    forcing one rebuild-and-retry cycle per binary.
    """
    ok, bad = {}, []

    for path in paths:
        try:
            ok[str(path)] = verify_engine(path, timeout)
        except EngineUnusable as exc:
            bad.append(str(exc))

    if bad:
        raise EngineUnusable(
            f"{len(bad)} of {len(list(paths))} engine(s) unusable:\n\n"
            + "\n\n".join(f"  * {b}" for b in bad)
        )

    return ok


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    try:
        for path, name in verify_all(argv[1:]).items():
            print(f"OK  {path}  ->  {name}")
    except EngineUnusable as exc:
        print(f"\nENGINE CHECK FAILED\n\n{exc}\n", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
