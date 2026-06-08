from __future__ import annotations

import contextlib
import csv
import importlib
import io
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import chess
import chess.engine
import chess.pgn


STOCKFISH_PATH = (
    r"C:\Users\Tom Greenwood\Desktop\Coding Projects\Chess Bot"
    r"\stockfish\stockfish-windows-x86-64-avx2.exe"
)

BITFISH_VERSION_NAME = "Bitfish v11"
BITFISH_IMPORT_OPTIONS = [
    ("v11.bitfish_board_v11", "v11.bitfish_engine_v11"),
]

RANK_TEST_DEPTH = 5
STOCKFISH_RANK_DEPTH = 12
STOCKFISH_MULTIPV = 8

CONVERSION_BITFISH_MAX_DEPTH = 20
CONVERSION_BITFISH_TIME = 1.0
CONVERSION_STOCKFISH_ELO = 1550
CONVERSION_STOCKFISH_TIME = 0.20
CONVERSION_MAX_PLIES = 160

OUTPUT_DIR = Path("weakness_tests")
RANK_CSV = OUTPUT_DIR / "weakness_rank_tests.csv"
CONVERSION_CSV = OUTPUT_DIR / "conversion_tests.csv"
CONVERSION_PGN = OUTPUT_DIR / "conversion_tests.pgn"


RANK_TESTS = [
    {
        "category": "opening",
        "name": "startpos",
        "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "notes": "early move choice; old weakness was b1c3",
    },
    {
        "category": "opening",
        "name": "open_game_after_e4_e5",
        "fen": "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
        "notes": "normal Nf3-style development check",
    },
    {
        "category": "tactical_pressure",
        "name": "tactical_pressure",
        "fen": "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQK2R w KQkq - 4 5",
        "notes": "known weakness: engine often chooses c1e3",
    },
    {
        "category": "development",
        "name": "italian_like",
        "fen": "r1bqk1nr/pppp1ppp/2n5/2b1p3/2B1P3/2N2N2/PPPP1PPP/R1BQK2R w KQkq - 4 4",
        "notes": "checks whether opening bonus damages normal development/castling",
    },
    {
        "category": "complex_middlegame",
        "name": "kiwipete",
        "fen": "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        "notes": "complex tactical/move-generation benchmark",
    },
    {
        "category": "queen_activity",
        "name": "queen_activity",
        "fen": "rnb1kbnr/pppp1ppp/8/4p3/4P2q/5N2/PPPP1PPP/RNBQKB1R w KQkq - 1 3",
        "notes": "response to early queen pressure",
    },
    {
        "category": "mate_delivery",
        "name": "rook_endgame_mate",
        "fen": "4r1k1/5ppp/8/8/8/8/5PPP/4R1K1 w - - 0 1",
        "notes": "immediate mate/capture conversion",
    },
    {
        "category": "king_pawn_endgame",
        "name": "king_pawn_endgame",
        "fen": "8/8/8/3k4/3P4/3K4/8/8 w - - 0 1",
        "notes": "basic king-pawn choice",
    },
    {
        "category": "promotion",
        "name": "promotion_race",
        "fen": "8/P6k/8/8/8/8/6pK/8 w - - 0 1",
        "notes": "promotion-race judgement",
    },
]


CONVERSION_TESTS = [
    {
        "category": "basic_mate_conversion",
        "name": "queen_vs_king",
        "fen": "6k1/8/8/8/8/8/8/5QK1 w - - 0 1",
        "bitfish_colour": chess.WHITE,
        "expected": "win",
        "notes": "queen and king versus bare king",
    },
    {
        "category": "basic_mate_conversion",
        "name": "rook_vs_king",
        "fen": "6k1/8/8/8/8/8/8/5RK1 w - - 0 1",
        "bitfish_colour": chess.WHITE,
        "expected": "win",
        "notes": "rook and king versus bare king",
    },
    {
        "category": "material_conversion",
        "name": "rook_up_with_pawns",
        "fen": "6k1/5ppp/8/8/8/8/5PPP/4R1K1 w - - 0 1",
        "bitfish_colour": chess.WHITE,
        "expected": "win",
        "notes": "simple rook-up endgame",
    },
    {
        "category": "promotion_conversion",
        "name": "queen_promotion_race",
        "fen": "8/P6k/8/8/8/8/6pK/8 w - - 0 1",
        "bitfish_colour": chess.WHITE,
        "expected": "win_or_draw",
        "notes": "known delicate promotion race; loss is bad, draw may indicate conversion weakness",
    },
    {
        "category": "king_pawn_conversion",
        "name": "connected_passers",
        "fen": "6k1/8/6K1/4PP2/8/8/8/8 w - - 0 1",
        "bitfish_colour": chess.WHITE,
        "expected": "win",
        "notes": "two connected passers with active king",
    },
    {
        "category": "queen_conversion",
        "name": "queen_up_with_pawns",
        "fen": "6k1/5ppp/8/8/8/8/5PPP/4Q1K1 w - - 0 1",
        "bitfish_colour": chess.WHITE,
        "expected": "win",
        "notes": "queen-up endgame; checks stalemate/perpetual/repetition risk",
    },
]

PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}


@dataclass
class BitfishModules:
    board_module: ModuleType
    engine_module: ModuleType
    board_module_name: str
    engine_module_name: str


@dataclass
class BitfishSearch:
    move: str
    score: int
    depth: int
    nodes: int
    tt_hits: int
    time_s: float


@dataclass
class StockfishLine:
    rank: int
    move: str
    score_type: str
    score: int
    score_cp_equiv: int
    pv: str


class StockfishUCI:
    def __init__(self, path: str, depth: int, multipv: int) -> None:
        self.depth = depth
        self.proc = subprocess.Popen(
            [path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._send("uci")
        self._wait_for("uciok")
        self._send(f"setoption name MultiPV value {multipv}")
        self._send("isready")
        self._wait_for("readyok")

    def close(self) -> None:
        try:
            self._send("quit")
        finally:
            if self.proc.poll() is None:
                self.proc.terminate()

    def _send(self, command: str) -> None:
        if self.proc.stdin is None:
            raise RuntimeError("stockfish stdin is unavailable")
        self.proc.stdin.write(command + "\n")
        self.proc.stdin.flush()

    def _readline(self) -> str:
        if self.proc.stdout is None:
            raise RuntimeError("stockfish stdout is unavailable")
        line = self.proc.stdout.readline()
        if line == "":
            raise RuntimeError("stockfish stopped responding")
        return line.strip()

    def _wait_for(self, token: str) -> list[str]:
        lines = []
        while True:
            line = self._readline()
            lines.append(line)
            if line == token:
                return lines

    def analyse_multipv(self, fen: str) -> list[StockfishLine]:
        self._send(f"position fen {fen}")
        self._send(f"go depth {self.depth}")
        lines_by_rank: dict[int, StockfishLine] = {}

        while True:
            line = self._readline()
            if line.startswith("info") and f" depth {self.depth} " in f" {line} ":
                parsed = parse_stockfish_info(line)
                if parsed is not None:
                    lines_by_rank[parsed.rank] = parsed
            if line.startswith("bestmove"):
                break

        return [lines_by_rank[rank] for rank in sorted(lines_by_rank)]


def parse_stockfish_info(line: str) -> StockfishLine | None:
    rank_match = re.search(r"\bmultipv\s+(\d+)", line)
    score_match = re.search(r"\bscore\s+(cp|mate)\s+(-?\d+)", line)
    pv_match = re.search(r"\bpv\s+(.+)", line)
    if rank_match is None or score_match is None or pv_match is None:
        return None

    rank = int(rank_match.group(1))
    score_type = score_match.group(1)
    score = int(score_match.group(2))
    pv = pv_match.group(1)
    move = pv.split()[0]

    if score_type == "cp":
        cp_equiv = score
    elif score > 0:
        cp_equiv = 100_000 - abs(score)
    else:
        cp_equiv = -100_000 + abs(score)

    return StockfishLine(rank, move, score_type, score, cp_equiv, pv)


def load_bitfish() -> BitfishModules:
    failures = []
    for board_name, engine_name in BITFISH_IMPORT_OPTIONS:
        try:
            board_module = importlib.import_module(board_name)
            engine_module = importlib.import_module(engine_name)
            return BitfishModules(board_module, engine_module, board_name, engine_name)
        except ImportError as exc:
            failures.append(f"{board_name}/{engine_name}: {exc}")
    raise ImportError("could not import Bitfish:\n" + "\n".join(failures))


def run_bitfish_search(
    modules: BitfishModules,
    fen: str,
    depth: int,
    time_limit: float | None = None,
) -> BitfishSearch:
    board = modules.board_module.Board(fen)
    engine = modules.engine_module.Engine()
    with contextlib.redirect_stdout(io.StringIO()):
        result = engine.search_best_move(board, max_depth=depth, time_limit=time_limit)
    move = "0000" if result.best_move is None else str(result.best_move)
    return BitfishSearch(move, result.score, result.depth, result.nodes, result.tt_hits, result.time_taken)


def rank_test(modules: BitfishModules) -> list[dict]:
    rows = []
    stockfish = StockfishUCI(STOCKFISH_PATH, STOCKFISH_RANK_DEPTH, STOCKFISH_MULTIPV)
    try:
        for index, test in enumerate(RANK_TESTS, start=1):
            print(f"[rank {index}/{len(RANK_TESTS)}] {test['name']}")
            bitfish = run_bitfish_search(modules, test["fen"], depth=RANK_TEST_DEPTH)
            lines = stockfish.analyse_multipv(test["fen"])
            best = lines[0]
            match = next((line for line in lines if line.move == bitfish.move), None)
            rows.append({
                "category": test["category"],
                "name": test["name"],
                "bitfish_move": bitfish.move,
                "stockfish_best_move": best.move,
                "stockfish_rank": None if match is None else match.rank,
                "stockfish_cp_loss": None if match is None else best.score_cp_equiv - match.score_cp_equiv,
                "bitfish_score": bitfish.score,
                "bitfish_depth": bitfish.depth,
                "bitfish_nodes": bitfish.nodes,
                "bitfish_tt_hits": bitfish.tt_hits,
                "bitfish_time_s": f"{bitfish.time_s:.6f}",
                "fen": test["fen"],
                "notes": test["notes"],
            })
    finally:
        stockfish.close()
    return rows


def material_balance(board: chess.Board, colour: chess.Color) -> int:
    white = 0
    black = 0
    for piece_type, value in PIECE_VALUES.items():
        white += len(board.pieces(piece_type, chess.WHITE)) * value
        black += len(board.pieces(piece_type, chess.BLACK)) * value
    balance = white - black
    return balance if colour == chess.WHITE else -balance


def result_from_bitfish_perspective(result: str, bitfish_colour: chess.Color) -> str:
    if result == "1/2-1/2":
        return "draw"
    if result == "1-0":
        return "win" if bitfish_colour == chess.WHITE else "loss"
    if result == "0-1":
        return "win" if bitfish_colour == chess.BLACK else "loss"
    return "unknown"


def classify_conversion(expected: str, outcome: str) -> str:
    if expected == "win":
        if outcome == "win":
            return "pass"
        if outcome == "draw":
            return "conversion_warning"
        if outcome == "loss":
            return "fail"
    if expected == "win_or_draw":
        if outcome in ("win", "draw"):
            return "pass"
        if outcome == "loss":
            return "fail"
    if outcome == "illegal_move":
        return "fail"
    return "unknown"


def choose_bitfish_chess_move(modules: BitfishModules, board: chess.Board) -> tuple[chess.Move | None, BitfishSearch]:
    search = run_bitfish_search(
        modules,
        board.fen(),
        depth=CONVERSION_BITFISH_MAX_DEPTH,
        time_limit=CONVERSION_BITFISH_TIME,
    )
    if search.move == "0000":
        return None, search
    return chess.Move.from_uci(search.move), search


def play_conversion_game(
    modules: BitfishModules,
    stockfish: chess.engine.SimpleEngine,
    test: dict,
    game_number: int,
) -> tuple[dict, chess.pgn.Game]:
    board = chess.Board(test["fen"])
    bitfish_colour = test["bitfish_colour"]
    initial_material = material_balance(board, bitfish_colour)
    bitfish_stats = []
    illegal_move = None

    while not board.is_game_over(claim_draw=True) and board.ply() < CONVERSION_MAX_PLIES:
        if board.turn == bitfish_colour:
            move, search = choose_bitfish_chess_move(modules, board)
            bitfish_stats.append(search)
            if move is None or move not in board.legal_moves:
                illegal_move = "none" if move is None else move.uci()
                break
            board.push(move)
        else:
            result = stockfish.play(
                board,
                chess.engine.Limit(time=CONVERSION_STOCKFISH_TIME),
            )

            if result.move is None:
                break

            if result.move not in board.legal_moves:
                illegal_move = result.move.uci()
                break

            board.push(result.move)

    raw_result = board.result(claim_draw=True)
    outcome = result_from_bitfish_perspective(raw_result, bitfish_colour)
    if illegal_move is not None:
        outcome = "illegal_move"

    if board.is_checkmate():
        ending_reason = "checkmate"
    elif board.is_stalemate():
        ending_reason = "stalemate"
    elif board.is_insufficient_material():
        ending_reason = "insufficient_material"
    elif board.can_claim_threefold_repetition():
        ending_reason = "threefold_claim_available"
    elif board.can_claim_fifty_moves():
        ending_reason = "fifty_move_claim_available"
    elif board.ply() >= CONVERSION_MAX_PLIES:
        ending_reason = "max_plies"
    elif illegal_move is not None:
        ending_reason = f"illegal_move:{illegal_move}"
    else:
        ending_reason = "other"

    final_material = material_balance(board, bitfish_colour)
    status = classify_conversion(test["expected"], outcome)
    avg_depth = sum(s.depth for s in bitfish_stats) / len(bitfish_stats) if bitfish_stats else 0
    avg_nodes = sum(s.nodes for s in bitfish_stats) / len(bitfish_stats) if bitfish_stats else 0
    avg_time = sum(s.time_s for s in bitfish_stats) / len(bitfish_stats) if bitfish_stats else 0

    game = chess.pgn.Game.from_board(board)
    game.headers["Event"] = "Bitfish Weakness Conversion Test"
    game.headers["Round"] = str(game_number)
    game.headers["White"] = BITFISH_VERSION_NAME if bitfish_colour == chess.WHITE else f"Stockfish {CONVERSION_STOCKFISH_ELO}"
    game.headers["Black"] = BITFISH_VERSION_NAME if bitfish_colour == chess.BLACK else f"Stockfish {CONVERSION_STOCKFISH_ELO}"
    game.headers["Result"] = raw_result
    game.headers["FEN"] = test["fen"]
    game.headers["SetUp"] = "1"
    game.headers["TestName"] = test["name"]

    row = {
        "category": test["category"],
        "name": test["name"],
        "expected": test["expected"],
        "outcome": outcome,
        "status": status,
        "raw_result": raw_result,
        "ending_reason": ending_reason,
        "plies": board.ply(),
        "initial_material_cp": initial_material,
        "final_material_cp": final_material,
        "avg_depth": f"{avg_depth:.2f}",
        "avg_nodes": f"{avg_nodes:.0f}",
        "avg_time_s": f"{avg_time:.4f}",
        "fen": test["fen"],
        "notes": test["notes"],
    }
    return row, game


def conversion_tests(modules: BitfishModules) -> list[dict]:
    rows = []
    with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as stockfish:
        stockfish.configure({"UCI_LimitStrength": True, "UCI_Elo": CONVERSION_STOCKFISH_ELO})
        with CONVERSION_PGN.open("w", encoding="utf-8") as pgn_file:
            for index, test in enumerate(CONVERSION_TESTS, start=1):
                print(f"[conversion {index}/{len(CONVERSION_TESTS)}] {test['name']}")
                row, game = play_conversion_game(modules, stockfish, test, index)
                rows.append(row)
                print(game, file=pgn_file, end="\n\n")
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def print_rank_summary(rows: list[dict]) -> None:
    ranked = [row for row in rows if row["stockfish_rank"] is not None]
    top_1 = sum(row["stockfish_rank"] == 1 for row in rows)
    top_3 = sum(row["stockfish_rank"] is not None and row["stockfish_rank"] <= 3 for row in rows)
    rank_values = [row["stockfish_rank"] for row in ranked if row["stockfish_rank"] is not None]
    loss_values = [row["stockfish_cp_loss"] for row in rows if row["stockfish_cp_loss"] is not None]
    avg_rank = sum(rank_values) / len(rank_values) if rank_values else 0
    avg_loss = sum(loss_values) / len(loss_values) if loss_values else 0

    print("\nPosition-rank tests")
    print("-------------------")
    print(f"top-1 matches: {top_1}/{len(rows)}")
    print(f"top-3 moves:   {top_3}/{len(rows)}")
    print(f"inside top {STOCKFISH_MULTIPV}: {len(ranked)}/{len(rows)}")
    print(f"average rank:  {avg_rank:.2f}")
    print(f"average loss:  {avg_loss:.1f} cp\n")

    for row in rows:
        rank_text = f"#{row['stockfish_rank']}" if row["stockfish_rank"] is not None else f">{STOCKFISH_MULTIPV}"
        loss_text = f"{row['stockfish_cp_loss']}cp" if row["stockfish_cp_loss"] is not None else "unknown"
        print(
            f"{row['category']:22s} {row['name']:24s} "
            f"{row['bitfish_move']:8s} rank {rank_text:>3s} "
            f"loss {loss_text:>8s} sf {row['stockfish_best_move']}"
        )


def print_conversion_summary(rows: list[dict]) -> None:
    passes = sum(row["status"] == "pass" for row in rows)
    warnings = sum(row["status"] == "conversion_warning" for row in rows)
    fails = sum(row["status"] == "fail" for row in rows)

    print("\nConversion tests")
    print("----------------")
    print(f"passes:   {passes}/{len(rows)}")
    print(f"warnings: {warnings}/{len(rows)}")
    print(f"fails:    {fails}/{len(rows)}\n")

    for row in rows:
        print(
            f"{row['status']:20s} {row['name']:24s} "
            f"outcome {row['outcome']:12s} plies {row['plies']:3d} "
            f"reason {row['ending_reason']}"
        )


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    print("Bitfish weakness test suite")
    print("---------------------------")
    print(f"engine label: {BITFISH_VERSION_NAME}")
    print(f"stockfish: {STOCKFISH_PATH}\n")

    modules = load_bitfish()
    print("loaded Bitfish:")
    print(f"  board:  {modules.board_module_name}")
    print(f"  engine: {modules.engine_module_name}\n")

    start = time.time()
    rank_rows = rank_test(modules)
    write_csv(RANK_CSV, rank_rows)
    print_rank_summary(rank_rows)

    conversion_rows = conversion_tests(modules)
    write_csv(CONVERSION_CSV, conversion_rows)
    print_conversion_summary(conversion_rows)

    print("\nFiles written")
    print("-------------")
    print(f"rank tests:       {RANK_CSV.resolve()}")
    print(f"conversion tests: {CONVERSION_CSV.resolve()}")
    print(f"conversion PGN:   {CONVERSION_PGN.resolve()}")
    print(f"total time:       {time.time() - start:.1f}s")


if __name__ == "__main__":
    main()
