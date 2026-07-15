#include "search.hpp"
#include "nnue.hpp"

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

#if SGR_CONTHIST
    conthist.assign(12 * 64 * 12 * 64, 0);
#endif
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
    // Keep the TT (entries stay valid as the game advances). Killers are
    // ply-indexed, so reset them; history stays useful, so halve it instead.
    reset_killers();

    for (auto& row : history) {
        for (int& value : row) {
            value /= 2;
        }
    }

#if SGR_CONTHIST
    for (int& value : conthist) {
        value /= 2;
    }
#endif
}

void Engine::clear_for_new_game() {
    clear_transposition_table();
    clear_search_heuristics();
}

std::optional<Move> Engine::valid_tt_move_key(
    U64 board_hash,
    const MoveList& moves
) const {
    const TTEntry& slot = transposition_table[board_hash & TT_MASK];

    if (slot.key != board_hash) {
        return std::nullopt;
    }

    if (!slot.best_move.has_value()) {
        return std::nullopt;
    }

    const Move& key = *slot.best_move;

    for (const Move& move : moves) {
        if (move == key) {
            return key;
        }
    }

    return std::nullopt;
}

SearchResult Engine::search_best_move(
    Board& board,
    int max_depth,
    std::optional<double> limit,
    std::optional<long long> nodes_arg,
    std::optional<double> soft_arg
) {
    nodes = 0;
    tt_hits = 0;
    start_time = std::chrono::steady_clock::now();
    time_limit = limit;
    soft_time_limit = soft_arg;
    node_limit = nodes_arg;
    stop_search = false;

    // Build the accumulators for the root position; make/unmake keep them in
    // sync through the tree.
    if (nnue::active()) nnue::refresh(board);

    reset_killers();

#if SGR_CONTHIST
    ss_piece.fill(-1);   // no previous move anywhere until a make records one
#endif

    MoveList legal_moves = board.generate_legal_moves();
    std::optional<Move> best_move = std::nullopt;

    if (!legal_moves.empty()) {
        auto tt_key = valid_tt_move_key(board.hash_key, legal_moves);
        auto ordered = order_moves(board, legal_moves, tt_key, 0);
        best_move = ordered[0];
    }

    int best_score = best_move.has_value() ? board.evaluate() : -INF;
    int completed_depth = 0;

#if SGR_BMSTAB
    std::optional<Move> prev_root_best = std::nullopt;
    int bm_stable = 0;   // consecutive iterations the root best move has held
#endif

    for (int depth = 1; depth <= max_depth; ++depth) {
        // Soft limit: once this far into the budget a deeper pass almost never
        // finishes before the hard deadline, so keep the last completed depth
        // rather than spending the rest of the clock on a search we discard.
        // The budget is scaled by best-move stability (stretched while the root
        // move is still changing, trimmed once it has settled) and clamped to
        // the hard deadline. Depth 1 always runs so a searched move exists.
        if (depth > 1 && soft_time_limit.has_value()) {
            double soft = *soft_time_limit;
#if SGR_BMSTAB
            soft *= BM_STABILITY_FACTOR[std::min(bm_stable, BM_STABILITY_COUNT - 1)];
#endif
            if (time_limit.has_value()) {
                soft = std::min(soft, *time_limit);
            }
            if (elapsed_seconds(start_time) >= soft) {
                break;
            }
        }

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
#if SGR_BMSTAB
            bm_stable = (prev_root_best.has_value() && *move == *prev_root_best)
                            ? bm_stable + 1 : 0;
            prev_root_best = move;
#endif
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

MoveList Engine::generate_moves(Board& board) const {
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

    MoveList moves = generate_moves(board);
    auto tt_move_key = valid_tt_move_key(board_hash, moves);
    moves = order_moves(board, moves, tt_move_key, 0);
    LegalityInfo li = board.legality_info();

    int original_alpha = alpha;
    int us = board.side_to_move;
    bool legal_found = false;

#if SGR_IMPROVING
    // Seed ply 0 so interior nodes at ply 2 have a same-side reference.
    ss_static_eval[0] = board.in_check(us)
        ? NO_STATIC_EVAL
        : evaluate_position(board);
#endif

    for (const Move& move : moves) {
        if (time_is_up() || (node_limit.has_value() && nodes >= *node_limit)) {
            stop_search = true;
            break;
        }

        if (!board.is_legal(move, li)) {
            continue;
        }

        legal_found = true;
        UndoInfo undo = board.make_move(move);
#if SGR_CONTHIST
        ss_piece[0] = undo.placed_piece;
        ss_to[0] = move.to();
#endif
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

        store_tt(board_hash, depth, score_to_tt(best_score, 0), flag, *best_move);
    }

    return {best_score, best_move};
}

bool Engine::is_killer_move(int ply, const Move& move) const {
    if (ply >= MAX_PLY) {
        return false;
    }

    Move key = move;

    return (killer_moves[ply][0].has_value() && *killer_moves[ply][0] == key)
        || (killer_moves[ply][1].has_value() && *killer_moves[ply][1] == key);
}

bool Engine::can_reduce_late_move(
    Board& board,
    const Move& move,
    int depth,
    int ply,
    int legal_moves_searched,
    const std::optional<Move>& tt_move_key,
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

    if (tt_move_key.has_value() && move == *tt_move_key) {
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
    int ply,
    std::optional<Move> excluded
) {
    if (ply >= MAX_PLY - 1) {
        return evaluate_quiet_position(board);
    }

    nodes += 1;

    if (node_limit.has_value() && nodes >= *node_limit) {
        stop_search = true;
        return 0;
    }

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

    // With a move excluded the stored entry describes a different search, so
    // no TT cutoff (and no store below); the entry is still read for the
    // singular test's own conditions.
    if (!excluded.has_value() && tt_slot.key == board_hash && tt_slot.depth >= depth) {
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

#if SGR_IMPROVING
    // Record the static eval for this ply and compare with the same side's
    // eval two plies up. An in-check ply records the sentinel: it has no
    // meaningful static eval, and a comparison through one counts as not
    // improving (the conservative side -- full RFP margin, halved LMP budget).
    int node_static_eval = NO_STATIC_EVAL;
    bool improving = false;

    if (!in_check_node) {
        node_static_eval = evaluate_position(board);
        improving = ply >= 2
            && ss_static_eval[ply - 2] != NO_STATIC_EVAL
            && node_static_eval > ss_static_eval[ply - 2];
    }

    ss_static_eval[ply] = node_static_eval;
#endif

#if SGR_RFP
    // Reverse futility: the mirror of the futility block below. If the static
    // eval is so far above beta that a conservative margin per remaining ply
    // cannot pull it back under, trust it and stand pat. Same mate and check
    // guards as futility; like the futility return, nothing is TT-stored.
    if (
        depth <= RFP_MAX_DEPTH
        && !in_check_node
        && std::abs(alpha) < MATE - 1000
        && std::abs(beta) < MATE - 1000
    ) {
#if SGR_IMPROVING
        // A rising eval is a more trustworthy bound, so one ply of margin is
        // waived; at depth 1 improving this prunes on eval >= beta alone.
        int rfp_eval = node_static_eval;

        if (rfp_eval - RFP_MARGIN * (depth - (improving ? 1 : 0)) >= beta) {
#else
        int rfp_eval = evaluate_position(board);

        if (rfp_eval - RFP_MARGIN * depth >= beta) {
#endif
            return rfp_eval;
        }
    }
#endif

    if (
        depth <= 2
        && !in_check_node
        && std::abs(alpha) < MATE - 1000
        && std::abs(beta) < MATE - 1000
    ) {
#if SGR_IMPROVING
        int static_eval = node_static_eval;   // already computed above
#else
        int static_eval = evaluate_position(board);
#endif

        if (static_eval + FUTILITY_MARGIN[depth] <= alpha) {
            return quiescence(board, alpha, beta, ply);
        }
    }

    // No null move with a move excluded: the verdict must come from the
    // remaining moves themselves.
    if (!excluded.has_value() && can_try_null_move(board, depth, beta, ply)) {
        NullMoveUndo undo = board.make_null_move();
#if SGR_CONTHIST
        ss_piece[ply] = -1;   // a null move is no follow-up context
#endif

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

    MoveList moves = generate_moves(board);
    std::optional<Move> tt_move_key = valid_tt_move_key(board_hash, moves);
    moves = order_moves(board, moves, tt_move_key, ply);
    LegalityInfo li = board.legality_info();

#if SGR_SINGULAR
    // Singular extension test: the TT move carries a lower-bound score from a
    // search nearly as deep as this node. Search the OTHER moves, reduced,
    // against a window a margin below that score; if none reaches it, the TT
    // move is the position's only good move and earns one extra ply in the
    // loop below.
    int singular_extension = 0;

    if (
        depth >= SINGULAR_MIN_DEPTH
        && !excluded.has_value()
        && tt_move_key.has_value()
        && ply < MAX_PLY - 2
        && tt_slot.key == board_hash
        && tt_slot.flag != TT_UPPER
        && tt_slot.depth >= depth - SINGULAR_TT_DEPTH_SLACK
    ) {
        // Copy out of the TT before recursing: the helper search may replace
        // this slot.
        int tt_score = score_from_tt(tt_slot.score, ply);

        if (std::abs(tt_score) < MATE_THRESHOLD) {
            int singular_beta = tt_score - SINGULAR_MARGIN * depth;

            int singular_score = negamax(
                board,
                (depth - 1) / 2,
                singular_beta - 1,
                singular_beta,
                ply,
                tt_move_key
            );

            if (!stop_search && singular_score < singular_beta) {
                singular_extension = 1;
            }
        }
    }
#endif

    int best_score = -INF;
    std::optional<Move> best_move_key = std::nullopt;
    bool legal_found = false;
    int legal_moves_searched = 0;

#if SGR_HMALUS
    // Quiets searched at this node, in order; on a quiet beta cutoff every
    // earlier entry is a quiet that failed where the cutoff move succeeded.
    Move tried_quiets[256];
    int n_tried = 0;
#endif

    for (const Move& move : moves) {
        if (!board.is_legal(move, li)) {
            continue;
        }

        if (excluded.has_value() && move == *excluded) {
            continue;
        }

#if SGR_LMP
        // Late move pruning: enough quiets have been searched at this shallow
        // depth without a cutoff; the rest are ordered worst-by-history and
        // almost never matter. Killers are exempt, captures and promotions
        // are never pruned, and the threshold guarantees legal_found is
        // already true. Placed before the malus recording below so a pruned
        // (never-searched) quiet cannot be penalised at a cutoff.
        // The depth guard must precede the LMP_COUNT[] lookup: the table only
        // covers depths 0..LMP_MAX_DEPTH.
#if SGR_IMPROVING
        // A falling eval halves the quiet budget: the worst-ordered quiets
        // are even less likely to rescue a position trending downward.
        int lmp_budget = depth <= LMP_MAX_DEPTH
            ? (improving ? LMP_COUNT[depth] : LMP_COUNT[depth] / 2)
            : 0;
#else
        int lmp_budget = depth <= LMP_MAX_DEPTH ? LMP_COUNT[depth] : 0;
#endif
        if (
            depth <= LMP_MAX_DEPTH
            && !in_check_node
            && legal_moves_searched >= lmp_budget
            && std::abs(alpha) < MATE - 1000
            && !is_noisy_move(board, move)
            && !is_killer_move(ply, move)
        ) {
            continue;
        }
#endif

#if SGR_HMALUS
        if (!is_noisy_move(board, move)) {
            tried_quiets[n_tried++] = move;
        }
#endif

        bool reduce_late_move = can_reduce_late_move(
            board,
            move,
            depth,
            ply,
            legal_moves_searched,
            tt_move_key,
            in_check_node
        );

        legal_found = true;
        legal_moves_searched += 1;

        UndoInfo undo = board.make_move(move);
#if SGR_CONTHIST
        ss_piece[ply] = undo.placed_piece;
        ss_to[ply] = move.to();
#endif

        bool gives_check = board.in_check(board.side_to_move);
        int extension = gives_check && depth <= CHECK_EXTENSION_MAX_DEPTH && ply < MAX_PLY - 2 ? 1 : 0;
#if SGR_SINGULAR
        if (
            singular_extension
            && tt_move_key.has_value()
            && move == *tt_move_key
        ) {
            extension = std::max(extension, singular_extension);
        }
#endif
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

#if SGR_HISTLMR
            // The quiet's history record adjusts its reduction: proven quiets
            // are reduced less, serial failures more. can_reduce_late_move has
            // already filtered to non-TT, non-killer quiets.
            if (reduction > 0) {
                int hist_score = history[move.from()][move.to()];
#if SGR_CONTHIST
                if (ply > 0 && ss_piece[ply - 1] >= 0) {
                    hist_score += conthist[conthist_index(
                        ss_piece[ply - 1], ss_to[ply - 1],
                        ss_piece[ply], move.to())];
                }
#endif
                reduction -= std::clamp(
                    hist_score / HISTLMR_DIV, -HISTLMR_MAX, HISTLMR_MAX);
                reduction = std::max(0, std::min(reduction, next_depth - 1));
            }
#endif
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
            best_move_key = move;
        }

        alpha = std::max(alpha, score);

        if (alpha >= beta) {
            if (!is_noisy_move(board, move)) {
                store_killer(ply, move);

                int bonus = depth * depth;
                int& hist = history[move.from()][move.to()];
                hist = std::min(hist + bonus, HISTORY_MAX);

#if SGR_CONTHIST
                // The move has been unmade, so piece_at(from) is the mover.
                int prev_piece = ply > 0 ? ss_piece[ply - 1] : -1;
                int prev_to = ply > 0 ? ss_to[ply - 1] : 0;

                if (prev_piece >= 0) {
                    auto piece = board.piece_at(move.from());
                    if (piece.has_value()) {
                        int& ch = conthist[conthist_index(
                            prev_piece, prev_to, *piece, move.to())];
                        ch = std::min(ch + bonus, HISTORY_MAX);
                    }
                }
#endif

#if SGR_HMALUS
                // Penalise the quiets tried before the cutoff move (the last
                // entry is the cutoff move itself), so moves that keep failing
                // sink in the ordering instead of staying at a flattering peak.
                for (int i = 0; i < n_tried - 1; ++i) {
                    const Move& q = tried_quiets[i];
                    int& qh = history[q.from()][q.to()];
                    qh = std::max(qh - bonus, -HISTORY_MAX);

#if SGR_CONTHIST
                    if (prev_piece >= 0) {
                        auto qp = board.piece_at(q.from());
                        if (qp.has_value()) {
                            int& qch = conthist[conthist_index(
                                prev_piece, prev_to, *qp, q.to())];
                            qch = std::max(qch - bonus, -HISTORY_MAX);
                        }
                    }
#endif
                }
#endif
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

    // An excluded-move search describes a position minus one move; storing it
    // would poison later probes of the real position.
    if (!excluded.has_value()) {
        store_tt(board_hash, depth, score_to_tt(best_score, ply), flag, best_move_key);
    }

    return best_score;
}

int Engine::quiescence(Board& board, int alpha, int beta, int ply) {
    if (ply >= MAX_PLY - 1) {
        return evaluate_quiet_position(board);
    }

    nodes += 1;

    if (node_limit.has_value() && nodes >= *node_limit) {
        stop_search = true;
        return 0;
    }

    if (nodes % TIME_CHECK_INTERVAL == 0 && time_is_up()) {
        stop_search = true;
        return 0;
    }

    int us = board.side_to_move;

    if (board.in_check(us)) {
        MoveList moves = generate_moves(board);
        moves = order_moves(board, moves, std::nullopt, ply, false);
        LegalityInfo li = board.legality_info();

        bool legal_found = false;

        for (const Move& move : moves) {
            if (!board.is_legal(move, li)) {
                continue;
            }

            legal_found = true;
            UndoInfo undo = board.make_move(move);
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

    MoveList noisy_moves;

    for (const Move& move : generate_moves(board)) {
        if (is_noisy_move(board, move)) {
            noisy_moves.add(move);
        }
    }

    noisy_moves = order_moves(board, noisy_moves, std::nullopt, ply, false);
    LegalityInfo li = board.legality_info();

    for (const Move& move : noisy_moves) {
        auto captured = board.piece_at(move.to());

        if (captured.has_value()) {
            int captured_value = PIECE_VALUE[*captured];

            if (stand_pat + captured_value + DELTA_MARGIN <= alpha) {
                continue;
            }
        }

        // SEE pruning: skip captures that lose material by static exchange.
        // Never reached while in check (evasions take the path above), and
        // promotions are never pruned.
        if (!move.is_promotion() && !board.see_ge(move, 0)) {
            continue;
        }

        if (!board.is_legal(move, li)) {
            continue;
        }

        UndoInfo undo = board.make_move(move);
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
    if (move.is_promotion()) {
        return true;
    }

    if (move.is_en_passant()) {
        return true;
    }

    return board.piece_at(move.to()).has_value();
}

void Engine::store_killer(int ply, const Move& move) {
    if (ply >= MAX_PLY) {
        return;
    }

    Move key = move;

    if (killer_moves[ply][0].has_value() && *killer_moves[ply][0] == key) {
        return;
    }

    killer_moves[ply][1] = killer_moves[ply][0];
    killer_moves[ply][0] = key;
}

MoveList Engine::order_moves(
    Board& board,
    const MoveList& moves,
    const std::optional<Move>& tt_move_key,
    int ply,
    bool split_bad_captures
) const {
    std::optional<Move> tt_move = std::nullopt;
    std::optional<Move> killer_one = std::nullopt;
    std::optional<Move> killer_two = std::nullopt;

    // Score each move once; the sorts below compare cached values instead of
    // recomputing scores inside the comparator.
    struct Scored { Move move; int score; };
    Scored captures[256];     int n_cap = 0;
    Scored bad_captures[256]; int n_bad = 0;
    Scored good_quiets[256];  int n_gq  = 0;
    Scored other_quiets[256]; int n_oq  = 0;

    std::optional<Move> killer_key_one = std::nullopt;
    std::optional<Move> killer_key_two = std::nullopt;

    if (ply < MAX_PLY) {
        killer_key_one = killer_moves[ply][0];
        killer_key_two = killer_moves[ply][1];
    }

    for (const Move& move : moves) {
        Move key = move;

        if (tt_move_key.has_value() && key == *tt_move_key) {
            tt_move = move;
            continue;
        }

        if (is_noisy_move(board, move)) {
            int cscore = capture_score(board, move);

            // Losing captures (SEE < 0) get their own bucket, placed below
            // killers but above quiets. Promotions always stay in the main
            // capture bucket. Quiescence doesn't split: it SEE-prunes losing
            // captures itself, so splitting would pay for SEE twice.
            if (split_bad_captures && !move.is_promotion()
                    && !board.see_ge(move, 0)) {
                bad_captures[n_bad++] = {move, cscore};
            } else {
                captures[n_cap++] = {move, cscore};
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

        int hist = history[move.from()][move.to()];

#if SGR_CONTHIST
        // Add the follow-up score for the previous ply's move. Quiescence
        // passes split_bad_captures=false and skips this: it neither records
        // moves on the ply stack nor benefits from quiet ordering.
        if (split_bad_captures && ply > 0 && ss_piece[ply - 1] >= 0) {
            auto piece = board.piece_at(move.from());
            if (piece.has_value()) {
                hist += conthist[conthist_index(
                    ss_piece[ply - 1], ss_to[ply - 1], *piece, move.to())];
            }
        }
#endif

        if (hist > 0) {
            good_quiets[n_gq++] = {move, hist};
        } else {
            other_quiets[n_oq++] = {move, hist};
        }
    }

    auto by_score = [](const Scored& a, const Scored& b) {
        return a.score > b.score;
    };

    std::sort(captures, captures + n_cap, by_score);
    std::sort(bad_captures, bad_captures + n_bad, by_score);
    std::sort(good_quiets, good_quiets + n_gq, by_score);
#if SGR_HMALUS || SGR_CONTHIST
    // With malus / continuation scores these can be genuinely negative, so
    // order them least-bad first. Without either feature every score here is
    // exactly zero and the sort would be a no-op, so it is compiled out.
    std::sort(other_quiets, other_quiets + n_oq, by_score);
#endif

    MoveList ordered;

    if (tt_move.has_value()) {
        ordered.add(*tt_move);
    }

    for (int i = 0; i < n_cap; ++i) {
        ordered.add(captures[i].move);
    }

    if (killer_one.has_value()) {
        ordered.add(*killer_one);
    }

    if (killer_two.has_value()) {
        ordered.add(*killer_two);
    }

    // Losing captures go after the killers but ahead of quiet moves. SEE is
    // pin-blind and sometimes mislabels a winning capture, and a forcing
    // capture is usually worth trying before a random quiet; demoting them
    // below all quiets tested worse.
    for (int i = 0; i < n_bad; ++i) {
        ordered.add(bad_captures[i].move);
    }

    for (int i = 0; i < n_gq; ++i) {
        ordered.add(good_quiets[i].move);
    }

    for (int i = 0; i < n_oq; ++i) {
        ordered.add(other_quiets[i].move);
    }

    return ordered;
}

int Engine::capture_score(const Board& board, const Move& move) const {
    if (move.is_promotion()) {
        return 8'000 + PIECE_VALUE[move.promo_piece(board.side_to_move)];
    }

    if (move.is_en_passant()) {
        return 10'100;
    }

    auto attacker = board.piece_at(move.from());
    auto victim = board.piece_at(move.to());

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
    std::optional<Move> best_move_key
) {
    TTEntry& slot = transposition_table[board_hash & TT_MASK];

    // Replace if the slot holds a different position, or ours is searched at
    // least as deep. The table never wipes; old entries age out per slot.
    if (slot.key != board_hash || depth >= slot.depth) {
        slot = TTEntry{board_hash, depth, score, flag, best_move_key};
    }
}

std::optional<Move> Engine::get_tt_move(U64 board_hash) const {
    const TTEntry& slot = transposition_table[board_hash & TT_MASK];

    if (slot.key != board_hash) {
        return std::nullopt;
    }

    return slot.best_move;
}