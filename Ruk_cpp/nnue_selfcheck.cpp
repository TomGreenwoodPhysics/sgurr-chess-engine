// Checks that the incremental accumulator matches a from-scratch refresh,
// bit for bit. Build without main.cpp:
//
//   clang++ -std=c++20 -O3 -march=native -DNDEBUG -static \
//       nnue_selfcheck.cpp board.cpp evaluation.cpp search.cpp nnue.cpp -o nnue_selfcheck.exe
//   ./nnue_selfcheck.exe ../nets/gen1.nnue
//
// evaluate_raw() uses the maintained accumulator when its tracked key matches
// the board (as it does right after make/unmake), so calling refresh() first
// gives the ground truth to compare against.
#include "board.hpp"
#include "nnue.hpp"

#include <cstdio>
#include <random>
#include <string>
#include <vector>

static long long g_checks = 0, g_fails = 0;

// Check every legal move in the position: make it, compare the maintained
// output to a fresh refresh, then unmake and compare again.
static void check_all_moves(const std::string& fen) {
    Board board(fen);
    nnue::refresh(board);
    MoveList moves = board.generate_legal_moves();
    for (int i = 0; i < moves.size(); ++i) {
        nnue::refresh(board);                       // clean base
        UndoInfo u = board.make_move(moves[i]);
        long long inc = nnue::evaluate_raw(board);  // incremental
        nnue::refresh(board);
        long long ref = nnue::evaluate_raw(board);  // scratch
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

// Play a random game with no interleaved refresh, so the whole make chain
// (then the whole unmake chain) is purely incremental. Compare against a fresh
// refresh at the leaf and back at the root to catch accumulated error.
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
    printf("loaded %s active=%d\n", net, (int)nnue::active());

    // Positions chosen to exercise every special move type.
    const std::vector<std::string> fens = {
        START_FEN,
        "r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R3K2R w KQkq - 0 1",        // castling both sides
        "r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R3K2R b KQkq - 0 1",        // castling, black
        "rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3",  // en passant (white)
        "rnbqkbnr/pppp1ppp/8/8/3Pp3/2N5/PPP1PPPP/R1BQKBNR b KQkq d3 0 3", // en passant (black)
        "8/P6k/8/8/8/8/6Kp/8 w - - 0 1",                            // white promotion
        "8/P6k/8/8/8/8/6Kp/8 b - - 0 1",                            // black promotion
        "r1bqkbnr/pPpp1ppp/2n5/8/8/8/P1PPpPPP/RNBQKBNR w KQkq - 0 1", // promotion with capture
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", // kiwipete
    };
    for (const auto& f : fens) check_all_moves(f);

    std::mt19937 rng(0xC0FFEE);
    for (int g = 0; g < 2000; ++g) check_chain(rng, 40 + (int)(rng() % 60));

    printf("checks=%lld fails=%lld -> %s\n", g_checks, g_fails,
           g_fails == 0 ? "PASS" : "FAIL");
    return g_fails == 0 ? 0 : 1;
}
