from __future__ import annotations

import unittest

import chess
from pydantic import ValidationError

from web.backend.main import SearchNetworkRequest, SearchTraceRequest, eval_payload
from web.backend.sgurr_uci import parse_uci_info


class SearchTraceTest(unittest.TestCase):
    def test_parses_completed_iteration_metrics(self) -> None:
        info = parse_uci_info(
            "info depth 12 score cp -40 nodes 1271020 nps 3652356 "
            "hashfull 73 time 348 pv a7a6"
        )

        self.assertIsNotNone(info)
        self.assertEqual(info.depth, 12)
        self.assertEqual(info.nodes, 1_271_020)
        self.assertEqual(info.nps, 3_652_356)
        self.assertEqual(info.hashfull, 73)
        self.assertEqual(info.pv, ["a7a6"])

    def test_trace_payload_is_white_relative(self) -> None:
        info = parse_uci_info(
            "info depth 8 score cp -25 nodes 1000 nps 500000 "
            "hashfull 5 time 2 pv a7a6"
        )

        payload = eval_payload(info, chess.BLACK)

        self.assertEqual(payload["value"], 25)
        self.assertEqual(payload["display"], "+0.2")
        self.assertEqual(payload["nps"], 500_000)
        self.assertEqual(payload["hashfull"], 5)

    def test_trace_duration_is_bounded(self) -> None:
        with self.assertRaises(ValidationError):
            SearchTraceRequest(fen=chess.STARTING_FEN, movetime_ms=5_001)

    def test_network_trace_depth_is_bounded_for_interactive_use(self) -> None:
        self.assertEqual(SearchNetworkRequest(fen=chess.STARTING_FEN).depth, 6)
        self.assertEqual(SearchNetworkRequest(fen=chess.STARTING_FEN, depth=20).depth, 20)
        with self.assertRaises(ValidationError):
            SearchNetworkRequest(fen=chess.STARTING_FEN, depth=21)
        with self.assertRaises(ValidationError):
            SearchNetworkRequest(fen=chess.STARTING_FEN, depth=3)


if __name__ == "__main__":
    unittest.main()
