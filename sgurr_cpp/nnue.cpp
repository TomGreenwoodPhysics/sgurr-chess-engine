#include "nnue.hpp"
#include "board.hpp"

#include <array>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <vector>

// SGR_SIMD uses int16 accumulators and vectorised output.
// Clipped feature weights keep every accumulator safely within int16.
#if SGR_SIMD
#if !defined(__AVX2__)
#error "SGR_SIMD needs AVX2 (build with -march=native on any modern x86, or set -DSGR_SIMD=0 for the scalar path)"
#endif
#include <immintrin.h>
static_assert(nnue::HL % 16 == 0, "SGR_SIMD requires HL to be a multiple of 16");
// Vector lane sums are int32. The theoretical worst case (every out_weight at
// an int16 extreme) is x2.01 under the limit at HL=1024 on AVX-512 and exactly
// x1.00 on AVX2, so 1024 is the last width that is safe without int64
// widening. load() also bounds the sum from the weights actually loaded, which
// is what makes this safe rather than merely probable.
static_assert(nnue::HL <= 1024, "SGR_SIMD output sum needs int64 widening for HL>1024");
#endif

namespace nnue {

namespace {

struct Network {
    std::vector<std::int16_t> ft_weight;   // Feature-major weights for all buckets.
    std::array<std::int16_t, HL> ft_bias{};
    std::array<std::int16_t, 2 * HL> out_weight{};
    std::int32_t out_bias = 0;
    // King buckets read from version 2 network files.
    // Black mirrors its own king square with sq^56.
    int buckets = 1;
    std::array<std::uint8_t, 64> bucket_map{};
};

Network g_net;
bool g_active = false;

#if SGR_SIMD
using AccT = std::int16_t;
#else
using AccT = std::int32_t;
#endif

// Map a piece to one perspective, mirroring and swapping colours for Black.
inline int feature_index(int persp, int colour, int ptype, int sq) {
    int rel_sq = (persp == WHITE) ? sq : (sq ^ 56);
    int rel_colour = (colour == persp) ? 0 : 1;
    return rel_colour * 384 + ptype * 64 + rel_sq;
}

#if SGR_SIMD
#if defined(__AVX512BW__)
// AVX-512 path with 32 int16 lanes per instruction.
static_assert(nnue::HL % 32 == 0, "AVX-512 path requires HL % 32 == 0");

inline void vec_add(AccT* acc, const std::int16_t* w) {
    for (int k = 0; k < HL; k += 32) {
        __m512i a  = _mm512_loadu_si512(acc + k);
        __m512i wv = _mm512_loadu_si512(w + k);
        _mm512_storeu_si512(acc + k, _mm512_add_epi16(a, wv));
    }
}

inline void vec_sub(AccT* acc, const std::int16_t* w) {
    for (int k = 0; k < HL; k += 32) {
        __m512i a  = _mm512_loadu_si512(acc + k);
        __m512i wv = _mm512_loadu_si512(w + k);
        _mm512_storeu_si512(acc + k, _mm512_sub_epi16(a, wv));
    }
}

// Clamp and multiply both perspectives before reducing to one int32.
// One vector of output terms. Clipped ReLU multiplies the activation by its
// weight; squared clipped ReLU multiplies by the activation a second time.
// The a*w product stays in int16 only because load() checks
// QA * max|out_weight| against 32767 -- at QA=255 that leaves ~2% headroom.
inline __m512i out_term(__m512i a, __m512i wv) {
#if SGR_SCRELU
    return _mm512_madd_epi16(_mm512_mullo_epi16(a, wv), a);
#else
    return _mm512_madd_epi16(a, wv);
#endif
}

inline std::int32_t forward_sum(const AccT* us, const AccT* them) {
    const __m512i zero = _mm512_setzero_si512();
    const __m512i vqa  = _mm512_set1_epi16(static_cast<short>(QA));
    const std::int16_t* w = g_net.out_weight.data();
    __m512i sum = _mm512_setzero_si512();
    for (int k = 0; k < HL; k += 32) {
        __m512i a = _mm512_loadu_si512(us + k);
        a = _mm512_min_epi16(_mm512_max_epi16(a, zero), vqa);   // Clipped ReLU.
        sum = _mm512_add_epi32(sum, out_term(a, _mm512_loadu_si512(w + k)));
    }
    for (int k = 0; k < HL; k += 32) {
        __m512i a = _mm512_loadu_si512(them + k);
        a = _mm512_min_epi16(_mm512_max_epi16(a, zero), vqa);
        sum = _mm512_add_epi32(sum, out_term(a, _mm512_loadu_si512(w + HL + k)));
    }
    return _mm512_reduce_add_epi32(sum);
}
const char* const kSimdKind = "avx512";

#else
// AVX2 path with 16 int16 lanes per instruction.
inline void vec_add(AccT* acc, const std::int16_t* w) {
    for (int k = 0; k < HL; k += 16) {
        __m256i a  = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(acc + k));
        __m256i wv = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(w + k));
        _mm256_storeu_si256(reinterpret_cast<__m256i*>(acc + k), _mm256_add_epi16(a, wv));
    }
}

inline void vec_sub(AccT* acc, const std::int16_t* w) {
    for (int k = 0; k < HL; k += 16) {
        __m256i a  = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(acc + k));
        __m256i wv = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(w + k));
        _mm256_storeu_si256(reinterpret_cast<__m256i*>(acc + k), _mm256_sub_epi16(a, wv));
    }
}

inline std::int32_t hsum_epi32(__m256i v) {
    __m128i s = _mm_add_epi32(_mm256_castsi256_si128(v),
                              _mm256_extracti128_si256(v, 1));
    s = _mm_add_epi32(s, _mm_shuffle_epi32(s, _MM_SHUFFLE(1, 0, 3, 2)));
    s = _mm_add_epi32(s, _mm_shuffle_epi32(s, _MM_SHUFFLE(2, 3, 0, 1)));
    return _mm_cvtsi128_si32(s);
}

// See the AVX-512 out_term above for why a*w is safe in int16.
inline __m256i out_term(__m256i a, __m256i wv) {
#if SGR_SCRELU
    return _mm256_madd_epi16(_mm256_mullo_epi16(a, wv), a);
#else
    return _mm256_madd_epi16(a, wv);
#endif
}

inline std::int32_t forward_sum(const AccT* us, const AccT* them) {
    const __m256i zero = _mm256_setzero_si256();
    const __m256i vqa  = _mm256_set1_epi16(static_cast<short>(QA));
    const std::int16_t* w = g_net.out_weight.data();
    __m256i sum = _mm256_setzero_si256();
    for (int k = 0; k < HL; k += 16) {
        __m256i a = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(us + k));
        a = _mm256_min_epi16(_mm256_max_epi16(a, zero), vqa);   // Clipped ReLU.
        sum = _mm256_add_epi32(sum, out_term(
                  a, _mm256_loadu_si256(reinterpret_cast<const __m256i*>(w + k))));
    }
    for (int k = 0; k < HL; k += 16) {
        __m256i a = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(them + k));
        a = _mm256_min_epi16(_mm256_max_epi16(a, zero), vqa);
        sum = _mm256_add_epi32(sum, out_term(
                  a, _mm256_loadu_si256(reinterpret_cast<const __m256i*>(w + HL + k))));
    }
    return hsum_epi32(sum);
}
const char* const kSimdKind = "avx2";
#endif

#else
inline std::int32_t crelu(std::int32_t x) {
    if (x < 0) return 0;
    if (x > QA) return QA;
    return x;
}
const char* const kSimdKind = "scalar";
#endif

// Check whether the moving king crosses its perspective's bucket boundary.
inline bool crosses_bucket(const UndoInfo& undo) {
    if (g_net.buckets <= 1) return false;
    const Move& m = undo.move;
    if (undo.moved_piece == WK)
        return g_net.bucket_map[m.from()] != g_net.bucket_map[m.to()];
    if (undo.moved_piece == BK)
        return g_net.bucket_map[m.from() ^ 56] != g_net.bucket_map[m.to() ^ 56];
    return false;
}

// Rook squares moved by castling, keyed by the king's destination.
inline bool castling_rook(int king_to, int& rook, int& rf, int& rt) {
    switch (king_to) {
        case 6:  rook = WR; rf = 7;  rt = 5;  return true;   // White kingside.
        case 2:  rook = WR; rf = 0;  rt = 3;  return true;   // White queenside.
        case 62: rook = BR; rf = 63; rt = 61; return true;   // Black kingside.
        case 58: rook = BR; rf = 56; rt = 59; return true;   // Black queenside.
        default: return false;
    }
}

// Clamp, multiply and sum both accumulators. All paths are bit-identical.
std::int64_t output_from_acc(const AccT* white, const AccT* black, int side_to_move) {
    const AccT* us   = side_to_move == WHITE ? white : black;
    const AccT* them = side_to_move == WHITE ? black : white;
    // Squaring leaves the sum with an extra factor of QA, so it is divided out
    // before the bias, which is stored at QA*QB either way.
#if SGR_SIMD
    std::int64_t sum = forward_sum(us, them);
#else
    std::int64_t sum = 0;
    for (int k = 0; k < HL; ++k) {
        std::int64_t v = crelu(us[k]);
#if SGR_SCRELU
        sum += v * v * g_net.out_weight[k];
#else
        sum += v * g_net.out_weight[k];
#endif
    }
    for (int k = 0; k < HL; ++k) {
        std::int64_t v = crelu(them[k]);
#if SGR_SCRELU
        sum += v * v * g_net.out_weight[HL + k];
#else
        sum += v * g_net.out_weight[HL + k];
#endif
    }
#endif
#if SGR_SCRELU
    sum /= QA;
#endif
    return sum + g_net.out_bias;
}

#if SGR_EVAL_CACHE
struct EvalEntry {
    U64 key = 0;        // Zero marks an empty entry.
    int score = 0;
};
constexpr std::size_t EVAL_CACHE_SIZE = std::size_t{1} << SGR_EVAL_CACHE_BITS;
EvalEntry g_eval_cache[EVAL_CACHE_SIZE];

inline void clear_eval_cache() {
    for (auto& e : g_eval_cache) e = EvalEntry{};
}
#endif

inline int to_cp(std::int64_t output) {
    std::int64_t cp = output * SCALE / (static_cast<std::int64_t>(QA) * QB);

    // Keep the score well away from mate territory.
    if (cp > 29000) cp = 29000;
    if (cp < -29000) cp = -29000;
    return static_cast<int>(cp);
}

#if SGR_NNUE_STACK
// ---------------------------------------------------------------------------
// Accumulator stack: one level per ply, computed lazily.

// Deep enough for a search (under 128 plies) on top of a long game's moves.
// Running out is handled by starting again from one level, so this is a
// speed limit, not a correctness one.
constexpr int STACK_LEVELS = 1024;

// One ply. computed: acc holds the sums for the position tagged by hash.
// stale: this level cannot be derived from its parent (a king crossed a bucket
// boundary, or the stack fell out of step with the board) and is rebuilt from
// the board when needed. Otherwise it records the features its move changed.
struct alignas(64) Level {
    AccT acc[2][HL];
    U64 hash = 0;
    int off[2] = {0, 0};   // King-bucket feature offsets, set when computed.
    bool computed = false;
    bool stale = true;
    std::int8_t n_add = 0, n_sub = 0;
    std::int8_t add_piece[2] = {}, add_sq[2] = {};
    std::int8_t sub_piece[2] = {}, sub_sq[2] = {};
};

Level g_stack[STACK_LEVELS];
int g_top = 0;

inline const std::int16_t* feature_row(int persp, int off, int piece, int sq) {
    int idx = feature_index(persp, piece / 6, piece % 6, sq);
    return &g_net.ft_weight[static_cast<std::size_t>(off + idx) * HL];
}

inline void add_row(AccT* acc, const std::int16_t* w) {
#if SGR_SIMD
    vec_add(acc, w);
#else
    for (int k = 0; k < HL; ++k) acc[k] += w[k];
#endif
}

// out = in + adds - subs in a single pass. int16 lanes wrap and int32 ones do
// not overflow, so this is bit-identical to applying the rows one at a time.
template <int NA, int NS>
inline void acc_fused(AccT* out, const AccT* in,
                      const std::int16_t* const* add, const std::int16_t* const* sub) {
#if SGR_SIMD
#if defined(__AVX512BW__)
    for (int k = 0; k < HL; k += 32) {
        __m512i v = _mm512_loadu_si512(in + k);
        for (int i = 0; i < NA; ++i) v = _mm512_add_epi16(v, _mm512_loadu_si512(add[i] + k));
        for (int i = 0; i < NS; ++i) v = _mm512_sub_epi16(v, _mm512_loadu_si512(sub[i] + k));
        _mm512_storeu_si512(out + k, v);
    }
#else
    for (int k = 0; k < HL; k += 16) {
        __m256i v = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(in + k));
        for (int i = 0; i < NA; ++i)
            v = _mm256_add_epi16(v, _mm256_loadu_si256(reinterpret_cast<const __m256i*>(add[i] + k)));
        for (int i = 0; i < NS; ++i)
            v = _mm256_sub_epi16(v, _mm256_loadu_si256(reinterpret_cast<const __m256i*>(sub[i] + k)));
        _mm256_storeu_si256(reinterpret_cast<__m256i*>(out + k), v);
    }
#endif
#else
    for (int k = 0; k < HL; ++k) {
        AccT v = in[k];
        for (int i = 0; i < NA; ++i) v += add[i][k];
        for (int i = 0; i < NS; ++i) v -= sub[i][k];
        out[k] = v;
    }
#endif
}

// A legal move changes (adds, removes): quiet or promotion (1, 1), capture,
// capture-promotion or en passant (1, 2), castling (2, 2).
inline void acc_apply(AccT* out, const AccT* in, int na, const std::int16_t* const* add,
                      int ns, const std::int16_t* const* sub) {
    if (na == 1 && ns == 1)      acc_fused<1, 1>(out, in, add, sub);
    else if (na == 1 && ns == 2) acc_fused<1, 2>(out, in, add, sub);
    else if (na == 2 && ns == 2) acc_fused<2, 2>(out, in, add, sub);
    else {
        // Not reachable from a legal move; kept correct rather than assumed away.
        std::memcpy(out, in, HL * sizeof(AccT));
        for (int i = 0; i < na; ++i) add_row(out, add[i]);
        for (int i = 0; i < ns; ++i) {
#if SGR_SIMD
            vec_sub(out, sub[i]);
#else
            for (int k = 0; k < HL; ++k) out[k] -= sub[i][k];
#endif
        }
    }
}

// Rebuild one level from the board.
void rebuild(Level& L, const Board& board) {
    if (g_net.buckets > 1) {
        int wk = __builtin_ctzll(board.bitboards[WK]);
        int bk = __builtin_ctzll(board.bitboards[BK]);
        L.off[0] = g_net.bucket_map[wk] * INPUT;
        L.off[1] = g_net.bucket_map[bk ^ 56] * INPUT;
    } else {
        L.off[0] = L.off[1] = 0;
    }
    for (int persp = 0; persp < 2; ++persp) {
#if SGR_SIMD
        // Accumulator and stored bias types match in SIMD builds.
        std::memcpy(L.acc[persp], g_net.ft_bias.data(), HL * sizeof(AccT));
#else
        for (int k = 0; k < HL; ++k) L.acc[persp][k] = g_net.ft_bias[k];
#endif
    }
    for (int piece = 0; piece < 12; ++piece) {
        std::uint64_t bb = board.bitboards[piece];
        while (bb) {
            int sq = __builtin_ctzll(bb);
            bb &= bb - 1;
            add_row(L.acc[0], feature_row(WHITE, L.off[0], piece, sq));
            add_row(L.acc[1], feature_row(BLACK, L.off[1], piece, sq));
        }
    }
    L.computed = true;
    L.stale = false;
    L.hash = board.hash_key;
}

// Compute level j from its computed parent. No king crossed a bucket boundary
// between them, so the parent's offsets still apply.
void derive(int j) {
    Level& L = g_stack[j];
    const Level& P = g_stack[j - 1];
    L.off[0] = P.off[0];
    L.off[1] = P.off[1];
    for (int persp = 0; persp < 2; ++persp) {
        const std::int16_t* add[2];
        const std::int16_t* sub[2];
        for (int i = 0; i < L.n_add; ++i)
            add[i] = feature_row(persp, L.off[persp], L.add_piece[i], L.add_sq[i]);
        for (int i = 0; i < L.n_sub; ++i)
            sub[i] = feature_row(persp, L.off[persp], L.sub_piece[i], L.sub_sq[i]);
        acc_apply(L.acc[persp], P.acc[persp], L.n_add, add, L.n_sub, sub);
    }
    L.computed = true;
}

// The current level, computed for this board.
const Level& current(const Board& board) {
    Level& top = g_stack[g_top];
    if (top.hash != board.hash_key) {
        // Out of step with the board: never trust it, rebuild.
        rebuild(top, board);
        return top;
    }
    if (top.computed) return top;

    int i = g_top;
    while (i > 0 && !g_stack[i].computed && !g_stack[i].stale) --i;
    if (!g_stack[i].computed) {
        // A stale level (or an unbuilt root) lies between: rebuild the top.
        rebuild(top, board);
        return top;
    }
    for (int j = i + 1; j <= g_top; ++j) derive(j);
    return top;
}

void mark_stale(Level& L, U64 hash) {
    L.hash = hash;
    L.computed = false;
    L.stale = true;
}
#else
// ---------------------------------------------------------------------------
// Single accumulator, updated on every make and unmake. Kept for comparison.

// Current feature offset for each perspective's king bucket.
int g_bucket_off[2] = {0, 0};

// White and black accumulators tagged with their position key.
alignas(64) AccT g_acc[2][HL];
bool g_acc_valid = false;
U64 g_acc_hash = 0;

// Add or remove one piece from both accumulators.
inline void edit_feature(int piece, int sq, int sign) {
    int colour = piece / 6;
    int ptype = piece % 6;
    int iw = feature_index(WHITE, colour, ptype, sq);
    int ib = feature_index(BLACK, colour, ptype, sq);
    const std::int16_t* ww =
        &g_net.ft_weight[static_cast<std::size_t>(g_bucket_off[0] + iw) * HL];
    const std::int16_t* wb =
        &g_net.ft_weight[static_cast<std::size_t>(g_bucket_off[1] + ib) * HL];
#if SGR_SIMD
    if (sign > 0) { vec_add(g_acc[0], ww); vec_add(g_acc[1], wb); }
    else          { vec_sub(g_acc[0], ww); vec_sub(g_acc[1], wb); }
#else
    if (sign > 0) {
        for (int k = 0; k < HL; ++k) { g_acc[0][k] += ww[k]; g_acc[1][k] += wb[k]; }
    } else {
        for (int k = 0; k < HL; ++k) { g_acc[0][k] -= ww[k]; g_acc[1][k] -= wb[k]; }
    }
#endif
}

// Apply move feature deltas, including en passant and castling.
void apply_move(const UndoInfo& undo, int s) {
    const Move& m = undo.move;
    edit_feature(undo.moved_piece, m.from(), -s);
    edit_feature(undo.placed_piece, m.to(), +s);
    if (undo.captured_piece >= 0)
        edit_feature(undo.captured_piece, undo.captured_square, -s);
    int rook, rf, rt;
    if (m.is_castling() && castling_rook(m.to(), rook, rf, rt)) {
        edit_feature(rook, rf, -s);
        edit_feature(rook, rt, +s);
    }
}
#endif

}  // namespace

#if SGR_NNUE_STACK
void refresh(const Board& board) {
    rebuild(g_stack[g_top], board);
}

void reset(const Board& board) {
    g_top = 0;
    rebuild(g_stack[0], board);
}

void on_make(const UndoInfo& undo, std::uint64_t new_hash) {
    // A move follows on from the current level only if that level is this
    // move's starting position and the king stays in its bucket.
    const bool follows = g_stack[g_top].hash == undo.old_hash_key && !crosses_bucket(undo);

    if (g_top + 1 >= STACK_LEVELS) {
        // Out of levels: start again from one level, rebuilt when needed.
        g_top = 0;
        mark_stale(g_stack[0], new_hash);
        return;
    }

    Level& L = g_stack[++g_top];
    L.hash = new_hash;
    L.computed = false;
    L.stale = !follows;
    if (!follows) return;

    const Move& m = undo.move;
    L.n_add = 0;
    L.n_sub = 0;
    L.sub_piece[L.n_sub] = static_cast<std::int8_t>(undo.moved_piece);
    L.sub_sq[L.n_sub++]  = static_cast<std::int8_t>(m.from());
    L.add_piece[L.n_add] = static_cast<std::int8_t>(undo.placed_piece);
    L.add_sq[L.n_add++]  = static_cast<std::int8_t>(m.to());
    if (undo.captured_piece >= 0) {
        L.sub_piece[L.n_sub] = static_cast<std::int8_t>(undo.captured_piece);
        L.sub_sq[L.n_sub++]  = static_cast<std::int8_t>(undo.captured_square);
    }
    int rook, rf, rt;
    if (m.is_castling() && castling_rook(m.to(), rook, rf, rt)) {
        L.sub_piece[L.n_sub] = static_cast<std::int8_t>(rook);
        L.sub_sq[L.n_sub++]  = static_cast<std::int8_t>(rf);
        L.add_piece[L.n_add] = static_cast<std::int8_t>(rook);
        L.add_sq[L.n_add++]  = static_cast<std::int8_t>(rt);
    }
}

void on_unmake(const UndoInfo& undo, std::uint64_t) {
    if (g_top == 0) {
        // Nothing to return to (the stack was restarted): rebuild when needed.
        mark_stale(g_stack[0], undo.old_hash_key);
        return;
    }
    --g_top;
    Level& P = g_stack[g_top];
    if (P.hash != undo.old_hash_key) mark_stale(P, undo.old_hash_key);
}

void note_hash(std::uint64_t hash) {
    // Null moves leave every piece in place and only change the tagged key.
    g_stack[g_top].hash = hash;
}

long long evaluate_raw(const Board& board) {
    const Level& L = current(board);
    return output_from_acc(L.acc[0], L.acc[1], board.side_to_move);
}

int evaluate(const Board& board) {
#if SGR_EVAL_CACHE
    EvalEntry& e = g_eval_cache[board.hash_key & (EVAL_CACHE_SIZE - 1)];
    if (e.key == board.hash_key) return e.score;
#endif
    const Level& L = current(board);
    int score = to_cp(output_from_acc(L.acc[0], L.acc[1], board.side_to_move));
#if SGR_EVAL_CACHE
    e.key = board.hash_key;
    e.score = score;
#endif
    return score;
}
#else
void refresh(const Board& board) {
    // Set bucket offsets before adding features.
    if (g_net.buckets > 1) {
        int wk = __builtin_ctzll(board.bitboards[WK]);
        int bk = __builtin_ctzll(board.bitboards[BK]);
        g_bucket_off[0] = g_net.bucket_map[wk] * INPUT;
        g_bucket_off[1] = g_net.bucket_map[bk ^ 56] * INPUT;
    } else {
        g_bucket_off[0] = g_bucket_off[1] = 0;
    }
#if SGR_SIMD
    // Accumulator and stored bias types match in SIMD builds.
    std::memcpy(g_acc[0], g_net.ft_bias.data(), HL * sizeof(AccT));
    std::memcpy(g_acc[1], g_net.ft_bias.data(), HL * sizeof(AccT));
#else
    for (int k = 0; k < HL; ++k) {
        g_acc[0][k] = g_net.ft_bias[k];
        g_acc[1][k] = g_net.ft_bias[k];
    }
#endif
    for (int piece = 0; piece < 12; ++piece) {
        std::uint64_t bb = board.bitboards[piece];
        while (bb) {
            int sq = __builtin_ctzll(bb);
            bb &= bb - 1;
            edit_feature(piece, sq, +1);
        }
    }
    g_acc_valid = true;
    g_acc_hash = board.hash_key;
}

void reset(const Board& board) {
    refresh(board);
}

void on_make(const UndoInfo& undo, std::uint64_t new_hash) {
    // Refresh later if the key is stale or the king changes buckets.
    if (!g_acc_valid || g_acc_hash != undo.old_hash_key) { g_acc_valid = false; return; }
    if (crosses_bucket(undo)) { g_acc_valid = false; return; }
    apply_move(undo, +1);
    g_acc_hash = new_hash;
}

void on_unmake(const UndoInfo& undo, std::uint64_t post_hash) {
    if (!g_acc_valid || g_acc_hash != post_hash) { g_acc_valid = false; return; }
    if (crosses_bucket(undo)) { g_acc_valid = false; return; }
    apply_move(undo, -1);
    g_acc_hash = undo.old_hash_key;
}

void note_hash(std::uint64_t hash) {
    // Null moves only change the tagged key.
    if (g_acc_valid) g_acc_hash = hash;
}

long long evaluate_raw(const Board& board) {
    if (!g_acc_valid || g_acc_hash != board.hash_key) refresh(board);
    return output_from_acc(g_acc[0], g_acc[1], board.side_to_move);
}

int evaluate(const Board& board) {
#if SGR_EVAL_CACHE
    EvalEntry& e = g_eval_cache[board.hash_key & (EVAL_CACHE_SIZE - 1)];
    if (e.key == board.hash_key) return e.score;
#endif
    if (!g_acc_valid || g_acc_hash != board.hash_key) refresh(board);
    int score = to_cp(output_from_acc(g_acc[0], g_acc[1], board.side_to_move));
#if SGR_EVAL_CACHE
    e.key = board.hash_key;
    e.score = score;
#endif
    return score;
}
#endif

bool load(const std::string& path) {
    // Old-weight accumulators and scores are stale.
#if SGR_EVAL_CACHE
    clear_eval_cache();
#endif
#if SGR_NNUE_STACK
    g_top = 0;
    mark_stale(g_stack[0], 0);
#else
    g_acc_valid = false;
#endif

    std::ifstream in(path, std::ios::binary);
    if (!in) {
        return false;
    }

    char magic[4];
    in.read(magic, 4);
    if (std::memcmp(magic, "RUKN", 4) != 0) {
        std::cerr << "nnue: bad magic in " << path << "\n";
        return false;
    }

    std::uint32_t header[6];   // Version, input, hl, qa, qb and scale.
    in.read(reinterpret_cast<char*>(header), sizeof(header));
    if (header[2] != HL || header[3] != QA
        || header[4] != QB || header[5] != SCALE) {
        std::cerr << "nnue: architecture mismatch in " << path
                  << " (net wants input=" << header[1] << " hl=" << header[2]
                  << " qa=" << header[3] << " qb=" << header[4]
                  << " scale=" << header[5] << "; this build has hl=" << HL
                  << " qa=" << QA << " qb=" << QB << " scale=" << SCALE << ")\n";
        if (header[3] != QA) {
            // QA also separates the two activations: crelu nets are 255,
            // screlu nets 181. Loading one in the other build plays badly with
            // nothing in the logs to explain it, so say what to rebuild with.
            std::cerr << "nnue: rebuild with -DSGR_QA=" << header[3]
                      << (header[3] == 255 ? " -DSGR_SCRELU=0" : " -DSGR_SCRELU=1")
                      << " to use this network\n";
        }
        return false;
    }

    // Version 1 uses 768 inputs. Version 2 adds king buckets and their map.
    if (header[0] == 1) {
        if (header[1] != INPUT) {
            std::cerr << "nnue: v1 input " << header[1] << " != " << INPUT << "\n";
            return false;
        }
        g_net.buckets = 1;
        g_net.bucket_map.fill(0);
    } else if (header[0] == 2) {
        if (header[1] % INPUT != 0 || header[1] == 0) {
            std::cerr << "nnue: v2 input " << header[1]
                      << " is not a multiple of " << INPUT << "\n";
            return false;
        }
        g_net.buckets = static_cast<int>(header[1] / INPUT);
        in.read(reinterpret_cast<char*>(g_net.bucket_map.data()), 64);
        for (int sq = 0; sq < 64; ++sq) {
            if (g_net.bucket_map[sq] >= g_net.buckets) {
                std::cerr << "nnue: bucket map entry " << int(g_net.bucket_map[sq])
                          << " out of range for " << g_net.buckets << " buckets\n";
                return false;
            }
        }
    } else {
        std::cerr << "nnue: unknown net version " << header[0] << "\n";
        return false;
    }

    g_net.ft_weight.resize(static_cast<std::size_t>(header[1]) * HL);
    in.read(reinterpret_cast<char*>(g_net.ft_weight.data()),
            g_net.ft_weight.size() * sizeof(std::int16_t));
    in.read(reinterpret_cast<char*>(g_net.ft_bias.data()),
            g_net.ft_bias.size() * sizeof(std::int16_t));
    in.read(reinterpret_cast<char*>(g_net.out_weight.data()),
            g_net.out_weight.size() * sizeof(std::int16_t));
    in.read(reinterpret_cast<char*>(&g_net.out_bias), sizeof(std::int32_t));

    if (!in) {
        std::cerr << "nnue: truncated network file " << path << "\n";
        g_active = false;
        return false;
    }

#if SGR_SIMD
    // The SIMD output sum accumulates into int32 lanes, so bound it from the
    // weights actually loaded rather than trusting the width alone. madd pairs
    // elements, so array index i lands in lane (i % kStep) / 2; summing |w| per
    // lane and scaling by the largest possible activation gives the exact
    // worst case. Costs one pass at load.
#if defined(__AVX512BW__)
    constexpr int kStep = 32;
#else
    constexpr int kStep = 16;
#endif
    std::int64_t lane[kStep / 2] = {};
    std::int64_t max_abs_w = 0;

    for (std::size_t i = 0; i < g_net.out_weight.size(); ++i) {
        std::int16_t w = g_net.out_weight[i];
        std::int64_t aw = (w < 0) ? -static_cast<std::int64_t>(w) : w;
        lane[(i % kStep) / 2] += aw;
        if (aw > max_abs_w) max_abs_w = aw;
    }

    std::int64_t worst = 0;
    for (std::int64_t v : lane) if (v > worst) worst = v;
    // Squaring costs another factor of QA per term.
    worst *= SGR_SCRELU ? static_cast<std::int64_t>(QA) * QA : QA;

    if (worst > 2147483647LL) {
        std::cerr << "nnue: " << path << " can overflow the int32 output sum ("
                  << worst << " > 2147483647). Rebuild with -DSGR_SIMD=0 for the"
                  << " scalar path, or train a narrower net.\n";
        g_active = false;
        return false;
    }

#if SGR_SCRELU
    // screlu multiplies the activation by its weight in int16 before squaring.
    // QA=255 leaves only ~2% headroom here, so check it rather than assume it.
    if (static_cast<std::int64_t>(QA) * max_abs_w > 32767) {
        std::cerr << "nnue: " << path << " overflows the int16 a*w step of screlu"
                  << " (QA * " << max_abs_w << " > 32767). This net needs a"
                  << " smaller QB or a crelu build.\n";
        g_active = false;
        return false;
    }
#endif
#endif

    g_active = true;
    return true;
}

bool active() {
    return g_active;
}

const char* simd_kind() {
    return kSimdKind;
}

int buckets() {
    return g_net.buckets;
}

}  // namespace nnue
