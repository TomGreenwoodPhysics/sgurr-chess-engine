from __future__ import annotations

from dataclasses import dataclass

import chess

from v11.bitfish_board_v11 import Board as BitfishBoard
from v11.bitfish_engine_v11 import Engine as BitfishEngine


ENGINE_DEPTH = 10
ENGINE_TIME_LIMIT = 7.5


@dataclass
class WeaknessCase:
    name: str
    category: str
    fen: str
    avoid_moves: set[str]
    good_moves: set[str]
    note: str


TESTS = [
    WeaknessCase(
        name="nora_rook_pin_threat",
        category="threat_recognition",
        fen="7r/2kp4/b1pb3r/p4p2/P2P2p1/8/1P1R1PPP/2RB2K1 w - - 0 33",
        avoid_moves={"g2g3"},
        good_moves={"g1h2"},
        note="Chess.com marked 33.g3 as a blunder; best was Kh2 to stop ...Rh2.",
    ),
    WeaknessCase(
        name="king_hunt_black_survival",
        category="king_safety",
        fen="r2qk2r/pppb1ppp/3b4/4p3/1n2n3/1QP1BN2/PP2BPPP/RN2K2R b KQkq - 4 12",
        avoid_moves=set(),
        good_moves=set(),
        note="High legal-move-count middlegame from benchmark diagnostics.",
    ),
]


def run_case(case: WeaknessCase) -> tuple[bool, str]:
    chess_board = chess.Board(case.fen)
    board = BitfishBoard(case.fen)
    engine = BitfishEngine()

    result = engine.search_best_move(
        board,
        max_depth=ENGINE_DEPTH,
        time_limit=ENGINE_TIME_LIMIT,
    )

    move = "None" if result.best_move is None else str(result.best_move)

    if move in case.avoid_moves:
        return False, (
            f"FAIL {case.name}: chose avoided move {move}; "
            f"depth={result.depth}, score={result.score}, note={case.note}"
        )

    if case.good_moves and move not in case.good_moves:
        return False, (
            f"WARN {case.name}: chose {move}, expected one of {sorted(case.good_moves)}; "
            f"depth={result.depth}, score={result.score}, note={case.note}"
        )

    if result.best_move is not None:
        py_move = chess.Move.from_uci(move)
        if py_move not in chess_board.legal_moves:
            return False, f"FAIL {case.name}: illegal move {move}"

    return True, (
        f"PASS {case.name}: chose {move}; "
        f"depth={result.depth}, score={result.score}, note={case.note}"
    )


def main() -> None:
    passes = 0
    warnings = 0
    fails = 0

    print("Bitfish v12 weakness suite")
    print("--------------------------")

    for case in TESTS:
        ok, message = run_case(case)
        print(message)

        if message.startswith("PASS"):
            passes += 1
        elif message.startswith("WARN"):
            warnings += 1
        else:
            fails += 1

    print()
    print("Summary")
    print("-------")
    print(f"passes:   {passes}")
    print(f"warnings: {warnings}")
    print(f"fails:    {fails}")


if __name__ == "__main__":
    main()
