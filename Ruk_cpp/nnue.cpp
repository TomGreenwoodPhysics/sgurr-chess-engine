#include "nnue.hpp"
#include "board.hpp"

#include <array>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <vector>

namespace nnue {

namespace {

struct Network {
    std::vector<std::int16_t> ft_weight;   // INPUT * HL, feature-major
    std::array<std::int16_t, HL> ft_bias{};
    std::array<std::int16_t, 2 * HL> out_weight{};
    std::int32_t out_bias = 0;
};

Network g_net;
bool g_active = false;

// Accumulators: [0] = white perspective, [1] = black. g_acc_hash is the
// Zobrist key of the position they currently represent; evaluate() rebuilds
// them whenever it doesn't match the board.
std::int32_t g_acc[2][HL];
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

inline std::int32_t crelu(std::int32_t x) {
    if (x < 0) return 0;
    if (x > QA) return QA;
    return x;
}

// Add (sign = +1) or remove (sign = -1) one piece's contribution to both
// accumulators.
inline void edit_feature(int piece, int sq, int sign) {
    int colour = piece / 6;
    int ptype = piece % 6;
    int iw = feature_index(WHITE, colour, ptype, sq);
    int ib = feature_index(BLACK, colour, ptype, sq);
    const std::int16_t* ww = &g_net.ft_weight[static_cast<std::size_t>(iw) * HL];
    const std::int16_t* wb = &g_net.ft_weight[static_cast<std::size_t>(ib) * HL];
    if (sign > 0) {
        for (int k = 0; k < HL; ++k) { g_acc[0][k] += ww[k]; g_acc[1][k] += wb[k]; }
    } else {
        for (int k = 0; k < HL; ++k) { g_acc[0][k] -= ww[k]; g_acc[1][k] -= wb[k]; }
    }
}

// Apply a move's feature changes to the accumulators: s = +1 for make,
// s = -1 for unmake. Mirrors the piece edits in Board::make_move, including
// the en-passant victim (recorded in captured_piece/square) and the castling
// rook.
void apply_move(const UndoInfo& undo, int s) {
    const Move& m = undo.move;
    edit_feature(undo.moved_piece, m.from(), -s);
    edit_feature(undo.placed_piece, m.to(), +s);
    if (undo.captured_piece.has_value() && undo.captured_square.has_value())
        edit_feature(*undo.captured_piece, *undo.captured_square, -s);
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

std::int64_t output_from_acc(int side_to_move) {
    const std::int32_t* us   = g_acc[side_to_move == WHITE ? 0 : 1];
    const std::int32_t* them = g_acc[side_to_move == WHITE ? 1 : 0];
    std::int64_t sum = 0;
    for (int k = 0; k < HL; ++k)
        sum += static_cast<std::int64_t>(crelu(us[k])) * g_net.out_weight[k];
    for (int k = 0; k < HL; ++k)
        sum += static_cast<std::int64_t>(crelu(them[k])) * g_net.out_weight[HL + k];
    return sum + g_net.out_bias;
}

}  // namespace

void refresh(const Board& board) {
    for (int k = 0; k < HL; ++k) {
        g_acc[0][k] = g_net.ft_bias[k];
        g_acc[1][k] = g_net.ft_bias[k];
    }
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
    // mark it stale and let the next evaluate() rebuild it.
    if (!g_acc_valid || g_acc_hash != undo.old_hash_key) { g_acc_valid = false; return; }
    apply_move(undo, +1);
    g_acc_hash = new_hash;
}

void on_unmake(const UndoInfo& undo, std::uint64_t post_hash) {
    if (!g_acc_valid || g_acc_hash != post_hash) { g_acc_valid = false; return; }
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
    if (header[1] != INPUT || header[2] != HL || header[3] != QA
        || header[4] != QB || header[5] != SCALE) {
        std::cerr << "nnue: architecture mismatch in " << path
                  << " (input=" << header[1] << " hl=" << header[2]
                  << " qa=" << header[3] << " qb=" << header[4]
                  << " scale=" << header[5] << ")\n";
        return false;
    }

    g_net.ft_weight.resize(static_cast<std::size_t>(INPUT) * HL);
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

}  // namespace nnue
