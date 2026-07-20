from __future__ import annotations

import unittest

import chess
from fastapi import HTTPException

from web.backend.main import (
    EngineMoveRequest,
    PlayerMoveRequest,
    board_from_history,
    engine_move,
    outcome_payload,
    player_move,
    project_premove_sequence,
    state_payload,
)


def replay(start_fen: str, moves: list[str]) -> chess.Board:
    board = chess.Board(start_fen)
    for move_text in moves:
        board.push_uci(move_text)
    return board


class DrawRulesTest(unittest.TestCase):
    def test_threefold_repetition_is_claimed(self) -> None:
        start_fen = chess.Board().fen()
        moves = ["g1f3", "g8f6", "f3g1", "f6g8"] * 2
        current = replay(start_fen, moves)

        board = board_from_history(current.fen(), start_fen, moves)
        outcome = outcome_payload(board)

        self.assertTrue(outcome["game_over"])
        self.assertEqual(outcome["result"], "1/2-1/2")
        self.assertEqual(outcome["reason"], "threefold_repetition")

    def test_fivefold_repetition_is_automatic(self) -> None:
        start_fen = chess.Board().fen()
        moves = ["g1f3", "g8f6", "f3g1", "f6g8"] * 4
        current = replay(start_fen, moves)

        board = board_from_history(current.fen(), start_fen, moves)
        outcome = outcome_payload(board)

        self.assertTrue(outcome["game_over"])
        self.assertEqual(outcome["reason"], "fivefold_repetition")

    def test_repetition_from_custom_start_position(self) -> None:
        custom_start = chess.Board()
        custom_start.push_uci("e2e4")
        start_fen = custom_start.fen()
        moves = ["g8f6", "g1f3", "f6g8", "f3g1"] * 2
        current = replay(start_fen, moves)

        board = board_from_history(current.fen(), start_fen, moves)
        outcome = outcome_payload(board)

        self.assertTrue(outcome["game_over"])
        self.assertEqual(outcome["reason"], "threefold_repetition")

    def test_player_move_that_creates_repetition_ends_game(self) -> None:
        start_fen = chess.Board().fen()
        moves = ["g1f3", "g8f6", "f3g1", "f6g8", "g1f3", "g8f6", "f3g1"]
        current = replay(start_fen, moves)

        payload = player_move(
            PlayerMoveRequest(
                fen=current.fen(),
                start_fen=start_fen,
                moves=moves,
                move="f6g8",
            )
        )

        self.assertTrue(payload["game_over"])
        self.assertEqual(payload["reason"], "threefold_repetition")

    def test_watch_mode_stops_before_searching_repeated_position(self) -> None:
        start_fen = chess.Board().fen()
        moves = ["g1f3", "g8f6", "f3g1", "f6g8"] * 2
        current = replay(start_fen, moves)

        payload = engine_move(
            EngineMoveRequest(
                fen=current.fen(),
                start_fen=start_fen,
                moves=moves,
                movetime_ms=50,
            )
        )

        self.assertTrue(payload["game_over"])
        self.assertEqual(payload["reason"], "threefold_repetition")

    def test_fifty_move_rule_is_claimed(self) -> None:
        board = chess.Board("8/8/8/8/8/8/R7/K6k w - - 100 51")
        outcome = outcome_payload(board)

        self.assertTrue(outcome["game_over"])
        self.assertEqual(outcome["reason"], "fifty_moves")

    def test_seventyfive_move_rule_is_automatic(self) -> None:
        board = chess.Board("8/8/8/8/8/8/R7/K6k w - - 150 76")
        outcome = outcome_payload(board)

        self.assertTrue(outcome["game_over"])
        self.assertEqual(outcome["reason"], "seventyfive_moves")

    def test_stalemate(self) -> None:
        board = chess.Board("7k/5K2/6Q1/8/8/8/8/8 b - - 0 1")
        outcome = outcome_payload(board)

        self.assertTrue(outcome["game_over"])
        self.assertEqual(outcome["reason"], "stalemate")

    def test_insufficient_material(self) -> None:
        board = chess.Board("8/8/8/8/8/8/7k/K7 w - - 0 1")
        outcome = outcome_payload(board)

        self.assertTrue(outcome["game_over"])
        self.assertEqual(outcome["reason"], "insufficient_material")

    def test_mismatched_history_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            board_from_history(chess.Board().fen(), chess.Board().fen(), ["e2e4"])

        self.assertEqual(raised.exception.status_code, 400)

    def test_mating_material_is_reported_for_clock_rules(self) -> None:
        bare_kings = chess.Board("8/8/8/8/8/8/7k/K7 w - - 0 1")
        rook_advantage = chess.Board("8/8/8/8/8/8/R6k/K7 w - - 0 1")

        bare_payload = state_payload(bare_kings, [], start_fen=bare_kings.fen())
        rook_payload = state_payload(rook_advantage, [], start_fen=rook_advantage.fen())

        self.assertEqual(bare_payload["can_mate"], {"white": False, "black": False})
        self.assertEqual(rook_payload["can_mate"], {"white": True, "black": False})

    def test_state_includes_opposite_side_premove_options(self) -> None:
        board = chess.Board()
        payload = state_payload(board, [], start_fen=board.fen())

        self.assertIn("e7e5", payload["premove_moves"])
        self.assertNotIn("e2e4", payload["premove_moves"])

    def test_premove_sequence_projects_consecutive_same_side_moves(self) -> None:
        projected, available = project_premove_sequence(
            chess.Board(),
            "black",
            ["e7e5", "e5e4"],
        )

        self.assertIsNone(projected.piece_at(chess.E7))
        self.assertEqual(projected.piece_at(chess.E4), chess.Piece(chess.PAWN, chess.BLACK))
        self.assertIn("e4e3", available)

    def test_invalid_later_premove_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            project_premove_sequence(chess.Board(), "black", ["e7e5", "e7e6"])

        self.assertEqual(raised.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
