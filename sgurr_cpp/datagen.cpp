// Self-play data generator for NNUE training.
//
// Plays self-play games and appends 32-byte records to a fresh auto-numbered
// shard (data_NNNN_TAG.bin) in the output directory. Runs are resumable:
// Ctrl+C stops on a game boundary, and the next run continues towards the
// target by summing the shards already on disk. TAG is a random per-run token
// so parallel processes never collide on a filename, and the RNG is seeded
// from std::random_device so separate runs explore different games.
//
// Record layout (32 bytes, little-endian; decoded in nnue_tools.py):
//   u64    occupancy       (set bit = occupied square, LSB = a1)
//   u8[16] piece nibbles   (piece 0..11 per occupied square, ascending; low
//                           nibble of each byte first)
//   u8     side_to_move    (0 = white, 1 = black)
//   i16    score           (centipawns, side-to-move relative)
//   u8     result          (0 = stm lost, 1 = draw, 2 = stm won)
//   u8[4]  padding
//
// Usage:
//   datagen <out_dir> <target_positions> <depth|nodes:N> [book.epd|-] [net.nnue|-]
//
//   out_dir           directory for shards (created if absent)
//   target_positions  stop once the directory holds >= this many positions
//                     (0 = run until Ctrl+C)
//   depth | nodes:N   per-move search limit (nodes:N is hardware independent)
//   book.epd          optional opening book ('-' or omit = start position only)
//   net.nnue          optional network for labelling ('-' or omit = HCE)
//
// A hard kill is also safe: the loaders floor to whole 32-byte records, so a
// torn tail is ignored.

#include "board.hpp"
#include "search.hpp"
#include "nnue.hpp"

#include <atomic>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <random>
#include <string>
#include <vector>

namespace fs = std::filesystem;

namespace {

constexpr int SCORE_CAP = 2000;        // skip positions outside +/- this
constexpr int ADJ_SCORE = 2000;        // adjudicate a win above this (white POV)
constexpr int ADJ_PLIES = 6;           // ... sustained for this many plies
constexpr int MAX_PLIES = 400;
constexpr int OPENING_SKIP = 8;        // don't record the first few plies
constexpr int OPENING_BALANCE_CAP = 200;  // reject openings a probe rates beyond +/- this (cp)
constexpr int OPENING_PROBE_NODES = 5000; // cheap node budget for that opening probe

// Set by the Ctrl+C handler; polled at safe points so we stop on a clean game
// boundary rather than mid-write.
std::atomic<bool> g_stop{false};
void on_sigint(int) { g_stop.store(true); }

struct Sample {
    std::uint64_t occ;
    std::uint8_t nibbles[16];
    std::uint8_t stm;
    std::int16_t score;
};

void pack(const Board& b, Sample& s) {
    std::uint64_t occ = 0;
    for (int p = 0; p < 12; ++p) occ |= b.bitboards[p];
    s.occ = occ;
    std::memset(s.nibbles, 0, 16);
    int i = 0;
    std::uint64_t bb = occ;
    while (bb) {
        int sq = __builtin_ctzll(bb);
        bb &= bb - 1;
        int piece = *b.piece_at(sq);          // 0..11
        if (i & 1) s.nibbles[i >> 1] |= (piece << 4);
        else       s.nibbles[i >> 1] |= piece;
        ++i;
    }
    s.stm = static_cast<std::uint8_t>(b.side_to_move);
}

bool is_noisy(Board& b, const Move& m) {
    return m.is_promotion() || m.is_en_passant() || b.piece_at(m.to()).has_value();
}

std::vector<std::string> load_book(const std::string& path) {
    std::vector<std::string> out;
    std::ifstream in(path);
    std::string line;
    while (std::getline(in, line)) {
        if (!line.empty() && line[0] != '#') out.push_back(line);
    }
    return out;
}

bool is_shard(const fs::path& p) {
    return p.extension() == ".bin"
        && p.filename().string().rfind("data_", 0) == 0;
}

// Fresh shard path data_NNNN_TAG.bin: NNNN is one past the highest index on
// disk, TAG keeps parallel processes from picking the same filename.
fs::path next_shard(const fs::path& dir, std::uint32_t tag) {
    int max_idx = -1;
    for (const auto& e : fs::directory_iterator(dir)) {
        if (!is_shard(e.path())) continue;
        std::string stem = e.path().stem().string();     // "data_NNNN[_TAG]"
        try {
            int v = std::stoi(stem.substr(5));           // stoi stops at '_'
            if (v > max_idx) max_idx = v;
        } catch (...) { /* non-numeric suffix: ignore */ }
    }
    char buf[48];
    std::snprintf(buf, sizeof(buf), "data_%04d_%08x.bin", max_idx + 1, tag);
    return dir / buf;
}

// Total positions already on disk = sum of shard bytes / 32.
long long total_positions(const fs::path& dir) {
    long long bytes = 0;
    for (const auto& e : fs::directory_iterator(dir))
        if (is_shard(e.path())) bytes += static_cast<long long>(fs::file_size(e.path()));
    return bytes / 32;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 4) {
        std::cerr << "usage: datagen <out_dir> <target_positions> <depth|nodes:N>"
                     " [book.epd|-] [net.nnue|-]\n";
        return 1;
    }
    fs::path out_dir = argv[1];
    long long target = std::stoll(argv[2]);

    // argv[3]: a plain integer is a fixed depth; "nodes:N" is a node budget
    // with depth left uncapped.
    std::string limit_arg = argv[3];
    int depth = 0;
    long long node_budget = 0;
    bool use_nodes = false;
    if (limit_arg.rfind("nodes:", 0) == 0) {
        use_nodes = true;
        node_budget = std::stoll(limit_arg.substr(6));
        if (node_budget < 1) { std::cerr << "node budget must be >= 1\n"; return 1; }
    } else {
        depth = std::stoi(limit_arg);
    }

    std::string book_path = (argc > 4 && std::string(argv[4]) != "-") ? argv[4] : "";
    std::string net_path  = (argc > 5 && std::string(argv[5]) != "-") ? argv[5] : "";

    fs::create_directories(out_dir);

    if (!net_path.empty()) {
        if (!nnue::load(net_path)) {
            std::cerr << "failed to load net " << net_path << "\n";
            return 1;
        }
        std::cerr << "labelling with NNUE: " << net_path << "\n";
    } else {
        std::cerr << "labelling with hand-crafted eval\n";
    }

    std::vector<std::string> book;
    if (!book_path.empty()) book = load_book(book_path);

    long long start_total = total_positions(out_dir);
    if (target > 0 && start_total >= target) {
        std::cerr << "target already reached: " << start_total << " >= " << target
                  << " positions in " << out_dir.string() << "\n";
        return 0;
    }

    std::signal(SIGINT, on_sigint);
    std::random_device rd;
    std::mt19937 rng(rd());

    fs::path shard = next_shard(out_dir, static_cast<std::uint32_t>(rng()));
    std::ofstream out(shard, std::ios::binary);
    if (!out) { std::cerr << "cannot open shard " << shard.string() << "\n"; return 1; }

    // The search prints UCI "info" lines to stdout; mute them for datagen.
    std::cout.setstate(std::ios::failbit);

    std::cerr << "shard=" << shard.filename().string()
              << "  labelling by " << (use_nodes ? ("nodes=" + std::to_string(node_budget))
                                                 : ("depth=" + std::to_string(depth)))
              << "  existing=" << start_total
              << "  target=" << (target ? std::to_string(target) : std::string("(until Ctrl+C)"))
              << "\n";

    Engine engine;
    long long written = 0;          // positions written this run
    long long games = 0;
    long long skipped_openings = 0; // openings rejected by the balance filter

    while (!g_stop.load()) {
        // Check the on-disk total so parallel processes collectively stop at
        // the shared target rather than each writing the full amount.
        if (target > 0 && total_positions(out_dir) >= target) break;

        std::string start = book.empty()
            ? std::string(START_FEN)
            : book[rng() % book.size()];
        Board board(start);

        // Random plies for opening diversity. The book has only ~150 starts, so
        // a wide random prefix is what actually spreads the data across distinct
        // middlegames. We can randomise hard because the balance filter below
        // discards any opening that came out lopsided.
        int rand_plies = 4 + (rng() % 6);   // 4..9
        bool dead = false;
        for (int i = 0; i < rand_plies; ++i) {
            MoveList ms = board.generate_legal_moves();
            if (ms.size() == 0) { dead = true; break; }   // random plies mated/stalemated
            board.make_move(ms[rng() % ms.size()]);
        }
        if (dead) continue;

        // Opening balance filter: cheaply probe the post-opening position and
        // start a game only if it is a genuine contest. This keeps every
        // recorded game competitive (meaningful WDL, hard-fought middlegames)
        // despite the heavy opening randomisation -- we reject imbalanced
        // *starts* only; in-game play still yields plenty of imbalanced
        // positions across the eval spectrum.
        {
            SearchResult probe = engine.search_best_move(
                board, MAX_PLY - 1, std::nullopt, OPENING_PROBE_NODES);
            if (!probe.best_move.has_value()
                    || std::abs(probe.score) > OPENING_BALANCE_CAP) {
                ++skipped_openings;
                continue;
            }
        }

        std::vector<std::pair<Sample, int>> recorded;   // sample + stm
        int result_white = -1;   // 0 black win, 1 draw, 2 white win
        int adj_count = 0, adj_sign = 0;
        bool aborted = false;

        for (int ply = 0; ply < MAX_PLIES; ++ply) {
            if (g_stop.load()) { aborted = true; break; }   // discard partial game

            MoveList legal = board.generate_legal_moves();
            if (legal.size() == 0) {
                bool checked = board.in_check(board.side_to_move);
                result_white = checked ? (board.side_to_move == WHITE ? 0 : 2) : 1;
                break;
            }
            if (board.halfmove_clock >= 100 || board.is_repetition()) {
                result_white = 1; break;
            }

            SearchResult r = use_nodes
                ? engine.search_best_move(board, MAX_PLY - 1, std::nullopt, node_budget)
                : engine.search_best_move(board, depth);
            int score = r.score;                       // stm-relative
            Move best = *r.best_move;
            int white_score = (board.side_to_move == WHITE) ? score : -score;

            // win adjudication
            if (white_score >= ADJ_SCORE)      { adj_count = (adj_sign == 1 ? adj_count : 0) + 1; adj_sign = 1; }
            else if (white_score <= -ADJ_SCORE){ adj_count = (adj_sign == -1 ? adj_count : 0) + 1; adj_sign = -1; }
            else                               { adj_count = 0; adj_sign = 0; }
            if (adj_count >= ADJ_PLIES) { result_white = adj_sign == 1 ? 2 : 0; break; }

            // record quiet, non-extreme positions past the opening
            if (ply >= OPENING_SKIP && !board.in_check(board.side_to_move)
                && !is_noisy(board, best) && std::abs(score) < SCORE_CAP) {
                Sample s;
                pack(board, s);
                s.score = static_cast<std::int16_t>(score);
                recorded.emplace_back(s, board.side_to_move);
            }

            // play best move, with occasional random move for diversity
            Move play = best;
            if ((rng() % 100) < 5) play = legal[rng() % legal.size()];
            board.make_move(play);
        }
        if (aborted) break;                       // don't write an interrupted game
        if (result_white < 0) result_white = 1;   // ply cap => draw

        // flush samples with stm-relative WDL
        for (auto& [s, stm] : recorded) {
            int stm_result;   // 0 loss, 1 draw, 2 win for stm
            if (result_white == 1) stm_result = 1;
            else {
                bool white_won = (result_white == 2);
                bool stm_is_white = (stm == WHITE);
                stm_result = (white_won == stm_is_white) ? 2 : 0;
            }
            std::uint8_t res = static_cast<std::uint8_t>(stm_result);
            std::uint8_t pad[4] = {0, 0, 0, 0};
            out.write(reinterpret_cast<char*>(&s.occ), 8);
            out.write(reinterpret_cast<char*>(s.nibbles), 16);
            out.write(reinterpret_cast<char*>(&s.stm), 1);
            out.write(reinterpret_cast<char*>(&s.score), 2);
            out.write(reinterpret_cast<char*>(&res), 1);
            out.write(reinterpret_cast<char*>(pad), 4);
            ++written;
        }
        out.flush();                              // each game is durable on disk
        ++games;
        if (games % 50 == 0)
            std::cerr << "games=" << games << "  run_positions=" << written
                      << "  total=" << total_positions(out_dir)
                      << (target ? ("/" + std::to_string(target)) : "")
                      << "  (openings rejected=" << skipped_openings << ")\n";
    }

    out.flush();
    out.close();
    if (written == 0) {
        std::error_code ec;
        fs::remove(shard, ec);                     // don't leave an empty shard
    }

    std::cerr << "\nstopped" << (g_stop.load() ? " (Ctrl+C)" : "")
              << ": this run wrote " << written << " positions in " << games
              << " games (rejected " << skipped_openings << " lopsided openings)";
    if (written > 0) std::cerr << " -> " << shard.filename().string();
    std::cerr << "\ntotal in " << out_dir.string() << ": " << total_positions(out_dir)
              << (target ? ("/" + std::to_string(target)) : "") << " positions\n";
    return 0;
}
