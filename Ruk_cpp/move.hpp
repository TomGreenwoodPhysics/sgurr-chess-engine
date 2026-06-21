#pragma once

#include <cstdint>
#include <string>

enum Colour {
    WHITE = 0,
    BLACK = 1
};

enum Piece {
    WP = 0, WN = 1, WB = 2, WR = 3, WQ = 4, WK = 5,
    BP = 6, BN = 7, BB = 8, BR = 9, BQ = 10, BK = 11
};

// Promotion piece type, stored in bits 12-13 of a packed move. Ordered so that
// (WN + type) / (BN + type) yields the colour-specific promoted piece index.
enum PromoType {
    PROMO_N = 0,
    PROMO_B = 1,
    PROMO_R = 2,
    PROMO_Q = 3
};

// Special move kind, stored in bits 14-15.
enum MoveType {
    MT_NORMAL = 0,   // quiet move or ordinary capture
    MT_PROMO  = 1,
    MT_EP     = 2,   // en passant capture
    MT_CASTLE = 3
};

// Packed 16-bit move:
//   bits 0-5   from square
//   bits 6-11  to square
//   bits 12-13 promotion type (only meaningful when kind == MT_PROMO)
//   bits 14-15 move kind (MoveType)
//
// The whole move fits in a register and is its own transposition / killer key,
// so the previous separate MoveKey type is gone. Accessors keep call sites
// readable; everything inlines away.
struct Move {
    std::uint16_t data = 0;

    Move() = default;

    // Quiet move or ordinary capture.
    Move(int from, int to)
        : data(static_cast<std::uint16_t>(from | (to << 6))) {}

    // Special move (promotion / en passant / castling).
    Move(int from, int to, int promo_type, MoveType kind)
        : data(static_cast<std::uint16_t>(
              from | (to << 6) | (promo_type << 12) | (kind << 14))) {}

    int from() const { return data & 63; }
    int to() const { return (data >> 6) & 63; }
    int kind() const { return (data >> 14) & 3; }

    bool is_promotion() const { return kind() == MT_PROMO; }
    bool is_en_passant() const { return kind() == MT_EP; }
    bool is_castling() const { return kind() == MT_CASTLE; }

    int promo_type() const { return (data >> 12) & 3; }

    // Colour-specific promoted piece index (WN..WQ or BN..BQ).
    int promo_piece(int side) const {
        return (side == WHITE ? WN : BN) + promo_type();
    }

    bool operator==(const Move& other) const { return data == other.data; }
    bool operator!=(const Move& other) const { return data != other.data; }
};

constexpr Move NO_MOVE{};   // the null sentinel (a1a1, never generated)

// Fixed-capacity, allocation-free move container. A chess position has at most
// 218 legal moves, so 256 slots can never overflow. Replaces the per-node
// std::vector<Move> that movegen and ordering used to allocate and return.
struct MoveList {
    Move moves[256];
    int count = 0;

    void add(Move m) { moves[count++] = m; }
    int size() const { return count; }
    bool empty() const { return count == 0; }
    void clear() { count = 0; }

    Move& operator[](int i) { return moves[i]; }
    const Move& operator[](int i) const { return moves[i]; }

    Move* begin() { return moves; }
    Move* end() { return moves + count; }
    const Move* begin() const { return moves; }
    const Move* end() const { return moves + count; }
};

std::string square_name(int sq);
int square_index(const std::string& name);
std::string move_to_string(const Move& move);