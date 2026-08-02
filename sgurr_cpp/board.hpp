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

// Everything needed to undo one move. Built on every make_move, so absent
// values are -1 rather than std::optional: same convention as `mailbox`, which
// has always used -1 for an empty square. captured_piece and captured_square
// are set and cleared together -- either both hold a capture or both are -1.
struct UndoInfo {
    Move move;
    int moved_piece = -1;
    int placed_piece = -1;
    int captured_piece = -1;
    int captured_square = -1;
    std::uint8_t old_castling = 0;
    int old_en_passant = -1;
    int old_halfmove_clock = 0;
    int old_fullmove_number = 1;
    U64 old_hash_key = 0;
};

struct NullMoveUndo {
    int old_side_to_move = WHITE;
    int old_en_passant = -1;
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

// Capacity of Board::position_history, the repetition-detection ring. A power
// of two so the wrap is a mask. See the field declaration for why a ring, and
// why this size cannot be too small.
constexpr int POSITION_HISTORY_CAP = 1024;
constexpr int POSITION_HISTORY_MASK = POSITION_HISTORY_CAP - 1;

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

    // Occupancy, maintained incrementally rather than recomputed. occupancy()
    // used to OR together six or twelve bitboards on every call, and it is
    // called from is_square_attacked, legality_info, both move generators, and
    // twice inside the SEE exchange loop -- so the same twelve ORs were being
    // redone several times per node.
    //
    // These are derived state: they must always equal the union of the piece
    // bitboards. Only set_fen, make_move and unmake_move ever write a piece
    // bitboard, so those are the only three places that maintain them, and a
    // debug build re-derives and checks them after every make and unmake.
    U64 occ_white = 0;
    U64 occ_black = 0;
    U64 occ_all = 0;
    int side_to_move = WHITE;
    std::uint8_t castling_rights = 0;   // bits: 1=WK 2=WQ 4=BK 8=BQ
    int en_passant = -1;                // -1 = no en-passant square
    int halfmove_clock = 0;
    int fullmove_number = 1;
    U64 hash_key = 0;
    // Zobrist keys of the positions already visited, for repetition detection.
    // A fixed ring rather than a std::vector: make_move and unmake_move push
    // and pop this on every node in the tree, and a heap container there costs
    // a pointer chase, a capacity test and an occasional reallocation.
    //
    // The ring does not have to hold a whole game. is_repetition() never looks
    // back further than halfmove_clock entries, and halfmove_clock resets on
    // every pawn move and capture -- the search already scores a draw at 100,
    // and the 75-move rule ends a real game at 150. 1024 slots is several
    // times more history than can ever be read back, so a game long enough to
    // wrap loses only entries that no longer affect the answer, instead of
    // running off the end of a plain array.
    std::array<U64, POSITION_HISTORY_CAP> position_history{};
    int position_history_count = 0;

    Board();
    explicit Board(const std::string& fen);

    void set_fen(const std::string& fen);
    U64 compute_hash() const;

    // Rebuild occ_* from the piece bitboards. Only needed when the position is
    // set wholesale; make/unmake keep them in sync incrementally.
    void refresh_occupancy();

    // Re-derives occupancy and asserts it matches the cache. Compiled to
    // nothing when NDEBUG is set, so release builds pay nothing for it.
    void assert_occupancy_sync() const;

    U64 occupancy(std::optional<int> colour = std::nullopt) const;
    std::optional<int> piece_at(int sq) const;
    int king_square(int colour) const;

    U64 bishop_attacks_from(int sq, U64 occ) const;
    U64 rook_attacks_from(int sq, U64 occ) const;
    U64 queen_attacks_from(int sq, U64 occ) const;
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
    void add_knight_moves(MoveList& moves, int piece, U64 own);
    void add_king_moves(MoveList& moves, int piece, U64 own);
    void add_castling_moves(MoveList& moves);

    void update_castling_rights(int piece, const Move& move, int captured);
};

long long perft(Board& board, int depth);
void divide(Board& board, int depth);