#include "nnue.hpp"
#include "board.hpp"

#include <array>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <vector>

// -DSGR_SIMD switches the accumulator to int16 and the output layer to an
// AVX2 clamp+madd. The result is bit-identical to the scalar int32 path (all
// integer arithmetic, no reordering that changes the total), so it carries no
// Elo risk of its own -- only speed. The int16 accumulator is provably safe:
// train.py clips feature weights to +/-127, so the worst-case raw accumulator
// (bias + 32 pieces) stays inside +/-~4100, an 8x+ margin under int16. See the
// range check in the roadmap notes.
#if SGR_SIMD
#if !defined(__AVX2__)
#error "SGR_SIMD needs AVX2 (build with -march=native on any modern x86, or set -DSGR_SIMD=0 for the scalar path)"
#endif
#include <immintrin.h>
static_assert(nnue::HL % 16 == 0, "SGR_SIMD requires HL to be a multiple of 16");
// The output int32 lane sums stay exact (== the scalar int64 total) only while
// HL <= 512: per lane <= (HL/8) * 2*255*32767 must fit int32. HL=1024 would
// need periodic widening to int64 -- guard it rather than fail silently.
static_assert(nnue::HL <= 512, "SGR_SIMD output sum needs int64 widening for HL>512");
#endif

namespace nnue {

namespace {

struct Network {
    std::vector<std::int16_t> ft_weight;   // buckets * INPUT * HL, feature-major
    std::array<std::int16_t, HL> ft_bias{};
    std::array<std::int16_t, 2 * HL> out_weight{};
    std::int32_t out_bias = 0;
    // King buckets (version-2 nets). bucket_map maps the perspective's OWN
    // king square (relative frame; black mirrors via sq^56) to a bucket, and
    // that perspective's features shift by bucket*INPUT. The map is READ FROM
    // THE NET FILE -- the trainer embeds it -- so engine and trainer can never
    // disagree on bucket assignment. v1 nets load as buckets=1, zero map.
    int buckets = 1;
    std::array<std::uint8_t, 64> bucket_map{};
};

Network g_net;
bool g_active = false;

// Per-perspective feature offset (bucket * INPUT) for the accumulators'
// current position; recomputed by refresh(). A king move that changes its own
// side's bucket invalidates that perspective wholesale -- on_make/on_unmake
// detect this and mark the accumulator stale instead of editing it, and
// evaluate() falls back to a full refresh, the same safety net every other
// mismatch already uses.
int g_bucket_off[2] = {0, 0};

// Accumulators: [0] = white perspective, [1] = black. g_acc_hash is the
// Zobrist key of the position they currently represent; evaluate() rebuilds
// them whenever it doesn't match the board.
#if SGR_SIMD
using AccT = std::int16_t;
#else
using AccT = std::int32_t;
#endif
alignas(64) AccT g_acc[2][HL];
bool g_acc_valid = false;
U64 g_acc_hash = 0;

// Feature index from a given perspective. From black's perspective the board is
// mirrored vertically (sq ^ 56) and the piece colours are swapped, so the same
// weights serve both sides.
inline int feature_index(int persp, int colour, int ptype, int sq) {
    int rel_sq = (persp == WHITE) ? sq : (sq ^ 56);
    int rel_colour = (colour == persp) ? 0 : 1;
    return rel_colour * 384 + ptype * 64 + rel_sq;
}

#if SGR_SIMD
#if defined(__AVX512BW__)
// AVX-512 path: 32 int16 lanes per instruction. On Zen 4 these are
// double-pumped through 256-bit units, so the win over AVX2 is halved
// instruction count (front-end pressure), not raw ALU width — measured, not
// assumed. Arithmetic is exact at any width, so output stays bit-identical.
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

// Both perspectives' clamp+madd, reduced to one int32. Per-lane bound: each
// madd result is <= 2*255*32767 ~ 16.7M and both sides give at most
// 2*(HL/32) <= 32 accumulations per lane, so lane sums stay far inside int32
// (the HL <= 512 static_assert above is the formal guard).
inline std::int32_t forward_sum(const AccT* us, const AccT* them) {
    const __m512i zero = _mm512_setzero_si512();
    const __m512i vqa  = _mm512_set1_epi16(static_cast<short>(QA));
    const std::int16_t* w = g_net.out_weight.data();
    __m512i sum = _mm512_setzero_si512();
    for (int k = 0; k < HL; k += 32) {
        __m512i a = _mm512_loadu_si512(us + k);
        a = _mm512_min_epi16(_mm512_max_epi16(a, zero), vqa);   // crelu
        sum = _mm512_add_epi32(sum, _mm512_madd_epi16(a, _mm512_loadu_si512(w + k)));
    }
    for (int k = 0; k < HL; k += 32) {
        __m512i a = _mm512_loadu_si512(them + k);
        a = _mm512_min_epi16(_mm512_max_epi16(a, zero), vqa);
        sum = _mm512_add_epi32(sum, _mm512_madd_epi16(a, _mm512_loadu_si512(w + HL + k)));
    }
    return _mm512_reduce_add_epi32(sum);
}
const char* const kSimdKind = "avx512";

#else
// AVX2 path: 16 int16 lanes per instruction.
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

inline std::int32_t forward_sum(const AccT* us, const AccT* them) {
    const __m256i zero = _mm256_setzero_si256();
    const __m256i vqa  = _mm256_set1_epi16(static_cast<short>(QA));
    const std::int16_t* w = g_net.out_weight.data();
    __m256i sum = _mm256_setzero_si256();
    for (int k = 0; k < HL; k += 16) {
        __m256i a = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(us + k));
        a = _mm256_min_epi16(_mm256_max_epi16(a, zero), vqa);   // crelu
        sum = _mm256_add_epi32(sum, _mm256_madd_epi16(
                  a, _mm256_loadu_si256(reinterpret_cast<const __m256i*>(w + k))));
    }
    for (int k = 0; k < HL; k += 16) {
        __m256i a = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(them + k));
        a = _mm256_min_epi16(_mm256_max_epi16(a, zero), vqa);
        sum = _mm256_add_epi32(sum, _mm256_madd_epi16(
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

// Add (sign = +1) or remove (sign = -1) one piece's contribution to both
// accumulators.
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

// Apply a move's feature changes to the accumulators: s = +1 for make,
// s = -1 for unmake. Mirrors the piece edits in Board::make_move, including
// the en-passant victim (recorded in captured_piece/square) and the castling
// rook.
void apply_move(const UndoInfo& undo, int s) {
    const Move& m = undo.move;
    edit_feature(undo.moved_piece, m.from(), -s);
    edit_feature(undo.placed_piece, m.to(), +s);
    if (undo.captured_piece >= 0)
        edit_feature(undo.captured_piece, undo.captured_square, -s);
    if (m.is_castling()) {
        int rook = -1, rf = 0, rt = 0;
        switch (m.to()) {
            case 6:  rook = WR; rf = 7;  rt = 5;  break;   // white kingside
            case 2:  rook = WR; rf = 0;  rt = 3;  break;   // white queenside
            case 62: rook = BR; rf = 63; rt = 61; break;   // black kingside
            case 58: rook = BR; rf = 56; rt = 59; break;   // black queenside
            default: break;
        }
        if (rook >= 0) { edit_feature(rook, rf, -s); edit_feature(rook, rt, +s); }
    }
}

// Does this move change the mover's own king bucket? Only that side's
// perspective re-indexes (the opponent sees the king as an ordinary piece and
// updates incrementally), but the single g_acc_valid flag covers both, so a
// crossing costs one full refresh -- rare enough (bucket-crossing king moves
// plus castling) that the simplicity wins.
inline bool crosses_bucket(const UndoInfo& undo) {
    if (g_net.buckets <= 1) return false;
    const Move& m = undo.move;
    if (undo.moved_piece == WK)
        return g_net.bucket_map[m.from()] != g_net.bucket_map[m.to()];
    if (undo.moved_piece == BK)
        return g_net.bucket_map[m.from() ^ 56] != g_net.bucket_map[m.to() ^ 56];
    return false;
}

// Clamp each accumulator lane to [0, QA], multiply by the int16 output
// weights, and total. The vector paths compute every intermediate exactly as
// the scalar path does (integer ops, no overflow within the guarded bounds),
// so the int64 total is identical across scalar/AVX2/AVX-512 -- a speed
// change, never a numeric one.
std::int64_t output_from_acc(int side_to_move) {
    const AccT* us   = g_acc[side_to_move == WHITE ? 0 : 1];
    const AccT* them = g_acc[side_to_move == WHITE ? 1 : 0];
#if SGR_SIMD
    return static_cast<std::int64_t>(forward_sum(us, them)) + g_net.out_bias;
#else
    std::int64_t sum = 0;
    for (int k = 0; k < HL; ++k)
        sum += static_cast<std::int64_t>(crelu(us[k])) * g_net.out_weight[k];
    for (int k = 0; k < HL; ++k)
        sum += static_cast<std::int64_t>(crelu(them[k])) * g_net.out_weight[HL + k];
    return sum + g_net.out_bias;
#endif
}

}  // namespace

void refresh(const Board& board) {
    // Bucket offsets from each side's own king, BEFORE any features are
    // added: every edit_feature call below indexes through these.
    if (g_net.buckets > 1) {
        int wk = __builtin_ctzll(board.bitboards[WK]);
        int bk = __builtin_ctzll(board.bitboards[BK]);
        g_bucket_off[0] = g_net.bucket_map[wk] * INPUT;
        g_bucket_off[1] = g_net.bucket_map[bk ^ 56] * INPUT;
    } else {
        g_bucket_off[0] = g_bucket_off[1] = 0;
    }
#if SGR_SIMD
    // AccT == int16_t == the stored bias type, so the init is two straight
    // copies rather than a widening loop.
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

void on_make(const UndoInfo& undo, std::uint64_t new_hash) {
    // Only update if the accumulator matches the pre-move position; otherwise
    // mark it stale and let the next evaluate() rebuild it. A king move that
    // changes its own bucket re-indexes that whole perspective, so it also
    // goes the stale->refresh route rather than an incremental edit.
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
    // Null move: no pieces change, only the tagged key follows the board.
    if (g_acc_valid) g_acc_hash = hash;
}

long long evaluate_raw(const Board& board) {
    if (!g_acc_valid || g_acc_hash != board.hash_key) refresh(board);
    return output_from_acc(board.side_to_move);
}

int evaluate(const Board& board) {
    if (!g_acc_valid || g_acc_hash != board.hash_key) refresh(board);
    std::int64_t output = output_from_acc(board.side_to_move);
    std::int64_t cp = output * SCALE / (static_cast<std::int64_t>(QA) * QB);

    // Keep the score well away from mate territory.
    if (cp > 29000) cp = 29000;
    if (cp < -29000) cp = -29000;
    return static_cast<int>(cp);
}

bool load(const std::string& path) {
    g_acc_valid = false;   // accumulators built with the old weights are stale

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

    std::uint32_t header[6];   // version, input, hl, qa, qb, scale
    in.read(reinterpret_cast<char*>(header), sizeof(header));
    if (header[2] != HL || header[3] != QA
        || header[4] != QB || header[5] != SCALE) {
        std::cerr << "nnue: architecture mismatch in " << path
                  << " (input=" << header[1] << " hl=" << header[2]
                  << " qa=" << header[3] << " qb=" << header[4]
                  << " scale=" << header[5] << ")\n";
        return false;
    }

    // v1: classic 768-input net. v2: king-bucketed, input = buckets*768 with
    // the 64-byte bucket map stored right after the header.
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
