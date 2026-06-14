from __future__ import annotations

import csv
import json
import math
import os
import time
from pathlib import Path
from typing import Any

import chess
import chess.engine
import chess.pgn


# ---------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------

PROJECT_DIR = Path(__file__).resolve().parent

STOCKFISH_PATH = r"C:\Users\Tom Greenwood\Desktop\Coding Projects\Chess Bot\stockfish\stockfish-windows-x86-64-avx2.exe"
BITFISH_CPP_PATH = PROJECT_DIR.parent / "bitfish_cpp_exp" / "bitfish_exp.exe"

# allows a dynamically linked MSYS2 build to run when launched from PowerShell/Anaconda
MSYS2_UCRT64_BIN = r"C:\msys64\ucrt64\bin"
os.environ["PATH"] = MSYS2_UCRT64_BIN + os.pathsep + os.environ["PATH"]


# ---------------------------------------------------------------------
# benchmark settings
# ---------------------------------------------------------------------

STOCKFISH_ELO = 2400
NUM_GAMES = 1000
MAX_PLIES = 400

# depth is a safety cap; time is the main limit
BITFISH_MAX_DEPTH = 100
BITFISH_TIME_PER_MOVE = 0.5
STOCKFISH_TIME_PER_MOVE = 0.1

# true = most stable while debugging; avoids carrying C++ TT/history across positions
# false = faster and closer to a normal engine game, but currently more likely to expose state bugs
USE_FRESH_BITFISH_PROCESS_EACH_MOVE = False

ENGINE_STARTUP_TIMEOUT = 20.0

OUTPUT_DIR = PROJECT_DIR / "analysis_games"
PGN_FILE = OUTPUT_DIR / "bitfish_cpp_benchmark_games.pgn"
MOVE_LOG_FILE = OUTPUT_DIR / "bitfish_cpp_move_log.jsonl"
DIAGNOSTICS_FILE = OUTPUT_DIR / "bitfish_cpp_diagnostics.csv"
CRASH_POSITION_FILE = PROJECT_DIR / "cpp_crash_position.json"
CRASH_UCI_FILE = PROJECT_DIR / "cpp_crash_uci_command.txt"

LOW_DEPTH_LIMIT = 3
WORST_CASES_TO_PRINT = 20


def get_game_phase(ply: int) -> str:
    if ply < 20:
        return "opening"

    if ply < 80:
        return "middlegame"

    return "endgame"


def score_to_centipawns(score: chess.engine.PovScore, turn: chess.Color) -> int:
    pov = score.pov(turn)

    if pov.is_mate():
        mate = pov.mate()
        if mate is None:
            return 0
        return 100000 if mate > 0 else -100000

    cp = pov.score()
    return cp if cp is not None else 0


def launch_bitfish() -> chess.engine.SimpleEngine:
    return chess.engine.SimpleEngine.popen_uci(
        [str(BITFISH_CPP_PATH), "uci"],
        timeout=ENGINE_STARTUP_TIMEOUT,
    )


def choose_bitfish_cpp_move(
    bitfish: chess.engine.SimpleEngine,
    board: chess.Board,
) -> tuple[chess.Move | None, dict[str, Any]]:
    start = time.time()

    result = bitfish.play(
        board,
        chess.engine.Limit(
            time=BITFISH_TIME_PER_MOVE,
            depth=BITFISH_MAX_DEPTH,
        ),
        info=chess.engine.INFO_ALL,
    )

    elapsed = time.time() - start
    info = result.info

    move = result.move
    nodes = int(info.get("nodes", 0))
    depth = int(info.get("depth", 0))

    # python-chess uses tbhits for tablebases, not our transposition table.
    # keep this column for compatibility, but expect it to be zero for now.
    tt_hits = int(info.get("tbhits", 0))

    score_obj = info.get("score")
    score = score_to_centipawns(score_obj, board.turn) if score_obj is not None else 0

    nodes_per_second = nodes / elapsed if elapsed > 0 else 0

    stats: dict[str, Any] = {
        "depth": depth,
        "nodes": nodes,
        "time": elapsed,
        "nodes_per_second": nodes_per_second,
        "legal_moves": board.legal_moves.count(),
        "tt_hits": tt_hits,
        "score": score,
    }

    return move, stats


def write_crash_report(
    board: chess.Board,
    game_number: int,
    bitfish_colour: chess.Color,
) -> None:
    move_history = " ".join(move.uci() for move in board.move_stack)

    crash_report = {
        "game": game_number,
        "ply": board.ply(),
        "bitfish_colour": "white" if bitfish_colour == chess.WHITE else "black",
        "fen": board.fen(),
        "legal_moves": [move.uci() for move in board.legal_moves],
        "move_history": move_history,
        "settings": {
            "bitfish_max_depth": BITFISH_MAX_DEPTH,
            "bitfish_time_per_move": BITFISH_TIME_PER_MOVE,
            "fresh_process_each_move": USE_FRESH_BITFISH_PROCESS_EACH_MOVE,
        },
    }

    CRASH_POSITION_FILE.write_text(
        json.dumps(crash_report, indent=4),
        encoding="utf-8",
    )

    CRASH_UCI_FILE.write_text(
        "uci\n"
        "isready\n"
        f"position fen {board.fen()}\n"
        f"go depth {BITFISH_MAX_DEPTH} movetime {int(BITFISH_TIME_PER_MOVE * 1000)}\n"
        "quit\n",
        encoding="utf-8",
    )

    print()
    print("C++ engine crashed.")
    print("-------------------")
    print(f"game: {crash_report['game']}")
    print(f"ply: {crash_report['ply']}")
    print(f"colour: {crash_report['bitfish_colour']}")
    print(f"fen: {crash_report['fen']}")
    print(f"crash position written to {CRASH_POSITION_FILE.name}")
    print(f"uci reproduction written to {CRASH_UCI_FILE.name}")


def save_game_pgn(
    board: chess.Board,
    game_number: int,
    bitfish_colour: chess.Color,
    result: str,
) -> None:
    game = chess.pgn.Game.from_board(board)

    game.headers["Event"] = "Bitfish C++ Benchmark"
    game.headers["Round"] = str(game_number)
    game.headers["White"] = "BitfishCPP" if bitfish_colour == chess.WHITE else "Stockfish"
    game.headers["Black"] = "BitfishCPP" if bitfish_colour == chess.BLACK else "Stockfish"
    game.headers["Result"] = result
    game.headers["StockfishElo"] = str(STOCKFISH_ELO)
    game.headers["BitfishTimePerMove"] = f"{BITFISH_TIME_PER_MOVE:.2f}"
    game.headers["BitfishMaxDepth"] = str(BITFISH_MAX_DEPTH)
    game.headers["FreshBitfishProcessEachMove"] = str(USE_FRESH_BITFISH_PROCESS_EACH_MOVE)
    game.headers["StockfishTimePerMove"] = f"{STOCKFISH_TIME_PER_MOVE:.2f}"

    with PGN_FILE.open("a", encoding="utf-8") as file:
        print(game, file=file, end="\n\n")


def choose_bitfish_move_safely(
    board: chess.Board,
    game_number: int,
    bitfish_colour: chess.Color,
    persistent_engine: chess.engine.SimpleEngine | None,
) -> tuple[chess.Move | None, dict[str, Any]]:
    try:
        if USE_FRESH_BITFISH_PROCESS_EACH_MOVE:
            with launch_bitfish() as bitfish:
                return choose_bitfish_cpp_move(bitfish, board)

        if persistent_engine is None:
            raise RuntimeError("persistent_engine is None while fresh-process mode is disabled")

        return choose_bitfish_cpp_move(persistent_engine, board)

    except Exception:
        write_crash_report(board, game_number, bitfish_colour)
        raise


def play_game(
    stockfish: chess.engine.SimpleEngine,
    bitfish_colour: chess.Color,
    game_number: int,
) -> tuple[str, int, str, list[dict], str]:
    board = chess.Board()

    move_stats: list[dict] = []
    bitfish_move_logs: list[dict] = []
    stop_reason = "normal_game_over"

    persistent_bitfish: chess.engine.SimpleEngine | None = None

    try:
        if not USE_FRESH_BITFISH_PROCESS_EACH_MOVE:
            persistent_bitfish = launch_bitfish()

        while not board.is_game_over(claim_draw=True) and board.ply() < MAX_PLIES:
            if board.turn == bitfish_colour:
                phase = get_game_phase(board.ply())
                fen_before = board.fen()

                move, stats = choose_bitfish_move_safely(
                    board,
                    game_number,
                    bitfish_colour,
                    persistent_bitfish,
                )

                row = {
                    "game": game_number,
                    "ply": board.ply(),
                    "fen_before": fen_before,
                    "move": move.uci() if move is not None else None,
                    "bitfish_colour": "white" if bitfish_colour == chess.WHITE else "black",
                    "phase": phase,
                    "depth": stats["depth"],
                    "nodes": stats["nodes"],
                    "time": stats["time"],
                    "nodes_per_second": stats["nodes_per_second"],
                    "legal_moves": stats["legal_moves"],
                    "tt_hits": stats["tt_hits"],
                    "score": stats["score"],
                }

                move_stats.append(row)
                bitfish_move_logs.append(row.copy())

            else:
                result = stockfish.play(
                    board,
                    chess.engine.Limit(time=STOCKFISH_TIME_PER_MOVE),
                )
                move = result.move

            if move is None:
                stop_reason = "move_is_none"
                print(f"  stopped early: {stop_reason}")
                print(f"  fen: {board.fen()}")
                break

            if move not in board.legal_moves:
                stop_reason = f"illegal_move:{move}"
                print(f"  stopped early: {stop_reason}")
                print(board)
                print(f"  fen: {board.fen()}")
                print("  legal moves:", " ".join(m.uci() for m in board.legal_moves))
                break

            board.push(move)

    finally:
        if persistent_bitfish is not None:
            persistent_bitfish.quit()

    if board.ply() >= MAX_PLIES and not board.is_game_over(claim_draw=True):
        stop_reason = "max_plies"

    result = board.result(claim_draw=True)

    save_game_pgn(board, game_number, bitfish_colour, result)

    with MOVE_LOG_FILE.open("a", encoding="utf-8") as file:
        for log in bitfish_move_logs:
            log["result"] = result
            log["stop_reason"] = stop_reason
            file.write(json.dumps(log) + "\n")

    for stat in move_stats:
        stat["result"] = result
        stat["stop_reason"] = stop_reason

    if result == "*" and stop_reason == "normal_game_over":
        stop_reason = "unfinished_unknown"

    if result == "*":
        return "unfinished", board.ply(), result, move_stats, stop_reason

    if result == "1/2-1/2":
        return "draw", board.ply(), result, move_stats, stop_reason

    if result == "1-0":
        winner = chess.WHITE
    elif result == "0-1":
        winner = chess.BLACK
    else:
        return "unfinished", board.ply(), result, move_stats, stop_reason

    if winner == bitfish_colour:
        return "win", board.ply(), result, move_stats, stop_reason

    return "loss", board.ply(), result, move_stats, stop_reason


def score_results(results: list[str]) -> tuple[int, int, int, int, float, float]:
    wins = results.count("win")
    draws = results.count("draw")
    losses = results.count("loss")
    unfinished = results.count("unfinished")

    completed = wins + draws + losses
    score = wins + 0.5 * draws
    score_rate = score / completed if completed > 0 else 0

    return wins, draws, losses, unfinished, score, score_rate


def estimate_elo_difference(score_rate: float) -> float:
    if score_rate <= 0:
        return -999

    if score_rate >= 1:
        return 999

    return -400 * math.log10(1 / score_rate - 1)


def average(values: list[float]) -> float:
    if not values:
        return 0.0

    return sum(values) / len(values)


def summarise_search_stats(all_move_stats: list[dict]) -> dict[str, Any]:
    depths = [stat["depth"] for stat in all_move_stats]
    nodes = [stat["nodes"] for stat in all_move_stats]
    times = [stat["time"] for stat in all_move_stats]
    nodes_per_second = [stat["nodes_per_second"] for stat in all_move_stats]
    legal_moves = [stat["legal_moves"] for stat in all_move_stats]
    tt_hits = [stat["tt_hits"] for stat in all_move_stats]
    scores = [stat["score"] for stat in all_move_stats]

    phase_depths = {
        "opening": [],
        "middlegame": [],
        "endgame": [],
    }

    for stat in all_move_stats:
        phase_depths[stat["phase"]].append(stat["depth"])

    return {
        "moves": len(all_move_stats),
        "avg_depth": average(depths),
        "max_depth": max(depths) if depths else 0,
        "avg_nodes": average(nodes),
        "avg_time": average(times),
        "avg_nodes_per_second": average(nodes_per_second),
        "avg_legal_moves": average(legal_moves),
        "avg_tt_hits": average(tt_hits),
        "avg_score": average(scores),
        "phase_depths": {
            phase: average(depth_list)
            for phase, depth_list in phase_depths.items()
        },
    }


def write_diagnostics_csv(all_move_stats: list[dict]) -> None:
    if not all_move_stats:
        return

    fieldnames = [
        "game",
        "ply",
        "bitfish_colour",
        "phase",
        "move",
        "depth",
        "legal_moves",
        "nodes",
        "time",
        "nodes_per_second",
        "tt_hits",
        "score",
        "result",
        "stop_reason",
        "fen_before",
    ]

    with DIAGNOSTICS_FILE.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        for stat in all_move_stats:
            writer.writerow({
                "game": stat.get("game"),
                "ply": stat.get("ply"),
                "bitfish_colour": stat.get("bitfish_colour"),
                "phase": stat.get("phase"),
                "move": stat.get("move"),
                "depth": stat.get("depth"),
                "legal_moves": stat.get("legal_moves"),
                "nodes": stat.get("nodes"),
                "time": f"{stat.get('time', 0):.6f}",
                "nodes_per_second": f"{stat.get('nodes_per_second', 0):.1f}",
                "tt_hits": stat.get("tt_hits"),
                "score": stat.get("score"),
                "result": stat.get("result"),
                "stop_reason": stat.get("stop_reason"),
                "fen_before": stat.get("fen_before"),
            })


def print_position_report(title: str, rows: list[dict]) -> None:
    print()
    print(title)
    print("-" * len(title))

    if not rows:
        print("none")
        return

    for stat in rows[:WORST_CASES_TO_PRINT]:
        print(
            f"game {stat['game']:>2} ply {stat['ply']:>3} "
            f"{stat['phase']:<10} depth {stat['depth']:>2} "
            f"legal {stat['legal_moves']:>2} "
            f"nodes {stat['nodes']:>8} "
            f"nps {stat['nodes_per_second']:>9.0f} "
            f"time {stat['time']:>5.2f}s "
            f"score {stat['score']:>8} "
            f"move {stat['move']}"
        )
        print(f"fen: {stat['fen_before']}")


def print_diagnostic_reports(all_move_stats: list[dict]) -> None:
    middlegame = [
        stat for stat in all_move_stats
        if stat["phase"] == "middlegame"
    ]

    low_depth_middlegame = sorted(
        [
            stat for stat in middlegame
            if stat["depth"] <= LOW_DEPTH_LIMIT
        ],
        key=lambda stat: (
            stat["depth"],
            -stat["legal_moves"],
            stat["nodes_per_second"],
        ),
    )

    worst_nodes_per_second = sorted(
        all_move_stats,
        key=lambda stat: stat["nodes_per_second"],
    )

    highest_legal_moves = sorted(
        all_move_stats,
        key=lambda stat: stat["legal_moves"],
        reverse=True,
    )

    longest_searches = sorted(
        all_move_stats,
        key=lambda stat: stat["time"],
        reverse=True,
    )

    print_position_report(
        f"Worst middlegame searches: depth <= {LOW_DEPTH_LIMIT}",
        low_depth_middlegame,
    )
    print_position_report(
        "Slowest nodes/s positions",
        worst_nodes_per_second,
    )
    print_position_report(
        "Highest legal-move-count positions",
        highest_legal_moves,
    )
    print_position_report(
        "Longest Bitfish C++ searches",
        longest_searches,
    )


def check_paths() -> None:
    if not BITFISH_CPP_PATH.exists():
        raise FileNotFoundError(
            f"Could not find {BITFISH_CPP_PATH}. "
            "Compile the C++ engine first from bitfish_cpp/."
        )

    if not Path(STOCKFISH_PATH).exists():
        raise FileNotFoundError(f"Could not find Stockfish at {STOCKFISH_PATH}")


def main() -> None:
    check_paths()

    OUTPUT_DIR.mkdir(exist_ok=True)
    PGN_FILE.write_text("", encoding="utf-8")
    MOVE_LOG_FILE.write_text("", encoding="utf-8")
    DIAGNOSTICS_FILE.write_text("", encoding="utf-8")

    results = []
    all_move_stats = []

    with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH, timeout=ENGINE_STARTUP_TIMEOUT) as stockfish:
        stockfish.configure({
            "UCI_LimitStrength": True,
            "UCI_Elo": STOCKFISH_ELO,
        })

        start_time = time.time()

        for game_number in range(1, NUM_GAMES + 1):
            bitfish_colour = chess.WHITE if game_number % 2 == 1 else chess.BLACK
            colour_name = "White" if bitfish_colour == chess.WHITE else "Black"

            print(f"Game {game_number}/{NUM_GAMES}: Bitfish C++ as {colour_name}")

            result, plies, raw_result, move_stats, stop_reason = play_game(
                stockfish,
                bitfish_colour,
                game_number,
            )

            results.append(result)
            all_move_stats.extend(move_stats)

            game_avg_depth = average([stat["depth"] for stat in move_stats])
            game_avg_time = average([stat["time"] for stat in move_stats])

            print(f"  result: {result} ({raw_result}), plies: {plies}")
            print(f"  stop reason: {stop_reason}")
            print(f"  average depth: {game_avg_depth:.2f}")
            print(f"  average time/move: {game_avg_time:.2f}s")

        elapsed = time.time() - start_time

    wins, draws, losses, unfinished, score, score_rate = score_results(results)
    elo_diff = estimate_elo_difference(score_rate)
    search_stats = summarise_search_stats(all_move_stats)

    print()
    print("Benchmark complete")
    print("------------------")
    print("Engine: Bitfish C++")
    print(f"Fresh engine each move: {USE_FRESH_BITFISH_PROCESS_EACH_MOVE}")
    print(f"Bitfish time per move: {BITFISH_TIME_PER_MOVE:.2f}s")
    print(f"Bitfish max depth: {BITFISH_MAX_DEPTH}")
    print(f"Stockfish Elo setting: {STOCKFISH_ELO}")
    print(f"Stockfish time per move: {STOCKFISH_TIME_PER_MOVE:.2f}s")

    completed_games = wins + draws + losses

    print(f"Games requested: {NUM_GAMES}")
    print(f"Completed games: {completed_games}")
    print(f"Unfinished games: {unfinished}")
    print(f"Wins: {wins}")
    print(f"Draws: {draws}")
    print(f"Losses: {losses}")
    print(f"Score: {score}/{completed_games if completed_games > 0 else 0}")
    print(f"Score rate: {100 * score_rate:.1f}%")

    if score_rate == 1:
        print("Estimated Elo difference: higher than this setting, not enough losses/draws to estimate.")
    elif score_rate == 0:
        print("Estimated Elo difference: lower than this setting, no score achieved.")
    else:
        print(f"Estimated Elo difference vs Stockfish setting: {elo_diff:+.0f}")

    print(f"Total time: {elapsed:.1f}s")

    print()
    print("Engine search stats")
    print("-------------------")
    print(f"Engine moves analysed: {search_stats['moves']}")
    print(f"Average depth reached: {search_stats['avg_depth']:.2f}")
    print(f"Maximum depth reached: {search_stats['max_depth']}")
    print(f"Average nodes per move: {search_stats['avg_nodes']:.0f}")
    print(f"Average time per move: {search_stats['avg_time']:.2f}s")
    print(f"Average nodes/s: {search_stats['avg_nodes_per_second']:.0f}")
    print(f"Average legal moves: {search_stats['avg_legal_moves']:.1f}")
    print(f"Average TT hits per move: {search_stats['avg_tt_hits']:.0f}")
    print(f"Average score: {search_stats['avg_score']:.0f}")

    print()
    print("Average depth by phase")
    print("----------------------")
    print(f"Opening: {search_stats['phase_depths']['opening']:.2f}")
    print(f"Middlegame: {search_stats['phase_depths']['middlegame']:.2f}")
    print(f"Endgame: {search_stats['phase_depths']['endgame']:.2f}")

    write_diagnostics_csv(all_move_stats)
    print_diagnostic_reports(all_move_stats)

    print()
    print("Analysis files written")
    print("----------------------")
    print(f"PGN: {PGN_FILE}")
    print(f"Move log: {MOVE_LOG_FILE}")
    print(f"Diagnostics CSV: {DIAGNOSTICS_FILE}")


if __name__ == "__main__":
    main()