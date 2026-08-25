from __future__ import annotations

import json
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen


BASE_URL = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8000"
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def get(path: str):
    with urlopen(f"{BASE_URL}{path}", timeout=20) as response:
        return json.load(response)


def get_bytes(path: str) -> bytes:
    with urlopen(f"{BASE_URL}{path}", timeout=20) as response:
        return response.read()


def post(path: str, payload: dict):
    request = Request(
        f"{BASE_URL}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return urlopen(request, timeout=30)


assert get("/ready")["ok"] is True
health = get("/health")
assert health["ok"] is True
assert health["nnue_loaded"] is True
assert b"Sgurr" in get_bytes("/")
assert b"Position Lab" in get_bytes("/")
assert b"Search Microscope" in get_bytes("/search-lab/")
assert b"--accent" in get_bytes("/styles/base.css")
assert len(get_bytes("/assets/intro/sgurr-cave-chamber.webp")) > 100_000
assert len(get_bytes("/assets/intro/sgurr-social-card.jpg")) > 50_000
assert b"<svg" in get_bytes("/assets/pieces/chessnut/wK.svg")

engines = get("/api/engines")
available = [entry["id"] for entry in engines["engines"] if entry["available"]]
assert available == ["v8.2"]

with post(
    "/api/search-trace",
    {"fen": START_FEN, "engine": "v8.2", "movetime_ms": 1_500},
) as trace:
    assert json.loads(trace.readline())["type"] == "started"
    try:
        with post(
            "/api/engine-move",
            {"fen": START_FEN, "moves": [], "movetime_ms": 50},
        ):
            raise AssertionError("overlapping search was accepted")
    except HTTPError as exc:
        assert exc.code == 429
    trace_events = [json.loads(line) for line in trace if line.strip()]
    assert any(event["type"] == "complete" for event in trace_events)
    iterations = [event for event in trace_events if event["type"] == "iteration"]
    assert len(iterations[-1]["pv_san"]) >= 2
    assert len(iterations[-1]["pv_fens"]) == len(iterations[-1]["pv_san"]) + 1

with post(
    "/api/engine-move",
    {"fen": START_FEN, "moves": [], "movetime_ms": 100},
) as response:
    move = json.load(response)
    assert move["last_move"]["by"] == "engine"

with post("/api/search-network", {"fen": START_FEN, "depth": 4}) as response:
    network_events = [json.loads(line) for line in response if line.strip()]
    assert any(event["type"] == "trace" for event in network_events)
    completion = next(event for event in network_events if event["type"] == "complete")
    assert completion["target_depth"] == 4
    assert completion["depth"] == 4
    assert completion["limited"] is False

try:
    with post("/api/search-network", {"fen": START_FEN, "depth": 14}):
        raise AssertionError("depth above the public limit was accepted")
except HTTPError as exc:
    assert exc.code == 400

oversized = Request(
    f"{BASE_URL}/api/engine-move",
    data=b"x" * 65_537,
    headers={"Content-Type": "application/octet-stream"},
    method="POST",
)
try:
    with urlopen(oversized, timeout=20):
        raise AssertionError("oversized request was accepted")
except HTTPError as exc:
    assert exc.code == 413
