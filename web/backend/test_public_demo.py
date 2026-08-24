from __future__ import annotations

import asyncio
import queue
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import chess
from fastapi import HTTPException
from pydantic import ValidationError

from web.backend import main
from web.backend.sgurr_uci import EngineCrashedError, SgurrUciEngine


class PublicDemoTest(unittest.TestCase):
    def test_historical_ratings_use_v82_bridge(self) -> None:
        ratings = {str(entry["id"]): entry["rating"] for entry in main.ENGINE_SPECS}

        self.assertEqual(
            ratings,
            {
                "v8.2": 3012,
                "v8.1": 2981,
                "v8.0": 2960,
                "v7.0": 2857,
                "v6.0": 2761,
                "v5.0": 2677,
                "v4.0": 2559,
                "v3.1": 2497,
                "v3.0": 2545,
                "v2.0": 2423,
                "v1.0": 2341,
                "classical": 2332,
            },
        )

    def test_clock_search_is_capped(self) -> None:
        request = main.EngineMoveRequest(
            fen=chess.STARTING_FEN,
            wtime_ms=5_400_000,
            btime_ms=5_400_000,
            winc_ms=30_000,
            binc_ms=30_000,
        )
        with patch.object(main, "PUBLIC_DEMO", True):
            self.assertEqual(main.go_args_for(request, chess.Board()), "movetime 2000")

    def test_network_depth_is_enforced_server_side(self) -> None:
        request = main.SearchNetworkRequest(fen=chess.STARTING_FEN, depth=14)
        with patch.object(main, "PUBLIC_DEMO", True), patch.object(
            main, "DEMO_NETWORK_MAX_DEPTH", 12
        ):
            with self.assertRaises(HTTPException) as raised:
                main.search_network(request)
        self.assertEqual(raised.exception.status_code, 400)

    def test_historical_engines_are_local_only(self) -> None:
        entry = main.ENGINES["v8.1"]
        with patch.object(main, "PUBLIC_DEMO", True):
            available, reason, badge = main.engine_availability("v8.1", entry)
        self.assertFalse(available)
        self.assertIn("locally", reason)
        self.assertEqual(badge, "LOCAL ONLY")

    def test_compute_slot_rejects_overlap(self) -> None:
        semaphore = threading.BoundedSemaphore(1)
        with patch.object(main, "PUBLIC_DEMO", True), patch.object(
            main, "DEMO_COMPUTE_SLOTS", semaphore
        ):
            acquired = main.acquire_demo_compute_slot()
            with self.assertRaises(HTTPException) as raised:
                main.acquire_demo_compute_slot()
            main.release_demo_compute_slot(acquired)
            self.assertTrue(main.acquire_demo_compute_slot())
            main.release_demo_compute_slot(True)
        self.assertEqual(raised.exception.status_code, 429)

    def test_rate_limiter_expires_old_requests(self) -> None:
        limiter = main.SlidingWindowLimiter(window_seconds=10)
        self.assertEqual(limiter.check("client", 2, now=0), 0)
        self.assertEqual(limiter.check("client", 2, now=1), 0)
        self.assertEqual(limiter.check("client", 2, now=2), 8)
        self.assertEqual(limiter.check("client", 2, now=10), 0)

    def test_request_sizes_are_bounded(self) -> None:
        with self.assertRaises(ValidationError):
            main.EngineMoveRequest(fen="x" * 129)
        with self.assertRaises(ValidationError):
            main.EngineMoveRequest(
                fen=chess.STARTING_FEN,
                moves=["e2e4"] * 513,
            )
        with self.assertRaises(ValidationError):
            main.EngineMoveRequest(
                fen=chess.STARTING_FEN,
                wtime_ms=86_400_001,
            )

    def test_reader_uses_its_launch_queue(self) -> None:
        engine = SgurrUciEngine(Path("unused"))
        launch_queue: queue.Queue[str | None] = queue.Queue()
        replacement_queue: queue.Queue[str | None] = queue.Queue()
        engine._lines = replacement_queue

        class Process:
            stdout = ["uciok\n"]

        engine._reader_loop(Process(), launch_queue)

        self.assertEqual(launch_queue.get_nowait(), "uciok")
        self.assertIsNone(launch_queue.get_nowait())
        self.assertTrue(replacement_queue.empty())

    def test_cancel_before_launch_prevents_search(self) -> None:
        engine = SgurrUciEngine(Path("unused"))
        engine.cancel()

        with self.assertRaises(EngineCrashedError):
            engine.search(chess.STARTING_FEN, "depth 1", 1.0)

    def test_chunked_request_body_is_bounded(self) -> None:
        called = False
        sent = []
        messages = iter(
            [
                {"type": "http.request", "body": b"123", "more_body": True},
                {"type": "http.request", "body": b"456", "more_body": False},
            ]
        )

        async def downstream(scope, receive, send) -> None:
            nonlocal called
            called = True

        async def receive():
            return next(messages)

        async def send(message) -> None:
            sent.append(message)

        middleware = main.RequestBodyLimitMiddleware(
            downstream,
            max_bytes=5,
            enabled=True,
        )
        scope = {"type": "http", "method": "POST", "headers": []}
        asyncio.run(middleware(scope, receive, send))

        self.assertFalse(called)
        self.assertEqual(sent[0]["status"], 413)


if __name__ == "__main__":
    unittest.main()
