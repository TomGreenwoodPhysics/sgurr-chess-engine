#include "board.hpp"
#include "evaluation.hpp"
#include "search.hpp"
#include "nnue.hpp"

#include <chrono>
#include <iomanip>
#include <iostream>
#include <cstdlib>
#include <optional>
#include <sstream>
#include <string>
#include <vector>

// Advertised engine identity, in ONE place.
//
// The UCI `id name` line is the only channel by which a GUI, a tournament
// runner, or a PGN header learns which engine it is talking to, so a stale
// value here silently mislabels every game record it touches. It has been
// stale before: the string read "Sgurr 7.0" for the whole of v8.0's life,
// including the 3,329-game calibration that produced the 3006 rating.
//
// Overridable at build time (-DSGR_VERSION=\"8.1\") like the other build
// switches, so a release build can stamp itself without a source edit.
#ifndef SGR_VERSION
#define SGR_VERSION "8.0"
#endif
constexpr const char* ENGINE_NAME = "Sgurr";
constexpr const char* ENGINE_AUTHOR = "Tom";

// Runtime UCI options.
//
// Until now the engine advertised NONE, which is a standards gap (a GUI cannot
// even set Hash) and the reason no search parameter in this project has ever
// been tuned -- every margin and threshold is a compile-time constant. These
// are the standard housekeeping options; the tunable search parameters follow
// in a later change.
//
// `Threads` is declared with min == max == 1 rather than omitted. The engine is
// single-threaded by design (the rating scale here is single-core, so parallel
// search would measure exactly zero), and declaring it honestly tells a GUI
// that the option exists and is pinned, rather than leaving it to guess.
int g_move_overhead_ms = static_cast<int>(MOVE_OVERHEAD_MS);

std::vector<std::string> split(const std::string& text);   // defined below

void print_uci_options(const Engine& engine) {
    std::cout << "option name Hash type spin default " << DEFAULT_HASH_MB
              << " min " << MIN_HASH_MB << " max " << MAX_HASH_MB << "\n";
    std::cout << "option name Clear Hash type button\n";
    std::cout << "option name Move Overhead type spin default "
              << MOVE_OVERHEAD_MS << " min 0 max 5000\n";
    std::cout << "option name Threads type spin default 1 min 1 max 1\n";
    (void)engine;
}

// Parse `setoption name <words...> value <words...>`. The name may contain
// spaces ("Clear Hash"), so it is everything between `name` and `value`.
void handle_setoption(const std::string& command, Engine& engine) {
    std::vector<std::string> parts = split(command);

    std::string name;
    std::string value;
    int section = 0;   // 0 = before name, 1 = in name, 2 = in value

    for (std::size_t i = 1; i < parts.size(); ++i) {
        if (parts[i] == "name" && section == 0) {
            section = 1;
        } else if (parts[i] == "value" && section == 1) {
            section = 2;
        } else if (section == 1) {
            name += (name.empty() ? "" : " ") + parts[i];
        } else if (section == 2) {
            value += (value.empty() ? "" : " ") + parts[i];
        }
    }

    auto as_int = [&](int fallback) {
        try {
            return std::stoi(value);
        } catch (...) {
            return fallback;
        }
    };

    if (name == "Hash") {
        int asked = as_int(DEFAULT_HASH_MB);
        engine.resize_hash(asked);
        // Report what was ACTUALLY allocated, not what was asked for. The entry
        // count is rounded down to a power of two so the probe can index with a
        // mask, which can cost up to a third of the request (256 MB -> 192 MB).
        // Silently honouring a different size than the user set is exactly the
        // kind of thing that later gets mistaken for a measurement.
        double actual_mb = double(engine.tt_size * sizeof(TTEntry)) / (1024.0 * 1024.0);
        std::cerr << "info string Hash " << asked << " MB requested -> "
                  << std::fixed << std::setprecision(2) << actual_mb
                  << " MB (" << engine.tt_size << " entries)\n";
    } else if (name == "Clear Hash") {
        engine.clear_for_new_game();
    } else if (name == "Move Overhead") {
        g_move_overhead_ms = std::max(0, as_int(g_move_overhead_ms));
    } else if (name == "Threads") {
        // Accepted and pinned at 1; see the note above.
    } else if (!name.empty()) {
        std::cerr << "info string unknown option '" << name << "' ignored\n";
    }
}

std::vector<std::string> split(const std::string& text) {
    std::vector<std::string> parts;
    std::istringstream stream(text);
    std::string part;

    while (stream >> part) {
        parts.push_back(part);
    }

    return parts;
}

std::optional<Move> parse_move(Board& board, const std::string& text) {
    for (const Move& move : board.generate_legal_moves()) {
        if (move_to_string(move) == text) {
            return move;
        }
    }

    return std::nullopt;
}

Board apply_uci_position(Board board, const std::string& command) {
    std::vector<std::string> parts = split(command);

    if (parts.size() < 2) {
        return board;
    }

    std::size_t move_start = parts.size();

    if (parts[1] == "startpos") {
        board = Board(START_FEN);

        if (parts.size() > 2 && parts[2] == "moves") {
            move_start = 3;
        }
    } else if (parts[1] == "fen") {
        std::size_t moves_index = parts.size();

        for (std::size_t i = 2; i < parts.size(); ++i) {
            if (parts[i] == "moves") {
                moves_index = i;
                break;
            }
        }

        std::string fen;

        for (std::size_t i = 2; i < moves_index; ++i) {
            if (!fen.empty()) {
                fen += " ";
            }

            fen += parts[i];
        }

        board = Board(fen);

        if (moves_index < parts.size()) {
            move_start = moves_index + 1;
        }
    } else {
        return board;
    }

    for (std::size_t i = move_start; i < parts.size(); ++i) {
        std::optional<Move> move = parse_move(board, parts[i]);

        if (!move.has_value()) {
            break;
        }

        board.make_move(*move);
    }

    return board;
}

std::optional<int> parse_go_depth(const std::string& command) {
    std::vector<std::string> parts = split(command);

    for (std::size_t i = 0; i + 1 < parts.size(); ++i) {
        if (parts[i] == "depth") {
            return std::stoi(parts[i + 1]);
        }
    }

    return std::nullopt;
}

std::optional<long long> parse_go_value(const std::string& command, const std::string& token) {
    std::vector<std::string> parts = split(command);

    for (std::size_t i = 0; i + 1 < parts.size(); ++i) {
        if (parts[i] == token) {
            return std::stoll(parts[i + 1]);
        }
    }

    return std::nullopt;
}

// A move's time allowance, in seconds. `hard` is the deadline at which the
// search is aborted mid-iteration; `soft`, when present, is the point past
// which no new iterative-deepening pass is started. Fixed `movetime` uses the
// whole allotment (no soft limit); a clock-based budget carries both.
struct TimeBudget {
    double hard;
    std::optional<double> soft;
};

std::optional<TimeBudget> parse_go_time_budget(const std::string& command, const Board& board) {
    if (auto movetime = parse_go_value(command, "movetime")) {
        return TimeBudget{ *movetime / 1000.0, std::nullopt };
    }

    // Clock-based allocation from wtime/btime/winc/binc/movestogo.
    bool white = board.side_to_move == WHITE;
    auto time_left = parse_go_value(command, white ? "wtime" : "btime");

    if (!time_left.has_value()) {
        return std::nullopt;   // no clock given: fixed-depth search
    }

    long long inc = parse_go_value(command, white ? "winc" : "binc").value_or(0);
    long long mtg = parse_go_value(command, "movestogo").value_or(30);

    if (mtg < 1) {
        mtg = 1;
    }

    // Hold back a margin for GUI/network latency so the move is transmitted
    // before the flag falls, then budget one slice of the remaining time plus
    // half the increment, never more than half the clock, with a safety floor.
    long long usable = std::max(1LL, *time_left - g_move_overhead_ms);
    long long hard = usable / mtg + inc / 2;
    hard = std::min(hard, usable / 2);
    hard = std::max(hard, 10LL);

    // Stop starting fresh iterations partway through the budget: the final
    // pass then completes instead of being aborted, unused, at the hard limit.
    long long soft = std::max(10LL, static_cast<long long>(hard * SOFT_TIME_FRACTION));

    return TimeBudget{ hard / 1000.0, soft / 1000.0 };
}

// Defined below, next to the position list it walks. Declared here so `bench`
// also works as a command inside a live UCI session, not just as an argv mode.
constexpr int BENCH_DEPTH = 11;
int run_bench(int depth);

void uci_loop() {
    Board board;
    Engine engine;

    std::string command;

    while (std::getline(std::cin, command)) {
        if (command == "uci") {
            std::cout << "id name " << ENGINE_NAME << " " << SGR_VERSION << "\n";
            std::cout << "id author " << ENGINE_AUTHOR << "\n";
            print_uci_options(engine);
            std::cout << "uciok\n";
        } else if (command.rfind("setoption", 0) == 0) {
            handle_setoption(command, engine);
        } else if (command == "isready") {
            std::cout << "readyok\n";
        } else if (command == "ucinewgame") {
            board = Board();
            engine.clear_for_new_game();
        } else if (command.rfind("position", 0) == 0) {
            board = apply_uci_position(board, command);
            engine.clear_for_new_position();
        } else if (command.rfind("go", 0) == 0) {
            std::optional<int> requested_depth = parse_go_depth(command);
            std::optional<TimeBudget> budget = parse_go_time_budget(command, board);
            std::optional<long long> node_limit = parse_go_value(command, "nodes");

            std::optional<double> hard_limit =
                budget.has_value() ? std::optional<double>(budget->hard) : std::nullopt;
            std::optional<double> soft_limit =
                budget.has_value() ? budget->soft : std::nullopt;

            // With a clock, movetime, or a node budget, depth is bounded by that
            // limit rather than the default cap.
            int depth = requested_depth.value_or(
                (budget.has_value() || node_limit.has_value()) ? MAX_PLY - 1 : MAX_DEPTH
            );

            SearchResult result = engine.search_best_move(
                board,
                depth,
                hard_limit,
                node_limit,
                soft_limit
            );

            if (result.best_move.has_value()) {
                std::cout << "bestmove " << move_to_string(*result.best_move) << "\n";
            } else {
                std::cout << "bestmove 0000\n";
            }
        } else if (command == "bench" || command.rfind("bench ", 0) == 0) {
            // Optional depth: "bench 13". Anything unparseable falls back to
            // the default rather than aborting a live session.
            int depth = BENCH_DEPTH;
            std::vector<std::string> parts = split(command);

            if (parts.size() > 1) {
                try {
                    depth = std::stoi(parts[1]);
                } catch (...) {
                    depth = BENCH_DEPTH;
                }
            }

            run_bench(depth);
        } else if (command == "quit") {
            break;
        }
    }
}

void test_mode() {
    Board board;
    Engine engine;

    board.print_board();

    std::cout << "\nperft tests:\n";

    for (int depth = 1; depth <= 4; ++depth) {
        std::cout << "perft(" << depth << ") = " << perft(board, depth) << "\n";
    }

    std::cout << "\nevaluation tests:\n";
    std::cout << "start eval = " << board.evaluate() << "\n";

    Move e2e4(square_index("e2"), square_index("e4"));
    UndoInfo undo = board.make_move(e2e4);
    std::cout << "after e2e4 eval, black to move = " << board.evaluate() << "\n";
    board.unmake_move(undo);
    std::cout << "after unmake eval = " << board.evaluate() << "\n";

    std::cout << "\nnull move test:\n";

    U64 old_hash = board.hash_key;
    int old_eval = board.evaluate();

    NullMoveUndo null_undo = board.make_null_move();

    std::cout << "after null move side = "
              << (board.side_to_move == WHITE ? "white" : "black")
              << "\n";

    board.unmake_null_move(null_undo);

    std::cout << "null restored hash = "
              << (board.hash_key == old_hash ? "yes" : "no")
              << "\n";

    std::cout << "null restored eval = "
              << (board.evaluate() == old_eval ? "yes" : "no")
              << "\n";

    std::cout << "\nsearch test:\n";

    SearchResult result = engine.search_best_move(
        board,
        5,
        2.0
    );

    if (result.best_move.has_value()) {
        std::cout << "best move: " << move_to_string(*result.best_move) << "\n";
    } else {
        std::cout << "best move: none\n";
    }

    std::cout << "score: " << result.score << "\n";
    std::cout << "depth: " << result.depth << "\n";
    std::cout << "nodes: " << result.nodes << "\n";
    std::cout << "tt hits: " << result.tt_hits << "\n";
    std::cout << "time: " << result.time_taken << "s\n";
}

int run_see_tests() {
    // Each case: FEN, the capturing move in UCI form, and the hand-verified
    // SEE value (centipawns, from the side-to-move's perspective). Values use
    // the canonical scale P=100 N=320 B=330 R=500 Q=900.
    struct SeeCase {
        const char* fen;
        const char* uci;
        int expected;
        const char* note;
    };

    const std::vector<SeeCase> cases = {
        {"4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1", "e4d5", 100,
         "pawn takes undefended pawn"},
        {"4k3/2n5/8/3p4/4P3/8/8/4K3 w - - 0 1", "e4d5", 0,
         "pawn takes pawn defended by knight (even)"},
        {"4k3/8/4p3/3p4/8/8/8/3RK3 w - - 0 1", "d1d5", -400,
         "rook takes pawn defended by pawn (loses the exchange)"},
        {"3rk3/8/8/3p4/8/8/3R4/3RK3 w - - 0 1", "d2d5", 100,
         "attacker x-ray: doubled rooks beat a single rook defender"},
        {"4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1", "e5d6", 100,
         "en passant, undefended"},
        {"4k3/2p5/8/3pP3/8/8/8/4K3 w - d6 0 1", "e5d6", 0,
         "en passant, recaptured by a pawn (even)"},
        {"4k3/8/8/3p4/4K3/8/8/8 w - - 0 1", "e4d5", 100,
         "king takes undefended pawn"},
        {"4k3/8/2p1p3/3p4/2K1P3/8/8/8 w - - 0 1", "e4d5", 0,
         "king-legality guard: king cannot recapture into a defended square"},
        {"4k3/8/2p5/3p4/4B3/5Q2/8/4K3 w - - 0 1", "e4d5", -130,
         "diagonal x-ray: queen behind bishop, recapture proceeds"},
    };

    int passed = 0;

    for (const SeeCase& c : cases) {
        Board board(c.fen);

        std::optional<Move> move = std::nullopt;

        for (const Move& candidate : board.generate_legal_moves()) {
            if (move_to_string(candidate) == c.uci) {
                move = candidate;
                break;
            }
        }

        if (!move.has_value()) {
            std::cout << "FAIL  " << c.uci << " not a legal move in [" << c.fen
                      << "]  (" << c.note << ")\n";
            continue;
        }

        int got = board.see(*move);
        bool ok = got == c.expected;
        passed += ok ? 1 : 0;

        std::cout << (ok ? "PASS  " : "FAIL  ")
                  << c.uci
                  << "  expected " << c.expected
                  << "  got " << got
                  << "   " << c.note << "\n";
    }

    std::cout << "\nSEE: " << passed << "/" << cases.size() << " passed\n";

    return passed == static_cast<int>(cases.size()) ? 0 : 1;
}

// ---------------------------------------------------------------------------
// bench: a fixed-depth search over a fixed set of positions.
//
// The search is fully deterministic -- no randomness, no clock (a fixed-depth
// search passes no time limit, so time_is_up() never fires), and every
// heuristic is cleared before each position. So the per-position node counts
// and their total are a FINGERPRINT of the engine's search behaviour.
//
// That is what makes this the project's cheapest verification tool. A change
// meant to be speed-only -- build flags, data layout, SIMD, a refactor --
// must leave the fingerprint byte-identical. If it moves, the change altered
// WHAT is searched rather than only how fast, and the speedup is not free.
// METHODOLOGY.md 7 already requires node-identical A/B binaries before they
// are trusted; this makes that check one command instead of a procedure.
//
// The fingerprint goes to stdout and everything non-deterministic (wall time,
// NPS, net path, SIMD path) goes to stderr, so
//
//     diff <(old.exe bench 2>/dev/null) <(new.exe bench 2>/dev/null)
//
// compares exactly the deterministic part and nothing else.
//
// Heuristics are cleared before EVERY position rather than once at the start,
// so each entry is independent: reordering or adding positions cannot shift
// another position's count, and a divergence names the position that caused
// it instead of every position after it.
//
// The node counts also depend on the loaded network -- a different net is a
// different evaluation and therefore a different tree. That is a feature: it
// means an accidental net mismatch shows up as a fingerprint difference
// rather than passing silently, which is the failure that cost this project
// ~430 Elo once already.
//
// BENCH_DEPTH is declared above uci_loop, where the `bench` command needs it.

const char* const BENCH_FENS[] = {
    // openings
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3",
    "r1bqkb1r/pp1n1ppp/2p1pn2/3p4/2PP4/2N1PN2/PP3PPP/R1BQKB1R w KQkq - 0 6",
    "rnbqkb1r/pp2pppp/3p1n2/8/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 0 6",

    // middlegames
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10",
    "4rrk1/pp1n3p/3q2pQ/2p1pb2/2PP4/2P3N1/P2B2PP/4RRK1 b - - 7 19",
    "2rq1rk1/pb1nbppp/1p2pn2/8/2BP4/2N1PN2/PPQ2PPP/R1B2RK1 w - - 0 12",
    "r2q1rk1/1b1nbppp/p3pn2/1p6/3P4/1BN1PN2/PP2QPPP/R1BR2K1 w - - 0 12",
    "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",

    // capture-rich, to exercise quiescence and SEE
    "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
    "3r1rk1/p3qppp/2bb4/2p5/3p4/1P2P3/PBQN1PPP/2R2RK1 w - - 0 1",

    // endgames
    "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
    "8/8/1P6/5pr1/8/4R3/7k/2K5 w - - 0 1",
    "6k1/6p1/6Pp/ppp5/3pn2P/1P3K2/1PP2P2/3N4 b - - 0 1",
    "R7/P4k2/8/8/8/8/r7/6K1 w - - 0 1",
    "8/p3k3/1p6/2p5/2P5/1P4P1/P3K3/8 w - - 0 1",
    "8/8/4k3/8/1p2P3/1P6/4K3/8 w - - 0 1",
    "8/5k2/8/8/8/3K4/4P3/8 w - - 0 1",
};

int run_bench(int depth) {
    const int count = static_cast<int>(sizeof(BENCH_FENS) / sizeof(BENCH_FENS[0]));

    Engine engine;

    std::cout << "bench depth " << depth
              << " eval " << (nnue::active() ? "nnue" : "hce")
              << " positions " << count << "\n";

    long long total_nodes = 0;
    double search_seconds = 0.0;   // search time only, excluding the TT clears

    for (int i = 0; i < count; ++i) {
        Board board(BENCH_FENS[i]);

        // Independence: no TT entry, killer, history or continuation-history
        // score may carry over from the previous position.
        engine.clear_for_new_game();

        // The search writes UCI "info" lines to stdout; keep them out of the
        // fingerprint.
        std::cout.setstate(std::ios::failbit);
        SearchResult result = engine.search_best_move(board, depth);
        std::cout.clear();

        total_nodes += result.nodes;
        search_seconds += result.time_taken;

        std::cout << "pos " << std::setw(2) << (i + 1)
                  << "  nodes " << std::setw(10) << result.nodes
                  << "  bm " << std::setw(5)
                  << (result.best_move.has_value()
                          ? move_to_string(*result.best_move)
                          : std::string("none"))
                  << "  score " << result.score
                  << "\n";
    }

    std::cout << "nodes " << total_nodes << "\n";

    std::cerr << "time " << std::fixed << std::setprecision(3) << search_seconds
              << " s   nps "
              << (search_seconds > 0.0
                      ? static_cast<long long>(total_nodes / search_seconds)
                      : 0LL)
              << "\n";

    return 0;
}

int main(int argc, char* argv[]) {
    // Load an NNUE network if one is available; otherwise use the hand-crafted
    // evaluation.
    {
        // $SGR_EVALFILE overrides the compile-time default (-DSGR_DEFAULT_NET),
        // which is empty unless set at build time. An HCE build therefore never
        // picks up a stray net, whatever the working directory.
#ifndef SGR_DEFAULT_NET
#define SGR_DEFAULT_NET ""
#endif
        const char* env = std::getenv("SGR_EVALFILE");
        std::string net_path = env ? env : SGR_DEFAULT_NET;
        if (!net_path.empty() && nnue::load(net_path)) {
            std::cerr << "info string nnue: loaded " << net_path
                      << " (" << nnue::simd_kind();
            if (nnue::buckets() > 1) std::cerr << ", k=" << nnue::buckets();
            std::cerr << ")\n";
        } else {
            std::cerr << "info string nnue: no network, using hand-crafted eval\n";
        }
    }

    // Bare launch = UCI, like every standard engine, so GUIs and tournament
    // runners (fastchess/cutechess) work without arguments. The old bare-launch
    // test mode moved behind an explicit "test" argument.
    if (argc <= 1 || std::string(argv[1]) == "uci") {
        uci_loop();
    } else if (argc > 1 && std::string(argv[1]) == "test") {
        test_mode();
    } else if (argc > 1 && std::string(argv[1]) == "seetest") {
        return run_see_tests();
    } else if (argc > 1 && std::string(argv[1]) == "bench") {
        int depth = argc > 2 ? std::atoi(argv[2]) : BENCH_DEPTH;

        if (depth < 1) {
            std::cerr << "bench: depth must be >= 1\n";
            return 1;
        }

        return run_bench(depth);
    } else if (argc > 2 && std::string(argv[1]) == "fen") {
        std::string fen;

        for (int i = 2; i < argc; ++i) {
            if (!fen.empty()) {
                fen += " ";
            }

            fen += argv[i];
        }

        Board board(fen);
        Engine engine;

        board.print_board();

        SearchResult result = engine.search_best_move(
            board,
            10,
            5.0
        );

        if (result.best_move.has_value()) {
            std::cout << "best move: " << move_to_string(*result.best_move) << "\n";
        } else {
            std::cout << "best move: none\n";
        }

        std::cout << "score: " << result.score << "\n";
        std::cout << "depth: " << result.depth << "\n";
        std::cout << "nodes: " << result.nodes << "\n";
        std::cout << "time: " << result.time_taken << "s\n";
    } else {
        // Unknown argument: behave like a normal engine rather than surprising
        // a GUI that passed something unexpected.
        uci_loop();
    }

    return 0;
}