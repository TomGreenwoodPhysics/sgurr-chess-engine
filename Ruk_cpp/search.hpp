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

struct MoveKey {
    int from_sq = 0;
    int to_sq = 0;
    int promotion = -1;
    bool is_en_passant = false;
    bool is_castling = false;

    bool operator==(const MoveKey& other) const {
        return from_sq == other.from_sq
            && to_sq == other.to_sq
            && promotion == other.promotion
            && is_en_passant == other.is_en_passant
            && is_castling == other.is_castling;
    }
};

struct MoveKeyHash {
    std::size_t operator()(const MoveKey& key) const {
        std::size_t h = 17;
        h = h * 31 + std::hash<int>{}(key.from_sq);
        h = h * 31 + std::hash<int>{}(key.to_sq);
        h = h * 31 + std::hash<int>{}(key.promotion);
        h = h * 31 + std::hash<bool>{}(key.is_en_passant);
        h = h * 31 + std::hash<bool>{}(key.is_castling);
        return h;
    }
};

struct TTEntry {
    U64 key = 0;                 // full hash for collision detection; 0 = empty
    int depth = -1;
    int score = 0;
    int flag = TT_EXACT;
    std::optional<MoveKey> best_move_key = std::nullopt;
};

MoveKey move_key(const Move& move);

class Engine {
public:
    long long nodes = 0;
    long long tt_hits = 0;

    std::vector<TTEntry> transposition_table;   // fixed size TT_SIZE, indexed by hash & TT_MASK

    Engine();

    SearchResult search_best_move(
        Board& board,
        int max_depth = MAX_DEPTH,
        std::optional<double> time_limit = std::nullopt
    );

    void clear_transposition_table();
    void clear_search_heuristics();
    void clear_for_new_position();
    void clear_for_new_game();

    int evaluate_position(const Board& board) const;
    int evaluate_quiet_position(const Board& board) const;
    std::vector<Move> generate_moves(Board& board) const;

private:
    std::chrono::steady_clock::time_point start_time;
    std::optional<double> time_limit = std::nullopt;
    bool stop_search = false;

    std::array<std::array<std::optional<MoveKey>, 2>, MAX_PLY> killer_moves{};
    std::array<std::array<int, 64>, 64> history{};

    bool time_is_up() const;

    void reset_killers();
    void reset_history();

    std::optional<MoveKey> valid_tt_move_key(
        U64 board_hash,
        const std::vector<Move>& moves
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
        const std::optional<MoveKey>& tt_move_key,
        bool in_check
    ) const;

    int lmr_reduction(int depth, int legal_moves_searched) const;

    bool can_try_null_move(Board& board, int depth, int beta, int ply) const;

    bool is_noisy_move(const Board& board, const Move& move) const;

    void store_killer(int ply, const Move& move);

    std::vector<Move> order_moves(
        Board& board,
        const std::vector<Move>& moves,
        const std::optional<MoveKey>& tt_move_key,
        int ply,
        bool split_bad_captures = true
    ) const;

    int capture_score(const Board& board, const Move& move) const;

    void store_tt(
        U64 board_hash,
        int depth,
        int score,
        int flag,
        std::optional<MoveKey> best_move_key
    );

    std::optional<MoveKey> get_tt_move_key(U64 board_hash) const;
};