#pragma once

#include <cstdint>
#include <string>

class Board;

// NNUE evaluation with 768 inputs per perspective and one hidden layer.
// Both perspectives share feature weights. The output uses clipped ReLU, or
// squared clipped ReLU under SGR_SCRELU, and returns a side-to-move-relative
// score.
//
// Integer quantisation
//   feature weights and biases  int16 scaled by QA
//   output weights              int16 scaled by QB
//   output bias                 int32 scaled by QA*QB
//   eval_cp = (sum + out_bias) * SCALE / (QA * QB)
//
// Under SGR_SCRELU the sum carries an extra factor of QA, because each term is
// squared, so it is divided by QA before the bias is added. The bias and the
// file format are unchanged, which is why one .nnue cannot say which
// activation it was trained for -- see the toggle below.
//
// Little-endian network format
//   char   magic[4] = "RUKN"
//   uint32 version  = 1 (classic) or 2 (king-bucketed)
//   uint32 input    = 768 (v1) or buckets*768 (v2)
//   uint32 hl       = HL
//   uint32 qa, qb, scale
//   uint8  bucket_map[64]          (v2 only, relative own-king square to bucket)
//   int16  ft_weight[input * hl]   (feature-major order)
//   int16  ft_bias[hl]
//   int16  out_weight[2 * hl]      ([0..hl) = stm side, [hl..2hl) = other side)
//   int32  out_bias
//
// Version 2 shifts each perspective's features by its own king bucket.
// Crossing a bucket boundary invalidates that accumulator.

struct UndoInfo;   // Defined in board.hpp.

namespace nnue {

constexpr int INPUT = 768;
// Hidden-layer width. SGR_HL can override it for older networks.
#ifndef SGR_HL
#define SGR_HL 384
#endif
constexpr int HL    = SGR_HL;
// QA is the accumulator/feature scale. 255 is the crelu standard, but squaring
// changes where the useful precision sits: Renegade measured +26.4 +/- 12.5
// from 255 -> 181 after switching to screlu, more than the switch itself gave
// them. 181 is ~255/sqrt(2), and 181^2 = 32761 just fits int16. The net header
// records qa and load() rejects a mismatch, so a wrong pairing fails loudly.
#ifndef SGR_QA
#define SGR_QA 181
#endif
constexpr int QA    = SGR_QA;
constexpr int QB    = 64;
constexpr int SCALE = 400;

// Enable bit-identical AVX2 int16 inference. Set SGR_SIMD=0 for scalar int32.
#ifndef SGR_SIMD
#define SGR_SIMD 1
#endif

// Square the clipped activation instead of using it directly. The network must
// be TRAINED with the matching activation: a screlu-trained net read by a crelu
// build trains well and plays badly, with nothing to show it is wrong.
#ifndef SGR_SCRELU
#define SGR_SCRELU 1
#endif

// Keep one accumulator per ply. Make and unmake only push and pop; a level's
// sums are computed when that position is evaluated, from its nearest computed
// ancestor, one fused pass per ply. Scores are bit-identical to the single
// accumulator it replaces, so the search tree does not change.
#ifndef SGR_NNUE_STACK
#define SGR_NNUE_STACK 1
#endif

// Load a network. Failure leaves the handcrafted evaluation active.
bool load(const std::string& path);

// Whether a network is loaded and NNUE evaluation should be used.
bool active();

// Return the compiled inference path name.
const char* simd_kind();

// Return the loaded network's king-bucket count.
int buckets();

// Side-relative evaluation in centipawns.
int evaluate(const Board& board);

// Pre-scaling integer output (sum + out_bias), used by nnue_selfcheck.
long long evaluate_raw(const Board& board);

// Maintain accumulators across moves. Key mismatches trigger a full refresh.
// Null moves only retag the accumulator hash.
// refresh() rebuilds the current accumulator from the board in place; reset()
// also drops every earlier ply, and is called once at the root of a search.
void refresh(const Board& board);
void reset(const Board& board);
void on_make(const UndoInfo& undo, std::uint64_t new_hash);
void on_unmake(const UndoInfo& undo, std::uint64_t post_hash);
void note_hash(std::uint64_t hash);

}  // namespace nnue
