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
//
// ALL DEFAULT OFF as of v8.2. The package measured -1.0 +/-21.1 against v8.1
// over 698 games -- inconclusive, not negative, but an interval spanning
// -22..+20 means a true -15 is entirely consistent with what was seen. Shipping
// it alongside a validated +11.9% NPS speed gain would have risked a net
// regression that the data could not rule out, and would have conflated a
// measured change with an unmeasured one in the same ledger row.
//
// The code stays. Enable any subset with -DSGR_<NAME>=1 to resume validation
// when there is machine time; the bisect order is in
// benchmarks/v90_batch_prediction.md.
// ---------------------------------------------------------------------------

// Internal iterative reduction. A node with no TT move has never been searched
// to a useful depth here, so its move ordering is guesswork and a full-depth
// search is largely wasted -- the first move tried is unlikely to be best.
// Reduce a ply instead and let the shallower pass populate the TT; the ordering
// on any re-visit is then real. Cheaper than the classic internal iterative
// DEEPENING it replaces, which ran a whole extra search to get the same
// information.
#ifndef SGR_IIR
#define SGR_IIR 0
#endif

// Eval-scaled null-move reduction. The reduction was flat: 2 plies, 3 from
// depth 6. But the further the static eval already sits above beta, the more
// certain the null move is to fail high, and the less of the tree is worth
// spending to confirm it. Scale R with depth and with that surplus.
#ifndef SGR_NMPSCALE
#define SGR_NMPSCALE 0
#endif

// Razoring above depth 2. The existing block drops straight into quiescence
// when the static eval is far enough below alpha, but only at depth 1-2. The
// same reasoning holds deeper with a wider margin: a position this far behind
// is not going to be rescued by quiet moves. Unlike the shallow case this
// VERIFIES -- it runs quiescence and only returns if that also fails low, since
// a deeper node has more to lose from a wrong bail-out.
#ifndef SGR_RAZOR
#define SGR_RAZOR 0
#endif

// Move-loop futility. LMP already skips late quiets on COUNT; this skips them
// on MARGIN. A quiet move cannot usually swing the score by more than a bound
// per remaining ply, so at shallow depth a static eval that far below alpha
// means this particular quiet is not going to rescue the node either. The two
// are complementary: LMP catches "we have tried enough", this catches "the
// position is too far behind for a quiet move to matter".
#ifndef SGR_FUTILITY
#define SGR_FUTILITY 0
#endif

// SEE pruning in the main search. Quiescence already refuses captures that lose
// material by static exchange; the main loop never did. Skips moves whose
// exchange value is worse than a depth-scaled allowance -- shallow nodes have
// less depth left to recover a sacrifice, so they permit less.
#ifndef SGR_SEEPRUNE
#define SGR_SEEPRUNE 0
#endif

// History pruning. A quiet whose history is deeply negative has failed here
// repeatedly, in this exact context, at this exact continuation. At shallow
// depth that is enough to skip it outright rather than merely reduce it.
#ifndef SGR_HISTPRUNE
#define SGR_HISTPRUNE 0
#endif

// Capture history. Captures are ordered by MVV-LVA plus a SEE good/bad split,
// which is static: it knows what a capture wins on paper and nothing about
// whether THIS capture has actually been working. Indexed by moving piece,
// destination, and victim type, so "rook takes the pawn on d5" accumulates a
// record of its own the way quiet moves already do.
#ifndef SGR_CAPHIST
#define SGR_CAPHIST 0
#endif

// Principal variation search at the ROOT. Interior nodes have used PVS since
// v1.0; the root never did, searching every move with a full window. After the
// first root move an ordinary move only has to be PROVED worse, which a null
// window does for a fraction of the cost, with a re-search only on surprise.
#ifndef SGR_ROOTPVS
#define SGR_ROOTPVS 0
#endif

// Fifty-move-rule eval scaling. A position's evaluation means less the closer
// it sits to a draw by the halfmove clock: a winning position with two plies
// left before the fifty-move reset is not winning. Scales the returned score
// toward zero as the clock runs up.
//
// Search-side, so it uses the FIXED net and carries no training-seed variance
// (METHODOLOGY 2) -- an evaluation change that is nonetheless cheap to test.
#ifndef SGR_EVALSCALE
#define SGR_EVALSCALE 0
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
    // REVERTED TO 400'000 FOR v8.2. 128 was part of the v9.0 batch, which
    // measured -1.0 +/-21.1 and was held back; shipping the divisor change
    // alone would have altered the search in a release meant to be
    // behaviourally identical to v8.1. It stays inert until games say
    // otherwise, and it is SPSA target #1 when there is machine time --
    // testable via option.HistLmrDiv without a rebuild.
    //
    // The reasoning for 128, kept because it is still the right starting
    // point: it puts the ±1 step at the ~75th percentile of that distribution
    // and ±2 at the ~95th, so the adjustment engages on the moves whose
    // history actually says something. Chosen on the distribution, NOT on
    // tree size:
    // node counts across the range are non-monotonic and therefore useless as
    // a guide (+31.3% at 32, +21.0% at 64, +14.4% at 128, +34.3% at 256,
    // +12.2% at 512). Reduction changes cascade, and a smaller tree is not a
    // stronger engine -- see METHODOLOGY 5 on singular extensions.
    //
    // A reasoned starting point, not a tuned one. No games have chosen it, so
    // it is the first thing to suspect if the batch regresses. It is also a
    // UCI option, so sweeping it needs no rebuild: fastchess can drive it with
    // -engine option.HistLmrDiv=<n> in the same testing session.
    int histlmr_div             = 400'000;
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

    int fut_max_depth           = 6;     // move-loop futility applies at <= this
    int fut_margin              = 120;   // cp per ply of remaining depth
    int see_max_depth           = 8;     // SEE pruning applies at <= this
    int see_quiet_margin        = 50;    // quiets need see >= -this * depth
    int see_cap_margin          = 20;    // captures need see >= -this * depth^2
    int histprune_max_depth     = 3;
    // Prune a quiet whose history is below -this * depth. Sized against the
    // measured distribution (see histlmr_div): |hist| is tens to low hundreds,
    // so -50*depth reaches the negative tail without swallowing the bulk.
    //
    // The WEAKEST member of the v9.0 batch, and the honest reason is recorded
    // here rather than discovered later. Swept across margin 10..400 and
    // maxdepth 3..5, it never behaves like a reliable pruner: -10.6% at
    // (25, 5) but +4.6% at (50, 5), -4.7% at (50, 3) but +1.1% at (100, 3).
    // That is cascade noise, not a signal, so this value is chosen on the
    // distribution and on convention (shallow depth only) rather than by
    // picking the best number off a noisy sweep -- which is how histlmr_div
    // got its original nonsense value. Bisect candidate #2 if the batch fails,
    // and a good SPSA target once the harness exists.
    int histprune_margin        = 50;

    // Capture-history weight in the ordering score. capture_score works on a
    // ~10,000 base with a 10x victim multiplier, so the history term must nudge
    // WITHIN an MVV-LVA tier, never across it.
    //
    // Measured: caphist values live in the tens. Any divisor >= 64 made the
    // term round to zero -- 64, 256, 1024, 4096 and 16384 all produced byte-
    // identical trees, which is what inert looks like. So the divisor is 1 and
    // the raw value IS the nudge.
    //
    // The clamp is what makes that safe rather than lucky. Nothing stops the
    // table reaching HISTORY_MAX in principle, and at div=1 that would swamp
    // MVV-LVA entirely. Capping the CONTRIBUTION makes the "within a tier"
    // intent structural instead of a property the table happens to have today.
    // 256 is below the pawn-to-knight victim step (2200), so a pawn capture can
    // never be promoted over a queen capture however the history runs.
    int caphist_div             = 1;
    int caphist_max             = 256;
    // Halfmove clock at which eval scaling starts biting, and the floor it
    // scales toward. 100 plies is the draw, so scaling from ~40 leaves normal
    // play untouched and only compresses scores as a real reset approaches.
    int evalscale_start         = 40;
    int evalscale_min_pct       = 40;    // never scale below this % of the eval

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

// Packed to exactly 16 bytes, down from 24.
//
// The table is the hottest random-access structure in the engine and every
// probe is a likely cache miss, so what matters is entries per cache line: at
// 24 bytes a 64-byte line holds 2.67, at 16 it holds exactly 4. The same 48 MB
// also now buys 3.1M entries instead of 2.1M.
//
// The full 64-bit key is KEPT. Truncating it to 32 bits would save four more
// bytes and is what most engines do, but it raises the collision rate, and a
// collision changes what the search finds -- that would make this a behaviour
// change needing games rather than a layout change needing a bench diff.
//
// Field widths: score must stay 32-bit because mate scores run to +/-1,000,000.
// depth fits int8 because MAX_PLY is 128 and the UCI layer now clamps a
// requested depth to 127. flag holds three values. Move is already 16 bits.
struct TTEntry {
    U64 key = 0;                    // full hash; 0 = empty
    std::int32_t score = 0;
    std::int8_t depth = -1;
    std::uint8_t flag = TT_EXACT;
    Move best_move = NO_MOVE;       // NO_MOVE = entry carries no move
};

static_assert(sizeof(TTEntry) == 16,
              "TTEntry must stay 16 bytes: 4 per cache line is the point");

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
#if SGR_EVALSCALE
    // Damp the evaluation as the fifty-move clock runs up. Mate scores pass
    // through untouched.
    int scale_for_fifty_move(const Board& board, int score) const;
#endif
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

#if SGR_CAPHIST
    // Capture history, [piece][to][victim type] flattened. 12*64*6 ints is
    // ~18 KB, small enough to sit inline rather than on the heap as conthist
    // does.
    std::array<int, 12 * 64 * 6> caphist{};

    static int caphist_index(int piece, int to, int victim_type) {
        return (piece * 64 + to) * 6 + victim_type;
    }

    // Victim type for the table: 0-5 by piece type, and en passant / a missing
    // victim both read as a pawn, which is what they capture.
    int caphist_victim(const Board& board, const Move& move) const {
        if (move.is_en_passant()) {
            return 0;
        }
        auto v = board.piece_at(move.to());
        return v.has_value() ? (*v % 6) : 0;
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

    // Lazy move picker.
    //
    // order_moves() bucketed every move, sorted all four buckets, then built a
    // flat MoveList and returned it BY VALUE -- 514 bytes copied per node. Most
    // nodes take a beta cutoff within the first few moves, so the two quiet
    // sorts (the largest buckets) were being paid for at nearly every interior
    // node and thrown away.
    //
    // This emits the identical sequence, but sorts a bucket only when a move is
    // actually wanted from it, and hands moves back one at a time instead of
    // materialising a list. Bucket contents, scores and comparator are
    // unchanged, and std::sort is deterministic for a given input sequence, so
    // the order is preserved exactly -- which the bench fingerprint enforces
    // rather than assumes.
    class MovePicker {
    public:
        MovePicker(const Engine& eng,
                   Board& board,
                   const MoveList& moves,
                   const std::optional<Move>& tt_move_key,
                   int ply,
                   bool split_bad_captures);

        // Next move in order, or false when exhausted.
        bool next(Move& out);

    private:
        struct Scored { Move move; int score; };

        enum Stage {
            S_TT, S_CAPTURES, S_KILLER1, S_KILLER2,
            S_BAD, S_GOOD_QUIET, S_OTHER_QUIET, S_DONE
        };

        Scored captures_[256];     int n_cap_ = 0;
        Scored bad_captures_[256]; int n_bad_ = 0;
        Scored good_quiets_[256];  int n_gq_  = 0;
        Scored other_quiets_[256]; int n_oq_  = 0;

        Move tt_move_ = NO_MOVE;   bool has_tt_ = false;
        Move killer_one_ = NO_MOVE; bool has_k1_ = false;
        Move killer_two_ = NO_MOVE; bool has_k2_ = false;

        int stage_ = S_TT;
        int index_ = 0;
        bool sorted_cap_ = false;
        bool sorted_bad_ = false;
        bool sorted_gq_ = false;
        bool sorted_oq_ = false;
    };

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