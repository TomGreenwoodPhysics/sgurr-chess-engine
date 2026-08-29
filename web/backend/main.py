from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import queue
import re
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

import chess
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:
    from .sgurr_uci import (
        EngineCrashedError,
        EngineStartupError,
        EngineTimeoutError,
        SgurrUciEngine,
        UciInfo,
    )
except ImportError:  # Supports `uvicorn main:app` from web/backend.
    from sgurr_uci import (  # type: ignore
        EngineCrashedError,
        EngineStartupError,
        EngineTimeoutError,
        SgurrUciEngine,
        UciInfo,
    )


BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parents[1]
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
FRONTEND_ASSETS_DIR = FRONTEND_DIR / "assets"
ROOT_ASSETS_DIR = REPO_ROOT / "assets"
LOGGER = logging.getLogger("sgurr.web")


def env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be true or false")


def bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name)
    try:
        value = default if raw is None else int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


PUBLIC_DEMO = env_flag("SGURR_PUBLIC_DEMO")
# Selectable opponents
# The frontend lists these engines and sends an ID with each move.
# SGURR_ENGINE_EXE still overrides the default binary.
CPP_DIR = REPO_ROOT / "sgurr_cpp"
NETS_DIR = REPO_ROOT / "nets"
_trace_engine_override = os.environ.get("SGURR_TRACE_ENGINE_EXE")
TRACE_ENGINE_PATH = (
    Path(_trace_engine_override)
    if _trace_engine_override
    else CPP_DIR / "sgr_trace.exe"
)
if not TRACE_ENGINE_PATH.is_absolute():
    TRACE_ENGINE_PATH = REPO_ROOT / TRACE_ENGINE_PATH
TRACE_ENGINE_PATH = TRACE_ENGINE_PATH.resolve()
# Canonical releases appear newest first, with index 0 as the default.
# Older ratings use old rating + (3012.1 - 3058.5), rounded to the nearest Elo.
# They are estimates rather than official CCRL ratings.
# v3.1 ranks below v3.0 because its flat soft limit lost games at the pool TC.
# `rating` supplies both the subtitle and the frontend ladder.
ENGINE_SPECS: list[dict[str, object]] = [
    {
        # v8.2 keeps the v8.1 net and search but is about 15% faster.
        # Controlled recalibration measured 3012.1 +/-5.8 over 9,890 games.
        # This corrected a 3058 result affected by inconsistent hash sizes,
        # a filtered book, and promotion forfeits. See METHODOLOGY section 9.
        "id": "v8.2",
        "exe": CPP_DIR / "sgr_v8_2.exe",
        "net": NETS_DIR / "gen8.nnue",
        "label": 'Sgurr v8.2 "Thearlaich"',
        "tech": "GEN8 NNUE + PACKED TT",
        "rating": 3012,
    },
    {
        # The 2026-08-03 pool gauntlet measured a 20.9 Elo gain over v8.0.
        # Self-play measured a similar 21.2 +/-8.7 gain.
        "id": "v8.1",
        "exe": CPP_DIR / "sgr_v8_1.exe",
        "net": NETS_DIR / "gen8.nnue",
        "label": 'Sgurr v8.1 "Thearlaich"',
        "tech": "GEN8 NNUE + PGO SPEED",
        "rating": 2981,
    },
    {
        "id": "v8.0",
        "exe": CPP_DIR / "sgr_gen8.exe",
        "net": NETS_DIR / "gen8.nnue",
        "label": 'Sgurr v8.0 "Thearlaich"',
        "tech": "GEN8 NNUE",
        "rating": 2960,
    },
    {
        "id": "v7.0",
        "exe": CPP_DIR / "sgr_gen7.exe",
        "net": NETS_DIR / "gen7.nnue",
        "label": 'Sgurr v7.0 "Ghreadaidh"',
        "tech": "GEN7 NNUE (CLEAN REGEN)",
        "rating": 2857,
    },
    {
        "id": "v6.0",
        "exe": CPP_DIR / "sgr_v6_0.exe",
        "net": NETS_DIR / "gen5.nnue",
        "label": 'Sgurr v6.0 "Banachdaich"',
        "tech": "GEN5 NNUE + REFINED SEARCH",
        "rating": 2761,
    },
    {
        "id": "v5.0",
        "exe": CPP_DIR / "sgr_v5_0.exe",
        "net": NETS_DIR / "gen5.nnue",
        "label": 'Sgurr v5.0 "Gillean"',
        "tech": "GEN5 NNUE + RFP SEARCH",
        "rating": 2677,
    },
    {
        "id": "v4.0",
        "exe": CPP_DIR / "sgr_v4_0.exe",
        "net": NETS_DIR / "gen5.nnue",
        "label": 'Sgurr v4.0 "MacKenzie"',
        "tech": "GEN5 NNUE",
        "rating": 2559,
    },
    {
        "id": "v3.1",
        "exe": CPP_DIR / "sgr_v3_1.exe",
        "net": NETS_DIR / "gen3.nnue",
        "label": 'Sgurr v3.1 "Blackpeak"',
        "tech": "GEN3 NNUE + SOFT TIME",
        "rating": 2497,
    },
    {
        "id": "v3.0",
        "exe": CPP_DIR / "sgr_gen3.exe",
        "net": NETS_DIR / "gen3.nnue",
        "label": 'Sgurr v3.0 "Blackpeak"',
        "tech": "GEN3 NNUE",
        "rating": 2545,
    },
    {
        "id": "v2.0",
        "exe": CPP_DIR / "sgr_gen2.exe",
        "net": NETS_DIR / "gen2.nnue",
        "label": 'Sgurr v2.0 "Notches"',
        "tech": "GEN2 NNUE",
        "rating": 2423,
    },
    {
        "id": "v1.0",
        "exe": CPP_DIR / "sgr_gen1.exe",
        "net": NETS_DIR / "gen1.nnue",
        "label": 'Sgurr v1.0 "Fox"',
        "tech": "GEN1 NNUE",
        "rating": 2341,
    },
    {
        # This version intentionally uses hand-crafted evaluation.
        "id": "classical",
        "exe": CPP_DIR / "Ruk_hce.exe",
        "net": None,
        "label": "Sgurr classical",
        "tech": "HAND-CRAFTED EVAL",
        "rating": 2332,
    },
]
_engine_override = os.environ.get("SGURR_ENGINE_EXE") or os.environ.get("SGR_ENGINE_EXE")
if _engine_override:
    _override_path = Path(_engine_override)
    ENGINE_SPECS[0]["exe"] = (
        _override_path if _override_path.is_absolute() else REPO_ROOT / _override_path
    )
for _spec in ENGINE_SPECS:
    _spec["exe"] = Path(_spec["exe"]).resolve()
    if _spec.get("net") is not None:
        _spec["net"] = Path(_spec["net"]).resolve()
    # Build the subtitle from the stored rating to avoid duplicating it.
    _spec["subtitle"] = f"{_spec['tech']} · ~{_spec['rating']}"

DEFAULT_ENGINE_ID = str(ENGINE_SPECS[0]["id"])
# Compatibility aliases for the default engine.
ENGINE_PATH = ENGINE_SPECS[0]["exe"]
ENGINE_NET_PATH = ENGINE_SPECS[0]["net"]
ENGINE_LABEL = str(ENGINE_SPECS[0]["label"])
ENGINE_SUBTITLE = str(ENGINE_SPECS[0]["subtitle"])
DEFAULT_MOVETIME_MS = int(os.environ.get("SGURR_MOVETIME_MS", "700"))
ENGINE_STARTUP_TIMEOUT = float(os.environ.get("SGURR_STARTUP_TIMEOUT", "5.0"))
ENGINE_TIMEOUT_PADDING = float(os.environ.get("SGURR_TIMEOUT_PADDING", "5.0"))
TRACE_MAX_CONCURRENT = max(1, int(os.environ.get("SGURR_TRACE_MAX_CONCURRENT", "2")))
TRACE_SLOTS = threading.BoundedSemaphore(TRACE_MAX_CONCURRENT)
DEMO_MAX_CONCURRENT = bounded_env_int(
    "SGURR_MAX_CONCURRENT_SEARCHES", 1, 1, 4
)
DEMO_COMPUTE_SLOTS = threading.BoundedSemaphore(DEMO_MAX_CONCURRENT)
DEMO_ENGINE_MAX_MOVETIME_MS = bounded_env_int(
    "SGURR_ENGINE_MAX_MOVETIME_MS", 2_000, 100, 10_000
)
DEMO_TRACE_MAX_MOVETIME_MS = bounded_env_int(
    "SGURR_TRACE_MAX_MOVETIME_MS", 5_000, 100, 5_000
)
DEMO_NETWORK_MAX_DEPTH = bounded_env_int(
    "SGURR_NETWORK_MAX_DEPTH", 12, 4, 20
)
DEMO_NETWORK_MAX_NODES = bounded_env_int(
    "SGURR_NETWORK_MAX_NODES", 1_500_000, 10_000, 20_000_000
)
DEMO_NETWORK_TIMEOUT_SECONDS = bounded_env_int(
    "SGURR_NETWORK_TIMEOUT_SECONDS", 15, 5, 60
)
DEMO_ENGINE_REQUESTS_PER_MINUTE = bounded_env_int(
    "SGURR_ENGINE_REQUESTS_PER_MINUTE", 30, 1, 300
)
DEMO_TRACE_REQUESTS_PER_MINUTE = bounded_env_int(
    "SGURR_TRACE_REQUESTS_PER_MINUTE", 6, 1, 60
)
MAX_REQUEST_BYTES = 65_536
EXPECTED_NET_SHA256 = "896eb832d74776a42375e7fa152b4e032fff1cf85ba2e529b420fe2d1b4b74bf"
NNUE_ASSET_ROUTE = f"/api/nnue/gen8/{EXPECTED_NET_SHA256}.nnue"
EXPOSE_ENGINE_PATH = os.environ.get("SGURR_EXPOSE_ENGINE_PATH", "").lower() in {
    "1",
    "true",
    "yes",
}

DEFAULT_ALLOWED_ORIGINS = (
    "http://127.0.0.1:4173",
    "http://localhost:4173",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:5500",
    "http://localhost:5500",
)
DEFAULT_ALLOWED_HOSTS = ("127.0.0.1", "localhost", "testserver")
HOSTNAME_PATTERN = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)

WEB_ASSET_FILES = {
    "music": frozenset(
        {
            "menu-theme.ogg",
            "game-pulse.mp3",
            "game-urgent.mp3",
        }
    ),
    "sounds": frozenset(
        {
            "clock-flag.ogg",
            "clock-warning.ogg",
            "result-draw-neutral.ogg",
            "result-draw.ogg",
            "result-human-explosion.ogg",
            "result-human-splat.ogg",
            "result-human-victory.ogg",
            "result-sgurr-alien.ogg",
            "result-sgurr-burble.ogg",
            "result-sgurr-energy.ogg",
        }
    ),
}


class SlidingWindowLimiter:
    def __init__(self, window_seconds: float = 60.0, max_keys: int = 2_048) -> None:
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, *, now: float | None = None) -> int:
        current = time.monotonic() if now is None else now
        cutoff = current - self.window_seconds
        with self._lock:
            events = self._events.get(key)
            if events is None:
                self._make_room(cutoff)
                events = deque()
                self._events[key] = events
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return max(1, math.ceil(events[0] + self.window_seconds - current))
            events.append(current)
        return 0

    def _make_room(self, cutoff: float) -> None:
        if len(self._events) < self.max_keys:
            return
        stale = [
            key
            for key, events in self._events.items()
            if not events or events[-1] <= cutoff
        ]
        for key in stale:
            self._events.pop(key, None)
        if len(self._events) >= self.max_keys:
            self._events.pop(next(iter(self._events)))


REQUEST_LIMITER = SlidingWindowLimiter()


class RequestBodyLimitMiddleware:
    def __init__(self, app, *, max_bytes: int, enabled: bool) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.enabled = enabled

    async def __call__(self, scope, receive, send) -> None:
        if not self.enabled or scope["type"] != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return

        raw_length = dict(scope.get("headers", ())).get(b"content-length")
        if raw_length is not None:
            try:
                content_length = int(raw_length)
            except ValueError:
                content_length = 0
            if content_length > self.max_bytes:
                await JSONResponse(
                    status_code=413,
                    content={"detail": "Request body is too large"},
                )(scope, receive, send)
                return

        buffered = deque()
        received = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            buffered.append(message)
            if message["type"] != "http.request":
                continue
            received += len(message.get("body", b""))
            if received > self.max_bytes:
                await JSONResponse(
                    status_code=413,
                    content={"detail": "Request body is too large"},
                )(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        async def replay_receive():
            if buffered:
                return buffered.popleft()
            return await receive()

        await self.app(scope, replay_receive, send)


def allowed_origins_from_env(value: str | None) -> list[str]:
    if value is None:
        return list(DEFAULT_ALLOWED_ORIGINS)

    text = value.strip()
    if not text or text.lower() == "none":
        return []

    origins: list[str] = []
    for raw_origin in text.split(","):
        origin = raw_origin.strip().rstrip("/")
        if origin == "*":
            raise RuntimeError(
                "SGURR_ALLOWED_ORIGINS must list explicit origins; '*' is not allowed"
            )
        parsed = urlsplit(origin)
        try:
            parsed.port
        except ValueError as exc:
            raise RuntimeError(
                f"Invalid origin in SGURR_ALLOWED_ORIGINS: {origin}"
            ) from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.hostname is None
            or not HOSTNAME_PATTERN.fullmatch(parsed.hostname)
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise RuntimeError(f"Invalid origin in SGURR_ALLOWED_ORIGINS: {origin}")
        if origin not in origins:
            origins.append(origin)
    return origins


def allowed_hosts_from_env(
    value: str | None,
    *,
    platform_host: str | None = None,
) -> list[str]:
    raw_hosts = DEFAULT_ALLOWED_HOSTS if value is None else value.split(",")
    hosts: list[str] = []
    for raw_host in raw_hosts:
        host = raw_host.strip().lower().rstrip(".")
        if host == "*":
            raise RuntimeError(
                "SGURR_ALLOWED_HOSTS must list explicit hosts; '*' is not allowed"
            )
        if not host or not HOSTNAME_PATTERN.fullmatch(host):
            raise RuntimeError(f"Invalid host in SGURR_ALLOWED_HOSTS: {raw_host.strip()}")
        if host not in hosts:
            hosts.append(host)

    if platform_host:
        host = platform_host.strip().lower().rstrip(".")
        if not HOSTNAME_PATTERN.fullmatch(host):
            raise RuntimeError("RENDER_EXTERNAL_HOSTNAME is invalid")
        if host not in hosts:
            hosts.append(host)

    if not hosts:
        raise RuntimeError("SGURR_ALLOWED_HOSTS must contain at least one host")
    return hosts


ALLOWED_ORIGINS = allowed_origins_from_env(os.environ.get("SGURR_ALLOWED_ORIGINS"))
ALLOWED_HOSTS = allowed_hosts_from_env(
    os.environ.get("SGURR_ALLOWED_HOSTS"),
    platform_host=os.environ.get("RENDER_EXTERNAL_HOSTNAME"),
)

PIECE_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 0,
}

STARTING_COUNTS = {
    chess.PAWN: 8,
    chess.KNIGHT: 2,
    chess.BISHOP: 2,
    chess.ROOK: 2,
    chess.QUEEN: 1,
}

PIECE_NAMES = {
    chess.PAWN: "pawn",
    chess.KNIGHT: "knight",
    chess.BISHOP: "bishop",
    chess.ROOK: "rook",
    chess.QUEEN: "queen",
}


# Each subprocess starts with its first search.
# `engine` remains an alias for the default.
ENGINES: dict[str, dict[str, object]] = {
    str(spec["id"]): {
        "engine": SgurrUciEngine(
            spec["exe"],
            startup_timeout=ENGINE_STARTUP_TIMEOUT,
            net_path=spec.get("net"),
            require_nnue=PUBLIC_DEMO and spec.get("net") is not None,
        ),
        "exe": spec["exe"],
        "net": spec.get("net"),
        "label": spec["label"],
        "subtitle": spec["subtitle"],
        "tech": spec["tech"],
        "rating": spec["rating"],
    }
    for spec in ENGINE_SPECS
}
engine = ENGINES[DEFAULT_ENGINE_ID]["engine"]


def engine_availability(
    engine_id: str,
    entry: dict[str, object],
) -> tuple[bool, str | None, str | None]:
    if PUBLIC_DEMO and engine_id != DEFAULT_ENGINE_ID:
        return (
            False,
            "Available locally; the free demo includes Sgurr v8.2 only.",
            "LOCAL ONLY",
        )
    if not Path(entry["exe"]).is_file():
        return False, "This engine build is not available on the server.", "NOT BUILT"
    net_path = entry.get("net")
    if net_path is not None and not Path(net_path).is_file():
        return False, "This engine network is not available on the server.", "NET MISSING"
    return True, None, None


def engine_entry_for(engine_id: str | None) -> tuple[str, dict[str, object]]:
    if engine_id is not None and engine_id not in ENGINES:
        raise HTTPException(status_code=400, detail="Unknown engine")
    resolved_id = engine_id or DEFAULT_ENGINE_ID
    entry = ENGINES[resolved_id]
    available, reason, _ = engine_availability(resolved_id, entry)
    if not available:
        raise HTTPException(status_code=503, detail=reason or "Engine unavailable")
    return resolved_id, entry


def engine_for(engine_id: str | None):
    return engine_entry_for(engine_id)[1]["engine"]


READINESS_OK = not PUBLIC_DEMO


def validate_public_runtime() -> None:
    global READINESS_OK

    for path in (Path(ENGINE_PATH), TRACE_ENGINE_PATH):
        if not path.is_file() or not os.access(path, os.X_OK):
            raise RuntimeError(f"Executable unavailable: {path}")
    net_path = Path(ENGINE_NET_PATH)
    if not net_path.is_file():
        raise RuntimeError(f"NNUE network unavailable: {net_path}")
    if hashlib.sha256(net_path.read_bytes()).hexdigest() != EXPECTED_NET_SHA256:
        raise RuntimeError("NNUE network checksum mismatch")

    engine.ensure_ready()

    trace_seen = False
    trace_engine = SgurrUciEngine(
        TRACE_ENGINE_PATH,
        startup_timeout=ENGINE_STARTUP_TIMEOUT,
        net_path=net_path,
        require_nnue=True,
    )

    def capture_trace(line: str) -> None:
        nonlocal trace_seen
        if line.startswith("info string trace "):
            trace_seen = True

    try:
        trace_engine.search(
            chess.STARTING_FEN,
            "depth 1 nodes 10000",
            max(ENGINE_STARTUP_TIMEOUT, ENGINE_TIMEOUT_PADDING + 1.0),
            on_line=capture_trace,
        )
    finally:
        trace_engine.close()
    if not trace_seen:
        raise RuntimeError("Trace engine produced no search events")

    READINESS_OK = True


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        if PUBLIC_DEMO:
            validate_public_runtime()
        yield
    except Exception as exc:
        if PUBLIC_DEMO and not READINESS_OK:
            LOGGER.exception("Public demo startup check failed")
            raise RuntimeError("Public demo startup check failed") from exc
        raise
    finally:
        for entry in ENGINES.values():
            entry["engine"].close()


app = FastAPI(title="Sgurr Web Demo API", version="0.1.0", lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
app.add_middleware(
    RequestBodyLimitMiddleware,
    max_bytes=MAX_REQUEST_BYTES,
    enabled=PUBLIC_DEMO,
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = None
    if PUBLIC_DEMO and request.method == "POST":
        limits = {
            "/api/engine-move": ("engine", DEMO_ENGINE_REQUESTS_PER_MINUTE),
            "/api/search-trace": ("analysis", DEMO_TRACE_REQUESTS_PER_MINUTE),
            "/api/search-network": ("analysis", DEMO_TRACE_REQUESTS_PER_MINUTE),
        }
        limit_entry = limits.get(request.url.path)
        if limit_entry is not None:
            limit_group, limit = limit_entry
            retry_after = REQUEST_LIMITER.check(
                limit_group,
                limit,
            )
            if retry_after:
                response = JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit reached; try again shortly"},
                    headers={"Retry-After": str(retry_after)},
                )

    if response is None:
        response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=()",
    )
    return response


class NewGameRequest(BaseModel):
    human_side: Literal["white", "black"] = "white"


UciMoveText = Annotated[str, Field(min_length=4, max_length=5)]


class GameRequest(BaseModel):
    fen: str = Field(min_length=1, max_length=128)
    moves: list[UciMoveText] = Field(default_factory=list, max_length=512)
    start_fen: str | None = Field(default=None, max_length=128)


class LoadFenRequest(BaseModel):
    fen: str = Field(min_length=1, max_length=128)


class PlayerMoveRequest(GameRequest):
    move: UciMoveText


class PremoveSequenceRequest(BaseModel):
    fen: str = Field(min_length=1, max_length=128)
    human_side: Literal["white", "black"]
    premoves: list[UciMoveText] = Field(default_factory=list, max_length=32)


class EngineMoveRequest(GameRequest):
    engine: str | None = Field(default=None, max_length=32)
    movetime_ms: int | None = Field(default=None, ge=50, le=30_000)
    wtime_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    btime_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    winc_ms: int = Field(default=0, ge=0, le=3_600_000)
    binc_ms: int = Field(default=0, ge=0, le=3_600_000)
    movestogo: int = Field(default=120, ge=1, le=240)


class SearchTraceRequest(BaseModel):
    fen: str = Field(min_length=1, max_length=128)
    engine: str | None = Field(default=None, max_length=32)
    movetime_ms: int = Field(default=1_500, ge=100, le=5_000)


class SearchNetworkRequest(BaseModel):
    fen: str = Field(min_length=1, max_length=128)
    depth: int = Field(default=6, ge=4, le=20)


def board_from_fen(fen: str, *, require_valid: bool = True) -> chess.Board:
    try:
        board = chess.Board(fen)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid FEN: {exc}") from exc

    if require_valid:
        error = playable_position_error(board)
        if error is not None:
            raise HTTPException(status_code=400, detail=error)

    return board


def playable_position_error(board: chess.Board) -> str | None:
    if board.is_valid():
        return None

    status = board.status()
    for flag, text in (
        (chess.STATUS_NO_WHITE_KING, "White king missing"),
        (chess.STATUS_NO_BLACK_KING, "Black king missing"),
        (chess.STATUS_TOO_MANY_KINGS, "Too many kings"),
        (chess.STATUS_PAWNS_ON_BACKRANK, "Pawn on a back rank"),
        (chess.STATUS_OPPOSITE_CHECK, "Side not to move is in check"),
        (chess.STATUS_TOO_MANY_CHECKERS, "Impossible check"),
    ):
        if status & flag:
            return text

    return "Position not playable"


def move_from_uci(text: str) -> chess.Move:
    try:
        return chess.Move.from_uci(text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid UCI move: {text}") from exc


def board_from_history(
    fen: str,
    start_fen: str | None,
    moves: list[str],
) -> chess.Board:
    current = board_from_fen(fen)

    # Allow one-off FEN analysis without game history.
    if start_fen is None and not moves:
        return current

    initial_fen = start_fen or chess.Board().fen()
    board = board_from_fen(initial_fen)
    for ply, move_text in enumerate(moves, start=1):
        move = move_from_uci(move_text)
        if move not in board.legal_moves:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid move history at ply {ply}: {move_text}",
            )
        board.push(move)

    if board.fen() != current.fen():
        raise HTTPException(
            status_code=400,
            detail="Current FEN does not match the supplied game history",
        )

    return board


def move_rows(moves: list[str], start_fen: str | None = None) -> list[dict[str, str | int]]:
    try:
        board = chess.Board(start_fen) if start_fen else chess.Board()
    except ValueError:
        board = chess.Board()

    rows: list[dict[str, str | int]] = []

    for move_text in moves:
        try:
            move = chess.Move.from_uci(move_text)
        except ValueError:
            break
        if move not in board.legal_moves:
            break

        row_number = board.fullmove_number
        side = board.turn
        san = board.san(move)

        if not rows or rows[-1]["number"] != row_number:
            rows.append({"number": row_number, "white": "", "black": ""})

        rows[-1]["white" if side == chess.WHITE else "black"] = san
        board.push(move)

    return rows


def material_payload(board: chess.Board) -> dict[str, object]:
    white = 0
    black = 0

    for piece in board.piece_map().values():
        value = PIECE_VALUES[piece.piece_type]
        if piece.color == chess.WHITE:
            white += value
        else:
            black += value

    captured = {"white": [], "black": []}
    for piece_type, starting_count in STARTING_COUNTS.items():
        white_remaining = len(board.pieces(piece_type, chess.WHITE))
        black_remaining = len(board.pieces(piece_type, chess.BLACK))
        captured["white"].extend(
            [PIECE_NAMES[piece_type]] * max(0, starting_count - white_remaining)
        )
        captured["black"].extend(
            [PIECE_NAMES[piece_type]] * max(0, starting_count - black_remaining)
        )

    return {
        "white": white,
        "black": black,
        "diff": white - black,
        "captured": captured,
    }


def outcome_payload(board: chess.Board) -> dict[str, str | bool | None]:
    outcome = board.outcome(claim_draw=True)
    if outcome is None:
        return {
            "game_over": False,
            "result": None,
            "winner": None,
            "reason": None,
        }

    winner = (
        "white"
        if outcome.winner == chess.WHITE
        else "black"
        if outcome.winner == chess.BLACK
        else None
    )
    return {
        "game_over": True,
        "result": outcome.result(),
        "winner": winner,
        "reason": outcome.termination.name.lower(),
    }


def premove_moves(board: chess.Board) -> list[str]:
    premove_board = board.copy(stack=False)
    premove_board.turn = not board.turn
    premove_board.ep_square = None
    return [move.uci() for move in premove_board.generate_pseudo_legal_moves()]


def project_premove_sequence(
    board: chess.Board,
    human_side: Literal["white", "black"],
    premoves: list[str],
) -> tuple[chess.Board, list[str]]:
    projected = board.copy(stack=False)
    colour = chess.WHITE if human_side == "white" else chess.BLACK

    for index, move_text in enumerate(premoves, start=1):
        projected.turn = colour
        projected.ep_square = None
        move = move_from_uci(move_text)
        if not projected.is_pseudo_legal(move):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid premove at position {index}: {move_text}",
            )
        projected.push(move)

    projected.turn = colour
    projected.ep_square = None
    available = [move.uci() for move in projected.generate_pseudo_legal_moves()]
    return projected, available


def pv_payload(board: chess.Board, moves: list[str] | None) -> dict[str, object]:
    """Convert a legal UCI principal variation into display-ready SAN and FENs."""
    variation = board.copy(stack=False)
    san_moves: list[str] = []
    fens = [variation.fen()]

    for move_text in moves or []:
        try:
            move = chess.Move.from_uci(move_text)
        except ValueError:
            break
        if move not in variation.legal_moves:
            break
        san_moves.append(variation.san(move))
        variation.push(move)
        fens.append(variation.fen())

    return {
        "pv_san": san_moves,
        "pv_fens": fens,
    }


def move_san(board: chess.Board, move_text: str) -> str | None:
    try:
        move = chess.Move.from_uci(move_text)
    except ValueError:
        return None
    if move not in board.legal_moves:
        return None
    return board.san(move)


def eval_payload(
    info: UciInfo | None,
    search_turn: chess.Color,
    board: chess.Board | None = None,
) -> dict[str, object] | None:
    if info is None:
        return None

    sign = 1 if search_turn == chess.WHITE else -1
    white_relative = info.score * sign

    if info.score_kind == "mate":
        display = f"M{abs(white_relative)}"
        if white_relative < 0:
            display = f"-{display}"
    else:
        display = f"{white_relative / 100:+.1f}"

    payload: dict[str, object] = {
        "kind": info.score_kind,
        "value": white_relative,
        "display": display,
        "depth": info.depth,
        "nodes": info.nodes,
        "nps": info.nps,
        "hashfull": info.hashfull,
        "time_ms": info.time_ms,
        "pv": info.pv or [],
        "raw": info.raw,
        "perspective": "white",
    }
    if board is not None:
        payload.update(pv_payload(board, info.pv))
    return payload


def state_payload(
    board: chess.Board,
    moves: list[str],
    *,
    start_fen: str | None = None,
    last_move: dict[str, str] | None = None,
    latest_eval: dict[str, object] | None = None,
) -> dict[str, object]:
    start = start_fen or chess.Board().fen()
    return {
        "fen": board.fen(),
        "start_fen": start,
        "turn": "white" if board.turn == chess.WHITE else "black",
        "legal_moves": [move.uci() for move in board.legal_moves],
        "premove_moves": premove_moves(board),
        "move_rows": move_rows(moves, start),
        "moves": moves,
        "last_move": last_move,
        "latest_eval": latest_eval,
        "in_check": board.is_check(),
        "material": material_payload(board),
        "can_mate": {
            "white": not board.has_insufficient_material(chess.WHITE),
            "black": not board.has_insufficient_material(chess.BLACK),
        },
        **outcome_payload(board),
    }


def request_uses_clock(request: EngineMoveRequest) -> bool:
    return request.wtime_ms is not None and request.btime_ms is not None


def demo_movetime_for(request: EngineMoveRequest, board: chess.Board) -> int:
    if request_uses_clock(request):
        active_ms = request.wtime_ms if board.turn == chess.WHITE else request.btime_ms
        inc_ms = request.winc_ms if board.turn == chess.WHITE else request.binc_ms
        requested = max(
            50,
            int((active_ms or 0) / max(1, request.movestogo) + inc_ms / 2),
        )
    else:
        requested = request.movetime_ms or DEFAULT_MOVETIME_MS
    return min(requested, DEMO_ENGINE_MAX_MOVETIME_MS)


def go_args_for(request: EngineMoveRequest, board: chess.Board) -> str:
    if PUBLIC_DEMO:
        return f"movetime {demo_movetime_for(request, board)}"
    if request_uses_clock(request):
        return (
            f"wtime {max(1, request.wtime_ms or 0)} "
            f"btime {max(1, request.btime_ms or 0)} "
            f"winc {request.winc_ms} "
            f"binc {request.binc_ms} "
            f"movestogo {request.movestogo}"
        )

    movetime_ms = request.movetime_ms or DEFAULT_MOVETIME_MS
    return f"movetime {movetime_ms}"


def web_asset_path(category: str, filename: str) -> Path:
    allowed = WEB_ASSET_FILES.get(category)
    if allowed is None or filename not in allowed:
        raise HTTPException(status_code=404, detail="Asset not found")

    path = (ROOT_ASSETS_DIR / category / filename).resolve()
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    return path


def engine_timeout_for(request: EngineMoveRequest, board: chess.Board) -> float:
    if PUBLIC_DEMO:
        return max(
            ENGINE_STARTUP_TIMEOUT,
            demo_movetime_for(request, board) / 1000.0 + ENGINE_TIMEOUT_PADDING,
        )
    if request_uses_clock(request):
        active_ms = request.wtime_ms if board.turn == chess.WHITE else request.btime_ms
        inc_ms = request.winc_ms if board.turn == chess.WHITE else request.binc_ms
        slice_ms = max(50.0, (active_ms or 0) / max(1, request.movestogo) + inc_ms / 2)
        # Bound clock searches so a stalled engine cannot hang the UI.
        return max(ENGINE_STARTUP_TIMEOUT, min(45.0, slice_ms / 1000.0 + ENGINE_TIMEOUT_PADDING))

    movetime_ms = request.movetime_ms or DEFAULT_MOVETIME_MS
    return max(ENGINE_STARTUP_TIMEOUT, movetime_ms / 1000.0 + ENGINE_TIMEOUT_PADDING)


def acquire_demo_compute_slot() -> bool:
    if not PUBLIC_DEMO:
        return False
    if not DEMO_COMPUTE_SLOTS.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Engine busy; try again shortly")
    return True


def release_demo_compute_slot(acquired: bool) -> None:
    if acquired:
        DEMO_COMPUTE_SLOTS.release()


def acquire_trace_slots() -> bool:
    demo_acquired = acquire_demo_compute_slot()
    if TRACE_SLOTS.acquire(blocking=False):
        return demo_acquired
    release_demo_compute_slot(demo_acquired)
    raise HTTPException(status_code=429, detail="Search microscope is busy; try again shortly")


def release_trace_slots(demo_acquired: bool) -> None:
    TRACE_SLOTS.release()
    release_demo_compute_slot(demo_acquired)


@app.get("/health")
def health() -> dict[str, object]:
    engine_exists, _, _ = engine_availability(
        DEFAULT_ENGINE_ID,
        ENGINES[DEFAULT_ENGINE_ID],
    )
    payload: dict[str, object] = {
        "ok": engine_exists and (READINESS_OK or not PUBLIC_DEMO),
        "engine_exists": engine_exists,
        "engine_running": engine.is_running,
        "nnue_loaded": engine.nnue_loaded,
        "engine_label": ENGINE_LABEL,
        "engine_subtitle": ENGINE_SUBTITLE,
        "python_chess": getattr(chess, "__version__", "unknown"),
        "public_demo": PUBLIC_DEMO,
    }
    if EXPOSE_ENGINE_PATH:
        payload["engine_path"] = str(ENGINE_PATH)
    return payload


@app.get("/ready", include_in_schema=False, response_model=None)
def ready():
    payload = {"ok": READINESS_OK}
    if READINESS_OK:
        return payload
    return JSONResponse(status_code=503, content=payload)


@app.get("/api/capabilities")
def capabilities() -> dict[str, object]:
    return {
        "public_demo": PUBLIC_DEMO,
        "self_play": not PUBLIC_DEMO,
        "limits": {
            "engine_movetime_ms": (
                DEMO_ENGINE_MAX_MOVETIME_MS if PUBLIC_DEMO else 30_000
            ),
            "search_trace_movetime_ms": (
                DEMO_TRACE_MAX_MOVETIME_MS if PUBLIC_DEMO else 5_000
            ),
            "search_network_depth": (
                DEMO_NETWORK_MAX_DEPTH if PUBLIC_DEMO else 20
            ),
        },
    }


@app.get("/api/engines")
def list_engines() -> dict[str, object]:
    engines = []
    for engine_id, entry in ENGINES.items():
        available, reason, badge = engine_availability(engine_id, entry)
        engines.append(
            {
                "id": engine_id,
                "label": entry["label"],
                "subtitle": entry["subtitle"],
                "tech": entry["tech"],
                "rating": entry["rating"],
                "available": available,
                "unavailable_reason": reason,
                "unavailable_badge": badge,
            }
        )
    return {
        "default": DEFAULT_ENGINE_ID,
        "public_demo": PUBLIC_DEMO,
        "engines": engines,
    }


@app.get("/assets/music/{filename}", include_in_schema=False)
def web_music_asset(filename: str) -> FileResponse:
    return FileResponse(
        web_asset_path("music", filename),
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/assets/sounds/{filename}", include_in_schema=False)
def web_sound_asset(filename: str) -> FileResponse:
    return FileResponse(
        web_asset_path("sounds", filename),
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get(NNUE_ASSET_ROUTE, include_in_schema=False)
def nnue_network_asset() -> FileResponse:
    net_path = Path(ENGINE_NET_PATH)
    try:
        valid = (
            net_path.is_file()
            and hashlib.sha256(net_path.read_bytes()).hexdigest() == EXPECTED_NET_SHA256
        )
    except OSError:
        valid = False
    if not valid:
        raise HTTPException(status_code=503, detail="NNUE Lab unavailable")
    return FileResponse(
        net_path,
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "ETag": f'"{EXPECTED_NET_SHA256}"',
        },
    )


@app.post("/api/new")
def new_game(_: NewGameRequest) -> dict[str, object]:
    if not PUBLIC_DEMO:
        engine.mark_new_game()
    board = chess.Board()
    return state_payload(board, [], start_fen=board.fen())


@app.post("/api/load-fen")
def load_fen(request: LoadFenRequest) -> dict[str, object]:
    board = board_from_fen(request.fen.strip())
    if not PUBLIC_DEMO:
        engine.mark_new_game()
    return state_payload(board, [], start_fen=board.fen())


@app.post("/api/player-move")
def player_move(request: PlayerMoveRequest) -> dict[str, object]:
    board = board_from_history(request.fen, request.start_fen, request.moves)
    move = move_from_uci(request.move)

    if move not in board.legal_moves:
        raise HTTPException(status_code=400, detail=f"Illegal move: {request.move}")

    san = board.san(move)
    board.push(move)
    moves = [*request.moves, move.uci()]
    return state_payload(
        board,
        moves,
        start_fen=request.start_fen,
        last_move={"uci": move.uci(), "san": san, "by": "player"},
    )


@app.post("/api/premove-sequence")
def premove_sequence(request: PremoveSequenceRequest) -> dict[str, object]:
    board = board_from_fen(request.fen)
    projected, available = project_premove_sequence(
        board,
        request.human_side,
        request.premoves,
    )
    return {
        "projected_fen": projected.fen(),
        "premove_moves": available,
    }


@app.post("/api/engine-move")
def engine_move(request: EngineMoveRequest) -> dict[str, object]:
    board = board_from_history(request.fen, request.start_fen, request.moves)
    if board.is_game_over(claim_draw=True):
        return state_payload(board, request.moves, start_fen=request.start_fen)

    search_turn = board.turn
    selected_engine = engine_for(request.engine)
    demo_slot = acquire_demo_compute_slot()

    try:
        result = selected_engine.search(
            board.fen(),
            go_args_for(request, board),
            engine_timeout_for(request, board),
        )
    except EngineStartupError as exc:
        LOGGER.warning("Engine startup failed: %s", exc)
        detail = "Engine unavailable" if PUBLIC_DEMO else str(exc)
        raise HTTPException(status_code=503, detail=detail) from exc
    except EngineTimeoutError as exc:
        LOGGER.warning("Engine search timed out: %s", exc)
        detail = "Engine search timed out" if PUBLIC_DEMO else str(exc)
        raise HTTPException(status_code=504, detail=detail) from exc
    except EngineCrashedError as exc:
        LOGGER.warning("Engine stopped unexpectedly: %s", exc)
        detail = "Engine stopped unexpectedly" if PUBLIC_DEMO else str(exc)
        raise HTTPException(status_code=502, detail=detail) from exc
    finally:
        release_demo_compute_slot(demo_slot)

    if result.bestmove == "0000":
        return state_payload(
            board,
            request.moves,
            start_fen=request.start_fen,
            latest_eval=eval_payload(result.info, search_turn),
        )

    move = move_from_uci(result.bestmove)
    if move not in board.legal_moves:
        raise HTTPException(
            status_code=502,
            detail=f"Sgurr returned illegal move {result.bestmove} for {request.fen}",
        )

    san = board.san(move)
    board.push(move)
    moves = [*request.moves, move.uci()]
    return state_payload(
        board,
        moves,
        start_fen=request.start_fen,
        last_move={"uci": move.uci(), "san": san, "by": "engine"},
        latest_eval=eval_payload(result.info, search_turn),
    )


@app.post("/api/search-trace")
def search_trace(request: SearchTraceRequest) -> StreamingResponse:
    """Stream completed iterative-deepening passes from an isolated engine.

    The normal game process is deliberately not reused: a visitor leaving the
    microscope open must never delay a move in the playable site. The stream
    contains one small NDJSON object per completed depth, not per search node.
    """
    board = board_from_fen(request.fen.strip())
    search_turn = board.turn
    engine_id, entry = engine_entry_for(request.engine)
    engine_path = Path(entry["exe"])

    if not engine_path.is_file():
        raise HTTPException(status_code=503, detail=f"Engine unavailable: {entry['label']}")
    demo_slot = acquire_trace_slots()

    event_queue: queue.Queue[tuple[str, object]] = queue.Queue()
    trace_engine = SgurrUciEngine(
        engine_path,
        startup_timeout=ENGINE_STARTUP_TIMEOUT,
        net_path=entry.get("net"),
        require_nnue=PUBLIC_DEMO and entry.get("net") is not None,
    )
    movetime_ms = (
        min(request.movetime_ms, DEMO_TRACE_MAX_MOVETIME_MS)
        if PUBLIC_DEMO
        else request.movetime_ms
    )

    def on_info(info: UciInfo) -> None:
        event_queue.put(("iteration", info))

    def run_search() -> None:
        try:
            result = trace_engine.search(
                board.fen(),
                f"movetime {movetime_ms}",
                max(
                    ENGINE_STARTUP_TIMEOUT,
                    movetime_ms / 1000.0 + ENGINE_TIMEOUT_PADDING,
                ),
                on_info=on_info,
            )
            event_queue.put(("complete", result))
        except (EngineStartupError, EngineTimeoutError, EngineCrashedError) as exc:
            LOGGER.warning("Search trace stopped: %s", exc)
            detail = "Search trace stopped" if PUBLIC_DEMO else str(exc)
            event_queue.put(("error", detail))
        except Exception:
            event_queue.put(("error", "Search trace failed unexpectedly"))
        finally:
            try:
                trace_engine.close()
            finally:
                release_trace_slots(demo_slot)

    worker = threading.Thread(
        target=run_search,
        name="sgurr-search-trace",
        daemon=True,
    )
    try:
        worker.start()
    except Exception:
        trace_engine.close()
        release_trace_slots(demo_slot)
        raise

    def encode(payload: dict[str, object]) -> bytes:
        return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")

    def stream():
        completed = False
        try:
            yield encode(
                {
                    "type": "started",
                    "engine": engine_id,
                    "label": entry["label"],
                    "fen": board.fen(),
                    "perspective": "white",
                    "movetime_ms": movetime_ms,
                }
            )

            while True:
                event_type, value = event_queue.get()

                if event_type == "iteration":
                    payload = eval_payload(value, search_turn, board)
                    if payload is not None:
                        yield encode({"type": "iteration", **payload})
                    continue

                if event_type == "complete":
                    yield encode(
                        {
                            "type": "complete",
                            "bestmove": value.bestmove,
                            "bestmove_san": move_san(board, value.bestmove),
                            "final": eval_payload(value.info, search_turn, board),
                        }
                    )
                else:
                    yield encode({"type": "error", "detail": str(value)})
                completed = True
                break
        finally:
            if not completed:
                trace_engine.cancel()

    return StreamingResponse(
        stream(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/search-network")
def search_network(request: SearchNetworkRequest) -> StreamingResponse:
    """Stream bounded samples from every iteration through the target depth."""
    board = board_from_fen(request.fen.strip())
    if PUBLIC_DEMO and request.depth > DEMO_NETWORK_MAX_DEPTH:
        raise HTTPException(
            status_code=400,
            detail=f"Search depth is limited to {DEMO_NETWORK_MAX_DEPTH} on the free demo",
        )
    if not TRACE_ENGINE_PATH.is_file():
        raise HTTPException(
            status_code=503,
            detail="Trace engine unavailable; build it with sgurr_cpp/build.sh -t",
        )
    demo_slot = acquire_trace_slots()

    event_queue: queue.Queue[tuple[str, object]] = queue.Queue()
    trace_engine = SgurrUciEngine(
        TRACE_ENGINE_PATH,
        startup_timeout=ENGINE_STARTUP_TIMEOUT,
        net_path=ENGINE_SPECS[0].get("net"),
        require_nnue=PUBLIC_DEMO,
    )
    prefix = "info string trace "

    def on_line(line: str) -> None:
        if not line.startswith(prefix):
            return
        try:
            event_queue.put(("trace", json.loads(line[len(prefix):])))
        except json.JSONDecodeError:
            event_queue.put(("error", "Trace engine returned malformed data"))

    def on_info(info: UciInfo) -> None:
        if info.depth is None:
            return
        event_queue.put(
            (
                "progress",
                {
                    "depth": info.depth,
                    "nodes": info.nodes,
                    "time_ms": info.time_ms,
                },
            )
        )

    def run_search() -> None:
        try:
            # Give deep searches time to finish but cap stalled processes.
            timeout_seconds = (
                float(DEMO_NETWORK_TIMEOUT_SECONDS)
                if PUBLIC_DEMO
                else min(
                    300.0,
                    max(15.0, 15.0 * (2.0 ** (max(0, request.depth - 12) / 2.0))),
                )
            )
            go_args = f"depth {request.depth}"
            if PUBLIC_DEMO:
                go_args += f" nodes {DEMO_NETWORK_MAX_NODES}"
            result = trace_engine.search(
                board.fen(),
                go_args,
                max(ENGINE_STARTUP_TIMEOUT, timeout_seconds),
                on_info=on_info,
                on_line=on_line,
            )
            event_queue.put(("complete", result))
        except (EngineStartupError, EngineTimeoutError, EngineCrashedError) as exc:
            LOGGER.warning("Search network stopped: %s", exc)
            detail = "Search network stopped" if PUBLIC_DEMO else str(exc)
            event_queue.put(("error", detail))
        except Exception:
            event_queue.put(("error", "Search network trace failed unexpectedly"))
        finally:
            try:
                trace_engine.close()
            finally:
                release_trace_slots(demo_slot)

    worker = threading.Thread(
        target=run_search,
        name="sgurr-search-network",
        daemon=True,
    )
    try:
        worker.start()
    except Exception:
        trace_engine.close()
        release_trace_slots(demo_slot)
        raise

    def encode(payload: dict[str, object]) -> bytes:
        return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")

    def stream():
        yield encode({"type": "started", "depth": request.depth, "fen": board.fen()})
        batch: list[bytes] = []
        batch_started = 0.0
        completed = False
        try:
            while True:
                timeout = max(0.0, 0.016 - (time.monotonic() - batch_started)) if batch else None
                try:
                    event_type, value = event_queue.get(timeout=timeout)
                except queue.Empty:
                    yield b"".join(batch)
                    batch.clear()
                    batch_started = 0.0
                    continue
                if event_type == "trace":
                    if not batch:
                        batch_started = time.monotonic()
                    batch.append(encode({"type": "trace", "event": value}))
                    if len(batch) >= 24:
                        yield b"".join(batch)
                        batch.clear()
                        batch_started = 0.0
                    continue
                if event_type == "progress":
                    if batch:
                        yield b"".join(batch)
                        batch.clear()
                        batch_started = 0.0
                    yield encode({"type": "progress", **value})
                    continue
                if batch:
                    yield b"".join(batch)
                    batch.clear()
                    batch_started = 0.0
                if event_type == "complete":
                    achieved_depth = value.info.depth if value.info is not None else None
                    yield encode(
                        {
                            "type": "complete",
                            "bestmove": value.bestmove,
                            "events": "bounded",
                            "target_depth": request.depth,
                            "depth": achieved_depth,
                            "nodes": value.info.nodes if value.info is not None else None,
                            "limited": (
                                PUBLIC_DEMO
                                and achieved_depth is not None
                                and achieved_depth < request.depth
                            ),
                        }
                    )
                else:
                    yield encode({"type": "error", "detail": str(value)})
                completed = True
                break
        finally:
            if not completed:
                trace_engine.cancel()

    return StreamingResponse(
        stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


# Register static mounts last so API, health, and allowlisted audio routes win.
if FRONTEND_ASSETS_DIR.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_ASSETS_DIR),
        name="frontend-assets",
    )
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
