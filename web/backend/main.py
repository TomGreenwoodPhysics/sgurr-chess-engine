from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import chess
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, StreamingResponse
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
except ImportError:  # Allows `uvicorn main:app` from web/backend.
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
# --- selectable opponents -------------------------------------------------
# The demo offers several engines; the frontend lists them via /api/engines and
# names one per move (falling back to the first, the default). SGURR_ENGINE_EXE
# still overrides the default's binary, preserving the old single-engine setup.
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
# Every canonical release, newest first (index 0 is the default, and what
# SGURR_ENGINE_EXE overrides). Ratings are the pool-2026-07-B Ordo solve from
# benchmarks/ledger.md -- CCRL-Blitz-ANCHORED ESTIMATES on one consistent
# scale, not official CCRL ratings, hence the tilde.
#
# Every number here was solved from games -- as of 2026-08-05 there is no
# longer an inferred figure on this ladder.
# Note v3.1 rates BELOW v3.0: it was a search-only release whose flat soft
# time limit lost at the pool TC. That is real, measured, and left visible.
# `rating` is the structured form of the number the subtitle carries; the
# subtitle itself is derived from `tech` + `rating` below so the figure lives
# in exactly one place. The frontend uses `rating` to sort and display the
# ladder, so a version added here shows up in the opponent picker for free.
ENGINE_SPECS: list[dict[str, object]] = [
    {
        # v8.2 is v8.1 with a packed TT entry and a lazy move picker: same net,
        # same search, same moves, ~15% faster.
        #
        # Measured 2026-08-05: 3058.5 +/-6.5 over an 11,144-game pool gauntlet,
        # +31.5 vs v8.1 in the same Ordo solve.
        #
        # This page carried 3041 for a day, marked INFERRED: v8.1's 3026.7 plus
        # 70*log2(1.1543) = +14.5 for a +15.43% NPS gain. The games say +31.5.
        # The rule under-predicted by 17 Elo, and the label is the only reason
        # that is a footnote rather than a wrong number shipped as a fact.
        #
        # Corrected 2026-08-10: 3058 -> 3012. The engine did not change, the
        # measurement did. The old calibration left Hash unset (engines ran at
        # 8-128 MB where CCRL requires one shared value), used a book filtered
        # by Sgurr's own eval, and included two engines forfeiting ~20% of
        # their games on an illegal uppercase promotion. Re-measured against
        # five families under controlled conditions: 3012.1 +/-5.8 over 9,890
        # games, systematic ~+/-25. See METHODOLOGY 9.
        #
        # Every rating below is still the pool-2026-07-B solve and therefore
        # sits ~45 Elo high in absolute terms. The ladder's ORDER and its
        # version-to-version gaps are unaffected, which is what this list uses
        # them for; re-measuring the older versions is owed.
        "id": "v8.2",
        "exe": CPP_DIR / "sgr_v8_2.exe",
        "net": NETS_DIR / "gen8.nnue",
        "label": 'Sgurr v8.2 "Thearlaich"',
        "tech": "GEN8 NNUE + PACKED TT",
        "rating": 3012,
    },
    {
        # Measured 2026-08-03: 3026.7 +/-11.1 over a 3,456-game pool gauntlet,
        # +20.9 vs v8.0 in the same Ordo solve, against +21.2 +/-8.7 in
        # self-play. It held the 3006 floor until then rather than displaying
        # the prediction, since an unmeasured number on a public page is what
        # this project's methodology exists to prevent.
        "id": "v8.1",
        "exe": CPP_DIR / "sgr_v8_1.exe",
        "net": NETS_DIR / "gen8.nnue",
        "label": 'Sgurr v8.1 "Thearlaich"',
        "tech": "GEN8 NNUE + PGO SPEED",
        "rating": 3027,
    },
    {
        "id": "v8.0",
        "exe": CPP_DIR / "sgr_gen8.exe",
        "net": NETS_DIR / "gen8.nnue",
        "label": 'Sgurr v8.0 "Thearlaich"',
        "tech": "GEN8 NNUE",
        "rating": 3006,
    },
    {
        "id": "v7.0",
        "exe": CPP_DIR / "sgr_gen7.exe",
        "net": NETS_DIR / "gen7.nnue",
        "label": 'Sgurr v7.0 "Ghreadaidh"',
        "tech": "GEN7 NNUE (CLEAN REGEN)",
        "rating": 2903,
    },
    {
        "id": "v6.0",
        "exe": CPP_DIR / "sgr_v6_0.exe",
        "net": NETS_DIR / "gen5.nnue",
        "label": 'Sgurr v6.0 "Banachdaich"',
        "tech": "GEN5 NNUE + REFINED SEARCH",
        "rating": 2807,
    },
    {
        "id": "v5.0",
        "exe": CPP_DIR / "sgr_v5_0.exe",
        "net": NETS_DIR / "gen5.nnue",
        "label": 'Sgurr v5.0 "Gillean"',
        "tech": "GEN5 NNUE + RFP SEARCH",
        "rating": 2724,
    },
    {
        "id": "v4.0",
        "exe": CPP_DIR / "sgr_v4_0.exe",
        "net": NETS_DIR / "gen5.nnue",
        "label": 'Sgurr v4.0 "MacKenzie"',
        "tech": "GEN5 NNUE",
        "rating": 2604,
    },
    {
        "id": "v3.1",
        "exe": CPP_DIR / "sgr_v3_1.exe",
        "net": NETS_DIR / "gen3.nnue",
        "label": 'Sgurr v3.1 "Blackpeak"',
        "tech": "GEN3 NNUE + SOFT TIME",
        "rating": 2540,
    },
    {
        "id": "v3.0",
        "exe": CPP_DIR / "sgr_gen3.exe",
        "net": NETS_DIR / "gen3.nnue",
        "label": 'Sgurr v3.0 "Blackpeak"',
        "tech": "GEN3 NNUE",
        "rating": 2589,
    },
    {
        "id": "v2.0",
        "exe": CPP_DIR / "sgr_gen2.exe",
        "net": NETS_DIR / "gen2.nnue",
        "label": 'Sgurr v2.0 "Notches"',
        "tech": "GEN2 NNUE",
        "rating": 2468,
    },
    {
        "id": "v1.0",
        "exe": CPP_DIR / "sgr_gen1.exe",
        "net": NETS_DIR / "gen1.nnue",
        "label": 'Sgurr v1.0 "Fox"',
        "tech": "GEN1 NNUE",
        "rating": 2385,
    },
    {
        # No net by design: this IS the hand-crafted eval.
        "id": "classical",
        "exe": CPP_DIR / "Ruk_hce.exe",
        "net": None,
        "label": "Sgurr classical",
        "tech": "HAND-CRAFTED EVAL",
        "rating": 2376,
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
    # Single source of truth for the rating: the displayed subtitle is built
    # from it rather than repeating the number as free text.
    _spec["subtitle"] = f"{_spec['tech']} · ~{_spec['rating']}"

DEFAULT_ENGINE_ID = str(ENGINE_SPECS[0]["id"])
# Back-compat aliases: /health and the engine-path exposure describe the default.
ENGINE_PATH = ENGINE_SPECS[0]["exe"]
ENGINE_LABEL = str(ENGINE_SPECS[0]["label"])
ENGINE_SUBTITLE = str(ENGINE_SPECS[0]["subtitle"])
DEFAULT_MOVETIME_MS = int(os.environ.get("SGURR_MOVETIME_MS", "700"))
ENGINE_STARTUP_TIMEOUT = float(os.environ.get("SGURR_STARTUP_TIMEOUT", "5.0"))
ENGINE_TIMEOUT_PADDING = float(os.environ.get("SGURR_TIMEOUT_PADDING", "5.0"))
TRACE_MAX_CONCURRENT = max(1, int(os.environ.get("SGURR_TRACE_MAX_CONCURRENT", "2")))
TRACE_SLOTS = threading.BoundedSemaphore(TRACE_MAX_CONCURRENT)
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


def allowed_hosts_from_env(value: str | None) -> list[str]:
    if value is None:
        return list(DEFAULT_ALLOWED_HOSTS)

    hosts: list[str] = []
    for raw_host in value.split(","):
        host = raw_host.strip().lower().rstrip(".")
        if host == "*":
            raise RuntimeError(
                "SGURR_ALLOWED_HOSTS must list explicit hosts; '*' is not allowed"
            )
        if not host or not HOSTNAME_PATTERN.fullmatch(host):
            raise RuntimeError(f"Invalid host in SGURR_ALLOWED_HOSTS: {raw_host.strip()}")
        if host not in hosts:
            hosts.append(host)

    if not hosts:
        raise RuntimeError("SGURR_ALLOWED_HOSTS must contain at least one host")
    return hosts


ALLOWED_ORIGINS = allowed_origins_from_env(os.environ.get("SGURR_ALLOWED_ORIGINS"))
ALLOWED_HOSTS = allowed_hosts_from_env(os.environ.get("SGURR_ALLOWED_HOSTS"))

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


# One UCI engine per spec (lazy: each subprocess starts on its first search).
# `engine` stays an alias for the default so existing code paths keep working.
ENGINES: dict[str, dict[str, object]] = {
    str(spec["id"]): {
        "engine": SgurrUciEngine(
            spec["exe"],
            startup_timeout=ENGINE_STARTUP_TIMEOUT,
            net_path=spec.get("net"),
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


def engine_for(engine_id: str | None):
    entry = ENGINES.get(engine_id or DEFAULT_ENGINE_ID) or ENGINES[DEFAULT_ENGINE_ID]
    return entry["engine"]


def engine_entry_for(engine_id: str | None) -> tuple[str, dict[str, object]]:
    resolved_id = engine_id if engine_id in ENGINES else DEFAULT_ENGINE_ID
    return resolved_id, ENGINES[resolved_id]


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        yield
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


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
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


class GameRequest(BaseModel):
    fen: str
    moves: list[str] = Field(default_factory=list)
    start_fen: str | None = None


class LoadFenRequest(BaseModel):
    fen: str


class PlayerMoveRequest(GameRequest):
    move: str


class PremoveSequenceRequest(BaseModel):
    fen: str
    human_side: Literal["white", "black"]
    premoves: list[str] = Field(default_factory=list, max_length=32)


class EngineMoveRequest(GameRequest):
    engine: str | None = Field(default=None, max_length=32)
    movetime_ms: int | None = Field(default=None, ge=50, le=30_000)
    wtime_ms: int | None = Field(default=None, ge=0)
    btime_ms: int | None = Field(default=None, ge=0)
    winc_ms: int = Field(default=0, ge=0)
    binc_ms: int = Field(default=0, ge=0)
    movestogo: int = Field(default=120, ge=1, le=240)


class SearchTraceRequest(BaseModel):
    fen: str
    engine: str | None = Field(default=None, max_length=32)
    movetime_ms: int = Field(default=1_500, ge=100, le=5_000)


class SearchNetworkRequest(BaseModel):
    fen: str
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

    # Keep the engine-move endpoint useful for one-off FEN analysis when no
    # game history was supplied. Web games always include start_fen and moves.
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


def eval_payload(info: UciInfo | None, search_turn: chess.Color) -> dict[str, object] | None:
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

    return {
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


def go_args_for(request: EngineMoveRequest) -> str:
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
    if request_uses_clock(request):
        active_ms = request.wtime_ms if board.turn == chess.WHITE else request.btime_ms
        inc_ms = request.winc_ms if board.turn == chess.WHITE else request.binc_ms
        slice_ms = max(50.0, (active_ms or 0) / max(1, request.movestogo) + inc_ms / 2)
        # UCI clock searches can be longer than fixed demo searches, but keep
        # the web request bounded so a wedged engine does not hang the UI.
        return max(ENGINE_STARTUP_TIMEOUT, min(45.0, slice_ms / 1000.0 + ENGINE_TIMEOUT_PADDING))

    movetime_ms = request.movetime_ms or DEFAULT_MOVETIME_MS
    return max(ENGINE_STARTUP_TIMEOUT, movetime_ms / 1000.0 + ENGINE_TIMEOUT_PADDING)


@app.get("/health")
def health() -> dict[str, object]:
    payload: dict[str, object] = {
        "ok": True,
        "engine_exists": ENGINE_PATH.exists(),
        "engine_running": engine.is_running,
        "engine_label": ENGINE_LABEL,
        "engine_subtitle": ENGINE_SUBTITLE,
        "python_chess": getattr(chess, "__version__", "unknown"),
    }
    if EXPOSE_ENGINE_PATH:
        payload["engine_path"] = str(ENGINE_PATH)
    return payload


@app.get("/api/engines")
def list_engines() -> dict[str, object]:
    return {
        "default": DEFAULT_ENGINE_ID,
        "engines": [
            {
                "id": engine_id,
                "label": entry["label"],
                "subtitle": entry["subtitle"],
                "tech": entry["tech"],
                "rating": entry["rating"],
                "available": Path(entry["exe"]).exists(),
            }
            for engine_id, entry in ENGINES.items()
        ],
    }


@app.get("/assets/{category}/{filename}", include_in_schema=False)
def web_asset(category: str, filename: str) -> FileResponse:
    return FileResponse(
        web_asset_path(category, filename),
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.post("/api/new")
def new_game(_: NewGameRequest) -> dict[str, object]:
    engine.mark_new_game()
    board = chess.Board()
    return state_payload(board, [], start_fen=board.fen())


@app.post("/api/load-fen")
def load_fen(request: LoadFenRequest) -> dict[str, object]:
    board = board_from_fen(request.fen.strip())
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

    try:
        result = engine_for(request.engine).search(
            board.fen(),
            go_args_for(request),
            engine_timeout_for(request, board),
        )
    except EngineStartupError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EngineTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except EngineCrashedError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

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
    if not TRACE_SLOTS.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Search microscope is busy; try again shortly")

    event_queue: queue.Queue[tuple[str, object]] = queue.Queue()
    trace_engine = SgurrUciEngine(
        engine_path,
        startup_timeout=ENGINE_STARTUP_TIMEOUT,
        net_path=entry.get("net"),
    )

    def on_info(info: UciInfo) -> None:
        event_queue.put(("iteration", info))

    def run_search() -> None:
        try:
            result = trace_engine.search(
                board.fen(),
                f"movetime {request.movetime_ms}",
                max(
                    ENGINE_STARTUP_TIMEOUT,
                    request.movetime_ms / 1000.0 + ENGINE_TIMEOUT_PADDING,
                ),
                on_info=on_info,
            )
            event_queue.put(("complete", result))
        except (EngineStartupError, EngineTimeoutError, EngineCrashedError) as exc:
            event_queue.put(("error", str(exc)))
        except Exception:
            event_queue.put(("error", "Search trace failed unexpectedly"))
        finally:
            try:
                trace_engine.close()
            finally:
                TRACE_SLOTS.release()

    worker = threading.Thread(
        target=run_search,
        name="sgurr-search-trace",
        daemon=True,
    )
    worker.start()

    def encode(payload: dict[str, object]) -> bytes:
        return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")

    def stream():
        yield encode(
            {
                "type": "started",
                "engine": engine_id,
                "label": entry["label"],
                "fen": board.fen(),
                "perspective": "white",
            }
        )

        while True:
            event_type, value = event_queue.get()

            if event_type == "iteration":
                payload = eval_payload(value, search_turn)
                if payload is not None:
                    yield encode({"type": "iteration", **payload})
                continue

            if event_type == "complete":
                yield encode(
                    {
                        "type": "complete",
                        "bestmove": value.bestmove,
                        "final": eval_payload(value.info, search_turn),
                    }
                )
            else:
                yield encode({"type": "error", "detail": str(value)})
            break

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
    if not TRACE_ENGINE_PATH.is_file():
        raise HTTPException(
            status_code=503,
            detail="Trace engine unavailable; build it with sgurr_cpp/build.sh -t",
        )
    if not TRACE_SLOTS.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Search microscope is busy; try again shortly")

    event_queue: queue.Queue[tuple[str, object]] = queue.Queue()
    trace_engine = SgurrUciEngine(
        TRACE_ENGINE_PATH,
        startup_timeout=ENGINE_STARTUP_TIMEOUT,
        net_path=ENGINE_SPECS[0].get("net"),
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
            # Strict deep searches grow exponentially and intentionally have no
            # movetime cap. Give the advanced presets room to finish while
            # retaining a hard ceiling for a stalled diagnostic process.
            timeout_seconds = min(
                300.0,
                max(15.0, 15.0 * (2.0 ** (max(0, request.depth - 12) / 2.0))),
            )
            result = trace_engine.search(
                board.fen(),
                f"depth {request.depth}",
                max(ENGINE_STARTUP_TIMEOUT, timeout_seconds),
                on_info=on_info,
                on_line=on_line,
            )
            event_queue.put(("complete", result))
        except (EngineStartupError, EngineTimeoutError, EngineCrashedError) as exc:
            event_queue.put(("error", str(exc)))
        except Exception:
            event_queue.put(("error", "Search network trace failed unexpectedly"))
        finally:
            try:
                trace_engine.close()
            finally:
                TRACE_SLOTS.release()

    threading.Thread(
        target=run_search,
        name="sgurr-search-network",
        daemon=True,
    ).start()

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
                    yield encode(
                        {
                            "type": "complete",
                            "bestmove": value.bestmove,
                            "events": "bounded",
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
