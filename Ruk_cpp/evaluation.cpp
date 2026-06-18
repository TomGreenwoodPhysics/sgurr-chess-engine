#include "evaluation.hpp"

#include <array>
#include <bit>
#include <cmath>
#include <vector>

namespace {

// Tunable evaluation parameters. In the normal engine build EVAL_PARAM is
// constexpr (identical codegen to before). The Texel tuner compiles this
// translation unit with -DTUNING, which makes the marked parameters mutable
// so they can be adjusted at runtime.
#ifdef TUNING
#define EVAL_PARAM
#else
#define EVAL_PARAM constexpr
#endif

EVAL_PARAM std::array<int, 12> PIECE_VALUE = {
    100, 377, 369, 550, 1155, 0,
    100, 377, 369, 550, 1155, 0
};

constexpr std::array<int, 64> PAWN_PST = {
     0,   0,   0,   0,   0,   0,   0,   0,
     0,   2,   4, -10, -10,   4,   2,   0,
     2,   2,   6,  10,  10,   6,   2,   2,
     4,   4,  10,  22,  22,  10,   4,   4,
     8,   8,  16,  28,  28,  16,   8,   8,
    16,  16,  24,  32,  32,  24,  16,  16,
    45,  45,  45,  45,  45,  45,  45,  45,
     0,   0,   0,   0,   0,   0,   0,   0
};

constexpr std::array<int, 64> KNIGHT_PST = {
   -50, -30, -20, -15, -15, -20, -30, -50,
   -25, -12,   0,   5,   5,   0, -12, -25,
   -15,   8,  18,  22,  22,  18,   8, -15,
   -10,  10,  25,  32,  32,  25,  10, -10,
   -10,  12,  28,  35,  35,  28,  12, -10,
   -15,  10,  20,  28,  28,  20,  10, -15,
   -20, -10,   8,  12,  12,   8, -10, -20,
   -45, -25, -15, -10, -10, -15, -25, -45
};

constexpr std::array<int, 64> BISHOP_PST = {
   -20, -10, -15, -10, -10, -15, -10, -20,
   -10,  12,   8,   8,   8,   8,  12, -10,
   -10,  16,  14,  16,  16,  14,  16, -10,
   -10,  10,  18,  22,  22,  18,  10, -10,
   -10,   8,  18,  22,  22,  18,   8, -10,
   -10,  10,  14,  18,  18,  14,  10, -10,
   -10,   8,   4,   8,   8,   4,   8, -10,
   -20, -10, -10, -10, -10, -10, -10, -20
};

constexpr std::array<int, 64> ROOK_PST = {
     0,   0,   4,   8,   8,   4,   0,   0,
    12,  16,  16,  20,  20,  16,  16,  12,
    -4,   0,   4,   8,   8,   4,   0,  -4,
    -8,  -4,   0,   4,   4,   0,  -4,  -8,
    -8,  -4,   0,   4,   4,   0,  -4,  -8,
    -8,  -4,   0,   4,   4,   0,  -4,  -8,
    -4,   0,   4,   8,   8,   4,   0,  -4,
     0,   0,   4,   8,   8,   4,   0,   0
};

constexpr std::array<int, 64> QUEEN_PST = {
   -20, -10, -10,  -5,  -5, -10, -10, -20,
   -10,   0,   8,   4,   4,   4,   0, -10,
   -10,   8,   8,   8,   8,   8,   4, -10,
     0,   4,   8,  10,  10,   8,   4,  -5,
    -5,   4,   8,  10,  10,   8,   4,  -5,
   -10,   4,   8,   8,   8,   8,   4, -10,
   -10,   0,   4,   4,   4,   4,   0, -10,
   -20, -10, -10,  -5,  -5, -10, -10, -20
};

constexpr std::array<int, 64> KING_PST = {
    40,  50,  30,   0,   0,  30,  50,  40,
    30,  40,  20,   0,   0,  20,  40,  30,
    10,  10, -10, -20, -20, -10,  10,  10,
   -20, -20, -30, -40, -40, -30, -20, -20,
   -30, -30, -40, -50, -50, -40, -30, -30,
   -30, -30, -40, -50, -50, -40, -30, -30,
   -30, -30, -40, -50, -50, -40, -30, -30,
   -30, -30, -40, -50, -50, -40, -30, -30
};

constexpr std::array<int, 64> PAWN_PST_EG = {
     0,   0,   0,   0,   0,   0,   0,   0,
     2,   2,   2,   2,   2,   2,   2,   2,
     6,   6,   6,   6,   6,   6,   6,   6,
    16,  14,  12,  12,  12,  12,  14,  16,
    32,  28,  25,  22,  22,  25,  28,  32,
    60,  55,  50,  45,  45,  50,  55,  60,
   110, 105, 100,  95,  95, 100, 105, 110,
     0,   0,   0,   0,   0,   0,   0,   0
};

constexpr std::array<int, 64> KNIGHT_PST_EG = {
   -40, -25, -18, -12, -12, -18, -25, -40,
   -25, -12,   0,   5,   5,   0, -12, -25,
   -18,   0,  10,  15,  15,  10,   0, -18,
   -12,   5,  15,  22,  22,  15,   5, -12,
   -12,   5,  15,  22,  22,  15,   5, -12,
   -18,   0,  10,  15,  15,  10,   0, -18,
   -25, -12,   0,   5,   5,   0, -12, -25,
   -40, -25, -18, -12, -12, -18, -25, -40
};

constexpr std::array<int, 64> BISHOP_PST_EG = {
   -15,  -8,  -6,  -4,  -4,  -6,  -8, -15,
    -8,   0,   2,   4,   4,   2,   0,  -8,
    -6,   2,   6,   8,   8,   6,   2,  -6,
    -4,   4,   8,  12,  12,   8,   4,  -4,
    -4,   4,   8,  12,  12,   8,   4,  -4,
    -6,   2,   6,   8,   8,   6,   2,  -6,
    -8,   0,   2,   4,   4,   2,   0,  -8,
   -15,  -8,  -6,  -4,  -4,  -6,  -8, -15
};

constexpr std::array<int, 64> ROOK_PST_EG = {
     0,   0,   0,   0,   0,   0,   0,   0,
     2,   2,   2,   2,   2,   2,   2,   2,
     2,   2,   2,   2,   2,   2,   2,   2,
     2,   2,   2,   2,   2,   2,   2,   2,
     2,   2,   2,   2,   2,   2,   2,   2,
     4,   4,   4,   4,   4,   4,   4,   4,
    10,  10,  10,  10,  10,  10,  10,  10,
     4,   4,   4,   4,   4,   4,   4,   4
};

constexpr std::array<int, 64> QUEEN_PST_EG = {
   -20, -12,  -8,  -5,  -5,  -8, -12, -20,
   -12,  -4,   0,   2,   2,   0,  -4, -12,
    -8,   0,   6,  10,  10,   6,   0,  -8,
    -5,   2,  10,  14,  14,  10,   2,  -5,
    -5,   2,  10,  14,  14,  10,   2,  -5,
    -8,   0,   6,  10,  10,   6,   0,  -8,
   -12,  -4,   0,   2,   2,   0,  -4, -12,
   -20, -12,  -8,  -5,  -5,  -8, -12, -20
};

constexpr std::array<int, 64> KING_PST_EG = {
   -50, -35, -25, -20, -20, -25, -35, -50,
   -30, -15,  -5,   0,   0,  -5, -15, -30,
   -20,  -5,  10,  18,  18,  10,  -5, -20,
   -15,   0,  18,  28,  28,  18,   0, -15,
   -15,   0,  18,  28,  28,  18,   0, -15,
   -20,  -5,  10,  18,  18,  10,  -5, -20,
   -30, -15,  -5,   0,   0,  -5, -15, -30,
   -50, -35, -25, -20, -20, -25, -35, -50
};

EVAL_PARAM std::array<std::array<int, 64>, 6> PIECE_SQUARE_TABLE_MG = {
    PAWN_PST,
    KNIGHT_PST,
    BISHOP_PST,
    ROOK_PST,
    QUEEN_PST,
    KING_PST
};

EVAL_PARAM std::array<std::array<int, 64>, 6> PIECE_SQUARE_TABLE_EG = {
    PAWN_PST_EG,
    KNIGHT_PST_EG,
    BISHOP_PST_EG,
    ROOK_PST_EG,
    QUEEN_PST_EG,
    KING_PST_EG
};

constexpr int PHASE_KNIGHT = 1;
constexpr int PHASE_BISHOP = 1;
constexpr int PHASE_ROOK = 2;
constexpr int PHASE_QUEEN = 4;
constexpr int PHASE_MAX = 24;

constexpr int OPENING_MAX_FULLMOVE = 3;
constexpr int OPENING_MIN_NON_PAWN_MATERIAL = 5200;

constexpr int OPENING_CENTRE_PAWN_BONUS = 22;
constexpr int OPENING_KINGSIDE_KNIGHT_BONUS = 18;
constexpr int OPENING_QUEENSIDE_KNIGHT_BONUS = 8;
constexpr int OPENING_BISHOP_DEVELOPMENT_BONUS = 5;
constexpr int OPENING_CASTLED_BONUS = 25;

EVAL_PARAM std::array<int, 8> PASSED_PAWN_BONUS = {
    0, -4, 14, 25, 51, 83, 94, 0
};

EVAL_PARAM int DOUBLED_PAWN_PENALTY = 23;
EVAL_PARAM int ISOLATED_PAWN_PENALTY = 17;
EVAL_PARAM int BACKWARD_PAWN_PENALTY = 11;

EVAL_PARAM int KING_ZONE_PRESSURE_PENALTY = 2;
EVAL_PARAM int PRESSURE_PAWN = -10;
EVAL_PARAM int PRESSURE_MINOR = 2;
EVAL_PARAM int PRESSURE_ROOK = 4;
EVAL_PARAM int PRESSURE_QUEEN = 7;
EVAL_PARAM int KING_OPEN_FILE_PENALTY = 11;

EVAL_PARAM int ROOK_OPEN_FILE_BONUS = 49;
EVAL_PARAM int ROOK_SEMI_OPEN_FILE_BONUS = 27;
EVAL_PARAM int BISHOP_PAIR_BONUS = 82;

EVAL_PARAM int BISHOP_MOBILITY_BONUS = 3;
EVAL_PARAM int ROOK_MOBILITY_BONUS = 4;
EVAL_PARAM int QUEEN_MOBILITY_BONUS = 3;

const std::vector<int> BISHOP_DELTAS = {9, 7, -9, -7};
const std::vector<int> ROOK_DELTAS = {8, -8, 1, -1};
const std::vector<int> QUEEN_DELTAS = {9, 7, -9, -7, 8, -8, 1, -1};

U64 file_mask(int file) {
    U64 mask = 0;

    for (int rank = 0; rank < 8; ++rank) {
        mask |= bit(rank * 8 + file);
    }

    return mask;
}

U64 adjacent_file_mask(int file) {
    U64 mask = 0;

    if (file > 0) {
        mask |= file_mask(file - 1);
    }

    if (file < 7) {
        mask |= file_mask(file + 1);
    }

    return mask;
}

int count_bits(U64 bb) {
    return static_cast<int>(std::popcount(bb));
}

constexpr int MOP_UP_EDGE_BONUS = 30;
constexpr int MOP_UP_KING_CLOSE_BONUS = 60;

int centre_manhattan_distance(int sq) {
    int f = file_of(sq);
    int r = rank_of(sq);
    int fd = std::max(3 - f, f - 4);
    int rd = std::max(3 - r, r - 4);
    return fd + rd;
}

int king_manhattan_distance(int a, int b) {
    return std::abs(file_of(a) - file_of(b)) + std::abs(rank_of(a) - rank_of(b));
}

} // namespace

int Board::game_phase() const {
    int phase =
        (count_bits(bitboards[WN]) + count_bits(bitboards[BN])) * PHASE_KNIGHT +
        (count_bits(bitboards[WB]) + count_bits(bitboards[BB])) * PHASE_BISHOP +
        (count_bits(bitboards[WR]) + count_bits(bitboards[BR])) * PHASE_ROOK +
        (count_bits(bitboards[WQ]) + count_bits(bitboards[BQ])) * PHASE_QUEEN;

    // Promotions can push the raw phase above the opening value; clamp.
    return std::min(phase, PHASE_MAX);
}

int Board::evaluate_fast() const {
    int material = 0;
    int mg = 0;
    int eg = 0;

    for (int piece = 0; piece < 12; ++piece) {
        U64 bb = bitboards[piece];

        if (piece <= WK) {
            const auto& pst_mg = PIECE_SQUARE_TABLE_MG[piece];
            const auto& pst_eg = PIECE_SQUARE_TABLE_EG[piece];
            int value = PIECE_VALUE[piece];

            while (bb) {
                auto [sq, next] = pop_lsb(bb);
                bb = next;
                material += value;
                mg += pst_mg[sq];
                eg += pst_eg[sq];
            }
        } else {
            const auto& pst_mg = PIECE_SQUARE_TABLE_MG[piece - 6];
            const auto& pst_eg = PIECE_SQUARE_TABLE_EG[piece - 6];
            int value = PIECE_VALUE[piece];

            while (bb) {
                auto [sq, next] = pop_lsb(bb);
                bb = next;
                int msq = mirror_square(sq);
                material -= value;
                mg -= pst_mg[msq];
                eg -= pst_eg[msq];
            }
        }
    }

    int phase = game_phase();
    int pst = (mg * phase + eg * (PHASE_MAX - phase)) / PHASE_MAX;
    int score = material + pst;

    return side_to_move == WHITE ? score : -score;
}

int Board::evaluate_quiet() const {
    // Stand-pat must use the full evaluation: quiescence terminates almost
    // every search line, so whatever this returns IS the engine's effective
    // positional knowledge. Routing it to material+PST only made pawn
    // structure, king safety, mobility and mop-up invisible to the search.
    return evaluate();
}

int Board::non_pawn_material_total() const {
    int total = 0;

    for (int piece : {WN, WB, WR, WQ, BN, BB, BR, BQ}) {
        total += PIECE_VALUE[piece] * count_bits(bitboards[piece]);
    }

    return total;
}

bool Board::opening_phase_active() const {
    if (fullmove_number > OPENING_MAX_FULLMOVE) {
        return false;
    }

    return non_pawn_material_total() >= OPENING_MIN_NON_PAWN_MATERIAL;
}

int Board::evaluate_opening_principles_for_colour(int colour) const {
    U64 pawns;
    U64 knights;
    U64 bishops;
    U64 king;

    int centre_one;
    int centre_two;
    int kingside_knight_square;
    int queenside_knight_square;
    int bishop_home_one;
    int bishop_home_two;
    int castled_king_one;
    int castled_king_two;

    if (colour == WHITE) {
        pawns = bitboards[WP];
        knights = bitboards[WN];
        bishops = bitboards[WB];
        king = bitboards[WK];

        centre_one = square_index("d4");
        centre_two = square_index("e4");
        kingside_knight_square = square_index("f3");
        queenside_knight_square = square_index("c3");
        bishop_home_one = square_index("c1");
        bishop_home_two = square_index("f1");
        castled_king_one = square_index("g1");
        castled_king_two = square_index("c1");
    } else {
        pawns = bitboards[BP];
        knights = bitboards[BN];
        bishops = bitboards[BB];
        king = bitboards[BK];

        centre_one = square_index("d5");
        centre_two = square_index("e5");
        kingside_knight_square = square_index("f6");
        queenside_knight_square = square_index("c6");
        bishop_home_one = square_index("c8");
        bishop_home_two = square_index("f8");
        castled_king_one = square_index("g8");
        castled_king_two = square_index("c8");
    }

    int score = 0;

    if (pawns & bit(centre_one)) {
        score += OPENING_CENTRE_PAWN_BONUS;
    }

    if (pawns & bit(centre_two)) {
        score += OPENING_CENTRE_PAWN_BONUS;
    }

    if (knights & bit(kingside_knight_square)) {
        score += OPENING_KINGSIDE_KNIGHT_BONUS;
    }

    if (knights & bit(queenside_knight_square)) {
        score += OPENING_QUEENSIDE_KNIGHT_BONUS;
    }

    if (!(bishops & bit(bishop_home_one))) {
        score += OPENING_BISHOP_DEVELOPMENT_BONUS;
    }

    if (!(bishops & bit(bishop_home_two))) {
        score += OPENING_BISHOP_DEVELOPMENT_BONUS;
    }

    if ((king & bit(castled_king_one)) || (king & bit(castled_king_two))) {
        score += OPENING_CASTLED_BONUS;
    }

    return score;
}

int Board::evaluate_opening_principles() const {
    if (!opening_phase_active()) {
        return 0;
    }

    return evaluate_opening_principles_for_colour(WHITE)
         - evaluate_opening_principles_for_colour(BLACK);
}

int Board::evaluate_pawn_structure_for_colour(int colour) const {
    U64 own_pawns;
    U64 enemy_pawns;
    int forward;

    if (colour == WHITE) {
        own_pawns = bitboards[WP];
        enemy_pawns = bitboards[BP];
        forward = 8;
    } else {
        own_pawns = bitboards[BP];
        enemy_pawns = bitboards[WP];
        forward = -8;
    }

    int score = 0;
    U64 bb = own_pawns;

    while (bb) {
        auto [sq, next] = pop_lsb(bb);
        bb = next;

        int f = file_of(sq);
        int r = rank_of(sq);

        U64 ahead_mask = 0;

        if (colour == WHITE) {
            for (int ahead_rank = r + 1; ahead_rank < 8; ++ahead_rank) {
                for (int adjacent_file = f - 1; adjacent_file <= f + 1; ++adjacent_file) {
                    if (adjacent_file >= 0 && adjacent_file < 8) {
                        ahead_mask |= bit(ahead_rank * 8 + adjacent_file);
                    }
                }
            }
        } else {
            for (int ahead_rank = 0; ahead_rank < r; ++ahead_rank) {
                for (int adjacent_file = f - 1; adjacent_file <= f + 1; ++adjacent_file) {
                    if (adjacent_file >= 0 && adjacent_file < 8) {
                        ahead_mask |= bit(ahead_rank * 8 + adjacent_file);
                    }
                }
            }
        }

        if (!(enemy_pawns & ahead_mask)) {
            int bonus_index = colour == WHITE ? r : 7 - r;
            score += PASSED_PAWN_BONUS[bonus_index];
        }

        U64 behind_mask = 0;

        if (colour == WHITE) {
            for (int behind_rank = 0; behind_rank < r; ++behind_rank) {
                behind_mask |= bit(behind_rank * 8 + f);
            }
        } else {
            for (int behind_rank = r + 1; behind_rank < 8; ++behind_rank) {
                behind_mask |= bit(behind_rank * 8 + f);
            }
        }

        if (own_pawns & behind_mask) {
            score -= DOUBLED_PAWN_PENALTY;
        }

        if (!(own_pawns & adjacent_file_mask(f))) {
            score -= ISOLATED_PAWN_PENALTY;
        }

        int front_sq = sq + forward;

        if (on_board(front_sq)) {
            U64 enemy_attackers_of_front = pawn_attacks_from(
                front_sq,
                colour == WHITE ? WHITE : BLACK
            );

            bool front_attacked_by_enemy_pawn = enemy_pawns & enemy_attackers_of_front;

            U64 support_mask = 0;

            for (int adjacent_file : {f - 1, f + 1}) {
                if (adjacent_file < 0 || adjacent_file >= 8) {
                    continue;
                }

                if (colour == WHITE) {
                    for (int support_rank = 0; support_rank <= r; ++support_rank) {
                        support_mask |= bit(support_rank * 8 + adjacent_file);
                    }
                } else {
                    for (int support_rank = r; support_rank < 8; ++support_rank) {
                        support_mask |= bit(support_rank * 8 + adjacent_file);
                    }
                }
            }

            bool can_be_supported = own_pawns & support_mask;

            if (front_attacked_by_enemy_pawn && !can_be_supported) {
                score -= BACKWARD_PAWN_PENALTY;
            }
        }
    }

    return score;
}

namespace {

struct PawnCacheEntry {
    U64 white_pawns = ~0ULL;   // impossible pawn set: never matches a real position
    U64 black_pawns = ~0ULL;
    int score = 0;
};

constexpr std::size_t PAWN_CACHE_SIZE = std::size_t(1) << 15;
constexpr std::size_t PAWN_CACHE_MASK = PAWN_CACHE_SIZE - 1;

thread_local std::array<PawnCacheEntry, PAWN_CACHE_SIZE> pawn_cache{};

U64 mix64(U64 x) {
    x += 0x9E3779B97F4A7C15ULL;
    x = (x ^ (x >> 30)) * 0xBF58476D1CE4E5B9ULL;
    x = (x ^ (x >> 27)) * 0x94D049BB133111EBULL;
    return x ^ (x >> 31);
}

} // namespace

int Board::evaluate_pawn_structure() const {
    U64 wp = bitboards[WP];
    U64 bp = bitboards[BP];

    // Pawn structure changes on a small minority of moves, so cache the
    // result keyed on the exact pawn bitboards (full-key check: no aliasing).
    std::size_t index = mix64(wp ^ mix64(bp)) & PAWN_CACHE_MASK;
    PawnCacheEntry& entry = pawn_cache[index];

    if (entry.white_pawns == wp && entry.black_pawns == bp) {
        return entry.score;
    }

    int score = evaluate_pawn_structure_for_colour(WHITE)
              - evaluate_pawn_structure_for_colour(BLACK);

    entry = PawnCacheEntry{wp, bp, score};
    return score;
}

int Board::evaluate_king_safety_for_colour(int colour) const {
    int king_sq = king_square(colour);

    if (king_sq == -1) {
        return 0;
    }

    int enemy = colour ^ 1;
    int score = 0;

    U64 zone = king_attacks(king_sq) | bit(king_sq);

    // Weighted pressure: one pass over enemy pieces, each contributing
    // weight x (attack squares inside the king zone). Replaces 9 separate
    // is_square_attacked calls (each up to two ray walks) per king.
    int pressure = 0;
    U64 occ = occupancy();

    U64 bb = bitboards[enemy == WHITE ? WP : BP];
    while (bb) {
        auto [sq, next] = pop_lsb(bb);
        bb = next;
        pressure += PRESSURE_PAWN * count_bits(pawn_attacks_from(sq, enemy) & zone);
    }

    bb = bitboards[enemy == WHITE ? WN : BN];
    while (bb) {
        auto [sq, next] = pop_lsb(bb);
        bb = next;
        pressure += PRESSURE_MINOR * count_bits(knight_attacks(sq) & zone);
    }

    bb = bitboards[enemy == WHITE ? WB : BB];
    while (bb) {
        auto [sq, next] = pop_lsb(bb);
        bb = next;
        pressure += PRESSURE_MINOR
            * count_bits(attacks_from_slider(sq, BISHOP_DELTAS, occ) & zone);
    }

    bb = bitboards[enemy == WHITE ? WR : BR];
    while (bb) {
        auto [sq, next] = pop_lsb(bb);
        bb = next;
        pressure += PRESSURE_ROOK
            * count_bits(attacks_from_slider(sq, ROOK_DELTAS, occ) & zone);
    }

    bb = bitboards[enemy == WHITE ? WQ : BQ];
    while (bb) {
        auto [sq, next] = pop_lsb(bb);
        bb = next;
        pressure += PRESSURE_QUEEN
            * count_bits(attacks_from_slider(sq, QUEEN_DELTAS, occ) & zone);
    }

    score -= pressure * KING_ZONE_PRESSURE_PENALTY;

    int king_file = file_of(king_sq);
    U64 own_pawns = bitboards[colour == WHITE ? WP : BP];

    for (int f = std::max(0, king_file - 1); f < std::min(8, king_file + 2); ++f) {
        U64 pawns_on_file = own_pawns & file_mask(f);

        if (!pawns_on_file) {
            score -= KING_OPEN_FILE_PENALTY;
        } else {
            U64 pawn_bb = pawns_on_file;

            while (pawn_bb) {
                auto [psq, next] = pop_lsb(pawn_bb);
                pawn_bb = next;

                if (colour == WHITE && rank_of(psq) > rank_of(king_sq) + 2) {
                    score -= KING_OPEN_FILE_PENALTY / 2;
                } else if (colour == BLACK && rank_of(psq) < rank_of(king_sq) - 2) {
                    score -= KING_OPEN_FILE_PENALTY / 2;
                }
            }
        }
    }

    return score;
}

int Board::evaluate_king_safety() const {
    return evaluate_king_safety_for_colour(WHITE)
         - evaluate_king_safety_for_colour(BLACK);
}

int Board::evaluate_mobility_for_colour(int colour) const {
    U64 occ = occupancy();
    U64 own = occupancy(colour);
    int score = 0;

    U64 bishops;
    U64 rooks;
    U64 queens;

    if (colour == WHITE) {
        bishops = bitboards[WB];
        rooks = bitboards[WR];
        queens = bitboards[WQ];
    } else {
        bishops = bitboards[BB];
        rooks = bitboards[BR];
        queens = bitboards[BQ];
    }

    U64 own_pawns = bitboards[colour == WHITE ? WP : BP];
    U64 enemy_pawns = bitboards[colour == WHITE ? BP : WP];

    if (count_bits(bishops) >= 2) {
        score += BISHOP_PAIR_BONUS;
    }

    U64 bb = bishops;
    while (bb) {
        auto [sq, next] = pop_lsb(bb);
        bb = next;

        U64 moves = attacks_from_slider(sq, BISHOP_DELTAS, occ) & ~own;
        score += count_bits(moves) * BISHOP_MOBILITY_BONUS;
    }

    bb = rooks;
    while (bb) {
        auto [sq, next] = pop_lsb(bb);
        bb = next;

        U64 moves = attacks_from_slider(sq, ROOK_DELTAS, occ) & ~own;
        score += count_bits(moves) * ROOK_MOBILITY_BONUS;

        U64 file = file_mask(file_of(sq));

        if (!(own_pawns & file)) {
            score += (enemy_pawns & file)
                ? ROOK_SEMI_OPEN_FILE_BONUS
                : ROOK_OPEN_FILE_BONUS;
        }
    }

    bb = queens;
    while (bb) {
        auto [sq, next] = pop_lsb(bb);
        bb = next;

        U64 moves = attacks_from_slider(sq, QUEEN_DELTAS, occ) & ~own;
        score += count_bits(moves) * QUEEN_MOBILITY_BONUS;
    }

    return score;
}

int Board::evaluate_mop_up_for_colour(int colour) const {
    int enemy = colour ^ 1;

    U64 enemy_pieces = occupancy(enemy);
    U64 enemy_king = bitboards[enemy == WHITE ? WK : BK];

    if (enemy_pieces != enemy_king) {
        return 0;
    }

    U64 heavy = colour == WHITE
        ? (bitboards[WR] | bitboards[WQ])
        : (bitboards[BR] | bitboards[BQ]);

    if (!heavy) {
        return 0;
    }

    int our_king = king_square(colour);
    int their_king = king_square(enemy);

    if (our_king == -1 || their_king == -1) {
        return 0;
    }

    return MOP_UP_EDGE_BONUS * centre_manhattan_distance(their_king)
         + MOP_UP_KING_CLOSE_BONUS * (14 - king_manhattan_distance(our_king, their_king));
}

int Board::evaluate_mop_up() const {
    return evaluate_mop_up_for_colour(WHITE)
         - evaluate_mop_up_for_colour(BLACK);
}

int Board::evaluate_mobility() const {
    return evaluate_mobility_for_colour(WHITE)
         - evaluate_mobility_for_colour(BLACK);
}

namespace {
constexpr int LAZY_EVAL_MARGIN = 500;
constexpr int EVAL_UNBOUNDED = 100'000'000;
}

int Board::evaluate(int alpha, int beta) const {
    int score = evaluate_fast();             // side-relative

    if (side_to_move == BLACK) {
        score = -score;                       // white point of view
    }

    // Mop-up stays in the cheap stage: it is nearly free in normal positions
    // (two bitboard tests) and its swings are far larger than any margin, so
    // it must never be skipped or endgame conversion breaks.
    score += evaluate_mop_up();

    int side_relative = side_to_move == WHITE ? score : -score;

    // If even the maximum possible contribution of the remaining terms cannot
    // bring the score back inside the window, the exact value is irrelevant
    // to the cutoff decision.
    if (side_relative + LAZY_EVAL_MARGIN <= alpha
        || side_relative - LAZY_EVAL_MARGIN >= beta) {
        return side_relative;
    }

    score += evaluate_opening_principles();
    score += evaluate_pawn_structure();
    score += evaluate_king_safety();
    score += evaluate_mobility();

    return side_to_move == WHITE ? score : -score;
}

int Board::evaluate() const {
    return evaluate(-EVAL_UNBOUNDED, EVAL_UNBOUNDED);
}