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
    transposition_table.assign(TT_SIZE, TTEntry{});
    reset_killers();
    reset_history();
}

void Engine::reset_killers() {
    for (auto& row : killer_moves) {
        row[0] = std::nullopt;
        row[1] = std::nullopt;
    }
}

void Engine::reset_history() {
    for (auto& row : history) {
        row.fill(0);
    }
}

namespace {

constexpr int MATE_THRESHOLD = MATE - 1000;

// Mate scores inside the search are root-relative ("mate at absolute ply m").
// TT entries must be node-relative ("mate in d plies from this position") so
// they stay valid when probed at a different ply, or in a later search after
// the game has advanced.
int score_to_tt(int score, int ply) {
    if (score > MATE_THRESHOLD) {
        return score + ply;
    }

    if (score < -MATE_THRESHOLD) {
        return score - ply;
    }

    return score;
}

int score_from_tt(int score, int ply) {
    if (score > MATE_THRESHOLD) {
        return score - ply;
    }

    if (score < -MATE_THRESHOLD) {
        return score + ply;
    }

    return score;
}

} // namespace

void Engine::clear_transposition_table() {
    transposition_table.assign(TT_SIZE, TTEntry{});
}

void Engine::clear_search_heuristics() {
    reset_killers();
    reset_history();
}

void Engine::clear_for_new_position() {
    // Keep the transposition table: entries are keyed by position hash and
    // remain valid as the game advances. Killers are ply-indexed and reset;
    // history is square-indexed and stays valid, so age it instead.
    reset_killers();

    for (auto& row : history) {
        for (int& value : row) {
            value /= 2;
        }
    }
}

void Engine::clear_for_new_game() {
    clear_transposition_table();
    clear_search_heuristics();
}

std::optional<MoveKey> Engine::valid_tt_move_key(
    U64 board_hash,
    const std::vector<Move>& moves
) const {
    const TTEntry& slot = transposition_table[board_hash & TT_MASK];

    if (slot.key != board_hash) {
        return std::nullopt;
    }

    if (!slot.best_move_key.has_value()) {
        return std::nullopt;
    }

    const MoveKey& key = *slot.best_move_key;

    for (const Move& move : moves) {
        if (move_key(move) == key) {
            return key;
        }
    }

    return std::nullopt;
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

    reset_killers();

    std::vector<Move> legal_moves = board.generate_legal_moves();
    std::optional<Move> best_move = std::nullopt;

    if (!legal_moves.empty()) {
        auto tt_key = valid_tt_move_key(board.hash_key, legal_moves);
        auto ordered = order_moves(board, legal_moves, tt_key, 0);
        best_move = ordered.front();
    }

    int best_score = best_move.has_value() ? board.evaluate() : -INF;
    int completed_depth = 0;

    for (int depth = 1; depth <= max_depth; ++depth) {
        int score;
        std::optional<Move> move;

        bool mate_range = std::abs(best_score) > MATE - 1000;

        if (depth == 1 || completed_depth == 0 || mate_range) {
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
                // Widen progressively before falling back to a full window.
                alpha = score - ASPIRATION_WINDOW * 4;
                beta = score + ASPIRATION_WINDOW * 4;

                result = negamax_root(board, depth, alpha, beta);
                score = result.first;
                move = result.second;

                if (!stop_search && (score <= alpha || score >= beta)) {
                    result = negamax_root(board, depth, -INF, INF);
                    score = result.first;
                    move = result.second;
                }
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
            << " tbhits " << tt_hits
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

    std::vector<Move> moves = generate_moves(board);
    auto tt_move_key = valid_tt_move_key(board_hash, moves);
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

        store_tt(board_hash, depth, score_to_tt(best_score, 0), flag, move_key(*best_move));
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

    // Draw detection must precede the TT probe: repetition is a property of
    // the path taken, and a stored score for this position must not mask a
    // draw on this particular path.
    if (ply > 0 && (board.halfmove_clock >= 100 || board.is_repetition())) {
        return 0;
    }

    U64 board_hash = board.hash_key;
    int original_alpha = alpha;

    const TTEntry& tt_slot = transposition_table[board_hash & TT_MASK];

    if (tt_slot.key == board_hash && tt_slot.depth >= depth) {
        const TTEntry& entry = tt_slot;
        tt_hits += 1;

        int tt_score = score_from_tt(entry.score, ply);

        if (entry.flag == TT_EXACT) {
            return tt_score;
        }

        if (entry.flag == TT_LOWER) {
            alpha = std::max(alpha, tt_score);
        } else if (entry.flag == TT_UPPER) {
            beta = std::min(beta, tt_score);
        }

        if (alpha >= beta) {
            return tt_score;
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
            depth - 1 - (NULL_MOVE_REDUCTION + (depth >= 6 ? 1 : 0)),
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
                score_to_tt(beta, ply),
                TT_LOWER,
                std::nullopt
            );

            return beta;
        }
    }

    std::vector<Move> moves = generate_moves(board);
    std::optional<MoveKey> tt_move_key = valid_tt_move_key(board_hash, moves);
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

        if (legal_moves_searched == 1) {
            // First move: full window (the presumed PV).
            score = -negamax(board, next_depth, -beta, -alpha, ply + 1);
        } else {
            // PVS: prove later moves are worse with a null window, possibly
            // LMR-reduced. Re-search at full depth, then full window, only on
            // surprise.
            int reduction = reduce_late_move
                ? lmr_reduction(depth, legal_moves_searched)
                : 0;
            int reduced_depth = std::max(0, next_depth - reduction);

            score = -negamax(board, reduced_depth, -alpha - 1, -alpha, ply + 1);

            if (score > alpha && reduction > 0 && !stop_search) {
                score = -negamax(board, next_depth, -alpha - 1, -alpha, ply + 1);
            }

            if (score > alpha && score < beta && !stop_search) {
                score = -negamax(board, next_depth, -beta, -alpha, ply + 1);
            }
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
                int& hist = history[move.from_sq][move.to_sq];
                hist = std::min(hist + depth * depth, 1'000'000);
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

    store_tt(board_hash, depth, score_to_tt(best_score, ply), flag, best_move_key);

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
        moves = order_moves(board, moves, std::nullopt, ply, false);

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

    int stand_pat = board.evaluate(alpha, beta);

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

    noisy_moves = order_moves(board, noisy_moves, std::nullopt, ply, false);

    for (const Move& move : noisy_moves) {
        auto captured = board.piece_at(move.to_sq);

        if (captured.has_value()) {
            int captured_value = PIECE_VALUE[*captured];

            if (stand_pat + captured_value + DELTA_MARGIN <= alpha) {
                continue;
            }
        }

        // SEE pruning: skip captures that lose material by static exchange.
        // Only reached when not in check (evasions take the path above), so it
        // is always safe to discard a losing capture here. Promotions are
        // excluded from SEE and never pruned.
        if (!move.promotion.has_value() && !board.see_ge(move, 0)) {
            continue;
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
    int ply,
    bool split_bad_captures
) const {
    std::optional<Move> tt_move = std::nullopt;
    std::optional<Move> killer_one = std::nullopt;
    std::optional<Move> killer_two = std::nullopt;

    // Score each move exactly once; the sorts below compare cached values
    // instead of recomputing scores inside the comparator.
    std::vector<std::pair<Move, int>> captures;
    std::vector<std::pair<Move, int>> bad_captures;
    std::vector<std::pair<Move, int>> good_quiets;
    std::vector<Move> other_quiets;

    captures.reserve(moves.size());
    good_quiets.reserve(moves.size());
    other_quiets.reserve(moves.size());

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
            int cscore = capture_score(board, move);

            // Split captures by static exchange: losing captures (SEE < 0) are
            // demoted to their own bucket, placed below killers but above quiets
            // during assembly. Promotions are excluded from SEE and always stay
            // in the main capture bucket. Only the main search splits; quiescence
            // orders captures as before (it prunes losing captures itself, so a
            // split there would just pay for SEE twice in the hottest path).
            if (split_bad_captures && !move.promotion.has_value()
                    && !board.see_ge(move, 0)) {
                bad_captures.emplace_back(move, cscore);
            } else {
                captures.emplace_back(move, cscore);
            }
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

        int hist = history[move.from_sq][move.to_sq];

        if (hist > 0) {
            good_quiets.emplace_back(move, hist);
        } else {
            other_quiets.push_back(move);
        }
    }

    std::sort(
        captures.begin(),
        captures.end(),
        [](const std::pair<Move, int>& a, const std::pair<Move, int>& b) {
            return a.second > b.second;
        }
    );

    std::sort(
        bad_captures.begin(),
        bad_captures.end(),
        [](const std::pair<Move, int>& a, const std::pair<Move, int>& b) {
            return a.second > b.second;
        }
    );

    std::sort(
        good_quiets.begin(),
        good_quiets.end(),
        [](const std::pair<Move, int>& a, const std::pair<Move, int>& b) {
            return a.second > b.second;
        }
    );

    std::vector<Move> ordered;
    ordered.reserve(moves.size());

    if (tt_move.has_value()) {
        ordered.push_back(*tt_move);
    }

    for (const auto& [move, score] : captures) {
        ordered.push_back(move);
    }

    if (killer_one.has_value()) {
        ordered.push_back(*killer_one);
    }

    if (killer_two.has_value()) {
        ordered.push_back(*killer_two);
    }

    // Losing captures: tried after the TT move, winning captures, and killers,
    // but ahead of quiet moves. A forcing capture, even one that loses material
    // by static exchange, is usually worth trying before a random quiet --
    // measured clearly better than demoting them below all quiets (the latter
    // raised fixed-depth node counts, since SEE is pin-blind and sometimes
    // mislabels a tactically winning capture as losing).
    for (const auto& [move, score] : bad_captures) {
        ordered.push_back(move);
    }

    for (const auto& [move, score] : good_quiets) {
        ordered.push_back(move);
    }

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
    TTEntry& slot = transposition_table[board_hash & TT_MASK];

    // Replace if the slot holds a different position, or ours is searched at
    // least as deep. The table never wipes; old entries age out per slot.
    if (slot.key != board_hash || depth >= slot.depth) {
        slot = TTEntry{board_hash, depth, score, flag, best_move_key};
    }
}

std::optional<MoveKey> Engine::get_tt_move_key(U64 board_hash) const {
    const TTEntry& slot = transposition_table[board_hash & TT_MASK];

    if (slot.key != board_hash) {
        return std::nullopt;
    }

    return slot.best_move_key;
}