import unittest

import chess
from fastapi import HTTPException

from web.backend.main import GameRequest, resume_game


class ResumeGameTest(unittest.TestCase):
    def test_resume_preserves_move_history_and_repetition(self):
        moves = ["g1f3", "g8f6", "f3g1", "f6g8"] * 2
        board = chess.Board()
        for move in moves:
            board.push_uci(move)
        state = resume_game(GameRequest(fen=board.fen(), start_fen=chess.STARTING_FEN, moves=moves))
        self.assertEqual(state["moves"], moves)
        self.assertEqual(state["reason"], "threefold_repetition")
        self.assertTrue(state["game_over"])

    def test_resume_custom_position(self):
        board = chess.Board()
        board.push_uci("e2e4")
        start = board.fen()
        board.push_uci("c7c5")
        state = resume_game(GameRequest(fen=board.fen(), start_fen=start, moves=["c7c5"]))
        self.assertEqual(state["start_fen"], start)
        self.assertEqual(state["move_rows"][0]["black"], "c5")
        self.assertIn("g1f3", state["legal_moves"])

    def test_resume_rejects_mismatched_position_and_illegal_history(self):
        for moves in [["e2e4"], ["e2e5"]]:
            with self.subTest(moves=moves), self.assertRaises(HTTPException):
                resume_game(GameRequest(fen=chess.STARTING_FEN, start_fen=chess.STARTING_FEN, moves=moves))


if __name__ == "__main__":
    unittest.main()
