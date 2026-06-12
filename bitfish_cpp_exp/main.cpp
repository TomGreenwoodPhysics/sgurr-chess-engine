#include "board.hpp"
#include "evaluation.hpp"
#include "search.hpp"

#include <iostream>
#include <optional>
#include <sstream>
#include <string>
#include <vector>

std::vector<std::string> split(const std::string& text) {
    std::vector<std::string> parts;
    std::istringstream stream(text);
    std::string part;

    while (stream >> part) {
        parts.push_back(part);
    }

    return parts;
}

std::optional<Move> parse_move(Board& board, const std::string& text) {
    for (const Move& move : board.generate_legal_moves()) {
        if (move_to_string(move) == text) {
            return move;
        }
    }

    return std::nullopt;
}

Board apply_uci_position(Board board, const std::string& command) {
    std::vector<std::string> parts = split(command);

    if (parts.size() < 2) {
        return board;
    }

    std::size_t move_start = parts.size();

    if (parts[1] == "startpos") {
        board = Board(START_FEN);

        if (parts.size() > 2 && parts[2] == "moves") {
            move_start = 3;
        }
    } else if (parts[1] == "fen") {
        std::size_t moves_index = parts.size();

        for (std::size_t i = 2; i < parts.size(); ++i) {
            if (parts[i] == "moves") {
                moves_index = i;
                break;
            }
        }

        std::string fen;

        for (std::size_t i = 2; i < moves_index; ++i) {
            if (!fen.empty()) {
                fen += " ";
            }

            fen += parts[i];
        }

        board = Board(fen);

        if (moves_index < parts.size()) {
            move_start = moves_index + 1;
        }
    } else {
        return board;
    }

    for (std::size_t i = move_start; i < parts.size(); ++i) {
        std::optional<Move> move = parse_move(board, parts[i]);

        if (!move.has_value()) {
            break;
        }

        board.make_move(*move);
    }

    return board;
}

std::optional<int> parse_go_depth(const std::string& command) {
    std::vector<std::string> parts = split(command);

    for (std::size_t i = 0; i + 1 < parts.size(); ++i) {
        if (parts[i] == "depth") {
            return std::stoi(parts[i + 1]);
        }
    }

    return std::nullopt;
}

std::optional<long long> parse_go_value(const std::string& command, const std::string& token) {
    std::vector<std::string> parts = split(command);

    for (std::size_t i = 0; i + 1 < parts.size(); ++i) {
        if (parts[i] == token) {
            return std::stoll(parts[i + 1]);
        }
    }

    return std::nullopt;
}

std::optional<double> parse_go_movetime(const std::string& command, const Board& board) {
    if (auto movetime = parse_go_value(command, "movetime")) {
        return *movetime / 1000.0;
    }

    // Clock-based allocation from wtime/btime/winc/binc/movestogo.
    bool white = board.side_to_move == WHITE;
    auto time_left = parse_go_value(command, white ? "wtime" : "btime");

    if (!time_left.has_value()) {
        return std::nullopt;   // no clock given: fixed-depth search
    }

    long long inc = parse_go_value(command, white ? "winc" : "binc").value_or(0);
    long long mtg = parse_go_value(command, "movestogo").value_or(30);

    if (mtg < 1) {
        mtg = 1;
    }

    // Budget one slice of the remaining time plus half the increment, never
    // more than half the clock, with a small safety floor.
    long long budget = *time_left / mtg + inc / 2;
    budget = std::min(budget, *time_left / 2);
    budget = std::max(budget, 10LL);

    return budget / 1000.0;
}

void uci_loop() {
    Board board;
    Engine engine;

    std::string command;

    while (std::getline(std::cin, command)) {
        if (command == "uci") {
            std::cout << "id name BitfishCPP\n";
            std::cout << "id author Tom\n";
            std::cout << "uciok\n";
        } else if (command == "isready") {
            std::cout << "readyok\n";
        } else if (command == "ucinewgame") {
            board = Board();
            engine.clear_for_new_game();
        } else if (command.rfind("position", 0) == 0) {
            board = apply_uci_position(board, command);
            engine.clear_for_new_position();
        } else if (command.rfind("go", 0) == 0) {
            std::optional<int> requested_depth = parse_go_depth(command);
            std::optional<double> movetime = parse_go_movetime(command, board);

            // With a clock or movetime, depth is bounded by time, not a cap.
            int depth = requested_depth.value_or(
                movetime.has_value() ? MAX_PLY - 1 : MAX_DEPTH
            );

            SearchResult result = engine.search_best_move(
                board,
                depth,
                movetime
            );

            if (result.best_move.has_value()) {
                std::cout << "bestmove " << move_to_string(*result.best_move) << "\n";
            } else {
                std::cout << "bestmove 0000\n";
            }
        } else if (command == "quit") {
            break;
        }
    }
}

void test_mode() {
    Board board;
    Engine engine;

    board.print_board();

    std::cout << "\nperft tests:\n";

    for (int depth = 1; depth <= 4; ++depth) {
        std::cout << "perft(" << depth << ") = " << perft(board, depth) << "\n";
    }

    std::cout << "\nevaluation tests:\n";
    std::cout << "start eval = " << board.evaluate() << "\n";

    Move e2e4(square_index("e2"), square_index("e4"));
    UndoInfo undo = board.make_move(e2e4);
    std::cout << "after e2e4 eval, black to move = " << board.evaluate() << "\n";
    board.unmake_move(undo);
    std::cout << "after unmake eval = " << board.evaluate() << "\n";

    std::cout << "\nnull move test:\n";

    U64 old_hash = board.hash_key;
    int old_eval = board.evaluate();

    NullMoveUndo null_undo = board.make_null_move();

    std::cout << "after null move side = "
              << (board.side_to_move == WHITE ? "white" : "black")
              << "\n";

    board.unmake_null_move(null_undo);

    std::cout << "null restored hash = "
              << (board.hash_key == old_hash ? "yes" : "no")
              << "\n";

    std::cout << "null restored eval = "
              << (board.evaluate() == old_eval ? "yes" : "no")
              << "\n";

    std::cout << "\nsearch test:\n";

    SearchResult result = engine.search_best_move(
        board,
        5,
        2.0
    );

    if (result.best_move.has_value()) {
        std::cout << "best move: " << move_to_string(*result.best_move) << "\n";
    } else {
        std::cout << "best move: none\n";
    }

    std::cout << "score: " << result.score << "\n";
    std::cout << "depth: " << result.depth << "\n";
    std::cout << "nodes: " << result.nodes << "\n";
    std::cout << "tt hits: " << result.tt_hits << "\n";
    std::cout << "time: " << result.time_taken << "s\n";
}

int main(int argc, char* argv[]) {
    if (argc > 1 && std::string(argv[1]) == "uci") {
        uci_loop();
    } else if (argc > 2 && std::string(argv[1]) == "fen") {
        std::string fen;

        for (int i = 2; i < argc; ++i) {
            if (!fen.empty()) {
                fen += " ";
            }

            fen += argv[i];
        }

        Board board(fen);
        Engine engine;

        board.print_board();

        SearchResult result = engine.search_best_move(
            board,
            10,
            5.0
        );

        if (result.best_move.has_value()) {
            std::cout << "best move: " << move_to_string(*result.best_move) << "\n";
        } else {
            std::cout << "best move: none\n";
        }

        std::cout << "score: " << result.score << "\n";
        std::cout << "depth: " << result.depth << "\n";
        std::cout << "nodes: " << result.nodes << "\n";
        std::cout << "time: " << result.time_taken << "s\n";
    } else {
        test_mode();
    }

    return 0;
}