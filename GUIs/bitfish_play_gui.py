from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import chess
import chess.pgn
import pygame

try:
    from v11.bitfish_board_v11 import Board as BitfishBoard
    from v11.bitfish_board_v11 import Move as BitfishMove
    from v11.bitfish_engine_v11 import Engine as BitfishEngine
except ImportError:
    from v10.bitfish_board_v10 import Board as BitfishBoard
    from v10.bitfish_board_v10 import Move as BitfishMove
    from v10.bitfish_engine_v10 import Engine as BitfishEngine


EVAL_PANEL_WIDTH = 44
BOARD_SIZE = 640
SIDE_PANEL_WIDTH = 220
WINDOW_SIZE = EVAL_PANEL_WIDTH + BOARD_SIZE + SIDE_PANEL_WIDTH
SQUARE_SIZE = BOARD_SIZE // 8

DEFAULT_ENGINE_DEPTH = 10
DEFAULT_ENGINE_TIME_LIMIT = 3.0

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


class BitfishGui:
    def __init__(self) -> None:
        pygame.init()
        pygame.display.set_caption("Bitfish")

        self.screen = pygame.display.set_mode((WINDOW_SIZE, BOARD_SIZE))
        self.clock = pygame.time.Clock()

        self.board_font = pygame.font.SysFont("segoeuisymbol", 58)
        self.large_font = pygame.font.SysFont("arial", 32, bold=True)
        self.medium_font = pygame.font.SysFont("arial", 22, bold=True)
        self.small_font = pygame.font.SysFont("arial", 16)

        self.engine_depth = DEFAULT_ENGINE_DEPTH
        self.engine_time_limit = DEFAULT_ENGINE_TIME_LIMIT
        self.auto_flip_as_black = AUTO_FLIP_AS_BLACK

        self.chess_board = chess.Board()
        self.engine = BitfishEngine()

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

        self.input_mode: str | None = None
        self.text_input = ""
        self.input_error = ""

        self.menu_buttons = [
            ButtonRect(pygame.Rect(280, 150, 340, 52), "Play as White", "play_white"),
            ButtonRect(pygame.Rect(280, 215, 340, 52), "Play as Black", "play_black"),
            ButtonRect(pygame.Rect(280, 280, 340, 52), "Watch Bitfish vs itself", "watch"),
            ButtonRect(pygame.Rect(280, 365, 70, 38), "- Depth", "depth_down"),
            ButtonRect(pygame.Rect(362, 365, 176, 38), "Depth", "noop_depth"),
            ButtonRect(pygame.Rect(550, 365, 70, 38), "+ Depth", "depth_up"),
            ButtonRect(pygame.Rect(280, 415, 70, 38), "- Time", "time_down"),
            ButtonRect(pygame.Rect(362, 415, 176, 38), "Time", "noop_time"),
            ButtonRect(pygame.Rect(550, 415, 70, 38), "+ Time", "time_up"),
            ButtonRect(pygame.Rect(280, 465, 340, 38), "Toggle auto-flip as Black", "toggle_auto_flip"),
            ButtonRect(pygame.Rect(280, 515, 340, 38), "Load FEN", "load_fen"),
        ]

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

    def reset_runtime_state(self) -> None:
        self.selected_square = None
        self.last_move = None
        self.engine_info = ""
        self.last_engine_score = 0
        self.last_engine_score_from_white = 0
        self.input_mode = None
        self.text_input = ""
        self.input_error = ""

    def start_game(self, human_colour: chess.Color | None, fen: str | None = None) -> None:
        try:
            self.chess_board = chess.Board(fen) if fen else chess.Board()
        except ValueError:
            self.status = "Invalid FEN"
            return

        self.engine = BitfishEngine()
        self.human_colour = human_colour
        self.flip_board = bool(self.auto_flip_as_black and human_colour == chess.BLACK)

        self.reset_runtime_state()
        self.game_started = True
        self.update_static_eval_display()

        if human_colour is None:
            self.status = "Watching Bitfish vs itself"
        elif human_colour == chess.WHITE:
            self.status = "You are White"
        else:
            self.status = "You are Black"

        if self.engine_to_move():
            self.draw()
            pygame.display.flip()
            self.make_engine_move()

    def restart(self) -> None:
        self.start_game(self.human_colour)

    def load_fen(self, fen: str) -> None:
        try:
            board = chess.Board(fen.strip())
        except ValueError:
            self.input_error = "Invalid FEN"
            self.status = "Invalid FEN"
            return

        self.chess_board = board
        self.engine = BitfishEngine()
        self.selected_square = None
        self.last_move = None
        self.engine_info = ""
        self.game_started = True
        self.input_mode = None
        self.text_input = ""
        self.input_error = ""
        self.update_static_eval_display()
        self.status = "Loaded FEN"

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
            self.selected_square = None
            return

        self.chess_board.push(move)
        self.last_move = move
        self.selected_square = None
        self.status = "Bitfish thinking..."
        self.update_static_eval_display()
        self.draw()
        pygame.display.flip()

        self.update_game_over_status()

        if self.engine_to_move():
            self.make_engine_move()

    def make_engine_move(self) -> None:
        if self.chess_board.is_game_over(claim_draw=True):
            self.update_game_over_status()
            return

        self.engine_thinking = True
        self.status = "Bitfish thinking..."
        self.draw()
        pygame.display.flip()

        bitfish_board = BitfishBoard(self.chess_board.fen())

        start = time.time()
        result = self.engine.search_best_move(
            bitfish_board,
            max_depth=self.engine_depth,
            time_limit=self.engine_time_limit,
        )
        elapsed = time.time() - start

        self.engine_thinking = False

        if result.best_move is None:
            self.status = "Bitfish found no move"
            return

        move = chess.Move.from_uci(str(result.best_move))

        if move not in self.chess_board.legal_moves:
            self.status = f"Bitfish illegal move: {move}"
            return

        self.last_engine_score = result.score
        self.chess_board.push(move)
        self.last_move = move
        self.update_static_eval_display()

        if SHOW_ENGINE_INFO:
            self.engine_info = (
                f"depth {result.depth}, "
                f"nodes {result.nodes}, "
                f"{elapsed:.2f}s, "
                f"score {result.score}"
            )

        self.status = "Your move" if self.human_to_move() else "Bitfish to move"
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
        self.engine_info = ""
        self.status = "Move undone"
        self.update_static_eval_display()

    def export_pgn(self) -> None:
        out_dir = Path("analysis_games")
        out_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = out_dir / f"bitfish_gui_game_{timestamp}.pgn"

        game = chess.pgn.Game.from_board(self.chess_board)
        game.headers["Event"] = "Bitfish GUI Game"
        game.headers["Date"] = datetime.now().strftime("%Y.%m.%d")
        game.headers["White"] = self.player_name(chess.WHITE)
        game.headers["Black"] = self.player_name(chess.BLACK)
        game.headers["Result"] = self.chess_board.result(claim_draw=True)

        path.write_text(str(game) + "\n\n", encoding="utf-8")
        self.status = f"PGN exported: {path}"

    def player_name(self, colour: chess.Color) -> str:
        if self.human_colour is None:
            return "Bitfish"

        if self.human_colour == colour:
            return "Human"

        return "Bitfish"

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
            board = BitfishBoard(self.chess_board.fen())
            score = board.evaluate()
            self.last_engine_score_from_white = score if board.side_to_move == 0 else -score
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

        title = self.large_font.render("Bitfish", True, TEXT)
        self.screen.blit(title, title.get_rect(center=(WINDOW_SIZE // 2, 70)))

        subtitle = self.small_font.render("Choose how you want to play", True, MUTED_TEXT)
        self.screen.blit(subtitle, subtitle.get_rect(center=(WINDOW_SIZE // 2, 110)))

        mouse_pos = pygame.mouse.get_pos()

        for button in self.menu_buttons:
            label = button.label

            if button.action == "noop_depth":
                label = f"Depth: {self.engine_depth}"
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
        self.screen.blit(hint, hint.get_rect(center=(WINDOW_SIZE // 2, 590)))

        if self.input_mode == "fen":
            self.draw_text_input_overlay()

    def draw_board(self) -> None:
        for rank in range(8):
            for file in range(8):
                square = chess.square(file, rank)
                row, col = self.square_to_screen(square)

                rect = pygame.Rect(EVAL_PANEL_WIDTH + col * SQUARE_SIZE, row * SQUARE_SIZE, SQUARE_SIZE, SQUARE_SIZE)

                colour = LIGHT_SQUARE if (rank + file) % 2 == 0 else DARK_SQUARE

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
            row, col = self.square_to_screen(square)
            rect = pygame.Rect(EVAL_PANEL_WIDTH + col * SQUARE_SIZE, row * SQUARE_SIZE, SQUARE_SIZE, SQUARE_SIZE)

            symbol = PIECE_SYMBOLS[(piece.color, piece.piece_type)]
            text = self.board_font.render(symbol, True, (20, 20, 20))
            text_rect = text.get_rect()
            text_rect.centerx = rect.centerx
            text_rect.centery = rect.centery + 2

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
        panel_rect = pygame.Rect(EVAL_PANEL_WIDTH + BOARD_SIZE, 0, SIDE_PANEL_WIDTH, BOARD_SIZE)
        pygame.draw.rect(self.screen, PANEL, panel_rect)

        y = 18
        x = EVAL_PANEL_WIDTH + BOARD_SIZE + 12

        def draw_line(text: str, colour: tuple[int, int, int] = TEXT) -> None:
            nonlocal y
            rendered = self.small_font.render(text, True, colour)
            self.screen.blit(rendered, (x, y))
            y += 22

        draw_line("Bitfish", TEXT)
        y += 8

        draw_line(f"Depth: {self.engine_depth}", MUTED_TEXT)
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
        draw_line("W lost: " + (" ".join(white_captured) if white_captured else "-"), TEXT)
        draw_line("B lost: " + (" ".join(black_captured) if black_captured else "-"), TEXT)
        y += 8

        draw_line("Status:", MUTED_TEXT)
        status_colour = ERROR_TEXT if "Invalid" in self.status or "Illegal" in self.status else TEXT
        for line in self.wrap_text(self.status, 28):
            draw_line(line, status_colour)
        y += 8

        if self.engine_info:
            draw_line("Engine:", MUTED_TEXT)
            for chunk in self.engine_info.split(", "):
                draw_line(chunk, TEXT)

        y = BOARD_SIZE - 150
        draw_line("Keys:", MUTED_TEXT)
        draw_line("F  flip board", MUTED_TEXT)
        draw_line("R  restart", MUTED_TEXT)
        draw_line("U  undo", MUTED_TEXT)
        draw_line("L  load FEN", MUTED_TEXT)
        draw_line("P  export PGN", MUTED_TEXT)
        draw_line("Esc quit/cancel", MUTED_TEXT)

    def draw_text_input_overlay(self) -> None:
        overlay = pygame.Surface((WINDOW_SIZE, BOARD_SIZE), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))

        box = pygame.Rect(80, 220, WINDOW_SIZE - 160, 160)
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

    def draw(self) -> None:
        if not self.game_started:
            self.draw_menu()
            return

        self.screen.fill(BACKGROUND)
        self.draw_eval_bar()
        self.draw_board()
        self.draw_side_panel()

        if self.input_mode == "fen":
            self.draw_text_input_overlay()

    def handle_menu_click(self, pos: tuple[int, int]) -> None:
        for button in self.menu_buttons:
            if button.rect.collidepoint(pos):
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
            self.engine_depth = min(20, self.engine_depth + 1)
        elif action == "time_down":
            self.engine_time_limit = max(0.2, round(self.engine_time_limit - 0.5, 1))
        elif action == "time_up":
            self.engine_time_limit = min(30.0, round(self.engine_time_limit + 0.5, 1))
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
                    square = self.screen_to_square(*event.pos)
                    if square is not None:
                        self.handle_board_click(square)

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
