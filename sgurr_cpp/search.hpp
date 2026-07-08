#pragma once

#include "board.hpp"

#include <array>
#include <chrono>
#include <optional>
#include <unordered_map>
#include <vector>

constexpr int INF = 10'000'000;
constexpr int MATE = 1'000'000;

constexpr int MAX_DEPTH = 5;
constexpr int MAX_PLY = 128;
constexpr int NULL_MOVE_REDUCTION = 2;

constexpr int LMR_FULL_DEPTH_MOVES = 2;
constexpr int LMR_MIN_DEPTH = 3;

constexpr int TT_EXACT = 0;
constexpr int TT_LOWER = 1;
constexpr int TT_UPPER = 2;

constexpr int TT_SIZE_BITS = 21;
constexpr std::size_t TT_SIZE = std::size_t(1) << TT_SIZE_BITS;   // ~2M entries
constexpr U64 TT_MASK = TT_SIZE - 1;
constexpr int TIME_CHECK_INTERVAL = 512;
constexpr int CHECK_EXTENSION_MAX_DEPTH = 4;

// Time-management knobs (clock play only; explicit `movetime` and node limits
// are unaffected). MOVE_OVERHEAD_MS is the clock margin held back for GUI and
// network latency so the move always arrives before the flag falls.
// SOFT_TIME_FRACTION is how far into the budget a new iterative-deepening pass
// may still be started; past it the last completed depth is kept rather than
// starting an iteration that would be aborted, unfinished, at the hard limit.
constexpr long long MOVE_OVERHEAD_MS = 30;
constexpr double SOFT_TIME_FRACTION = 0.6;

constexpr int ASPIRATION_WINDOW = 50;
constexpr int DELTA_MARGIN = 200;

struct SearchResult {
    std::optional<Move> best_move = std::nullopt;
    int score = 0;
    int depth = 0;
    long long nodes = 0;
    long long tt_hits = 0;
    double time_taken = 0.0;
};

struct TTEntry {
    U64 key = 0;                 // full hash for collision detection; 0 = empty
    int depth = -1;
    int score = 0;
    int flag = TT_EXACT;
    std::optional<Move> best_move = std::nullopt;
};

class Engine {
public:
    long long nodes = 0;
    long long tt_hits = 0;

    std::vector<TTEntry> transposition_table;   // fixed size TT_SIZE, indexed by hash & TT_MASK

    Engine();

    SearchResult search_best_move(
        Board& board,
        int max_depth = MAX_DEPTH,
        std::optional<double> time_limit = std::nullopt,
        std::optional<long long> node_limit = std::nullopt,
        std::optional<double> soft_limit = std::nullopt
    );

    void clear_transposition_table();
    void clear_search_heuristics();
    void clear_for_new_position();
    void clear_for_new_game();

    int evaluate_position(const Board& board) const;
    int evaluate_quiet_position(const Board& board) const;
    MoveList generate_moves(Board& board) const;

private:
    std::chrono::steady_clock::time_point start_time;
    std::optional<double> time_limit = std::nullopt;         // hard deadline: abort mid-search
    std::optional<double> soft_time_limit = std::nullopt;    // don't start a new iteration past this
    std::optional<long long> node_limit = std::nullopt;
    bool stop_search = false;

    std::array<std::array<std::optional<Move>, 2>, MAX_PLY> killer_moves{};
    std::array<std::array<int, 64>, 64> history{};

    bool time_is_up() const;

    void reset_killers();
    void reset_history();

    std::optional<Move> valid_tt_move_key(
        U64 board_hash,
        const MoveList& moves
    ) const;

    std::pair<int, std::optional<Move>> negamax_root(
        Board& board,
        int depth,
        int alpha,
        int beta
    );

    int negamax(
        Board& board,
        int depth,
        int alpha,
        int beta,
        int ply
    );

    int quiescence(Board& board, int alpha, int beta, int ply);

    bool is_killer_move(int ply, const Move& move) const;

    bool can_reduce_late_move(
        Board& board,
        const Move& move,
        int depth,
        int ply,
        int legal_moves_searched,
        const std::optional<Move>& tt_move_key,
        bool in_check
    ) const;

    int lmr_reduction(int depth, int legal_moves_searched) const;

    bool can_try_null_move(Board& board, int depth, int beta, int ply) const;

    bool is_noisy_move(const Board& board, const Move& move) const;

    void store_killer(int ply, const Move& move);

    MoveList order_moves(
        Board& board,
        const MoveList& moves,
        const std::optional<Move>& tt_move_key,
        int ply,
        bool split_bad_captures = true
    ) const;

    int capture_score(const Board& board, const Move& move) const;

    void store_tt(
        U64 board_hash,
        int depth,
        int score,
        int flag,
        std::optional<Move> best_move_key
    );

    std::optional<Move> get_tt_move(U64 board_hash) const;
};