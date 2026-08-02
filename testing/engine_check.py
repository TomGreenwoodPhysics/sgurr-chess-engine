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


def verify_engine(path, timeout: float = DEFAULT_TIMEOUT) -> str:
    """Launch `path` and complete a UCI handshake.

    Returns the engine's advertised `id name` on success. Raises
    EngineUnusable, with a diagnosis specific enough to act on, otherwise.
    """
    p = Path(path)

    if not p.exists():
        raise EngineUnusable(f"{p}: file does not exist")

    if p.is_dir():
        raise EngineUnusable(f"{p}: is a directory, not an engine binary")

    if p.stat().st_size == 0:
        raise EngineUnusable(f"{p}: file is empty (a truncated or failed link?)")

    try:
        proc = subprocess.run(
            [str(p), "uci"],
            input="uci\nisready\nquit\n",
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise EngineUnusable(
            f"{p}: started but did not answer the UCI handshake within "
            f"{timeout:g}s. It is running yet unresponsive -- a hang on "
            f"startup, or waiting on something (a missing network file?)."
        ) from None
    except (OSError, ValueError) as exc:
        # PermissionError / OSError is what a security-policy block surfaces as.
        raise EngineUnusable(f"{p}: could not be started ({exc}).\n{_BLOCKED_HINT}") from None

    out = (proc.stdout or "") + (proc.stderr or "")

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
