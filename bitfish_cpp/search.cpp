#include "search.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <iostream>

namespace {

constexpr std::array<int, 12> PIECE_VALUE = {
    100, 320, 330, 500, 900, 0,
    100, 320, 330, 500, 900, 0
};

constexpr int MAX_PIECE_VALUE = 900;

constexpr std::array<int, 3> FUTILITY_MARGIN = {
    0, 150, 300
};

double elapsed_seconds(std::chrono::steady_clock::time_point start) {
    using namespace std::chrono;
    return duration<double>(steady_clock::now() - start).count();
}

} // namespace

MoveKey move_key(const Move& move) {
    return MoveKey{
        move.from_sq,
        move.to_sq,
        move.promotion.has_value() ? *move.promotion : -1,
        move.is_en_passant,
        move.is_castling
    };
}

Engine::Engine() {
    for (auto& row : killer_moves) {
        row[0] = std::nullopt;
        row[1] = std::nullopt;
    }

    for (auto& row : history) {
        row.fill(0);
    }
}

SearchResult Engine::search_best_move(
    Board& board,
    int max_depth,
    std::optional<double> limit
) {
    nodes = 0;
    tt_hits = 0;
    start_time = std::chrono::steady_clock::now();
    time_limit = limit;
    stop_search = false;

    for (auto& row : killer_moves) {
        row[0] = std::nullopt;
        row[1] = std::nullopt;
    }

    std::vector<Move> legal_moves = board.generate_legal_moves();
    std::optional<Move> best_move = std::nullopt;

    if (!legal_moves.empty()) {
        auto tt_key = get_tt_move_key(board.hash_key);
        auto ordered = order_moves(board, legal_moves, tt_key, 0);
        best_move = ordered.front();
    }

    int best_score = best_move.has_value() ? board.evaluate() : -INF;
    int completed_depth = 0;

    for (int depth = 1; depth <= max_depth; ++depth) {
        int score;
        std::optional<Move> move;

        if (depth == 1 || completed_depth == 0) {
            auto result = negamax_root(board, depth, -INF, INF);
            score = result.first;
            move = result.second;
        } else {
            int alpha = best_score - ASPIRATION_WINDOW;
            int beta = best_score + ASPIRATION_WINDOW;

            auto result = negamax_root(board, depth, alpha, beta);
            score = result.first;
            move = result.second;

            if (!stop_search && (score <= alpha || score >= beta)) {
                result = negamax_root(board, depth, -INF, INF);
                score = result.first;
                move = result.second;
            }
        }

        if (stop_search) {
            break;
        }

        if (move.has_value()) {
            best_move = move;
            best_score = score;
            completed_depth = depth;
        }

        std::cout
            << "info depth " << depth
            << " score cp " << best_score
            << " nodes " << nodes
            << " tthits " << tt_hits
            << " time " << static_cast<int>(elapsed_seconds(start_time) * 1000)
            << " pv " << (best_move.has_value() ? move_to_string(*best_move) : "none")
            << "\n";
    }

    return SearchResult{
        best_move,
        best_score,
        completed_depth,
        nodes,
        tt_hits,
        elapsed_seconds(start_time)
    };
}

bool Engine::time_is_up() const {
    if (!time_limit.has_value()) {
        return false;
    }

    return elapsed_seconds(start_time) >= *time_limit;
}

int Engine::evaluate_position(const Board& board) const {
    return board.evaluate();
}

int Engine::evaluate_quiet_position(const Board& board) const {
    return board.evaluate_quiet();
}

std::vector<Move> Engine::generate_moves(Board& board) const {
    return board.generate_pseudo_legal_moves();
}

std::pair<int, std::optional<Move>> Engine::negamax_root(
    Board& board,
    int depth,
    int alpha,
    int beta
) {
    int best_score = -INF;
    std::optional<Move> best_move = std::nullopt;

    U64 board_hash = board.hash_key;
    auto tt_move_key = get_tt_move_key(board_hash);

    std::vector<Move> moves = generate_moves(board);
    moves = order_moves(board, moves, tt_move_key, 0);

    int original_alpha = alpha;
    int us = board.side_to_move;
    bool legal_found = false;

    for (const Move& move : moves) {
        if (time_is_up()) {
            stop_search = true;
            break;
        }

        UndoInfo undo = board.make_move(move);

        if (board.in_check(us)) {
            board.unmake_move(undo);
            continue;
        }

        legal_found = true;
        int score = -negamax(board, depth - 1, -beta, -alpha, 1);
        board.unmake_move(undo);

        if (stop_search) {
            break;
        }

        if (score > best_score) {
            best_score = score;
            best_move = move;
        }

        alpha = std::max(alpha, score);

        if (alpha >= beta) {
            break;
        }
    }

    if (!legal_found) {
        if (board.in_check(us)) {
            return {-MATE, std::nullopt};
        }

        return {0, std::nullopt};
    }

    if (!stop_search && best_move.has_value()) {
        int flag = TT_EXACT;

        if (best_score <= original_alpha) {
            flag = TT_UPPER;
        } else if (best_score >= beta) {
            flag = TT_LOWER;
        }

        store_tt(board_hash, depth, best_score, flag, move_key(*best_move));
    }

    return {best_score, best_move};
}

bool Engine::is_killer_move(int ply, const Move& move) const {
    if (ply >= MAX_PLY) {
        return false;
    }

    MoveKey key = move_key(move);

    return (killer_moves[ply][0].has_value() && *killer_moves[ply][0] == key)
        || (killer_moves[ply][1].has_value() && *killer_moves[ply][1] == key);
}

bool Engine::can_reduce_late_move(
    Board& board,
    const Move& move,
    int depth,
    int ply,
    int legal_moves_searched,
    const std::optional<MoveKey>& tt_move_key,
    bool in_check
) const {
    if (depth < LMR_MIN_DEPTH) {
        return false;
    }

    if (in_check) {
        return false;
    }

    if (legal_moves_searched <= LMR_FULL_DEPTH_MOVES) {
        return false;
    }

    if (tt_move_key.has_value() && move_key(move) == *tt_move_key) {
        return false;
    }

    if (is_noisy_move(board, move)) {
        return false;
    }

    if (is_killer_move(ply, move)) {
        return false;
    }

    return true;
}

int Engine::lmr_reduction(int depth, int legal_moves_searched) const {
    int reduction = 1 + static_cast<int>(
        std::log(depth) * std::log(std::max(legal_moves_searched, 1)) / 2.5
    );

    return std::max(1, std::min(reduction, depth - 1));
}

bool Engine::can_try_null_move(Board& board, int depth, int beta, int ply) const {
    if (depth < 3) {
        return false;
    }

    if (ply == 0) {
        return false;
    }

    if (beta >= MATE - 1000) {
        return false;
    }

    if (board.in_check(board.side_to_move)) {
        return false;
    }

    return board.has_non_pawn_material(board.side_to_move);
}

int Engine::negamax(
    Board& board,
    int depth,
    int alpha,
    int beta,
    int ply
) {
    if (ply >= MAX_PLY - 1) {
        return evaluate_quiet_position(board);
    }

    nodes += 1;

    if (nodes % TIME_CHECK_INTERVAL == 0 && time_is_up()) {
        stop_search = true;
        return 0;
    }

    U64 board_hash = board.hash_key;
    int original_alpha = alpha;

    auto entry_it = transposition_table.find(board_hash);

    if (entry_it != transposition_table.end() && entry_it->second.depth >= depth) {
        const TTEntry& entry = entry_it->second;
        tt_hits += 1;

        if (entry.flag == TT_EXACT) {
            return entry.score;
        }

        if (entry.flag == TT_LOWER) {
            alpha = std::max(alpha, entry.score);
        } else if (entry.flag == TT_UPPER) {
            beta = std::min(beta, entry.score);
        }

        if (alpha >= beta) {
            return entry.score;
        }
    }

    int us = board.side_to_move;
    bool in_check_node = board.in_check(us);

    if (depth <= 0) {
        if (in_check_node && ply < MAX_PLY - 1) {
            depth = 1;
        } else {
            return quiescence(board, alpha, beta, ply);
        }
    }

    if (
        depth <= 2
        && !in_check_node
        && std::abs(alpha) < MATE - 1000
        && std::abs(beta) < MATE - 1000
    ) {
        int static_eval = evaluate_position(board);

        if (static_eval + FUTILITY_MARGIN[depth] <= alpha) {
            return quiescence(board, alpha, beta, ply);
        }
    }

    if (can_try_null_move(board, depth, beta, ply)) {
        NullMoveUndo undo = board.make_null_move();

        int score = -negamax(
            board,
            depth - 1 - NULL_MOVE_REDUCTION,
            -beta,
            -beta + 1,
            ply + 1
        );

        board.unmake_null_move(undo);

        if (stop_search) {
            return 0;
        }

        if (score >= beta) {
            store_tt(
                board_hash,
                depth,
                beta,
                TT_LOWER,
                std::nullopt
            );

            return beta;
        }
    }

    std::optional<MoveKey> tt_move_key = std::nullopt;

    if (entry_it != transposition_table.end()) {
        tt_move_key = entry_it->second.best_move_key;
    }

    std::vector<Move> moves = generate_moves(board);
    moves = order_moves(board, moves, tt_move_key, ply);

    int best_score = -INF;
    std::optional<MoveKey> best_move_key = std::nullopt;
    bool legal_found = false;
    int legal_moves_searched = 0;

    for (const Move& move : moves) {
        bool reduce_late_move = can_reduce_late_move(
            board,
            move,
            depth,
            ply,
            legal_moves_searched,
            tt_move_key,
            in_check_node
        );

        UndoInfo undo = board.make_move(move);

        if (board.in_check(us)) {
            board.unmake_move(undo);
            continue;
        }

        legal_found = true;
        legal_moves_searched += 1;

        bool gives_check = board.in_check(board.side_to_move);
        int extension = gives_check && depth <= CHECK_EXTENSION_MAX_DEPTH && ply < MAX_PLY - 2 ? 1 : 0;
        int next_depth = depth - 1 + extension;

        int score;

        if (reduce_late_move) {
            int reduction = lmr_reduction(depth, legal_moves_searched);
            int reduced_depth = std::max(0, next_depth - reduction);

            score = -negamax(board, reduced_depth, -alpha - 1, -alpha, ply + 1);

            if (score > alpha && !stop_search) {
                score = -negamax(board, next_depth, -beta, -alpha, ply + 1);
            }
        } else {
            score = -negamax(board, next_depth, -beta, -alpha, ply + 1);
        }

        board.unmake_move(undo);

        if (stop_search) {
            return 0;
        }

        if (score > best_score) {
            best_score = score;
            best_move_key = move_key(move);
        }

        alpha = std::max(alpha, score);

        if (alpha >= beta) {
            if (!is_noisy_move(board, move)) {
                store_killer(ply, move);
                history[move.from_sq][move.to_sq] += depth * depth;
            }

            break;
        }
    }

    if (!legal_found) {
        if (in_check_node) {
            return -MATE + ply;
        }

        return 0;
    }

    int flag = TT_EXACT;

    if (best_score <= original_alpha) {
        flag = TT_UPPER;
    } else if (best_score >= beta) {
        flag = TT_LOWER;
    }

    store_tt(board_hash, depth, best_score, flag, best_move_key);

    return best_score;
}

int Engine::quiescence(Board& board, int alpha, int beta, int ply) {
    if (ply >= MAX_PLY - 1) {
        return evaluate_quiet_position(board);
    }

    nodes += 1;

    if (nodes % TIME_CHECK_INTERVAL == 0 && time_is_up()) {
        stop_search = true;
        return 0;
    }

    int us = board.side_to_move;

    if (board.in_check(us)) {
        std::vector<Move> moves = generate_moves(board);
        moves = order_moves(board, moves, std::nullopt, ply);

        bool legal_found = false;

        for (const Move& move : moves) {
            UndoInfo undo = board.make_move(move);

            if (board.in_check(us)) {
                board.unmake_move(undo);
                continue;
            }

            legal_found = true;
            int score = -quiescence(board, -beta, -alpha, ply + 1);
            board.unmake_move(undo);

            if (stop_search) {
                return 0;
            }

            if (score >= beta) {
                return beta;
            }

            alpha = std::max(alpha, score);
        }

        if (!legal_found) {
            return -MATE + ply;
        }

        return alpha;
    }

    int stand_pat = evaluate_quiet_position(board);

    if (stand_pat >= beta) {
        return beta;
    }

    if (stand_pat + MAX_PIECE_VALUE + DELTA_MARGIN < alpha) {
        return alpha;
    }

    alpha = std::max(alpha, stand_pat);

    std::vector<Move> noisy_moves;

    for (const Move& move : generate_moves(board)) {
        if (is_noisy_move(board, move)) {
            noisy_moves.push_back(move);
        }
    }

    noisy_moves = order_moves(board, noisy_moves, std::nullopt, ply);

    for (const Move& move : noisy_moves) {
        auto captured = board.piece_at(move.to_sq);

        if (captured.has_value()) {
            int captured_value = PIECE_VALUE[*captured];

            if (stand_pat + captured_value + DELTA_MARGIN <= alpha) {
                continue;
            }
        }

        UndoInfo undo = board.make_move(move);

        if (board.in_check(us)) {
            board.unmake_move(undo);
            continue;
        }

        int score = -quiescence(board, -beta, -alpha, ply + 1);
        board.unmake_move(undo);

        if (score >= beta) {
            return beta;
        }

        alpha = std::max(alpha, score);
    }

    return alpha;
}

bool Engine::is_noisy_move(const Board& board, const Move& move) const {
    if (move.promotion.has_value()) {
        return true;
    }

    if (move.is_en_passant) {
        return true;
    }

    return board.piece_at(move.to_sq).has_value();
}

void Engine::store_killer(int ply, const Move& move) {
    if (ply >= MAX_PLY) {
        return;
    }

    MoveKey key = move_key(move);

    if (killer_moves[ply][0].has_value() && *killer_moves[ply][0] == key) {
        return;
    }

    killer_moves[ply][1] = killer_moves[ply][0];
    killer_moves[ply][0] = key;
}

std::vector<Move> Engine::order_moves(
    Board& board,
    const std::vector<Move>& moves,
    const std::optional<MoveKey>& tt_move_key,
    int ply
) const {
    std::optional<Move> tt_move = std::nullopt;
    std::vector<Move> captures;
    std::optional<Move> killer_one = std::nullopt;
    std::optional<Move> killer_two = std::nullopt;
    std::vector<Move> quiets;

    std::optional<MoveKey> killer_key_one = std::nullopt;
    std::optional<MoveKey> killer_key_two = std::nullopt;

    if (ply < MAX_PLY) {
        killer_key_one = killer_moves[ply][0];
        killer_key_two = killer_moves[ply][1];
    }

    for (const Move& move : moves) {
        MoveKey key = move_key(move);

        if (tt_move_key.has_value() && key == *tt_move_key) {
            tt_move = move;
            continue;
        }

        if (is_noisy_move(board, move)) {
            captures.push_back(move);
            continue;
        }

        if (killer_key_one.has_value() && key == *killer_key_one) {
            killer_one = move;
            continue;
        }

        if (killer_key_two.has_value() && key == *killer_key_two) {
            killer_two = move;
            continue;
        }

        quiets.push_back(move);
    }

    std::sort(
        captures.begin(),
        captures.end(),
        [&](const Move& a, const Move& b) {
            return capture_score(board, a) > capture_score(board, b);
        }
    );

    std::vector<Move> ordered;

    if (tt_move.has_value()) {
        ordered.push_back(*tt_move);
    }

    ordered.insert(ordered.end(), captures.begin(), captures.end());

    if (killer_one.has_value()) {
        ordered.push_back(*killer_one);
    }

    if (killer_two.has_value()) {
        ordered.push_back(*killer_two);
    }

    std::vector<Move> good_quiets;
    std::vector<Move> other_quiets;

    for (const Move& move : quiets) {
        if (history[move.from_sq][move.to_sq] > 0) {
            good_quiets.push_back(move);
        } else {
            other_quiets.push_back(move);
        }
    }

    std::sort(
        good_quiets.begin(),
        good_quiets.end(),
        [&](const Move& a, const Move& b) {
            return history[a.from_sq][a.to_sq] > history[b.from_sq][b.to_sq];
        }
    );

    ordered.insert(ordered.end(), good_quiets.begin(), good_quiets.end());
    ordered.insert(ordered.end(), other_quiets.begin(), other_quiets.end());

    return ordered;
}

int Engine::capture_score(const Board& board, const Move& move) const {
    if (move.promotion.has_value()) {
        return 8'000 + PIECE_VALUE[*move.promotion];
    }

    if (move.is_en_passant) {
        return 10'100;
    }

    auto attacker = board.piece_at(move.from_sq);
    auto victim = board.piece_at(move.to_sq);

    if (!attacker.has_value() || !victim.has_value()) {
        return 0;
    }

    return 10'000 + 10 * PIECE_VALUE[*victim] - PIECE_VALUE[*attacker];
}

void Engine::store_tt(
    U64 board_hash,
    int depth,
    int score,
    int flag,
    std::optional<MoveKey> best_move_key
) {
    if (transposition_table.size() >= MAX_TT_SIZE) {
        transposition_table.clear();
    }

    auto old = transposition_table.find(board_hash);

    if (old == transposition_table.end() || depth >= old->second.depth) {
        transposition_table[board_hash] = TTEntry{
            depth,
            score,
            flag,
            best_move_key
        };
    }
}

std::optional<MoveKey> Engine::get_tt_move_key(U64 board_hash) const {
    auto entry = transposition_table.find(board_hash);

    if (entry == transposition_table.end()) {
        return std::nullopt;
    }

    return entry->second.best_move_key;
}