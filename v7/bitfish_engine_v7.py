from __future__ import annotations

import sys
import time
from dataclasses import dataclass

from v7.bitfish_board_v7 import (
    Board,
    Move,
    WHITE,
    PIECE_VALUE,
    START_FEN,
)


INF = 10_000_000
MATE = 1_000_000

MAX_DEPTH = 5
MAX_PLY = 128
NULL_MOVE_REDUCTION = 2
LMR_FULL_DEPTH_MOVES = 4
LMR_MIN_DEPTH = 3

TT_EXACT = 0
TT_LOWER = 1
TT_UPPER = 2

MAX_TT_SIZE = 1_000_000


@dataclass
class SearchResult:
    best_move: Move | None
    score: int
    depth: int
    nodes: int
    tt_hits: int
    time_taken: float


@dataclass
class TTEntry:
    depth: int
    score: int
    flag: int
    best_move_key: tuple[int, int, int | None, bool, bool] | None


def move_key(move: Move) -> tuple[int, int, int | None, bool, bool]:
    return (
        move.from_sq,
        move.to_sq,
        move.promotion,
        move.is_en_passant,
        move.is_castling,
    )



class Engine:
    def __init__(self) -> None:
        self.nodes = 0
        self.tt_hits = 0
        self.start_time = 0.0
        self.time_limit: float | None = None
        self.stop_search = False

        self.transposition_table: dict[int, TTEntry] = {}
        self.killer_moves: list[
            list[tuple[int, int, int | None, bool, bool] | None]
        ] = [[None, None] for _ in range(MAX_PLY)]
        self.history: list[list[int]] = [
            [0 for _ in range(64)]
            for _ in range(64)
        ]

    def search_best_move(
        self,
        board: Board,
        max_depth: int = MAX_DEPTH,
        time_limit: float | None = None,
    ) -> SearchResult:
        self.nodes = 0
        self.tt_hits = 0
        self.start_time = time.time()
        self.time_limit = time_limit
        self.stop_search = False
        self.killer_moves = [[None, None] for _ in range(MAX_PLY)]

        best_move = None
        best_score = -INF
        completed_depth = 0

        for depth in range(1, max_depth + 1):
            score, move = self.negamax_root(board, depth)

            if self.stop_search:
                break

            if move is not None:
                best_move = move
                best_score = score
                completed_depth = depth

            print(
                f"info depth {depth} score cp {best_score} "
                f"nodes {self.nodes} tthits {self.tt_hits} "
                f"time {int((time.time() - self.start_time) * 1000)} pv {best_move}",
                flush=True,
            )

        return SearchResult(
            best_move=best_move,
            score=best_score,
            depth=completed_depth,
            nodes=self.nodes,
            tt_hits=self.tt_hits,
            time_taken=time.time() - self.start_time,
        )

    def time_is_up(self) -> bool:
        if self.time_limit is None:
            return False

        return time.time() - self.start_time >= self.time_limit

    def negamax_root(self, board: Board, depth: int) -> tuple[int, Move | None]:
        alpha = -INF
        beta = INF

        best_score = -INF
        best_move = None

        board_hash = board.hash_key
        tt_move_key = self.get_tt_move_key(board_hash)

        moves = board.generate_pseudo_legal_moves()
        moves = self.order_moves(board, moves, tt_move_key, 0)

        original_alpha = alpha
        us = board.side_to_move
        legal_found = False

        for move in moves:
            if self.time_is_up():
                self.stop_search = True
                break

            undo = board.make_move(move)

            if board.in_check(us):
                board.unmake_move(undo)
                continue

            legal_found = True
            score = -self.negamax(board, depth - 1, -beta, -alpha, 1)
            board.unmake_move(undo)

            if self.stop_search:
                break

            if score > best_score:
                best_score = score
                best_move = move

            alpha = max(alpha, score)

        if not legal_found:
            if board.in_check(us):
                return -MATE, None
            return 0, None

        if not self.stop_search and best_move is not None:
            flag = TT_EXACT

            if best_score <= original_alpha:
                flag = TT_UPPER
            elif best_score >= beta:
                flag = TT_LOWER

            self.store_tt(
                board_hash,
                depth,
                best_score,
                flag,
                move_key(best_move),
            )

        return best_score, best_move


    def is_killer_move(self, ply: int, move: Move) -> bool:
        if ply >= MAX_PLY:
            return False

        key = move_key(move)
        return key == self.killer_moves[ply][0] or key == self.killer_moves[ply][1]

    def can_reduce_late_move(
        self,
        board: Board,
        move: Move,
        depth: int,
        ply: int,
        legal_moves_searched: int,
        tt_move_key: tuple[int, int, int | None, bool, bool] | None,
        in_check: bool,
    ) -> bool:
        if depth < LMR_MIN_DEPTH:
            return False

        if in_check:
            return False

        if legal_moves_searched <= LMR_FULL_DEPTH_MOVES:
            return False

        if tt_move_key is not None and move_key(move) == tt_move_key:
            return False

        if self.is_noisy_move(board, move):
            return False

        if self.is_killer_move(ply, move):
            return False

        return True

    def can_try_null_move(self, board: Board, depth: int, beta: int, ply: int) -> bool:
        if depth < 3:
            return False

        if ply == 0:
            return False

        if beta >= MATE - 1000:
            return False

        if board.in_check(board.side_to_move):
            return False

        return board.has_non_pawn_material(board.side_to_move)

    def negamax(
        self,
        board: Board,
        depth: int,
        alpha: int,
        beta: int,
        ply: int,
    ) -> int:
        self.nodes += 1

        if self.nodes % 4096 == 0 and self.time_is_up():
            self.stop_search = True
            return 0

        board_hash = board.hash_key
        original_alpha = alpha

        entry = self.transposition_table.get(board_hash)

        if entry is not None and entry.depth >= depth:
            self.tt_hits += 1

            if entry.flag == TT_EXACT:
                return entry.score

            if entry.flag == TT_LOWER:
                alpha = max(alpha, entry.score)

            elif entry.flag == TT_UPPER:
                beta = min(beta, entry.score)

            if alpha >= beta:
                return entry.score

        if depth == 0:
            return self.quiescence(board, alpha, beta, ply)

        us = board.side_to_move
        in_check_node = board.in_check(us)

        if self.can_try_null_move(board, depth, beta, ply):
            undo = board.make_null_move()
            score = -self.negamax(
                board,
                depth - 1 - NULL_MOVE_REDUCTION,
                -beta,
                -beta + 1,
                ply + 1,
            )
            board.unmake_null_move(undo)

            if self.stop_search:
                return 0

            if score >= beta:
                self.store_tt(
                    board_hash,
                    depth,
                    beta,
                    TT_LOWER,
                    None,
                )
                return beta

        tt_move_key = entry.best_move_key if entry is not None else None

        moves = board.generate_pseudo_legal_moves()
        moves = self.order_moves(board, moves, tt_move_key, ply)

        best_score = -INF
        best_move_key = None
        legal_found = False
        legal_moves_searched = 0

        for move in moves:
            reduce_late_move = self.can_reduce_late_move(
                board,
                move,
                depth,
                ply,
                legal_moves_searched,
                tt_move_key,
                in_check_node,
            )

            undo = board.make_move(move)

            if board.in_check(us):
                board.unmake_move(undo)
                continue

            legal_found = True
            legal_moves_searched += 1

            if reduce_late_move:
                score = -self.negamax(
                    board,
                    depth - 2,
                    -alpha - 1,
                    -alpha,
                    ply + 1,
                )

                if score > alpha and not self.stop_search:
                    score = -self.negamax(board, depth - 1, -beta, -alpha, ply + 1)
            else:
                score = -self.negamax(board, depth - 1, -beta, -alpha, ply + 1)

            board.unmake_move(undo)

            if self.stop_search:
                return 0

            if score > best_score:
                best_score = score
                best_move_key = move_key(move)

            alpha = max(alpha, score)

            if alpha >= beta:
                if not self.is_noisy_move(board, move):
                    self.store_killer(ply, move)
                    self.history[move.from_sq][move.to_sq] += depth * depth
                break

        if not legal_found:
            if in_check_node:
                return -MATE + ply
            return 0

        flag = TT_EXACT

        if best_score <= original_alpha:
            flag = TT_UPPER
        elif best_score >= beta:
            flag = TT_LOWER

        self.store_tt(
            board_hash,
            depth,
            best_score,
            flag,
            best_move_key,
        )

        return best_score

    def quiescence(self, board: Board, alpha: int, beta: int, ply: int) -> int:
        self.nodes += 1

        stand_pat = board.evaluate()

        if stand_pat >= beta:
            return beta

        alpha = max(alpha, stand_pat)

        moves = [
            move for move in board.generate_pseudo_legal_moves()
            if self.is_noisy_move(board, move)
        ]

        moves = self.order_moves(board, moves, None, ply)
        us = board.side_to_move

        for move in moves:
            undo = board.make_move(move)

            if board.in_check(us):
                board.unmake_move(undo)
                continue

            score = -self.quiescence(board, -beta, -alpha, ply + 1)
            board.unmake_move(undo)

            if score >= beta:
                return beta

            alpha = max(alpha, score)

        return alpha

    def store_tt(
        self,
        board_hash: int,
        depth: int,
        score: int,
        flag: int,
        best_move_key: tuple[int, int, int | None, bool, bool] | None,
    ) -> None:
        if len(self.transposition_table) >= MAX_TT_SIZE:
            self.transposition_table.clear()

        old_entry = self.transposition_table.get(board_hash)

        if old_entry is None or depth >= old_entry.depth:
            self.transposition_table[board_hash] = TTEntry(
                depth=depth,
                score=score,
                flag=flag,
                best_move_key=best_move_key,
            )

    def get_tt_move_key(
        self,
        board_hash: int,
    ) -> tuple[int, int, int | None, bool, bool] | None:
        entry = self.transposition_table.get(board_hash)

        if entry is None:
            return None

        return entry.best_move_key

    def is_noisy_move(self, board: Board, move: Move) -> bool:
        if move.promotion is not None:
            return True

        if move.is_en_passant:
            return True

        return board.piece_at(move.to_sq) is not None

    def store_killer(self, ply: int, move: Move) -> None:
        if ply >= MAX_PLY:
            return

        key = move_key(move)

        if self.killer_moves[ply][0] == key:
            return

        self.killer_moves[ply][1] = self.killer_moves[ply][0]
        self.killer_moves[ply][0] = key

    def order_moves(
        self,
        board: Board,
        moves: list[Move],
        tt_move_key: tuple[int, int, int | None, bool, bool] | None,
        ply: int,
    ) -> list[Move]:
        tt_move: Move | None = None
        captures: list[Move] = []
        killer_one: Move | None = None
        killer_two: Move | None = None
        quiets: list[Move] = []

        killer_key_one = None
        killer_key_two = None

        if ply < MAX_PLY:
            killer_key_one = self.killer_moves[ply][0]
            killer_key_two = self.killer_moves[ply][1]

        for move in moves:
            key = move_key(move)

            if tt_move_key is not None and key == tt_move_key:
                tt_move = move
                continue

            if self.is_noisy_move(board, move):
                captures.append(move)
                continue

            if killer_key_one is not None and key == killer_key_one:
                killer_one = move
                continue

            if killer_key_two is not None and key == killer_key_two:
                killer_two = move
                continue

            quiets.append(move)

        captures.sort(
            key=lambda move: self.capture_score(board, move),
            reverse=True,
        )

        ordered: list[Move] = []

        if tt_move is not None:
            ordered.append(tt_move)

        ordered.extend(captures)

        if killer_one is not None:
            ordered.append(killer_one)

        if killer_two is not None:
            ordered.append(killer_two)

        if quiets:
            good_quiets: list[Move] = []
            other_quiets: list[Move] = []

            for move in quiets:
                if self.history[move.from_sq][move.to_sq] > 0:
                    good_quiets.append(move)
                else:
                    other_quiets.append(move)

            if good_quiets:
                good_quiets.sort(
                    key=lambda move: self.history[move.from_sq][move.to_sq],
                    reverse=True,
                )
                ordered.extend(good_quiets)

            ordered.extend(other_quiets)

        return ordered

    def capture_score(self, board: Board, move: Move) -> int:
        if move.promotion is not None:
            return 8_000 + PIECE_VALUE[move.promotion]

        if move.is_en_passant:
            return 10_100

        attacker = board.piece_at(move.from_sq)
        victim = board.piece_at(move.to_sq)

        if victim is None or attacker is None:
            return 0

        return 10_000 + 10 * PIECE_VALUE[victim] - PIECE_VALUE[attacker]


def parse_move(board: Board, text: str) -> Move | None:
    text = text.strip()

    for move in board.generate_legal_moves():
        if str(move) == text:
            return move

    return None


def apply_uci_position(board: Board, command: str) -> Board:
    parts = command.split()

    if len(parts) < 2:
        return board

    if parts[1] == "startpos":
        board = Board(START_FEN)
        move_start = 3 if len(parts) > 2 and parts[2] == "moves" else len(parts)

    elif parts[1] == "fen":
        if "moves" in parts:
            moves_index = parts.index("moves")
            fen = " ".join(parts[2:moves_index])
            move_start = moves_index + 1
        else:
            fen = " ".join(parts[2:])
            move_start = len(parts)

        board = Board(fen)

    else:
        return board

    for move_text in parts[move_start:]:
        move = parse_move(board, move_text)

        if move is None:
            break

        board.make_move(move)

    return board


def parse_go_depth(command: str) -> int:
    parts = command.split()

    if "depth" in parts:
        index = parts.index("depth")

        if index + 1 < len(parts):
            return int(parts[index + 1])

    return MAX_DEPTH


def parse_go_movetime(command: str) -> float | None:
    parts = command.split()

    if "movetime" in parts:
        index = parts.index("movetime")

        if index + 1 < len(parts):
            return int(parts[index + 1]) / 1000

    return None


def uci_loop() -> None:
    board = Board()
    engine = Engine()

    while True:
        try:
            command = input().strip()
        except EOFError:
            break

        if command == "uci":
            print("id name BitGarry")
            print("id author Tom")
            print("uciok")

        elif command == "isready":
            print("readyok")

        elif command == "ucinewgame":
            board = Board()
            engine.transposition_table.clear()
            engine.killer_moves = [[None, None] for _ in range(MAX_PLY)]
            engine.history = [[0 for _ in range(64)] for _ in range(64)]

        elif command.startswith("position"):
            board = apply_uci_position(board, command)

        elif command.startswith("go"):
            depth = parse_go_depth(command)
            movetime = parse_go_movetime(command)

            result = engine.search_best_move(
                board,
                max_depth=depth,
                time_limit=movetime,
            )

            if result.best_move is None:
                print("bestmove 0000")
            else:
                print(f"bestmove {result.best_move}")

        elif command == "quit":
            break


def human_loop() -> None:
    board = Board()
    engine = Engine()

    print("BitGarry v7 command mode")
    print("commands: display, moves, best, go 5, move e2e4, new, quit")

    while True:
        command = input("> ").strip()

        if command == "quit":
            break

        elif command == "new":
            board = Board()
            engine.transposition_table.clear()
            engine.killer_moves = [[None, None] for _ in range(MAX_PLY)]
            engine.history = [[0 for _ in range(64)] for _ in range(64)]
            board.print_board()

        elif command == "display":
            board.print_board()

        elif command == "moves":
            print(" ".join(str(move) for move in board.generate_legal_moves()))

        elif command == "best":
            result = engine.search_best_move(board, max_depth=MAX_DEPTH)
            print_result(result)

        elif command.startswith("go"):
            parts = command.split()
            depth = int(parts[1]) if len(parts) > 1 else MAX_DEPTH

            result = engine.search_best_move(board, max_depth=depth)
            print_result(result)

            if result.best_move is not None:
                board.make_move(result.best_move)
                board.print_board()

        elif command.startswith("move"):
            parts = command.split()

            if len(parts) < 2:
                print("usage: move e2e4")
                continue

            move = parse_move(board, parts[1])

            if move is None:
                print("illegal move")
            else:
                board.make_move(move)
                board.print_board()

        else:
            print("unknown command")


def print_result(result: SearchResult) -> None:
    if result.best_move is None:
        print("no legal move")
        return

    print(f"best move: {result.best_move}")
    print(f"score: {result.score}")
    print(f"depth: {result.depth}")
    print(f"nodes: {result.nodes}")
    print(f"tt hits: {result.tt_hits}")
    print(f"time: {result.time_taken:.3f}s")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "uci":
        uci_loop()
    else:
        human_loop()