#pragma once

#include "move.hpp"

#include <array>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

using U64 = std::uint64_t;

constexpr U64 FULL = 0xFFFFFFFFFFFFFFFFULL;

constexpr const char* START_FEN =
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

struct UndoInfo {
    Move move;
    int moved_piece = -1;
    int placed_piece = -1;
    std::optional<int> captured_piece = std::nullopt;
    std::optional<int> captured_square = std::nullopt;
    std::uint8_t old_castling = 0;
    std::optional<int> old_en_passant = std::nullopt;
    int old_halfmove_clock = 0;
    int old_fullmove_number = 1;
    U64 old_hash_key = 0;
};

struct NullMoveUndo {
    int old_side_to_move = WHITE;
    std::optional<int> old_en_passant = std::nullopt;
    int old_halfmove_clock = 0;
    int old_fullmove_number = 1;
    U64 old_hash_key = 0;
};

// Per-position king-safety data used to test move legality without make/unmake.
// Computed once per node; is_legal() then answers each move in O(1).
struct LegalityInfo {
    int ksq = -1;        // side-to-move king square
    int nchk = 0;        // number of checkers (0, 1, or 2)
    U64 checkers = 0;    // enemy pieces giving check
    U64 pinned = 0;      // own pieces pinned to the king
    U64 check_mask = 0;  // when nchk == 1: squares that resolve the check
};

int rank_of(int sq);
int file_of(int sq);
U64 bit(int sq);
int mirror_square(int sq);
bool on_board(int sq);
std::pair<int, U64> pop_lsb(U64 bb);

class Board {
public:
    std::array<U64, 12> bitboards{};
    std::array<int, 64> mailbox{};
    int side_to_move = WHITE;
    std::uint8_t castling_rights = 0;   // bits: 1=WK 2=WQ 4=BK 8=BQ
    std::optional<int> en_passant = std::nullopt;
    int halfmove_clock = 0;
    int fullmove_number = 1;
    U64 hash_key = 0;
    std::vector<U64> position_history;

    Board();
    explicit Board(const std::string& fen);

    void set_fen(const std::string& fen);
    U64 compute_hash() const;

    U64 occupancy(std::optional<int> colour = std::nullopt) const;
    std::optional<int> piece_at(int sq) const;
    int king_square(int colour) const;

    U64 attacks_from_slider(int sq, const std::vector<int>& deltas, U64 occ) const;
    U64 knight_attacks(int sq) const;
    U64 king_attacks(int sq) const;
    U64 pawn_attacks_from(int sq, int colour) const;

    bool is_square_attacked(int sq, int by_colour) const;
    bool square_attacked_with_occ(int sq, int by_colour, U64 occ) const;
    bool is_repetition() const;
    bool in_check(int colour) const;

    LegalityInfo legality_info() const;
    bool is_legal(const Move& move, const LegalityInfo& li) const;

    U64 attackers_to(int sq, U64 occ) const;
    int see(const Move& move) const;
    bool see_ge(const Move& move, int threshold) const;

    MoveList generate_pseudo_legal_moves();
    MoveList generate_legal_moves();

    UndoInfo make_move(const Move& move);
    void unmake_move(const UndoInfo& undo);

    NullMoveUndo make_null_move();
    void unmake_null_move(const NullMoveUndo& undo);

    bool has_non_pawn_material(int colour) const;

    void print_board() const;

    int evaluate_fast() const;
    int evaluate_quiet() const;
    int evaluate() const;
    int evaluate(int alpha, int beta) const;   // lazy: may skip slow terms when far outside the window

    int game_phase() const;
    int non_pawn_material_total() const;
    bool opening_phase_active() const;
    int evaluate_opening_principles_for_colour(int colour) const;
    int evaluate_opening_principles() const;

    int evaluate_pawn_structure_for_colour(int colour) const;
    int evaluate_pawn_structure() const;

    int evaluate_king_safety_for_colour(int colour) const;
    int evaluate_king_safety() const;

    int evaluate_mobility_for_colour(int colour) const;
    int evaluate_mobility() const;

    int evaluate_mop_up_for_colour(int colour) const;
    int evaluate_mop_up() const;

private:
    void add_pawn_move(MoveList& moves, int from_sq, int to_sq, int colour);
    void add_piece_moves(
        MoveList& moves,
        int piece,
        const std::vector<int>& deltas,
        U64 own,
        U64 occ
    );
    void add_knight_moves(MoveList& moves, int piece, U64 own);
    void add_king_moves(MoveList& moves, int piece, U64 own);
    void add_castling_moves(MoveList& moves);

    void update_castling_rights(
        int piece,
        const Move& move,
        std::optional<int> captured
    );
};

long long perft(Board& board, int depth);
void divide(Board& board, int depth);