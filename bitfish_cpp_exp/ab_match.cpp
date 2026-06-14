// A/B validation match for Bitfish Texel tuning.
//
// Build (TUNING exposes the eval globals; we include evaluation.cpp directly):
//   g++ -std=c++20 -O2 -DTUNING ab_match.cpp board.cpp search.cpp -o ab_match
//
// Usage:
//   ./ab_match <tuned_params.txt> <games> <depth> <seed>
//
// Plays <games> pairs of games from randomized openings. In each pair the two
// sides swap colours, so opening luck cancels. "A" uses the tuned parameters
// loaded from file; "B" uses the engine's default (compiled-in) values. Before
// each search we install the right parameter set into the mutable globals, so
// both players use the identical search and differ only in evaluation.
//
// Reports A's score and a rough Elo delta with an approximate error margin.

// (TUNING is provided on the compile command line via -DTUNING)
#include "evaluation.cpp"

#include "board.hpp"
#include "search.hpp"

#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <map>
#include <random>
#include <sstream>
#include <string>
#include <vector>

namespace {

// Snapshot of every tunable parameter, so we can swap A/B sets per move.
struct ParamSet {
    std::array<int, 12> piece_value;
    std::array<std::array<int, 64>, 6> pst_mg;
    std::array<std::array<int, 64>, 6> pst_eg;
    std::array<int, 8> passed_pawn;
    int doubled, isolated, backward;
    int kzpp, p_pawn, p_minor, p_rook, p_queen;
    int king_open_file, rook_open, rook_semi, bishop_pair;
    int bishop_mob, rook_mob, queen_mob;
};

ParamSet capture_current() {
    ParamSet s;
    s.piece_value = PIECE_VALUE;
    s.pst_mg = PIECE_SQUARE_TABLE_MG;
    s.pst_eg = PIECE_SQUARE_TABLE_EG;
    s.passed_pawn = PASSED_PAWN_BONUS;
    s.doubled = DOUBLED_PAWN_PENALTY;
    s.isolated = ISOLATED_PAWN_PENALTY;
    s.backward = BACKWARD_PAWN_PENALTY;
    s.kzpp = KING_ZONE_PRESSURE_PENALTY;
    s.p_pawn = PRESSURE_PAWN; s.p_minor = PRESSURE_MINOR;
    s.p_rook = PRESSURE_ROOK; s.p_queen = PRESSURE_QUEEN;
    s.king_open_file = KING_OPEN_FILE_PENALTY;
    s.rook_open = ROOK_OPEN_FILE_BONUS; s.rook_semi = ROOK_SEMI_OPEN_FILE_BONUS;
    s.bishop_pair = BISHOP_PAIR_BONUS;
    s.bishop_mob = BISHOP_MOBILITY_BONUS; s.rook_mob = ROOK_MOBILITY_BONUS;
    s.queen_mob = QUEEN_MOBILITY_BONUS;
    return s;
}

void install(const ParamSet& s) {
    PIECE_VALUE = s.piece_value;
    PIECE_SQUARE_TABLE_MG = s.pst_mg;
    PIECE_SQUARE_TABLE_EG = s.pst_eg;
    PASSED_PAWN_BONUS = s.passed_pawn;
    DOUBLED_PAWN_PENALTY = s.doubled;
    ISOLATED_PAWN_PENALTY = s.isolated;
    BACKWARD_PAWN_PENALTY = s.backward;
    KING_ZONE_PRESSURE_PENALTY = s.kzpp;
    PRESSURE_PAWN = s.p_pawn; PRESSURE_MINOR = s.p_minor;
    PRESSURE_ROOK = s.p_rook; PRESSURE_QUEEN = s.p_queen;
    KING_OPEN_FILE_PENALTY = s.king_open_file;
    ROOK_OPEN_FILE_BONUS = s.rook_open; ROOK_SEMI_OPEN_FILE_BONUS = s.rook_semi;
    BISHOP_PAIR_BONUS = s.bishop_pair;
    BISHOP_MOBILITY_BONUS = s.bishop_mob; ROOK_MOBILITY_BONUS = s.rook_mob;
    QUEEN_MOBILITY_BONUS = s.queen_mob;
}

// Apply tuned values from texel_tune output onto a copy of the defaults.
// Recognises the "NAME = value" scalar lines and the PST comment+grid blocks.
ParamSet load_tuned(const std::string& path, const ParamSet& base) {
    ParamSet s = base;
    std::ifstream in(path);
    std::string line;

    std::map<std::string, int*> scalar = {
        {"DOUBLED_PAWN_PENALTY", &s.doubled},
        {"ISOLATED_PAWN_PENALTY", &s.isolated},
        {"BACKWARD_PAWN_PENALTY", &s.backward},
        {"KING_ZONE_PRESSURE_PENALTY", &s.kzpp},
        {"PRESSURE_PAWN", &s.p_pawn}, {"PRESSURE_MINOR", &s.p_minor},
        {"PRESSURE_ROOK", &s.p_rook}, {"PRESSURE_QUEEN", &s.p_queen},
        {"KING_OPEN_FILE_PENALTY", &s.king_open_file},
        {"ROOK_OPEN_FILE_BONUS", &s.rook_open},
        {"ROOK_SEMI_OPEN_FILE_BONUS", &s.rook_semi},
        {"BISHOP_PAIR_BONUS", &s.bishop_pair},
        {"BISHOP_MOBILITY_BONUS", &s.bishop_mob},
        {"ROOK_MOBILITY_BONUS", &s.rook_mob},
        {"QUEEN_MOBILITY_BONUS", &s.queen_mob},
    };
    std::map<std::string, int> piece_idx = {
        {"PIECE_VALUE_KNIGHT", 1}, {"PIECE_VALUE_BISHOP", 2},
        {"PIECE_VALUE_ROOK", 3}, {"PIECE_VALUE_QUEEN", 4},
    };

    // PST grid parsing state.
    int pst_piece = -1, pst_phase = -1, pst_row = 0;

    auto parse_pst_header = [&](const std::string& l) {
        // e.g. "// KNIGHT_PST_EG" or "// PAWN_PST"
        static const char* names[] = {"PAWN","KNIGHT","BISHOP","ROOK","QUEEN","KING"};
        for (int p = 0; p < 6; ++p) {
            std::string n = names[p];
            if (l.find(n + "_PST_EG") != std::string::npos) {
                pst_piece = p; pst_phase = 1; pst_row = 0; return true;
            }
            if (l.find(n + "_PST") != std::string::npos) {
                pst_piece = p; pst_phase = 0; pst_row = 0; return true;
            }
        }
        return false;
    };

    while (std::getline(in, line)) {
        if (line.rfind("// ", 0) == 0) {
            if (parse_pst_header(line)) continue;
        }

        // PST data row: comma-separated ints, no '='.
        if (pst_piece >= 0 && pst_row < 8 && line.find('=') == std::string::npos
            && line.find(',') != std::string::npos) {
            std::stringstream ss(line);
            std::string cell;
            int col = 0;
            while (std::getline(ss, cell, ',') && col < 8) {
                // strip spaces
                std::string num;
                for (char c : cell) if (c == '-' || std::isdigit(c)) num += c;
                if (!num.empty()) {
                    int sq = pst_row * 8 + col;
                    if (pst_phase == 0) s.pst_mg[pst_piece][sq] = std::stoi(num);
                    else s.pst_eg[pst_piece][sq] = std::stoi(num);
                    col += 1;
                }
            }
            pst_row += 1;
            continue;
        }

        auto eq = line.find('=');
        if (eq == std::string::npos) continue;
        std::string name = line.substr(0, eq);
        // trim
        while (!name.empty() && name.back() == ' ') name.pop_back();
        int val = std::atoi(line.substr(eq + 1).c_str());

        if (scalar.count(name)) { *scalar[name] = val; continue; }
        if (piece_idx.count(name)) {
            int i = piece_idx[name];
            s.piece_value[i] = val;
            s.piece_value[i + 6] = val;
            continue;
        }
        if (name.rfind("PASSED_PAWN_BONUS_r", 0) == 0) {
            int r = std::atoi(name.substr(19).c_str());
            if (r >= 2 && r <= 7) s.passed_pawn[r - 1] = val;
        }
    }
    return s;
}

bool bare_kings(const Board& b) {
    return b.occupancy() == (b.bitboards[WK] | b.bitboards[BK]);
}

// Play one game; A_is_white decides which colour the tuned set plays.
// Returns A's score: 1.0 win, 0.5 draw, 0.0 loss.
double play_game(const ParamSet& A, const ParamSet& B, bool A_is_white,
                 const std::vector<Move>& opening, int depth) {
    Board board;
    Engine eng_w, eng_b;

    for (const Move& m : opening) board.make_move(m);

    int ply = 0;
    while (ply < 300) {
        std::vector<Move> legal = board.generate_legal_moves();
        if (legal.empty()) {
            if (board.in_check(board.side_to_move))
                return (board.side_to_move == WHITE) == A_is_white ? 0.0 : 1.0;
            return 0.5;
        }
        if (board.halfmove_clock >= 100 || bare_kings(board)
            || board.is_repetition())
            return 0.5;

        bool white_to_move = board.side_to_move == WHITE;
        bool tuned_to_move = (white_to_move == A_is_white);
        install(tuned_to_move ? A : B);

        Engine& eng = white_to_move ? eng_w : eng_b;
        eng.clear_for_new_position();
        SearchResult sr = eng.search_best_move(board, depth, std::nullopt);
        if (!sr.best_move) return 0.5;
        board.make_move(*sr.best_move);
        ply += 1;
    }
    return 0.5;
}

} // namespace

int main(int argc, char* argv[]) {
    if (argc < 5) {
        std::cerr << "usage: ab_match <tuned_params.txt> <pairs> <depth> <seed>\n";
        return 1;
    }

    ParamSet base = capture_current();
    ParamSet tuned = load_tuned(argv[1], base);
    int pairs = std::atoi(argv[2]);
    int depth = std::atoi(argv[3]);
    std::mt19937 rng(std::atoi(argv[4]));

    double a_score = 0.0;
    int wins = 0, draws = 0, losses = 0;

    for (int g = 0; g < pairs; ++g) {
        // Build one random opening; reuse it for both colour assignments.
        install(base);
        Board ob;
        std::vector<Move> opening;
        bool ok = true;
        for (int i = 0; i < 8; ++i) {
            std::vector<Move> legal = ob.generate_legal_moves();
            if (legal.empty()) { ok = false; break; }
            std::uniform_int_distribution<std::size_t> pick(0, legal.size() - 1);
            Move m = legal[pick(rng)];
            opening.push_back(m);
            ob.make_move(m);
        }
        if (!ok || std::abs(ob.evaluate()) > 200) { --g; continue; }

        double s1 = play_game(tuned, base, true, opening, depth);
        double s2 = play_game(tuned, base, false, opening, depth);

        for (double s : {s1, s2}) {
            a_score += s;
            if (s == 1.0) wins++; else if (s == 0.5) draws++; else losses++;
        }

        if ((g + 1) % 10 == 0) {
            int n = (g + 1) * 2;
            std::cerr << (g + 1) << " pairs: A " << a_score << "/" << n
                      << " (+" << wins << " =" << draws << " -" << losses << ")\n";
        }
    }

    int n = pairs * 2;
    double rate = a_score / n;
    double elo = (rate <= 0 || rate >= 1) ? 0.0
                 : -400.0 * std::log10(1.0 / rate - 1.0);
    double margin = 800.0 / std::sqrt(static_cast<double>(n));  // rough 1-sigma

    std::cout << "\nTuned (A) vs default (B): " << a_score << "/" << n
              << " = " << (rate * 100.0) << "%\n";
    std::cout << "+" << wins << " =" << draws << " -" << losses << "\n";
    std::cout << "Elo delta (A - B): " << elo
              << " +/- ~" << margin << " (1 sigma)\n";
    return 0;
}
