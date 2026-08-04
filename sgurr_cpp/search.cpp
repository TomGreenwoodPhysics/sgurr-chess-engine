#include "search.hpp"
#include "nnue.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <iostream>
#include <new>
#include <string>

namespace {

constexpr std::array<int, 12> PIECE_VALUE = {
    100, 320, 330, 500, 900, 0,
    100, 320, 330, 500, 900, 0
};

constexpr int MAX_PIECE_VALUE = 900;

// The LMP quiet budget by depth. Was a constexpr table {0, 6, 12, 18};
// the three live entries are tunable now, so it becomes a lookup that
// reads them. Depth is already guarded to <= lmp_max_depth by the caller.
int lmp_count_for(int depth) {
    switch (depth) {
        case 1:  return params.lmp_count_1;
        case 2:  return params.lmp_count_2;
        case 3:  return params.lmp_count_3;
        default: return params.lmp_count_3;
    }
}

double elapsed_seconds(std::chrono::steady_clock::time_point start) {
    using namespace std::chrono;
    return duration<double>(steady_clock::now() - start).count();
}

} // namespace

Engine::Engine() {
    // The LMR table is derived from params and starts zeroed. Without this the
    // engine would reduce every late move by 0 plies -- a silent, catastrophic
    // behaviour change rather than a crash, so it is built here where every
    // path that can search must pass.
    refresh_derived_params();
    resize_hash(DEFAULT_HASH_MB);
    reset_killers();
    reset_history();
}

void Engine::resize_hash(int mb) {
    mb = std::clamp(mb, MIN_HASH_MB, MAX_HASH_MB);

    std::size_t entries = (static_cast<std::size_t>(mb) * 1024 * 1024) / sizeof(TTEntry);

    // Round DOWN to a power of two. The probe indexes with `hash & tt_mask`,
    // which is one AND on the hottest path in the engine; a non-power-of-two
    // size would force a modulo there. Rounding down rather than up also keeps
    // the table inside the megabytes the user actually asked for.
    std::size_t pow2 = 1;
    while (pow2 * 2 <= entries) {
        pow2 *= 2;
    }

    // Allocation can fail outright at the top of the range -- 4096 MB is a
    // 3.2 GB request once rounded. Falling back to the default is strictly
    // better than letting bad_alloc escape and kill the engine mid-game, and
    // the fallback is announced rather than silent.
    try {
        std::vector<TTEntry> fresh(pow2, TTEntry{});
        transposition_table.swap(fresh);
        tt_size = pow2;
        tt_mask = pow2 - 1;
    } catch (const std::bad_alloc&) {
        std::cerr << "info string Hash: could not allocate " << mb
                  << " MB, keeping " << (tt_size / 1024) << "k entries\n";
        if (tt_size == 0) {                     // nothing usable yet: must not
            tt_size = 1 << 16;                  // leave the table empty, since
            tt_mask = tt_size - 1;              // every probe indexes into it
            transposition_table.assign(tt_size, TTEntry{});
        }
    }
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

#if SGR_CAPHIST
    caphist.fill(0);
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

// The UCI `score` field.
//
// A forced mate must be reported as `score mate <moves>` -- positive when this
// side is delivering it, negative when receiving it. Reporting it as a
// centipawn value instead makes a GUI display a mate as a ~10,000-pawn
// advantage, which is how this engine behaved until now.
//
// Internally a mate is encoded root-relative as MATE - plies (negamax returns
// -MATE + ply at a checkmated node), so plies-to-mate is MATE - |score|, and
// UCI wants MOVES, hence the round-up by (plies + 1) / 2.
//
// The |score| <= MATE guards keep the +/-INF sentinel -- used as the initial
// best_score when a search is started on a position with no legal moves --
// out of the mate band, so it falls through to a centipawn score rather than
// being reported as a nonsensical mate distance.
std::string uci_score(int score) {
    if (score > MATE_THRESHOLD && score <= MATE) {
        return "mate " + std::to_string((MATE - score + 1) / 2);
    }

    if (score < -MATE_THRESHOLD && score >= -MATE) {
        // A root that is ALREADY mate is zero moves away, and "-0" is not a
        // number any GUI should be handed. Zero is unsigned.
        int moves = (MATE + score + 1) / 2;
        return moves == 0 ? "mate 0" : "mate -" + std::to_string(moves);
    }

    return "cp " + std::to_string(score);
}

} // namespace

void Engine::clear_transposition_table() {
    transposition_table.assign(tt_size, TTEntry{});
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

#if SGR_CAPHIST
    for (int& value : caphist) {
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
    const TTEntry& slot = transposition_table[board_hash & tt_mask];

    if (slot.key != board_hash) {
        return std::nullopt;
    }

    if (slot.best_move == NO_MOVE) {
        return std::nullopt;
    }

    const Move key = slot.best_move;

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
            soft *= params.bm_stability_x100[
                        std::min(bm_stable, BM_STABILITY_COUNT - 1)] / 100.0;
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
            int alpha = best_score - params.aspiration_window;
            int beta = best_score + params.aspiration_window;

            auto result = negamax_root(board, depth, alpha, beta);
            score = result.first;
            move = result.second;

            if (!stop_search && (score <= alpha || score >= beta)) {
                // Widen progressively before falling back to a full window.
                alpha = score - params.aspiration_window * 4;
                beta = score + params.aspiration_window * 4;

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
        } else if (completed_depth == 0) {
            // Terminal root: checkmate or stalemate, so there is no move to
            // report, but negamax_root's score (-MATE or 0) IS meaningful.
            // Without this, best_score keeps its -INF initialiser and the info
            // line reports `score cp -10000000` -- a ~100,000-pawn evaluation
            // where a mate or a draw belongs.
            best_score = score;
        }

        long long ms = static_cast<long long>(elapsed_seconds(start_time) * 1000);

        // `tbhits` used to carry the transposition-table hit count here. That
        // field means ENDGAME TABLEBASE hits in UCI, and this engine has no
        // tablebases, so any GUI or PGN tracker reading it recorded nonsense
        // (fastchess has a track_tbhits switch that would have done exactly
        // that). TT health belongs in `hashfull`, which is what it now
        // reports; tt_hits is still counted and still returned in
        // SearchResult, it is simply no longer mislabelled on the wire.
        std::cout
            << "info depth " << depth
            << " score " << uci_score(best_score)
            << " nodes " << nodes
            // Divide by at least 1ms: an iteration that completes inside the
            // clock's resolution would otherwise report the raw node count as
            // a rate, which reads as an absurdly SLOW engine at shallow depth.
            << " nps " << (nodes * 1000 / std::max(ms, 1LL))
            << " hashfull " << hashfull()
            << " time " << ms;

        // Omit `pv` entirely rather than emitting the non-move token "none":
        // a GUI parsing the pv field is entitled to expect moves in it.
        if (best_move.has_value()) {
            std::cout << " pv " << move_to_string(*best_move);
        }

        std::cout << "\n";
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

int Engine::hashfull() const {
    // UCI `hashfull` is transposition-table occupancy in permille. Sampled
    // over the first 1000 slots rather than scanned in full: entries are
    // indexed by hash & TT_MASK and so are spread uniformly, and walking all
    // TT_SIZE entries once per iteration would cost more than the number is
    // worth. This is also the telemetry that was missing when the 2026-07-15
    // "TT size buys nothing" result proved hard to interpret.
    int used = 0;

    for (int i = 0; i < 1000; ++i) {
        if (transposition_table[i].key != 0) {
            used += 1;
        }
    }

    return used;
}

bool Engine::time_is_up() const {
    if (!time_limit.has_value()) {
        return false;
    }

    return elapsed_seconds(start_time) >= *time_limit;
}

int Engine::evaluate_position(const Board& board) const {
#if SGR_EVALSCALE
    return scale_for_fifty_move(board, board.evaluate());
#else
    return board.evaluate();
#endif
}

#if SGR_EVALSCALE
// A position's evaluation means less the closer it sits to a draw by the
// halfmove clock: two plies short of the fifty-move reset, a "winning"
// position is not winning. Scale linearly from evalscale_start toward
// evalscale_min_pct at 100.
//
// Mate scores are left alone -- a forced mate is not diluted by the clock,
// it ENDS the game before the clock matters, and rescaling it would corrupt
// the mate-distance encoding the TT relies on.
int Engine::scale_for_fifty_move(const Board& board, int score) const {
    if (std::abs(score) > MATE_THRESHOLD) {
        return score;
    }

    int hmc = board.halfmove_clock;

    if (hmc <= params.evalscale_start) {
        return score;
    }

    int span = 100 - params.evalscale_start;
    if (span <= 0) {
        return score;
    }

    int over = std::min(hmc, 100) - params.evalscale_start;
    int pct = 100 - (100 - params.evalscale_min_pct) * over / span;

    return score * pct / 100;
}
#endif

int Engine::evaluate_quiet_position(const Board& board) const {
#if SGR_EVALSCALE
    return scale_for_fifty_move(board, board.evaluate_quiet());
#else
    return board.evaluate_quiet();
#endif
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
#if SGR_ROOTPVS
    bool legal_found_any = false;   // first SEARCHED root move gets the full window
#endif

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

        // The child node's first act is to probe this slot. Start the fetch
        // now so the line is on its way while make_move's remaining work and
        // the call setup happen. A hint only: it cannot fault and cannot
        // change what is searched.
        __builtin_prefetch(&transposition_table[board.hash_key & tt_mask]);

#if SGR_CONTHIST
        ss_piece[0] = undo.placed_piece;
        ss_to[0] = move.to();
#endif
#if SGR_ROOTPVS
        // PVS at the root. The first move gets the full window as the presumed
        // PV; every later one only has to be PROVED worse, which a null window
        // does for a fraction of the cost. Re-search fully only when one
        // surprises us by beating alpha -- and only while it is still inside
        // the aspiration window, since a score at or above beta is a fail-high
        // the caller will widen and re-run anyway.
        int score;

        if (!legal_found_any) {
            score = -negamax(board, depth - 1, -beta, -alpha, 1);
        } else {
            score = -negamax(board, depth - 1, -alpha - 1, -alpha, 1);

            if (score > alpha && score < beta && !stop_search) {
                score = -negamax(board, depth - 1, -beta, -alpha, 1);
            }
        }

        legal_found_any = true;
#else
        int score = -negamax(board, depth - 1, -beta, -alpha, 1);
#endif
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
    if (depth < params.lmr_min_depth) {
        return false;
    }

    if (in_check) {
        return false;
    }

    if (legal_moves_searched <= params.lmr_full_depth_moves) {
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

namespace {

// LMR reductions, precomputed. The formula costs two std::log calls, and it was
// evaluating them at every late move of every node -- but both inputs are small
// integers, so every result it can produce fits in a table.
//
// LMR_DIM covers depth and move number up to 63. Depth is bounded by the root
// depth (extensions only ever restore a ply, never add one beyond the parent),
// so a `go depth 64`+ search or a position with 64+ legal moves falls through to
// the formula rather than reading off the end.
constexpr int LMR_DIM = 64;

// Exactly the expression lmr_reduction used to evaluate inline: same double
// arithmetic, same truncating cast, same clamp. Both clamp inputs are table
// indices, so the clamp is folded into the table rather than left at the call
// site -- there is nothing at the call site it could depend on.
//
// The divisor is now params.lmr_div_x100 / 100.0. At the default 250 that is
// 2.5, i.e. bit-for-bit the original expression.
int lmr_formula(int depth, int legal_moves_searched) {
    int reduction = 1 + static_cast<int>(
        std::log(depth) * std::log(std::max(legal_moves_searched, 1))
        / (params.lmr_div_x100 / 100.0)
    );

    return std::max(1, std::min(reduction, depth - 1));
}

// No longer const: the divisor is tunable, so the table is derived state that
// must be rebuilt whenever it changes. See refresh_derived_params().
std::array<std::array<int, LMR_DIM>, LMR_DIM> LMR_TABLE{};

} // namespace

SearchParams params;

void refresh_derived_params() {
    // Row 0 is left zeroed. log(0) is -inf and -inf * 0 is NaN, so depth 0 has
    // no defined value here -- it is also unreachable, since the caller is
    // gated on depth >= lmr_min_depth.
    for (int depth = 1; depth < LMR_DIM; ++depth) {
        for (int moves = 0; moves < LMR_DIM; ++moves) {
            LMR_TABLE[depth][moves] = lmr_formula(depth, moves);
        }
    }
}

int Engine::lmr_reduction(int depth, int legal_moves_searched) const {
    if (depth < LMR_DIM && legal_moves_searched < LMR_DIM) {
        return LMR_TABLE[depth][legal_moves_searched];
    }

    return lmr_formula(depth, legal_moves_searched);
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

    const TTEntry& tt_slot = transposition_table[board_hash & tt_mask];

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
        depth <= params.rfp_max_depth
        && !in_check_node
        && std::abs(alpha) < MATE - 1000
        && std::abs(beta) < MATE - 1000
    ) {
#if SGR_IMPROVING
        // A rising eval is a more trustworthy bound, so one ply of margin is
        // waived; at depth 1 improving this prunes on eval >= beta alone.
        int rfp_eval = node_static_eval;

        if (rfp_eval - params.rfp_margin * (depth - (improving ? 1 : 0)) >= beta) {
#else
        int rfp_eval = evaluate_position(board);

        if (rfp_eval - params.rfp_margin * depth >= beta) {
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

        int futility_margin = (depth == 1) ? params.futility_margin_1
                                   : params.futility_margin_2;

        if (static_eval + futility_margin <= alpha) {
            return quiescence(board, alpha, beta, ply);
        }
    }

#if SGR_RAZOR
    // Verified razoring at depth 3..razor_max_depth. Same idea as the block
    // above -- a static eval this far below alpha is not being rescued by quiet
    // moves -- but with a wider, depth-scaled margin, and it CONFIRMS with a
    // quiescence search before bailing out. The shallow block returns the
    // quiescence score outright; at these depths there is more to lose from a
    // wrong bail, so a qsearch that comes back above alpha means the position
    // is not actually lost and the node is searched normally.
    if (
        depth > 2
        && depth <= params.razor_max_depth
        && !in_check_node
        && std::abs(alpha) < MATE - 1000
        && std::abs(beta) < MATE - 1000
    ) {
#if SGR_IMPROVING
        int razor_eval = node_static_eval;
#else
        int razor_eval = evaluate_position(board);
#endif
        if (razor_eval + params.razor_margin * depth <= alpha) {
            int q = quiescence(board, alpha, alpha + 1, ply);
            if (stop_search) {
                return 0;
            }
            if (q <= alpha) {
                return q;
            }
        }
    }
#endif

    // No null move with a move excluded: the verdict must come from the
    // remaining moves themselves.
    if (!excluded.has_value() && can_try_null_move(board, depth, beta, ply)) {
        NullMoveUndo undo = board.make_null_move();
#if SGR_CONTHIST
        ss_piece[ply] = -1;   // a null move is no follow-up context
#endif

#if SGR_NMPSCALE
        // R grows with depth, and with how far the static eval already sits
        // above beta: the bigger that surplus, the more certain the null move
        // is to fail high and the less tree is worth spending to confirm it.
        // The eval term is only available when a static eval was computed at
        // this node -- in-check plies record the sentinel, but can_try_null_move
        // has already excluded those.
        int R = params.null_move_reduction + depth / params.nmp_depth_div;
#if SGR_IMPROVING
        if (node_static_eval != NO_STATIC_EVAL) {
            R += std::min((node_static_eval - beta) / params.nmp_eval_div,
                          params.nmp_eval_max);
        }
#endif
        // Never reduce past the node itself; a negative depth would hand the
        // child a quiescence search whose bound is not what this test means.
        R = std::clamp(R, 1, depth - 1);
#else
        int R = params.null_move_reduction + (depth >= 6 ? 1 : 0);
#endif

        int score = -negamax(
            board,
            depth - 1 - R,
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
                NO_MOVE
            );

            return beta;
        }
    }

    MoveList moves = generate_moves(board);
    std::optional<Move> tt_move_key = valid_tt_move_key(board_hash, moves);
    MovePicker picker(*this, board, moves, tt_move_key, ply, true);
    LegalityInfo li = board.legality_info();

#if SGR_IIR
    // Internal iterative reduction. No TT move means this node has never been
    // searched usefully, so its ordering is guesswork and a full-depth pass
    // mostly buys a re-search. Take a ply off; the shallower search populates
    // the TT, and the ordering on any revisit is real.
    //
    // Deliberately AFTER the singular test's depth gate would read `depth`, so
    // it cannot silently disqualify a node from singular extension -- the
    // reduction is applied here, before the loop, and the singular block below
    // sees the reduced value, which is the intended relationship: a node too
    // poorly ordered to have a TT move is not one to spend a singular search on.
    if (depth >= params.iir_min_depth && !tt_move_key.has_value()) {
        depth -= params.iir_reduction;
    }
#endif

    // Check geometry for this node, computed once. The move loop below tests
    // each move against it instead of making the move and scanning the board.
    // Valid for the whole loop: make/unmake is balanced, so the position is
    // unchanged between iterations (and across the singular search below).
    CheckInfo ci = board.check_info();

#if SGR_SINGULAR
    // Singular extension test: the TT move carries a lower-bound score from a
    // search nearly as deep as this node. Search the OTHER moves, reduced,
    // against a window a margin below that score; if none reaches it, the TT
    // move is the position's only good move and earns one extra ply in the
    // loop below.
    int singular_extension = 0;

    if (
        depth >= params.singular_min_depth
        && !excluded.has_value()
        && tt_move_key.has_value()
        && ply < MAX_PLY - 2
        && tt_slot.key == board_hash
        && tt_slot.flag != TT_UPPER
        && tt_slot.depth >= depth - params.singular_tt_depth_slack
    ) {
        // Copy out of the TT before recursing: the helper search may replace
        // this slot.
        int tt_score = score_from_tt(tt_slot.score, ply);

        if (std::abs(tt_score) < MATE_THRESHOLD) {
            int singular_beta = tt_score - params.singular_margin * depth;

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
    Move best_move_key = NO_MOVE;
    bool legal_found = false;
    int legal_moves_searched = 0;

#if SGR_HMALUS
    // Quiets searched at this node, in order; on a quiet beta cutoff every
    // earlier entry is a quiet that failed where the cutoff move succeeded.
    Move tried_quiets[256];
    int n_tried = 0;
#endif

#if SGR_CAPHIST
    // Captures searched at this node, in order. On a NOISY beta cutoff every
    // earlier entry is a capture that failed where the cutoff capture worked --
    // the same malus logic the quiets already get.
    Move tried_caps[256];
    int n_caps = 0;
#endif

    Move move;
    while (picker.next(move)) {
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
        // The depth guard must precede the lmp_count_for() lookup: it only
        // covers depths 0..params.lmp_max_depth.
#if SGR_IMPROVING
        // A falling eval halves the quiet budget: the worst-ordered quiets
        // are even less likely to rescue a position trending downward.
        int lmp_budget = depth <= params.lmp_max_depth
            ? (improving ? lmp_count_for(depth) : lmp_count_for(depth) / 2)
            : 0;
#else
        int lmp_budget = depth <= params.lmp_max_depth ? lmp_count_for(depth) : 0;
#endif
        if (
            depth <= params.lmp_max_depth
            && !in_check_node
            && legal_moves_searched >= lmp_budget
            && std::abs(alpha) < MATE - 1000
            && !is_noisy_move(board, move)
            && !is_killer_move(ply, move)
        ) {
            continue;
        }
#endif

        // ---- shallow-depth move pruning ------------------------------------
        // All of these sit BEFORE the malus recording below, for the same
        // reason LMP does: a move that is never searched must not be punished
        // at a later cutoff for failing.
        //
        // Common guards: never prune the first move (legal_found would stay
        // false and a legal position could be reported as mate), never prune
        // while in check, never prune near mate scores, and never prune the TT
        // move or a killer. Ordered cheapest test first -- a history lookup
        // costs an array read, SEE costs an exchange simulation.
        if (
            legal_moves_searched > 0
            && !in_check_node
            && std::abs(alpha) < MATE - 1000
            && !(tt_move_key.has_value() && move == *tt_move_key)
            && !is_killer_move(ply, move)
        ) {
            const bool quiet = !is_noisy_move(board, move);

#if SGR_HISTPRUNE
            // A quiet that keeps failing in this exact continuation.
            if (quiet && depth <= params.histprune_max_depth) {
                int h = history[move.from()][move.to()];
#if SGR_CONTHIST
                if (ply > 0 && ss_piece[ply - 1] >= 0) {
                    auto pc = board.piece_at(move.from());
                    if (pc.has_value()) {
                        h += conthist[conthist_index(
                            ss_piece[ply - 1], ss_to[ply - 1], *pc, move.to())];
                    }
                }
#endif
                if (h < -params.histprune_margin * depth) {
                    continue;
                }
            }
#endif

#if SGR_FUTILITY
            // Too far behind for a quiet move to matter at this depth.
            if (quiet && depth <= params.fut_max_depth) {
#if SGR_IMPROVING
                int fe = node_static_eval;
#else
                int fe = evaluate_position(board);
#endif
                if (fe != NO_STATIC_EVAL
                        && fe + params.fut_margin * depth <= alpha) {
                    continue;
                }
            }
#endif

#if SGR_SEEPRUNE
            // Loses too much material by static exchange to be worth the
            // remaining depth. Captures get a quadratic allowance because a
            // sacrifice has more scope to pay off than a quiet blunder does.
            if (depth <= params.see_max_depth && !move.is_promotion()) {
                int threshold = quiet
                    ? -params.see_quiet_margin * depth
                    : -params.see_cap_margin * depth * depth;
                if (!board.see_ge(move, threshold)) {
                    continue;
                }
            }
#endif
        }
        // --------------------------------------------------------------------

#if SGR_HMALUS
        if (!is_noisy_move(board, move)) {
            tried_quiets[n_tried++] = move;
        }
#endif

#if SGR_CAPHIST
        if (is_noisy_move(board, move) && !move.is_promotion()) {
            tried_caps[n_caps++] = move;
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

        // Answered from the node's check geometry before the move is made.
        // This used to be in_check() on the position AFTER make_move, which
        // is a full attack scan -- knights, pawns, king, then both slider
        // sets -- run for every move searched at every interior node.
        bool gives_check = board.gives_check(move, ci);

        UndoInfo undo = board.make_move(move);

        // See negamax_root: prefetch the slot the child will probe. The gap
        // here is larger -- the extension logic and the LMR arithmetic both
        // run before the recursive call reaches the TT.
        __builtin_prefetch(&transposition_table[board.hash_key & tt_mask]);

#if SGR_CONTHIST
        ss_piece[ply] = undo.placed_piece;
        ss_to[ply] = move.to();
#endif

        int extension = gives_check && depth <= params.check_ext_max_depth && ply < MAX_PLY - 2 ? 1 : 0;
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
                    hist_score / params.histlmr_div, -params.histlmr_max, params.histlmr_max);
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
#if SGR_CAPHIST
            else if (!move.is_promotion()) {
                // Noisy cutoff. Reward this capture and penalise the captures
                // tried before it, exactly as quiets are handled above. The
                // move is unmade, so piece_at(from) is the mover and
                // piece_at(to) is the victim again.
                int bonus = depth * depth;
                auto pc = board.piece_at(move.from());

                if (pc.has_value()) {
                    int& ch = caphist[caphist_index(
                        *pc, move.to(), caphist_victim(board, move))];
                    ch = std::min(ch + bonus, HISTORY_MAX);
                }

                for (int i = 0; i < n_caps - 1; ++i) {
                    const Move& c = tried_caps[i];
                    auto cp = board.piece_at(c.from());
                    if (cp.has_value()) {
                        int& cch = caphist[caphist_index(
                            *cp, c.to(), caphist_victim(board, c))];
                        cch = std::max(cch - bonus, -HISTORY_MAX);
                    }
                }
            }
#endif

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
        MovePicker qpicker(*this, board, moves, std::nullopt, ply, false);
        LegalityInfo li = board.legality_info();

        bool legal_found = false;

        Move move;
        while (qpicker.next(move)) {
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

#if SGR_EVALSCALE
    // The stand-pat must be scaled the same way evaluate_position is, or
    // quiescence and the main search would disagree about the same position.
    int stand_pat = scale_for_fifty_move(board, board.evaluate(alpha, beta));
#else
    int stand_pat = board.evaluate(alpha, beta);
#endif

    if (stand_pat >= beta) {
        return beta;
    }

    if (stand_pat + MAX_PIECE_VALUE + params.delta_margin < alpha) {
        return alpha;
    }

    alpha = std::max(alpha, stand_pat);

    // Generated directly rather than by generating everything and discarding
    // the quiets. Emission order matches the old filter exactly, which matters:
    // order_moves sorts with std::sort, which is not stable, so a reordering
    // among equal-scored captures would change the search rather than speed it
    // up.
    MoveList noisy_moves = board.generate_noisy_moves();

    MovePicker npicker(*this, board, noisy_moves, std::nullopt, ply, false);
    LegalityInfo li = board.legality_info();

    Move move;
    while (npicker.next(move)) {
        auto captured = board.piece_at(move.to());

        if (captured.has_value()) {
            int captured_value = PIECE_VALUE[*captured];

            if (stand_pat + captured_value + params.delta_margin <= alpha) {
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

namespace {
// The one comparator, shared by the picker and by order_moves, so the two can
// never drift into different orderings.
struct ByScoreDesc {
    template <class T>
    bool operator()(const T& a, const T& b) const { return a.score > b.score; }
};
}  // namespace

Engine::MovePicker::MovePicker(
    const Engine& eng,
    Board& board,
    const MoveList& moves,
    const std::optional<Move>& tt_move_key,
    int ply,
    bool split_bad_captures
) {
    // Bucketing is EAGER and byte-for-byte the same pass order_moves does. Only
    // the sorting is deferred: deferring the bucketing too would mean deciding
    // the good/bad capture split lazily, and that split needs SEE, which is
    // exactly the expensive thing worth keeping in one predictable place.
    std::optional<Move> killer_key_one = std::nullopt;
    std::optional<Move> killer_key_two = std::nullopt;

    if (ply < MAX_PLY) {
        killer_key_one = eng.killer_moves[ply][0];
        killer_key_two = eng.killer_moves[ply][1];
    }

    for (const Move& move : moves) {
        Move key = move;

        if (tt_move_key.has_value() && key == *tt_move_key) {
            tt_move_ = move;
            has_tt_ = true;
            continue;
        }

        if (eng.is_noisy_move(board, move)) {
            int cscore = eng.capture_score(board, move);

            if (split_bad_captures && !move.is_promotion()
                    && !board.see_ge(move, 0)) {
                bad_captures_[n_bad_++] = {move, cscore};
            } else {
                captures_[n_cap_++] = {move, cscore};
            }
            continue;
        }

        if (killer_key_one.has_value() && key == *killer_key_one) {
            killer_one_ = move;
            has_k1_ = true;
            continue;
        }

        if (killer_key_two.has_value() && key == *killer_key_two) {
            killer_two_ = move;
            has_k2_ = true;
            continue;
        }

        int hist = eng.history[move.from()][move.to()];

#if SGR_CONTHIST
        if (split_bad_captures && ply > 0 && eng.ss_piece[ply - 1] >= 0) {
            auto piece = board.piece_at(move.from());
            if (piece.has_value()) {
                hist += eng.conthist[conthist_index(
                    eng.ss_piece[ply - 1], eng.ss_to[ply - 1], *piece, move.to())];
            }
        }
#endif

        if (hist > 0) {
            good_quiets_[n_gq_++] = {move, hist};
        } else {
            other_quiets_[n_oq_++] = {move, hist};
        }
    }
}

bool Engine::MovePicker::next(Move& out) {
    for (;;) {
        switch (stage_) {
            case S_TT:
                stage_ = S_CAPTURES;
                index_ = 0;
                if (has_tt_) { out = tt_move_; return true; }
                break;

            case S_CAPTURES:
                if (!sorted_cap_) {
                    std::sort(captures_, captures_ + n_cap_, ByScoreDesc{});
                    sorted_cap_ = true;
                }
                if (index_ < n_cap_) { out = captures_[index_++].move; return true; }
                stage_ = S_KILLER1;
                break;

            case S_KILLER1:
                stage_ = S_KILLER2;
                if (has_k1_) { out = killer_one_; return true; }
                break;

            case S_KILLER2:
                stage_ = S_BAD;
                index_ = 0;
                if (has_k2_) { out = killer_two_; return true; }
                break;

            case S_BAD:
                if (!sorted_bad_) {
                    std::sort(bad_captures_, bad_captures_ + n_bad_, ByScoreDesc{});
                    sorted_bad_ = true;
                }
                if (index_ < n_bad_) { out = bad_captures_[index_++].move; return true; }
                stage_ = S_GOOD_QUIET;
                index_ = 0;
                break;

            case S_GOOD_QUIET:
                if (!sorted_gq_) {
                    std::sort(good_quiets_, good_quiets_ + n_gq_, ByScoreDesc{});
                    sorted_gq_ = true;
                }
                if (index_ < n_gq_) { out = good_quiets_[index_++].move; return true; }
                stage_ = S_OTHER_QUIET;
                index_ = 0;
                break;

            case S_OTHER_QUIET:
#if SGR_HMALUS || SGR_CONTHIST
                // With malus or continuation scores these are genuinely
                // negative, so they order least-bad first. Without either,
                // every score here is exactly zero and the sort is a no-op.
                if (!sorted_oq_) {
                    std::sort(other_quiets_, other_quiets_ + n_oq_, ByScoreDesc{});
                    sorted_oq_ = true;
                }
#endif
                if (index_ < n_oq_) { out = other_quiets_[index_++].move; return true; }
                stage_ = S_DONE;
                break;

            default:
                return false;
        }
    }
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

    int score = 10'000 + 10 * PIECE_VALUE[*victim] - PIECE_VALUE[*attacker];

#if SGR_CAPHIST
    // Nudges within an MVV-LVA tier rather than across tiers: the divisor keeps
    // the history term small against a base that is already ~10,000 with a 10x
    // victim multiplier.
    score += std::clamp(
        caphist[caphist_index(*attacker, move.to(), *victim % 6)] / params.caphist_div,
        -params.caphist_max, params.caphist_max);
#endif

    return score;
}

void Engine::store_tt(
    U64 board_hash,
    int depth,
    int score,
    int flag,
    Move best_move_key
) {
    TTEntry& slot = transposition_table[board_hash & tt_mask];

    // Replace if the slot holds a different position, or ours is searched at
    // least as deep. The table never wipes; old entries age out per slot.
    if (slot.key != board_hash || depth >= slot.depth) {
        // Explicit narrowing at the one place it happens. depth is bounded by
        // MAX_PLY - 1 = 127 (the UCI layer clamps, and the search never
        // extends past its own root depth), flag holds 0-2, and score keeps
        // its full 32 bits for mate encoding.
        slot = TTEntry{
            board_hash,
            static_cast<std::int32_t>(score),
            static_cast<std::int8_t>(depth),
            static_cast<std::uint8_t>(flag),
            best_move_key
        };
    }
}

Move Engine::get_tt_move(U64 board_hash) const {
    const TTEntry& slot = transposition_table[board_hash & tt_mask];

    if (slot.key != board_hash) {
        return NO_MOVE;
    }

    return slot.best_move;
}