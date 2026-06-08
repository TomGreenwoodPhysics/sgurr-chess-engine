from __future__ import annotations

import csv
import json
import math
import time
from pathlib import Path
from typing import Any

import chess
import chess.engine
import chess.pgn

from v12.bitfish_board_v12_see import Board as BitfishBoard
from v12.bitfish_board_v12_see import Move as BitfishMove
from v12.bitfish_engine_v12_see import Engine as BitfishEngine


STOCKFISH_PATH = r"C:\Users\Tom Greenwood\Desktop\Coding Projects\Chess Bot\stockfish\stockfish-windows-x86-64-avx2.exe"

STOCKFISH_ELO = 2000
NUM_GAMES = 2
MAX_PLIES = 400

BITFISH_MAX_DEPTH = 10
BITFISH_TIME_PER_MOVE = 5
STOCKFISH_TIME_PER_MOVE = 0.1

OUTPUT_DIR = Path("analysis_games")
PGN_FILE = OUTPUT_DIR / "bitfish_benchmark_games.pgn"
MOVE_LOG_FILE = OUTPUT_DIR / "bitfish_move_log.jsonl"
DIAGNOSTICS_FILE = OUTPUT_DIR / "bitfish_diagnostics.csv"

LOW_DEPTH_LIMIT = 3
WORST_CASES_TO_PRINT = 20


def get_game_phase(ply: int) -> str:
    if ply < 20:
        return "opening"

    if ply < 80:
        return "middlegame"

    return "endgame"


def chess_board_to_bitfish_board(board: chess.Board) -> BitfishBoard:
    return BitfishBoard(board.fen())


def bitfish_move_to_chess_move(move: BitfishMove | None) -> chess.Move | None:
    if move is None:
        return None

    return chess.Move.from_uci(str(move))


def choose_bitfish_move(
    engine: BitfishEngine,
    board: chess.Board,
) -> tuple[chess.Move | None, dict[str, Any]]:
    bitfish_board = chess_board_to_bitfish_board(board)
    legal_move_count = len(bitfish_board.generate_legal_moves())

    result = engine.search_best_move(
        bitfish_board,
        max_depth=BITFISH_MAX_DEPTH,
        time_limit=BITFISH_TIME_PER_MOVE,
    )

    best_move: BitfishMove | None = result.best_move
    move = bitfish_move_to_chess_move(best_move)
    nodes_per_second = result.nodes / result.time_taken if result.time_taken > 0 else 0

    stats: dict[str, Any] = {
        "depth": result.depth,
        "nodes": result.nodes,
        "time": result.time_taken,
        "nodes_per_second": nodes_per_second,
        "legal_moves": legal_move_count,
        "tt_hits": result.tt_hits,
        "score": result.score,
        "main_nodes": getattr(result, "main_nodes", 0),
        "q_nodes": getattr(result, "q_nodes", 0),
        "eval_calls": getattr(result, "eval_calls", 0),
        "eval_time": getattr(result, "eval_time", 0.0),
        "movegen_calls": getattr(result, "movegen_calls", 0),
        "movegen_time": getattr(result, "movegen_time", 0.0),
        "futility_prunes": getattr(result, "futility_prunes", 0),
        "delta_prunes": getattr(result, "delta_prunes", 0),
        "null_prunes": getattr(result, "null_prunes", 0),
        "lmr_reductions": getattr(result, "lmr_reductions", 0),
        "lmr_researches": getattr(result, "lmr_researches", 0),
        "beta_cutoffs": getattr(result, "beta_cutoffs", 0),
        "time_checks": getattr(result, "time_checks", 0),
        "full_eval_calls": getattr(result, "full_eval_calls", 0),
        "full_eval_time": getattr(result, "full_eval_time", 0.0),
        "quiet_eval_calls": getattr(result, "quiet_eval_calls", 0),
        "quiet_eval_time": getattr(result, "quiet_eval_time", 0.0),
    }

    return move, stats


def save_game_pgn(
    board: chess.Board,
    game_number: int,
    bitfish_colour: chess.Color,
    result: str,
) -> None:
    game = chess.pgn.Game.from_board(board)

    game.headers["Event"] = "Bitfish Benchmark"
    game.headers["Round"] = str(game_number)
    game.headers["White"] = "Bitfish" if bitfish_colour == chess.WHITE else "Stockfish"
    game.headers["Black"] = "Bitfish" if bitfish_colour == chess.BLACK else "Stockfish"
    game.headers["Result"] = result
    game.headers["StockfishElo"] = str(STOCKFISH_ELO)
    game.headers["BitfishTimePerMove"] = f"{BITFISH_TIME_PER_MOVE:.2f}"
    game.headers["StockfishTimePerMove"] = f"{STOCKFISH_TIME_PER_MOVE:.2f}"
    game.headers["BitfishMaxDepth"] = str(BITFISH_MAX_DEPTH)

    with open(PGN_FILE, "a", encoding="utf-8") as file:
        print(game, file=file, end="\n\n")


def play_game(
    stockfish: chess.engine.SimpleEngine,
    bitfish_colour: chess.Color,
    game_number: int,
) -> tuple[str, int, str, list[dict], str]:
    board = chess.Board()

    # fresh engine each game so the transposition table does not carry over
    bitfish = BitfishEngine()

    move_stats = []
    bitfish_move_logs = []
    stop_reason = "normal_game_over"

    while not board.is_game_over(claim_draw=True) and board.ply() < MAX_PLIES:
        if board.turn == bitfish_colour:
            phase = get_game_phase(board.ply())
            fen_before = board.fen()

            move, stats = choose_bitfish_move(bitfish, board)

            move_stats.append({
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
                "main_nodes": stats["main_nodes"],
                "q_nodes": stats["q_nodes"],
                "eval_calls": stats["eval_calls"],
                "eval_time": stats["eval_time"],
                "full_eval_calls": stats["full_eval_calls"],
                "full_eval_time": stats["full_eval_time"],
                "quiet_eval_calls": stats["quiet_eval_calls"],
                "quiet_eval_time": stats["quiet_eval_time"],
                "movegen_calls": stats["movegen_calls"],
                "movegen_time": stats["movegen_time"],
                "futility_prunes": stats["futility_prunes"],
                "delta_prunes": stats["delta_prunes"],
                "null_prunes": stats["null_prunes"],
                "lmr_reductions": stats["lmr_reductions"],
                "lmr_researches": stats["lmr_researches"],
                "beta_cutoffs": stats["beta_cutoffs"],
                "time_checks": stats["time_checks"],
            })

            bitfish_move_logs.append({
                "game": game_number,
                "ply": board.ply(),
                "fen_before": fen_before,
                "move": move.uci() if move is not None else None,
                "phase": phase,
                "depth": stats["depth"],
                "nodes": stats["nodes"],
                "time": stats["time"],
                "nodes_per_second": stats["nodes_per_second"],
                "legal_moves": stats["legal_moves"],
                "tt_hits": stats["tt_hits"],
                "score": stats["score"],
                "main_nodes": stats["main_nodes"],
                "q_nodes": stats["q_nodes"],
                "eval_calls": stats["eval_calls"],
                "eval_time": stats["eval_time"],
                "full_eval_calls": stats["full_eval_calls"],
                "full_eval_time": stats["full_eval_time"],
                "quiet_eval_calls": stats["quiet_eval_calls"],
                "quiet_eval_time": stats["quiet_eval_time"],
                "movegen_calls": stats["movegen_calls"],
                "movegen_time": stats["movegen_time"],
                "futility_prunes": stats["futility_prunes"],
                "delta_prunes": stats["delta_prunes"],
                "null_prunes": stats["null_prunes"],
                "lmr_reductions": stats["lmr_reductions"],
                "lmr_researches": stats["lmr_researches"],
                "beta_cutoffs": stats["beta_cutoffs"],
                "time_checks": stats["time_checks"],
                "bitfish_colour": "white" if bitfish_colour == chess.WHITE else "black",
            })

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

    if board.ply() >= MAX_PLIES and not board.is_game_over(claim_draw=True):
        stop_reason = "max_plies"

    result = board.result(claim_draw=True)

    save_game_pgn(board, game_number, bitfish_colour, result)

    with open(MOVE_LOG_FILE, "a", encoding="utf-8") as file:
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

    total_decisive_or_drawn = wins + draws + losses
    score = wins + 0.5 * draws
    score_rate = score / total_decisive_or_drawn if total_decisive_or_drawn > 0 else 0

    return wins, draws, losses, unfinished, score, score_rate


def estimate_elo_difference(score_rate: float) -> float:
    if score_rate <= 0:
        return -999

    if score_rate >= 1:
        return 999

    return -400 * math.log10(1 / score_rate - 1)


def average(values: list[float]) -> float:
    if not values:
        return 0

    return sum(values) / len(values)


def summarise_search_stats(all_move_stats: list[dict]) -> dict:
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
        "main_nodes",
        "q_nodes",
        "eval_calls",
        "eval_time",
        "full_eval_calls",
        "full_eval_time",
        "quiet_eval_calls",
        "quiet_eval_time",
        "movegen_calls",
        "movegen_time",
        "futility_prunes",
        "delta_prunes",
        "null_prunes",
        "lmr_reductions",
        "lmr_researches",
        "beta_cutoffs",
        "time_checks",
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
                "main_nodes": stat.get("main_nodes"),
                "q_nodes": stat.get("q_nodes"),
                "eval_calls": stat.get("eval_calls"),
                "eval_time": f"{stat.get('eval_time', 0):.6f}",
                "full_eval_calls": stat.get("full_eval_calls"),
                "full_eval_time": f"{stat.get('full_eval_time', 0):.6f}",
                "quiet_eval_calls": stat.get("quiet_eval_calls"),
                "quiet_eval_time": f"{stat.get('quiet_eval_time', 0):.6f}",
                "movegen_calls": stat.get("movegen_calls"),
                "movegen_time": f"{stat.get('movegen_time', 0):.6f}",
                "futility_prunes": stat.get("futility_prunes"),
                "delta_prunes": stat.get("delta_prunes"),
                "null_prunes": stat.get("null_prunes"),
                "lmr_reductions": stat.get("lmr_reductions"),
                "lmr_researches": stat.get("lmr_researches"),
                "beta_cutoffs": stat.get("beta_cutoffs"),
                "time_checks": stat.get("time_checks"),
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
            f"nodes {stat['nodes']:>7} "
            f"nps {stat['nodes_per_second']:>8.0f} "
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
        "Longest Bitfish searches",
        longest_searches,
    )



def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    PGN_FILE.write_text("", encoding="utf-8")
    MOVE_LOG_FILE.write_text("", encoding="utf-8")
    DIAGNOSTICS_FILE.write_text("", encoding="utf-8")

    results = []
    all_move_stats = []

    with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as stockfish:
        stockfish.configure({
            "UCI_LimitStrength": True,
            "UCI_Elo": STOCKFISH_ELO,
        })

        start_time = time.time()

        for game_number in range(1, NUM_GAMES + 1):
            bitfish_colour = chess.WHITE if game_number % 2 == 1 else chess.BLACK
            colour_name = "White" if bitfish_colour == chess.WHITE else "Black"

            print(f"Game {game_number}/{NUM_GAMES}: Bitfish as {colour_name}")

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
    print(f"Bitfish max depth: {BITFISH_MAX_DEPTH}")
    print(f"Bitfish time per move: {BITFISH_TIME_PER_MOVE:.2f}s")
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
