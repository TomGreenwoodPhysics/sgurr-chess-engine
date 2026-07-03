#pragma once

#include <cstdint>
#include <string>

class Board;

// NNUE evaluation: (768 -> HL) x2 -> 1 perspective network.
//
// 768 inputs per perspective = 2 colours x 6 piece types x 64 squares. The two
// accumulators (white / black point of view) share the feature-transformer
// weights. The output layer reads [stm accumulator, other accumulator] through
// a clipped ReLU (clamp to [0, QA]) and scales the dot product to centipawns.
//
// Quantisation (integer arithmetic throughout):
//   feature weights/biases : int16, scaled by QA
//   output weights         : int16, scaled by QB
//   output bias            : int32, scaled by QA*QB
//   eval_cp = (sum + out_bias) * SCALE / (QA * QB)
// The trainer has to match this architecture, activation and scaling.
//
// Network file format (little-endian):
//   char   magic[4] = "RUKN"
//   uint32 version  = 1
//   uint32 input    = 768
//   uint32 hl       = HL
//   uint32 qa, qb, scale
//   int16  ft_weight[input * hl]   (feature-major: ft_weight[feature*hl + k])
//   int16  ft_bias[hl]
//   int16  out_weight[2 * hl]      ([0..hl) = stm side, [hl..2hl) = other side)
//   int32  out_bias

struct UndoInfo;   // defined in board.hpp

namespace nnue {

constexpr int INPUT = 768;
constexpr int HL    = 256;
constexpr int QA    = 255;
constexpr int QB    = 64;
constexpr int SCALE = 400;

// Load a network file. Returns false on failure, in which case the engine
// keeps using the hand-crafted evaluation.
bool load(const std::string& path);

// Whether a network is loaded and NNUE evaluation should be used.
bool active();

// Side-relative evaluation in centipawns (positive = good for side to move).
int evaluate(const Board& board);

// Pre-scaling integer output (sum + out_bias), used by nnue_selfcheck.
long long evaluate_raw(const Board& board);

// Incremental accumulator maintenance. refresh() rebuilds both accumulators
// from scratch; the engine calls it once at the search root, after which
// make_move / unmake_move apply per-move feature deltas (on_make / on_unmake).
// Null moves change no pieces, so they only retag the accumulators with the
// new key (note_hash). Each hook checks the stored Zobrist key before touching
// anything and evaluate() falls back to a full refresh on any mismatch, so a
// missed update can only cost speed, not a wrong score.
void refresh(const Board& board);
void on_make(const UndoInfo& undo, std::uint64_t new_hash);
void on_unmake(const UndoInfo& undo, std::uint64_t post_hash);
void note_hash(std::uint64_t hash);

}  // namespace nnue