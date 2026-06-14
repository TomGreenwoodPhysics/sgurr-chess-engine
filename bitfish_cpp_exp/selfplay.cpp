#include "board.hpp"
#include "search.hpp"

#include <cstdlib>
#include <fstream>
#include <iostream>
#include <random>
#include <sstream>
#include <string>
#include <vector>

// Self-play game generator / A-vs-B referee.
//
// Modes:
//   selfplay <games> <depth> <seed> <out.csv>
//       One engine plays itself from randomized openings. Each quiet,
//       in-window position is written as "fen;result" (result from white's
//       point of view: 1, 0.5, 0).
//
// Game end: mate, stalemate, threefold-ish (engine twofold), 50-move,
// bare-kings, or move cap (scored as draw).

namespace {

std::string board_to_fen(const Board& board) {
    std::ostringstream fen;

    for (int rank = 7; rank >= 0; --rank) {
        int empty = 0;

        for (int file = 0; file < 8; ++file) {
            int sq = rank * 8 + file;
            std::optional<int> piece = board.piece_at(sq);

            if (!piece.has_value()) {
                empty += 1;
                continue;
            }

            if (empty > 0) {
                fen << empty;
                empty = 0;
            }

            static const char* chars = "PNBRQKpnbrqk";
            fen << chars[*piece];
        }

        if (empty > 0) {
            fen << empty;
        }

        if (rank > 0) {
            fen << "/";
        }
    }

    fen << (board.side_to_move == WHITE ? " w " : " b ");
    fen << (board.castling.empty() ? "-" : board.castling);
    fen << " ";

    if (board.en_passant.has_value()) {
        fen << square_name(*board.en_passant);
    } else {
        fen << "-";
    }

    fen << " " << board.halfmove_clock << " " << board.fullmove_number;
    return fen.str();
}

bool bare_kings(const Board& board) {
    U64 all = board.occupancy();
    U64 kings = board.bitboards[WK] | board.bitboards[BK];
    return all == kings;
}

bool is_capture(const Board& board, const Move& move) {
    return board.piece_at(move.to_sq).has_value() || move.is_en_passant;
}

} // namespace

int main(int argc, char* argv[]) {
    if (argc < 6 || std::string(argv[1]) != "selfplay") {
        std::cerr << "usage: selfplay <games> <depth> <seed> <out.csv>\n";
        return 1;
    }

    int games = std::atoi(argv[2]);
    int depth = std::atoi(argv[3]);
    unsigned seed = static_cast<unsigned>(std::atoi(argv[4]));
    std::ofstream out(argv[5]);

    std::mt19937 rng(seed);
    long long positions_written = 0;

    for (int g = 0; g < games; ++g) {
        Board board;
        Engine engine;

        // Randomized opening: 8 random legal plies; discard busted starts.
        bool valid_start = true;

        for (int i = 0; i < 8; ++i) {
            std::vector<Move> legal = board.generate_legal_moves();

            if (legal.empty()) {
                valid_start = false;
                break;
            }

            std::uniform_int_distribution<std::size_t> pick(0, legal.size() - 1);
            board.make_move(legal[pick(rng)]);
        }

        if (!valid_start || std::abs(board.evaluate()) > 200) {
            --g;   // retry with a different random opening
            continue;
        }

        struct Sample {
            std::string fen;
        };

        std::vector<Sample> samples;
        double result = 0.5;
        int max_plies = 300;
        int ply = 0;

        for (; ply < max_plies; ++ply) {
            std::vector<Move> legal = board.generate_legal_moves();

            if (legal.empty()) {
                if (board.in_check(board.side_to_move)) {
                    result = board.side_to_move == WHITE ? 0.0 : 1.0;
                } else {
                    result = 0.5;
                }
                break;
            }

            if (board.halfmove_clock >= 100 || bare_kings(board)
                || board.is_repetition()) {
                result = 0.5;
                break;
            }

            engine.clear_for_new_position();
            SearchResult sr = engine.search_best_move(board, depth, std::nullopt);

            if (!sr.best_move.has_value()) {
                result = 0.5;
                break;
            }

            // Sample quiet positions: past the opening, not in check, the
            // chosen move is not a capture, and the score is not mate-range.
            bool quiet = ply >= 10
                && !board.in_check(board.side_to_move)
                && !is_capture(board, *sr.best_move)
                && std::abs(sr.score) < 2000;

            if (quiet && (ply % 2 == 0 || (rng() & 1))) {
                samples.push_back({board_to_fen(board)});
            }

            board.make_move(*sr.best_move);
        }

        for (const Sample& s : samples) {
            out << s.fen << ";" << result << "\n";
            positions_written += 1;
        }

        if ((g + 1) % 25 == 0) {
            std::cerr << "worker " << seed << ": " << (g + 1) << "/" << games
                      << " games, " << positions_written << " positions\n";
        }
    }

    std::cerr << "worker " << seed << " done: " << positions_written
              << " positions\n";
    return 0;
}
