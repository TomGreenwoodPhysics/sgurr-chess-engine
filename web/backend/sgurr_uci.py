from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class EngineError(RuntimeError):
    """Base class for UCI bridge failures."""


class EngineStartupError(EngineError):
    """Raised when the Sgurr process cannot be started or initialized."""


class EngineCrashedError(EngineError):
    """Raised when the Sgurr process exits unexpectedly."""


class EngineTimeoutError(EngineError):
    """Raised when the engine does not answer within the requested timeout."""


@dataclass(frozen=True)
class UciInfo:
    score_kind: str
    score: int
    depth: int | None = None
    nodes: int | None = None
    nps: int | None = None
    hashfull: int | None = None
    time_ms: int | None = None
    pv: list[str] | None = None
    raw: str = ""


@dataclass(frozen=True)
class UciSearchResult:
    bestmove: str
    info: UciInfo | None
    raw_lines: list[str]


_SCORE_RE = re.compile(r"\bscore\s+(cp|mate)\s+(-?\d+)")
_DEPTH_RE = re.compile(r"\bdepth\s+(\d+)")
_NODES_RE = re.compile(r"\bnodes\s+(\d+)")
_NPS_RE = re.compile(r"\bnps\s+(\d+)")
_HASHFULL_RE = re.compile(r"\bhashfull\s+(\d+)")
_TIME_RE = re.compile(r"\btime\s+(\d+)")


def _parse_int(pattern: re.Pattern[str], line: str) -> int | None:
    match = pattern.search(line)
    return int(match.group(1)) if match else None


def parse_uci_info(line: str) -> UciInfo | None:
    score_match = _SCORE_RE.search(line)
    if not score_match:
        return None

    tokens = line.split()
    pv: list[str] | None = None
    if "pv" in tokens:
        pv_index = tokens.index("pv")
        pv = tokens[pv_index + 1 :] or None

    return UciInfo(
        score_kind=score_match.group(1),
        score=int(score_match.group(2)),
        depth=_parse_int(_DEPTH_RE, line),
        nodes=_parse_int(_NODES_RE, line),
        nps=_parse_int(_NPS_RE, line),
        hashfull=_parse_int(_HASHFULL_RE, line),
        time_ms=_parse_int(_TIME_RE, line),
        pv=pv,
        raw=line,
    )


class SgurrUciEngine:
    """Small persistent UCI bridge for the local Sgurr executable."""

    def __init__(
        self,
        engine_path: Path,
        *,
        startup_timeout: float = 5.0,
        net_path: Path | None = None,
    ) -> None:
        self.engine_path = engine_path
        self.startup_timeout = startup_timeout
        self.net_path = net_path
        self._process: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._lock = threading.RLock()
        self._new_game_pending = True

    @property
    def is_running(self) -> bool:
        process = self._process
        return process is not None and process.poll() is None

    def mark_new_game(self) -> None:
        with self._lock:
            self._new_game_pending = True
            if self.is_running:
                self._drain_lines_locked()
                self._send_locked("ucinewgame")
                self._send_locked("isready")
                self._wait_for_locked(
                    lambda line: line.strip() == "readyok",
                    self.startup_timeout,
                    "readyok after ucinewgame",
                )
                self._new_game_pending = False

    def search(
        self,
        fen: str,
        go_args: str,
        timeout_seconds: float,
        *,
        on_info: Callable[[UciInfo], None] | None = None,
        on_line: Callable[[str], None] | None = None,
    ) -> UciSearchResult:
        with self._lock:
            self._start_locked()
            self._send_new_game_if_needed_locked()
            self._drain_lines_locked()
            self._send_locked(f"position fen {fen}")
            self._send_locked(f"go {go_args}")

            raw_lines: list[str] = []
            latest_info: UciInfo | None = None
            deadline = time.monotonic() + timeout_seconds

            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._kill_locked()
                    raise EngineTimeoutError(
                        f"Sgurr did not return bestmove within {timeout_seconds:.1f}s"
                    )

                line = self._read_line_locked(remaining)
                raw_lines.append(line)
                if on_line is not None:
                    on_line(line)

                parsed = parse_uci_info(line)
                if parsed is not None:
                    latest_info = parsed
                    if on_info is not None:
                        on_info(parsed)

                if line.startswith("bestmove"):
                    parts = line.split()
                    if len(parts) < 2:
                        raise EngineCrashedError(f"Malformed bestmove line: {line}")
                    return UciSearchResult(parts[1], latest_info, raw_lines)

    def close(self) -> None:
        with self._lock:
            process = self._process
            if process is None:
                return

            if process.poll() is None:
                try:
                    self._send_locked("quit")
                    process.wait(timeout=1.0)
                except Exception:
                    self._kill_locked()

            self._process = None

    def cancel(self) -> None:
        """Interrupt an active search without waiting for the search lock."""
        process = self._process
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
        except OSError:
            pass

    def _start_locked(self) -> None:
        if self.is_running:
            return

        if self._process is not None:
            self._drain_lines_locked()
            self._process = None

        if not self.engine_path.exists():
            raise EngineStartupError(
                f"Engine executable not found: {self.engine_path}"
            )

        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

        # Released binaries have an absolute default net compiled in
        # (-DSGR_DEFAULT_NET) that only resolves on the machine that built them.
        # $SGR_EVALFILE overrides it, so each engine finds its own net wherever
        # the repo lives. Without this they silently fall back to the HCE --
        # no error, just "info string nnue: no network", and ~430 Elo missing.
        env = dict(os.environ)
        if self.net_path is not None:
            env["SGR_EVALFILE"] = str(self.net_path)

        try:
            self._process = subprocess.Popen(
                [str(self.engine_path), "uci"],
                cwd=str(self.engine_path.parent),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=flags,
                env=env,
            )
        except OSError as exc:
            raise EngineStartupError(f"Could not start Sgurr: {exc}") from exc

        self._reader = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader.start()

        try:
            self._send_locked("uci")
            self._wait_for_locked(
                lambda line: line.strip() == "uciok",
                self.startup_timeout,
                "uciok",
            )
            self._send_locked("isready")
            self._wait_for_locked(
                lambda line: line.strip() == "readyok",
                self.startup_timeout,
                "readyok",
            )
        except EngineError:
            self._kill_locked()
            raise

    def _send_new_game_if_needed_locked(self) -> None:
        if not self._new_game_pending:
            return
        self._send_locked("ucinewgame")
        self._send_locked("isready")
        self._wait_for_locked(
            lambda line: line.strip() == "readyok",
            self.startup_timeout,
            "readyok after ucinewgame",
        )
        self._new_game_pending = False

    def _reader_loop(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            self._lines.put(None)
            return

        try:
            for line in process.stdout:
                self._lines.put(line.rstrip("\r\n"))
        finally:
            self._lines.put(None)

    def _send_locked(self, command: str) -> None:
        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            raise EngineCrashedError("Sgurr is not running")

        try:
            process.stdin.write(command + "\n")
            process.stdin.flush()
        except OSError as exc:
            raise EngineCrashedError(f"Could not write to Sgurr: {exc}") from exc

    def _wait_for_locked(
        self,
        predicate: Callable[[str], bool],
        timeout_seconds: float,
        label: str,
    ) -> str:
        deadline = time.monotonic() + timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise EngineTimeoutError(f"Timed out waiting for {label}")
            line = self._read_line_locked(remaining)
            if predicate(line):
                return line

    def _read_line_locked(self, timeout_seconds: float) -> str:
        process = self._process
        wait = max(0.01, min(timeout_seconds, 0.1))

        while True:
            try:
                line = self._lines.get(timeout=wait)
            except queue.Empty:
                if process is not None and process.poll() is not None:
                    raise EngineCrashedError(
                        f"Sgurr exited with code {process.returncode}"
                    )
                timeout_seconds -= wait
                if timeout_seconds <= 0:
                    raise EngineTimeoutError("Timed out waiting for Sgurr output")
                wait = max(0.01, min(timeout_seconds, 0.1))
                continue

            if line is None:
                code = process.returncode if process is not None else "unknown"
                raise EngineCrashedError(f"Sgurr exited with code {code}")
            return line

    def _drain_lines_locked(self) -> None:
        while True:
            try:
                self._lines.get_nowait()
            except queue.Empty:
                return

    def _kill_locked(self) -> None:
        process = self._process
        if process is None:
            return

        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=1.0)
            except Exception:
                process.kill()
                process.wait(timeout=1.0)

        self._process = None
        self._drain_lines_locked()
