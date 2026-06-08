#pragma once

#include <optional>
#include <string>

enum Colour {
    WHITE = 0,
    BLACK = 1
};

enum Piece {
    WP = 0, WN = 1, WB = 2, WR = 3, WQ = 4, WK = 5,
    BP = 6, BN = 7, BB = 8, BR = 9, BQ = 10, BK = 11
};

struct Move {
    int from_sq = 0;
    int to_sq = 0;
    std::optional<int> promotion = std::nullopt;
    bool is_en_passant = false;
    bool is_castling = false;

    Move() = default;

    Move(
        int from,
        int to,
        std::optional<int> promo = std::nullopt,
        bool ep = false,
        bool castling = false
    )
        : from_sq(from),
          to_sq(to),
          promotion(promo),
          is_en_passant(ep),
          is_castling(castling)
    {}
};

std::string square_name(int sq);
int square_index(const std::string& name);
std::string move_to_string(const Move& move);