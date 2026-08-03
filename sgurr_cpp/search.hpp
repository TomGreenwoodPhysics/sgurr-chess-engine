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


constexpr int TT_EXACT = 0;
constexpr int TT_LOWER = 1;
constexpr int TT_UPPER = 2;

// Transposition table sizing. `Hash` is a UCI option, so the entry count is a
// runtime value on the Engine rather than a compile-time constant. The count is
// always rounded DOWN to a power of two, which keeps the probe a single AND
// against a mask instead of a modulo on the hottest path in the engine.
//
// The default reproduces the historical table exactly: sizeof(TTEntry) is 24,
// so 48 MB is 2^21 entries, which is what TT_SIZE_BITS = 21 used to give.
constexpr int DEFAULT_HASH_MB = 48;
constexpr int MIN_HASH_MB = 1;
constexpr int MAX_HASH_MB = 4096;

constexpr int TIME_CHECK_INTERVAL = 512;

// Time-management knobs (clock play only; explicit `movetime` and node limits
// are unaffected). MOVE_OVERHEAD_MS is the clock margin held back for GUI and
// network latency so the move always arrives before the flag falls.
// SOFT_TIME_FRACTION is how far into the budget a new iterative-deepening pass
// may still be started; past it the last completed depth is kept rather than
// starting an iteration that would be aborted, unfinished, at the hard limit.
constexpr long long MOVE_OVERHEAD_MS = 30;
// Overridable at build time (-DSGR_SOFT_TIME_FRACTION=<f>) so time-management
// policies can be A/B-tested from one tree; 1.0 makes the soft limit coincide
// with the hard deadline, i.e. v3.0-style hard-limit-only behaviour.
#ifndef SGR_SOFT_TIME_FRACTION
#define SGR_SOFT_TIME_FRACTION 0.6
#endif

// Best-move stability scaling for the soft limit (clock play only). The soft
// budget is stretched while the root best move is still changing (the position
// has not settled, so more search is likely to change the move) and trimmed
// once it has held for several iterations. Indexed by the number of consecutive
// iterations the root best move has been unchanged, capped at the final entry;
// the scaled soft limit is always still clamped to the hard deadline. These are
// starting values, to be swept before they are believed.
constexpr int BM_STABILITY_COUNT = 5;

// Compile-time toggle for the scaling above (default on). Build with
// -DSGR_BMSTAB=0 to fall back to the flat v3.1 soft limit, so the feature can
// be A/B-tested from one source tree.
#ifndef SGR_BMSTAB
#define SGR_BMSTAB 1
#endif

// History malus and continuation history (both default on; -DSGR_HMALUS=0 /
// -DSGR_CONTHIST=0 revert them, as with SGR_BMSTAB). Malus: on a quiet beta
// cutoff, the quiets already tried at that node are penalised, not just the
// cutoff move rewarded, so consistently useless moves sink in the ordering.
// Continuation history: quiets are also scored by how well they have done as
// the follow-up to the previous ply's move (indexed by that move's piece/to
// and this move's piece/to), which captures reply patterns the from/to
// butterfly table cannot see.
#ifndef SGR_HMALUS
#define SGR_HMALUS 1
#endif
#ifndef SGR_CONTHIST
#define SGR_CONTHIST 1
#endif

// History scores (butterfly and continuation) are clamped to +/-HISTORY_MAX.
constexpr int HISTORY_MAX = 1'000'000;

// Reverse futility pruning and late move pruning (both default on;
// -DSGR_RFP=0 / -DSGR_LMP=0 revert, as with the other search toggles).
// WARNING: labeller/datagen builds must pass -DSGR_RFP=0. RFP returns the raw
// static eval where a search score is expected; under datagen's fixed node
// budget its speed win buys nothing, so labels drift toward the labeller
// net's own opinions -- this is what flattened gen6 (probe "saturated",
// net-isolated A/B +6 +/-20; see ledger 2026-07-15). RFP belongs in the
// playing engine, not in the labeller.
// RFP: at shallow depth, if the static eval sits so far above beta that a
// conservative margin per remaining ply cannot pull it back under, trust it
// and stand pat instead of searching. LMP: at shallow depth, once enough
// quiet moves have been searched without a cutoff, skip the remaining quiets
// (they are ordered worst-by-history and almost never matter). Margins and
// counts are starting values, to be swept before they are believed.
#ifndef SGR_RFP
#define SGR_RFP 1
#endif
#ifndef SGR_LMP
#define SGR_LMP 1
#endif

// Improving flag, history-adjusted LMR, and singular extensions (the v6.0
// package -- SPRT vs v5.0: +57.3 +/-17.3, H1 at 1,139 games, undecomposed.
// All default on since v6.0; -DSGR_IMPROVING=0 / -DSGR_HISTLMR=0 /
// -DSGR_SINGULAR=0 revert, as with the other search toggles. All three return
// searched scores, so unlike RFP they are labeller-safe).
// Improving: the static eval is recorded at each ply and compared with the
// same side's eval two plies up. A rising eval makes the static eval a more
// trustworthy bound, so RFP prunes with a one-ply-smaller margin; a falling
// one means the worst-ordered quiets are even less likely to rescue the
// position, so LMP halves its quiet budget.
// History-adjusted LMR: a quiet's reduction is nudged by its history record
// (butterfly + continuation), one ply per HISTLMR_DIV of score, clamped to
// +/-HISTLMR_MAX -- proven quiets are reduced less, serial failures more.
// Singular extensions: when the TT move carries a lower-bound score from a
// search nearly as deep as this node, the REMAINING moves are searched at
// reduced depth against a window a margin below that score; if none reaches
// it, the TT move is the position's only good move and is extended one ply so
// the forcing line it carries is not cut short by reductions elsewhere.
// Margins and divisors are starting values, to be swept before they are
// believed.
#ifndef SGR_IMPROVING
#define SGR_IMPROVING 1
#endif
#ifndef SGR_HISTLMR
#define SGR_HISTLMR 1
#endif
#ifndef SGR_SINGULAR
#define SGR_SINGULAR 1
#endif
constexpr int NO_STATIC_EVAL = -INF;          // in-check plies record no eval

// ---------------------------------------------------------------------------
// The v9.0 batch. Each carries its own toggle so a failing package can be
// bisected by halves without a source edit, as the v6.0 package could not be.
// ---------------------------------------------------------------------------

// Internal iterative reduction. A node with no TT move has never been searched
// to a useful depth here, so its move ordering is guesswork and a full-depth
// search is largely wasted -- the first move tried is unlikely to be best.
// Reduce a ply instead and let the shallower pass populate the TT; the ordering
// on any re-visit is then real. Cheaper than the classic internal iterative
// DEEPENING it replaces, which ran a whole extra search to get the same
// information.
#ifndef SGR_IIR
#define SGR_IIR 1
#endif

// Eval-scaled null-move reduction. The reduction was flat: 2 plies, 3 from
// depth 6. But the further the static eval already sits above beta, the more
// certain the null move is to fail high, and the less of the tree is worth
// spending to confirm it. Scale R with depth and with that surplus.
#ifndef SGR_NMPSCALE
#define SGR_NMPSCALE 1
#endif

// Razoring above depth 2. The existing block drops straight into quiescence
// when the static eval is far enough below alpha, but only at depth 1-2. The
// same reasoning holds deeper with a wider margin: a position this far behind
// is not going to be rescued by quiet moves. Unlike the shallow case this
// VERIFIES -- it runs quiescence and only returns if that also fails low, since
// a deeper node has more to lose from a wrong bail-out.
#ifndef SGR_RAZOR
#define SGR_RAZOR 1
#endif


// Tunable search parameters.
//
// Every value here was a hand-set compile-time constant, and NOT ONE has ever
// been swept -- three separate comments in this file say so ("starting values,
// to be swept before they are believed"). They are gathered into one struct so
// they can be exposed as UCI options and driven by an SPSA harness.
//
// The defaults are EXACTLY the constants they replace, so the engine at default
// settings searches an identical tree. That is enforced by the bench
// fingerprint, not assumed.
//
// Conceptually-fractional values are stored as integers scaled by 100, because
// UCI `spin` options are integral and SPSA steps in integers.
//
// WARNING on the time-management block. METHODOLOGY.md 6 records that the v3.1
// soft time limit measured +24.6 in self-play and NEGATIVE in the pool. Time
// parameters have a documented history of self-play/pool divergence in this
// project, so tuning them against self-play will produce settings that win the
// tuning run and lose real games. Tune them against a pool gauntlet or not at
// all; they are exposed here for completeness, not as an invitation.
struct SearchParams {
    // pruning
    int rfp_margin              = 100;
    int rfp_max_depth           = 6;
    int lmp_max_depth           = 3;
    int lmp_count_1             = 6;
    int lmp_count_2             = 12;
    int lmp_count_3             = 18;
    int futility_margin_1       = 150;
    int futility_margin_2       = 300;

    // reductions
    int null_move_reduction     = 2;
    int lmr_min_depth           = 3;
    int lmr_full_depth_moves    = 2;
    int lmr_div_x100            = 250;   // the 2.5 divisor in the LMR formula
    // 400'000 shipped from v6.0 to v8.1 and did nothing whatsoever. Measured
    // 2026-08-03 by instrumenting every histLMR decision over bench 10
    // (493,781 samples), the actual |hist_score| distribution is:
    //
    //     exactly 0   15.4%      64..255     33.4%   (cum 94.9%)
    //     1..15       10.4%      256..1023    4.3%   (cum 99.2%)
    //     16..63      35.7%      1024+        0.8%
    //
    // Typical magnitude is tens to low hundreds, because history earns
    // depth*depth per cutoff and is halved every move. hist_score / 400'000
    // was therefore zero for essentially every move in the engine's life;
    // setting histlmr_max to 0, which disables the adjustment outright, changed
    // the bench tree not at all.
    //
    // 128 puts the ±1 step at the ~75th percentile of that distribution and ±2
    // at the ~95th, so the adjustment engages on the moves whose history
    // actually says something. Chosen on the distribution, NOT on tree size:
    // node counts across the range are non-monotonic and therefore useless as
    // a guide (+31.3% at 32, +21.0% at 64, +14.4% at 128, +34.3% at 256,
    // +12.2% at 512). Reduction changes cascade, and a smaller tree is not a
    // stronger engine -- see METHODOLOGY 5 on singular extensions.
    //
    // A reasoned starting point, not a tuned one. No games have chosen it, so
    // it is the first thing to suspect if the batch regresses. It is also a
    // UCI option, so sweeping it needs no rebuild: fastchess can drive it with
    // -engine option.HistLmrDiv=<n> in the same testing session.
    int histlmr_div             = 128;
    int histlmr_max             = 2;

    // extensions
    int singular_min_depth      = 7;
    int singular_tt_depth_slack = 3;
    int singular_margin         = 2;
    int check_ext_max_depth     = 4;

    // windows
    int aspiration_window       = 50;
    int delta_margin            = 200;

    // v9.0 batch
    int iir_min_depth           = 4;     // no TT move at this depth or more -> reduce
    int iir_reduction           = 1;
    int nmp_depth_div           = 6;     // R += depth / this
    int nmp_eval_div            = 200;   // R += (eval - beta) / this ...
    int nmp_eval_max            = 3;     // ... capped here
    int razor_max_depth         = 4;     // verified razoring applies at 3..this
    // cp per ply of depth: the node razors when eval + margin*depth <= alpha,
    // so a SMALLER margin fires more often. 100 gives alpha-300 at depth 3 and
    // alpha-400 at depth 4, which is the conventional range, and it is the only
    // setting swept where the feature behaves like a pruning feature at all
    // (-14.9% tree vs razoring off; 200-800 fired less and cost 3-12% MORE,
    // 1200 never fired). Tree size is not evidence of strength -- see the note
    // on histlmr_div -- but a pruning feature that grows the tree is not doing
    // its job either way.
    int razor_margin            = 100;

    // time management -- see the warning above
    int soft_time_fraction_x100 = static_cast<int>(SGR_SOFT_TIME_FRACTION * 100);
    int bm_stability_x100[BM_STABILITY_COUNT] = {220, 130, 100, 85, 75};
};

// One global instance. The engine is single-threaded by design, and this
// mirrors how nnue.cpp already holds its network and accumulators.
extern SearchParams params;

// Rebuild anything derived from `params`. Currently the LMR reduction table,
// which is precomputed from lmr_div_x100. MUST be called after any setoption
// that changes a parameter feeding a derived table, or the table silently keeps
// describing the old value -- a stale-derived-state bug of exactly the kind
// METHODOLOGY.md 7 catalogues.
void refresh_derived_params();

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
    Move best_move = NO_MOVE;    // NO_MOVE = entry carries no move
};

class Engine {
public:
    long long nodes = 0;
    long long tt_hits = 0;

    std::vector<TTEntry> transposition_table;   // tt_size entries, indexed by hash & tt_mask
    std::size_t tt_size = 0;
    U64 tt_mask = 0;

    Engine();

    // Resize the transposition table to (about) `mb` megabytes, rounded down
    // to a power-of-two entry count. Discards the current contents, so it is a
    // between-games operation, never a mid-search one.
    void resize_hash(int mb);

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

    // Transposition-table occupancy in permille, for the UCI `hashfull` field.
    int hashfull() const;

private:
    std::chrono::steady_clock::time_point start_time;
    std::optional<double> time_limit = std::nullopt;         // hard deadline: abort mid-search
    std::optional<double> soft_time_limit = std::nullopt;    // don't start a new iteration past this
    std::optional<long long> node_limit = std::nullopt;
    bool stop_search = false;

    std::array<std::array<std::optional<Move>, 2>, MAX_PLY> killer_moves{};
    std::array<std::array<int, 64>, 64> history{};

#if SGR_IMPROVING
    // Static eval recorded at each ply of the current line (NO_STATIC_EVAL at
    // in-check plies), read two plies up for the improving flag.
    std::array<int, MAX_PLY> ss_static_eval{};
#endif

#if SGR_CONTHIST
    // Continuation history, [prev_piece][prev_to][piece][to] flattened. At
    // 12*64*12*64 ints (~2.3 MB) it lives on the heap, unlike the small
    // butterfly table above.
    std::vector<int> conthist;

    // Which (piece, to) moved at each ply of the current line; -1 piece means
    // "no previous move" (root, or a null move). Written on make, read one ply
    // deeper for ordering and at cutoffs for the conthist update.
    std::array<int, MAX_PLY> ss_piece{};
    std::array<int, MAX_PLY> ss_to{};

    static int conthist_index(int prev_piece, int prev_to, int piece, int to) {
        return ((prev_piece * 64 + prev_to) * 12 + piece) * 64 + to;
    }
#endif

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

    // `excluded` is set only by the singular-extension test: the node is
    // searched as if that move did not exist, with its own TT probe, null
    // move, and TT store disabled (the stored result would describe a
    // different position, and the null-move verdict would not be about the
    // remaining moves).
    int negamax(
        Board& board,
        int depth,
        int alpha,
        int beta,
        int ply,
        std::optional<Move> excluded = std::nullopt
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
        Move best_move_key
    );

    Move get_tt_move(U64 board_hash) const;
};