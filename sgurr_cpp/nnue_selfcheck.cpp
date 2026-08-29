// Check incremental accumulators against a full refresh.
// Build without main.cpp
//
//   clang++ -std=c++20 -O3 -march=native -DNDEBUG -static \
//       nnue_selfcheck.cpp board.cpp evaluation.cpp search.cpp nnue.cpp -o nnue_selfcheck.exe
//   ./nnue_selfcheck.exe ../nets/gen1.nnue
#include "board.hpp"
#include "nnue.hpp"

#include <cstdio>
#include <random>
#include <string>
#include <vector>

static long long g_checks = 0, g_fails = 0;
// Deterministic checksum used to compare scalar and SIMD builds.
static long long g_evalsum = 0;

// Compare incremental and refreshed scores after every make and unmake.
static void check_all_moves(const std::string& fen) {
    Board board(fen);
    nnue::refresh(board);
    MoveList moves = board.generate_legal_moves();
    for (int i = 0; i < moves.size(); ++i) {
        nnue::refresh(board);                       // Clean base.
        UndoInfo u = board.make_move(moves[i]);
        long long inc = nnue::evaluate_raw(board);  // Incremental score.
        nnue::refresh(board);
        long long ref = nnue::evaluate_raw(board);  // Refreshed score.
        g_evalsum += ref;
        ++g_checks;
        if (inc != ref) { ++g_fails; if (g_fails <= 10)
            printf("  MAKE mismatch fen=[%s] move=%d inc=%lld ref=%lld\n",
                   fen.c_str(), i, inc, ref); }
        board.unmake_move(u);
        long long inc2 = nnue::evaluate_raw(board);
        nnue::refresh(board);
        long long ref2 = nnue::evaluate_raw(board);
        ++g_checks;
        if (inc2 != ref2) { ++g_fails; if (g_fails <= 10)
            printf("  UNMAKE mismatch fen=[%s] move=%d inc=%lld ref=%lld\n",
                   fen.c_str(), i, inc2, ref2); }
    }
}

// Check a fully incremental random make and unmake sequence.
static void check_chain(std::mt19937& rng, int max_ply) {
    Board board(START_FEN);
    nnue::refresh(board);
    std::vector<UndoInfo> undos;
    for (int ply = 0; ply < max_ply; ++ply) {
        MoveList ms = board.generate_legal_moves();
        if (ms.size() == 0) break;
        undos.push_back(board.make_move(ms[rng() % ms.size()]));
    }
    long long inc_leaf = nnue::evaluate_raw(board);
    nnue::refresh(board);
    long long ref_leaf = nnue::evaluate_raw(board);
    ++g_checks; if (inc_leaf != ref_leaf) { ++g_fails;
        printf("  CHAIN(make) mismatch inc=%lld ref=%lld\n", inc_leaf, ref_leaf); }

    for (int i = (int)undos.size() - 1; i >= 0; --i) board.unmake_move(undos[i]);
    long long inc_root = nnue::evaluate_raw(board);
    nnue::refresh(board);
    long long ref_root = nnue::evaluate_raw(board);
    ++g_checks; if (inc_root != ref_root) { ++g_fails;
        printf("  CHAIN(unmake) mismatch inc=%lld ref=%lld\n", inc_root, ref_root); }
}

int main(int argc, char** argv) {
    const char* net = argc > 1 ? argv[1] : "../nets/gen1.nnue";
    if (!nnue::load(net)) { printf("failed to load net %s\n", net); return 1; }
    printf("loaded %s active=%d simd=%s buckets=%d\n", net, (int)nnue::active(),
           nnue::simd_kind(), nnue::buckets());

    // Print one raw FEN score for comparison with nnue_tools.py fwd.
    if (argc > 3 && std::string(argv[2]) == "fwd") {
        Board board(argv[3]);
        nnue::refresh(board);
        printf("%lld\n", nnue::evaluate_raw(board));
        return 0;
    }

    // Cover special moves and king-bucket boundaries.
    const std::vector<std::string> fens = {
        START_FEN,
        "r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R3K2R w KQkq - 0 1",        // Castling for White.
        "r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R3K2R b KQkq - 0 1",        // Castling for Black.
        "rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3",  // White en passant.
        "rnbqkbnr/pppp1ppp/8/8/3Pp3/2N5/PPP1PPPP/R1BQKBNR b KQkq d3 0 3", // Black en passant.
        "8/P6k/8/8/8/8/6Kp/8 w - - 0 1",                            // White promotion.
        "8/P6k/8/8/8/8/6Kp/8 b - - 0 1",                            // Black promotion.
        "r1bqkbnr/pPpp1ppp/2n5/8/8/8/P1PPpPPP/RNBQKBNR w KQkq - 0 1", // Capture promotion.
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", // Kiwipete.
        "4k3/8/8/8/8/8/8/3K4 w - - 0 1",     // Back-rank bucket boundary.
        "4k3/8/8/8/8/8/4K3/8 w - - 0 1",     // Rank-band boundary.
        "8/8/8/4k3/4K3/8/8/8 w - - 0 1",     // Middle rank-band boundary.
        "8/8/2k5/8/8/5K2/8/8 b - - 0 1",     // Asymmetric buckets.
    };
    for (const auto& f : fens) check_all_moves(f);

    std::mt19937 rng(0xC0FFEE);
    for (int g = 0; g < 2000; ++g) check_chain(rng, 40 + (int)(rng() % 60));

    printf("checks=%lld fails=%lld evalsum=%lld -> %s\n", g_checks, g_fails,
           g_evalsum, g_fails == 0 ? "PASS" : "FAIL");
    return g_fails == 0 ? 0 : 1;
}
