from __future__ import annotations

import ctypes
import json
import os
import queue
import random
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import chess
import chess.engine
import chess.pgn
import pygame


PROJECT_DIR = Path(__file__).resolve().parents[1]

# The compiled C++ UCI engine executable. Needs to be an NNUE-capable build
# (one that honours SGR_EVALFILE). Override with the SGR_ENGINE_EXE
# environment variable. All C++ opponent modes share this one binary; the
# net (or the forced-HCE fallback) is chosen per opponent via SGR_EVALFILE.
ENGINE_EXE_PATH = Path(
    os.environ.get("SGR_ENGINE_EXE", str(PROJECT_DIR / "sgurr_cpp" / "sgr_v3_1.exe"))
)

# Trained NNUE networks the engine loads in NNUE mode (chosen per opponent via
# SGR_EVALFILE). Ratings shown in the UI are the measured CCRL-Blitz-anchored
# Ordo estimates from benchmarks/ledger.md (gen3 added 2026-07-06); update them
# there and here together.
GEN1_NET_PATH = PROJECT_DIR / "nets" / "gen1.nnue"
GEN2_NET_PATH = PROJECT_DIR / "nets" / "gen2.nnue"
GEN3_NET_PATH = PROJECT_DIR / "nets" / "gen3.nnue"

# Deliberately missing path: pointing SGR_EVALFILE here forces the engine's
# hand-crafted-eval fallback even if a default net is baked into the binary.
NO_NET_PATH = PROJECT_DIR / "nets" / "__no_net__.nnue"

SOUND_DIR = PROJECT_DIR / "assets" / "sounds"
ANALYSIS_DIR = PROJECT_DIR / "analysis_games"

ENGINE_TIMEOUT = 20.0

for candidate in (PROJECT_DIR, PROJECT_DIR.parent):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)


EVAL_PANEL_WIDTH = 72
BOARD_SIZE = 720
SIDE_PANEL_WIDTH = 360
PLAYER_BAR_HEIGHT = 44
BOARD_TOP = PLAYER_BAR_HEIGHT
WINDOW_WIDTH = EVAL_PANEL_WIDTH + BOARD_SIZE + SIDE_PANEL_WIDTH
WINDOW_HEIGHT = BOARD_SIZE + PLAYER_BAR_HEIGHT * 2
SQUARE_SIZE = BOARD_SIZE // 8
TARGET_FPS = 240
DISPLAY_DEPTH = 32
PIECE_SUPERSAMPLE = 2
TEXT_INPUT_REPEAT_DELAY_MS = 350
TEXT_INPUT_REPEAT_INTERVAL_MS = 35
SHARP_UPSCALE_THRESHOLD = 1.15

SETTINGS_PATH = Path(os.environ.get(
    "SGURR_GUI_SETTINGS",
    str(Path(os.environ.get("APPDATA", Path.home())) / "Sgurr" / "gui_settings.json"),
))
ANIMATION_MODES = ("Off", "Reduced", "Full")
MOVE_SOUND_NAMES = {"move_self", "move_opponent", "capture", "castle", "promote"}
ALERT_SOUND_NAMES = {"check", "illegal", "game_start", "game_end", "victory", "defeat", "draw"}


@dataclass(frozen=True)
class TimeControl:
    key: str
    label: str
    base_seconds: float
    increment_seconds: float


TIME_CONTROLS = (
    TimeControl("bullet_1_0", "Bullet 1+0", 60.0, 0.0),
    TimeControl("bullet_2_1", "Bullet 2+1", 120.0, 1.0),
    TimeControl("blitz_3_0", "Blitz 3+0", 180.0, 0.0),
    TimeControl("blitz_3_2", "Blitz 3+2", 180.0, 2.0),
    TimeControl("blitz_5_0", "Blitz 5+0", 300.0, 0.0),
    TimeControl("rapid_10_0", "Rapid 10+0", 600.0, 0.0),
    TimeControl("rapid_15_10", "Rapid 15+10", 900.0, 10.0),
)
DEFAULT_TIME_CONTROL_KEY = "blitz_5_0"
DEPTH_CAP_OPTIONS: tuple[int | None, ...] = (
    None, 8, 12, 16, 20, 24, 30, 40, 60, 100
)
PYTHON_UNLIMITED_DEPTH = 128

# Piece slide animation duration (seconds).
MOVE_ANIM_SECONDS = 0.14
# Let the mating move settle and briefly pulse the defeated king before the
# result modal covers the board.
CHECKMATE_REVEAL_DELAY = 1.8

# Engine selection. HCE and the NNUE generations are the same C++ executable
# with a different net (selected via SGR_EVALFILE); the pure-Python engine is
# the weaker (~1500) original.
ENGINE_CPP = "cpp"                       # C++ engine, hand-crafted eval (classical)
ENGINE_CPP_NNUE_GEN1 = "cpp_nnue_gen1"   # C++ engine, gen1 NNUE (v1.0 "Fox")
ENGINE_CPP_NNUE_GEN2 = "cpp_nnue_gen2"   # C++ engine, gen2 NNUE (v2.0 "Notches")
ENGINE_CPP_NNUE_GEN3 = "cpp_nnue_gen3"   # C++ engine, gen3 NNUE (v3.0 "Blackpeak")
ENGINE_PYTHON = "python"                 # original pure-Python engine
DEFAULT_ENGINE_CHOICE = ENGINE_CPP_NNUE_GEN3

CPP_ENGINE_CHOICES = (ENGINE_CPP, ENGINE_CPP_NNUE_GEN1, ENGINE_CPP_NNUE_GEN2,
                      ENGINE_CPP_NNUE_GEN3)

# Order the opponent toggle cycles through (classical, then the NNUE ladder,
# then the legacy Python engine).
ENGINE_CYCLE = [ENGINE_CPP, ENGINE_CPP_NNUE_GEN1, ENGINE_CPP_NNUE_GEN2,
                ENGINE_CPP_NNUE_GEN3, ENGINE_PYTHON]

ENGINE_PROFILES = {
    ENGINE_CPP: {
        "short_name": "Sgurr Classical (HCE)",
        "label": "Sgurr Classical (HCE) (2400 ±35)",
        "pgn_name": "Sgurr-HCE",
        "default_depth": None,
        "default_time": 0.5,
        "max_depth": 100,
        "net": None,               # None -> hand-crafted eval (classical)
    },
    ENGINE_CPP_NNUE_GEN1: {
        "short_name": "Sgurr v1.0 \"Fox\"",
        "label": "Sgurr v1.0 \"Fox\" (2408 ±34)",
        "pgn_name": "Sgurr-NNUE-gen1",
        "default_depth": None,
        "default_time": 0.5,
        "max_depth": 100,
        "net": GEN1_NET_PATH,      # v1.0 "Fox"
    },
    ENGINE_CPP_NNUE_GEN2: {
        "short_name": "Sgurr v2.0 \"Notches\"",
        "label": "Sgurr v2.0 \"Notches\" (2491 ±33)",
        "pgn_name": "Sgurr-NNUE-gen2",
        "default_depth": None,
        "default_time": 0.5,
        "max_depth": 100,
        "net": GEN2_NET_PATH,      # v2.0 "Notches"
    },
    ENGINE_CPP_NNUE_GEN3: {
        "short_name": "Sgurr v3.0 \"Blackpeak\"",
        "label": "Sgurr v3.0 \"Blackpeak\" (2616 ±37)",
        "pgn_name": "Sgurr-NNUE-gen3",
        "default_depth": None,
        "default_time": 0.5,
        "max_depth": 100,
        "net": GEN3_NET_PATH,      # v3.0 "Blackpeak"
    },
    ENGINE_PYTHON: {
        "short_name": "Sgurr Legacy Python",
        "label": "Sgurr Legacy Python (~1500)",
        "pgn_name": "SgurrPython",
        "default_depth": None,
        "default_time": 0.5,
        "max_depth": 100,
        "net": None,
    },
}

SOUND_FILE_CANDIDATES = {
    "move_self": ["move-self.mp3", "Move-self.mp3", "move_self.mp3", "Move.mp3", "move.mp3", "move.wav"],
    "move_opponent": ["move-opponent.mp3", "Move-opponent.mp3", "move_opponent.mp3", "Move.mp3", "move.mp3", "move.wav"],
    "move": ["Move.mp3", "move.mp3", "move.wav"],
    "capture": ["capture.mp3", "Capture.mp3", "capture.wav"],
    "check": ["move-check.mp3", "Move-check.mp3", "move_check.mp3", "Check.mp3", "check.mp3", "check.wav"],
    "checkmate": ["Checkmate.mp3", "checkmate.mp3", "checkmate.wav"],
    "game_end": ["game-end.mp3", "Game-end.mp3", "game_end.mp3", "game_end.wav"],
    "game_start": ["game-start.mp3", "Game-start.mp3", "game_start.mp3"],
    "victory": ["Victory.mp3", "victory.mp3", "victory.wav"],
    "defeat": ["Defeat.mp3", "defeat.mp3", "defeat.wav"],
    "draw": ["Draw.mp3", "draw.mp3", "draw.wav"],
    "promote": ["promote.mp3", "Promote.mp3", "promote.wav"],
    "castle": ["castle.mp3", "Castle.mp3", "castle.wav"],
    "illegal": ["illegal.mp3", "Illegal.mp3", "illegal.wav"],
    "button": ["button.mp3", "Button.mp3", "click.mp3", "Click.mp3", "button.wav", "click.wav"],
}

AUTO_FLIP_AS_BLACK = True
SHOW_ENGINE_INFO = True

# UI font: Bahnschrift is a modern sans that ships with Windows 10; the stack
# falls back to Segoe UI / Arial anywhere it is missing. Change UI_FONT_STACK
# to restyle all interface text at once.
UI_FONT_STACK = "bahnschrift,segoeui,arial"
PIECE_FONT_NAME = "segoeuisymbol"

MATERIAL_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 0,
}

EVAL_BAR_WIDTH = 34
EVAL_BAR_MARGIN = 10
# Per-frame easing factor for the eval bar (60 fps -> ~250 ms settle).
EVAL_BAR_EASING = 0.18

# Use the platform's familiar chess silhouettes.  Colour, outline and shadow
# still come from the active theme, but the piece forms remain conventional.
SOLID_GLYPHS = {
    chess.KING: "♚",
    chess.QUEEN: "♛",
    chess.ROOK: "♜",
    chess.BISHOP: "♝",
    chess.KNIGHT: "♞",
    chess.PAWN: "♟",
}

# Board-editor palette, drawn left-to-right in white and black rows.
EDIT_PALETTE_ORDER = [chess.KING, chess.QUEEN, chess.ROOK, chess.BISHOP,
                      chess.KNIGHT, chess.PAWN]

PROMOTION_CHOICES = [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT]

CHECKMATE_DRILLS = (
    ("queen", "K+Q vs K", (chess.QUEEN,)),
    ("rook", "K+R vs K", (chess.ROOK,)),
    ("two_rooks", "K+2R vs K", (chess.ROOK, chess.ROOK)),
    ("two_bishops", "K+2B vs K", (chess.BISHOP, chess.BISHOP)),
    ("bishop_knight", "K+B+N vs K", (chess.BISHOP, chess.KNIGHT)),
)
CHECKMATE_DRILL_BY_KEY = {
    key: (label, pieces) for key, label, pieces in CHECKMATE_DRILLS
}

ODDS_RECIPIENTS = ("you", "engine")
ODDS_PRESETS = (
    ("queen", "Queen odds", (chess.D1,)),
    ("rook", "Rook odds", (chess.A1,)),
    ("knight", "Knight odds", (chess.B1,)),
    ("bishop", "Bishop odds", (chess.C1,)),
    ("two_pawns", "Two-pawn odds", (chess.C2, chess.F2)),
)
ODDS_PRESET_BY_KEY = {
    key: (label, squares) for key, label, squares in ODDS_PRESETS
}


def enable_high_dpi() -> None:
    """Ask Windows for native physical pixels instead of a blurred DPI bitmap."""
    if sys.platform != "win32":
        return
    try:
        # Per-monitor DPI awareness v2 (Windows 10+).
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass


@dataclass(frozen=True)
class Theme:
    display_name: str
    background: tuple
    background2: tuple
    panel: tuple
    panel2: tuple
    panel_edge: tuple
    board_light: tuple
    board_dark: tuple
    frame: tuple
    coord: tuple
    text: tuple
    muted: tuple
    button: tuple
    button_hover: tuple
    button_press: tuple
    button_text: tuple
    accent: tuple
    accent2: tuple
    error: tuple
    last_move: tuple
    selected: tuple
    legal_dot: tuple
    check_glow: tuple
    eval_white: tuple
    eval_black: tuple
    eval_line: tuple
    piece_white: tuple
    piece_black: tuple
    piece_white_edge: tuple
    piece_black_edge: tuple


THEMES = {
    "neon": Theme(
        display_name="Neon Dark",
        background=(12, 15, 21), background2=(7, 9, 13),
        panel=(20, 24, 32), panel2=(27, 33, 44), panel_edge=(48, 57, 74),
        board_light=(45, 52, 65), board_dark=(24, 29, 39),
        frame=(7, 9, 13), coord=(128, 143, 169),
        text=(239, 244, 252), muted=(148, 161, 187),
        button=(31, 37, 49), button_hover=(45, 54, 71), button_press=(22, 27, 36),
        button_text=(235, 242, 251),
        accent=(54, 202, 226), accent2=(204, 108, 239), error=(255, 112, 122),
        last_move=(54, 202, 226), selected=(204, 108, 239), legal_dot=(54, 202, 226),
        check_glow=(250, 68, 78),
        eval_white=(237, 243, 251), eval_black=(31, 37, 49), eval_line=(54, 202, 226),
        piece_white=(242, 246, 252), piece_black=(23, 28, 38),
        piece_white_edge=(13, 17, 24), piece_black_edge=(83, 177, 197),
    ),
    "modern": Theme(
        display_name="Modern Dark",
        background=(22, 25, 22), background2=(14, 16, 15),
        panel=(31, 35, 31), panel2=(43, 48, 42), panel_edge=(76, 85, 73),
        board_light=(238, 241, 219), board_dark=(82, 128, 66),
        frame=(13, 15, 14), coord=(147, 158, 139),
        text=(244, 246, 240), muted=(174, 183, 168),
        button=(51, 57, 50), button_hover=(72, 81, 70), button_press=(37, 42, 37),
        button_text=(246, 248, 242),
        accent=(86, 143, 226), accent2=(93, 176, 93), error=(242, 105, 96),
        last_move=(242, 220, 91), selected=(250, 232, 104), legal_dot=(38, 48, 34),
        check_glow=(231, 70, 59),
        eval_white=(247, 249, 243), eval_black=(34, 39, 34), eval_line=(86, 143, 226),
        piece_white=(253, 253, 248), piece_black=(23, 28, 24),
        piece_white_edge=(35, 40, 35), piece_black_edge=(225, 231, 218),
    ),
    "wood": Theme(
        display_name="Classic Wood",
        background=(37, 26, 22), background2=(24, 17, 15),
        panel=(51, 36, 29), panel2=(67, 47, 37), panel_edge=(118, 82, 61),
        board_light=(245, 216, 170), board_dark=(151, 94, 57),
        frame=(27, 19, 16), coord=(226, 201, 163),
        text=(252, 242, 224), muted=(211, 187, 157),
        button=(74, 51, 40), button_hover=(102, 70, 53), button_press=(51, 35, 29),
        button_text=(252, 243, 227),
        accent=(226, 177, 71), accent2=(201, 111, 58), error=(243, 108, 83),
        last_move=(235, 183, 65), selected=(248, 207, 97), legal_dot=(70, 42, 25),
        check_glow=(218, 76, 54),
        eval_white=(252, 244, 229), eval_black=(51, 36, 29), eval_line=(226, 177, 71),
        piece_white=(255, 248, 233), piece_black=(38, 25, 20),
        piece_white_edge=(72, 45, 29), piece_black_edge=(235, 207, 168),
    ),
    "light": Theme(
        display_name="Minimal Light",
        background=(235, 239, 245), background2=(220, 226, 235),
        panel=(244, 247, 250), panel2=(233, 238, 245), panel_edge=(158, 173, 193),
        board_light=(228, 234, 241), board_dark=(121, 145, 170),
        frame=(148, 164, 184), coord=(79, 94, 115),
        text=(24, 32, 49), muted=(97, 113, 137),
        button=(230, 235, 242), button_hover=(216, 224, 235), button_press=(202, 212, 226),
        button_text=(27, 36, 53),
        accent=(67, 99, 224), accent2=(132, 88, 232), error=(211, 66, 73),
        last_move=(250, 215, 96), selected=(224, 205, 252), legal_dot=(57, 76, 105),
        check_glow=(226, 67, 70),
        eval_white=(242, 245, 249), eval_black=(101, 120, 143), eval_line=(67, 99, 224),
        piece_white=(246, 247, 244), piece_black=(32, 42, 58),
        piece_white_edge=(72, 86, 106), piece_black_edge=(242, 246, 251),
    ),
    "highland": Theme(
        display_name="Highland Heather",
        background=(28, 23, 32), background2=(15, 17, 20),
        panel=(38, 32, 43), panel2=(51, 44, 57), panel_edge=(91, 78, 98),
        board_light=(180, 190, 164), board_dark=(76, 91, 70),
        frame=(18, 19, 20), coord=(211, 204, 188),
        text=(247, 240, 226), muted=(188, 177, 174),
        button=(58, 49, 64), button_hover=(79, 66, 86), button_press=(43, 36, 48),
        button_text=(249, 242, 231),
        accent=(188, 126, 195), accent2=(220, 178, 91), error=(238, 98, 102),
        last_move=(226, 185, 82), selected=(199, 137, 205), legal_dot=(46, 59, 43),
        check_glow=(228, 67, 74),
        eval_white=(247, 241, 227), eval_black=(48, 40, 53), eval_line=(188, 126, 195),
        piece_white=(250, 244, 230), piece_black=(35, 28, 39),
        piece_white_edge=(64, 52, 66), piece_black_edge=(225, 205, 176),
    ),
    "ocean": Theme(
        display_name="Deep Ocean",
        background=(8, 27, 38), background2=(5, 16, 25),
        panel=(14, 38, 50), panel2=(22, 53, 67), panel_edge=(54, 94, 108),
        board_light=(157, 194, 196), board_dark=(38, 91, 106),
        frame=(5, 18, 25), coord=(166, 200, 205),
        text=(232, 246, 246), muted=(139, 176, 181),
        button=(25, 57, 70), button_hover=(35, 77, 91), button_press=(17, 43, 54),
        button_text=(235, 248, 248),
        accent=(48, 201, 188), accent2=(247, 146, 104), error=(255, 105, 112),
        last_move=(247, 175, 92), selected=(65, 213, 199), legal_dot=(16, 65, 75),
        check_glow=(244, 73, 80),
        eval_white=(232, 246, 244), eval_black=(20, 48, 60), eval_line=(48, 201, 188),
        piece_white=(241, 246, 235), piece_black=(11, 39, 49),
        piece_white_edge=(30, 69, 76), piece_black_edge=(132, 224, 214),
    ),
    "frost": Theme(
        display_name="Nordic Frost",
        background=(208, 217, 221), background2=(187, 200, 206),
        panel=(229, 234, 236), panel2=(216, 224, 227), panel_edge=(105, 123, 132),
        board_light=(222, 230, 227), board_dark=(91, 120, 126),
        frame=(82, 101, 108), coord=(45, 65, 71),
        text=(25, 38, 43), muted=(82, 103, 111),
        button=(208, 219, 223), button_hover=(193, 208, 213), button_press=(177, 194, 200),
        button_text=(25, 40, 45),
        accent=(33, 132, 149), accent2=(207, 105, 70), error=(193, 57, 64),
        last_move=(239, 190, 93), selected=(116, 188, 197), legal_dot=(40, 70, 76),
        check_glow=(211, 59, 66),
        eval_white=(239, 243, 242), eval_black=(77, 99, 106), eval_line=(33, 132, 149),
        piece_white=(247, 246, 236), piece_black=(27, 43, 48),
        piece_white_edge=(61, 81, 86), piece_black_edge=(231, 239, 237),
    ),
}

THEME_ORDER = ["neon", "modern", "wood", "light", "highland", "ocean", "frost"]
DEFAULT_THEME = "neon"


@dataclass
class ButtonRect:
    rect: pygame.Rect
    label: str
    action: str
    style: str = "secondary"


@dataclass(frozen=True)
class EngineClockLimit:
    white_clock: float
    black_clock: float
    white_inc: float
    black_inc: float


@dataclass
class SearchResult:
    best_move: chess.Move | None
    score: int
    depth: int
    nodes: int
    time_taken: float


def score_to_white_centipawns(score: chess.engine.PovScore | None) -> int:
    if score is None:
        return 0

    white_score = score.pov(chess.WHITE)

    if white_score.is_mate():
        mate = white_score.mate()
        if mate is None:
            return 0
        return 100000 if mate > 0 else -100000

    cp = white_score.score()
    return cp if cp is not None else 0


def material_eval_white(board: chess.Board) -> int:
    """Material-only evaluation in white-relative centipawns."""
    if board.is_checkmate():
        return -100000 if board.turn == chess.WHITE else 100000

    if board.is_stalemate() or board.is_insufficient_material():
        return 0

    material = 0
    for piece in board.piece_map().values():
        value = MATERIAL_VALUES[piece.piece_type] * 100
        material += value if piece.color == chess.WHITE else -value

    return material


def copy_text_to_clipboard(text: str) -> bool:
    """Copy text to the Windows clipboard via clip.exe (no extra deps)."""
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(["clip"], input=text.encode("utf-8"), check=True,
                       creationflags=flags, timeout=5)
        return True
    except Exception:
        return False


class CppSgurrEngine:
    """Wrapper around the C++ Sgurr UCI executable.

    The same executable runs in classical (hand-crafted eval) or NNUE mode
    depending on net_path, which is passed to the child process as
    SGR_EVALFILE. None points the engine at a missing file, forcing the
    classical fallback.

    One engine process persists for the whole game (it keeps its
    transposition table between moves and avoids per-move process spawn and
    net reload); pass a fresh game token to signal a new game (python-chess
    then sends ucinewgame). Call close() when finished.
    """

    def __init__(
        self,
        engine_path: Path = ENGINE_EXE_PATH,
        net_path: Path | None = None,
    ) -> None:
        self.engine_path = engine_path
        self.net_path = net_path
        self._engine: chess.engine.SimpleEngine | None = None

    def _child_env(self) -> dict[str, str]:
        # Keep the full environment and set SGR_EVALFILE for the chosen mode.
        env = dict(os.environ)
        target = self.net_path if self.net_path is not None else NO_NET_PATH
        env["SGR_EVALFILE"] = str(target)
        return env

    def _ensure_engine(self) -> chess.engine.SimpleEngine:
        if self._engine is not None:
            return self._engine

        if not self.engine_path.exists():
            raise FileNotFoundError(
                f"Engine executable not found: {self.engine_path}. Build the C++ "
                f"engine (with nnue.cpp) or set SGR_ENGINE_EXE to its location."
            )

        if self.net_path is not None and not self.net_path.exists():
            raise FileNotFoundError(
                f"NNUE net not found: {self.net_path}. Train it or fix the path."
            )

        self._engine = chess.engine.SimpleEngine.popen_uci(
            [str(self.engine_path), "uci"],
            timeout=ENGINE_TIMEOUT,
            env=self._child_env(),
        )
        return self._engine

    def search_best_move(
        self,
        board: chess.Board,
        max_depth: int | None,
        time_limit: float | None = None,
        clock_limit: EngineClockLimit | None = None,
        game_token: object | None = None,
    ) -> SearchResult:
        engine = self._ensure_engine()
        start = time.time()
        if clock_limit is not None:
            limit_kwargs = {
                "white_clock": max(0.001, clock_limit.white_clock),
                "black_clock": max(0.001, clock_limit.black_clock),
                "white_inc": max(0.0, clock_limit.white_inc),
                "black_inc": max(0.0, clock_limit.black_inc),
            }
        else:
            limit_kwargs = {"time": max(0.01, time_limit or 0.01)}
        if max_depth is not None:
            limit_kwargs["depth"] = max_depth
        limit = chess.engine.Limit(**limit_kwargs)

        try:
            result = engine.play(
                board,
                limit,
                game=game_token,
                info=chess.engine.INFO_ALL,
            )
        except chess.engine.EngineTerminatedError:
            # The process died; drop the handle so the next search relaunches.
            self._engine = None
            raise

        elapsed = time.time() - start
        info = result.info
        score = score_to_white_centipawns(info.get("score"))
        depth = int(info.get("depth", 0))
        nodes = int(info.get("nodes", 0))

        return SearchResult(
            best_move=result.move,
            score=score,
            depth=depth,
            nodes=nodes,
            time_taken=elapsed,
        )

    def quick_white_eval(self, board: chess.Board) -> int:
        # Cheap fallback for the eval bar before any search score exists.
        return material_eval_white(board)

    def close(self) -> None:
        if self._engine is None:
            return
        try:
            self._engine.quit()
        except Exception:
            try:
                self._engine.close()
            except Exception:
                pass
        self._engine = None


class PythonSgurrEngine:
    """Adapter around the original pure-Python Sgurr engine (~1500 elo).

    The GUI uses python-chess for display and input while the engine searches
    with its own SgurrBoard/SgurrEngine classes. sgurr_python is imported lazily so
    the GUI still runs with the C++ engine if the package isn't importable.
    """

    def __init__(self) -> None:
        try:
            from sgurr_python.sgurr_board import Board as SgurrBoard
            from sgurr_python.sgurr_engine import Engine as SgurrEngine
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "Could not import sgurr_python. Put this script in the project "
                "folder or one folder below it so that sgurr_python is importable."
            ) from exc

        self._SgurrBoard = SgurrBoard
        self.engine = SgurrEngine()

    def search_best_move(
        self,
        board: chess.Board,
        max_depth: int | None,
        time_limit: float | None = None,
        clock_limit: EngineClockLimit | None = None,
        game_token: object | None = None,
    ) -> SearchResult:
        sgurr_board = self._SgurrBoard(board.fen())

        depth_cap = max_depth if max_depth is not None else PYTHON_UNLIMITED_DEPTH
        start = time.time()
        result = self.engine.search_best_move(
            sgurr_board,
            max_depth=depth_cap,
            time_limit=max(0.01, time_limit or 0.01),
        )
        elapsed = time.time() - start

        raw_move = getattr(result, "best_move", None)
        best_move: chess.Move | None = None

        if raw_move is not None:
            try:
                best_move = chess.Move.from_uci(str(raw_move))
            except ValueError:
                best_move = None

        return SearchResult(
            best_move=best_move,
            score=self.safe_int(getattr(result, "score", 0)),
            depth=self.safe_int(getattr(result, "depth", 0)),
            nodes=self.safe_int(getattr(result, "nodes", 0)),
            time_taken=elapsed,
        )

    def quick_white_eval(self, board: chess.Board) -> int:
        if board.is_checkmate():
            return -100000 if board.turn == chess.WHITE else 100000

        if board.is_stalemate() or board.is_insufficient_material():
            return 0

        try:
            sgurr_board = self._SgurrBoard(board.fen())
            score = self.safe_int(sgurr_board.evaluate())
            return score if getattr(sgurr_board, "side_to_move", 0) == 0 else -score
        except Exception:
            return material_eval_white(board)

    def close(self) -> None:
        pass

    @staticmethod
    def safe_int(value: object) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0


class SgurrGui:
    @staticmethod
    def create_window(size: tuple[int, int]) -> pygame.Surface:
        flags = pygame.RESIZABLE | pygame.DOUBLEBUF
        try:
            return pygame.display.set_mode(
                size, flags, depth=DISPLAY_DEPTH, vsync=0
            )
        except (TypeError, pygame.error):
            return pygame.display.set_mode(size, flags, depth=DISPLAY_DEPTH)

    @staticmethod
    def desktop_size() -> tuple[int, int]:
        try:
            sizes = pygame.display.get_desktop_sizes()
            if sizes:
                return sizes[0]
        except (AttributeError, pygame.error):
            pass

        info = pygame.display.Info()
        return max(640, info.current_w), max(400, info.current_h)

    @staticmethod
    def create_fullscreen_window(size: tuple[int, int]) -> pygame.Surface:
        flags = pygame.FULLSCREEN | pygame.DOUBLEBUF
        try:
            return pygame.display.set_mode(
                size, flags, depth=DISPLAY_DEPTH, vsync=0
            )
        except (TypeError, pygame.error):
            return pygame.display.set_mode(size, flags, depth=DISPLAY_DEPTH)

    def __init__(self) -> None:
        enable_high_dpi()
        pygame.init()
        try:
            pygame.transform.set_smoothscale_backend("SSE")
        except (ValueError, pygame.error):
            pass
        self.preferences = self.load_preferences()
        self.animation_mode = self.valid_animation_mode(
            self.preferences.get("animation_mode", "Full")
        )
        self.master_volume = self.valid_volume(self.preferences.get("master_volume", 0.8))
        self.move_volume = self.valid_volume(self.preferences.get("move_volume", 0.8))
        self.alert_volume = self.valid_volume(self.preferences.get("alert_volume", 0.8))
        self._preferences_dirty = False
        self._preferences_changed_at = 0
        self.sounds = self.load_sounds()
        pygame.display.set_caption("Sgurr")

        # Draw onto a fixed logical canvas, then letterbox/scale it into a
        # resizable native window.  Input is mapped back to logical pixels so
        # every existing board interaction remains exact at any window size.
        saved_size = self.preferences.get("window_size", [WINDOW_WIDTH, WINDOW_HEIGHT])
        try:
            initial_size = (max(640, int(saved_size[0])),
                            max(400, int(saved_size[1])))
        except (TypeError, ValueError, IndexError):
            initial_size = (WINDOW_WIDTH, WINDOW_HEIGHT)
        self.window = self.create_window(initial_size)
        self.screen = pygame.Surface(
            (WINDOW_WIDTH, WINDOW_HEIGHT), depth=DISPLAY_DEPTH
        ).convert()
        self.window_size = initial_size
        self.windowed_size = initial_size
        self.fullscreen = False
        self.viewport = pygame.Rect(0, 0, WINDOW_WIDTH, WINDOW_HEIGHT)
        self._fps_caption_at = 0
        self.clock = pygame.time.Clock()
        self.update_viewport(*initial_size)

        self.board_font = pygame.font.SysFont(
            PIECE_FONT_NAME, 64 * PIECE_SUPERSAMPLE
        )
        self._font_cache: dict[tuple, pygame.font.Font] = {}
        self._text_cache: dict[tuple, pygame.Surface] = {}
        self.title_font = self.ui_font(40, bold=True)
        self.large_font = self.ui_font(30, bold=True)
        self.medium_font = self.ui_font(22, bold=True)
        self.small_font = self.ui_font(16, bold=False)
        self.tiny_font = self.ui_font(14, bold=False)

        # Visual theme.
        saved_theme = self.preferences.get("theme", DEFAULT_THEME)
        self.theme_name = saved_theme if saved_theme in THEMES else DEFAULT_THEME
        self.theme = THEMES[self.theme_name]
        self._piece_cache: dict[tuple, pygame.Surface] = {}
        self._glow_cache: dict[tuple, pygame.Surface] = {}
        self._grad_cache: dict[tuple, pygame.Surface] = {}
        self._motif_cache: dict[str, pygame.Surface] = {}
        self._board_base_cache: dict[tuple, pygame.Surface] = {}

        # Which engine the player will face. Depth is an optional advanced cap;
        # by default clock play runs without a GUI-imposed maximum depth.
        saved_engine = self.preferences.get("engine", DEFAULT_ENGINE_CHOICE)
        self.engine_choice = saved_engine if saved_engine in ENGINE_PROFILES else DEFAULT_ENGINE_CHOICE
        self.max_engine_depth = ENGINE_PROFILES[self.engine_choice]["max_depth"]
        self.engine_depth: int | None = None
        self.apply_engine_defaults()
        self.engine_depth = self.valid_depth_cap(
            self.preferences.get("engine_depth_cap", self.engine_depth)
        )
        self.time_control_index = self.resolve_time_control_index(
            self.preferences.get("time_control")
        )
        self.game_clocks: dict[chess.Color, float] = {
            chess.WHITE: self.time_control.base_seconds,
            chess.BLACK: self.time_control.base_seconds,
        }
        self.clock_history: list[dict[chess.Color, float]] = []
        self.redo_clock_stack: list[dict[chess.Color, float]] = []
        self.clock_last_update = time.perf_counter()
        self.clock_flagged: chess.Color | None = None
        self.auto_flip_as_black = bool(
            self.preferences.get("auto_flip_as_black", AUTO_FLIP_AS_BLACK))

        self.chess_board = chess.Board()
        self.engine: CppSgurrEngine | PythonSgurrEngine | None = None
        self.game_token: object = object()
        self.game_start_fen: str = chess.STARTING_FEN

        self.human_colour: chess.Color | None = None
        self.flip_board = False
        self.selected_square: chess.Square | None = None
        self.last_move: chess.Move | None = None

        self.status = "Choose a side"
        self.engine_info = ""
        self.last_engine_score = 0
        self.game_started = False
        self.game_is_over = False
        self.game_over_sound_played = False
        self.game_over_reveal_at: float | None = None

        # Threaded search: the worker posts ("ok", SearchResult) or
        # ("error", message) here; the main loop polls and applies.
        self.search_queue: queue.Queue = queue.Queue()
        self.engine_thinking = False

        # Eval bar: target follows the last *search* score (never regressing
        # to material between moves); the displayed fraction eases toward it.
        self.eval_target_cp = 0
        self.have_search_eval = False
        self.eval_display_frac = 0.5
        self.eval_history: list[tuple[int, int]] = []


        # Sliding move animation (cosmetic): {piece, from, to, start, dur}.
        self.animation: dict | None = None

        # History navigation: undone moves are kept for redo; any new move
        # clears the redo stack.
        self.redo_stack: list[chess.Move] = []

        # Watch-mode pause (Space): freezes self-play so positions can be
        # inspected or edited mid-game.
        self.watch_paused = False

        # Pending promotion: (from_square, to_square) awaiting a picker choice.
        self.promotion_pending: tuple[chess.Square, chess.Square] | None = None
        self.promotion_buttons: list[tuple[pygame.Rect, int]] = []
        # Whether the pending promotion should animate (click) or pop (drag).
        self._promo_animate = True

        # Board editor state.
        self.edit_mode = False
        self.edit_board = chess.Board()
        self.edit_turn: chess.Color = chess.WHITE
        self.edit_brush: chess.Piece | None = None
        self.edit_drag_piece: chess.Piece | None = None
        self.edit_drag_mouse = (0, 0)
        self.edit_return_colour: chess.Color | None = chess.WHITE
        self.edit_odds_recipient = "you"
        self.edit_palette_rects: list[tuple[pygame.Rect, chess.Piece]] = []
        self.edit_buttons: list[ButtonRect] = []

        self.input_mode: str | None = None
        self.text_input = ""
        self.input_error = ""
        self.help_visible = False
        self.theme_gallery_visible = False
        self.time_gallery_visible = False
        self.settings_visible = False
        self.help_close_button = pygame.Rect(0, 0, 0, 0)
        self.theme_gallery_buttons: list[ButtonRect] = []
        self.time_gallery_buttons: list[ButtonRect] = []
        self.settings_buttons: list[ButtonRect] = []
        self.side_buttons: list[ButtonRect] = []
        self.rematch_button = pygame.Rect(0, 0, 0, 0)

        self.dragging_piece: chess.Piece | None = None
        self.dragging_from_square: chess.Square | None = None
        self.dragging_mouse_pos = (0, 0)
        self.drag_start_pos = (0, 0)
        self.drag_started = False
        self.focus_index = 0
        self.keyboard_focus = False

        menu_y = PLAYER_BAR_HEIGHT
        self.menu_card = pygame.Rect(WINDOW_WIDTH // 2 - 260, 108 + menu_y, 520, 520)
        x = self.menu_card.x + 28
        w = self.menu_card.width - 56
        arrow = 44
        game_arrow = 54
        self.menu_buttons = [
            ButtonRect(pygame.Rect(x, 154 + menu_y, arrow, 44), "‹", "engine_prev", "selector"),
            ButtonRect(pygame.Rect(x + arrow + 8, 154 + menu_y, w - 2 * arrow - 16, 44), "Opponent", "noop_engine", "selector_value"),
            ButtonRect(pygame.Rect(x + w - arrow, 154 + menu_y, arrow, 44), "›", "engine_next", "selector"),
            ButtonRect(pygame.Rect(x, 222 + menu_y, arrow, 40), "‹", "theme_prev", "selector"),
            ButtonRect(pygame.Rect(x + arrow + 8, 222 + menu_y, w - 2 * arrow - 16, 40), "Theme", "theme_gallery", "selector_value"),
            ButtonRect(pygame.Rect(x + w - arrow, 222 + menu_y, arrow, 40), "›", "theme_next", "selector"),
            ButtonRect(pygame.Rect(x, 300 + menu_y, game_arrow, 60), "<", "time_down", "selector"),
            ButtonRect(pygame.Rect(x + game_arrow + 8, 300 + menu_y, w - 2 * game_arrow - 16, 60), "Game mode", "time_gallery", "selector_value"),
            ButtonRect(pygame.Rect(x + w - game_arrow, 300 + menu_y, game_arrow, 60), ">", "time_up", "selector"),
            ButtonRect(pygame.Rect(x, 442 + menu_y, 206, 48), "Play as White", "play_white", "play_white"),
            ButtonRect(pygame.Rect(x + 222, 442 + menu_y, 206, 48), "Play as Black", "play_black", "play_black"),
            ButtonRect(pygame.Rect(x, 500 + menu_y, w, 42), "Watch Sgurr vs itself", "watch", "secondary"),
            ButtonRect(pygame.Rect(x, 566 + menu_y, 206, 38), "Load FEN", "load_fen", "ghost"),
            ButtonRect(pygame.Rect(x + 222, 566 + menu_y, 206, 38), "Board editor", "board_editor", "ghost"),
            ButtonRect(pygame.Rect(WINDOW_WIDTH - 174, 22, 100, 40), "Settings", "show_settings", "ghost"),
            ButtonRect(pygame.Rect(WINDOW_WIDTH - 62, 22, 40, 40), "?", "show_help", "ghost"),
        ]
        self.layout_menu_buttons()

        self.main_menu_button = pygame.Rect(0, 0, 0, 0)

    def layout_menu_buttons(self) -> None:
        x = self.menu_card.x + 28
        w = self.menu_card.width - 56
        y = self.menu_card.y
        arrow = 44
        game_arrow = 54
        rects = {
            "time_down": pygame.Rect(x, y + 50, game_arrow, 68),
            "time_gallery": pygame.Rect(x + game_arrow + 10, y + 50,
                                        w - 2 * game_arrow - 20, 68),
            "time_up": pygame.Rect(x + w - game_arrow, y + 50, game_arrow, 68),
            "engine_prev": pygame.Rect(x, y + 164, arrow, 42),
            "noop_engine": pygame.Rect(x + arrow + 8, y + 164,
                                       w - 2 * arrow - 16, 42),
            "engine_next": pygame.Rect(x + w - arrow, y + 164, arrow, 42),
            "theme_prev": pygame.Rect(x, y + 246, arrow, 40),
            "theme_gallery": pygame.Rect(x + arrow + 8, y + 246,
                                         w - 2 * arrow - 16, 40),
            "theme_next": pygame.Rect(x + w - arrow, y + 246, arrow, 40),
            "play_white": pygame.Rect(x, y + 340, 222, 50),
            "play_black": pygame.Rect(x + w - 222, y + 340, 222, 50),
            "watch": pygame.Rect(x, y + 402, w, 42),
            "load_fen": pygame.Rect(x, y + 474, 222, 38),
            "board_editor": pygame.Rect(x + w - 222, y + 474, 222, 38),
            "show_settings": pygame.Rect(WINDOW_WIDTH - 174, 22, 100, 40),
            "show_help": pygame.Rect(WINDOW_WIDTH - 62, 22, 40, 40),
        }
        for button in self.menu_buttons:
            if button.action in rects:
                button.rect = rects[button.action]

    # persistent preferences

    @staticmethod
    def load_preferences() -> dict:
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    @staticmethod
    def valid_animation_mode(value: object) -> str:
        return str(value) if str(value) in ANIMATION_MODES else "Full"

    @staticmethod
    def valid_volume(value: object) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.8

    def valid_depth_cap(self, value: object) -> int | None:
        if value is None:
            return None
        if isinstance(value, str) and value.strip().lower() in {
            "", "none", "no cap", "unlimited"
        }:
            return None
        try:
            depth = int(value)
        except (TypeError, ValueError):
            return None
        if depth <= 0:
            return None
        depth = max(1, min(self.max_engine_depth, depth))
        numeric_options = [option for option in DEPTH_CAP_OPTIONS if option is not None]
        return min(numeric_options, key=lambda option: abs(option - depth))

    @property
    def move_animation_duration(self) -> float:
        if self.animation_mode == "Off":
            return 0.0
        if self.animation_mode == "Reduced":
            return MOVE_ANIM_SECONDS * 0.5
        return MOVE_ANIM_SECONDS

    @property
    def checkmate_reveal_delay(self) -> float:
        if self.animation_mode == "Off":
            return 0.0
        if self.animation_mode == "Reduced":
            return 0.8
        return CHECKMATE_REVEAL_DELAY

    def preference_data(self) -> dict:
        return {
            "theme": self.theme_name,
            "engine": self.engine_choice,
            "engine_depth_cap": self.engine_depth,
            "time_control": self.time_control.key,
            "auto_flip_as_black": self.auto_flip_as_black,
            "animation_mode": self.animation_mode,
            "master_volume": round(self.master_volume, 2),
            "move_volume": round(self.move_volume, 2),
            "alert_volume": round(self.alert_volume, 2),
            "window_size": list(self.windowed_size if self.fullscreen else self.window_size),
        }

    def mark_preferences_dirty(self) -> None:
        self._preferences_dirty = True
        self._preferences_changed_at = pygame.time.get_ticks()

    def save_preferences(self, force: bool = False) -> None:
        if not self._preferences_dirty and not force:
            return
        if not force and pygame.time.get_ticks() - self._preferences_changed_at < 600:
            return
        try:
            SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            temporary = SETTINGS_PATH.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(self.preference_data(), indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, SETTINGS_PATH)
            self._preferences_dirty = False
        except OSError:
            # Preferences must never prevent the chess GUI from running.
            pass

    # engine selection helpers

    @property
    def engine_profile(self) -> dict:
        return ENGINE_PROFILES[self.engine_choice]

    @property
    def engine_name(self) -> str:
        return self.engine_profile["short_name"]

    @property
    def engine_label(self) -> str:
        return self.engine_profile["label"]

    @staticmethod
    def resolve_time_control_index(value: object) -> int:
        for index, control in enumerate(TIME_CONTROLS):
            if value == control.key or value == control.label:
                return index
        for index, control in enumerate(TIME_CONTROLS):
            if control.key == DEFAULT_TIME_CONTROL_KEY:
                return index
        return 0

    @property
    def time_control(self) -> TimeControl:
        return TIME_CONTROLS[self.time_control_index % len(TIME_CONTROLS)]

    @property
    def time_control_label(self) -> str:
        return self.time_control.label

    def apply_engine_defaults(self) -> None:
        profile = ENGINE_PROFILES[self.engine_choice]
        self.engine_depth = profile["default_depth"]
        self.max_engine_depth = profile["max_depth"]

    def depth_cap_label(self) -> str:
        if self.engine_depth is None:
            return "Unlimited"
        return f"Depth {self.engine_depth}"

    def search_limit_label(self) -> str:
        if self.engine_depth is None:
            return self.time_control_label.upper()
        return f"{self.time_control_label.upper()} - DEPTH {self.engine_depth} CAP"

    def cycle_depth_cap(self, direction: int) -> None:
        try:
            index = DEPTH_CAP_OPTIONS.index(self.engine_depth)
        except ValueError:
            index = 0
        self.engine_depth = DEPTH_CAP_OPTIONS[
            (index + direction) % len(DEPTH_CAP_OPTIONS)
        ]
        self.status = f"Depth cap: {self.depth_cap_label()}"
        self.mark_preferences_dirty()

    def toggle_engine(self, direction: int = 1) -> None:
        try:
            idx = ENGINE_CYCLE.index(self.engine_choice)
        except ValueError:
            idx = -1
        depth_cap = self.engine_depth
        self.engine_choice = ENGINE_CYCLE[(idx + direction) % len(ENGINE_CYCLE)]
        self.apply_engine_defaults()
        self.engine_depth = self.valid_depth_cap(depth_cap)
        self.status = f"Opponent: {self.engine_label}"
        self.mark_preferences_dirty()

    def cycle_theme(self, direction: int = 1) -> None:
        idx = THEME_ORDER.index(self.theme_name)
        self.select_theme(THEME_ORDER[(idx + direction) % len(THEME_ORDER)])

    def select_theme(self, name: str) -> None:
        if name not in THEMES:
            return
        self.theme_name = name
        self.theme = THEMES[self.theme_name]
        # Cached surfaces are theme-specific.
        self._piece_cache.clear()
        self._glow_cache.clear()
        self._grad_cache.clear()
        self._motif_cache.clear()
        self._text_cache.clear()
        self._board_base_cache.clear()
        self.status = f"Theme: {self.theme.display_name}"
        self.mark_preferences_dirty()

    def make_engine(self) -> CppSgurrEngine | PythonSgurrEngine:
        if self.engine_choice == ENGINE_PYTHON:
            return PythonSgurrEngine()
        net = ENGINE_PROFILES[self.engine_choice]["net"]
        return CppSgurrEngine(net_path=net)

    def close_engine(self) -> None:
        if self.engine is not None:
            try:
                self.engine.close()
            except Exception:
                pass
        self.engine = None

    def load_sounds(self) -> dict[str, pygame.mixer.Sound]:
        try:
            pygame.mixer.init()
        except pygame.error:
            return {}

        sounds: dict[str, pygame.mixer.Sound] = {}

        for name, filenames in SOUND_FILE_CANDIDATES.items():
            for filename in filenames:
                path = SOUND_DIR / filename
                if not path.exists():
                    continue

                try:
                    sounds[name] = pygame.mixer.Sound(str(path))

                    break
                except pygame.error:
                    pass

        return sounds

    def play_sound(self, name: str) -> None:
        sound = self.sounds.get(name)
        if sound is None:
            return

        try:
            base = 0.28 if name == "button" else 1.0
            if name in MOVE_SOUND_NAMES:
                category = self.move_volume
            elif name in ALERT_SOUND_NAMES:
                category = self.alert_volume
            else:
                category = 1.0
            sound.set_volume(base * self.master_volume * category)
            sound.play()
        except pygame.error:
            pass

    def play_game_over_sound(self) -> None:
        if self.game_over_sound_played:
            return

        result = self.current_game_result()

        if result == "1-0":
            if self.human_colour == chess.WHITE and "victory" in self.sounds:
                self.play_sound("victory")
            elif self.human_colour == chess.BLACK and "defeat" in self.sounds:
                self.play_sound("defeat")
            else:
                self.play_sound("game_end")

        elif result == "0-1":
            if self.human_colour == chess.BLACK and "victory" in self.sounds:
                self.play_sound("victory")
            elif self.human_colour == chess.WHITE and "defeat" in self.sounds:
                self.play_sound("defeat")
            else:
                self.play_sound("game_end")

        else:
            if "draw" in self.sounds:
                self.play_sound("draw")
            else:
                self.play_sound("game_end")

        self.game_over_sound_played = True

    def play_move_sound(
        self,
        move: chess.Move,
        was_capture: bool,
        was_castle: bool,
        was_promotion: bool,
        by_human: bool,
    ) -> None:
        self.game_is_over = self.position_or_clock_game_over()
        if self.game_is_over:
            self.play_game_over_sound()
        elif self.chess_board.is_check():
            self.play_sound("check")
        elif was_promotion:
            self.play_sound("promote")
        elif was_castle:
            self.play_sound("castle")
        elif was_capture:
            self.play_sound("capture")
        elif by_human:
            self.play_sound("move_self")
        else:
            self.play_sound("move_opponent")

    # ------------------------------------------------------------------
    # geometry
    # ------------------------------------------------------------------

    def square_to_screen(self, square: chess.Square) -> tuple[int, int]:
        file = chess.square_file(square)
        rank = chess.square_rank(square)

        if self.flip_board:
            col = 7 - file
            row = rank
        else:
            col = file
            row = 7 - rank

        return row, col

    def square_rect(self, square: chess.Square) -> pygame.Rect:
        row, col = self.square_to_screen(square)
        return pygame.Rect(EVAL_PANEL_WIDTH + col * SQUARE_SIZE,
                           BOARD_TOP + row * SQUARE_SIZE,
                           SQUARE_SIZE, SQUARE_SIZE)

    def square_center(self, square: chess.Square) -> tuple[int, int]:
        rect = self.square_rect(square)
        return rect.centerx, rect.centery

    def screen_to_square(self, x: int, y: int) -> chess.Square | None:
        board_x = x - EVAL_PANEL_WIDTH
        board_y = y - BOARD_TOP

        if (board_x < 0 or board_x >= BOARD_SIZE or
                board_y < 0 or board_y >= BOARD_SIZE):
            return None

        col = board_x // SQUARE_SIZE
        row = board_y // SQUARE_SIZE

        if self.flip_board:
            file = 7 - col
            rank = row
        else:
            file = col
            rank = 7 - row

        return chess.square(file, rank)

    def cycle_time_control(self, direction: int) -> None:
        self.time_control_index = (
            self.time_control_index + direction
        ) % len(TIME_CONTROLS)
        if not self.game_started:
            self.reset_game_clocks()
        self.status = f"Time control: {self.time_control_label}"
        self.mark_preferences_dirty()

    def select_time_control(self, key: str) -> None:
        for index, control in enumerate(TIME_CONTROLS):
            if control.key == key:
                self.time_control_index = index
                if not self.game_started:
                    self.reset_game_clocks()
                self.status = f"Time control: {self.time_control_label}"
                self.mark_preferences_dirty()
                return

    def clock_snapshot(self) -> dict[chess.Color, float]:
        return {
            chess.WHITE: float(self.game_clocks.get(chess.WHITE, self.time_control.base_seconds)),
            chess.BLACK: float(self.game_clocks.get(chess.BLACK, self.time_control.base_seconds)),
        }

    def reset_game_clocks(self) -> None:
        self.game_clocks = {
            chess.WHITE: self.time_control.base_seconds,
            chess.BLACK: self.time_control.base_seconds,
        }
        self.clock_history = [self.clock_snapshot()]
        self.redo_clock_stack.clear()
        self.clock_last_update = time.perf_counter()
        self.clock_flagged = None

    def restore_clock_from_history(self) -> None:
        if not self.clock_history:
            self.clock_history = [self.clock_snapshot()]
        snapshot = self.clock_history[-1]
        self.game_clocks = {
            chess.WHITE: float(snapshot.get(chess.WHITE, self.time_control.base_seconds)),
            chess.BLACK: float(snapshot.get(chess.BLACK, self.time_control.base_seconds)),
        }
        self.clock_last_update = time.perf_counter()

    def record_clock_snapshot(self) -> None:
        current_ply = len(self.chess_board.move_stack)
        self.clock_history = self.clock_history[:current_ply]
        self.clock_history.append(self.clock_snapshot())

    def add_move_increment(self, colour: chess.Color) -> None:
        self.game_clocks[colour] = (
            self.game_clocks.get(colour, self.time_control.base_seconds)
            + self.time_control.increment_seconds
        )

    def clock_should_run(self) -> bool:
        if not self.game_started or self.edit_mode or self.input_mode is not None:
            return False
        if self.game_is_over or self.clock_flagged is not None:
            return False
        if self.human_colour is None and self.watch_paused:
            return False
        return True

    def update_game_clock(self) -> None:
        now = time.perf_counter()
        if not self.clock_should_run():
            self.clock_last_update = now
            return

        elapsed = max(0.0, now - self.clock_last_update)
        self.clock_last_update = now
        if elapsed <= 0.0:
            return

        colour = self.chess_board.turn
        remaining = self.game_clocks.get(colour, self.time_control.base_seconds) - elapsed
        self.game_clocks[colour] = max(0.0, remaining)
        if remaining <= 0.0:
            self.flag_clock(colour)

    def flag_clock(self, colour: chess.Color) -> None:
        if self.clock_flagged is not None:
            return
        self.game_clocks[colour] = 0.0
        self.clock_flagged = colour
        self.game_is_over = True
        self.game_over_reveal_at = None
        self.status = f"{'White' if colour == chess.WHITE else 'Black'} loses on time"

        # Invalidate any in-flight search. The worker owns that engine handle
        # and closes it when it notices the stale token.
        was_thinking = self.engine_thinking
        self.game_token = object()
        if was_thinking:
            self.engine = None
        self.engine_thinking = False
        self.play_game_over_sound()

    def current_game_result(self) -> str:
        if self.clock_flagged == chess.WHITE:
            return "0-1"
        if self.clock_flagged == chess.BLACK:
            return "1-0"
        return self.chess_board.result(claim_draw=True)

    def position_or_clock_game_over(self) -> bool:
        return self.clock_flagged is not None or self.chess_board.is_game_over(claim_draw=True)

    def current_engine_clock_limit(self) -> EngineClockLimit:
        return EngineClockLimit(
            white_clock=max(0.0, self.game_clocks.get(chess.WHITE, 0.0)),
            black_clock=max(0.0, self.game_clocks.get(chess.BLACK, 0.0)),
            white_inc=self.time_control.increment_seconds,
            black_inc=self.time_control.increment_seconds,
        )

    def engine_move_time_limit(self) -> float:
        remaining = max(0.01, self.game_clocks.get(self.chess_board.turn, 0.01))
        increment = self.time_control.increment_seconds
        budget = remaining / 30.0 + increment * 0.5
        cap = max(0.01, remaining - 0.05)
        return max(0.01, min(budget, cap))

    @staticmethod
    def format_clock(seconds: float) -> str:
        seconds = max(0.0, seconds)
        if seconds < 10.0:
            tenths = int(seconds * 10.0 + 0.999)
            return f"0:{tenths // 10:02d}.{tenths % 10}"
        whole_seconds = int(seconds + 0.999)
        minutes, secs = divmod(whole_seconds, 60)
        return f"{minutes}:{secs:02d}"

    @staticmethod
    def enable_text_input_repeat() -> None:
        pygame.key.set_repeat(
            TEXT_INPUT_REPEAT_DELAY_MS,
            TEXT_INPUT_REPEAT_INTERVAL_MS,
        )

    @staticmethod
    def disable_text_input_repeat() -> None:
        pygame.key.set_repeat(0, 0)

    def reset_runtime_state(self) -> None:
        self.selected_square = None
        self.last_move = None
        self.engine_info = ""
        self.last_engine_score = 0
        self.game_over_sound_played = False
        self.clock_flagged = None
        self.game_is_over = self.position_or_clock_game_over()
        self.game_over_reveal_at = None
        self.disable_text_input_repeat()
        self.input_mode = None
        self.text_input = ""
        self.input_error = ""
        self.redo_stack.clear()
        self.redo_clock_stack.clear()
        self.watch_paused = False
        self.promotion_pending = None
        self.animation = None
        self.eval_history = []
        self.clear_drag_state()

    def snap_eval_display(self) -> None:
        """Jump the eval bar straight to its target (used on new positions)."""
        self.eval_display_frac = self.eval_to_bar_fraction(self.display_eval_pawns())

    def reset_eval_to_material(self) -> None:
        """Fall back to material for the bar target.

        Only used when there is no valid search score for the current
        position: at game start, and after history navigation or an edit.
        Between normal moves the last search score is kept instead (the old
        behaviour of snapping back to bare material between moves was the
        main eval-bar complaint).
        """
        self.have_search_eval = False
        self.eval_target_cp = material_eval_white(self.chess_board)
        if not self.eval_history:
            self.eval_history = [(len(self.chess_board.move_stack), self.eval_target_cp)]

    def record_eval_point(self, score_cp: int) -> None:
        ply = len(self.chess_board.move_stack)
        score_cp = max(-100000, min(100000, int(score_cp)))
        if self.eval_history and self.eval_history[-1][0] == ply:
            self.eval_history[-1] = (ply, score_cp)
        else:
            self.eval_history.append((ply, score_cp))

    def start_move_animation(self, move: chess.Move) -> None:
        duration = self.move_animation_duration
        if duration <= 0:
            self.animation = None
            return
        piece = self.chess_board.piece_at(move.to_square)
        if piece is None:
            return
        self.animation = {
            "piece": piece,
            "from": move.from_square,
            "to": move.to_square,
            "start": time.time(),
            "dur": duration,
        }

    def start_game(self, human_colour: chess.Color | None, fen: str | None = None) -> None:
        try:
            new_board = chess.Board(fen) if fen else chess.Board()
        except ValueError:
            self.status = "Invalid FEN"
            return

        try:
            engine = self.make_engine()
        except Exception as exc:
            self.status = f"Could not load {self.engine_label}: {exc}"
            return

        self.close_engine()
        self.chess_board = new_board
        self.engine = engine
        self.game_token = object()
        self.game_start_fen = new_board.fen()
        self.human_colour = human_colour
        self.flip_board = bool(self.auto_flip_as_black and human_colour == chess.BLACK)

        pygame.display.set_caption(f"Sgurr - {self.engine_name}")

        self.reset_runtime_state()
        self.reset_game_clocks()
        self.game_started = True
        self.reset_eval_to_material()
        self.snap_eval_display()

        if human_colour is None:
            self.status = f"Watching {self.engine_name} vs itself"
        elif human_colour == chess.WHITE:
            self.status = "You are White"
        else:
            self.status = "You are Black"

        self.play_sound("game_start")

        if self.engine_to_move():
            self.request_engine_move()

    def restart(self) -> None:
        if self.engine_thinking:
            self.status = "Wait for the engine to finish thinking"
            return
        # Restart from this game's starting position (which may be an edited
        # or FEN-loaded position, not necessarily startpos).
        self.start_game(self.human_colour, fen=self.game_start_fen)

    def return_to_main_menu(self) -> None:
        # Invalidate the search immediately.  A running worker owns its engine
        # until that search returns, then closes it without posting a stale
        # move back into the menu.
        was_thinking = self.engine_thinking
        self.game_token = object()
        if was_thinking:
            self.engine = None
        else:
            self.close_engine()
        self.chess_board = chess.Board()
        self.human_colour = None
        self.flip_board = False
        self.game_started = False
        self.engine_thinking = False
        self.edit_mode = False
        self.status = "Choose a side"
        self.reset_runtime_state()
        pygame.display.set_caption("Sgurr")

    def load_fen(self, fen: str) -> None:
        try:
            board = chess.Board(fen.strip())
        except ValueError:
            self.input_error = "Invalid FEN"
            self.status = "Invalid FEN"
            return

        try:
            engine = self.make_engine()
        except Exception as exc:
            self.input_error = f"Could not load {self.engine_name}"
            self.status = f"Could not load {self.engine_label}: {exc}"
            return

        self.close_engine()
        self.chess_board = board
        self.engine = engine
        self.game_token = object()
        self.game_start_fen = board.fen()
        self.reset_runtime_state()
        self.reset_game_clocks()
        self.game_started = True
        self.flip_board = bool(
            self.auto_flip_as_black and self.human_colour == chess.BLACK
        )
        pygame.display.set_caption(f"Sgurr - {self.engine_name}")
        self.reset_eval_to_material()
        self.snap_eval_display()
        self.status = "Loaded FEN"
        self.play_sound("game_start")

        if self.engine_to_move():
            self.request_engine_move()

    def engine_to_move(self) -> bool:
        if self.game_is_over:
            return False

        if self.human_colour is None:
            return True

        return self.chess_board.turn != self.human_colour

    def human_to_move(self) -> bool:
        if self.game_is_over:
            return False

        return self.human_colour is not None and self.chess_board.turn == self.human_colour

    def update_game_over_status(self) -> None:
        self.game_is_over = self.position_or_clock_game_over()
        if not self.game_is_over:
            return

        result = self.current_game_result()

        if self.clock_flagged == chess.WHITE:
            self.status = "White loses on time"
        elif self.clock_flagged == chess.BLACK:
            self.status = "Black loses on time"
        elif result == "1-0":
            self.status = "White wins"
        elif result == "0-1":
            self.status = "Black wins"
        else:
            self.status = "Draw"

        if self.chess_board.is_checkmate() and self.game_over_reveal_at is None:
            self.game_over_reveal_at = time.time() + self.checkmate_reveal_delay

        self.play_game_over_sound()

    # ------------------------------------------------------------------
    # move making (human + promotion picker)
    # ------------------------------------------------------------------

    def promotion_options(
        self, from_square: chess.Square, to_square: chess.Square
    ) -> list[int]:
        return [
            promo for promo in PROMOTION_CHOICES
            if chess.Move(from_square, to_square, promotion=promo)
            in self.chess_board.legal_moves
        ]

    def try_human_move(self, from_square: chess.Square, to_square: chess.Square,
                       animate: bool = True) -> None:
        """Commit a plain legal move, open the promotion picker, or reject.

        `animate` is False for drag-drops (the piece was already carried to the
        target by the drag, so it should just settle) and True for click moves.
        """
        candidate = chess.Move(from_square, to_square)

        if candidate in self.chess_board.legal_moves:
            self.make_human_move(candidate, animate=animate)
            return

        if self.promotion_options(from_square, to_square):
            self.promotion_pending = (from_square, to_square)
            self._promo_animate = animate
            self.selected_square = None
            self.clear_drag_state()
            self.status = "Choose a promotion piece"
            return

        self.status = "Illegal move"
        self.play_sound("illegal")
        self.selected_square = None
        self.clear_drag_state()

    def clear_drag_state(self) -> None:
        self.dragging_piece = None
        self.dragging_from_square = None
        self.dragging_mouse_pos = (0, 0)
        self.drag_start_pos = (0, 0)
        self.drag_started = False

    def make_human_move(self, move: chess.Move, animate: bool = True) -> None:
        moving_colour = self.chess_board.turn
        was_capture = self.chess_board.is_capture(move)
        was_castle = self.chess_board.is_castling(move)
        was_promotion = move.promotion is not None
        self.chess_board.push(move)
        self.redo_stack.clear()
        self.redo_clock_stack.clear()
        self.add_move_increment(moving_colour)
        self.record_clock_snapshot()
        if animate:
            self.start_move_animation(move)
        self.play_move_sound(move, was_capture, was_castle, was_promotion, by_human=True)
        self.last_move = move
        self.selected_square = None
        self.promotion_pending = None
        self.clear_drag_state()
        # Keep the previous search score as the bar target (one ply stale but
        # far better than material); the engine's reply refreshes it.
        history_score = (material_eval_white(self.chess_board)
                         if self.game_is_over
                         else self.eval_target_cp)
        self.record_eval_point(history_score)
        self.status = f"{self.engine_name} thinking..."
        self.update_game_over_status()

        if self.engine_to_move():
            self.request_engine_move()

    def start_piece_drag(self, pos: tuple[int, int]) -> None:
        if not self.human_to_move() or self.input_mode is not None:
            return
        if self.promotion_pending is not None or self.engine_thinking:
            return

        square = self.screen_to_square(*pos)
        if square is None:
            return

        piece = self.chess_board.piece_at(square)
        if piece is None or piece.color != self.human_colour:
            return

        self.dragging_piece = piece
        self.dragging_from_square = square
        self.dragging_mouse_pos = pos
        self.drag_start_pos = pos
        self.drag_started = False

    def update_piece_drag(self, pos: tuple[int, int]) -> None:
        if self.dragging_piece is None:
            return

        self.dragging_mouse_pos = pos
        dx = pos[0] - self.drag_start_pos[0]
        dy = pos[1] - self.drag_start_pos[1]
        if dx * dx + dy * dy > 16:
            self.drag_started = True

    def finish_piece_drag(self, pos: tuple[int, int]) -> None:
        if self.dragging_piece is None or self.dragging_from_square is None:
            square = self.screen_to_square(*pos)
            if square is not None:
                self.handle_board_click(square)
            return

        from_square = self.dragging_from_square
        to_square = self.screen_to_square(*pos)
        moved_piece = self.drag_started and to_square is not None and to_square != from_square

        if moved_piece:
            self.clear_drag_state()
            # Drag-drop: the piece already followed the cursor to the target,
            # so settle it in place rather than sliding from the origin.
            self.try_human_move(from_square, to_square, animate=False)
        else:
            self.clear_drag_state()
            self.handle_board_click(from_square)

    def handle_board_click(self, square: chess.Square) -> None:
        if not self.human_to_move() or self.input_mode is not None:
            return
        if self.promotion_pending is not None or self.engine_thinking:
            return

        piece = self.chess_board.piece_at(square)

        if self.selected_square is None:
            if piece is not None and piece.color == self.human_colour:
                self.selected_square = square
            return

        if square == self.selected_square:
            self.selected_square = None
            return

        if piece is not None and piece.color == self.human_colour:
            self.selected_square = square
            return

        from_square = self.selected_square
        self.selected_square = None
        self.try_human_move(from_square, square)

    # ------------------------------------------------------------------
    # threaded engine search
    # ------------------------------------------------------------------

    def request_engine_move(self) -> None:
        if self.engine_thinking or self.engine is None:
            return
        if self.game_is_over:
            self.update_game_over_status()
            return
        if self.game_clocks.get(self.chess_board.turn, 0.0) <= 0.0:
            self.flag_clock(self.chess_board.turn)
            return

        self.engine_thinking = True
        self.status = f"{self.engine_name} thinking..."

        snapshot = self.chess_board.copy()
        engine = self.engine
        depth = self.engine_depth
        time_limit = self.engine_move_time_limit()
        clock_limit = self.current_engine_clock_limit()
        token = self.game_token

        def worker() -> None:
            try:
                result = engine.search_best_move(
                    snapshot,
                    max_depth=depth,
                    time_limit=time_limit,
                    clock_limit=clock_limit,
                    game_token=token,
                )
                if token is not self.game_token:
                    engine.close()
                    return
                self.search_queue.put(("ok", (token, result)))
            except Exception as exc:
                if token is not self.game_token:
                    try:
                        engine.close()
                    except Exception:
                        pass
                    return
                self.search_queue.put(("error", (token, str(exc))))

        threading.Thread(target=worker, daemon=True).start()

    def poll_engine_result(self) -> None:
        while True:
            try:
                kind, payload = self.search_queue.get_nowait()
            except queue.Empty:
                return

            token, result_payload = payload
            if token is not self.game_token:
                continue

            self.engine_thinking = False

            if kind == "error":
                self.status = f"{self.engine_name} error: {result_payload}"
                return

            self.apply_engine_result(result_payload)
            return

    def apply_engine_result(self, result: SearchResult) -> None:
        if result.best_move is None:
            self.status = f"{self.engine_name} found no move"
            return

        move = result.best_move

        if move not in self.chess_board.legal_moves:
            # Stale result (e.g. the position changed under an error path).
            self.status = f"{self.engine_name} illegal move: {move}"
            return

        moving_colour = self.chess_board.turn
        self.last_engine_score = result.score
        was_capture = self.chess_board.is_capture(move)
        was_castle = self.chess_board.is_castling(move)
        was_promotion = move.promotion is not None
        self.chess_board.push(move)
        self.redo_stack.clear()
        self.redo_clock_stack.clear()
        self.add_move_increment(moving_colour)
        self.record_clock_snapshot()
        self.start_move_animation(move)
        self.play_move_sound(move, was_capture, was_castle, was_promotion, by_human=False)
        self.last_move = move

        # All C++ modes report a white-relative search score, so the eval bar
        # can use it directly; the Python engine's score is side-to-move
        # relative, so use its static eval instead.
        if self.engine_choice in CPP_ENGINE_CHOICES:
            self.eval_target_cp = result.score
            self.have_search_eval = True
        elif self.engine is not None:
            try:
                self.eval_target_cp = self.engine.quick_white_eval(self.chess_board)
                self.have_search_eval = True
            except Exception:
                pass

        self.record_eval_point(self.eval_target_cp)

        if SHOW_ENGINE_INFO:
            self.engine_info = (
                f"depth {result.depth}, "
                f"nodes {result.nodes}, "
                f"{result.time_taken:.2f}s, "
                f"score {result.score}"
            )

        self.status = "Your move" if self.human_to_move() else f"{self.engine_name} to move"
        self.update_game_over_status()

    # ------------------------------------------------------------------
    # history navigation (undo / redo)
    # ------------------------------------------------------------------

    def after_history_change(self, message: str) -> None:
        self.clock_flagged = None
        self.game_is_over = self.chess_board.is_game_over(claim_draw=True)
        self.last_move = self.chess_board.peek() if self.chess_board.move_stack else None
        self.selected_square = None
        self.promotion_pending = None
        self.animation = None
        current_ply = len(self.chess_board.move_stack)
        self.eval_history = [point for point in self.eval_history if point[0] <= current_ply]
        self.restore_clock_from_history()
        self.clear_drag_state()
        self.engine_info = ""
        self.game_over_sound_played = False
        self.game_over_reveal_at = None
        # The stored search score belongs to a different position now.
        self.reset_eval_to_material()
        self.record_eval_point(self.eval_target_cp)
        self.status = message

    def undo_ply(self) -> None:
        if self.engine_thinking or not self.game_started or self.input_mode is not None:
            return
        if not self.chess_board.move_stack:
            self.status = "At the start"
            return
        if len(self.clock_history) > 1:
            self.redo_clock_stack.append(self.clock_history.pop())
        else:
            self.redo_clock_stack.append(self.clock_snapshot())
        self.redo_stack.append(self.chess_board.pop())
        self.after_history_change(
            f"Move {len(self.chess_board.move_stack)} - back"
        )

    def redo_ply(self) -> None:
        if self.engine_thinking or not self.game_started or self.input_mode is not None:
            return
        if not self.redo_stack:
            self.status = "At the latest move"
            return
        self.chess_board.push(self.redo_stack.pop())
        if self.redo_clock_stack:
            snapshot = self.redo_clock_stack.pop()
            self.clock_history = self.clock_history[:len(self.chess_board.move_stack)]
            self.clock_history.append(snapshot)
            self.game_clocks = {
                chess.WHITE: float(snapshot.get(chess.WHITE, self.time_control.base_seconds)),
                chess.BLACK: float(snapshot.get(chess.BLACK, self.time_control.base_seconds)),
            }
        self.after_history_change(
            f"Move {len(self.chess_board.move_stack)} - forward"
        )

    def undo_move(self) -> None:
        """U key: undo a full move pair when facing the engine."""
        if not self.game_started or self.engine_thinking or self.input_mode is not None:
            return

        if len(self.chess_board.move_stack) == 0:
            self.status = "Nothing to undo"
            return

        if self.human_colour is not None and self.human_to_move():
            undo_count = min(2, len(self.chess_board.move_stack))
        else:
            undo_count = 1

        for _ in range(undo_count):
            if len(self.clock_history) > 1:
                self.redo_clock_stack.append(self.clock_history.pop())
            else:
                self.redo_clock_stack.append(self.clock_snapshot())
            self.redo_stack.append(self.chess_board.pop())

        self.after_history_change("Move undone")

    def trigger_engine_move(self) -> None:
        """G key: ask the engine to move now (after navigation, or when the
        watch-mode pause leaves it the engine's turn)."""
        if not self.game_started or self.engine_thinking or self.input_mode is not None:
            return
        if self.edit_mode or self.promotion_pending is not None:
            return
        if not self.engine_to_move():
            self.status = "Not the engine's turn"
            return
        self.redo_stack.clear()
        self.request_engine_move()

    # ------------------------------------------------------------------
    # board editor
    # ------------------------------------------------------------------

    def enter_edit_mode(self) -> None:
        if self.engine_thinking:
            self.status = "Wait for the engine to finish thinking"
            return
        if self.input_mode is not None:
            return

        # Carry the current position into the editor; remember which side the
        # human should get when play resumes.
        source = self.chess_board if self.game_started else chess.Board()
        self.edit_board = chess.Board(None)
        for square, piece in source.piece_map().items():
            self.edit_board.set_piece_at(square, piece)
        self.edit_turn = source.turn
        self.edit_return_colour = (
            self.human_colour if self.game_started else chess.WHITE
        )
        self.edit_odds_recipient = "you"
        self.edit_brush = None
        self.edit_drag_piece = None
        self.edit_mode = True
        self.selected_square = None
        self.promotion_pending = None
        self.animation = None
        self.clear_drag_state()
        self.status = "Board editor"

    def exit_edit_mode(self, message: str = "Editor cancelled") -> None:
        self.edit_mode = False
        self.edit_brush = None
        self.edit_drag_piece = None
        self.status = message

    def compose_edit_fen(self) -> str:
        """FEN from the edit board: chosen side to move, castling rights
        derived from king/rook start squares, no en passant."""
        placement = self.edit_board.board_fen()
        turn = "w" if self.edit_turn == chess.WHITE else "b"

        rights = ""
        if self.edit_board.piece_at(chess.E1) == chess.Piece(chess.KING, chess.WHITE):
            if self.edit_board.piece_at(chess.H1) == chess.Piece(chess.ROOK, chess.WHITE):
                rights += "K"
            if self.edit_board.piece_at(chess.A1) == chess.Piece(chess.ROOK, chess.WHITE):
                rights += "Q"
        if self.edit_board.piece_at(chess.E8) == chess.Piece(chess.KING, chess.BLACK):
            if self.edit_board.piece_at(chess.H8) == chess.Piece(chess.ROOK, chess.BLACK):
                rights += "k"
            if self.edit_board.piece_at(chess.A8) == chess.Piece(chess.ROOK, chess.BLACK):
                rights += "q"

        return f"{placement} {turn} {rights or '-'} - 0 1"

    def edit_player_label(self) -> str:
        if self.edit_return_colour == chess.WHITE:
            return "You play: White"
        if self.edit_return_colour == chess.BLACK:
            return "You play: Black"
        return "Mode: Watch"

    def cycle_edit_player(self) -> None:
        options: tuple[chess.Color | None, ...] = (chess.WHITE, chess.BLACK, None)
        try:
            index = options.index(self.edit_return_colour)
        except ValueError:
            index = 0
        self.edit_return_colour = options[(index + 1) % len(options)]
        self.status = self.edit_player_label()

    def edit_odds_label(self) -> str:
        target = "You" if self.edit_odds_recipient == "you" else "Engine"
        return f"Odds for: {target}"

    def cycle_edit_odds_recipient(self) -> None:
        try:
            index = ODDS_RECIPIENTS.index(self.edit_odds_recipient)
        except ValueError:
            index = 0
        self.edit_odds_recipient = ODDS_RECIPIENTS[(index + 1) % len(ODDS_RECIPIENTS)]
        self.status = self.edit_odds_label()

    @staticmethod
    def king_distance(a: chess.Square, b: chess.Square) -> int:
        return max(
            abs(chess.square_file(a) - chess.square_file(b)),
            abs(chess.square_rank(a) - chess.square_rank(b)),
        )

    @staticmethod
    def square_colour(square: chess.Square) -> int:
        return (chess.square_file(square) + chess.square_rank(square)) % 2

    @staticmethod
    def square_for_colour(square: chess.Square, colour: chess.Color) -> chess.Square:
        if colour == chess.WHITE:
            return square
        return chess.square(chess.square_file(square), 7 - chess.square_rank(square))

    def drill_attacker_colour(self) -> chess.Color:
        if self.edit_return_colour in (chess.WHITE, chess.BLACK):
            return self.edit_return_colour
        return self.edit_turn

    def odds_removed_colour(self) -> chess.Color | None:
        if self.edit_return_colour not in (chess.WHITE, chess.BLACK):
            return None

        recipient = (
            self.edit_return_colour
            if self.edit_odds_recipient == "you"
            else not self.edit_return_colour
        )
        return not recipient

    def bishops_are_compatible(
        self, piece_types: tuple[chess.PieceType, ...],
        piece_squares: list[chess.Square]
    ) -> bool:
        bishop_colours = [
            self.square_colour(square)
            for piece_type, square in zip(piece_types, piece_squares)
            if piece_type == chess.BISHOP
        ]
        return len(bishop_colours) < 2 or len(set(bishop_colours)) > 1

    def make_drill_board(
        self, attacker: chess.Color, piece_types: tuple[chess.PieceType, ...]
    ) -> chess.Board | None:
        defender = not attacker
        squares = list(chess.SQUARES)
        for _ in range(8000):
            chosen = random.sample(squares, 2 + len(piece_types))
            attacker_king, defender_king = chosen[:2]
            piece_squares = chosen[2:]
            if self.king_distance(attacker_king, defender_king) <= 1:
                continue
            if any(self.king_distance(square, defender_king) <= 1
                   for square in piece_squares):
                continue
            if not self.bishops_are_compatible(piece_types, piece_squares):
                continue

            board = chess.Board(None)
            board.set_piece_at(attacker_king, chess.Piece(chess.KING, attacker))
            board.set_piece_at(defender_king, chess.Piece(chess.KING, defender))
            for piece_type, square in zip(piece_types, piece_squares):
                board.set_piece_at(square, chess.Piece(piece_type, attacker))
            board.turn = self.edit_turn

            if board.is_valid() and not board.is_game_over(claim_draw=True):
                return board

        return self.fallback_drill_board(attacker, piece_types)

    def fallback_drill_board(
        self, attacker: chess.Color, piece_types: tuple[chess.PieceType, ...]
    ) -> chess.Board | None:
        if attacker == chess.WHITE:
            attacker_king, defender_king = chess.E4, chess.E8
            solo_square = chess.D4
            rook_pair = (chess.D4, chess.H4)
            minor_pair = (chess.C4, chess.F4)
        else:
            attacker_king, defender_king = chess.E5, chess.E1
            solo_square = chess.D5
            rook_pair = (chess.D5, chess.H5)
            minor_pair = (chess.C5, chess.F5)

        if len(piece_types) == 1:
            fallback_squares = (solo_square,)
        elif piece_types == (chess.ROOK, chess.ROOK):
            fallback_squares = rook_pair
        elif piece_types in (
            (chess.BISHOP, chess.BISHOP),
            (chess.BISHOP, chess.KNIGHT),
        ):
            fallback_squares = minor_pair
        else:
            fallback_squares = rook_pair + minor_pair

        board = chess.Board(None)
        board.set_piece_at(attacker_king, chess.Piece(chess.KING, attacker))
        board.set_piece_at(defender_king, chess.Piece(chess.KING, not attacker))
        for piece_type, square in zip(piece_types, fallback_squares):
            board.set_piece_at(square, chess.Piece(piece_type, attacker))
        board.turn = self.edit_turn
        if board.is_valid() and not board.is_game_over(claim_draw=True):
            return board
        return None

    def load_checkmate_drill(self, key: str) -> None:
        drill = CHECKMATE_DRILL_BY_KEY.get(key)
        if drill is None:
            self.status = "Unknown drill"
            self.play_sound("illegal")
            return

        label, piece_types = drill
        attacker = self.drill_attacker_colour()
        board = self.make_drill_board(attacker, piece_types)
        if board is None:
            self.status = "Could not create drill"
            self.play_sound("illegal")
            return

        self.edit_board = board
        self.edit_brush = None
        self.edit_drag_piece = None
        attacker_name = "White" if attacker == chess.WHITE else "Black"
        self.status = f"{attacker_name} {label} drill"

    def load_odds_preset(self, key: str) -> None:
        preset = ODDS_PRESET_BY_KEY.get(key)
        if preset is None:
            self.status = "Unknown odds preset"
            self.play_sound("illegal")
            return

        removed_colour = self.odds_removed_colour()
        if removed_colour is None:
            self.status = "Choose White or Black before odds"
            self.play_sound("illegal")
            return

        label, base_squares = preset
        source = chess.Board()
        self.edit_board = chess.Board(None)
        for square, piece in source.piece_map().items():
            self.edit_board.set_piece_at(square, piece)

        for base_square in base_squares:
            self.edit_board.remove_piece_at(
                self.square_for_colour(base_square, removed_colour)
            )

        self.edit_turn = chess.WHITE
        self.edit_brush = None
        self.edit_drag_piece = None
        target_name = "You" if self.edit_odds_recipient == "you" else "Engine"
        verb = "get" if self.edit_odds_recipient == "you" else "gets"
        self.status = f"{target_name} {verb} {label.lower()}"

    def edit_position_error(self) -> str | None:
        """None if the edited position is playable, else a short reason."""
        try:
            board = chess.Board(self.compose_edit_fen())
        except ValueError:
            return "Malformed position"

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

    def finish_edit_mode(self) -> None:
        error = self.edit_position_error()
        if error is not None:
            self.status = f"Fix position: {error}"
            self.play_sound("illegal")
            return

        fen = self.compose_edit_fen()
        self.edit_mode = False
        self.edit_brush = None
        self.edit_drag_piece = None
        self.human_colour = self.edit_return_colour
        self.load_fen(fen)

    def handle_edit_click(self, pos: tuple[int, int], button: int) -> None:
        # Right-click: clear the brush, else delete the piece under the cursor.
        if button == 3:
            if self.edit_brush is not None:
                self.edit_brush = None
                return
            square = self.screen_to_square(*pos)
            if square is not None:
                self.edit_board.remove_piece_at(square)
            return

        if button != 1:
            return

        for rect, piece in self.edit_palette_rects:
            if rect.collidepoint(pos):
                if self.edit_brush is not None and self.edit_brush == piece:
                    self.edit_brush = None      # toggle off
                else:
                    self.edit_brush = piece
                return

        for btn in self.edit_buttons:
            if btn.rect.collidepoint(pos):
                self.play_sound("button")
                self.handle_edit_action(btn.action)
                return

        square = self.screen_to_square(*pos)
        if square is None:
            return

        if self.edit_brush is not None:
            # Brush placement: repeated clicks keep placing the same piece.
            self.edit_board.set_piece_at(square, chess.Piece(
                self.edit_brush.piece_type, self.edit_brush.color))
            return

        piece = self.edit_board.piece_at(square)
        if piece is not None:
            # Pick the piece up; it is placed (or deleted) on mouse-up.
            self.edit_board.remove_piece_at(square)
            self.edit_drag_piece = piece
            self.edit_drag_mouse = pos

    def handle_edit_release(self, pos: tuple[int, int]) -> None:
        if self.edit_drag_piece is None:
            return
        square = self.screen_to_square(*pos)
        if square is not None:
            self.edit_board.set_piece_at(square, self.edit_drag_piece)
        # Dropped off the board -> deleted.
        self.edit_drag_piece = None

    def handle_edit_action(self, action: str) -> None:
        if action == "edit_done":
            self.finish_edit_mode()
        elif action == "edit_cancel":
            self.exit_edit_mode()
        elif action == "edit_clear":
            self.edit_board = chess.Board(None)
        elif action == "edit_start":
            source = chess.Board()
            self.edit_board = chess.Board(None)
            for square, piece in source.piece_map().items():
                self.edit_board.set_piece_at(square, piece)
            self.edit_turn = chess.WHITE
        elif action.startswith("edit_drill:"):
            self.load_checkmate_drill(action.split(":", 1)[1])
        elif action.startswith("edit_odds:"):
            self.load_odds_preset(action.split(":", 1)[1])
        elif action == "edit_player":
            self.cycle_edit_player()
        elif action == "edit_odds_for":
            self.cycle_edit_odds_recipient()
        elif action == "edit_turn":
            self.edit_turn = not self.edit_turn
            self.status = f"First move: {'White' if self.edit_turn == chess.WHITE else 'Black'}"
        elif action == "edit_copyfen":
            self.copy_fen_to_clipboard()

    # ------------------------------------------------------------------
    # clipboard
    # ------------------------------------------------------------------

    def copy_fen_to_clipboard(self) -> None:
        fen = self.compose_edit_fen() if self.edit_mode else self.chess_board.fen()
        if copy_text_to_clipboard(fen):
            self.status = "FEN copied to clipboard"
        else:
            self.status = f"FEN: {fen}"

    # ------------------------------------------------------------------

    def export_pgn(self) -> None:
        out_dir = ANALYSIS_DIR
        out_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = out_dir / f"Sgurr_{self.engine_choice}_gui_game_{timestamp}.pgn"

        # from_board carries SetUp/FEN headers automatically for games that
        # started from an edited or loaded position.
        game = chess.pgn.Game.from_board(self.chess_board)
        game.headers["Event"] = f"{self.engine_name} GUI Game"
        game.headers["Date"] = datetime.now().strftime("%Y.%m.%d")
        game.headers["White"] = self.player_name(chess.WHITE)
        game.headers["Black"] = self.player_name(chess.BLACK)
        game.headers["Result"] = self.current_game_result()
        game.headers["TimeControl"] = (
            f"{int(self.time_control.base_seconds)}+"
            f"{int(self.time_control.increment_seconds)}"
        )

        path.write_text(str(game) + "\n\n", encoding="utf-8")
        self.status = f"PGN exported: {path}"

    def player_name(self, colour: chess.Color) -> str:
        engine_name = self.engine_profile["pgn_name"]

        if self.human_colour is None:
            return engine_name

        if self.human_colour == colour:
            return "Human"

        return engine_name

    def begin_fen_input(self) -> None:
        if self.engine_thinking:
            self.status = "Wait for the engine to finish thinking"
            return
        self.input_mode = "fen"
        self.enable_text_input_repeat()
        self.keyboard_focus = False
        self.text_input = self.chess_board.fen() if self.game_started else ""
        self.input_error = ""
        self.status = "Paste/type FEN, Enter to load"

    def cancel_input(self) -> None:
        self.disable_text_input_repeat()
        self.input_mode = None
        self.text_input = ""
        self.input_error = ""
        self.status = "Input cancelled"

    def material_score(self) -> tuple[int, int, int]:
        white_material = 0
        black_material = 0

        for piece in self.chess_board.piece_map().values():
            value = MATERIAL_VALUES[piece.piece_type]

            if piece.color == chess.WHITE:
                white_material += value
            else:
                black_material += value

        return white_material, black_material, white_material - black_material

    def captured_pieces(self) -> tuple[list[int], list[int]]:
        starting_counts = {
            chess.PAWN: 8,
            chess.KNIGHT: 2,
            chess.BISHOP: 2,
            chess.ROOK: 2,
            chess.QUEEN: 1,
        }

        white_captured: list[int] = []
        black_captured: list[int] = []

        for piece_type, starting_count in starting_counts.items():
            white_remaining = len(self.chess_board.pieces(piece_type, chess.WHITE))
            black_remaining = len(self.chess_board.pieces(piece_type, chess.BLACK))

            white_captured.extend([piece_type] * max(0, starting_count - white_remaining))
            black_captured.extend([piece_type] * max(0, starting_count - black_remaining))

        return white_captured, black_captured

    def move_rows(self) -> list[tuple[int, str, str]]:
        """Return SAN history as numbered white/black columns."""
        try:
            replay = chess.Board(self.game_start_fen)
        except ValueError:
            replay = chess.Board()
        rows: list[list[object]] = []
        for move in self.chess_board.move_stack:
            number = replay.fullmove_number
            side = replay.turn
            try:
                san = replay.san(move)
            except Exception:
                san = move.uci()
            if not rows or rows[-1][0] != number:
                rows.append([number, "", ""])
            rows[-1][1 if side == chess.WHITE else 2] = san
            replay.push(move)
        return [(int(number), str(white), str(black))
                for number, white, black in rows]

    def display_eval_pawns(self) -> float:
        if self.edit_mode:
            return material_eval_white(self.edit_board) / 100.0

        if self.chess_board.is_checkmate():
            return -99.0 if self.chess_board.turn == chess.WHITE else 99.0

        if self.chess_board.is_stalemate() or self.chess_board.is_insufficient_material():
            return 0.0

        return self.eval_target_cp / 100.0

    def eval_to_bar_fraction(self, eval_pawns: float) -> float:
        eval_pawns = max(-8.0, min(8.0, eval_pawns))
        return 1.0 / (1.0 + 10 ** (-eval_pawns / 4.0))

    # ------------------------------------------------------------------
    # graphics primitives (theme-aware, cached)
    # ------------------------------------------------------------------

    def vgradient(self, w: int, h: int, top: tuple, bottom: tuple) -> pygame.Surface:
        key = ("grad", w, h, top, bottom)
        cached = self._grad_cache.get(key)
        if cached is not None:
            return cached
        surf = pygame.Surface((w, h)).convert()
        denom = max(1, h - 1)
        for yy in range(h):
            t = yy / denom
            col = (
                int(top[0] + (bottom[0] - top[0]) * t),
                int(top[1] + (bottom[1] - top[1]) * t),
                int(top[2] + (bottom[2] - top[2]) * t),
            )
            pygame.draw.line(surf, col, (0, yy), (w, yy))
        self._grad_cache[key] = surf
        return surf

    def themed_background(self) -> pygame.Surface:
        cached = self._motif_cache.get(self.theme_name)
        if cached is not None:
            return cached

        surf = self.vgradient(WINDOW_WIDTH, WINDOW_HEIGHT,
                              self.theme.background, self.theme.background2).copy()
        motif = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)

        if self.theme_name == "neon":
            # Two distant ridgelines and sparse stars: recognisably Sgurr,
            # quiet enough not to compete with controls.
            pygame.draw.polygon(motif, (*self.theme.accent, 11), [
                (0, WINDOW_HEIGHT), (0, 610), (150, 510), (260, 590),
                (430, 430), (590, 575), (760, 455), (930, 600),
                (WINDOW_WIDTH, 500), (WINDOW_WIDTH, WINDOW_HEIGHT),
            ])
            pygame.draw.lines(motif, (*self.theme.accent2, 24), False, [
                (0, 610), (150, 510), (260, 590), (430, 430), (590, 575),
                (760, 455), (930, 600), (WINDOW_WIDTH, 500),
            ], 2)
            for i in range(24):
                sx = 34 + (i * 137) % (WINDOW_WIDTH - 60)
                sy = 26 + (i * 83) % 330
                pygame.draw.circle(motif, (*self.theme.text, 24), (sx, sy), 1)
        elif self.theme_name == "modern":
            for offset in range(-300, WINDOW_WIDTH + 300, 220):
                pygame.draw.polygon(motif, (*self.theme.accent2, 8), [
                    (offset, 0), (offset + 150, 0),
                    (offset + 470, WINDOW_HEIGHT), (offset + 320, WINDOW_HEIGHT),
                ])
        elif self.theme_name == "wood":
            for index, y in enumerate(range(28, WINDOW_HEIGHT, 47)):
                points = []
                for x in range(0, WINDOW_WIDTH + 1, 48):
                    drift = ((x // 48 * 7 + index * 5) % 13) - 6
                    points.append((x, y + drift))
                pygame.draw.lines(motif, (*self.theme.accent, 12), False, points, 1)
        elif self.theme_name == "light":  # Subtle paper fibre, not digital noise.
            for i in range(110):
                px = (i * 97 + 31) % WINDOW_WIDTH
                py = (i * 53 + 17) % WINDOW_HEIGHT
                length = 2 + (i % 4)
                pygame.draw.line(motif, (*self.theme.panel_edge, 18),
                                 (px, py), (px + length, py), 1)
        elif self.theme_name == "highland":
            # Layered, misty ridges in heather and old-gold tones.
            rear = [(0, 590), (115, 500), (230, 568), (390, 420),
                    (530, 550), (675, 455), (WINDOW_WIDTH, 570)]
            front = [(0, 680), (160, 565), (290, 655), (470, 505),
                     (610, 625), (760, 520), (WINDOW_WIDTH, 645)]
            pygame.draw.lines(motif, (*self.theme.accent, 24), False, rear, 2)
            pygame.draw.lines(motif, (*self.theme.accent2, 17), False, front, 2)
            for i in range(18):
                px = (i * 173 + 41) % WINDOW_WIDTH
                py = 55 + (i * 71) % 300
                pygame.draw.circle(motif, (*self.theme.text, 15), (px, py), 18 + i % 3 * 9)
        elif self.theme_name == "ocean":
            # Long, restrained wave lines keep the dark seascape calm.
            for row, y in enumerate(range(420, WINDOW_HEIGHT + 60, 54)):
                points = []
                for x in range(-40, WINDOW_WIDTH + 80, 40):
                    wave = ((x // 40 + row * 2) % 6)
                    wave = wave if wave <= 3 else 6 - wave
                    points.append((x, y - wave * 5))
                colour = self.theme.accent if row % 2 == 0 else self.theme.accent2
                pygame.draw.lines(motif, (*colour, 13), False, points, 1)
        elif self.theme_name == "frost":
            # Fine ice-crystal facets, visible only in the open background.
            for i in range(34):
                px = (i * 127 + 19) % WINDOW_WIDTH
                py = (i * 79 + 31) % WINDOW_HEIGHT
                length = 5 + i % 5
                colour = self.theme.accent if i % 3 else self.theme.accent2
                pygame.draw.line(motif, (*colour, 18),
                                 (px - length, py), (px + length, py), 1)
                pygame.draw.line(motif, (*colour, 18),
                                 (px, py - length), (px, py + length), 1)

        surf.blit(motif, (0, 0))
        self._motif_cache[self.theme_name] = surf
        return surf

    def get_piece_surface(self, piece: chess.Piece, font_size: int = 64) -> pygame.Surface:
        key = (self.theme_name, piece.color, piece.piece_type, font_size)
        cached = self._piece_cache.get(key)
        if cached is not None:
            return cached

        glyph = SOLID_GLYPHS[piece.piece_type]
        is_white = piece.color == chess.WHITE
        fill = self.theme.piece_white if is_white else self.theme.piece_black
        edge = self.theme.piece_white_edge if is_white else self.theme.piece_black_edge

        font = self.board_font if font_size == 64 else pygame.font.SysFont(
            PIECE_FONT_NAME, font_size * PIECE_SUPERSAMPLE
        )
        fill_surf = font.render(glyph, True, fill).convert_alpha()
        edge_surf = font.render(glyph, True, edge).convert_alpha()
        shadow_surf = font.render(glyph, True, (0, 0, 0)).convert_alpha()
        shadow_surf.set_alpha(80)

        outline_width = max(1, round(font_size * 0.035)) * PIECE_SUPERSAMPLE
        pad = max(4, round(font_size * 0.09)) * PIECE_SUPERSAMPLE
        shadow_x = max(1, round(font_size * 0.035)) * PIECE_SUPERSAMPLE
        shadow_y = max(2, round(font_size * 0.05)) * PIECE_SUPERSAMPLE
        w, h = fill_surf.get_size()
        core = pygame.Surface((w + pad * 2, h + pad * 2), pygame.SRCALPHA)
        for dx in range(-outline_width, outline_width + 1):
            for dy in range(-outline_width, outline_width + 1):
                if (dx or dy) and dx * dx + dy * dy <= outline_width * outline_width + 1:
                    core.blit(edge_surf, (pad + dx, pad + dy))
        core.blit(fill_surf, (pad, pad))

        bounds = core.get_bounding_rect()
        extra = 6 * PIECE_SUPERSAMPLE
        canvas_w = bounds.width + extra * 2 + shadow_x
        canvas_h = bounds.height + extra * 2 + shadow_y
        canvas = pygame.Surface((canvas_w, canvas_h), pygame.SRCALPHA)
        ox = (canvas_w - bounds.width) // 2 - bounds.x
        oy = (canvas_h - bounds.height) // 2 - bounds.y
        canvas.blit(shadow_surf, (ox + pad + shadow_x, oy + pad + shadow_y))
        for dx in range(-outline_width, outline_width + 1):
            for dy in range(-outline_width, outline_width + 1):
                if (dx or dy) and dx * dx + dy * dy <= outline_width * outline_width + 1:
                    canvas.blit(edge_surf, (ox + pad + dx, oy + pad + dy))
        canvas.blit(fill_surf, (ox + pad, oy + pad))

        if PIECE_SUPERSAMPLE > 1:
            canvas = pygame.transform.smoothscale(
                canvas,
                (max(1, canvas.get_width() // PIECE_SUPERSAMPLE),
                 max(1, canvas.get_height() // PIECE_SUPERSAMPLE)),
            )
        self._piece_cache[key] = canvas
        return canvas

    def blit_piece(self, piece: chess.Piece, center: tuple[float, float],
                   size: int | None = None) -> None:
        if size is None:
            surf = self.get_piece_surface(piece)
        else:
            key = ("scaled", self.theme_name, piece.color, piece.piece_type, size)
            surf = self._piece_cache.get(key)
            if surf is None:
                source = self.get_piece_surface(piece, max(64, int(size * 1.45)))
                scale = size / max(1, max(source.get_width(), source.get_height()))
                scaled_size = (
                    max(1, int(source.get_width() * scale)),
                    max(1, int(source.get_height() * scale)),
                )
                surf = pygame.transform.smoothscale(source, scaled_size)
                self._piece_cache[key] = surf
        rect = surf.get_rect(center=(int(center[0]), int(center[1])))
        self.screen.blit(surf, rect)

    def get_check_glow(self) -> pygame.Surface:
        key = (self.theme_name,)
        cached = self._glow_cache.get(key)
        if cached is not None:
            return cached
        size = int(SQUARE_SIZE * 1.4)
        surf = pygame.Surface((size, size), pygame.SRCALPHA)
        cx = size // 2
        r, g, b = self.theme.check_glow
        for radius in range(cx, 0, -1):
            t = 1 - radius / cx
            alpha = int(150 * (t * t))
            pygame.draw.circle(surf, (r, g, b, alpha), (cx, cx), radius)
        self._glow_cache[key] = surf
        return surf

    def ui_font(self, size: int, bold: bool = True) -> pygame.font.Font:
        key = (size, bold)
        cached = self._font_cache.get(key)
        if cached is None:
            cached = pygame.font.SysFont(UI_FONT_STACK, size, bold=bold)
            self._font_cache[key] = cached
        return cached

    def text_surface(self, font: pygame.font.Font, text: str,
                     colour: tuple) -> pygame.Surface:
        key = (id(font), text, tuple(colour))
        cached = self._text_cache.get(key)
        if cached is None:
            if len(self._text_cache) >= 2048:
                self._text_cache.clear()
            cached = font.render(text, True, colour)
            self._text_cache[key] = cached
        return cached

    def fit_font(self, text: str, max_w: int, max_size: int = 22,
                 min_size: int = 13, bold: bool = True) -> pygame.font.Font:
        """Largest UI font (within the range) whose rendering of `text` fits
        `max_w`; shrinks so long labels never spill out of their box."""
        for size in range(max_size, min_size, -1):
            font = self.ui_font(size, bold)
            if font.size(text)[0] <= max_w:
                return font
        return self.ui_font(min_size, bold)

    @staticmethod
    def mix_colour(a: tuple, b: tuple, amount: float) -> tuple:
        return tuple(int(a[i] + (b[i] - a[i]) * amount) for i in range(3))

    @staticmethod
    def contrast_colour(background: tuple) -> tuple:
        luminance = (background[0] * 299 + background[1] * 587 + background[2] * 114) / 1000
        return (18, 21, 27) if luminance > 150 else (248, 250, 253)

    def update_viewport(self, width: int, height: int) -> None:
        width, height = max(640, width), max(400, height)
        self.window_size = (width, height)
        scale = min(width / WINDOW_WIDTH, height / WINDOW_HEIGHT)
        vw, vh = int(WINDOW_WIDTH * scale), int(WINDOW_HEIGHT * scale)
        self.viewport = pygame.Rect((width - vw) // 2, (height - vh) // 2, vw, vh)
        if hasattr(self, "_preferences_dirty") and not getattr(self, "fullscreen", False):
            self.mark_preferences_dirty()

    def to_logical(self, pos: tuple[int, int]) -> tuple[int, int]:
        if self.viewport.width <= 0 or self.viewport.height <= 0:
            return pos
        x = int((pos[0] - self.viewport.x) * WINDOW_WIDTH / self.viewport.width)
        y = int((pos[1] - self.viewport.y) * WINDOW_HEIGHT / self.viewport.height)
        return x, y

    def logical_mouse_pos(self) -> tuple[int, int]:
        return self.to_logical(pygame.mouse.get_pos())

    def present(self) -> None:
        self.window.fill(self.theme.background2)
        if self.viewport.size == (WINDOW_WIDTH, WINDOW_HEIGHT):
            self.window.blit(self.screen, self.viewport.topleft)
        else:
            native_target = self.window.subsurface(self.viewport)
            scale = max(
                self.viewport.width / WINDOW_WIDTH,
                self.viewport.height / WINDOW_HEIGHT,
            )
            if scale >= SHARP_UPSCALE_THRESHOLD:
                # Fullscreen was previously a fractional smooth upscale of the
                # whole logical canvas, which made the board and pieces mushy.
                # Nearest upscale keeps edges crisp until the renderer becomes
                # fully native-resolution in a future web/native rewrite.
                pygame.transform.scale(self.screen, self.viewport.size, native_target)
            else:
                pygame.transform.smoothscale(
                    self.screen, self.viewport.size, native_target
                )

    def toggle_fullscreen(self) -> None:
        if self.fullscreen:
            self.fullscreen = False
            self.window = self.create_window(self.windowed_size)
            self.update_viewport(*self.windowed_size)
            self.status = "Windowed"
            return

        self.windowed_size = self.window_size
        size = self.desktop_size()
        self.fullscreen = True
        self.window = self.create_fullscreen_window(size)
        self.update_viewport(*size)
        self.status = "Fullscreen"

    def draw_card(self, rect: pygame.Rect, *, fill: tuple | None = None,
                  border: tuple | None = None, radius: int = 14,
                  shadow: bool = True) -> None:
        if shadow:
            shadow_surf = pygame.Surface((rect.width + 12, rect.height + 12), pygame.SRCALPHA)
            pygame.draw.rect(shadow_surf, (0, 0, 0, 55),
                             pygame.Rect(5, 6, rect.width, rect.height),
                             border_radius=radius)
            self.screen.blit(shadow_surf, (rect.x - 5, rect.y - 5))
        pygame.draw.rect(self.screen, fill or self.theme.panel, rect,
                         border_radius=radius)
        pygame.draw.rect(self.screen, border or self.theme.panel_edge, rect, 1,
                         border_radius=radius)

    def draw_section_label(self, text: str, x: int, y: int) -> None:
        label = self.text_surface(self.ui_font(12, True), text.upper(), self.theme.muted)
        self.screen.blit(label, (x, y))

    def draw_button(self, rect: pygame.Rect, label: str, *,
                    variant: str = "secondary", accent_border: bool = False,
                    font: pygame.font.Font | None = None,
                    focused: bool = False) -> None:
        mouse_pos = self.logical_mouse_pos()
        hovered = rect.collidepoint(mouse_pos)
        pressed = hovered and pygame.mouse.get_pressed()[0]

        if variant == "primary":
            base = self.theme.accent
            text_colour = self.contrast_colour(base)
            border = self.mix_colour(base, (255, 255, 255), 0.18)
        elif variant == "primary_alt":
            base = self.theme.accent2
            text_colour = self.contrast_colour(base)
            border = self.mix_colour(base, (255, 255, 255), 0.18)
        elif variant == "play_white":
            base = self.theme.piece_white
            text_colour = self.theme.piece_white_edge
            border = self.theme.piece_white_edge
        elif variant == "play_black":
            base = self.theme.piece_black
            text_colour = self.theme.piece_black_edge
            border = self.theme.piece_black_edge
        elif variant == "danger":
            base = self.mix_colour(self.theme.error, self.theme.panel, 0.64)
            text_colour = self.theme.error
            border = self.mix_colour(self.theme.error, self.theme.panel, 0.28)
        elif variant in ("ghost", "selector_value"):
            base = self.theme.panel2
            text_colour = self.theme.button_text
            border = self.theme.panel_edge
        else:
            base = self.theme.button
            text_colour = self.theme.button_text
            border = self.theme.panel_edge

        if pressed:
            fill = self.mix_colour(base, (0, 0, 0), 0.20)
        elif hovered:
            fill = self.mix_colour(base, (255, 255, 255), 0.10)
        else:
            fill = base

        if variant == "toggle":
            fill = self.theme.panel2 if not hovered else self.theme.button_hover
            border = self.theme.panel_edge
            text_colour = self.theme.text

        pygame.draw.rect(self.screen, fill, rect, border_radius=10)
        border = self.theme.accent if accent_border else border
        pygame.draw.rect(self.screen, border, rect, 2, border_radius=10)
        if focused and self.keyboard_focus:
            pygame.draw.rect(self.screen, self.theme.accent2,
                             rect.inflate(6, 6), 3, border_radius=12)

        if variant == "toggle":
            rendered = self.text_surface(self.ui_font(15, True), label, text_colour)
            self.screen.blit(rendered, (rect.x + 14, rect.centery - rendered.get_height() // 2))
            track = pygame.Rect(rect.right - 58, rect.centery - 12, 44, 24)
            on = self.auto_flip_as_black
            pygame.draw.rect(self.screen, self.theme.accent2 if on else self.theme.button_press,
                             track, border_radius=12)
            knob_x = track.right - 11 if on else track.x + 11
            pygame.draw.circle(self.screen, self.contrast_colour(
                self.theme.accent2 if on else self.theme.button_press),
                (knob_x, track.centery), 8)
            return

        if font is None:
            font = self.fit_font(label, rect.width - 24,
                                 max_size=22 if rect.height >= 42 else 18)
        rendered = self.text_surface(font, label, text_colour)
        offset = 1 if pressed else 0
        self.screen.blit(rendered, rendered.get_rect(center=(rect.centerx, rect.centery + offset)))

    # ------------------------------------------------------------------
    # drawing
    # ------------------------------------------------------------------

    def draw_menu(self) -> None:
        self.screen.blit(self.themed_background(), (0, 0))
        menu_y = PLAYER_BAR_HEIGHT

        # Quiet twin-colour glow: accent is interactive, accent2 is selection.
        glow = pygame.Surface((WINDOW_WIDTH, 180), pygame.SRCALPHA)
        for radius, alpha in ((150, 8), (105, 12), (65, 16)):
            pygame.draw.circle(glow, (*self.theme.accent, alpha),
                               (WINDOW_WIDTH // 2 - 110, 10 + menu_y), radius)
            pygame.draw.circle(glow, (*self.theme.accent2, alpha),
                               (WINDOW_WIDTH // 2 + 110, 10 + menu_y), radius)
        self.screen.blit(glow, (0, 0))

        title = self.text_surface(self.title_font, "SGURR", self.theme.text)
        self.screen.blit(title, title.get_rect(center=(WINDOW_WIDTH // 2, 43 + menu_y)))
        subtitle = self.text_surface(
            self.small_font, "A home-grown chess engine from the Scottish hills",
            self.theme.muted)
        self.screen.blit(subtitle, subtitle.get_rect(center=(WINDOW_WIDTH // 2, 77 + menu_y)))

        self.draw_card(self.menu_card, fill=self.theme.panel)
        pygame.draw.line(self.screen, self.theme.accent,
                         (self.menu_card.x + 24, self.menu_card.y),
                         (self.menu_card.centerx, self.menu_card.y), 2)
        pygame.draw.line(self.screen, self.theme.accent2,
                         (self.menu_card.centerx, self.menu_card.y),
                         (self.menu_card.right - 24, self.menu_card.y), 2)

        x = self.menu_card.x + 28
        self.draw_section_label("Game mode", x, self.menu_card.y + 28)
        self.draw_section_label("Opponent", x, self.menu_card.y + 144)
        self.draw_section_label("Appearance", x, self.menu_card.y + 226)
        self.draw_section_label("Play", x, self.menu_card.y + 318)
        self.draw_section_label("Position tools", x, self.menu_card.y + 454)

        focus_buttons = self.menu_focus_buttons()
        focused = (focus_buttons[self.focus_index % len(focus_buttons)]
                   if focus_buttons else None)
        for button in self.menu_buttons:
            label = button.label
            if button.action == "noop_engine":
                label = self.engine_label
            elif button.action == "theme_gallery":
                label = self.theme.display_name
            elif button.action == "time_gallery":
                label = self.time_control_label
            is_mode_value = button.action == "time_gallery"
            font = self.ui_font(25, True) if is_mode_value else None
            self.draw_button(button.rect, label, variant=button.style,
                             focused=button is focused,
                             accent_border=is_mode_value,
                             font=font)

        status_lower = self.status.lower()
        if any(key in status_lower for key in ("could not", "invalid", "error")):
            toast = pygame.Rect(WINDOW_WIDTH // 2 - 300, self.menu_card.bottom + 18, 600, 36)
            pygame.draw.rect(self.screen, self.mix_colour(self.theme.error, self.theme.background, 0.82),
                             toast, border_radius=10)
            err = self.text_surface(
                self.fit_font(self.status, toast.width - 30, 16, 12, False),
                self.status, self.theme.error)
            self.screen.blit(err, err.get_rect(center=toast.center))
        else:
            hint = self.text_surface(
                self.tiny_font, "Press ? for controls and shortcuts", self.theme.muted)
            self.screen.blit(hint, hint.get_rect(center=(WINDOW_WIDTH // 2, self.menu_card.bottom + 34)))

        if self.input_mode == "fen":
            self.draw_text_input_overlay()
        elif self.theme_gallery_visible:
            self.draw_theme_gallery()
        elif self.time_gallery_visible:
            self.draw_time_gallery()
        elif self.settings_visible:
            self.draw_settings_overlay()

    def menu_focus_buttons(self) -> list[ButtonRect]:
        order = {
            action: index
            for index, action in enumerate((
                "time_down", "time_gallery", "time_up",
                "engine_prev", "engine_next",
                "theme_prev", "theme_gallery", "theme_next",
                "play_white", "play_black", "watch",
                "load_fen", "board_editor",
                "show_settings", "show_help",
            ))
        }
        return sorted(
            [button for button in self.menu_buttons
             if not button.action.startswith("noop")],
            key=lambda button: order.get(button.action, len(order)),
        )

    def focused_button(self, buttons: list[ButtonRect]) -> ButtonRect | None:
        if not buttons:
            return None
        self.focus_index %= len(buttons)
        return buttons[self.focus_index]

    def draw_modal_scrim(self) -> None:
        scrim = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
        scrim.fill((4, 7, 11, 170))
        self.screen.blit(scrim, (0, 0))

    def draw_theme_gallery(self) -> None:
        self.draw_modal_scrim()
        box = pygame.Rect(WINDOW_WIDTH // 2 - 450, 116, 900, 576)
        self.draw_card(box, fill=self.theme.panel, border=self.theme.accent, radius=18)
        title = self.text_surface(self.large_font, "Choose a theme", self.theme.text)
        self.screen.blit(title, (box.x + 32, box.y + 25))
        subtitle = self.text_surface(
            self.small_font, "Select a complete board and interface palette", self.theme.muted)
        self.screen.blit(subtitle, (box.x + 32, box.y + 64))

        self.theme_gallery_buttons = []
        card_w, card_h = 194, 176
        start_x, start_y = box.x + 34, box.y + 102
        gap_x, gap_y = 18, 18
        for index, name in enumerate(THEME_ORDER):
            row, col = divmod(index, 4)
            rect = pygame.Rect(start_x + col * (card_w + gap_x),
                               start_y + row * (card_h + gap_y), card_w, card_h)
            button = ButtonRect(rect, THEMES[name].display_name,
                                f"select_theme:{name}", "theme_card")
            self.theme_gallery_buttons.append(button)

        done = ButtonRect(pygame.Rect(box.right - 148, box.bottom - 52, 116, 36),
                          "Done", "theme_done", "primary")
        self.theme_gallery_buttons.append(done)
        focused = self.focused_button(self.theme_gallery_buttons)

        for button in self.theme_gallery_buttons[:-1]:
            name = button.action.split(":", 1)[1]
            preview = THEMES[name]
            rect = button.rect
            hovered = rect.collidepoint(self.logical_mouse_pos())
            fill = preview.panel2 if not hovered else self.mix_colour(
                preview.panel2, preview.accent, 0.12)
            pygame.draw.rect(self.screen, fill, rect, border_radius=12)
            border = preview.accent if name == self.theme_name else preview.panel_edge
            pygame.draw.rect(self.screen, border, rect,
                             3 if name == self.theme_name else 1, border_radius=12)
            if button is focused and self.keyboard_focus:
                pygame.draw.rect(self.screen, self.theme.accent2,
                                 rect.inflate(6, 6), 3, border_radius=14)

            board = pygame.Rect(rect.x + 17, rect.y + 17, 160, 104)
            square_w, square_h = board.width // 4, board.height // 2
            for rr in range(2):
                for cc in range(4):
                    colour = preview.board_light if (rr + cc) % 2 == 0 else preview.board_dark
                    pygame.draw.rect(self.screen, colour,
                                     (board.x + cc * square_w, board.y + rr * square_h,
                                      square_w, square_h))
            pygame.draw.rect(self.screen, preview.frame, board, 2)
            name_surf = self.text_surface(
                self.fit_font(preview.display_name, rect.width - 24, 16, 12, True),
                preview.display_name, preview.text)
            self.screen.blit(name_surf,
                             name_surf.get_rect(center=(rect.centerx, rect.bottom - 28)))

        self.draw_button(done.rect, done.label, variant="primary",
                         focused=done is focused, font=self.ui_font(15, True))

    def draw_time_gallery(self) -> None:
        self.draw_modal_scrim()
        box = pygame.Rect(WINDOW_WIDTH // 2 - 430, 138, 860, 532)
        self.draw_card(box, fill=self.theme.panel, border=self.theme.accent, radius=18)
        title = self.text_surface(self.large_font, "Choose a game mode", self.theme.text)
        self.screen.blit(title, (box.x + 32, box.y + 25))
        subtitle = self.text_surface(
            self.small_font, "Clock presets for the next game", self.theme.muted)
        self.screen.blit(subtitle, (box.x + 32, box.y + 64))

        self.time_gallery_buttons = []
        card_w, card_h = 184, 132
        start_x, start_y = box.x + 34, box.y + 108
        gap_x, gap_y = 22, 22
        for index, control in enumerate(TIME_CONTROLS):
            row, col = divmod(index, 4)
            rect = pygame.Rect(start_x + col * (card_w + gap_x),
                               start_y + row * (card_h + gap_y), card_w, card_h)
            self.time_gallery_buttons.append(
                ButtonRect(rect, control.label, f"select_time:{control.key}", "time_card")
            )

        done = ButtonRect(pygame.Rect(box.right - 148, box.bottom - 52, 116, 36),
                          "Done", "time_done", "primary")
        self.time_gallery_buttons.append(done)
        focused = self.focused_button(self.time_gallery_buttons)

        for button in self.time_gallery_buttons[:-1]:
            key = button.action.split(":", 1)[1]
            control = next(tc for tc in TIME_CONTROLS if tc.key == key)
            rect = button.rect
            selected = key == self.time_control.key
            hovered = rect.collidepoint(self.logical_mouse_pos())
            fill = self.theme.panel2 if not hovered else self.mix_colour(
                self.theme.panel2, self.theme.accent, 0.12)
            pygame.draw.rect(self.screen, fill, rect, border_radius=12)
            pygame.draw.rect(self.screen, self.theme.accent if selected else self.theme.panel_edge,
                             rect, 3 if selected else 1, border_radius=12)
            if button is focused and self.keyboard_focus:
                pygame.draw.rect(self.screen, self.theme.accent2,
                                 rect.inflate(6, 6), 3, border_radius=14)

            family, clock = control.label.split(" ", 1)
            family_surf = self.text_surface(self.ui_font(13, True), family.upper(), self.theme.muted)
            self.screen.blit(family_surf, (rect.x + 18, rect.y + 16))
            clock_surf = self.text_surface(self.ui_font(28, True), clock, self.theme.text)
            self.screen.blit(clock_surf, clock_surf.get_rect(midleft=(rect.x + 18, rect.y + 63)))
            detail = f"{int(control.base_seconds // 60)} min"
            if control.increment_seconds:
                detail += f" + {int(control.increment_seconds)} sec"
            else:
                detail += " + 0 sec"
            detail_surf = self.text_surface(self.ui_font(13, True), detail, self.theme.accent)
            self.screen.blit(detail_surf, (rect.x + 18, rect.bottom - 32))

        self.draw_button(done.rect, done.label, variant="primary",
                         focused=done is focused, font=self.ui_font(15, True))

    def draw_settings_overlay(self) -> None:
        self.draw_modal_scrim()
        box = pygame.Rect(WINDOW_WIDTH // 2 - 330, 112, 660, 584)
        self.draw_card(box, fill=self.theme.panel, border=self.theme.accent, radius=18)
        title = self.text_surface(self.large_font, "Settings", self.theme.text)
        self.screen.blit(title, (box.x + 32, box.y + 27))
        subtitle = self.text_surface(
            self.small_font, "Changes are saved automatically", self.theme.muted)
        self.screen.blit(subtitle, (box.x + 32, box.y + 65))

        left, right = box.x + 32, box.right - 32
        self.draw_section_label("Animation", left, box.y + 110)
        anim_y = box.y + 136
        self.settings_buttons = [
            ButtonRect(pygame.Rect(left, anim_y, 44, 40), "‹", "animation_prev", "selector"),
            ButtonRect(pygame.Rect(left + 52, anim_y, right - left - 104, 40),
                       self.animation_mode, "noop_animation", "selector_value"),
            ButtonRect(pygame.Rect(right - 44, anim_y, 44, 40), "›", "animation_next", "selector"),
        ]

        self.draw_section_label("Board", left, box.y + 200)
        self.settings_buttons.append(
            ButtonRect(pygame.Rect(left, box.y + 226, right - left, 42),
                       "Auto-flip as Black", "toggle_auto_flip", "toggle")
        )

        self.draw_section_label("Search", left, box.y + 295)
        depth_y = box.y + 321
        self.settings_buttons.extend([
            ButtonRect(pygame.Rect(left, depth_y, 44, 38), "<", "depth_down", "selector"),
            ButtonRect(pygame.Rect(left + 52, depth_y, right - left - 104, 38),
                       self.depth_cap_label(), "noop_depth", "selector_value"),
            ButtonRect(pygame.Rect(right - 44, depth_y, 44, 38), ">", "depth_up", "selector"),
        ])

        self.draw_section_label("Sound", left, box.y + 366)
        rows = [
            ("Master", "master", self.master_volume),
            ("Moves", "move", self.move_volume),
            ("Alerts", "alert", self.alert_volume),
        ]
        for index, (label, key, value) in enumerate(rows):
            y = box.y + 392 + index * 46
            self.settings_buttons.extend([
                ButtonRect(pygame.Rect(right - 246, y, 40, 38), "-", f"{key}_down", "selector"),
                ButtonRect(pygame.Rect(right - 40, y, 40, 38), "+", f"{key}_up", "selector"),
            ])
            label_surf = self.text_surface(self.ui_font(16, True), label, self.theme.text)
            self.screen.blit(label_surf, (left, y + 8))
            track = pygame.Rect(right - 194, y + 13, 142, 12)
            pygame.draw.rect(self.screen, self.theme.button_press, track, border_radius=6)
            amount = pygame.Rect(track.x, track.y, int(track.width * value), track.height)
            if amount.width:
                pygame.draw.rect(self.screen, self.theme.accent, amount, border_radius=6)
            value_surf = self.text_surface(
                self.ui_font(13, True), f"{round(value * 100):d}%", self.theme.muted)
            self.screen.blit(value_surf, value_surf.get_rect(midtop=(track.centerx, track.bottom + 5)))

        done = ButtonRect(pygame.Rect(right - 116, box.bottom - 52, 116, 36),
                          "Done", "settings_done", "primary")
        self.settings_buttons.append(done)
        focusable = [button for button in self.settings_buttons
                     if not button.action.startswith("noop")]
        focused = self.focused_button(focusable)
        for button in self.settings_buttons:
            if button.action == "noop_animation":
                label = self.animation_mode
            elif button.action == "noop_depth":
                label = self.depth_cap_label()
            else:
                label = button.label
            self.draw_button(button.rect, label, variant=button.style,
                             focused=button is focused,
                             font=self.ui_font(15, True))

    def board_base_surface(self) -> pygame.Surface:
        key = (self.theme_name, self.flip_board)
        cached = self._board_base_cache.get(key)
        if cached is not None:
            return cached

        surf = pygame.Surface((BOARD_SIZE, BOARD_SIZE), depth=DISPLAY_DEPTH).convert()
        for row in range(8):
            for col in range(8):
                colour = (self.theme.board_light if (row + col) % 2 == 0
                          else self.theme.board_dark)
                pygame.draw.rect(surf, colour,
                                 pygame.Rect(col * SQUARE_SIZE, row * SQUARE_SIZE,
                                             SQUARE_SIZE, SQUARE_SIZE))

        coord_font = self.ui_font(12, True)
        for i in range(8):
            if self.flip_board:
                file_label = chr(ord("h") - i)
                rank_label = str(i + 1)
            else:
                file_label = chr(ord("a") + i)
                rank_label = str(8 - i)
            bottom_square = self.theme.board_dark if i % 2 == 0 else self.theme.board_light
            left_square = self.theme.board_light if i % 2 == 0 else self.theme.board_dark
            file_colour = self.mix_colour(
                self.contrast_colour(bottom_square), bottom_square, 0.35)
            rank_colour = self.mix_colour(
                self.contrast_colour(left_square), left_square, 0.35)
            file_text = self.text_surface(coord_font, file_label, file_colour)
            rank_text = self.text_surface(coord_font, rank_label, rank_colour)
            surf.blit(file_text, (i * SQUARE_SIZE + SQUARE_SIZE - 14, BOARD_SIZE - 17))
            surf.blit(rank_text, (5, i * SQUARE_SIZE + 4))

        pygame.draw.rect(surf, self.theme.frame, surf.get_rect(), 3)
        self._board_base_cache[key] = surf
        return surf

    def draw_board(self, board: chess.Board, show_marks: bool = True,
                   animate: bool = False) -> None:
        self.screen.blit(self.board_base_surface(), (EVAL_PANEL_WIDTH, BOARD_TOP))

        # translucent highlights (last move, selection)
        if show_marks:
            if self.last_move is not None:
                for sq in (self.last_move.from_square, self.last_move.to_square):
                    self.blit_highlight(sq, self.theme.last_move, 95)
            if self.selected_square is not None:
                self.blit_highlight(self.selected_square, self.theme.selected, 110)
            self.draw_legal_move_hints()

        # check glow under the king in check
        if not self.edit_mode and board.is_check():
            king_sq = board.king(board.turn)
            if king_sq is not None:
                glow = self.get_check_glow()
                self.screen.blit(glow, glow.get_rect(center=self.square_center(king_sq)))

        self.draw_pieces(board, animate=animate)

    def player_identity(self, colour: chess.Color) -> tuple[str, str]:
        if self.human_colour is not None and colour == self.human_colour:
            return "You", "LOCAL PLAYER"
        rating = self.engine_label.split("(")[-1].rstrip(")")
        suffix = "WHITE" if colour == chess.WHITE else "BLACK"
        return self.engine_name, f"{rating}  •  {suffix}"

    def draw_player_cards(self) -> None:
        bottom_colour = chess.BLACK if self.flip_board else chess.WHITE
        top_colour = not bottom_colour

        def draw_card_for(colour: chess.Color, y: int) -> None:
            rect = pygame.Rect(EVAL_PANEL_WIDTH, y, BOARD_SIZE, PLAYER_BAR_HEIGHT - 6)
            active = self.chess_board.turn == colour and not self.game_is_over
            fill = self.theme.panel2 if active else self.theme.panel
            pygame.draw.rect(self.screen, fill, rect, border_radius=10)
            pygame.draw.rect(self.screen,
                             self.theme.accent if active else self.theme.panel_edge,
                             rect, 2 if active else 1, border_radius=10)

            piece_fill = self.theme.eval_white if colour == chess.WHITE else self.theme.eval_black
            pygame.draw.circle(self.screen, piece_fill, (rect.x + 20, rect.centery), 9)
            pygame.draw.circle(self.screen, self.theme.panel_edge,
                               (rect.x + 20, rect.centery), 9, 1)

            name, detail = self.player_identity(colour)
            name_font = self.fit_font(name, 290, 16, 12, True)
            name_surface = self.text_surface(name_font, name, self.theme.text)
            self.screen.blit(name_surface, (rect.x + 38, rect.y + 4))
            detail_surface = self.text_surface(
                self.ui_font(10, True), detail, self.theme.muted)
            self.screen.blit(detail_surface, (rect.x + 38, rect.y + 22))

            clock = pygame.Rect(rect.right - 86, rect.y + 5, 72, rect.height - 10)
            pygame.draw.rect(self.screen, self.theme.button, clock, border_radius=8)
            pygame.draw.rect(self.screen, self.theme.panel_edge, clock, 1, border_radius=8)
            remaining = self.game_clocks.get(colour, self.time_control.base_seconds)
            clock_colour = self.theme.error if remaining <= 10.0 else (
                self.theme.text if active else self.theme.muted
            )
            clock_text = self.text_surface(
                self.ui_font(13, True), self.format_clock(remaining), clock_colour)
            self.screen.blit(clock_text, clock_text.get_rect(center=clock.center))

            if active:
                pygame.draw.circle(self.screen, self.theme.accent,
                                   (clock.x - 13, rect.centery), 4)

        draw_card_for(top_colour, 3)
        draw_card_for(bottom_colour, BOARD_TOP + BOARD_SIZE + 3)

    def blit_highlight(self, square: chess.Square, colour: tuple, alpha: int) -> None:
        rect = self.square_rect(square)
        surf = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        surf.fill((colour[0], colour[1], colour[2], alpha))
        self.screen.blit(surf, rect.topleft)

    def draw_legal_move_hints(self) -> None:
        if self.selected_square is None:
            return

        col = self.theme.legal_dot
        for move in self.chess_board.legal_moves:
            if move.from_square != self.selected_square:
                continue
            rect = self.square_rect(move.to_square)
            surf = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
            centre = (rect.width // 2, rect.height // 2)
            if self.chess_board.is_capture(move):
                pygame.draw.circle(surf, (col[0], col[1], col[2], 90), centre,
                                   rect.width // 2 - 4, 6)
            else:
                pygame.draw.circle(surf, (col[0], col[1], col[2], 95), centre, 11)
            self.screen.blit(surf, rect.topleft)

    def draw_pieces(self, board: chess.Board, animate: bool = False) -> None:
        anim = self.animation if animate else None
        skip_sq = anim["to"] if anim is not None else None

        for square, piece in board.piece_map().items():
            if square == self.dragging_from_square and self.dragging_piece is not None:
                continue
            if skip_sq is not None and square == skip_sq:
                continue
            self.blit_piece(piece, self.square_center(square))

        if self.dragging_piece is not None:
            self.blit_piece(self.dragging_piece, self.dragging_mouse_pos)

        if self.edit_mode and self.edit_drag_piece is not None:
            self.blit_piece(self.edit_drag_piece, self.edit_drag_mouse)

        if anim is not None:
            t = (time.time() - anim["start"]) / anim["dur"]
            if t >= 1.0:
                self.animation = None
                self.blit_piece(anim["piece"], self.square_center(anim["to"]))
            else:
                ease = 1 - (1 - t) ** 3      # easeOutCubic
                fx, fy = self.square_center(anim["from"])
                tx, ty = self.square_center(anim["to"])
                self.blit_piece(anim["piece"], (fx + (tx - fx) * ease, fy + (ty - fy) * ease))

    def draw_board_frame(self) -> None:
        rect = pygame.Rect(EVAL_PANEL_WIDTH, BOARD_TOP, BOARD_SIZE, BOARD_SIZE)
        pygame.draw.rect(self.screen, self.theme.frame, rect, 3)

    def draw_coordinates(self) -> None:
        for i in range(8):
            if self.flip_board:
                file_label = chr(ord("h") - i)
                rank_label = str(i + 1)
            else:
                file_label = chr(ord("a") + i)
                rank_label = str(8 - i)

            bottom_square = self.theme.board_dark if i % 2 == 0 else self.theme.board_light
            left_square = self.theme.board_light if i % 2 == 0 else self.theme.board_dark
            file_colour = self.mix_colour(
                self.contrast_colour(bottom_square), bottom_square, 0.35)
            rank_colour = self.mix_colour(
                self.contrast_colour(left_square), left_square, 0.35)
            coord_font = self.ui_font(12, True)
            file_text = self.text_surface(coord_font, file_label, file_colour)
            rank_text = self.text_surface(coord_font, rank_label, rank_colour)

            self.screen.blit(file_text, (EVAL_PANEL_WIDTH + i * SQUARE_SIZE + SQUARE_SIZE - 14,
                                         BOARD_TOP + BOARD_SIZE - 17))
            self.screen.blit(rank_text, (EVAL_PANEL_WIDTH + 5,
                                         BOARD_TOP + i * SQUARE_SIZE + 4))

    def draw_eval_bar(self) -> None:
        x = (EVAL_PANEL_WIDTH - EVAL_BAR_WIDTH) // 2
        w = EVAL_BAR_WIDTH
        radius = w // 2

        eval_pawns = self.display_eval_pawns()
        is_forced_mate = abs(eval_pawns) >= 90
        if is_forced_mate:
            target = 1.0 if eval_pawns > 0 else 0.0
        else:
            target = self.eval_to_bar_fraction(eval_pawns)

        diff = target - self.eval_display_frac
        if abs(diff) < 0.0015:
            self.eval_display_frac = target
        else:
            frame_seconds = self.clock.get_time() / 1000.0
            if frame_seconds <= 0:
                frame_seconds = 1.0 / TARGET_FPS
            frame_seconds = min(0.1, frame_seconds)
            easing = 1.0 - (1.0 - EVAL_BAR_EASING) ** (frame_seconds * 60.0)
            self.eval_display_frac += diff * easing

        frac = max(0.0, min(1.0, self.eval_display_frac))

        label = "M" if eval_pawns >= 90 else "-M" if eval_pawns <= -90 else f"{eval_pawns:+.1f}"
        pill = pygame.Rect(6, BOARD_TOP + 7, EVAL_PANEL_WIDTH - 12, 28)
        pygame.draw.rect(self.screen, self.theme.panel2, pill, border_radius=9)
        pygame.draw.rect(self.screen, self.theme.panel_edge, pill, 1, border_radius=9)
        label_surface = self.text_surface(
            self.ui_font(13, True), label, self.theme.text)
        label_rect = label_surface.get_rect(center=pill.center)
        self.screen.blit(label_surface, label_rect)

        y = pill.bottom + 10
        h = BOARD_TOP + BOARD_SIZE - y - 12
        white_h = int(h * frac)
        if not is_forced_mate and 0.0 < frac < 1.0:
            white_h = max(1, min(h - 1, white_h))

        track = pygame.Rect(x, y, w, h)
        bar = pygame.Surface((w, h), pygame.SRCALPHA)
        mask = pygame.Surface((w, h), pygame.SRCALPHA)

        pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(),
                         border_radius=radius)
        pygame.draw.rect(bar, self.theme.eval_black, bar.get_rect())

        if white_h > 0:
            white_rect = pygame.Rect(0, h - white_h, w, white_h)
            pygame.draw.rect(bar, self.theme.eval_white, white_rect)

        bar.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        self.screen.blit(bar, track.topleft)
        pygame.draw.rect(self.screen, self.theme.panel_edge, track, 1, border_radius=radius)

    def panel_background(self) -> None:
        panel_x = EVAL_PANEL_WIDTH + BOARD_SIZE
        grad = self.vgradient(SIDE_PANEL_WIDTH, WINDOW_HEIGHT,
                              self.theme.panel2, self.theme.panel)
        self.screen.blit(grad, (panel_x, 0))
        pygame.draw.line(self.screen, self.theme.panel_edge,
                         (panel_x, 0), (panel_x, WINDOW_HEIGHT), 2)

    def draw_eval_graph(self, rect: pygame.Rect) -> None:
        self.draw_card(rect, shadow=False, radius=12)
        label_font = self.ui_font(12, True)
        self.screen.blit(self.text_surface(label_font, "EVAL TREND", self.theme.muted),
                         (rect.x + 14, rect.y + 9))

        points_data = self.eval_history[-40:]
        if not points_data:
            points_data = [(0, self.eval_target_cp)]
        latest_cp = points_data[-1][1]
        latest_text = ("M" if latest_cp >= 90000 else "-M" if latest_cp <= -90000
                       else f"{latest_cp / 100:+.1f}")
        value = self.text_surface(self.ui_font(12, True), latest_text, self.theme.text)
        self.screen.blit(value, (rect.right - value.get_width() - 14, rect.y + 9))

        plot = pygame.Rect(rect.x + 14, rect.y + 30, rect.width - 28, rect.height - 40)
        mid_y = plot.centery
        pygame.draw.line(self.screen, self.theme.panel_edge,
                         (plot.x, mid_y), (plot.right, mid_y), 1)

        min_ply = points_data[0][0]
        max_ply = points_data[-1][0]
        span = max(1, max_ply - min_ply)
        screen_points: list[tuple[int, int]] = []
        for ply, score_cp in points_data:
            px = plot.x + int((ply - min_ply) / span * plot.width)
            clamped = max(-800, min(800, score_cp))
            py = mid_y - int(clamped / 800 * (plot.height / 2 - 2))
            screen_points.append((px, py))

        if len(screen_points) > 1:
            pygame.draw.lines(self.screen, self.theme.accent, False, screen_points, 2)
        for point in screen_points[-12:]:
            pygame.draw.circle(self.screen, self.theme.accent2, point, 3)

    def draw_side_panel(self) -> None:
        self.panel_background()
        x = EVAL_PANEL_WIDTH + BOARD_SIZE + 14
        w = SIDE_PANEL_WIDTH - 28
        title_font = self.ui_font(20, True)
        label_font = self.ui_font(12, True)
        body_font = self.ui_font(14, False)
        value_font = self.ui_font(17, True)

        # Engine identity
        header = pygame.Rect(x, 14, w, 82)
        self.draw_card(header, fill=self.theme.panel2, shadow=False, radius=12)
        name = self.text_surface(title_font, self.engine_name, self.theme.text)
        self.screen.blit(name, (header.x + 14, header.y + 11))
        rating = self.engine_label.split("(")[-1].rstrip(")") if "(" in self.engine_label else ""
        rating_surf = self.text_surface(body_font, rating, self.theme.accent)
        self.screen.blit(rating_surf, (header.x + 14, header.y + 38))
        limits_text = self.search_limit_label()
        limits = self.text_surface(self.tiny_font, limits_text, self.theme.muted)
        self.screen.blit(limits, (header.x + 14, header.y + 60))
        if self.engine_thinking:
            phase = (pygame.time.get_ticks() % 1200) / 1200.0
            for i in range(3):
                pulse = max(0.25, 1.0 - abs(phase * 3 - i) * 0.8)
                colour = self.mix_colour(self.theme.panel2, self.theme.accent, pulse)
                pygame.draw.circle(self.screen, colour,
                                   (header.right - 47 + i * 10, header.y + 22), 3)

        # Game state strip
        state = pygame.Rect(x, 106, w, 58)
        self.draw_card(state, shadow=False, radius=12)
        if self.human_colour is None:
            mode = "WATCHING" + (" · PAUSED" if self.watch_paused else "")
        else:
            mode = f"YOU PLAY {'WHITE' if self.human_colour == chess.WHITE else 'BLACK'}"
        self.screen.blit(self.text_surface(label_font, mode, self.theme.muted),
                         (state.x + 14, state.y + 10))
        turn_colour = self.theme.eval_white if self.chess_board.turn == chess.WHITE else self.theme.eval_black
        pygame.draw.circle(self.screen, turn_colour, (state.x + 20, state.y + 39), 7)
        pygame.draw.circle(self.screen, self.theme.panel_edge, (state.x + 20, state.y + 39), 7, 1)
        turn = self.text_surface(
            body_font,
            f"{'White' if self.chess_board.turn == chess.WHITE else 'Black'} to move",
            self.theme.text)
        self.screen.blit(turn, turn.get_rect(midleft=(state.x + 34, state.y + 39)))

        # Evaluation and material
        evaluation = pygame.Rect(x, 174, w, 72)
        self.draw_card(evaluation, shadow=False, radius=12)
        eval_pawns = self.display_eval_pawns()
        eval_text = ("MATE" if eval_pawns >= 90 else "-MATE" if eval_pawns <= -90
                     else f"{eval_pawns:+.1f}")
        self.screen.blit(self.text_surface(label_font, "EVALUATION", self.theme.muted),
                         (evaluation.x + 14, evaluation.y + 13))
        self.screen.blit(self.text_surface(self.ui_font(25, True), eval_text, self.theme.text),
                         (evaluation.x + 14, evaluation.y + 33))
        white_material, black_material, material_diff = self.material_score()
        diff = (f"White +{material_diff}" if material_diff > 0 else
                f"Black +{-material_diff}" if material_diff < 0 else "Level")
        material_label = self.text_surface(label_font, "MATERIAL", self.theme.muted)
        self.screen.blit(material_label, (evaluation.x + 158, evaluation.y + 13))
        material = self.text_surface(
            value_font, f"{white_material} : {black_material}", self.theme.text)
        self.screen.blit(material, (evaluation.x + 158, evaluation.y + 34))
        diff_surface = self.text_surface(self.tiny_font, diff, self.theme.muted)
        self.screen.blit(diff_surface, diff_surface.get_rect(
            bottomright=(evaluation.right - 14, evaluation.bottom - 7)))

        # Captured pieces use the same vector set as the board.
        captured = pygame.Rect(x, 256, w, 78)
        self.draw_card(captured, shadow=False, radius=12)
        white_lost, black_lost = self.captured_pieces()

        def captured_row(label: str, pieces: list[int], colour: chess.Color, cy: int) -> None:
            self.screen.blit(self.text_surface(self.tiny_font, label, self.theme.muted),
                             (captured.x + 14, cy - 7))
            cursor = captured.x + 94
            if not pieces:
                self.screen.blit(self.text_surface(body_font, "—", self.theme.muted),
                                 (cursor, cy - 9))
            for piece_type in pieces[:10]:
                self.blit_piece(chess.Piece(piece_type, colour), (cursor + 9, cy), 21)
                cursor += 20

        captured_row("White lost", white_lost, chess.WHITE, captured.y + 25)
        captured_row("Black lost", black_lost, chess.BLACK, captured.y + 55)

        # Proper numbered move table; latest rows remain visible and the
        # current row receives a restrained accent highlight.
        moves = pygame.Rect(x, 344, w, 218)
        self.draw_card(moves, shadow=False, radius=12)
        rows = self.move_rows()
        self.screen.blit(self.text_surface(label_font, "MOVES", self.theme.muted),
                         (moves.x + 14, moves.y + 11))
        count_text = f"{len(self.chess_board.move_stack)} PLY"
        count = self.text_surface(self.tiny_font, count_text, self.theme.muted)
        self.screen.blit(count, (moves.right - count.get_width() - 14, moves.y + 12))
        table_y = moves.y + 38
        # A redo notice owns the card footer, so reserve the final row rather
        # than allowing it to cover the latest move in a full table.
        visible = rows[-(6 if self.redo_stack else 7):]
        if not visible:
            empty = self.text_surface(body_font, "No moves yet", self.theme.muted)
            self.screen.blit(empty, (moves.x + 14, table_y + 8))
        for index, (number, white, black) in enumerate(visible):
            row_rect = pygame.Rect(moves.x + 8, table_y + index * 24, moves.width - 16, 22)
            if index == len(visible) - 1:
                tint = self.mix_colour(self.theme.panel, self.theme.accent2, 0.15)
                pygame.draw.rect(self.screen, tint, row_rect, border_radius=6)
            self.screen.blit(self.text_surface(self.tiny_font, f"{number}.", self.theme.muted),
                             (row_rect.x + 7, row_rect.y + 3))
            wf = self.fit_font(white or "—", 105, 14, 11, False)
            bf = self.fit_font(black or "—", 105, 14, 11, False)
            self.screen.blit(self.text_surface(
                wf, white or "—", self.theme.text if white else self.theme.muted),
                             (row_rect.x + 43, row_rect.y + 3))
            self.screen.blit(self.text_surface(
                bf, black or "—", self.theme.text if black else self.theme.muted),
                             (row_rect.x + 169, row_rect.y + 3))
        if self.redo_stack:
            footer_y = moves.bottom - 29
            pygame.draw.line(self.screen, self.theme.panel_edge,
                             (moves.x + 12, footer_y), (moves.right - 12, footer_y), 1)
            redo = self.text_surface(
                self.tiny_font, f"{len(self.redo_stack)} move(s) available to redo",
                self.theme.accent2)
            self.screen.blit(redo, (moves.x + 14, moves.bottom - 20))

        # Status card with semantic colour and optional engine details.
        status = pygame.Rect(x, 572, w, 78)
        self.draw_card(status, shadow=False, radius=12)
        status_lower = self.status.lower()
        is_error = any(word in status_lower for word in ("invalid", "illegal", "could not", "error"))
        status_colour = self.theme.error if is_error else (
            self.theme.accent if self.engine_thinking else self.theme.accent2)
        pygame.draw.circle(self.screen, status_colour, (status.x + 19, status.y + 20), 5)
        self.screen.blit(self.text_surface(label_font, "STATUS", self.theme.muted),
                         (status.x + 31, status.y + 11))
        status_text = "Sgurr is thinking…" if self.engine_thinking else self.status
        for i, line_text in enumerate(self.wrap_text(status_text, 39)[:2]):
            line_surface = self.text_surface(
                body_font, line_text,
                self.theme.error if is_error else self.theme.text)
            self.screen.blit(line_surface, (status.x + 14, status.y + 33 + i * 17))
        if self.engine_info and not self.engine_thinking:
            info = self.text_surface(
                self.fit_font(self.engine_info, status.width - 28, 12, 10, False),
                self.engine_info, self.theme.muted)
            self.screen.blit(info, (status.x + 14, status.bottom - 16))

        self.side_buttons = [
            ButtonRect(pygame.Rect(x, 660, 158, 42), "Main menu", "side_menu", "ghost"),
            ButtonRect(pygame.Rect(x + 170, 660, 162, 42), "?  Shortcuts", "side_help", "secondary"),
        ]
        focused = self.focused_button(self.side_buttons)
        for button in self.side_buttons:
            self.draw_button(button.rect, button.label, variant=button.style,
                             font=self.ui_font(14, True), focused=button is focused)

        self.draw_eval_graph(pygame.Rect(x, 712, w, 84))

    def draw_edit_side_panel(self) -> None:
        self.panel_background()

        x = EVAL_PANEL_WIDTH + BOARD_SIZE + 14
        w = SIDE_PANEL_WIDTH - 28
        title = self.medium_font.render("Board editor", True, self.theme.text)
        self.screen.blit(title, (x, 14))

        old_focus = self.focused_button(self.edit_buttons)
        focused_action = old_focus.action if old_focus is not None else None
        self.edit_buttons = []

        def add_button(label: str, action: str, rect: pygame.Rect,
                       variant: str = "secondary") -> None:
            self.draw_button(rect, label, variant=variant,
                             focused=action == focused_action,
                             font=self.ui_font(14, True))
            self.edit_buttons.append(ButtonRect(rect, label, action, variant))

        half_w = (w - 12) // 2
        compact_h = 32
        row_gap = 36

        def add_preset_grid(entries: tuple, action_prefix: str, start_y: int) -> int:
            for index, entry in enumerate(entries):
                key, label = entry[0], entry[1]
                row = index // 2
                col = index % 2
                is_final_single = (
                    index == len(entries) - 1
                    and len(entries) % 2 == 1
                )
                if is_final_single:
                    rect = pygame.Rect(x, start_y + row * row_gap, w, compact_h)
                else:
                    bx = x if col == 0 else x + w - half_w
                    rect = pygame.Rect(bx, start_y + row * row_gap, half_w, compact_h)
                add_button(label, f"{action_prefix}:{key}", rect)
            return (len(entries) + 1) // 2

        self.draw_section_label("Play setup", x, 50)
        row_y = 74
        turn_label = f"First move: {'White' if self.edit_turn == chess.WHITE else 'Black'}"
        add_button(self.edit_player_label(), "edit_player", pygame.Rect(x, row_y, w, 36))
        add_button(turn_label, "edit_turn", pygame.Rect(x, row_y + 40, w, 36))
        add_button("Play from here", "edit_done",
                   pygame.Rect(x, row_y + 84, w, 40), "primary")

        self.draw_section_label("Practice", x, 210)
        drill_rows = add_preset_grid(CHECKMATE_DRILLS, "edit_drill", 232)

        odds_label_y = 232 + drill_rows * row_gap + 10
        self.draw_section_label("Odds", x, odds_label_y)
        odds_y = odds_label_y + 22
        add_button(self.edit_odds_label(), "edit_odds_for",
                   pygame.Rect(x, odds_y, w, compact_h))
        odds_rows = add_preset_grid(ODDS_PRESETS, "edit_odds", odds_y + row_gap)

        position_label_y = odds_y + (odds_rows + 1) * row_gap + 10
        self.draw_section_label("Position", x, position_label_y)
        pos_y = position_label_y + 22
        add_button("Start position", "edit_start", pygame.Rect(x, pos_y, half_w, compact_h))
        add_button("Copy FEN", "edit_copyfen",
                   pygame.Rect(x + w - half_w, pos_y, half_w, compact_h))
        add_button("Clear board", "edit_clear",
                   pygame.Rect(x, pos_y + row_gap, half_w, compact_h), "danger")
        add_button("Cancel (Esc)", "edit_cancel",
                   pygame.Rect(x + w - half_w, pos_y + row_gap, half_w, compact_h),
                   "secondary")

        pieces_label_y = pos_y + 2 * row_gap + 10
        self.draw_section_label("Pieces", x, pieces_label_y)
        cell = 32
        gap = 6
        palette_w = len(EDIT_PALETTE_ORDER) * cell + (len(EDIT_PALETTE_ORDER) - 1) * gap
        palette_x = x + (w - palette_w) // 2
        palette_y = pieces_label_y + 22
        self.edit_palette_rects = []
        for row, colour in enumerate((chess.WHITE, chess.BLACK)):
            for col, piece_type in enumerate(EDIT_PALETTE_ORDER):
                piece = chess.Piece(piece_type, colour)
                rect = pygame.Rect(palette_x + col * (cell + gap),
                                   palette_y + row * (cell + gap), cell, cell)
                selected = self.edit_brush is not None and self.edit_brush == piece
                hovered = rect.collidepoint(self.logical_mouse_pos())
                fill = self.theme.accent if selected else (
                    self.theme.button_hover if hovered else self.theme.button)
                pygame.draw.rect(self.screen, fill, rect, border_radius=8)
                pygame.draw.rect(self.screen, self.theme.panel_edge, rect, 1, border_radius=8)
                self.blit_piece(piece, rect.center, 28)
                self.edit_palette_rects.append((rect, piece))

        hy = palette_y + 2 * cell + gap + 14
        hint = self.text_surface(
            self.tiny_font,
            "Drag pieces; right-click deletes; palette toggles",
            self.theme.muted,
        )
        self.screen.blit(hint, (x, hy))
        hy += 19

        status_colour = self.theme.error if "Fix position" in self.status else self.theme.text
        for line in self.wrap_text(self.status, 42)[:2]:
            rendered = self.text_surface(self.tiny_font, line, status_colour)
            self.screen.blit(rendered, (x, hy))
            hy += 17

    def draw_promotion_overlay(self) -> None:
        if self.promotion_pending is None or self.human_colour is None:
            return

        overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 130))
        self.screen.blit(overlay, (0, 0))

        box = pygame.Rect(0, 0, 4 * 78 + 40, 132)
        box.center = (EVAL_PANEL_WIDTH + BOARD_SIZE // 2,
                      BOARD_TOP + BOARD_SIZE // 2)
        pygame.draw.rect(self.screen, self.theme.panel, box, border_radius=12)
        pygame.draw.rect(self.screen, self.theme.accent, box, 2, border_radius=12)

        title = self.small_font.render("Promote to: (Esc cancels)", True, self.theme.muted)
        self.screen.blit(title, (box.x + 20, box.y + 12))

        old_promotion_focus = self.focus_index if self.keyboard_focus else -1
        self.promotion_buttons = []
        bx = box.x + 20
        for promo in PROMOTION_CHOICES:
            rect = pygame.Rect(bx, box.y + 40, 70, 74)
            hovered = rect.collidepoint(self.logical_mouse_pos())
            pygame.draw.rect(self.screen, self.theme.button_hover if hovered else self.theme.button,
                             rect, border_radius=10)
            pygame.draw.rect(self.screen, self.theme.panel_edge, rect, 2, border_radius=10)
            if len(self.promotion_buttons) == old_promotion_focus and self.keyboard_focus:
                pygame.draw.rect(self.screen, self.theme.accent2,
                                 rect.inflate(6, 6), 3, border_radius=12)
            self.blit_piece(chess.Piece(promo, self.human_colour), rect.center, 60)
            self.promotion_buttons.append((rect, promo))
            bx += 78

    def draw_text_input_overlay(self) -> None:
        overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))

        box = pygame.Rect(0, 0, 760, 202)
        box.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2)
        self.draw_card(box, fill=self.theme.panel, border=self.theme.accent, radius=16)

        title = self.large_font.render("Load a position", True, self.theme.text)
        self.screen.blit(title, (box.x + 24, box.y + 20))

        prompt = self.small_font.render("Paste or type a Forsyth–Edwards Notation string.",
                                        True, self.theme.muted)
        self.screen.blit(prompt, (box.x + 24, box.y + 58))

        shown_text = self.text_input[-90:] if len(self.text_input) > 90 else self.text_input
        input_rect = pygame.Rect(box.x + 24, box.y + 90, box.width - 48, 42)
        pygame.draw.rect(self.screen, self.theme.background, input_rect, border_radius=8)
        pygame.draw.rect(self.screen, self.theme.accent, input_rect, 1, border_radius=8)

        rendered = self.small_font.render(shown_text, True, self.theme.text)
        text_pos = (input_rect.x + 12, input_rect.centery - rendered.get_height() // 2)
        self.screen.blit(rendered, text_pos)
        if (pygame.time.get_ticks() // 500) % 2 == 0:
            caret_x = min(input_rect.right - 10, text_pos[0] + rendered.get_width() + 2)
            pygame.draw.line(self.screen, self.theme.accent,
                             (caret_x, input_rect.y + 10), (caret_x, input_rect.bottom - 10), 2)

        if self.input_error:
            error = self.small_font.render(self.input_error, True, self.theme.error)
            self.screen.blit(error, (box.x + 24, box.y + 143))
        else:
            keys = self.tiny_font.render("ENTER  Load position     ESC  Cancel     CTRL+V  Paste",
                                         True, self.theme.muted)
            self.screen.blit(keys, (box.x + 24, box.y + 150))

    def draw_help_overlay(self) -> None:
        overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 165))
        self.screen.blit(overlay, (0, 0))

        box = pygame.Rect(0, 0, 680, 500)
        box.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2)
        self.draw_card(box, fill=self.theme.panel, border=self.theme.accent, radius=16)
        title = self.large_font.render("Controls & shortcuts", True, self.theme.text)
        self.screen.blit(title, (box.x + 32, box.y + 25))
        subtitle = self.small_font.render(
            "Everything useful, without keeping it permanently on screen.",
            True, self.theme.muted)
        self.screen.blit(subtitle, (box.x + 32, box.y + 62))

        groups = [
            ("PLAY", [("Drag / click", "Move a piece"), ("U", "Undo full move"),
                       ("< / >", "Step through history"), ("G", "Ask engine to move"),
                       ("R", "Restart position"), ("F", "Flip board")]),
            ("TOOLS", [("E", "Board editor"), ("L", "Load FEN"),
                        ("C", "Copy FEN"), ("P", "Export PGN"),
                        ("T", "Cycle theme"), ("F11", "Fullscreen"),
                        ("Space", "Pause watch mode")]),
        ]
        for column, (heading, shortcuts) in enumerate(groups):
            col_x = box.x + 32 + column * 325
            self.draw_section_label(heading, col_x, box.y + 110)
            for row, (key_name, description) in enumerate(shortcuts):
                cy = box.y + 144 + row * 47
                key_w = max(52, self.ui_font(13, True).size(key_name)[0] + 20)
                key_rect = pygame.Rect(col_x, cy, key_w, 30)
                pygame.draw.rect(self.screen, self.theme.panel2, key_rect, border_radius=7)
                pygame.draw.rect(self.screen, self.theme.panel_edge, key_rect, 1, border_radius=7)
                key = self.ui_font(13, True).render(key_name, True, self.theme.accent)
                self.screen.blit(key, key.get_rect(center=key_rect.center))
                desc = self.ui_font(14, False).render(description, True, self.theme.text)
                self.screen.blit(desc, (col_x + 92, cy + 6))

        footer = self.tiny_font.render(
            "Tab / Shift+Tab navigates  •  Enter activates  •  Esc closes",
            True, self.theme.muted)
        self.screen.blit(footer, (box.x + 32, box.bottom - 43))
        self.help_close_button = pygame.Rect(box.right - 142, box.bottom - 57, 110, 36)
        self.draw_button(self.help_close_button, "Done", variant="primary",
                         font=self.ui_font(14, True),
                         focused=self.help_visible and self.keyboard_focus)

    def checkmate_reveal_pending(self) -> bool:
        return (
            self.chess_board.is_checkmate()
            and self.game_over_reveal_at is not None
            and time.time() < self.game_over_reveal_at
        )

    def draw_checkmate_animation(self) -> None:
        """Pulse the mated king while the final move remains unobscured."""
        if not self.checkmate_reveal_pending() or self.game_over_reveal_at is None:
            return

        king_square = self.chess_board.king(self.chess_board.turn)
        if king_square is None:
            return

        started_at = self.game_over_reveal_at - self.checkmate_reveal_delay
        elapsed = max(0.0, time.time() - started_at)
        settled = max(0.0, elapsed - self.move_animation_duration)
        king_rect = self.square_rect(king_square)
        centre = king_rect.center

        # A soft red square breathes beneath two expanding rings.  It is
        # intentionally transparent so the king and mating move stay legible.
        phase = (settled % 0.7) / 0.7
        triangle = 1.0 - abs(phase * 2.0 - 1.0)
        square_glow = pygame.Surface(king_rect.size, pygame.SRCALPHA)
        glow_alpha = int(24 + triangle * 34)
        pygame.draw.rect(square_glow, (*self.theme.error, glow_alpha),
                         square_glow.get_rect(), border_radius=12)
        pygame.draw.rect(square_glow, (*self.theme.error, 105),
                         square_glow.get_rect(), 2, border_radius=12)
        self.screen.blit(square_glow, king_rect.topleft)

        if self.animation_mode == "Reduced":
            return

        ring_size = SQUARE_SIZE * 2
        rings = pygame.Surface((ring_size, ring_size), pygame.SRCALPHA)
        ring_centre = (ring_size // 2, ring_size // 2)
        for offset in (0.0, 0.38):
            age = settled - offset
            if age < 0:
                continue
            ring_phase = (age % 0.95) / 0.95
            radius = int(20 + ring_phase * 50)
            alpha = int(145 * (1.0 - ring_phase))
            pygame.draw.circle(rings, (*self.theme.error, alpha),
                               ring_centre, radius, 3)
        self.screen.blit(rings, rings.get_rect(center=centre))

    def game_over_message(self) -> tuple[str, str]:
        result = self.current_game_result()
        if self.clock_flagged is not None:
            flagged = "White" if self.clock_flagged == chess.WHITE else "Black"
            winner = "Black" if self.clock_flagged == chess.WHITE else "White"
            return f"{winner} wins", f"{flagged} loses on time"

        outcome = self.chess_board.outcome(claim_draw=True)

        if result == "1-0":
            title = "White wins"
        elif result == "0-1":
            title = "Black wins"
        else:
            title = "Draw"

        if outcome is None:
            detail = result
        elif outcome.termination == chess.Termination.CHECKMATE:
            detail = "Checkmate"
        elif outcome.termination == chess.Termination.STALEMATE:
            detail = "Stalemate"
        elif outcome.termination == chess.Termination.INSUFFICIENT_MATERIAL:
            detail = "Insufficient material"
        elif outcome.termination == chess.Termination.SEVENTYFIVE_MOVES:
            detail = "75-move rule"
        elif outcome.termination == chess.Termination.FIVEFOLD_REPETITION:
            detail = "Fivefold repetition"
        elif outcome.termination == chess.Termination.FIFTY_MOVES:
            detail = "50-move rule"
        elif outcome.termination == chess.Termination.THREEFOLD_REPETITION:
            detail = "Threefold repetition"
        else:
            detail = result

        return title, detail

    def draw_game_over_overlay(self) -> None:
        if not self.game_is_over:
            return

        overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))

        box = pygame.Rect(0, 0, 500, 292)
        box.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2)
        self.draw_card(box, fill=self.theme.panel, border=self.theme.accent, radius=16)

        title, detail = self.game_over_message()

        result = self.current_game_result()
        icon_colour = chess.WHITE if result == "1-0" else chess.BLACK
        self.blit_piece(chess.Piece(chess.KING, icon_colour),
                        (box.centerx, box.y + 54), 70)
        title_surface = self.large_font.render(title, True,
                                               self.theme.accent2 if result != "1/2-1/2" else self.theme.text)
        self.screen.blit(title_surface, title_surface.get_rect(center=(box.centerx, box.y + 111)))

        detail_surface = self.small_font.render(detail, True, self.theme.muted)
        self.screen.blit(detail_surface, detail_surface.get_rect(center=(box.centerx, box.y + 146)))

        result_surface = self.small_font.render(
            f"Result: {self.current_game_result()}", True, self.theme.muted)
        result_pill = pygame.Rect(0, 0, 112, 30)
        result_pill.center = (box.centerx, box.y + 180)
        pygame.draw.rect(self.screen, self.theme.panel2, result_pill, border_radius=15)
        self.screen.blit(result_surface, result_surface.get_rect(center=result_pill.center))

        self.rematch_button = pygame.Rect(box.x + 52, box.bottom - 66, 188, 44)
        self.main_menu_button = pygame.Rect(box.x + 260, box.bottom - 66, 188, 44)
        focus = self.focus_index % 2 if self.keyboard_focus else -1
        self.draw_button(self.rematch_button, "Rematch", variant="primary",
                         focused=focus == 0)
        self.draw_button(self.main_menu_button, "Main menu", variant="secondary",
                         focused=focus == 1)

    def draw(self) -> None:
        if self.edit_mode:
            self.screen.blit(self.themed_background(), (0, 0))
            self.draw_eval_bar()
            self.draw_board(self.edit_board, show_marks=False)
            self.draw_edit_side_panel()
            if self.help_visible:
                self.draw_help_overlay()
            return

        if not self.game_started:
            self.draw_menu()
            if self.help_visible:
                self.draw_help_overlay()
            return

        self.screen.blit(self.themed_background(), (0, 0))
        self.draw_eval_bar()
        self.draw_board(self.chess_board, animate=True)
        self.draw_player_cards()
        self.draw_side_panel()

        if self.checkmate_reveal_pending():
            self.draw_checkmate_animation()
        elif self.game_is_over:
            self.draw_game_over_overlay()

        if self.promotion_pending is not None:
            self.draw_promotion_overlay()

        if self.input_mode == "fen":
            self.draw_text_input_overlay()

        if self.help_visible:
            self.draw_help_overlay()

    # ------------------------------------------------------------------
    # input handling
    # ------------------------------------------------------------------

    def handle_menu_click(self, pos: tuple[int, int]) -> None:
        self.keyboard_focus = False
        if self.theme_gallery_visible:
            for button in self.theme_gallery_buttons:
                if button.rect.collidepoint(pos):
                    self.play_sound("button")
                    self.handle_menu_action(button.action)
                    return
            return
        if self.time_gallery_visible:
            for button in self.time_gallery_buttons:
                if button.rect.collidepoint(pos):
                    self.play_sound("button")
                    self.handle_menu_action(button.action)
                    return
            return
        if self.settings_visible:
            for button in self.settings_buttons:
                if button.rect.collidepoint(pos) and not button.action.startswith("noop"):
                    self.play_sound("button")
                    self.handle_menu_action(button.action)
                    return
            return
        for button in self.menu_buttons:
            if button.rect.collidepoint(pos):
                if not button.action.startswith("noop"):
                    self.play_sound("button")
                self.handle_menu_action(button.action)
                return

    def handle_side_click(self, pos: tuple[int, int]) -> bool:
        for button in self.side_buttons:
            if not button.rect.collidepoint(pos):
                continue
            self.play_sound("button")
            if button.action == "side_help":
                self.help_visible = True
            elif button.action == "side_menu":
                self.return_to_main_menu()
            return True
        return pos[0] >= EVAL_PANEL_WIDTH + BOARD_SIZE

    def handle_menu_action(self, action: str) -> None:
        if action == "play_white":
            self.start_game(chess.WHITE)
        elif action == "play_black":
            self.start_game(chess.BLACK)
        elif action == "watch":
            self.start_game(None)
        elif action == "engine_prev":
            self.toggle_engine(-1)
        elif action == "engine_next":
            self.toggle_engine(1)
        elif action == "theme_prev":
            self.cycle_theme(-1)
        elif action == "theme_next":
            self.cycle_theme(1)
        elif action == "theme_gallery":
            self.theme_gallery_visible = True
            self.time_gallery_visible = False
            self.settings_visible = False
            self.focus_index = THEME_ORDER.index(self.theme_name)
        elif action.startswith("select_theme:"):
            self.select_theme(action.split(":", 1)[1])
        elif action == "theme_done":
            self.theme_gallery_visible = False
            self.focus_index = 0
        elif action == "time_gallery":
            self.time_gallery_visible = True
            self.theme_gallery_visible = False
            self.settings_visible = False
            self.focus_index = self.time_control_index
        elif action.startswith("select_time:"):
            self.select_time_control(action.split(":", 1)[1])
        elif action == "time_done":
            self.time_gallery_visible = False
            self.focus_index = 0
        elif action == "depth_down":
            self.cycle_depth_cap(-1)
        elif action == "depth_up":
            self.cycle_depth_cap(1)
        elif action == "time_down":
            self.cycle_time_control(-1)
        elif action == "time_up":
            self.cycle_time_control(1)
        elif action == "toggle_auto_flip":
            self.auto_flip_as_black = not self.auto_flip_as_black
            self.mark_preferences_dirty()
        elif action == "show_settings":
            self.settings_visible = True
            self.theme_gallery_visible = False
            self.time_gallery_visible = False
            self.focus_index = 0
        elif action == "settings_done":
            self.settings_visible = False
            self.focus_index = 0
        elif action in ("animation_prev", "animation_next"):
            index = ANIMATION_MODES.index(self.animation_mode)
            direction = -1 if action.endswith("prev") else 1
            self.animation_mode = ANIMATION_MODES[(index + direction) % len(ANIMATION_MODES)]
            if self.animation_mode == "Off":
                self.animation = None
            self.mark_preferences_dirty()
        elif action.endswith("_down") or action.endswith("_up"):
            key, direction = action.rsplit("_", 1)
            attr = f"{key}_volume"
            if hasattr(self, attr):
                delta = -0.1 if direction == "down" else 0.1
                setattr(self, attr, self.valid_volume(getattr(self, attr) + delta))
                self.mark_preferences_dirty()
        elif action == "load_fen":
            self.human_colour = chess.WHITE
            self.begin_fen_input()
        elif action == "board_editor":
            self.enter_edit_mode()
        elif action == "show_help":
            self.help_visible = True

    def handle_promotion_click(self, pos: tuple[int, int]) -> None:
        if self.promotion_pending is None:
            return
        for rect, promo in self.promotion_buttons:
            if rect.collidepoint(pos):
                from_square, to_square = self.promotion_pending
                move = chess.Move(from_square, to_square, promotion=promo)
                if move in self.chess_board.legal_moves:
                    self.make_human_move(move, animate=self._promo_animate)
                else:
                    self.promotion_pending = None
                    self.status = "Illegal move"
                return
        self.promotion_pending = None
        self.status = "Promotion cancelled"

    def handle_text_input_key(self, event: pygame.event.Event) -> None:
        if event.key == pygame.K_ESCAPE:
            self.cancel_input()
            return

        if event.key == pygame.K_RETURN:
            if self.input_mode == "fen":
                self.load_fen(self.text_input)
            return

        if event.key == pygame.K_BACKSPACE:
            self.text_input = self.text_input[:-1]
            return

        if event.key == pygame.K_v and (pygame.key.get_mods() & pygame.KMOD_CTRL):
            try:
                pygame.scrap.init()
                data = pygame.scrap.get(pygame.SCRAP_TEXT)
                if data:
                    self.text_input += data.decode("utf-8", errors="ignore").replace("\x00", "")
            except pygame.error:
                pass
            return

        if event.unicode:
            self.text_input += event.unicode

    def active_focus_buttons(self) -> list[ButtonRect]:
        if self.theme_gallery_visible:
            return self.theme_gallery_buttons
        if self.time_gallery_visible:
            return self.time_gallery_buttons
        if self.settings_visible:
            return [button for button in self.settings_buttons
                    if not button.action.startswith("noop")]
        if self.help_visible:
            return [ButtonRect(self.help_close_button, "Done", "help_done", "primary")]
        if self.edit_mode:
            return self.edit_buttons
        if not self.game_started:
            return self.menu_focus_buttons()
        if self.promotion_pending is not None:
            return [ButtonRect(rect, str(promo), f"promote:{promo}")
                    for rect, promo in self.promotion_buttons]
        if self.game_is_over and not self.checkmate_reveal_pending():
            return [
                ButtonRect(self.rematch_button, "Rematch", "rematch", "primary"),
                ButtonRect(self.main_menu_button, "Main menu", "game_menu", "secondary"),
            ]
        return self.side_buttons

    def move_keyboard_focus(self, direction: int) -> None:
        buttons = self.active_focus_buttons()
        if not buttons:
            return
        if not self.keyboard_focus:
            self.focus_index = 0 if direction > 0 else len(buttons) - 1
        else:
            self.focus_index = (self.focus_index + direction) % len(buttons)
        self.keyboard_focus = True

    def activate_focused_button(self) -> None:
        buttons = self.active_focus_buttons()
        if not buttons:
            return
        button = buttons[self.focus_index % len(buttons)]
        action = button.action
        if action.startswith("promote:"):
            self.handle_promotion_click(button.rect.center)
        elif action.startswith("edit_"):
            self.handle_edit_action(action)
        elif action == "help_done":
            self.help_visible = False
        elif action == "side_menu" or action == "game_menu":
            self.return_to_main_menu()
        elif action == "side_help":
            self.help_visible = True
            self.focus_index = 0
        elif action == "rematch":
            self.restart()
        else:
            self.handle_menu_action(action)
        self.play_sound("button")

    def handle_keydown(self, event: pygame.event.Event) -> bool:
        if (
            event.key == pygame.K_F11
            or (event.key == pygame.K_RETURN and event.mod & pygame.KMOD_ALT)
        ):
            self.toggle_fullscreen()
            return True

        if self.input_mode is not None:
            self.handle_text_input_key(event)
            return True

        if event.key == pygame.K_TAB:
            direction = -1 if event.mod & pygame.KMOD_SHIFT else 1
            self.move_keyboard_focus(direction)
            return True

        if event.key in (pygame.K_RETURN, pygame.K_SPACE) and self.keyboard_focus:
            self.activate_focused_button()
            return True

        if self.theme_gallery_visible or self.time_gallery_visible or self.settings_visible:
            if event.key == pygame.K_ESCAPE:
                self.theme_gallery_visible = False
                self.time_gallery_visible = False
                self.settings_visible = False
                self.focus_index = 0
            return True

        if self.help_visible:
            if event.key in (pygame.K_ESCAPE, pygame.K_F1) or event.unicode == "?":
                self.help_visible = False
            return True

        if self.edit_mode:
            if event.key == pygame.K_ESCAPE:
                self.exit_edit_mode()
            elif event.key == pygame.K_f:
                self.flip_board = not self.flip_board
            elif event.key == pygame.K_t:
                self.cycle_theme()
            elif event.key == pygame.K_c:
                self.copy_fen_to_clipboard()
            elif event.key == pygame.K_RETURN:
                self.finish_edit_mode()
            return True

        if event.key == pygame.K_ESCAPE:
            if self.promotion_pending is not None:
                self.promotion_pending = None
                self.status = "Promotion cancelled"
                return True
            return False

        if event.key == pygame.K_F1 or event.unicode == "?":
            self.help_visible = True
            return True
        # theme + editor work in the menu too
        if event.key == pygame.K_t:
            self.cycle_theme()
            return True
        if event.key == pygame.K_e:
            self.enter_edit_mode()
            return True

        if event.key == pygame.K_f and self.game_started:
            self.flip_board = not self.flip_board
        elif event.key == pygame.K_r and self.game_started:
            self.restart()
        elif event.key == pygame.K_u and self.game_started:
            self.undo_move()
        elif event.key == pygame.K_LEFT and self.game_started:
            self.undo_ply()
        elif event.key == pygame.K_RIGHT and self.game_started:
            self.redo_ply()
        elif event.key == pygame.K_g and self.game_started:
            self.trigger_engine_move()
        elif event.key == pygame.K_SPACE and self.game_started and self.human_colour is None:
            self.watch_paused = not self.watch_paused
            self.status = "Watch paused" if self.watch_paused else "Watch resumed"
        elif event.key == pygame.K_c and self.game_started:
            self.copy_fen_to_clipboard()
        elif event.key == pygame.K_l:
            self.begin_fen_input()
        elif event.key == pygame.K_p and self.game_started:
            self.export_pgn()

        return True

    def run(self) -> None:
        running = True

        try:
            while running:
                self.update_game_clock()
                self.poll_engine_result()

                self.draw()
                self.present()
                pygame.display.flip()
                # tick() can collapse to ~60 FPS on Windows because of coarse
                # sleep granularity.  busy_loop uses high-precision timing and
                # is appropriate for the requested high-refresh renderer.
                self.clock.tick_busy_loop(TARGET_FPS)
                now_ms = pygame.time.get_ticks()
                if now_ms - self._fps_caption_at >= 500:
                    self._fps_caption_at = now_ms
                    if self.edit_mode:
                        caption = "Sgurr - Board editor"
                    elif self.game_started:
                        caption = f"Sgurr - {self.engine_name}"
                    else:
                        caption = "Sgurr"
                    pygame.display.set_caption(
                        f"{caption} - {self.clock.get_fps():.0f} FPS"
                    )
                self.save_preferences()

                if (
                    self.game_started
                    and not self.edit_mode
                    and self.input_mode is None
                    and self.human_colour is None
                    and not self.watch_paused
                    and not self.engine_thinking
                    and self.engine_to_move()
                ):
                    self.request_engine_move()

                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                    elif event.type == pygame.VIDEORESIZE:
                        width, height = max(640, event.w), max(400, event.h)
                        if not self.fullscreen:
                            self.window = self.create_window((width, height))
                            self.windowed_size = (width, height)
                        self.update_viewport(width, height)
                    elif event.type == pygame.KEYDOWN:
                        running = self.handle_keydown(event)
                    elif event.type == pygame.MOUSEBUTTONDOWN and event.button in (1, 3):
                        self.keyboard_focus = False
                        pos = self.to_logical(event.pos)
                        if self.help_visible:
                            if event.button == 1 and self.help_close_button.collidepoint(pos):
                                self.play_sound("button")
                                self.help_visible = False
                            continue
                        if self.input_mode is not None:
                            continue
                        if self.edit_mode:
                            self.handle_edit_click(pos, event.button)
                            continue
                        if event.button != 1:
                            continue
                        if not self.game_started:
                            self.handle_menu_click(pos)
                            continue
                        if self.promotion_pending is not None:
                            self.handle_promotion_click(pos)
                            continue
                        if self.game_is_over:
                            if self.checkmate_reveal_pending():
                                continue
                            if self.rematch_button.collidepoint(pos):
                                self.play_sound("button")
                                self.restart()
                            elif self.main_menu_button.collidepoint(pos):
                                self.play_sound("button")
                                self.return_to_main_menu()
                            continue
                        if self.handle_side_click(pos):
                            continue
                        self.start_piece_drag(pos)
                    elif event.type == pygame.MOUSEMOTION:
                        pos = self.to_logical(event.pos)
                        if self.edit_mode:
                            self.edit_drag_mouse = pos
                        else:
                            self.update_piece_drag(pos)
                    elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                        pos = self.to_logical(event.pos)
                        if self.input_mode is not None:
                            continue
                        if self.edit_mode:
                            self.handle_edit_release(pos)
                            continue
                        if not self.game_started:
                            continue
                        if self.promotion_pending is not None:
                            continue
                        if self.game_is_over:
                            continue
                        self.finish_piece_drag(pos)
        finally:
            self.save_preferences(force=True)
            self.close_engine()
            pygame.quit()

        sys.exit()

    @staticmethod
    def wrap_text(text: str, max_chars: int) -> list[str]:
        words = text.split()
        if not words:
            return [""]

        lines: list[str] = []
        current = words[0]

        for word in words[1:]:
            if len(current) + 1 + len(word) <= max_chars:
                current += " " + word
            else:
                lines.append(current)
                current = word

        lines.append(current)
        return lines


def main() -> None:
    gui = SgurrGui()
    gui.run()


if __name__ == "__main__":
    main()
