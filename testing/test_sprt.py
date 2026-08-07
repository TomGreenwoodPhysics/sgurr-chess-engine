#!/usr/bin/env python3
"""Unit tests for the SPRT harness's statistics and decision logic.

Why this file exists. `sprt.py` decided whether every search change in this
project shipped or was discarded. Its verdicts are recorded in the changelog
and the ledger as though they were measurements, but the arithmetic producing
them had never itself been checked against anything. A sign error in the LLR,
an off-by-one in the stopping rule, or a mis-derived confidence interval would
not crash: it would quietly accept or reject changes and leave a plausible
number behind, which is the same failure mode the engine pre-flight exists to
prevent.

The tests below pin the parts that can be verified independently:

* closed-form values the statistics must reproduce exactly (the Elo formula
  has an analytic answer, so a regression is unambiguous);
* invariants that must hold for any correct implementation (antisymmetry,
  monotonicity, the 1/sqrt(n) shrink of the interval);
* the decision rule, including the minimum-games guard, driven through
  `Tally` rather than by re-deriving the arithmetic here.

Nothing here plays a game or starts an engine, so it runs in milliseconds.

    python3 -m unittest discover -s testing -p "test_*.py"
"""
import io
import math
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sprt  # noqa: E402


def tally(elo0=0.0, elo1=5.0, alpha=0.05, beta=0.05, min_games=16):
    """A Tally with the project's standard non-regression bounds."""
    return sprt.Tally(SimpleNamespace(
        elo0=elo0, elo1=elo1, alpha=alpha, beta=beta, min_games=min_games))


def feed(t, pairs):
    """Record colour-balanced pairs, swallowing the per-pair progress line."""
    with redirect_stdout(io.StringIO()):
        for r1, r2 in pairs:
            decided = t.record_pair(r1, r2)
    return decided


class TestEloWithCi(unittest.TestCase):
    """`elo_with_ci` has a closed form, so it can be checked exactly."""

    def test_no_games_is_not_a_rating(self):
        self.assertEqual(sprt.elo_with_ci(0, 0, 0), (0.0, 0.0))

    def test_even_score_is_zero_elo(self):
        elo, _ = sprt.elo_with_ci(50, 0, 50)
        self.assertAlmostEqual(elo, 0.0, places=9)

    def test_all_draws_is_zero_elo_with_no_uncertainty(self):
        # Every game landing on exactly the mean leaves no variance to
        # propagate, so the interval must collapse rather than divide by zero.
        elo, ci = sprt.elo_with_ci(0, 100, 0)
        self.assertAlmostEqual(elo, 0.0, places=9)
        self.assertAlmostEqual(ci, 0.0, places=9)

    def test_matches_the_analytic_elo_formula(self):
        # elo = -400 * log10((1 - x) / x). At a 75% score that is
        # 400 * log10(3) = 190.8485..., independently derivable.
        for w, d, l, expected in [
            (75, 0, 25, 400 * math.log10(3)),
            (60, 0, 40, -400 * math.log10(40 / 60)),
            (0, 50, 50, -400 * math.log10(0.75 / 0.25)),
        ]:
            with self.subTest(w=w, d=d, l=l):
                elo, _ = sprt.elo_with_ci(w, d, l)
                self.assertAlmostEqual(elo, expected, places=9)

    def test_draws_count_as_half_a_point(self):
        # 60/0/40 and 50/20/30 are both a 60% score, so they must rate the
        # same. If draws were ever dropped or double counted, these diverge.
        self.assertAlmostEqual(sprt.elo_with_ci(60, 0, 40)[0],
                               sprt.elo_with_ci(50, 20, 30)[0], places=9)

    def test_is_antisymmetric(self):
        # Swapping wins and losses is the same match seen from the other side.
        for w, d, l in [(70, 10, 20), (55, 30, 15), (99, 0, 1)]:
            with self.subTest(w=w, d=d, l=l):
                self.assertAlmostEqual(sprt.elo_with_ci(w, d, l)[0],
                                       -sprt.elo_with_ci(l, d, w)[0], places=9)

    def test_clamps_instead_of_diverging_at_a_perfect_score(self):
        # log10(0) is -inf. A whitewash must report a large finite number, or
        # a single lopsided early batch takes the whole run's output with it.
        self.assertEqual(sprt.elo_with_ci(10, 0, 0), (800.0, 0.0))
        self.assertEqual(sprt.elo_with_ci(0, 0, 10), (-800.0, 0.0))

    def test_interval_shrinks_as_one_over_root_n(self):
        # Quadrupling the sample at a fixed score ratio should roughly halve
        # the interval. This is the property every "N games buys +/-X Elo"
        # claim in the ledger rests on.
        _, ci_1x = sprt.elo_with_ci(300, 400, 300)
        _, ci_4x = sprt.elo_with_ci(1200, 1600, 1200)
        self.assertAlmostEqual(ci_1x / ci_4x, 2.0, delta=0.05)

    def test_more_wins_never_lowers_the_rating(self):
        ratings = [sprt.elo_with_ci(w, 0, 100 - w)[0] for w in range(10, 91, 10)]
        self.assertEqual(ratings, sorted(ratings))


class TestSprtLlr(unittest.TestCase):
    """The log-likelihood ratio drives every accept/reject decision."""

    def test_no_games_is_no_evidence(self):
        self.assertEqual(sprt.sprt_llr(0, 0, 0, 0, 5), 0.0)

    def test_an_even_score_argues_for_h0(self):
        # With elo0=0 and elo1=5, a dead-even result is evidence for "not an
        # improvement". A positive LLR here would mean the test drifts toward
        # accepting changes that did nothing, which is the expensive direction.
        self.assertLess(sprt.sprt_llr(500, 0, 500, 0, 5), 0.0)

    def test_a_dominant_score_argues_for_h1(self):
        self.assertGreater(sprt.sprt_llr(700, 0, 300, 0, 5), 0.0)

    def test_evidence_accumulates_with_sample_size(self):
        # Same score ratio, ten times the games: the LLR must grow, or the
        # test could never reach a bound and would run forever.
        small = sprt.sprt_llr(60, 0, 40, 0, 5)
        large = sprt.sprt_llr(600, 0, 400, 0, 5)
        self.assertGreater(large, small)
        self.assertAlmostEqual(large / small, 10.0, delta=0.5)

    def test_is_monotone_in_wins(self):
        llrs = [sprt.sprt_llr(w, 0, 1000 - w, 0, 5) for w in range(400, 601, 25)]
        self.assertEqual(llrs, sorted(llrs))

    def test_a_wider_alternative_resolves_a_large_gain_faster(self):
        # testing/README.md: "for a large expected jump (e.g. NNUE), widening
        # to elo0=0 elo1=10 resolves faster". A 60% score is ~+70 Elo, well
        # past every bound below, so the LLR should climb as elo1 moves out.
        llrs = [sprt.sprt_llr(600, 0, 400, 0, e1) for e1 in (5, 10, 20, 40)]
        self.assertEqual(llrs, sorted(llrs))
        self.assertGreater(llrs[1], llrs[0])


class TestDecisionRule(unittest.TestCase):
    """`Tally` turns the LLR into a verdict. That is where a run stops."""

    def test_bounds_come_from_alpha_and_beta(self):
        t = tally(alpha=0.05, beta=0.05)
        self.assertAlmostEqual(t.upper, math.log(0.95 / 0.05), places=12)
        self.assertAlmostEqual(t.lower, math.log(0.05 / 0.95), places=12)
        self.assertAlmostEqual(t.upper, 2.9444389791664403, places=12)

    def test_counts_wins_draws_and_losses_from_pairs(self):
        t = tally(min_games=10_000)
        feed(t, [(1.0, 0.0), (0.5, 0.5), (1.0, 1.0)])
        self.assertEqual((t.w, t.d, t.l), (3, 2, 1))
        self.assertEqual(t.pairs_done, 3)

    def test_accepts_h1_on_a_convincing_win(self):
        t = tally(min_games=16)
        decided = feed(t, [(1.0, 1.0)] * 20)
        self.assertTrue(decided)
        self.assertIn("H1", t.decided)

    def test_accepts_h0_on_a_convincing_loss(self):
        t = tally(min_games=16)
        decided = feed(t, [(0.0, 0.0)] * 20)
        self.assertTrue(decided)
        self.assertIn("H0", t.decided)

    def test_will_not_decide_before_min_games(self):
        # The guard that exists because an early lopsided batch can cross a
        # bound on a handful of games. 8 pairs is 16 games, under the 40 here,
        # and every one is a win, so only the guard can be holding it back.
        t = tally(min_games=40)
        decided = feed(t, [(1.0, 1.0)] * 8)
        self.assertFalse(decided)
        self.assertIsNone(t.decided)
        self.assertGreater(sprt.sprt_llr(t.w, t.d, t.l, 0.0, 5.0), t.upper)

    def test_decides_once_min_games_is_reached(self):
        t = tally(min_games=40)
        feed(t, [(1.0, 1.0)] * 8)
        self.assertIsNone(t.decided)
        feed(t, [(1.0, 1.0)] * 12)
        self.assertIsNotNone(t.decided)

    def test_an_even_run_stays_undecided(self):
        # 200 games of exact parity sits between the bounds. If this decided,
        # the harness would be manufacturing verdicts out of noise.
        t = tally(min_games=16)
        self.assertFalse(feed(t, [(1.0, 0.0)] * 100))
        self.assertIsNone(t.decided)

    def test_a_verdict_is_never_overwritten(self):
        t = tally(min_games=16)
        feed(t, [(1.0, 1.0)] * 20)
        first = t.decided
        feed(t, [(0.0, 0.0)] * 200)
        self.assertEqual(t.decided, first)

    def test_abort_stops_the_run_without_a_verdict(self):
        # A dead engine must not leave a scoreline behind. `decided` is what
        # the worker loops poll, so it has to become truthy to unblock them,
        # but it must not read as an accepted hypothesis.
        t = tally()
        t.abort("engine died")
        self.assertEqual(t.aborted, "engine died")
        self.assertEqual(t.decided, "ABORTED")
        self.assertNotIn("ACCEPTED", t.decided)

    def test_abort_keeps_the_first_reason(self):
        t = tally()
        t.abort("first")
        t.abort("second")
        self.assertEqual(t.aborted, "first")


class TestTimeControlParsing(unittest.TestCase):
    """A misparsed time control silently changes what was measured."""

    def test_base_plus_increment_in_milliseconds(self):
        self.assertEqual(sprt.parse_tc("8+0.08"), (8000, 80))
        self.assertEqual(sprt.parse_tc("10+0.1"), (10000, 100))

    def test_bare_base_means_no_increment(self):
        self.assertEqual(sprt.parse_tc("0.5"), (500, 0))
        self.assertEqual(sprt.parse_tc("60"), (60000, 0))

    def test_the_projects_two_standard_controls(self):
        # 8+0.08 is the SPRT control, 10+0.1 the pool control. Both appear in
        # the ledger next to every measured number.
        self.assertEqual(sprt.parse_tc("8+0.08"), (8000, 80))
        self.assertEqual(sprt.parse_tc("10+0.1"), (10000, 100))


class TestOpeningBook(unittest.TestCase):
    """Two engines with no book replay one game, so the book is load-bearing."""

    def book(self, text):
        fh = tempfile.NamedTemporaryFile("w", suffix=".epd", delete=False)
        fh.write(text)
        fh.close()
        self.addCleanup(os.unlink, fh.name)
        return sprt.load_book(fh.name)

    def test_skips_blanks_and_comments(self):
        entries = self.book("# a comment\n\ne2e4 e7e5\n\n# another\nd2d4\n")
        self.assertEqual(entries, [("moves", ["e2e4", "e7e5"]),
                                   ("moves", ["d2d4"])])

    def test_reads_epd_positions(self):
        entries = self.book(
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -\n")
        self.assertEqual(entries[0][0], "fen")

    def test_a_missing_book_falls_back_to_the_start_position(self):
        # Rather than producing an empty job queue and a match of zero games.
        self.assertEqual(sprt.load_book("does_not_exist.epd"), [("moves", [])])
        self.assertEqual(sprt.load_book(None), [("moves", [])])

    def test_an_empty_book_falls_back_too(self):
        self.assertEqual(self.book("\n# only comments\n"), [("moves", [])])

    def test_epd_is_padded_to_a_full_fen(self):
        # EPD carries four fields; the engine is sent a six-field FEN, so the
        # halfmove and fullmove counters have to be supplied.
        fen, moves = sprt.opening_for(
            ("fen", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"))
        self.assertEqual(fen.split()[-2:], ["0", "1"])
        self.assertEqual(len(fen.split()), 6)
        self.assertEqual(moves, [])

    def test_a_full_fen_is_left_alone(self):
        original = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 3 7"
        fen, _ = sprt.opening_for(("fen", original))
        self.assertEqual(fen, original)

    def test_move_lines_start_from_the_initial_position(self):
        fen, moves = sprt.opening_for(("moves", ["e2e4", "e7e5"]))
        self.assertEqual(fen, sprt.cl.START_FEN)
        self.assertEqual(moves, ["e2e4", "e7e5"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
