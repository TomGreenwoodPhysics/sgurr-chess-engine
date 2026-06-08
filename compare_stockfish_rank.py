from __future__ import annotations

import csv
import importlib
import re
import subprocess
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType


STOCKFISH_PATH = (
    r"C:\Users\Tom Greenwood\Desktop\Coding Projects\Chess Bot"
    r"\stockfish\stockfish-windows-x86-64-avx2.exe"
)

STOCKFISH_DEPTH = 12
STOCKFISH_MULTIPV = 8
BITFISH_DEPTH = 5

OUTPUT_FILE = Path("bitfish_stockfish_rank_comparison.csv")

VERSIONS = [
    {
        "name": "v7_baseline",
        "board_module": "bitfish_board_v7",
        "engine_module": "bitfish_engine_v7",
        "package_alias": "CPv7",
    },
    {
        "name": "pst_experiment",
        "board_module": "bitfish_board_pst_experiment",
        "engine_module": "bitfish_engine_pst_experiment",
        "package_alias": "CPpst",
    },
]


POSITIONS = [
    {
        "name": "startpos",
        "fen": "rnbqkbnr/pppppppp/8/8/8/8/8/8 w - - 0 1",
        "notes": "intentionally unused placeholder",
    },
]

# actual positions kept separate to avoid accidental editing above
POSITIONS = [
    {
        "name": "startpos",
        "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "notes": "starting position",
    },
    {
        "name": "open_game_after_e4_e5",
        "fen": "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
        "notes": "simple open game after 1 e4 e5",
    },
    {
        "name": "four_knights_like",
        "fen": "r1bqkb1r/pppp1ppp/2n2n2/4p3/4P3/2N2N2/PPPP1PPP/R1BQKB1R w KQkq - 4 4",
        "notes": "normal development position",
    },
    {
        "name": "italian_like",
        "fen": "r1bqk1nr/pppp1ppp/2n5/2b1p3/2B1P3/2N2N2/PPPP1PPP/R1BQK2R w KQkq - 4 4",
        "notes": "castling/development position",
    },
    {
        "name": "kiwipete",
        "fen": "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        "notes": "classic complex move-generation/search test",
    },
    {
        "name": "tactical_pressure",
        "fen": "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQK2R w KQkq - 4 5",
        "notes": "development with central tension",
    },
    {
        "name": "queen_activity",
        "fen": "rnb1kbnr/pppp1ppp/8/4p3/4P2q/5N2/PPPP1PPP/RNBQKB1R w KQkq - 1 3",
        "notes": "early queen activity and king safety",
    },
    {
        "name": "rook_endgame",
        "fen": "4r1k1/5ppp/8/8/8/8/5PPP/4R1K1 w - - 0 1",
        "notes": "simple rook endgame",
    },
    {
        "name": "king_pawn_endgame",
        "fen": "8/8/8/3k4/3P4/3K4/8/8 w - - 0 1",
        "notes": "king and pawn endgame",
    },
    {
        "name": "promotion_race",
        "fen": "8/P6k/8/8/8/8/6pK/8 w - - 0 1",
        "notes": "promotion race",
    },
]


@dataclass
class EngineModules:
    name: str
    board_module: ModuleType
    engine_module: ModuleType


@dataclass
class EngineResult:
    version: str
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


@dataclass
class RankedResult:
    position: str
    version: str
    bitfish_move: str
    bitfish_score: int
    bitfish_depth: int
    bitfish_nodes: int
    bitfish_time_s: float
    stockfish_rank: int | None
    stockfish_score_type: str | None
    stockfish_score: int | None
    stockfish_cp_loss: int | None
    stockfish_best_move: str
    stockfish_best_score: int
    fen: str
    notes: str


class StockfishUCI:
    def __init__(self, path: str, depth: int, multipv: int) -> None:
        self.path = path
        self.depth = depth
        self.multipv = multipv
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
            raise RuntimeError("stockfish stdin is not available")

        self.proc.stdin.write(command + "\n")
        self.proc.stdin.flush()

    def _readline(self) -> str:
        if self.proc.stdout is None:
            raise RuntimeError("stockfish stdout is not available")

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

        return [
            lines_by_rank[rank]
            for rank in sorted(lines_by_rank)
        ]


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
    first_move = pv.split()[0]

    if score_type == "cp":
        cp_equiv = score
    else:
        # keep mate scores ordered far beyond centipawn scores
        if score > 0:
            cp_equiv = 100_000 - abs(score)
        else:
            cp_equiv = -100_000 + abs(score)

    return StockfishLine(
        rank=rank,
        move=first_move,
        score_type=score_type,
        score=score,
        score_cp_equiv=cp_equiv,
        pv=pv,
    )


def register_package_alias(
    package_name: str,
    board_module_name: str,
    board_module: ModuleType,
) -> None:
    if package_name not in sys.modules:
        package = types.ModuleType(package_name)
        package.__path__ = []
        sys.modules[package_name] = package

    sys.modules[f"{package_name}.{board_module_name}"] = board_module


def load_engine_modules() -> list[EngineModules]:
    loaded = []

    for version in VERSIONS:
        board_module_name = version["board_module"]
        engine_module_name = version["engine_module"]
        package_alias = version["package_alias"]

        board_module = importlib.import_module(board_module_name)
        register_package_alias(package_alias, board_module_name, board_module)

        engine_module = importlib.import_module(engine_module_name)

        loaded.append(
            EngineModules(
                name=version["name"],
                board_module=board_module,
                engine_module=engine_module,
            )
        )

    return loaded


def run_engine(modules: EngineModules, fen: str, depth: int) -> EngineResult:
    board = modules.board_module.Board(fen)
    engine = modules.engine_module.Engine()

    result = engine.search_best_move(board, max_depth=depth)
    best_move = "0000" if result.best_move is None else str(result.best_move)

    return EngineResult(
        version=modules.name,
        move=best_move,
        score=result.score,
        depth=result.depth,
        nodes=result.nodes,
        tt_hits=result.tt_hits,
        time_s=result.time_taken,
    )


def rank_engine_move(
    position: dict,
    engine_result: EngineResult,
    stockfish_lines: list[StockfishLine],
) -> RankedResult:
    best_line = stockfish_lines[0]
    matching_line = None

    for line in stockfish_lines:
        if line.move == engine_result.move:
            matching_line = line
            break

    if matching_line is None:
        stockfish_rank = None
        score_type = None
        score = None
        cp_loss = None
    else:
        stockfish_rank = matching_line.rank
        score_type = matching_line.score_type
        score = matching_line.score
        cp_loss = best_line.score_cp_equiv - matching_line.score_cp_equiv

    return RankedResult(
        position=position["name"],
        version=engine_result.version,
        bitfish_move=engine_result.move,
        bitfish_score=engine_result.score,
        bitfish_depth=engine_result.depth,
        bitfish_nodes=engine_result.nodes,
        bitfish_time_s=engine_result.time_s,
        stockfish_rank=stockfish_rank,
        stockfish_score_type=score_type,
        stockfish_score=score,
        stockfish_cp_loss=cp_loss,
        stockfish_best_move=best_line.move,
        stockfish_best_score=best_line.score,
        fen=position["fen"],
        notes=position["notes"],
    )


def run_comparison() -> list[RankedResult]:
    modules_list = load_engine_modules()

    print("loaded versions:")
    for modules in modules_list:
        print(f"  {modules.name}: {modules.board_module.__name__}, {modules.engine_module.__name__}")

    stockfish = StockfishUCI(
        path=STOCKFISH_PATH,
        depth=STOCKFISH_DEPTH,
        multipv=STOCKFISH_MULTIPV,
    )

    ranked_results = []

    try:
        for index, position in enumerate(POSITIONS, start=1):
            print()
            print(f"[{index}/{len(POSITIONS)}] {position['name']}")

            stockfish_lines = stockfish.analyse_multipv(position["fen"])
            print("stockfish top moves:")

            for line in stockfish_lines:
                score_text = (
                    f"{line.score} cp"
                    if line.score_type == "cp"
                    else f"mate {line.score}"
                )
                print(f"  #{line.rank}: {line.move} ({score_text})")

            for modules in modules_list:
                print(f"running {modules.name}...")
                engine_result = run_engine(modules, position["fen"], BITFISH_DEPTH)
                ranked = rank_engine_move(position, engine_result, stockfish_lines)
                ranked_results.append(ranked)

                if ranked.stockfish_rank is None:
                    rank_text = f"outside top {STOCKFISH_MULTIPV}"
                    loss_text = "unknown loss"
                else:
                    rank_text = f"rank #{ranked.stockfish_rank}"
                    loss_text = f"{ranked.stockfish_cp_loss} cp loss"

                print(
                    f"  {modules.name}: {ranked.bitfish_move}, "
                    f"{rank_text}, {loss_text}, "
                    f"nodes {ranked.bitfish_nodes}, time {ranked.bitfish_time_s:.3f}s"
                )
    finally:
        stockfish.close()

    return ranked_results


def print_summary(results: list[RankedResult]) -> None:
    version_names = [version["name"] for version in VERSIONS]

    print()
    print("=" * 88)
    print("summary")
    print("=" * 88)

    for version in version_names:
        version_results = [
            result for result in results
            if result.version == version
        ]

        ranked = [
            result for result in version_results
            if result.stockfish_rank is not None
        ]

        top_1 = sum(result.stockfish_rank == 1 for result in version_results)
        top_3 = sum(
            result.stockfish_rank is not None and result.stockfish_rank <= 3
            for result in version_results
        )
        top_n = len(ranked)

        known_losses = [
            result.stockfish_cp_loss
            for result in version_results
            if result.stockfish_cp_loss is not None
        ]

        rank_values = [
            result.stockfish_rank
            for result in ranked
            if result.stockfish_rank is not None
        ]

        avg_rank = (
            sum(rank_values) / len(rank_values)
            if rank_values else 0
        )
        avg_loss = (
            sum(known_losses) / len(known_losses)
            if known_losses else 0
        )
        total_nodes = sum(result.bitfish_nodes for result in version_results)
        total_time = sum(result.bitfish_time_s for result in version_results)
        nodes_per_s = total_nodes / total_time if total_time > 0 else 0

        print()
        print(version)
        print("-" * len(version))
        print(f"stockfish top-1 matches: {top_1}/{len(version_results)}")
        print(f"stockfish top-3 moves:   {top_3}/{len(version_results)}")
        print(f"inside top {STOCKFISH_MULTIPV}:        {top_n}/{len(version_results)}")
        print(f"average rank:            {avg_rank:.2f}")
        print(f"average cp loss:         {avg_loss:.1f}")
        print(f"total nodes:             {total_nodes}")
        print(f"total time:              {total_time:.3f}s")
        print(f"nodes/s:                 {nodes_per_s:.1f}")

    print()
    print("=" * 88)
    print("position comparison")
    print("=" * 88)

    headers = ["position", "sf best"] + version_names
    rows = []

    positions = list(dict.fromkeys(result.position for result in results))

    for position in positions:
        position_results = [
            result for result in results
            if result.position == position
        ]

        sf_best = position_results[0].stockfish_best_move
        row = [position, sf_best]

        for version in version_names:
            result = next(
                result for result in position_results
                if result.version == version
            )

            if result.stockfish_rank is None:
                detail = f"{result.bitfish_move} >{STOCKFISH_MULTIPV}"
            else:
                detail = (
                    f"{result.bitfish_move} #{result.stockfish_rank} "
                    f"({result.stockfish_cp_loss}cp)"
                )

            row.append(detail)

        rows.append(row)

    widths = [
        max(len(str(row[i])) for row in [headers] + rows)
        for i in range(len(headers))
    ]

    print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
    print("  ".join("-" * widths[i] for i in range(len(headers))))

    for row in rows:
        print("  ".join(str(row[i]).ljust(widths[i]) for i in range(len(row))))


def write_csv(results: list[RankedResult]) -> None:
    fieldnames = [
        "position",
        "version",
        "bitfish_move",
        "stockfish_rank",
        "stockfish_cp_loss",
        "stockfish_score_type",
        "stockfish_score",
        "stockfish_best_move",
        "stockfish_best_score",
        "bitfish_score",
        "bitfish_depth",
        "bitfish_nodes",
        "bitfish_time_s",
        "fen",
        "notes",
    ]

    with OUTPUT_FILE.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        for result in results:
            writer.writerow(
                {
                    "position": result.position,
                    "version": result.version,
                    "bitfish_move": result.bitfish_move,
                    "stockfish_rank": result.stockfish_rank,
                    "stockfish_cp_loss": result.stockfish_cp_loss,
                    "stockfish_score_type": result.stockfish_score_type,
                    "stockfish_score": result.stockfish_score,
                    "stockfish_best_move": result.stockfish_best_move,
                    "stockfish_best_score": result.stockfish_best_score,
                    "bitfish_score": result.bitfish_score,
                    "bitfish_depth": result.bitfish_depth,
                    "bitfish_nodes": result.bitfish_nodes,
                    "bitfish_time_s": f"{result.bitfish_time_s:.6f}",
                    "fen": result.fen,
                    "notes": result.notes,
                }
            )


def main() -> None:
    print("Bitfish Stockfish rank comparison")
    print("---------------------------------")
    print(f"stockfish: {STOCKFISH_PATH}")
    print(f"stockfish depth: {STOCKFISH_DEPTH}")
    print(f"stockfish multipv: {STOCKFISH_MULTIPV}")
    print(f"bitfish depth: {BITFISH_DEPTH}")
    print(f"output: {OUTPUT_FILE.resolve()}")
    print()

    results = run_comparison()
    print_summary(results)
    write_csv(results)

    print()
    print(f"wrote: {OUTPUT_FILE.resolve()}")


if __name__ == "__main__":
    main()
