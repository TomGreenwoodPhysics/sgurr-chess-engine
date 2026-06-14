// Texel tuner for Bitfish.
//
// Build (note: evaluation.cpp is #included, not linked):
//   g++ -std=c++20 -O2 -DTUNING texel_tune.cpp board.cpp -o texel_tune
//
// Usage:
//   ./texel_tune <positions.csv> <mode>
// where mode is "scalars" or "all" (scalars + piece-square tables).
//
// positions.csv lines: "<fen>;<result>" with result 1 / 0.5 / 0 (White POV).
//
// Method (Texel tuning, Österlund 2014): minimise the mean squared error
//   E = mean( (result - sigmoid(K * eval_white / 400))^2 )
// first over the scaling constant K with the current evaluation, then over
// the evaluation parameters by coordinate descent with a shrinking step.

#define TUNING
#include "evaluation.cpp"   // grants direct access to EVAL_PARAM globals

#include "board.hpp"

#include <chrono>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace {

std::vector<Board> g_boards;
std::vector<float> g_results;

// Held-out split: every 10th position is validation, never trained on.
std::vector<std::size_t> g_train;
std::vector<std::size_t> g_valid;

void clear_pawn_cache() {
    pawn_cache.fill(PawnCacheEntry{});
}

int white_eval(const Board& b) {
    int e = b.evaluate();
    return b.side_to_move == WHITE ? e : -e;
}

double sigmoid(double K, int eval_cp) {
    return 1.0 / (1.0 + std::pow(10.0, -K * eval_cp / 400.0));
}

double error_on(const std::vector<std::size_t>& idx, double K) {
    clear_pawn_cache();
    double sum = 0.0;

    for (std::size_t i : idx) {
        double p = sigmoid(K, white_eval(g_boards[i]));
        double d = g_results[i] - p;
        sum += d * d;
    }

    return sum / static_cast<double>(idx.size());
}

// --- K fitting (golden-section on cached evals; params are fixed here) ---

double fit_k() {
    std::vector<int> evals(g_train.size());
    clear_pawn_cache();

    for (std::size_t j = 0; j < g_train.size(); ++j) {
        evals[j] = white_eval(g_boards[g_train[j]]);
    }

    auto err = [&](double K) {
        double sum = 0.0;
        for (std::size_t j = 0; j < g_train.size(); ++j) {
            double p = sigmoid(K, evals[j]);
            double d = g_results[g_train[j]] - p;
            sum += d * d;
        }
        return sum / static_cast<double>(g_train.size());
    };

    double lo = 0.2, hi = 3.0;
    const double phi = (std::sqrt(5.0) - 1.0) / 2.0;

    for (int it = 0; it < 60; ++it) {
        double a = hi - phi * (hi - lo);
        double b = lo + phi * (hi - lo);
        if (err(a) < err(b)) hi = b; else lo = a;
    }

    return (lo + hi) / 2.0;
}

// --- Parameter registry ---

struct Param {
    std::string name;
    int* ptr;
    int* mirror;   // optional second location kept equal (black piece values)
};

std::vector<Param> build_scalar_params() {
    std::vector<Param> ps;

    const char* piece_names[] = {"PAWN", "KNIGHT", "BISHOP", "ROOK", "QUEEN"};

    // Material: knight..queen; pawn stays fixed at 100 as the scale anchor.
    for (int p = 1; p <= 4; ++p) {
        ps.push_back({std::string("PIECE_VALUE_") + piece_names[p],
                      &PIECE_VALUE[p], &PIECE_VALUE[p + 6]});
    }

    for (int r = 1; r <= 6; ++r) {
        ps.push_back({"PASSED_PAWN_BONUS_r" + std::to_string(r + 1),
                      &PASSED_PAWN_BONUS[r], nullptr});
    }

    ps.push_back({"DOUBLED_PAWN_PENALTY", &DOUBLED_PAWN_PENALTY, nullptr});
    ps.push_back({"ISOLATED_PAWN_PENALTY", &ISOLATED_PAWN_PENALTY, nullptr});
    ps.push_back({"BACKWARD_PAWN_PENALTY", &BACKWARD_PAWN_PENALTY, nullptr});
    ps.push_back({"KING_ZONE_PRESSURE_PENALTY", &KING_ZONE_PRESSURE_PENALTY, nullptr});
    ps.push_back({"PRESSURE_PAWN", &PRESSURE_PAWN, nullptr});
    ps.push_back({"PRESSURE_MINOR", &PRESSURE_MINOR, nullptr});
    ps.push_back({"PRESSURE_ROOK", &PRESSURE_ROOK, nullptr});
    ps.push_back({"PRESSURE_QUEEN", &PRESSURE_QUEEN, nullptr});
    ps.push_back({"KING_OPEN_FILE_PENALTY", &KING_OPEN_FILE_PENALTY, nullptr});
    ps.push_back({"ROOK_OPEN_FILE_BONUS", &ROOK_OPEN_FILE_BONUS, nullptr});
    ps.push_back({"ROOK_SEMI_OPEN_FILE_BONUS", &ROOK_SEMI_OPEN_FILE_BONUS, nullptr});
    ps.push_back({"BISHOP_PAIR_BONUS", &BISHOP_PAIR_BONUS, nullptr});
    ps.push_back({"BISHOP_MOBILITY_BONUS", &BISHOP_MOBILITY_BONUS, nullptr});
    ps.push_back({"ROOK_MOBILITY_BONUS", &ROOK_MOBILITY_BONUS, nullptr});
    ps.push_back({"QUEEN_MOBILITY_BONUS", &QUEEN_MOBILITY_BONUS, nullptr});

    return ps;
}

std::vector<Param> build_pst_params() {
    std::vector<Param> ps;
    const char* piece_names[] = {"P", "N", "B", "R", "Q", "K"};

    for (int phase = 0; phase < 2; ++phase) {
        auto& table = phase == 0 ? PIECE_SQUARE_TABLE_MG : PIECE_SQUARE_TABLE_EG;
        const char* tag = phase == 0 ? "MG" : "EG";

        for (int p = 0; p < 6; ++p) {
            for (int sq = 0; sq < 64; ++sq) {
                // Pawns never stand on the first or last rank.
                if (p == 0 && (sq < 8 || sq >= 56)) {
                    continue;
                }
                ps.push_back({std::string("PST_") + tag + "_" + piece_names[p]
                                  + "_" + std::to_string(sq),
                              &table[p][sq], nullptr});
            }
        }
    }

    return ps;
}

void set_param(Param& p, int v) {
    *p.ptr = v;
    if (p.mirror) *p.mirror = v;
}

// --- Coordinate descent ---

void tune(std::vector<Param>& params, double K, const std::vector<int>& steps,
          int max_sweeps_per_step) {
    double best = error_on(g_train, K);
    std::printf("start: train E = %.6f, valid E = %.6f\n",
                best, error_on(g_valid, K));

    for (int step : steps) {
        for (int sweep = 0; sweep < max_sweeps_per_step; ++sweep) {
            bool improved = false;
            auto t0 = std::chrono::steady_clock::now();

            for (Param& p : params) {
                int orig = *p.ptr;

                set_param(p, orig + step);
                double e = error_on(g_train, K);

                if (e + 1e-9 < best) {
                    best = e;
                    improved = true;
                    continue;
                }

                set_param(p, orig - step);
                e = error_on(g_train, K);

                if (e + 1e-9 < best) {
                    best = e;
                    improved = true;
                    continue;
                }

                set_param(p, orig);
            }

            auto t1 = std::chrono::steady_clock::now();
            double secs = std::chrono::duration<double>(t1 - t0).count();
            std::printf("step %2d sweep %d: train E = %.6f, valid E = %.6f"
                        "  (%.0fs)\n",
                        step, sweep, best, error_on(g_valid, K), secs);
            std::fflush(stdout);

            if (!improved) break;
        }
    }
}

void dump_params(const std::vector<Param>& params) {
    std::printf("\n=== tuned values ===\n");
    for (const Param& p : params) {
        std::printf("%s = %d\n", p.name.c_str(), *p.ptr);
    }
}

void dump_psts() {
    for (int phase = 0; phase < 2; ++phase) {
        auto& table = phase == 0 ? PIECE_SQUARE_TABLE_MG : PIECE_SQUARE_TABLE_EG;
        const char* names[] = {"PAWN", "KNIGHT", "BISHOP", "ROOK", "QUEEN", "KING"};

        for (int p = 0; p < 6; ++p) {
            std::printf("\n// %s_%s\n", names[p], phase == 0 ? "PST" : "PST_EG");
            for (int r = 0; r < 8; ++r) {
                std::printf("    ");
                for (int f = 0; f < 8; ++f) {
                    std::printf("%4d,", table[p][r * 8 + f]);
                }
                std::printf("\n");
            }
        }
    }
}

} // namespace

int main(int argc, char* argv[]) {
    if (argc < 3) {
        std::cerr << "usage: texel_tune <positions.csv> <scalars|all>\n";
        return 1;
    }

    std::string mode = argv[2];
    std::ifstream in(argv[1]);
    std::string line;

    while (std::getline(in, line)) {
        auto semi = line.rfind(';');
        if (semi == std::string::npos) continue;

        Board b;
        b.set_fen(line.substr(0, semi));

        g_boards.push_back(b);
        g_results.push_back(std::stof(line.substr(semi + 1)));
    }

    for (std::size_t i = 0; i < g_boards.size(); ++i) {
        (i % 10 == 9 ? g_valid : g_train).push_back(i);
    }

    std::printf("loaded %zu positions (%zu train, %zu valid)\n",
                g_boards.size(), g_train.size(), g_valid.size());

    double K = fit_k();
    std::printf("fitted K = %.4f\n", K);

    auto scalars = build_scalar_params();
    tune(scalars, K, {8, 4, 2, 1}, 20);
    dump_params(scalars);

    if (mode == "all") {
        auto psts = build_pst_params();
        tune(psts, K, {8, 4, 2, 1}, 6);
        dump_psts();
        // Re-tune scalars once more: PST shifts change their optimum.
        tune(scalars, K, {2, 1}, 10);
        dump_params(scalars);
    }

    std::fflush(stdout);
    return 0;
}
