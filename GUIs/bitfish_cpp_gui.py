from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import chess
import chess.engine
import chess.pgn
import pygame


PROJECT_DIR = Path(__file__).resolve().parent
BITFISH_CPP_PATH = PROJECT_DIR.parent / "bitfish_cpp_exp" / "bitfish_exp.exe"
MSYS2_UCRT64_BIN = r"C:\msys64\ucrt64\bin"
os.environ["PATH"] = MSYS2_UCRT64_BIN + os.pathsep + os.environ["PATH"]
ENGINE_TIMEOUT = 20.0



EVAL_PANEL_WIDTH = 72
BOARD_SIZE = 720
SIDE_PANEL_WIDTH = 360
WINDOW_WIDTH = EVAL_PANEL_WIDTH + BOARD_SIZE + SIDE_PANEL_WIDTH
WINDOW_HEIGHT = BOARD_SIZE
SQUARE_SIZE = BOARD_SIZE // 8

DEFAULT_ENGINE_DEPTH = 30
DEFAULT_ENGINE_TIME_LIMIT = 0.5

TIME_OPTIONS = [0.1, 0.2, 0.5, 1.0, 2.0, 3.0, 5.0, 7.5, 10.0]
MAX_ENGINE_DEPTH = 50

SOUND_DIR = PROJECT_DIR.parent / "assets" / "sounds"
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

AUTO_FLIP_AS_BLACK = False
SHOW_ENGINE_INFO = True

LIGHT_SQUARE = (238, 238, 210)
DARK_SQUARE = (118, 150, 86)
SELECTED_SQUARE = (246, 246, 105)
LEGAL_DOT = (60, 60, 60)
LAST_MOVE = (186, 202, 68)

BACKGROUND = (35, 35, 35)
PANEL = (45, 45, 45)
TEXT = (235, 235, 235)
MUTED_TEXT = (180, 180, 180)
BUTTON = (75, 75, 75)
BUTTON_HOVER = (95, 95, 95)
BUTTON_TEXT = (245, 245, 245)
ERROR_TEXT = (255, 130, 130)

MATERIAL_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 0,
}

EVAL_BAR_WIDTH = 24
EVAL_BAR_MARGIN = 8

PIECE_SYMBOLS = {
    (chess.WHITE, chess.PAWN): "♙",
    (chess.WHITE, chess.KNIGHT): "♘",
    (chess.WHITE, chess.BISHOP): "♗",
    (chess.WHITE, chess.ROOK): "♖",
    (chess.WHITE, chess.QUEEN): "♕",
    (chess.WHITE, chess.KING): "♔",
    (chess.BLACK, chess.PAWN): "♟",
    (chess.BLACK, chess.KNIGHT): "♞",
    (chess.BLACK, chess.BISHOP): "♝",
    (chess.BLACK, chess.ROOK): "♜",
    (chess.BLACK, chess.QUEEN): "♛",
    (chess.BLACK, chess.KING): "♚",
}


@dataclass
class ButtonRect:
    rect: pygame.Rect
    label: str
    action: str


@dataclass
class CppSearchResult:
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


class CppBitfishEngine:
    """Small wrapper that calls the C++ Bitfish UCI executable.

    A fresh process is used for each move. This is slightly slower than keeping
    one process alive, but it avoids unsafe persistent search state while the
    C++ port is still being stabilised.
    """

    def __init__(self, engine_path: Path = BITFISH_CPP_PATH) -> None:
        self.engine_path = engine_path

    def search_best_move(
        self,
        board: chess.Board,
        max_depth: int,
        time_limit: float,
    ) -> CppSearchResult:
        if not self.engine_path.exists():
            raise FileNotFoundError(
                f"Could not find {self.engine_path}. Compile the C++ engine first."
            )

        start = time.time()

        with chess.engine.SimpleEngine.popen_uci(
            [str(self.engine_path), "uci"],
            timeout=ENGINE_TIMEOUT,
        ) as engine:
            result = engine.play(
                board,
                chess.engine.Limit(time=time_limit, depth=max_depth),
                info=chess.engine.INFO_ALL,
            )

        elapsed = time.time() - start
        info = result.info
        score = score_to_white_centipawns(info.get("score"))
        depth = int(info.get("depth", 0))
        nodes = int(info.get("nodes", 0))

        return CppSearchResult(
            best_move=result.move,
            score=score,
            depth=depth,
            nodes=nodes,
            time_taken=elapsed,
        )

    def quick_white_eval(self, board: chess.Board) -> int:
        # cheap fallback for the eval bar; the full engine score is updated after searches
        if board.is_checkmate():
            return -100000 if board.turn == chess.WHITE else 100000

        if board.is_stalemate() or board.is_insufficient_material():
            return 0

        material = 0
        for piece in board.piece_map().values():
            value = MATERIAL_VALUES[piece.piece_type] * 100
            material += value if piece.color == chess.WHITE else -value

        return material


class BitfishGui:
    def __init__(self) -> None:
        pygame.init()
        self.sounds = self.load_sounds()
        pygame.display.set_caption("Bitfish C++")

        self.screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
        self.clock = pygame.time.Clock()

        self.board_font = pygame.font.SysFont("segoeuisymbol", 68)
        self.large_font = pygame.font.SysFont("arial", 32, bold=True)
        self.medium_font = pygame.font.SysFont("arial", 22, bold=True)
        self.small_font = pygame.font.SysFont("arial", 16)
        self.symbol_font = pygame.font.SysFont("segoeuisymbol", 20)

        self.engine_depth = DEFAULT_ENGINE_DEPTH
        self.engine_time_limit = DEFAULT_ENGINE_TIME_LIMIT
        self.auto_flip_as_black = AUTO_FLIP_AS_BLACK

        self.chess_board = chess.Board()
        self.engine = CppBitfishEngine()

        self.human_colour: chess.Color | None = None
        self.flip_board = False
        self.selected_square: chess.Square | None = None
        self.last_move: chess.Move | None = None

        self.status = "Choose a side"
        self.engine_info = ""
        self.last_engine_score = 0
        self.last_engine_score_from_white = 0
        self.game_started = False
        self.engine_thinking = False
        self.game_over_sound_played = False

        self.input_mode: str | None = None
        self.text_input = ""
        self.input_error = ""

        self.dragging_piece: chess.Piece | None = None
        self.dragging_from_square: chess.Square | None = None
        self.dragging_mouse_pos = (0, 0)
        self.drag_start_pos = (0, 0)
        self.drag_started = False

        menu_cx = WINDOW_WIDTH // 2

        def centred_rect(width: int, y: int, height: int) -> pygame.Rect:
            return pygame.Rect(menu_cx - width // 2, y, width, height)

        controls_w = 340
        left_x = menu_cx - controls_w // 2
        mid_x = left_x + 82
        right_x = left_x + 270

        self.menu_buttons = [
            ButtonRect(centred_rect(340, 150, 52), "Play as White", "play_white"),
            ButtonRect(centred_rect(340, 215, 52), "Play as Black", "play_black"),
            ButtonRect(centred_rect(340, 280, 52), "Watch Bitfish vs itself", "watch"),
            ButtonRect(pygame.Rect(left_x, 365, 70, 38), "- Max", "depth_down"),
            ButtonRect(pygame.Rect(mid_x, 365, 176, 38), "Max depth", "noop_depth"),
            ButtonRect(pygame.Rect(right_x, 365, 70, 38), "+ Max", "depth_up"),
            ButtonRect(pygame.Rect(left_x, 415, 70, 38), "- Time", "time_down"),
            ButtonRect(pygame.Rect(mid_x, 415, 176, 38), "Time", "noop_time"),
            ButtonRect(pygame.Rect(right_x, 415, 70, 38), "+ Time", "time_up"),
            ButtonRect(centred_rect(340, 465, 38), "Toggle auto-flip as Black", "toggle_auto_flip"),
            ButtonRect(centred_rect(340, 515, 38), "Load FEN", "load_fen"),
        ]

        self.main_menu_button = pygame.Rect(0, 0, 0, 0)

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

                    if name == "button":
                        sounds[name].set_volume(0.35)

                    break
                except pygame.error:
                    pass

        return sounds

    def play_sound(self, name: str) -> None:
        sound = self.sounds.get(name)
        if sound is None:
            return

        try:
            sound.play()
        except pygame.error:
            pass

    def play_game_over_sound(self) -> None:
        if self.game_over_sound_played:
            return

        result = self.chess_board.result(claim_draw=True)

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
        if self.chess_board.is_game_over(claim_draw=True):
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

    def screen_to_square(self, x: int, y: int) -> chess.Square | None:
        board_x = x - EVAL_PANEL_WIDTH

        if board_x < 0 or board_x >= BOARD_SIZE or y < 0 or y >= BOARD_SIZE:
            return None

        col = board_x // SQUARE_SIZE
        row = y // SQUARE_SIZE

        if self.flip_board:
            file = 7 - col
            rank = row
        else:
            file = col
            rank = 7 - row

        return chess.square(file, rank)


    def previous_time_option(self) -> float:
        for option in reversed(TIME_OPTIONS):
            if option < self.engine_time_limit - 1e-9:
                return option
        return TIME_OPTIONS[0]

    def next_time_option(self) -> float:
        for option in TIME_OPTIONS:
            if option > self.engine_time_limit + 1e-9:
                return option
        return TIME_OPTIONS[-1]

    def reset_runtime_state(self) -> None:
        self.selected_square = None
        self.last_move = None
        self.engine_info = ""
        self.last_engine_score = 0
        self.last_engine_score_from_white = 0
        self.game_over_sound_played = False
        self.input_mode = None
        self.text_input = ""
        self.input_error = ""
        self.clear_drag_state()

    def start_game(self, human_colour: chess.Color | None, fen: str | None = None) -> None:
        try:
            self.chess_board = chess.Board(fen) if fen else chess.Board()
        except ValueError:
            self.status = "Invalid FEN"
            return

        self.engine = CppBitfishEngine()
        self.human_colour = human_colour
        self.flip_board = bool(self.auto_flip_as_black and human_colour == chess.BLACK)

        self.reset_runtime_state()
        self.game_started = True
        self.update_static_eval_display()

        if human_colour is None:
            self.status = "Watching Bitfish C++ vs itself"
        elif human_colour == chess.WHITE:
            self.status = "You are White"
        else:
            self.status = "You are Black"

        self.play_sound("game_start")

        if self.engine_to_move():
            self.draw()
            pygame.display.flip()
            self.make_engine_move()

    def restart(self) -> None:
        self.start_game(self.human_colour)

    def return_to_main_menu(self) -> None:
        self.chess_board = chess.Board()
        self.engine = CppBitfishEngine()
        self.human_colour = None
        self.flip_board = False
        self.game_started = False
        self.engine_thinking = False
        self.status = "Choose a side"
        self.reset_runtime_state()

    def load_fen(self, fen: str) -> None:
        try:
            board = chess.Board(fen.strip())
        except ValueError:
            self.input_error = "Invalid FEN"
            self.status = "Invalid FEN"
            return

        self.chess_board = board
        self.engine = CppBitfishEngine()
        self.selected_square = None
        self.last_move = None
        self.engine_info = ""
        self.game_over_sound_played = False
        self.clear_drag_state()
        self.game_started = True
        self.input_mode = None
        self.text_input = ""
        self.input_error = ""
        self.update_static_eval_display()
        self.status = "Loaded FEN"
        self.play_sound("game_start")

        if self.engine_to_move():
            self.draw()
            pygame.display.flip()
            self.make_engine_move()

    def engine_to_move(self) -> bool:
        if self.chess_board.is_game_over(claim_draw=True):
            return False

        if self.human_colour is None:
            return True

        return self.chess_board.turn != self.human_colour

    def human_to_move(self) -> bool:
        if self.chess_board.is_game_over(claim_draw=True):
            return False

        return self.human_colour is not None and self.chess_board.turn == self.human_colour

    def update_game_over_status(self) -> None:
        if not self.chess_board.is_game_over(claim_draw=True):
            return

        result = self.chess_board.result(claim_draw=True)

        if result == "1-0":
            self.status = "White wins"
        elif result == "0-1":
            self.status = "Black wins"
        else:
            self.status = "Draw"

        self.play_game_over_sound()

    def legal_move_from_squares(self, from_square: chess.Square, to_square: chess.Square) -> chess.Move | None:
        candidate = chess.Move(from_square, to_square)

        if candidate in self.chess_board.legal_moves:
            return candidate

        piece = self.chess_board.piece_at(from_square)

        if piece is None or piece.piece_type != chess.PAWN:
            return None

        promotion_rank = 7 if piece.color == chess.WHITE else 0

        if chess.square_rank(to_square) != promotion_rank:
            return None

        for promotion in (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT):
            candidate = chess.Move(from_square, to_square, promotion=promotion)

            if candidate in self.chess_board.legal_moves:
                return candidate

        return None

    def clear_drag_state(self) -> None:
        self.dragging_piece = None
        self.dragging_from_square = None
        self.dragging_mouse_pos = (0, 0)
        self.drag_start_pos = (0, 0)
        self.drag_started = False

    def make_human_move(self, move: chess.Move) -> None:
        was_capture = self.chess_board.is_capture(move)
        was_castle = self.chess_board.is_castling(move)
        was_promotion = move.promotion is not None
        self.chess_board.push(move)
        self.play_move_sound(move, was_capture, was_castle, was_promotion, by_human=True)
        self.last_move = move
        self.selected_square = None
        self.clear_drag_state()
        self.status = "Bitfish C++ thinking..."
        self.update_static_eval_display()
        self.draw()
        pygame.display.flip()

        self.update_game_over_status()

        if self.engine_to_move():
            self.make_engine_move()

    def start_piece_drag(self, pos: tuple[int, int]) -> None:
        if not self.human_to_move() or self.input_mode is not None:
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
            move = self.legal_move_from_squares(from_square, to_square)
            if move is not None:
                self.make_human_move(move)
                return
            self.status = "Illegal move"
            self.play_sound("illegal")
            self.selected_square = None
        else:
            self.handle_board_click(from_square)

        self.clear_drag_state()

    def handle_board_click(self, square: chess.Square) -> None:
        if not self.human_to_move() or self.input_mode is not None:
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

        move = self.legal_move_from_squares(self.selected_square, square)

        if move is None:
            self.status = "Illegal move"
            self.play_sound("illegal")
            self.selected_square = None
            return

        self.make_human_move(move)

    def make_engine_move(self) -> None:
        if self.chess_board.is_game_over(claim_draw=True):
            self.update_game_over_status()
            return

        self.engine_thinking = True
        self.status = "Bitfish C++ thinking..."
        self.draw()
        pygame.display.flip()

        try:
            result = self.engine.search_best_move(
                self.chess_board,
                max_depth=self.engine_depth,
                time_limit=self.engine_time_limit,
            )
        except Exception as exc:
            self.engine_thinking = False
            self.status = f"Bitfish C++ error: {exc}"
            return

        elapsed = result.time_taken
        self.engine_thinking = False

        if result.best_move is None:
            self.status = "Bitfish C++ found no move"
            return

        move = result.best_move

        if move not in self.chess_board.legal_moves:
            self.status = f"Bitfish C++ illegal move: {move}"
            return

        self.last_engine_score = result.score
        self.last_engine_score_from_white = result.score
        was_capture = self.chess_board.is_capture(move)
        was_castle = self.chess_board.is_castling(move)
        was_promotion = move.promotion is not None
        self.chess_board.push(move)
        self.play_move_sound(move, was_capture, was_castle, was_promotion, by_human=False)
        self.last_move = move
        self.update_static_eval_display()

        if SHOW_ENGINE_INFO:
            self.engine_info = (
                f"depth {result.depth}, "
                f"nodes {result.nodes}, "
                f"{elapsed:.2f}s, "
                f"score {result.score}"
            )

        self.status = "Your move" if self.human_to_move() else "Bitfish C++ to move"
        self.update_game_over_status()

    def undo_move(self) -> None:
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
            self.chess_board.pop()

        self.last_move = self.chess_board.peek() if self.chess_board.move_stack else None
        self.selected_square = None
        self.clear_drag_state()
        self.engine_info = ""
        self.status = "Move undone"
        self.update_static_eval_display()

    def export_pgn(self) -> None:
        out_dir = Path("analysis_games")
        out_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = out_dir / f"bitfish_gui_game_{timestamp}.pgn"

        game = chess.pgn.Game.from_board(self.chess_board)
        game.headers["Event"] = "Bitfish C++ GUI Game"
        game.headers["Date"] = datetime.now().strftime("%Y.%m.%d")
        game.headers["White"] = self.player_name(chess.WHITE)
        game.headers["Black"] = self.player_name(chess.BLACK)
        game.headers["Result"] = self.chess_board.result(claim_draw=True)

        path.write_text(str(game) + "\n\n", encoding="utf-8")
        self.status = f"PGN exported: {path}"

    def player_name(self, colour: chess.Color) -> str:
        if self.human_colour is None:
            return "BitfishCPP"

        if self.human_colour == colour:
            return "Human"

        return "BitfishCPP"

    def begin_fen_input(self) -> None:
        self.input_mode = "fen"
        self.text_input = self.chess_board.fen() if self.game_started else ""
        self.input_error = ""
        self.status = "Paste/type FEN, Enter to load"

    def cancel_input(self) -> None:
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

    def captured_pieces(self) -> tuple[list[str], list[str]]:
        starting_counts = {
            chess.PAWN: 8,
            chess.KNIGHT: 2,
            chess.BISHOP: 2,
            chess.ROOK: 2,
            chess.QUEEN: 1,
        }

        white_captured: list[str] = []
        black_captured: list[str] = []

        for piece_type, starting_count in starting_counts.items():
            white_remaining = len(self.chess_board.pieces(piece_type, chess.WHITE))
            black_remaining = len(self.chess_board.pieces(piece_type, chess.BLACK))

            white_captured.extend([PIECE_SYMBOLS[(chess.WHITE, piece_type)]] * max(0, starting_count - white_remaining))
            black_captured.extend([PIECE_SYMBOLS[(chess.BLACK, piece_type)]] * max(0, starting_count - black_remaining))

        return white_captured, black_captured

    def update_static_eval_display(self) -> None:
        try:
            self.last_engine_score_from_white = self.engine.quick_white_eval(self.chess_board)
        except Exception:
            self.last_engine_score_from_white = 0

    def display_eval_pawns(self) -> float:
        if self.chess_board.is_checkmate():
            return -99.0 if self.chess_board.turn == chess.WHITE else 99.0

        if self.chess_board.is_stalemate() or self.chess_board.is_insufficient_material():
            return 0.0

        return self.last_engine_score_from_white / 100.0

    def eval_to_bar_fraction(self, eval_pawns: float) -> float:
        eval_pawns = max(-8.0, min(8.0, eval_pawns))
        return 1.0 / (1.0 + 10 ** (-eval_pawns / 4.0))

    def draw_menu(self) -> None:
        self.screen.fill(BACKGROUND)

        title = self.large_font.render("Bitfish C++", True, TEXT)
        self.screen.blit(title, title.get_rect(center=(WINDOW_WIDTH // 2, 70)))

        subtitle = self.small_font.render("Choose how you want to play", True, MUTED_TEXT)
        self.screen.blit(subtitle, subtitle.get_rect(center=(WINDOW_WIDTH // 2, 110)))

        mouse_pos = pygame.mouse.get_pos()

        for button in self.menu_buttons:
            label = button.label

            if button.action == "noop_depth":
                label = f"Max depth: {self.engine_depth}"
            elif button.action == "noop_time":
                label = f"Time: {self.engine_time_limit:.1f}s"
            elif button.action == "toggle_auto_flip":
                label = f"Auto-flip as Black: {self.auto_flip_as_black}"

            colour = BUTTON_HOVER if button.rect.collidepoint(mouse_pos) else BUTTON
            pygame.draw.rect(self.screen, colour, button.rect, border_radius=10)
            pygame.draw.rect(self.screen, (120, 120, 120), button.rect, 2, border_radius=10)

            font = self.small_font if button.rect.height < 45 else self.medium_font
            rendered = font.render(label, True, BUTTON_TEXT)
            self.screen.blit(rendered, rendered.get_rect(center=button.rect.center))

        hint = self.small_font.render(
            "In game: F flip, R restart, U undo, L load FEN, P export PGN, Esc quit",
            True,
            MUTED_TEXT,
        )
        self.screen.blit(hint, hint.get_rect(center=(WINDOW_WIDTH // 2, 620)))

        if self.input_mode == "fen":
            self.draw_text_input_overlay()

    def draw_board(self) -> None:
        for rank in range(8):
            for file in range(8):
                square = chess.square(file, rank)
                row, col = self.square_to_screen(square)

                rect = pygame.Rect(EVAL_PANEL_WIDTH + col * SQUARE_SIZE, row * SQUARE_SIZE, SQUARE_SIZE, SQUARE_SIZE)

                colour = DARK_SQUARE if (rank + file) % 2 == 0 else LIGHT_SQUARE

                if self.last_move is not None and square in (self.last_move.from_square, self.last_move.to_square):
                    colour = LAST_MOVE

                if self.selected_square == square:
                    colour = SELECTED_SQUARE

                pygame.draw.rect(self.screen, colour, rect)

        self.draw_legal_move_hints()
        self.draw_pieces()
        self.draw_coordinates()

    def draw_legal_move_hints(self) -> None:
        if self.selected_square is None:
            return

        for move in self.chess_board.legal_moves:
            if move.from_square != self.selected_square:
                continue

            row, col = self.square_to_screen(move.to_square)
            centre = (
                EVAL_PANEL_WIDTH + col * SQUARE_SIZE + SQUARE_SIZE // 2,
                row * SQUARE_SIZE + SQUARE_SIZE // 2,
            )

            pygame.draw.circle(self.screen, LEGAL_DOT, centre, 9)

    def draw_pieces(self) -> None:
        for square, piece in self.chess_board.piece_map().items():
            if square == self.dragging_from_square and self.dragging_piece is not None:
                continue

            row, col = self.square_to_screen(square)
            rect = pygame.Rect(EVAL_PANEL_WIDTH + col * SQUARE_SIZE, row * SQUARE_SIZE, SQUARE_SIZE, SQUARE_SIZE)
            self.draw_piece_symbol(piece, rect.center)

        if self.dragging_piece is not None:
            self.draw_piece_symbol(self.dragging_piece, self.dragging_mouse_pos)

    def draw_piece_symbol(self, piece: chess.Piece, centre: tuple[int, int]) -> None:
        symbol = PIECE_SYMBOLS[(piece.color, piece.piece_type)]
        text = self.board_font.render(symbol, True, (20, 20, 20))
        text_rect = text.get_rect()
        text_rect.centerx = centre[0]
        text_rect.centery = centre[1] + 2
        self.screen.blit(text, text_rect)

    def draw_coordinates(self) -> None:
        for i in range(8):
            if self.flip_board:
                file_label = chr(ord("h") - i)
                rank_label = str(i + 1)
            else:
                file_label = chr(ord("a") + i)
                rank_label = str(8 - i)

            file_text = self.small_font.render(file_label, True, MUTED_TEXT)
            rank_text = self.small_font.render(rank_label, True, MUTED_TEXT)

            self.screen.blit(file_text, (EVAL_PANEL_WIDTH + i * SQUARE_SIZE + SQUARE_SIZE - 14, BOARD_SIZE - 18))
            self.screen.blit(rank_text, (EVAL_PANEL_WIDTH + 4, i * SQUARE_SIZE + 4))

    def draw_eval_bar(self) -> None:
        bar_x = EVAL_BAR_MARGIN
        bar_y = EVAL_BAR_MARGIN
        bar_h = BOARD_SIZE - 2 * EVAL_BAR_MARGIN

        eval_pawns = self.display_eval_pawns()
        white_fraction = self.eval_to_bar_fraction(eval_pawns)

        white_h = int(bar_h * white_fraction)
        black_h = bar_h - white_h

        pygame.draw.rect(self.screen, (25, 25, 25), pygame.Rect(bar_x, bar_y, EVAL_BAR_WIDTH, black_h))
        pygame.draw.rect(self.screen, (235, 235, 235), pygame.Rect(bar_x, bar_y + black_h, EVAL_BAR_WIDTH, white_h))
        pygame.draw.rect(self.screen, (95, 95, 95), pygame.Rect(bar_x, bar_y, EVAL_BAR_WIDTH, bar_h), 2)

        label = "M" if eval_pawns >= 90 else "-M" if eval_pawns <= -90 else f"{eval_pawns:+.1f}"
        label_surface = self.small_font.render(label, True, TEXT)
        self.screen.blit(label_surface, (bar_x + EVAL_BAR_WIDTH + 3, bar_y + 4))

    def draw_side_panel(self) -> None:
        panel_rect = pygame.Rect(EVAL_PANEL_WIDTH + BOARD_SIZE, 0, SIDE_PANEL_WIDTH, WINDOW_HEIGHT)
        pygame.draw.rect(self.screen, PANEL, panel_rect)

        y = 18
        x = EVAL_PANEL_WIDTH + BOARD_SIZE + 12

        def draw_line(text: str, colour: tuple[int, int, int] = TEXT) -> None:
            nonlocal y
            rendered = self.small_font.render(text, True, colour)
            self.screen.blit(rendered, (x, y))
            y += 20

        def draw_captured_line(label: str, pieces: list[str]) -> None:
            nonlocal y
            label_surface = self.small_font.render(label, True, TEXT)
            self.screen.blit(label_surface, (x, y))
            cursor_x = x + label_surface.get_width() + 4

            if not pieces:
                dash = self.small_font.render("-", True, TEXT)
                self.screen.blit(dash, (cursor_x, y))
            else:
                for symbol in pieces:
                    symbol_surface = self.symbol_font.render(symbol, True, TEXT)
                    self.screen.blit(symbol_surface, (cursor_x, y - 2))
                    cursor_x += symbol_surface.get_width() + 3

            y += 20

        draw_line("Bitfish C++", TEXT)
        y += 8

        draw_line(f"Max depth: {self.engine_depth}", MUTED_TEXT)
        draw_line(f"Time: {self.engine_time_limit:.1f}s", MUTED_TEXT)
        y += 8

        if self.human_colour is None:
            draw_line("Mode: watch", MUTED_TEXT)
        else:
            side = "White" if self.human_colour == chess.WHITE else "Black"
            draw_line(f"You: {side}", MUTED_TEXT)

        draw_line(f"Turn: {'White' if self.chess_board.turn == chess.WHITE else 'Black'}", MUTED_TEXT)
        draw_line(f"Flip: {self.flip_board}", MUTED_TEXT)
        y += 8

        white_material, black_material, material_diff = self.material_score()

        draw_line("Material:", MUTED_TEXT)
        draw_line(f"W: {white_material}", TEXT)
        draw_line(f"B: {black_material}", TEXT)

        if material_diff > 0:
            draw_line(f"White +{material_diff}", TEXT)
        elif material_diff < 0:
            draw_line(f"Black +{-material_diff}", TEXT)
        else:
            draw_line("Equal", TEXT)

        y += 8

        eval_pawns = self.display_eval_pawns()
        draw_line("Eval:", MUTED_TEXT)

        if abs(eval_pawns) >= 90:
            eval_text = "White mate" if eval_pawns > 0 else "Black mate"
        else:
            eval_text = f"White {eval_pawns:+.1f}"

        draw_line(eval_text, TEXT)
        y += 8

        white_captured, black_captured = self.captured_pieces()
        draw_line("Captured:", MUTED_TEXT)
        draw_captured_line("W lost:", white_captured)
        draw_captured_line("B lost:", black_captured)
        y += 8

        draw_line("Status:", MUTED_TEXT)
        status_colour = ERROR_TEXT if "Invalid" in self.status or "Illegal" in self.status else TEXT
        for line in self.wrap_text(self.status, 42):
            draw_line(line, status_colour)
        y += 8

        if self.engine_info:
            draw_line("Engine:", MUTED_TEXT)
            for chunk in self.engine_info.split(", "):
                draw_line(chunk, TEXT)

        y = max(y + 12, WINDOW_HEIGHT - 150)
        draw_line("Keys:", MUTED_TEXT)
        draw_line("F  flip board", MUTED_TEXT)
        draw_line("R  restart", MUTED_TEXT)
        draw_line("U  undo", MUTED_TEXT)
        draw_line("L  load FEN", MUTED_TEXT)
        draw_line("P  export PGN", MUTED_TEXT)
        draw_line("Esc quit/cancel", MUTED_TEXT)

    def draw_text_input_overlay(self) -> None:
        overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))

        box = pygame.Rect(80, 220, WINDOW_WIDTH - 160, 160)
        pygame.draw.rect(self.screen, (50, 50, 50), box, border_radius=10)
        pygame.draw.rect(self.screen, (150, 150, 150), box, 2, border_radius=10)

        title = self.medium_font.render("Load FEN", True, TEXT)
        self.screen.blit(title, (box.x + 20, box.y + 15))

        prompt = self.small_font.render("Paste/type a FEN. Enter loads it. Esc cancels.", True, MUTED_TEXT)
        self.screen.blit(prompt, (box.x + 20, box.y + 50))

        shown_text = self.text_input[-90:] if len(self.text_input) > 90 else self.text_input
        input_rect = pygame.Rect(box.x + 20, box.y + 82, box.width - 40, 32)
        pygame.draw.rect(self.screen, (30, 30, 30), input_rect)
        pygame.draw.rect(self.screen, (120, 120, 120), input_rect, 1)

        rendered = self.small_font.render(shown_text, True, TEXT)
        self.screen.blit(rendered, (input_rect.x + 8, input_rect.y + 8))

        if self.input_error:
            error = self.small_font.render(self.input_error, True, ERROR_TEXT)
            self.screen.blit(error, (box.x + 20, box.y + 122))

    def game_over_message(self) -> tuple[str, str]:
        result = self.chess_board.result(claim_draw=True)
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
        if not self.chess_board.is_game_over(claim_draw=True):
            return

        overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))

        box = pygame.Rect(0, 0, 420, 230)
        box.center = (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2)

        pygame.draw.rect(self.screen, (45, 45, 45), box, border_radius=14)
        pygame.draw.rect(self.screen, (160, 160, 160), box, 2, border_radius=14)

        title, detail = self.game_over_message()

        title_surface = self.large_font.render(title, True, TEXT)
        self.screen.blit(title_surface, title_surface.get_rect(center=(box.centerx, box.y + 55)))

        detail_surface = self.medium_font.render(detail, True, MUTED_TEXT)
        self.screen.blit(detail_surface, detail_surface.get_rect(center=(box.centerx, box.y + 95)))

        result_surface = self.small_font.render(
            f"Result: {self.chess_board.result(claim_draw=True)}",
            True,
            MUTED_TEXT,
        )
        self.screen.blit(result_surface, result_surface.get_rect(center=(box.centerx, box.y + 125)))

        self.main_menu_button = pygame.Rect(0, 0, 180, 42)
        self.main_menu_button.center = (box.centerx, box.y + 175)

        mouse_pos = pygame.mouse.get_pos()
        colour = BUTTON_HOVER if self.main_menu_button.collidepoint(mouse_pos) else BUTTON

        pygame.draw.rect(self.screen, colour, self.main_menu_button, border_radius=10)
        pygame.draw.rect(self.screen, (120, 120, 120), self.main_menu_button, 2, border_radius=10)

        button_text = self.medium_font.render("Main menu", True, BUTTON_TEXT)
        self.screen.blit(button_text, button_text.get_rect(center=self.main_menu_button.center))

    def draw(self) -> None:
        if not self.game_started:
            self.draw_menu()
            return

        self.screen.fill(BACKGROUND)
        self.draw_eval_bar()
        self.draw_board()
        self.draw_side_panel()

        if self.chess_board.is_game_over(claim_draw=True):
            self.draw_game_over_overlay()

        if self.input_mode == "fen":
            self.draw_text_input_overlay()

    def handle_menu_click(self, pos: tuple[int, int]) -> None:
        for button in self.menu_buttons:
            if button.rect.collidepoint(pos):
                if not button.action.startswith("noop"):
                    self.play_sound("button")
                self.handle_menu_action(button.action)
                return

    def handle_menu_action(self, action: str) -> None:
        if action == "play_white":
            self.start_game(chess.WHITE)
        elif action == "play_black":
            self.start_game(chess.BLACK)
        elif action == "watch":
            self.start_game(None)
        elif action == "depth_down":
            self.engine_depth = max(1, self.engine_depth - 1)
        elif action == "depth_up":
            self.engine_depth = min(MAX_ENGINE_DEPTH, self.engine_depth + 1)
        elif action == "time_down":
            self.engine_time_limit = self.previous_time_option()
        elif action == "time_up":
            self.engine_time_limit = self.next_time_option()
        elif action == "toggle_auto_flip":
            self.auto_flip_as_black = not self.auto_flip_as_black
        elif action == "load_fen":
            self.game_started = True
            self.human_colour = chess.WHITE
            self.begin_fen_input()

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

    def handle_keydown(self, event: pygame.event.Event) -> bool:
        if self.input_mode is not None:
            self.handle_text_input_key(event)
            return True

        if event.key == pygame.K_ESCAPE:
            return False

        if event.key == pygame.K_f and self.game_started:
            self.flip_board = not self.flip_board
        elif event.key == pygame.K_r and self.game_started:
            self.restart()
        elif event.key == pygame.K_u and self.game_started:
            self.undo_move()
        elif event.key == pygame.K_l:
            self.begin_fen_input()
        elif event.key == pygame.K_p and self.game_started:
            self.export_pgn()

        return True

    def run(self) -> None:
        running = True

        while running:
            self.draw()
            pygame.display.flip()
            self.clock.tick(60)

            if self.game_started and self.input_mode is None and self.human_colour is None and self.engine_to_move():
                pygame.time.wait(200)
                self.make_engine_move()
                continue

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    running = self.handle_keydown(event)
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if self.input_mode is not None:
                        continue
                    if not self.game_started:
                        self.handle_menu_click(event.pos)
                        continue
                    if self.chess_board.is_game_over(claim_draw=True):
                        if self.main_menu_button.collidepoint(event.pos):
                            self.play_sound("button")
                            self.return_to_main_menu()
                        continue
                    self.start_piece_drag(event.pos)
                elif event.type == pygame.MOUSEMOTION:
                    self.update_piece_drag(event.pos)
                elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    if self.input_mode is not None or not self.game_started:
                        continue
                    if self.chess_board.is_game_over(claim_draw=True):
                        continue
                    self.finish_piece_drag(event.pos)

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
    gui = BitfishGui()
    gui.run()


if __name__ == "__main__":
    main()
