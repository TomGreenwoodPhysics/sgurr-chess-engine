// PGN -> Texel position extractor for Bitfish.
//
// Build:
//   g++ -std=c++20 -O2 pgn_extract.cpp board.cpp evaluation.cpp -o pgn_extract
//
// Usage:
//   ./pgn_extract <games.pgn> <out.csv>
//
// Reads a PGN, replays each game using Bitfish's own legal-move generator to
// resolve SAN, and writes quiet positions as "fen;result" (White POV: 1 / 0.5
// / 0). "Quiet" here matches the self-play generator: past the opening, side
// to move not in check, and the move actually played is not a capture. This
// keeps the PGN-derived positions distributionally consistent with the
// self-play set they are merged with.

#include "board.hpp"

#include <cctype>
#include <fstream>
#include <iostream>
#include <optional>
#include <sstream>
#include <string>
#include <vector>

namespace {

std::string square_to_name(int sq) {
    std::string s;
    s += static_cast<char>('a' + (sq % 8));
    s += static_cast<char>('1' + (sq / 8));
    return s;
}

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
            if (empty > 0) { fen << empty; empty = 0; }
            fen << "PNBRQKpnbrqk"[*piece];
        }
        if (empty > 0) fen << empty;
        if (rank > 0) fen << "/";
    }

    fen << (board.side_to_move == WHITE ? " w " : " b ");
    fen << (board.castling.empty() ? "-" : board.castling) << " ";
    fen << (board.en_passant.has_value() ? square_name(*board.en_passant) : "-");
    fen << " " << board.halfmove_clock << " " << board.fullmove_number;
    return fen.str();
}

bool is_capture(const Board& board, const Move& move) {
    return board.piece_at(move.to_sq).has_value() || move.is_en_passant;
}

// Render a move the way SAN would name its essentials, then match by string.
// Rather than generate SAN (disambiguation is fiddly), we go the robust way:
// for the SAN token, derive (destination, piece, promotion, castle) and find
// the unique legal move that fits.

char piece_letter(const Board& board, int from_sq) {
    std::optional<int> p = board.piece_at(from_sq);
    if (!p.has_value()) return '?';
    int t = *p % 6;
    return "PNBRQK"[t];
}

std::string strip_san(const std::string& raw) {
    std::string s;
    for (char c : raw) {
        if (c == '+' || c == '#' || c == '!' || c == '?') continue;
        s += c;
    }
    return s;
}

// Find the legal move matching a SAN token in the current position.
std::optional<Move> match_san(Board& board, const std::string& san_raw) {
    std::string san = strip_san(san_raw);
    if (san.empty()) return std::nullopt;

    std::vector<Move> legal = board.generate_legal_moves();

    // Castling.
    if (san == "O-O" || san == "0-0" || san == "O-O-O" || san == "0-0-0") {
        bool queenside = (san.size() == 5);
        for (const Move& m : legal) {
            if (!m.is_castling) continue;
            int df = m.to_sq % 8;
            bool mq = df < 4;
            if (mq == queenside) return m;
        }
        return std::nullopt;
    }

    // Promotion suffix, e.g. e8=Q.
    char promo = 0;
    auto eq = san.find('=');
    if (eq != std::string::npos && eq + 1 < san.size()) {
        promo = san[eq + 1];
        san = san.substr(0, eq);
    }

    // Piece type: leading uppercase among NBRQK, else pawn.
    char piece = 'P';
    std::size_t idx = 0;
    if (!san.empty() && std::string("NBRQK").find(san[0]) != std::string::npos) {
        piece = san[0];
        idx = 1;
    }

    // Destination is the last two chars that form a square.
    if (san.size() < 2) return std::nullopt;
    std::string dest = san.substr(san.size() - 2);
    int dest_sq = (dest[0] - 'a') + (dest[1] - '1') * 8;

    // Disambiguation hints between piece letter and destination.
    std::string middle = san.substr(idx, san.size() - 2 - idx);
    int dis_file = -1, dis_rank = -1;
    for (char c : middle) {
        if (c >= 'a' && c <= 'h') dis_file = c - 'a';
        else if (c >= '1' && c <= '8') dis_rank = c - '1';
    }

    for (const Move& m : legal) {
        if (m.to_sq != dest_sq) continue;
        if (piece_letter(board, m.from_sq) != piece) continue;
        if (dis_file != -1 && (m.from_sq % 8) != dis_file) continue;
        if (dis_rank != -1 && (m.from_sq / 8) != dis_rank) continue;
        if (promo) {
            if (!m.promotion) continue;
            char mp = "PNBRQK"[*m.promotion % 6];
            if (mp != promo) continue;
        }
        return m;
    }
    return std::nullopt;
}

} // namespace

int main(int argc, char* argv[]) {
    if (argc < 3) {
        std::cerr << "usage: pgn_extract <games.pgn> <out.csv>\n";
        return 1;
    }

    std::ifstream in(argv[1]);
    std::ofstream out(argv[2]);
    std::string line;

    std::string movetext;
    double result = -1.0;
    long long games = 0, positions = 0, failed = 0;

    auto flush_game = [&]() {
        if (movetext.empty() || result < 0) { movetext.clear(); result = -1; return; }

        Board board;
        board.set_fen(START_FEN);

        std::istringstream ms(movetext);
        std::string tok;
        int ply = 0;
        bool ok = true;

        std::vector<std::string> fens;

        while (ms >> tok) {
            // Drop move numbers like "12." and result tokens.
            if (tok == "1-0" || tok == "0-1" || tok == "1/2-1/2" || tok == "*") break;
            auto dot = tok.find('.');
            if (dot != std::string::npos) tok = tok.substr(dot + 1);
            if (tok.empty()) continue;

            std::optional<Move> mv = match_san(board, tok);
            if (!mv.has_value()) { ok = false; break; }

            bool quiet = ply >= 10
                && !board.in_check(board.side_to_move)
                && !is_capture(board, *mv);
            if (quiet) fens.push_back(board_to_fen(board));

            board.make_move(*mv);
            ply += 1;
        }

        if (ok) {
            for (const std::string& f : fens) {
                out << f << ";" << result << "\n";
                positions += 1;
            }
            games += 1;
        } else {
            failed += 1;
        }

        movetext.clear();
        result = -1;
    };

    while (std::getline(in, line)) {
        if (!line.empty() && line[0] == '[') {
            if (line.rfind("[Result ", 0) == 0) {
                // New game header begins; flush the previous game first.
                flush_game();
                if (line.find("\"1-0\"") != std::string::npos) result = 1.0;
                else if (line.find("\"0-1\"") != std::string::npos) result = 0.0;
                else if (line.find("\"1/2-1/2\"") != std::string::npos) result = 0.5;
                else result = -1.0;
            }
            continue;
        }
        if (!line.empty()) movetext += " " + line;
    }
    flush_game();   // last game

    std::cerr << "games parsed: " << games << ", failed: " << failed
              << ", positions: " << positions << "\n";
    return 0;
}
