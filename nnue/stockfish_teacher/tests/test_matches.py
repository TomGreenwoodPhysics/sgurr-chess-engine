import io
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from matches import audit_log, audit_pgn, paired_estimate
import chess
import chess.pgn


class MatchAuditTest(unittest.TestCase):
    def pgn(self, termination="normal", second_white="Gen8"):
        games = []
        for name in ("TeacherPilot", second_white):
            game = chess.pgn.Game()
            game.setup(chess.Board("8/8/8/8/8/8/4k3/K7 w - - 0 1"))
            game.headers.update(White=name, Black="Gen8" if name == "TeacherPilot" else "TeacherPilot", Result="1/2-1/2", Termination=termination)
            games.append(str(game))
        return "\n\n".join(games) + "\n"

    def test_pairs_and_termination_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "games.pgn"
            p.write_text(self.pgn())
            self.assertEqual(audit_pgn(p, 2)["wdl"], {"draw": 2})
            for text in (self.pgn("time forfeit"), self.pgn(second_white="TeacherPilot")):
                p.write_text(text)
                with self.assertRaises(RuntimeError):
                    audit_pgn(p, 2)

    def test_only_known_pv_warnings_exempted(self):
        audit_log("Warning; PV extends beyond threefold repetition\n")
        audit_log("Warning; PV extends beyond fifty-move rule\n")
        for line in ("Warning; engine protocol error", "Engine crashed", "Illegal move a7a8Q", "Lost by time forfeit"):
            with self.assertRaises(RuntimeError):
                audit_log(line)

    def test_named_opponent_and_pair_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'games.pgn'
            p.write_text(self.pgn().replace('TeacherPilot', 'Sgurr-X-Candidate').replace('Gen8', 'Sgurr-X-56M'))
            result = audit_pgn(p, 2, 'Sgurr-X-Candidate', 'Sgurr-X-56M')
            self.assertEqual(result['pair_scores'], [.5])
        estimate = paired_estimate([0, .25, .5, .75, 1])
        self.assertEqual(estimate['elo'], 0)
        self.assertAlmostEqual(estimate['elo_95'][0], -estimate['elo_95'][1])
        self.assertEqual(paired_estimate([.5] * 400)['elo_95'], [0, 0])


if __name__ == "__main__":
    unittest.main()
