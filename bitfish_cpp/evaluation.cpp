#include "evaluation.hpp"

#include <array>
#include <bit>
#include <cmath>
#include <vector>

namespace {

constexpr std::array<int, 12> PIECE_VALUE = {
    100, 320, 330, 500, 900, 0,
    100, 320, 330, 500, 900, 0
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

constexpr std::array<std::array<int, 64>, 6> PIECE_SQUARE_TABLE = {
    PAWN_PST,
    KNIGHT_PST,
    BISHOP_PST,
    ROOK_PST,
    QUEEN_PST,
    KING_PST
};

constexpr int OPENING_MAX_FULLMOVE = 3;
constexpr int OPENING_MIN_NON_PAWN_MATERIAL = 5200;

constexpr int OPENING_CENTRE_PAWN_BONUS = 22;
constexpr int OPENING_KINGSIDE_KNIGHT_BONUS = 18;
constexpr int OPENING_QUEENSIDE_KNIGHT_BONUS = 8;
constexpr int OPENING_BISHOP_DEVELOPMENT_BONUS = 5;
constexpr int OPENING_CASTLED_BONUS = 25;

constexpr std::array<int, 8> PASSED_PAWN_BONUS = {
    0, 10, 15, 25, 40, 65, 100, 0
};

constexpr int DOUBLED_PAWN_PENALTY = 20;
constexpr int ISOLATED_PAWN_PENALTY = 15;
constexpr int BACKWARD_PAWN_PENALTY = 15;

constexpr int KING_ATTACKER_PENALTY = 28;
constexpr int KING_OPEN_FILE_PENALTY = 22;

constexpr int BISHOP_MOBILITY_BONUS = 3;
constexpr int ROOK_MOBILITY_BONUS = 2;
constexpr int QUEEN_MOBILITY_BONUS = 1;

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

} // namespace

int Board::evaluate_fast() const {
    int score = 0;

    for (int piece = 0; piece < 12; ++piece) {
        U64 bb = bitboards[piece];

        if (piece <= WK) {
            const auto& pst = PIECE_SQUARE_TABLE[piece];
            int value = PIECE_VALUE[piece];

            while (bb) {
                auto [sq, next] = pop_lsb(bb);
                bb = next;
                score += value + pst[sq];
            }
        } else {
            const auto& pst = PIECE_SQUARE_TABLE[piece - 6];
            int value = PIECE_VALUE[piece];

            while (bb) {
                auto [sq, next] = pop_lsb(bb);
                bb = next;
                score -= value + pst[mirror_square(sq)];
            }
        }
    }

    return side_to_move == WHITE ? score : -score;
}

int Board::evaluate_quiet() const {
    return evaluate_fast();
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

int Board::evaluate_pawn_structure() const {
    return evaluate_pawn_structure_for_colour(WHITE)
         - evaluate_pawn_structure_for_colour(BLACK);
}

int Board::evaluate_king_safety_for_colour(int colour) const {
    int king_sq = king_square(colour);

    if (king_sq == -1) {
        return 0;
    }

    int enemy = colour ^ 1;
    int score = 0;

    U64 king_zone = king_attacks(king_sq);
    U64 zone_copy = king_zone | bit(king_sq);

    int attacker_count = 0;
    U64 temp = zone_copy;

    while (temp) {
        auto [sq, next] = pop_lsb(temp);
        temp = next;

        if (is_square_attacked(sq, enemy)) {
            attacker_count += 1;
        }
    }

    score -= attacker_count * KING_ATTACKER_PENALTY;

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

int Board::evaluate_mobility() const {
    return evaluate_mobility_for_colour(WHITE)
         - evaluate_mobility_for_colour(BLACK);
}

int Board::evaluate() const {
    int score = evaluate_fast();

    if (side_to_move == BLACK) {
        score = -score;
    }

    score += evaluate_opening_principles();
    score += evaluate_pawn_structure();
    score += evaluate_king_safety();
    score += evaluate_mobility();

    return side_to_move == WHITE ? score : -score;
}