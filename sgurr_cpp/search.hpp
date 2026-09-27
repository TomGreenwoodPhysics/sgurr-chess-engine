#pragma once

#include "board.hpp"

#include <array>
#include <chrono>
#include <memory>
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

// Runtime transposition table limits in megabytes.
// Entry counts are rounded down to a power of two for masked indexing.
constexpr int DEFAULT_HASH_MB = 48;
constexpr int MIN_HASH_MB = 1;
constexpr int MAX_HASH_MB = 4096;

constexpr int TIME_CHECK_INTERVAL = 512;

// Clock-play timing defaults. Explicit movetime and node limits are unaffected.
constexpr long long MOVE_OVERHEAD_MS = 30;
// SGR_SOFT_TIME_FRACTION controls when new iterations stop.
#ifndef SGR_SOFT_TIME_FRACTION
#define SGR_SOFT_TIME_FRACTION 0.6
#endif

// Number of best-move stability bands used to scale the soft limit.
constexpr int BM_STABILITY_COUNT = 5;

// Enable best-move stability scaling for the soft limit.
#ifndef SGR_BMSTAB
#define SGR_BMSTAB 1
#endif

// Clock management. Each move gets a budget from an estimate of the moves
// still to play. Iterations stop early once the root has settled, and carry
// on, up to a hard maximum of several budgets, while the best move keeps
// changing, the nodes spread across rival moves or the score falls. An
// iteration cut short by the maximum still counts if it found a better move.
// Only clock searches are affected: movetime, node and depth limits behave
// exactly as before, so datagen, the web app and bench do not change.
#ifndef SGR_TM2
#define SGR_TM2 1
#endif

// Report the line the search proved, recorded at PV nodes, instead of reading
// it back from the transposition table, where later entries overwrite it and
// cut it short. Reporting only: the search itself is unchanged.
#ifndef SGR_PV_TABLE
#define SGR_PV_TABLE 1
#endif

// History malus penalises quiets tried before a quiet cutoff.
// Continuation history scores replies in the context of the previous move.
#ifndef SGR_HMALUS
#define SGR_HMALUS 1
#endif
#ifndef SGR_CONTHIST
#define SGR_CONTHIST 1
#endif

// Clamp butterfly and continuation history scores to this magnitude.
constexpr int HISTORY_MAX = 1'000'000;

// Move-ordering counters, printed after bench and by the orderstats command.
// Measurement only: never on in a build that plays.
#ifndef SGR_ORDER_STATS
#define SGR_ORDER_STATS 0
#endif
#if SGR_ORDER_STATS
struct OrderStats {
    long long cutoffs = 0;         // beta cutoffs in the move loop
    long long first_move = 0;      // ... made by the first move searched
    long long index_sum = 0;       // sum of the cutoff move's position
    long long lmr_adj[5] = {};     // history's adjustment to a reduction, -2..+2
    long long prune_checked = 0;   // quiets tested for history pruning
    long long pruned = 0;          // ... and pruned
    long long hist_sign[2] = {};   // combined history at the reduction: <0, >=0
    long long hist_bits[24] = {};  // ... by bit length of its magnitude
    // What other settings would have done with the same history values.
    static constexpr int LMR_DIVS[] = {150, 228, 300, 4000, 5000, 5500, 6000, 6200,
                                       6500, 7000, 8000, 9000};
    static constexpr int PRUNE_MARGINS[] = {50, 75, 100, 1000, 1500, 1750, 2000, 2250,
                                            2500, 3000, 4000};
    long long lmr_by_div[std::size(LMR_DIVS)][5] = {};
    long long pruned_by_margin[std::size(PRUNE_MARGINS)] = {};
    // Static eval against the search score, at nodes whose score bounds the
    // error: raw eval, then corrected, before that node's own update.
    long long eval_nodes = 0;
    double raw_abs = 0, raw_sq = 0, corr_abs = 0, corr_sq = 0;
    // Decisions made on the static eval: tested, then taken.
    long long rfp[2] = {}, fut_drop[2] = {}, razor[2] = {}, nmp[2] = {}, fut_move[2] = {};
    long long nodes = 0;   // main-search nodes past the TT probe
    // The correction applied: signed from white's side, and its size.
    long long corr_count = 0;
    double corr_white = 0, corr_size = 0;
};
extern OrderStats order_stats;
void print_order_stats();
#endif

// Reverse futility and late move pruning.
// Datagen builds must set SGR_RFP=0 because labels require searched scores.
#ifndef SGR_RFP
#define SGR_RFP 1
#endif
#ifndef SGR_LMP
#define SGR_LMP 1
#endif

// Improving adjusts pruning from the same side's eval two plies earlier.
// History-adjusted LMR reduces successful quiets less and poor quiets more.
// Singular extensions deepen a TT move when alternatives fail a reduced test.
#ifndef SGR_IMPROVING
#define SGR_IMPROVING 1
#endif
#ifndef SGR_HISTLMR
#define SGR_HISTLMR 1
#endif
#ifndef SGR_SINGULAR
#define SGR_SINGULAR 1
#endif
constexpr int NO_STATIC_EVAL = -INF;          // In-check plies have no static eval.

// Experimental version 9 features. Each is disabled and independently toggled.

// Internal iterative reduction for nodes without a TT move.
#ifndef SGR_IIR
#define SGR_IIR 1
#endif

// Scale null-move reduction by depth and the eval surplus over beta.
#ifndef SGR_NMPSCALE
#define SGR_NMPSCALE 1
#endif

// Verified razoring at deeper shallow nodes.
#ifndef SGR_RAZOR
#define SGR_RAZOR 1
#endif

// Skip shallow quiets that cannot overcome the futility margin.
#ifndef SGR_FUTILITY
#define SGR_FUTILITY 1
#endif

// Prune moves below a depth-scaled SEE allowance.
#ifndef SGR_SEEPRUNE
#define SGR_SEEPRUNE 1
#endif

// Prune shallow quiets with strongly negative history.
#ifndef SGR_HISTPRUNE
#define SGR_HISTPRUNE 1
#endif

// Capture history indexed by mover, destination and victim type.
#ifndef SGR_CAPHIST
#define SGR_CAPHIST 1
#endif

// Batch F, move ordering. See benchmarks/v95_batch_f_prediction.md.
// One butterfly table per side to move, where both sides shared one.
#ifndef SGR_HIST_COLOUR
#define SGR_HIST_COLOUR 1
#endif
// History updates pull an entry towards a bound instead of adding to it, so
// entries stay bounded and recent results count for more.
#ifndef SGR_HIST_GRAVITY
#define SGR_HIST_GRAVITY 1
#endif
// Continuation history from our own moves two and four plies back, as well as
// the opponent's last move.
#ifndef SGR_CONTHIST_24
#define SGR_CONTHIST_24 1
#endif
// Captures ordered by victim value and capture history at full weight, not
// history held to a nudge within its victim's tier.
#ifndef SGR_CAPHIST_FULL
#define SGR_CAPHIST_FULL 1
#endif
// A picker that scores quiets only when it reaches them, runs SEE only on the
// capture about to be tried and sorts only the quiets likely to be searched.
// Quiets with strong history can go ahead of losing captures, and
// underpromotions wait with the losing captures.
#ifndef SGR_PICKER2
#define SGR_PICKER2 1
#endif
// Test builds abort if the picker repeats, invents or loses a move.
#ifndef SGR_PICKER_CHECK
#define SGR_PICKER_CHECK 0
#endif

// Bound on a history entry under gravity.
constexpr int HIST_LIMIT = 16384;

// Principal variation search at the root.
#ifndef SGR_ROOTPVS
#define SGR_ROOTPVS 1
#endif

// Scale evaluation towards zero as the halfmove clock nears a draw.
#ifndef SGR_EVALSCALE
#define SGR_EVALSCALE 1
#endif

// Batch G. Correct the static eval by how far it has missed the search in
// similar positions: the same pawns, the same pieces for either side, or
// the same minor or major pieces. Needs SGR_IMPROVING, which is where the
// per-node static eval is computed. See benchmarks/v95_batch_g_prediction.md.
#ifndef SGR_CORRHIST
#define SGR_CORRHIST 1
#endif
// Quiescence stands pat on the corrected eval too.
#ifndef SGR_CORR_QS
#define SGR_CORR_QS 1
#endif
#if SGR_CORRHIST && !SGR_IMPROVING
#error "SGR_CORRHIST needs SGR_IMPROVING for the per-node static eval"
#endif

// Scale evaluation by the material left on the board. akimbo measured a scalar
// term like this beating its own eight output buckets by +4.34 over 24,720
// games, for a fraction of the work.
#ifndef SGR_MATSCALE
#define SGR_MATSCALE 0
#endif

// Try a null move only when the static eval is already at or above beta. Below
// it, the reduced search almost always fails and its nodes are wasted.
#ifndef SGR_NMP_EVAL
#define SGR_NMP_EVAL 1
#endif
#if SGR_NMP_EVAL && !SGR_IMPROVING
#error "SGR_NMP_EVAL needs SGR_IMPROVING for the per-node static eval"
#endif

// Fail-low nodes store no TT move, since none of their moves proved anything,
// and a store without a move keeps the move already held for that position.
#ifndef SGR_TTMOVE_KEEP
#define SGR_TTMOVE_KEEP 1
#endif

// Quiescence probes the transposition table for a cutoff and a capture to try
// first, and stores its own results. Its stores never evict a main-search
// entry for another position: quiescence nodes far outnumber main-search ones
// and would flush the deep results out of a one-slot table.
#ifndef SGR_QS_TT
#define SGR_QS_TT 1
#endif

// Principal-variation nodes (open window) take no TT cutoffs, so the line the
// engine plays is always searched rather than read back from the table.
#ifndef SGR_PV_TTCUT
#define SGR_PV_TTCUT 1
#endif

// Principal-variation nodes reduce late moves one ply less.
#ifndef SGR_PV_LMR
#define SGR_PV_LMR 1
#endif

// Singular refinements. Double (and triple) extensions when the alternatives
// fall far short of the TT move, capped per line so the search cannot explode.
#ifndef SGR_SE_DOUBLE
#define SGR_SE_DOUBLE 1
#endif
// Multicut: when the reduced search without the TT move already beats beta,
// another move refutes this node too, so it fails high without searching.
#ifndef SGR_SE_MULTICUT
#define SGR_SE_MULTICUT 1
#endif
// Negative extensions: a TT move that is not singular is searched less.
#ifndef SGR_SE_NEGATIVE
#define SGR_SE_NEGATIVE 1
#endif

// Principal-variation nodes skip the early exits that stand in for a search:
// reverse futility, the shallow drop into quiescence, razoring and null move.
// They are a small part of the tree, and they decide the line that is played.
#ifndef SGR_PV_PRUNE
#define SGR_PV_PRUNE 1
#endif
// Mate-distance pruning. No line through a node can mate sooner than the next
// ply or be mated sooner than now, so the window is bounded to that range, and
// a node that cannot beat a mate already found returns at once.
#ifndef SGR_MDP
#define SGR_MDP 1
#endif


// Search parameters exposed through UCI.
// Fractional values use integer scaling because UCI spin options are integral.
// Tune time settings against a pool gauntlet, not self-play alone.
struct SearchParams {
    // Pruning
    int rfp_margin              = 100;
    int rfp_max_depth           = 6;
    int lmp_max_depth           = 3;
    int lmp_count_1             = 6;
    int lmp_count_2             = 12;
    int lmp_count_3             = 18;
    int futility_margin_1       = 150;
    int futility_margin_2       = 300;

    // Reductions
    int null_move_reduction     = 2;
    int lmr_min_depth           = 3;
    int lmr_full_depth_moves    = 2;
    int lmr_div_x100            = 241;   // SPSA 250 -> 241   // Scaled form of the 2.5 LMR divisor.
    // Bounded history (SGR_HIST_GRAVITY) sits on a larger scale. Its
    // settings change reductions and prune quiets at the old rates, measured
    // replaying games at 400k nodes a move: 19% of reduced quiets reduced
    // further, 20% of tested quiets pruned.
    int histlmr_div             = SGR_HIST_GRAVITY ? 6200 : 228;   // SPSA 400000 -> 228
    int histlmr_max             = 2;

    // Extensions
    int singular_min_depth      = 7;
    int singular_tt_depth_slack = 3;
    int singular_margin         = 2;
    int se_double_margin        = 16;    // Shortfall below singular beta for +2.
    int se_triple_margin        = 80;    // Shortfall for +3 on a quiet TT move.
    int se_double_limit         = 8;     // Double extensions allowed per line.
    int check_ext_max_depth     = 4;
    // score * (base + phase) / div, phase 0..24. Neutral at full material.
    int matscale_base           = 104;
    int matscale_div            = 128;

    // Windows
    int aspiration_window       = 50;
    int delta_margin            = 200;

    // Version 9 experiments
    int iir_min_depth           = 8;   // SPSA 4 -> 8     // Reduce nodes without a TT move from this depth.
    int iir_reduction           = 1;
    int nmp_depth_div           = 6;     // Depth divisor for null-move reduction.
    int nmp_eval_div            = 71;   // SPSA 200 -> 71   // Eval-surplus divisor for null-move reduction.
    int nmp_eval_max            = 3;     // Maximum eval-based reduction.
    int razor_max_depth         = 4;     // Maximum depth for verified razoring.
    // Centipawns per ply in the razoring margin.
    int razor_margin            = 500;   // SPSA 100 -> 500

    int fut_max_depth           = 6;     // Maximum move-loop futility depth.
    int fut_margin              = 144;   // SPSA 120 -> 144   // Centipawns per remaining ply.
    int see_max_depth           = 8;     // Maximum SEE pruning depth.
    int see_quiet_margin        = 46;   // SPSA 50 -> 46    // Linear quiet-move SEE margin.
    int see_cap_margin          = 26;   // SPSA 20 -> 26    // Quadratic capture SEE margin.
    int histprune_max_depth     = 3;
    // Prune quiets below the negative history margin times depth.
    int histprune_margin        = SGR_HIST_GRAVITY ? 2000 : 75;   // SPSA 50 -> 75

    // Keep capture history within its MVV-LVA tier.
    int caphist_div             = 1;
    int caphist_max             = 87;   // SPSA 256 -> 87

    // Move ordering, batch F. Starting values, for the tune to set.
    int hist_bonus_mul          = 200;   // History bonus per ply of depth.
    int hist_bonus_sub          = 100;
    int hist_bonus_max          = 2000;
    int cap_mvv_mul             = 16;    // Victim value's weight in capture order.
    int quiet_sort_limit        = 3000;  // Quiets below -limit * depth stay unsorted.
    // Quiets above this go before losing captures. Cutoffs came sooner with
    // losing captures ahead of all but the strongest quiets.
    int good_quiet_min          = 16000;

    // Correction history, batch G. A weight per table, 0 to switch it off,
    // and the learning rate. Chosen by replaying games against a deep
    // search; the tune sets them properly.
    int corr_pawn_w             = 512;
    int corr_nonpawn_w          = 512;   // each side's pieces, two tables
    int corr_minor_w            = 512;
    int corr_major_w            = 512;
    int corr_rate               = 16;
    // Start and floor for halfmove-clock evaluation scaling.
    int evalscale_start         = 40;
    int evalscale_min_pct       = 40;    // Minimum retained evaluation percentage.

    // Time management
    int soft_time_fraction_x100 = static_cast<int>(SGR_SOFT_TIME_FRACTION * 100);
    int bm_stability_x100[BM_STABILITY_COUNT] = {220, 130, 100, 85, 75};

    // Clock management under SGR_TM2. Shares are of the clock left once the
    // move overhead is held back; see allocate_time() in search.cpp. Starting
    // values match the anchors' spending by game stage in a model of the
    // pool's own game lengths; the tune sets them properly.
    int tm_horizon_start        = 30;    // Moves the clock is spread over at move 1.
    int tm_horizon_drop_x100    = 50;    // Moves the horizon shortens per move played.
    int tm_horizon_min          = 18;    // Floor on the horizon.
    int tm_inc_pct              = 50;    // Share of the increment added to each budget.
    int tm_budget_clock_pct     = 20;    // Cap on a budget as a share of the clock.
    int tm_optimum_pct          = 85;    // No new iteration once past this share of the budget.
    int tm_max_budget_x10       = 50;    // Hard limit in tenths of a budget,
    int tm_max_clock_pct        = 30;    // and at most this share of the clock.
    int tm_node_base_pct        = 50;    // Time factor if every root node went to the best move,
    int tm_node_slope_pct       = 150;   // plus this per unit share spent on other moves,
    int tm_node_min_pct         = 50;    // clamped to this range.
    int tm_node_max_pct         = 160;
    int tm_score_drop_cp        = 100;   // A fall of this many centipawns doubles the time,
    int tm_score_min_pct        = 80;    // clamped to this range.
    int tm_score_max_pct        = 160;
};

// Global parameters for the single-threaded engine.
extern SearchParams params;

#if SGR_TM2
// Time for one move under a clock, in milliseconds. The budget is the planned
// spend; no new iteration starts past the optimum; the search stops at the
// maximum whatever happens.
struct TimeAllocation {
    double budget;
    double optimum;
    double maximum;
};

TimeAllocation allocate_time(long long time_left_ms, long long inc_ms,
                             std::optional<long long> movestogo,
                             int fullmove_number, long long overhead_ms);
#endif

// Rebuild tables derived from params after a relevant option changes.
void refresh_derived_params();

struct SearchResult {
    std::optional<Move> best_move = std::nullopt;
    int score = 0;
    int depth = 0;
    long long nodes = 0;
    long long tt_hits = 0;
    double time_taken = 0.0;
};

// Sixteen-byte transposition entry with a full 64-bit key.
// Score remains 32-bit for mate values and depth fits the 127-ply limit.
struct TTEntry {
    U64 key = 0;                    // Full hash. Zero marks an empty entry.
    std::int32_t score = 0;
    std::int8_t depth = -1;
    std::uint8_t flag = TT_EXACT;
    Move best_move = NO_MOVE;       // NO_MOVE means no stored move.
};

static_assert(sizeof(TTEntry) == 16,
              "TTEntry must stay 16 bytes: 4 per cache line is the point");

class Engine {
public:
    long long nodes = 0;
    long long tt_hits = 0;

    std::vector<TTEntry> transposition_table;   // Indexed by hash & tt_mask.
    std::size_t tt_size = 0;
    U64 tt_mask = 0;

    Engine();

    // Resize to a power-of-two entry count and discard existing entries.
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
    // Damp non-mate evaluations as the fifty-move clock rises.
    int scale_for_fifty_move(const Board& board, int score) const;
#endif
#if SGR_MATSCALE
    // Damp evaluations as material comes off.
    int scale_for_material(const Board& board, int score) const;
#endif
#if SGR_CORRHIST
    // Correction tables by side to move. An entry is bounded by gravity like
    // history, and a weight of 512 turns a full entry into 128 centipawns.
    // They sit on the heap: at a third of a megabyte they would crowd the
    // main thread's stack, where the engine object lives.
#ifndef SGR_CORR_BITS
#define SGR_CORR_BITS 14
#endif
    static constexpr int CORR_BITS  = SGR_CORR_BITS;
    static constexpr int CORR_SIZE  = 1 << CORR_BITS;
    static constexpr int CORR_LIMIT = 16384;
    static constexpr int CORR_SCALE = 65536;
    using CorrTable = std::array<std::array<std::int16_t, CORR_SIZE>, 2>;
    struct CorrTables {
        CorrTable pawn;
        std::array<CorrTable, 2> nonpawn;   // keyed by one colour's pieces
        CorrTable minor;
        CorrTable major;
    };
    std::unique_ptr<CorrTables> corr = std::make_unique<CorrTables>();

    // Where a position's entries sit in each table.
    struct CorrIndex {
        int side, pawn, white, black, minor, major;
    };
    static CorrIndex corr_index(const Board& board);

    // The correction in centipawns, and the update towards a search score
    // that missed the corrected eval by error centipawns.
    int correction(const Board& board) const;
    void update_correction(const Board& board, int depth, int error);
    // Start loading a position's entries, from the move that reaches it.
    void prefetch_correction(const Board& board) const;
    void reset_corrhist();
#endif
    int evaluate_quiet_position(const Board& board) const;
    MoveList generate_moves(Board& board) const;

    // Transposition table occupancy in permille for UCI hashfull.
    int hashfull() const;

    // Called with each time check, every few hundred nodes. Returning true
    // stops the search as if time had run out. The UCI loop uses it to act
    // on stop and quit mid-search; everything else leaves it unset.
    bool (*poll)() = nullptr;

private:
    std::chrono::steady_clock::time_point start_time;
    std::optional<double> time_limit = std::nullopt;         // Hard search deadline.
    std::optional<double> soft_time_limit = std::nullopt;    // Deadline for new iterations.
    std::optional<long long> node_limit = std::nullopt;
    bool stop_search = false;

#if SGR_TM2
    // Nodes spent under each root move in this search, for the node share.
    std::vector<std::pair<Move, long long>> root_effort;
    // The last clock search's final score, from the side it moved for. A
    // lower score now means the reply was a surprise.
    int last_clock_score = 0;
    bool have_last_clock_score = false;
#endif

    std::array<std::array<std::optional<Move>, 2>, MAX_PLY> killer_moves{};
    // Butterfly history by from and to square, one table per side to move
    // under SGR_HIST_COLOUR.
    std::array<std::array<std::array<int, 64>, 64>, SGR_HIST_COLOUR ? 2 : 1> history{};

    int& butterfly(int side, const Move& move) {
        return history[SGR_HIST_COLOUR ? side : 0][move.from()][move.to()];
    }
    int butterfly(int side, const Move& move) const {
        return history[SGR_HIST_COLOUR ? side : 0][move.from()][move.to()];
    }

    // A quiet move's ordering score: butterfly history plus, in the main
    // search, continuation history for the moves before it.
    int quiet_history(const Board& board, const Move& move, int ply, bool with_cont) const;

    // Reward (bonus > 0) or penalise a quiet move in every table that scores it.
    void update_quiet_history(const Board& board, const Move& move, int ply, int bonus);

    int history_bonus(int depth) const;

#if SGR_IMPROVING
    // Static eval stack used by the improving heuristic.
    std::array<int, MAX_PLY> ss_static_eval{};
#endif

#if SGR_SE_DOUBLE
    // Double extensions taken on the line to each ply.
    std::array<int, MAX_PLY + 1> ss_double_ext{};
#endif

#if SGR_CONTHIST
    // Flattened continuation history stored on the heap.
    std::vector<int> conthist;

    // Moving piece and destination at each ply. A -1 piece means no prior move.
    std::array<int, MAX_PLY> ss_piece{};
    std::array<int, MAX_PLY> ss_to{};

    static int conthist_index(int prev_piece, int prev_to, int piece, int to) {
        return ((prev_piece * 64 + prev_to) * 12 + piece) * 64 + to;
    }
#endif

#if SGR_CAPHIST
    // Flattened capture history stored inline.
    std::array<int, 12 * 64 * 6> caphist{};

    static int caphist_index(int piece, int to, int victim_type) {
        return (piece * 64 + to) * 6 + victim_type;
    }

    // Victim type by piece, with en passant represented as a pawn.
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

    // Singular searches exclude one move and disable null moves and TT stores.
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

#if SGR_PICKER2
    // Staged picker. Stages run TT move, winning captures, killers, promising
    // quiets, losing captures, then the other quiets. Each stage scores its own
    // moves when it starts, so a node that cuts off early pays for little, and
    // quiets are scored with history learnt while the earlier moves were
    // searched. Outside the main search there is no split by SEE.
    class MovePicker {
    public:
        MovePicker(const Engine& eng,
                   Board& board,
                   const MoveList& moves,
                   const std::optional<Move>& tt_move_key,
                   int ply,
                   int depth,
                   bool main_search);

        // Return the next move or false when exhausted.
        bool next(Move& out);

    private:
        // Raw 16-bit moves, so the arrays need no initialising.
        struct Scored { std::uint16_t move; int score; };

        enum Stage {
            S_TT, S_CAPTURE_INIT, S_GOOD_CAPTURE, S_KILLER1, S_KILLER2,
            S_QUIET_INIT, S_GOOD_QUIET, S_BAD_CAPTURE, S_BAD_QUIET, S_DONE
        };

        bool in_list(const Move& move) const;
        bool next_move(Move& out);

#if SGR_PICKER_CHECK
        // Test builds check every move comes out exactly once.
        bool seen_[256] = {};
        int returned_ = 0;
#endif

        const Engine* eng_;
        const Board* board_;
        const MoveList* moves_;
        int ply_;
        int depth_;
        bool main_;

        Move tt_move_ = NO_MOVE;   bool has_tt_ = false;
        Move killer_[2];           // killers tried, skipped among the quiets
        int n_killers_ = 0;

        Scored caps_[256];            int n_caps_ = 0;
        std::uint16_t bad_caps_[256]; int n_bad_ = 0;
        Scored quiets_[256];          int n_quiets_ = 0;

        int stage_ = S_TT;
        int index_ = 0;       // next capture, then next quiet
        int bad_index_ = 0;   // next losing capture
    };
#else
    // Lazy move picker that sorts each bucket only when reached.
    class MovePicker {
    public:
        MovePicker(const Engine& eng,
                   Board& board,
                   const MoveList& moves,
                   const std::optional<Move>& tt_move_key,
                   int ply,
                   int depth,
                   bool split_bad_captures);

        // Return the next move or false when exhausted.
        bool next(Move& out);

    private:
        // The move is kept as its raw 16 bits so these arrays need no
        // initialising. A default Move zeroes itself, and zeroing four
        // 256-entry buckets on every node cost 12.6% of search time.
        struct Scored { std::uint16_t move; int score; };

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

        // SEE splits good captures from bad only when the capture stage is
        // reached, so nodes that cut on the TT move never pay for it.
        const Board* board_ = nullptr;
        bool split_bad_ = false;

        int stage_ = S_TT;
        int index_ = 0;
        bool sorted_cap_ = false;
        bool sorted_bad_ = false;
        bool sorted_gq_ = false;
        bool sorted_oq_ = false;
    };
#endif

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

#if SGR_QS_TT
    // Depth-0 store that never evicts a main-search entry for another position.
    void store_tt_qs(U64 board_hash, int score, int flag, Move best_move_key);
#endif

#if SGR_PV_TABLE
    // Make move the best at ply, followed by the line recorded below it.
    void update_pv(int ply, const Move& move);

    // The last root search's line, if it starts with best_move.
    std::vector<Move> recorded_principal_variation(
        Board& board,
        const Move& best_move,
        int depth
    );

    // Row ply of pv_moves holds the best line found from ply, up to
    // pv_length[ply]. Both are on the heap so the engine object keeps its size.
    std::vector<Move> pv_moves = std::vector<Move>(MAX_PLY * MAX_PLY);
    std::vector<int> pv_length = std::vector<int>(MAX_PLY);
#endif
};
