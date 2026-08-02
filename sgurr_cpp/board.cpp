#include "board.hpp"
#include "nnue.hpp"

#include <algorithm>
#include <cassert>
#include <iostream>
#include <random>
#include <sstream>
#include <stdexcept>

const std::string PIECES = "PNBRQKpnbrqk";

// Step offsets, used once at startup to build the knight and king attack
// tables. Sliders do not appear here: they are answered by magic lookup, and
// their delta sets were only ever a way of naming the piece type.
const std::vector<int> KNIGHT_DELTAS = {17, 15, 10, 6, -17, -15, -10, -6};
const std::vector<int> KING_DELTAS = {8, -8, 1, -1, 9, 7, -9, -7};

// SEE piece values, indexed by piece type (0..5 = P,N,B,R,Q,K). Same simple
// material scale as the MVV-LVA / delta pruning values in search.cpp, not the
// tuned eval values, so SEE stays consistent with the other ordering terms.
// The king value is a sentinel; the king-legality guard in see() stops it
// ever being counted as captured.
constexpr std::array<int, 6> SEE_VALUE = {100, 320, 330, 500, 900, 100000};

// Castling rights as a 4-bit mask. The bit layout matches the index used by
// ZOBRIST_CASTLING, so the rights byte indexes that table directly.
constexpr std::uint8_t CR_WK = 1, CR_WQ = 2, CR_BK = 4, CR_BQ = 8;

std::array<std::array<U64, 64>, 12> ZOBRIST_PIECES{};
U64 ZOBRIST_SIDE = 0;
std::array<U64, 16> ZOBRIST_CASTLING{};
std::array<U64, 8> ZOBRIST_EN_PASSANT_FILE{};

bool zobrist_initialised = false;

std::array<U64, 64> KNIGHT_ATTACKS_TBL{};
std::array<U64, 64> KING_ATTACKS_TBL{};
std::array<std::array<U64, 64>, 2> PAWN_ATTACKS_TBL{};

bool attack_tables_initialised = false;

void init_attack_tables() {
    if (attack_tables_initialised) {
        return;
    }

    for (int sq = 0; sq < 64; ++sq) {
        U64 knight = 0;

        for (int delta : KNIGHT_DELTAS) {
            int nxt = sq + delta;

            if (
                on_board(nxt) &&
                std::max(
                    std::abs(file_of(sq) - file_of(nxt)),
                    std::abs(rank_of(sq) - rank_of(nxt))
                ) == 2
            ) {
                knight |= bit(nxt);
            }
        }

        KNIGHT_ATTACKS_TBL[sq] = knight;

        U64 king = 0;

        for (int delta : KING_DELTAS) {
            int nxt = sq + delta;

            if (
                on_board(nxt) &&
                std::max(
                    std::abs(file_of(sq) - file_of(nxt)),
                    std::abs(rank_of(sq) - rank_of(nxt))
                ) == 1
            ) {
                king |= bit(nxt);
            }
        }

        KING_ATTACKS_TBL[sq] = king;

        for (int colour : {WHITE, BLACK}) {
            U64 pawn = 0;

            int d1 = colour == WHITE ? 7 : -7;
            int d2 = colour == WHITE ? 9 : -9;

            for (int delta : {d1, d2}) {
                int nxt = sq + delta;

                if (on_board(nxt) && std::abs(file_of(sq) - file_of(nxt)) == 1) {
                    pawn |= bit(nxt);
                }
            }

            PAWN_ATTACKS_TBL[colour][sq] = pawn;
        }
    }

    attack_tables_initialised = true;
}

void init_zobrist() {
    if (zobrist_initialised) {
        return;
    }

    std::mt19937_64 rng(123456789ULL);

    for (auto& piece_keys : ZOBRIST_PIECES) {
        for (auto& key : piece_keys) {
            key = rng();
        }
    }

    ZOBRIST_SIDE = rng();

    for (auto& key : ZOBRIST_CASTLING) {
        key = rng();
    }

    for (auto& key : ZOBRIST_EN_PASSANT_FILE) {
        key = rng();
    }

    zobrist_initialised = true;
}

int piece_from_char(char c) {
    auto pos = PIECES.find(c);

    if (pos == std::string::npos) {
        throw std::runtime_error("invalid piece character in fen");
    }

    return static_cast<int>(pos);
}

char char_from_piece(int piece) {
    return PIECES.at(piece);
}

std::uint8_t parse_castling_field(const std::string& field) {
    std::uint8_t rights = 0;

    if (field.find('K') != std::string::npos) rights |= CR_WK;
    if (field.find('Q') != std::string::npos) rights |= CR_WQ;
    if (field.find('k') != std::string::npos) rights |= CR_BK;
    if (field.find('q') != std::string::npos) rights |= CR_BQ;

    return rights;
}

U64 bit(int sq) {
    return 1ULL << sq;
}

int rank_of(int sq) {
    return sq / 8;
}

int file_of(int sq) {
    return sq % 8;
}

std::string square_name(int sq) {
    std::string out;
    out += static_cast<char>('a' + file_of(sq));
    out += static_cast<char>('1' + rank_of(sq));
    return out;
}

int square_index(const std::string& name) {
    return (name[1] - '1') * 8 + (name[0] - 'a');
}

std::string move_to_string(const Move& move) {
    std::string text = square_name(move.from()) + square_name(move.to());

    if (move.is_promotion()) {
        text += "nbrq"[move.promo_type()];
    }

    return text;
}

int mirror_square(int sq) {
    return sq ^ 56;
}

bool on_board(int sq) {
    return sq >= 0 && sq < 64;
}

std::pair<int, U64> pop_lsb(U64 bb) {
    int sq = __builtin_ctzll(bb);
    return {sq, bb & (bb - 1)};
}

bool same_row_or_col_or_diag(int a, int b, int delta) {
    int af = file_of(a);
    int bf = file_of(b);
    int ar = rank_of(a);
    int br = rank_of(b);

    if (delta == 1 || delta == -1) {
        return ar == br;
    }

    if (delta == 8 || delta == -8) {
        return af == bf;
    }

    return std::abs(af - bf) == std::abs(ar - br);
}

bool step_ok(int a, int b, int delta) {
    if (!on_board(b)) {
        return false;
    }

    return same_row_or_col_or_diag(a, b, delta);
}

// Magic bitboards for sliding pieces: one multiply-shift indexes a per-square
// table of precomputed attack sets. The magics are searched for at startup
// with a fixed PRNG seed, so the tables are identical on every run and no
// precomputed constants need embedding. Plain (non-PEXT) magics, so the binary
// runs on any 64-bit CPU regardless of -march.

namespace {

struct Magic {
    U64 mask = 0;
    U64 magic = 0;
    int shift = 0;
    const U64* attacks = nullptr;
};

std::array<Magic, 64> BISHOP_MAGIC{};
std::array<Magic, 64> ROOK_MAGIC{};
std::vector<U64> BISHOP_POOL;
std::vector<U64> ROOK_POOL;
bool magics_initialised = false;

constexpr int BISHOP_RAY[4] = {9, 7, -9, -7};
constexpr int ROOK_RAY[4]   = {8, -8, 1, -1};

int popcount64(U64 b) {
    return __builtin_popcountll(b);
}

// Reference attack set by ray-walking; used only while building the tables.
U64 slide_reference(int sq, U64 occ, const int* deltas) {
    U64 attacks = 0;

    for (int i = 0; i < 4; ++i) {
        int delta = deltas[i];
        int cur = sq;

        while (true) {
            int nxt = cur + delta;

            if (!step_ok(cur, nxt, delta)) {
                break;
            }

            attacks |= bit(nxt);

            if (occ & bit(nxt)) {
                break;
            }

            cur = nxt;
        }
    }

    return attacks;
}

// Relevant-occupancy mask: the interior squares of each ray. Edge squares are
// excluded because a blocker on the far edge cannot change what lies beyond it.
U64 slider_mask(int sq, const int* deltas) {
    U64 mask = 0;

    for (int i = 0; i < 4; ++i) {
        int delta = deltas[i];
        int cur = sq;

        while (true) {
            int nxt = cur + delta;

            if (!step_ok(cur, nxt, delta)) {
                break;
            }

            int beyond = nxt + delta;

            if (!step_ok(nxt, beyond, delta)) {
                break;   // nxt is an edge square: stop without adding it
            }

            mask |= bit(nxt);
            cur = nxt;
        }
    }

    return mask;
}

void init_slider(
    std::array<Magic, 64>& table,
    std::vector<U64>& pool,
    const int* deltas
) {
    // Pass 1: masks, shifts, and per-square offsets into one flat pool. The
    // pool is sized exactly once so the attack pointers stored below stay valid.
    std::array<int, 64> offset{};
    int total = 0;

    for (int sq = 0; sq < 64; ++sq) {
        table[sq].mask = slider_mask(sq, deltas);
        int bits = popcount64(table[sq].mask);
        table[sq].shift = 64 - bits;
        offset[sq] = total;
        total += (1 << bits);
    }

    pool.assign(static_cast<std::size_t>(total), 0);

    std::mt19937_64 rng(0x9E3779B97F4A7C15ULL);

    for (int sq = 0; sq < 64; ++sq) {
        U64 mask = table[sq].mask;
        int bits = 64 - table[sq].shift;
        int size = 1 << bits;

        // Enumerate every occupancy subset of the mask (carry-rippler) and its
        // reference attack set.
        std::vector<U64> occ(size), ref(size);
        U64 sub = 0;
        for (int i = 0; i < size; ++i) {
            occ[i] = sub;
            ref[i] = slide_reference(sq, sub, deltas);
            sub = (sub - mask) & mask;
        }

        U64* slot = pool.data() + offset[sq];
        std::vector<U64> filled(size, 0);
        std::vector<char> used(size, 0);

        while (true) {
            U64 magic = rng() & rng() & rng();   // sparse candidate

            if (popcount64((mask * magic) & 0xFF00000000000000ULL) < 6) {
                continue;
            }

            std::fill(used.begin(), used.end(), 0);
            bool ok = true;

            for (int i = 0; i < size; ++i) {
                std::size_t idx = static_cast<std::size_t>(
                    (occ[i] * magic) >> table[sq].shift
                );

                if (!used[idx]) {
                    used[idx] = 1;
                    filled[idx] = ref[i];
                } else if (filled[idx] != ref[i]) {
                    ok = false;
                    break;
                }
            }

            if (ok) {
                table[sq].magic = magic;
                for (int i = 0; i < size; ++i) {
                    slot[i] = filled[i];
                }
                table[sq].attacks = slot;
                break;
            }
        }
    }
}

void init_magics() {
    if (magics_initialised) {
        return;
    }

    init_slider(BISHOP_MAGIC, BISHOP_POOL, BISHOP_RAY);
    init_slider(ROOK_MAGIC, ROOK_POOL, ROOK_RAY);
    magics_initialised = true;
}

inline U64 bishop_attacks(int sq, U64 occ) {
    const Magic& m = BISHOP_MAGIC[sq];
    return m.attacks[((occ & m.mask) * m.magic) >> m.shift];
}

inline U64 rook_attacks(int sq, U64 occ) {
    const Magic& m = ROOK_MAGIC[sq];
    return m.attacks[((occ & m.mask) * m.magic) >> m.shift];
}

// Geometry tables for legality testing.
//   BETWEEN[a][b] = squares strictly between a and b on a shared line (else 0)
//   LINE[a][b]    = the whole board line through a and b (else 0)
U64 BETWEEN[64][64];
U64 LINE[64][64];
bool lines_initialised = false;

void init_lines() {
    if (lines_initialised) {
        return;
    }

    for (int a = 0; a < 64; ++a) {
        for (int b = 0; b < 64; ++b) {
            BETWEEN[a][b] = 0;
            LINE[a][b] = 0;
        }
    }

    const int dirs[8] = {1, -1, 8, -8, 9, -9, 7, -7};

    for (int a = 0; a < 64; ++a) {
        // BETWEEN: walk each ray, accumulating the squares passed so far.
        for (int di = 0; di < 8; ++di) {
            int delta = dirs[di];
            int cur = a;
            U64 path = 0;

            while (step_ok(cur, cur + delta, delta)) {
                int nxt = cur + delta;
                BETWEEN[a][nxt] = path;
                path |= bit(nxt);
                cur = nxt;
            }
        }

        // LINE: for each of the four axes, build the full board line through a,
        // then assign it to every square that lies on that line.
        const int axes[4][2] = {{1, -1}, {8, -8}, {9, -9}, {7, -7}};

        for (auto& axis : axes) {
            U64 full = bit(a);

            for (int k = 0; k < 2; ++k) {
                int delta = axis[k];
                int cur = a;
                while (step_ok(cur, cur + delta, delta)) {
                    cur += delta;
                    full |= bit(cur);
                }
            }

            U64 t = full;
            while (t) {
                auto [b, rest] = pop_lsb(t);
                t = rest;
                LINE[a][b] = full;
            }
        }
    }

    lines_initialised = true;
}

} // namespace

Board::Board() {
    init_zobrist();
    init_attack_tables();
    init_magics();
    init_lines();
    set_fen(START_FEN);
}

Board::Board(const std::string& fen) {
    init_zobrist();
    init_attack_tables();
    init_magics();
    init_lines();
    set_fen(fen);
}

void Board::set_fen(const std::string& fen) {
    std::istringstream stream(fen);

    std::string placement;
    std::string side;
    std::string castling_part;
    std::string ep;

    stream >> placement >> side >> castling_part >> ep;

    bitboards.fill(0);
    mailbox.fill(-1);
    position_history_count = 0;

    int rank = 7;
    int file = 0;

    for (char c : placement) {
        if (c == '/') {
            rank -= 1;
            file = 0;
        } else if (std::isdigit(static_cast<unsigned char>(c))) {
            file += c - '0';
        } else {
            int sq = rank * 8 + file;
            int piece = piece_from_char(c);
            bitboards[piece] |= bit(sq);
            mailbox[sq] = piece;
            file += 1;
        }
    }

    side_to_move = side == "w" ? WHITE : BLACK;
    castling_rights = castling_part == "-" ? 0 : parse_castling_field(castling_part);
    en_passant = ep == "-" ? -1 : square_index(ep);

    if (!(stream >> halfmove_clock)) {
        halfmove_clock = 0;
    }

    if (!(stream >> fullmove_number)) {
        fullmove_number = 1;
    }

    refresh_occupancy();

    hash_key = compute_hash();
}

U64 Board::compute_hash() const {
    U64 key = 0;

    for (int piece = 0; piece < 12; ++piece) {
        U64 bb = bitboards[piece];

        while (bb) {
            auto [sq, next] = pop_lsb(bb);
            bb = next;
            key ^= ZOBRIST_PIECES[piece][sq];
        }
    }

    if (side_to_move == BLACK) {
        key ^= ZOBRIST_SIDE;
    }

    key ^= ZOBRIST_CASTLING[castling_rights];

    if (en_passant >= 0) {
        key ^= ZOBRIST_EN_PASSANT_FILE[file_of(en_passant)];
    }

    return key;
}

U64 Board::occupancy(std::optional<int> colour) const {
    if (!colour.has_value()) {
        return occ_all;
    }

    return *colour == WHITE ? occ_white : occ_black;
}

void Board::refresh_occupancy() {
    occ_white = bitboards[WP] | bitboards[WN] | bitboards[WB] |
                bitboards[WR] | bitboards[WQ] | bitboards[WK];
    occ_black = bitboards[BP] | bitboards[BN] | bitboards[BB] |
                bitboards[BR] | bitboards[BQ] | bitboards[BK];
    occ_all = occ_white | occ_black;
}

void Board::assert_occupancy_sync() const {
#ifndef NDEBUG
    // The failure mode this guards against is silent: a stale occupancy makes
    // movegen and SEE reason about a board that does not exist, and the search
    // carries on producing plausible numbers. Check it on every make/unmake.
    U64 white = bitboards[WP] | bitboards[WN] | bitboards[WB] |
                bitboards[WR] | bitboards[WQ] | bitboards[WK];
    U64 black = bitboards[BP] | bitboards[BN] | bitboards[BB] |
                bitboards[BR] | bitboards[BQ] | bitboards[BK];

    assert(occ_white == white);
    assert(occ_black == black);
    assert(occ_all == (white | black));
#endif
}

std::optional<int> Board::piece_at(int sq) const {
    int piece = mailbox[sq];

    if (piece == -1) {
        return std::nullopt;
    }

    return piece;
}

int Board::king_square(int colour) const {
    int king = colour == WHITE ? WK : BK;
    U64 bb = bitboards[king];

    if (bb == 0) {
        return -1;
    }

    return 63 - __builtin_clzll(bb);
}

U64 Board::bishop_attacks_from(int sq, U64 occ) const {
    return bishop_attacks(sq, occ);
}

U64 Board::rook_attacks_from(int sq, U64 occ) const {
    return rook_attacks(sq, occ);
}

U64 Board::queen_attacks_from(int sq, U64 occ) const {
    return bishop_attacks(sq, occ) | rook_attacks(sq, occ);
}

U64 Board::knight_attacks(int sq) const {
    return KNIGHT_ATTACKS_TBL[sq];
}

U64 Board::king_attacks(int sq) const {
    return KING_ATTACKS_TBL[sq];
}

U64 Board::pawn_attacks_from(int sq, int colour) const {
    return PAWN_ATTACKS_TBL[colour][sq];
}

bool Board::is_square_attacked(int sq, int by_colour) const {
    // Attacker-centric: stand on sq and ask which squares could attack it.
    // Symmetry: a knight on A attacks B iff a knight on B attacks A.
    // For pawns the pattern is colour-flipped: a WHITE pawn attacks sq iff
    // it sits on a square in the BLACK pawn-attack pattern from sq.

    if (bitboards[by_colour == WHITE ? WN : BN] & KNIGHT_ATTACKS_TBL[sq]) {
        return true;
    }

    if (bitboards[by_colour == WHITE ? WP : BP] & PAWN_ATTACKS_TBL[by_colour ^ 1][sq]) {
        return true;
    }

    if (bitboards[by_colour == WHITE ? WK : BK] & KING_ATTACKS_TBL[sq]) {
        return true;
    }

    U64 queens = bitboards[by_colour == WHITE ? WQ : BQ];
    U64 diag = bitboards[by_colour == WHITE ? WB : BB] | queens;
    U64 orth = bitboards[by_colour == WHITE ? WR : BR] | queens;

    if (!(diag | orth)) {
        return false;
    }

    U64 occ = occupancy();

    if (diag && (bishop_attacks(sq, occ) & diag)) {
        return true;
    }

    if (orth && (rook_attacks(sq, occ) & orth)) {
        return true;
    }

    return false;
}

U64 Board::attackers_to(int sq, U64 occ) const {
    // Every piece of either colour that attacks `sq` given occupancy `occ`.
    // Sliders are regenerated against `occ`, so removing a front piece from
    // `occ` and recomputing reveals any x-ray attacker behind it for free.
    U64 result = 0;

    result |= KNIGHT_ATTACKS_TBL[sq] & (bitboards[WN] | bitboards[BN]);
    result |= KING_ATTACKS_TBL[sq] & (bitboards[WK] | bitboards[BK]);

    // Pawn attackers are colour-flipped, matching is_square_attacked: white
    // pawns attack `sq` from the black pawn-attack pattern of `sq`, and vice
    // versa.
    result |= PAWN_ATTACKS_TBL[BLACK][sq] & bitboards[WP];
    result |= PAWN_ATTACKS_TBL[WHITE][sq] & bitboards[BP];

    U64 bishops_queens = bitboards[WB] | bitboards[BB] | bitboards[WQ] | bitboards[BQ];
    U64 rooks_queens = bitboards[WR] | bitboards[BR] | bitboards[WQ] | bitboards[BQ];

    result |= bishop_attacks(sq, occ) & bishops_queens;
    result |= rook_attacks(sq, occ) & rooks_queens;

    // Restrict to pieces still present in `occ` (table-based knight/king/pawn
    // hits are not otherwise occ-aware).
    return result & occ;
}

bool Board::square_attacked_with_occ(int sq, int by_colour, U64 occ) const {
    // Like is_square_attacked, but slider rays are cast against a caller-supplied
    // occupancy. Used for king-move legality, where the king is first removed
    // from the board so it cannot block a check on itself.
    if (bitboards[by_colour == WHITE ? WN : BN] & KNIGHT_ATTACKS_TBL[sq]) {
        return true;
    }
    if (bitboards[by_colour == WHITE ? WP : BP] & PAWN_ATTACKS_TBL[by_colour ^ 1][sq]) {
        return true;
    }
    if (bitboards[by_colour == WHITE ? WK : BK] & KING_ATTACKS_TBL[sq]) {
        return true;
    }

    U64 queens = bitboards[by_colour == WHITE ? WQ : BQ];
    U64 diag = bitboards[by_colour == WHITE ? WB : BB] | queens;
    U64 orth = bitboards[by_colour == WHITE ? WR : BR] | queens;

    if (diag && (bishop_attacks(sq, occ) & diag)) {
        return true;
    }
    if (orth && (rook_attacks(sq, occ) & orth)) {
        return true;
    }

    return false;
}

LegalityInfo Board::legality_info() const {
    LegalityInfo li;
    int us = side_to_move;
    int them = us ^ 1;
    int ksq = king_square(us);
    li.ksq = ksq;

    U64 occ = occupancy();
    U64 their_pieces = occupancy(them);

    // Checkers: enemy pieces attacking the king right now.
    U64 checkers = attackers_to(ksq, occ) & their_pieces;
    li.checkers = checkers;
    li.nchk = __builtin_popcountll(checkers);

    if (li.nchk == 1) {
        auto [csq, rest] = pop_lsb(checkers);
        (void) rest;
        // Resolve a single check by capturing the checker or, for slider checks,
        // interposing on a square between it and the king.
        li.check_mask = checkers | BETWEEN[ksq][csq];
    }

    // Pinned pieces: for each enemy slider aligned with the king, if exactly one
    // piece sits between it and the king and that piece is ours, it is pinned.
    U64 bq = bitboards[them == WHITE ? WB : BB] | bitboards[them == WHITE ? WQ : BQ];
    U64 rq = bitboards[them == WHITE ? WR : BR] | bitboards[them == WHITE ? WQ : BQ];
    U64 snipers = (bishop_attacks(ksq, 0) & bq) | (rook_attacks(ksq, 0) & rq);
    U64 own_pieces = occupancy(us);
    U64 pinned = 0;

    while (snipers) {
        auto [s, rest] = pop_lsb(snipers);
        snipers = rest;
        U64 blockers = BETWEEN[ksq][s] & occ;
        if (blockers && (blockers & (blockers - 1)) == 0 && (blockers & own_pieces)) {
            pinned |= blockers;
        }
    }

    li.pinned = pinned;
    return li;
}

bool Board::is_legal(const Move& move, const LegalityInfo& li) const {
    int us = side_to_move;
    int them = us ^ 1;
    int from = move.from();
    int to = move.to();

    // Castling is fully validated during generation (king not in check and the
    // transit squares unattacked), so accept it directly.
    if (move.is_castling()) {
        return true;
    }

    // King moves: the destination must be safe once the king has left its square
    // (otherwise it could appear to escape a slider while still on the ray).
    if (from == li.ksq) {
        U64 occ = occupancy() ^ bit(li.ksq);
        return !square_attacked_with_occ(to, them, occ);
    }

    // En passant removes two pawns at once and can unveil a discovered check, so
    // test the king against the exact post-capture occupancy.
    if (move.is_en_passant()) {
        int cap = us == WHITE ? to - 8 : to + 8;
        U64 occ2 = (occupancy() ^ bit(from) ^ bit(cap)) | bit(to);
        int ksq = li.ksq;
        U64 their_pawns = bitboards[them == WHITE ? WP : BP] & ~bit(cap);

        if (PAWN_ATTACKS_TBL[us][ksq] & their_pawns) return false;
        if (KNIGHT_ATTACKS_TBL[ksq] & bitboards[them == WHITE ? WN : BN]) return false;
        if (KING_ATTACKS_TBL[ksq] & bitboards[them == WHITE ? WK : BK]) return false;

        U64 bq = bitboards[them == WHITE ? WB : BB] | bitboards[them == WHITE ? WQ : BQ];
        U64 rq = bitboards[them == WHITE ? WR : BR] | bitboards[them == WHITE ? WQ : BQ];
        if (bishop_attacks(ksq, occ2) & bq) return false;
        if (rook_attacks(ksq, occ2) & rq) return false;
        return true;
    }

    // During double check only the king may move.
    if (li.nchk == 2) {
        return false;
    }

    // A pinned piece may only travel along its pin line and can never resolve a
    // check.
    if (bit(from) & li.pinned) {
        if (li.nchk != 0) return false;
        if (!(LINE[li.ksq][from] & bit(to))) return false;
    }

    // Under a single check a non-king move must capture the checker or block it.
    if (li.nchk == 1 && !(li.check_mask & bit(to))) {
        return false;
    }

    return true;
}

CheckInfo Board::check_info() const {
    CheckInfo ci;

    int us = side_to_move;
    int them = us ^ 1;
    int ksq = king_square(them);
    ci.ksq = ksq;

    if (ksq < 0) {
        return ci;
    }

    U64 occ = occ_all;

    // Squares from which each of our piece types would attack the enemy king.
    // Pawns are colour-flipped in the same way as is_square_attacked: our pawn
    // attacks ksq exactly when it stands on the enemy pawn-attack pattern of
    // ksq. Kings cannot deliver check.
    ci.check_squares[0] = PAWN_ATTACKS_TBL[them][ksq];
    ci.check_squares[1] = KNIGHT_ATTACKS_TBL[ksq];
    ci.check_squares[2] = bishop_attacks(ksq, occ);
    ci.check_squares[3] = rook_attacks(ksq, occ);
    ci.check_squares[4] = ci.check_squares[2] | ci.check_squares[3];
    ci.check_squares[5] = 0;

    // Discovered-check candidates: the mirror of legality_info's pin scan, run
    // against the ENEMY king with OUR sliders. A piece that is the only thing
    // on the ray between one of our sliders and their king discovers check by
    // stepping off that ray. Only our own pieces qualify -- a lone enemy
    // blocker is pinned to its own king, and moving it is not our move.
    U64 our_bq = bitboards[us == WHITE ? WB : BB] | bitboards[us == WHITE ? WQ : BQ];
    U64 our_rq = bitboards[us == WHITE ? WR : BR] | bitboards[us == WHITE ? WQ : BQ];
    U64 snipers = (bishop_attacks(ksq, 0) & our_bq) | (rook_attacks(ksq, 0) & our_rq);
    U64 own = us == WHITE ? occ_white : occ_black;

    while (snipers) {
        auto [s, rest] = pop_lsb(snipers);
        snipers = rest;

        U64 blockers = BETWEEN[ksq][s] & occ;

        if (blockers && (blockers & (blockers - 1)) == 0 && (blockers & own)) {
            ci.discovery |= blockers;
        }
    }

    return ci;
}

bool Board::gives_check(const Move& move, const CheckInfo& ci) const {
    int ksq = ci.ksq;

    if (ksq < 0) {
        return false;
    }

    int from = move.from();
    int to = move.to();
    int us = side_to_move;

    U64 our_bq = bitboards[us == WHITE ? WB : BB] | bitboards[us == WHITE ? WQ : BQ];
    U64 our_rq = bitboards[us == WHITE ? WR : BR] | bitboards[us == WHITE ? WQ : BQ];

    // Promotion, en passant and castling all change occupancy in ways the
    // precomputed check_squares cannot describe (the arriving piece is not the
    // one that left, or two squares empty at once, or two pieces move). Each
    // is rare, so each is answered from the exact post-move occupancy.
    switch (move.kind()) {
        case MT_PROMO: {
            // The pawn vacates `from`, which may itself be on the line the
            // promoted piece now checks along -- e.g. a pawn on e7 promoting
            // to a queen on e8 against a king on e1.
            U64 occ_after = (occ_all ^ bit(from)) | bit(to);
            int ptype = move.promo_piece(us) % 6;

            if (ptype == 1 && (KNIGHT_ATTACKS_TBL[ksq] & bit(to))) {
                return true;
            }

            if ((ptype == 2 || ptype == 4)
                    && (bishop_attacks(ksq, occ_after) & bit(to))) {
                return true;
            }

            if ((ptype == 3 || ptype == 4)
                    && (rook_attacks(ksq, occ_after) & bit(to))) {
                return true;
            }

            return (ci.discovery & bit(from)) && !(LINE[ksq][from] & bit(to));
        }

        case MT_EP: {
            // Two squares empty at once: the pawn's origin and the victim's
            // square, which are on different files. Either can uncover a
            // slider, so recompute both ray sets outright.
            int cap = us == WHITE ? to - 8 : to + 8;
            U64 occ_after = (occ_all ^ bit(from) ^ bit(cap)) | bit(to);

            if (ci.check_squares[0] & bit(to)) {
                return true;
            }

            return (bishop_attacks(ksq, occ_after) & our_bq)
                || (rook_attacks(ksq, occ_after) & our_rq);
        }

        case MT_CASTLE: {
            // The king cannot give check, but the rook lands on a new square,
            // and the king vacating its own can uncover one of our sliders.
            int rook_from;
            int rook_to;

            switch (to) {
                case 6:  rook_from = 7;  rook_to = 5;  break;
                case 2:  rook_from = 0;  rook_to = 3;  break;
                case 62: rook_from = 63; rook_to = 61; break;
                default: rook_from = 56; rook_to = 59; break;   // to == 58
            }

            U64 occ_after =
                (occ_all ^ bit(from) ^ bit(rook_from)) | bit(to) | bit(rook_to);
            U64 rq_after = (our_rq ^ bit(rook_from)) | bit(rook_to);

            return (bishop_attacks(ksq, occ_after) & our_bq)
                || (rook_attacks(ksq, occ_after) & rq_after);
        }

        default:
            break;
    }

    // Ordinary move or capture.
    //
    // The direct test uses check_squares, which was built against the
    // PRE-move occupancy. That is exact here. The only square whose emptiness
    // could extend a ray to `to` is `from`, and for `from` to sit between the
    // enemy king and `to` all three must be collinear -- which for a slider
    // means it was already attacking the king along that ray before moving,
    // i.e. the enemy king was already in check. It never is. Knights cannot
    // produce three collinear squares at all, and the pawn, knight and king
    // tables do not depend on occupancy.
    int ptype = mailbox[from] % 6;

    if (ci.check_squares[ptype] & bit(to)) {
        return true;
    }

    // Discovered check: the mover was the sole blocker on one of our sliders'
    // rays to the enemy king, and it has stepped off that line. Staying on the
    // line -- moving further out along it, for instance -- still blocks.
    return (ci.discovery & bit(from)) && !(LINE[ksq][from] & bit(to));
}

int Board::see(const Move& move) const {
    // Static exchange evaluation of a capture: net material won on move.to()
    // if both sides keep recapturing with their least valuable attacker while
    // it is profitable. Pin-blind, as SEE usually is. Promotions are handled
    // by the caller, not here.
    int to = move.to();
    int from = move.from();
    int mover = mailbox[from];

    if (mover < 0) {
        return 0;
    }

    U64 occ = occupancy();
    int victim_value;

    if (move.is_en_passant()) {
        // The captured pawn sits behind `to`, not on it.
        int captured_sq = to + (mover < 6 ? -8 : 8);
        victim_value = SEE_VALUE[0];
        occ ^= bit(captured_sq);
    } else {
        int victim = mailbox[to];

        if (victim < 0) {
            return 0;   // not a capture: SEE is only defined on captures
        }

        victim_value = SEE_VALUE[victim % 6];
    }

    std::array<int, 32> gain{};
    int d = 0;
    gain[0] = victim_value;

    int on_square_type = mover % 6;   // piece now standing on `to`
    occ ^= bit(from);                 // the mover has left its origin
    int side = (mover < 6) ? BLACK : WHITE;   // opponent recaptures next

    while (true) {
        U64 side_attackers = attackers_to(to, occ) & occupancy(side);

        if (!side_attackers) {
            break;
        }

        int lva_sq = -1;
        int lva_type = -1;

        for (int t = 0; t < 6; ++t) {
            U64 pieces = side_attackers & bitboards[side * 6 + t];

            if (pieces) {
                lva_sq = __builtin_ctzll(pieces);
                lva_type = t;
                break;
            }
        }

        if (lva_sq == -1) {
            break;
        }

        // A king may only capture if the square is not defended by the other
        // side once the king has moved (otherwise it would step into check).
        // Removing the king's origin bit also reveals any x-ray behind it.
        if (lva_type == 5) {
            U64 opp_attackers =
                attackers_to(to, occ ^ bit(lva_sq)) & occupancy(side ^ 1);

            if (opp_attackers) {
                break;
            }
        }

        ++d;
        gain[d] = SEE_VALUE[on_square_type] - gain[d - 1];

        on_square_type = lva_type;
        occ ^= bit(lva_sq);   // remove the used attacker; reveals x-rays
        side ^= 1;

        if (d >= 31) {
            break;
        }
    }

    // Negamax the gain array back: each side stops capturing once continuing
    // would lose material. `d` counts recaptures; the initial capture is
    // already folded into gain[0], so fold gain[d]..gain[1] down into gain[0].
    while (d > 0) {
        gain[d - 1] = -std::max(-gain[d - 1], gain[d]);
        --d;
    }

    return gain[0];
}

bool Board::see_ge(const Move& move, int threshold) const {
    // Equivalent to see(move) >= threshold but without computing the exact
    // value: exits early when the victim already covers the threshold even
    // after conceding the moving piece. Same geometry, x-ray handling and
    // king-legality rule as see().
    int from = move.from();
    int to = move.to();
    int mover = mailbox[from];

    if (mover < 0) {
        return 0 >= threshold;
    }

    U64 occ = occupancy() ^ bit(from);
    int victim_value;

    if (move.is_en_passant()) {
        victim_value = SEE_VALUE[0];
        occ ^= bit(to + (mover < 6 ? -8 : 8));
    } else {
        int victim = mailbox[to];
        victim_value = (victim < 0) ? 0 : SEE_VALUE[victim % 6];
        if (victim >= 0) {
            occ ^= bit(to);
        }
    }

    // Fail if winning the victim still falls short of the threshold; succeed
    // if we clear it even after conceding the moving piece.
    int balance = victim_value - threshold;
    if (balance < 0) {
        return false;
    }

    balance -= SEE_VALUE[mover % 6];
    if (balance >= 0) {
        return true;
    }

    int mover_colour = (mover < 6) ? WHITE : BLACK;
    int side = mover_colour ^ 1;   // opponent recaptures next

    while (true) {
        U64 side_attackers = attackers_to(to, occ) & occupancy(side);

        if (!side_attackers) {
            break;
        }

        int lva_type = -1;
        U64 lva_bit = 0;

        for (int t = 0; t < 6; ++t) {
            U64 pieces = side_attackers & bitboards[side * 6 + t];

            if (pieces) {
                lva_type = t;
                lva_bit = pieces & (~pieces + 1);   // least significant bit
                break;
            }
        }

        // Same king-legality rule as see(): a king may only capture an
        // otherwise-undefended square. Removing its origin reveals x-rays.
        if (lva_type == 5
                && (attackers_to(to, occ ^ lva_bit) & occupancy(side ^ 1))) {
            break;
        }

        occ ^= lva_bit;          // remove the used attacker; reveals x-rays
        side ^= 1;
        balance = -balance - 1 - SEE_VALUE[lva_type];

        if (balance >= 0) {
            break;
        }
    }

    // Whichever side could not (profitably) continue is the loser; the move
    // meets the threshold iff that side is not the original mover's side.
    return mover_colour != side;
}

bool Board::is_repetition() const {
    int n = position_history_count;
    int limit = std::min(n, halfmove_clock);

    // Same side to move recurs every 2 plies; positions older than the last
    // irreversible move (pawn move / capture) can never repeat. `limit` is
    // bounded by halfmove_clock, so this window is always far inside the ring.
    for (int i = n - 2; i >= n - limit; i -= 2) {
        if (position_history[i & POSITION_HISTORY_MASK] == hash_key) {
            return true;
        }
    }

    return false;
}

bool Board::in_check(int colour) const {
    int king = king_square(colour);
    return king != -1 && is_square_attacked(king, colour ^ 1);
}

void Board::add_pawn_move(MoveList& moves, int from_sq, int to_sq, int colour) {
    int promotion_rank = colour == WHITE ? 7 : 0;

    if (rank_of(to_sq) == promotion_rank) {
        // queen first: promotions are generated in likely-best order
        moves.add(Move(from_sq, to_sq, PROMO_Q, MT_PROMO));
        moves.add(Move(from_sq, to_sq, PROMO_R, MT_PROMO));
        moves.add(Move(from_sq, to_sq, PROMO_B, MT_PROMO));
        moves.add(Move(from_sq, to_sq, PROMO_N, MT_PROMO));
    } else {
        moves.add(Move(from_sq, to_sq));
    }
}

void Board::add_knight_moves(MoveList& moves, int piece, U64 own) {
    U64 bb = bitboards[piece];

    while (bb) {
        auto [sq, next] = pop_lsb(bb);
        bb = next;

        int them = piece <= WK ? BLACK : WHITE;
        U64 enemy_king = bitboards[them == WHITE ? WK : BK];
        U64 attacks = knight_attacks(sq) & ~own & ~enemy_king & FULL;

        while (attacks) {
            auto [to_sq, next_attacks] = pop_lsb(attacks);
            attacks = next_attacks;
            moves.add(Move(sq, to_sq));
        }
    }
}

void Board::add_king_moves(MoveList& moves, int piece, U64 own) {
    U64 bb = bitboards[piece];

    while (bb) {
        auto [sq, next] = pop_lsb(bb);
        bb = next;

        int them = piece <= WK ? BLACK : WHITE;
        U64 enemy_king = bitboards[them == WHITE ? WK : BK];
        U64 attacks = king_attacks(sq) & ~own & ~enemy_king & FULL;

        while (attacks) {
            auto [to_sq, next_attacks] = pop_lsb(attacks);
            attacks = next_attacks;
            moves.add(Move(sq, to_sq));
        }
    }
}

namespace {

// Emit moves for one piece bitboard. Templated on the attack generator, so
// each call site compiles down to its own lookup with no dispatch: the piece
// type is a property of the call, not of the data.
//
// `targets` is the already-masked destination set -- everything except our own
// pieces and the enemy king for full generation, or just the enemy pieces when
// generating captures only. It does not vary between piece types, so the
// caller computes it once rather than per piece.
template <typename AttackFn>
void add_moves_from_attacks(MoveList& moves, U64 bb, U64 targets, U64 occ, AttackFn attacks_of) {
    while (bb) {
        auto [sq, next] = pop_lsb(bb);
        bb = next;

        U64 attacks = attacks_of(sq, occ) & targets;

        while (attacks) {
            auto [to_sq, next_attacks] = pop_lsb(attacks);
            attacks = next_attacks;
            moves.add(Move(sq, to_sq));
        }
    }
}

} // namespace

void Board::add_castling_moves(MoveList& moves) {
    int us = side_to_move;
    U64 occ = occupancy();

    if (us == WHITE) {
        if (castling_rights & CR_WK && !(occ & (bit(5) | bit(6)))) {
            if (!in_check(WHITE) && !is_square_attacked(5, BLACK) && !is_square_attacked(6, BLACK)) {
                moves.add(Move(4, 6, 0, MT_CASTLE));
            }
        }

        if (castling_rights & CR_WQ && !(occ & (bit(1) | bit(2) | bit(3)))) {
            if (!in_check(WHITE) && !is_square_attacked(3, BLACK) && !is_square_attacked(2, BLACK)) {
                moves.add(Move(4, 2, 0, MT_CASTLE));
            }
        }
    } else {
        if (castling_rights & CR_BK && !(occ & (bit(61) | bit(62)))) {
            if (!in_check(BLACK) && !is_square_attacked(61, WHITE) && !is_square_attacked(62, WHITE)) {
                moves.add(Move(60, 62, 0, MT_CASTLE));
            }
        }

        if (castling_rights & CR_BQ && !(occ & (bit(57) | bit(58) | bit(59)))) {
            if (!in_check(BLACK) && !is_square_attacked(59, WHITE) && !is_square_attacked(58, WHITE)) {
                moves.add(Move(60, 58, 0, MT_CASTLE));
            }
        }
    }
}

MoveList Board::generate_pseudo_legal_moves() {
    MoveList moves;

    int us = side_to_move;
    int them = us ^ 1;

    U64 own = occupancy(us);
    U64 enemy = occupancy(them);
    U64 enemy_king = bitboards[them == WHITE ? WK : BK];

    enemy &= ~enemy_king;

    // The enemy king must not be capturable, but it must still block occupancy.
    // Without this, pawns can illegally move forwards onto the enemy king square.
    U64 occ = own | enemy | enemy_king;

    if (us == WHITE) {
        U64 pawns = bitboards[WP];

        while (pawns) {
            auto [sq, next] = pop_lsb(pawns);
            pawns = next;

            int one = sq + 8;

            if (on_board(one) && !(occ & bit(one))) {
                add_pawn_move(moves, sq, one, WHITE);

                int two = sq + 16;
                if (rank_of(sq) == 1 && !(occ & bit(two))) {
                    moves.add(Move(sq, two));
                }
            }

            // Capture directions, visited in the same order the two-element
            // loop used: +7 (toward the a-file) then +9. A white pawn is never
            // on the 8th rank, so the only way either target leaves the board
            // is wrapping round a file edge -- which one file test settles,
            // replacing the old on_board / file_of / std::abs guard.
            int file = file_of(sq);

            if (file > 0) {
                int to_sq = sq + 7;

                if (enemy & bit(to_sq)) {
                    add_pawn_move(moves, sq, to_sq, WHITE);
                } else if (en_passant == to_sq) {
                    moves.add(Move(sq, to_sq, 0, MT_EP));
                }
            }

            if (file < 7) {
                int to_sq = sq + 9;

                if (enemy & bit(to_sq)) {
                    add_pawn_move(moves, sq, to_sq, WHITE);
                } else if (en_passant == to_sq) {
                    moves.add(Move(sq, to_sq, 0, MT_EP));
                }
            }
        }
    } else {
        U64 pawns = bitboards[BP];

        while (pawns) {
            auto [sq, next] = pop_lsb(pawns);
            pawns = next;

            int one = sq - 8;

            if (on_board(one) && !(occ & bit(one))) {
                add_pawn_move(moves, sq, one, BLACK);

                int two = sq - 16;
                if (rank_of(sq) == 6 && !(occ & bit(two))) {
                    moves.add(Move(sq, two));
                }
            }

            // Same, mirrored: -7 moves toward the h-file, -9 toward the
            // a-file, and the order (-7 then -9) is preserved.
            int file = file_of(sq);

            if (file < 7) {
                int to_sq = sq - 7;

                if (enemy & bit(to_sq)) {
                    add_pawn_move(moves, sq, to_sq, BLACK);
                } else if (en_passant == to_sq) {
                    moves.add(Move(sq, to_sq, 0, MT_EP));
                }
            }

            if (file > 0) {
                int to_sq = sq - 9;

                if (enemy & bit(to_sq)) {
                    add_pawn_move(moves, sq, to_sq, BLACK);
                } else if (en_passant == to_sq) {
                    moves.add(Move(sq, to_sq, 0, MT_EP));
                }
            }
        }
    }

    add_knight_moves(moves, us == WHITE ? WN : BN, own);

    U64 targets = ~own & ~enemy_king;

    add_moves_from_attacks(moves, bitboards[us == WHITE ? WB : BB], targets, occ,
                     [](int sq, U64 o) { return bishop_attacks(sq, o); });
    add_moves_from_attacks(moves, bitboards[us == WHITE ? WR : BR], targets, occ,
                     [](int sq, U64 o) { return rook_attacks(sq, o); });
    add_moves_from_attacks(moves, bitboards[us == WHITE ? WQ : BQ], targets, occ,
                     [](int sq, U64 o) { return bishop_attacks(sq, o) | rook_attacks(sq, o); });

    add_king_moves(moves, us == WHITE ? WK : BK, own);

    add_castling_moves(moves);

    return moves;
}

// Captures, en passant and promotions only -- the moves quiescence searches.
//
// Quiescence used to generate every pseudo-legal move and then discard the
// quiet ones, which is most of them. This emits only the moves it keeps.
//
// The emission ORDER must match what that filter produced, move for move.
// order_moves() sorts with std::sort, which is not stable, so two moves with
// equal scores can come out in either order depending on how they arrived --
// and equal scores are common among captures. A different order here would be
// a different search, not a faster one. So this mirrors the structure of
// generate_pseudo_legal_moves exactly: same piece order, same per-pawn order
// of push-promotion before captures, same left-then-right capture direction,
// and the same ascending square walks.
MoveList Board::generate_noisy_moves() {
    MoveList moves;

    int us = side_to_move;
    int them = us ^ 1;

    U64 own = occupancy(us);
    U64 enemy = occupancy(them);
    U64 enemy_king = bitboards[them == WHITE ? WK : BK];

    enemy &= ~enemy_king;

    U64 occ = own | enemy | enemy_king;

    // For every non-pawn, the full generator masks with ~own & ~enemy_king, so
    // the moves it emits that land on an occupied square are exactly those
    // landing on `enemy`. That single mask replaces the is_noisy_move test.
    if (us == WHITE) {
        U64 pawns = bitboards[WP];

        while (pawns) {
            auto [sq, next] = pop_lsb(pawns);
            pawns = next;

            // A push is noisy only when it promotes. A non-promoting push and
            // the double push both land on an empty square, so neither can be.
            int one = sq + 8;

            if (on_board(one) && !(occ & bit(one)) && rank_of(one) == 7) {
                add_pawn_move(moves, sq, one, WHITE);
            }

            // Capture directions, visited in the same order the two-element
            // loop used: +7 (toward the a-file) then +9. A white pawn is never
            // on the 8th rank, so the only way either target leaves the board
            // is wrapping round a file edge -- which one file test settles,
            // replacing the old on_board / file_of / std::abs guard.
            int file = file_of(sq);

            if (file > 0) {
                int to_sq = sq + 7;

                if (enemy & bit(to_sq)) {
                    add_pawn_move(moves, sq, to_sq, WHITE);
                } else if (en_passant == to_sq) {
                    moves.add(Move(sq, to_sq, 0, MT_EP));
                }
            }

            if (file < 7) {
                int to_sq = sq + 9;

                if (enemy & bit(to_sq)) {
                    add_pawn_move(moves, sq, to_sq, WHITE);
                } else if (en_passant == to_sq) {
                    moves.add(Move(sq, to_sq, 0, MT_EP));
                }
            }
        }
    } else {
        U64 pawns = bitboards[BP];

        while (pawns) {
            auto [sq, next] = pop_lsb(pawns);
            pawns = next;

            int one = sq - 8;

            if (on_board(one) && !(occ & bit(one)) && rank_of(one) == 0) {
                add_pawn_move(moves, sq, one, BLACK);
            }

            // Same, mirrored: -7 moves toward the h-file, -9 toward the
            // a-file, and the order (-7 then -9) is preserved.
            int file = file_of(sq);

            if (file < 7) {
                int to_sq = sq - 7;

                if (enemy & bit(to_sq)) {
                    add_pawn_move(moves, sq, to_sq, BLACK);
                } else if (en_passant == to_sq) {
                    moves.add(Move(sq, to_sq, 0, MT_EP));
                }
            }

            if (file > 0) {
                int to_sq = sq - 9;

                if (enemy & bit(to_sq)) {
                    add_pawn_move(moves, sq, to_sq, BLACK);
                } else if (en_passant == to_sq) {
                    moves.add(Move(sq, to_sq, 0, MT_EP));
                }
            }
        }
    }

    add_moves_from_attacks(moves, bitboards[us == WHITE ? WN : BN], enemy, occ,
                     [](int sq, U64) { return KNIGHT_ATTACKS_TBL[sq]; });
    add_moves_from_attacks(moves, bitboards[us == WHITE ? WB : BB], enemy, occ,
                     [](int sq, U64 o) { return bishop_attacks(sq, o); });
    add_moves_from_attacks(moves, bitboards[us == WHITE ? WR : BR], enemy, occ,
                     [](int sq, U64 o) { return rook_attacks(sq, o); });
    add_moves_from_attacks(moves, bitboards[us == WHITE ? WQ : BQ], enemy, occ,
                     [](int sq, U64 o) { return bishop_attacks(sq, o) | rook_attacks(sq, o); });
    add_moves_from_attacks(moves, bitboards[us == WHITE ? WK : BK], enemy, occ,
                     [](int sq, U64) { return KING_ATTACKS_TBL[sq]; });

    // Castling is never noisy: the king's destination is required to be empty.

    return moves;
}

MoveList Board::generate_legal_moves() {
    MoveList legal;
    LegalityInfo li = legality_info();

    for (const Move& move : generate_pseudo_legal_moves()) {
        if (is_legal(move, li)) {
            legal.add(move);
        }
    }

    return legal;
}

UndoInfo Board::make_move(const Move& move) {
    int piece = mailbox[move.from()];

    if (piece < 0) {
        throw std::runtime_error("no piece on source square");
    }

    int captured = mailbox[move.to()];                       // -1 = no capture
    int captured_square = captured < 0 ? -1 : move.to();

    UndoInfo undo;
    undo.move = move;
    undo.moved_piece = piece;
    undo.captured_piece = captured;
    undo.captured_square = captured_square;
    undo.old_castling = castling_rights;
    undo.old_en_passant = en_passant;
    undo.old_halfmove_clock = halfmove_clock;
    undo.old_fullmove_number = fullmove_number;
    undo.old_hash_key = hash_key;

    U64 from_mask = bit(move.from());
    U64 to_mask = bit(move.to());

    bitboards[piece] &= ~from_mask & FULL;
    mailbox[move.from()] = -1;

    if (captured >= 0) {
        bitboards[captured] &= ~to_mask & FULL;
    }

    if (move.is_en_passant()) {
        int cap_sq = side_to_move == WHITE ? move.to() - 8 : move.to() + 8;
        int cap_piece = side_to_move == WHITE ? BP : WP;

        captured = cap_piece;
        captured_square = cap_sq;

        bitboards[cap_piece] &= ~bit(cap_sq) & FULL;
        mailbox[cap_sq] = -1;
    }

    int placed_piece = move.is_promotion() ? move.promo_piece(side_to_move) : piece;
    undo.placed_piece = placed_piece;
    undo.captured_piece = captured;
    undo.captured_square = captured_square;

    bitboards[placed_piece] |= to_mask;
    mailbox[move.to()] = placed_piece;

    U64 rook_delta = 0;   // the castling rook's two squares, if any

    if (move.is_castling()) {
        if (move.to() == 6) {
            bitboards[WR] &= ~bit(7) & FULL;
            bitboards[WR] |= bit(5);
            mailbox[7] = -1;
            mailbox[5] = WR;
            rook_delta = bit(7) | bit(5);
        } else if (move.to() == 2) {
            bitboards[WR] &= ~bit(0) & FULL;
            bitboards[WR] |= bit(3);
            mailbox[0] = -1;
            mailbox[3] = WR;
            rook_delta = bit(0) | bit(3);
        } else if (move.to() == 62) {
            bitboards[BR] &= ~bit(63) & FULL;
            bitboards[BR] |= bit(61);
            mailbox[63] = -1;
            mailbox[61] = BR;
            rook_delta = bit(63) | bit(61);
        } else if (move.to() == 58) {
            bitboards[BR] &= ~bit(56) & FULL;
            bitboards[BR] |= bit(59);
            mailbox[56] = -1;
            mailbox[59] = BR;
            rook_delta = bit(56) | bit(59);
        }
    }

    // Mirror the piece edits above into the occupancy cache. side_to_move is
    // still the mover here; it is flipped further down.
    //
    // Each edit is one XOR. For the mover, `from` is ours and empties, `to`
    // becomes ours -- and `to` is never already in our set, because a move
    // cannot capture its own colour -- so both squares toggle. The castling
    // rook toggles its pair the same way. For the opponent, only a captured
    // square toggles, and captured_square is the en-passant victim's square,
    // not move.to(), when the two differ.
    U64& occ_us = side_to_move == WHITE ? occ_white : occ_black;
    U64& occ_them = side_to_move == WHITE ? occ_black : occ_white;

    occ_us ^= from_mask | to_mask | rook_delta;

    if (captured >= 0) {
        occ_them ^= bit(captured_square);
    }

    occ_all = occ_white | occ_black;

    update_castling_rights(piece, move, captured);

    en_passant = -1;

    if ((piece == WP || piece == BP) && std::abs(move.to() - move.from()) == 16) {
        en_passant = (move.to() + move.from()) / 2;
    }

    if (piece == WP || piece == BP || captured >= 0 || move.is_en_passant()) {
        halfmove_clock = 0;
    } else {
        halfmove_clock += 1;
    }

    if (side_to_move == BLACK) {
        fullmove_number += 1;
    }

    side_to_move ^= 1;

    position_history[position_history_count & POSITION_HISTORY_MASK] =
        undo.old_hash_key;
    position_history_count += 1;

    // Incremental Zobrist update.
    U64 h = undo.old_hash_key;

    h ^= ZOBRIST_PIECES[piece][move.from()];
    h ^= ZOBRIST_PIECES[placed_piece][move.to()];

    // captured and captured_square are always set together, so one test covers
    // both: -1/-1 for a quiet move, the victim and its square otherwise.
    if (captured >= 0) {
        h ^= ZOBRIST_PIECES[captured][captured_square];
    }

    if (move.is_castling()) {
        if (move.to() == 6) {
            h ^= ZOBRIST_PIECES[WR][7] ^ ZOBRIST_PIECES[WR][5];
        } else if (move.to() == 2) {
            h ^= ZOBRIST_PIECES[WR][0] ^ ZOBRIST_PIECES[WR][3];
        } else if (move.to() == 62) {
            h ^= ZOBRIST_PIECES[BR][63] ^ ZOBRIST_PIECES[BR][61];
        } else if (move.to() == 58) {
            h ^= ZOBRIST_PIECES[BR][56] ^ ZOBRIST_PIECES[BR][59];
        }
    }

    h ^= ZOBRIST_CASTLING[undo.old_castling];
    h ^= ZOBRIST_CASTLING[castling_rights];

    if (undo.old_en_passant >= 0) {
        h ^= ZOBRIST_EN_PASSANT_FILE[file_of(undo.old_en_passant)];
    }

    if (en_passant >= 0) {
        h ^= ZOBRIST_EN_PASSANT_FILE[file_of(en_passant)];
    }

    h ^= ZOBRIST_SIDE;

    hash_key = h;

    if (nnue::active()) nnue::on_make(undo, hash_key);

    assert_occupancy_sync();

    return undo;
}

void Board::unmake_move(const UndoInfo& undo) {
    const Move& move = undo.move;

    // hash_key is still the post-move key here; on_unmake reverses the feature
    // deltas before the board state below is restored.
    if (nnue::active()) nnue::on_unmake(undo, hash_key);

    side_to_move ^= 1;
    position_history_count -= 1;

    bitboards[undo.placed_piece] &= ~bit(move.to()) & FULL;
    mailbox[move.to()] = -1;

    bitboards[undo.moved_piece] |= bit(move.from());
    mailbox[move.from()] = undo.moved_piece;

    if (undo.captured_piece >= 0) {
        bitboards[undo.captured_piece] |= bit(undo.captured_square);
        mailbox[undo.captured_square] = undo.captured_piece;
    }

    U64 rook_delta = 0;

    if (move.is_castling()) {
        if (move.to() == 6) {
            bitboards[WR] &= ~bit(5) & FULL;
            bitboards[WR] |= bit(7);
            mailbox[5] = -1;
            mailbox[7] = WR;
            rook_delta = bit(5) | bit(7);
        } else if (move.to() == 2) {
            bitboards[WR] &= ~bit(3) & FULL;
            bitboards[WR] |= bit(0);
            mailbox[3] = -1;
            mailbox[0] = WR;
            rook_delta = bit(3) | bit(0);
        } else if (move.to() == 62) {
            bitboards[BR] &= ~bit(61) & FULL;
            bitboards[BR] |= bit(63);
            mailbox[61] = -1;
            mailbox[63] = BR;
            rook_delta = bit(61) | bit(63);
        } else if (move.to() == 58) {
            bitboards[BR] &= ~bit(59) & FULL;
            bitboards[BR] |= bit(56);
            mailbox[59] = -1;
            mailbox[56] = BR;
            rook_delta = bit(59) | bit(56);
        }
    }

    // Undo the occupancy edits. side_to_move was flipped back to the mover at
    // the top of this function, so these are exactly the XORs make_move
    // applied -- and an XOR is its own inverse.
    U64& occ_us = side_to_move == WHITE ? occ_white : occ_black;
    U64& occ_them = side_to_move == WHITE ? occ_black : occ_white;

    occ_us ^= bit(move.from()) | bit(move.to()) | rook_delta;

    if (undo.captured_piece >= 0) {
        occ_them ^= bit(undo.captured_square);
    }

    occ_all = occ_white | occ_black;

    castling_rights = undo.old_castling;
    en_passant = undo.old_en_passant;
    halfmove_clock = undo.old_halfmove_clock;
    fullmove_number = undo.old_fullmove_number;
    hash_key = undo.old_hash_key;

    assert_occupancy_sync();
}

NullMoveUndo Board::make_null_move() {
    NullMoveUndo undo;
    undo.old_side_to_move = side_to_move;
    undo.old_en_passant = en_passant;
    undo.old_halfmove_clock = halfmove_clock;
    undo.old_fullmove_number = fullmove_number;
    undo.old_hash_key = hash_key;

    en_passant = -1;
    halfmove_clock += 1;

    if (side_to_move == BLACK) {
        fullmove_number += 1;
    }

    side_to_move ^= 1;

    position_history[position_history_count & POSITION_HISTORY_MASK] =
        undo.old_hash_key;
    position_history_count += 1;

    // Incremental Zobrist update: only en passant and side change.
    U64 h = undo.old_hash_key;

    if (undo.old_en_passant >= 0) {
        h ^= ZOBRIST_EN_PASSANT_FILE[file_of(undo.old_en_passant)];
    }

    h ^= ZOBRIST_SIDE;

    hash_key = h;

    if (nnue::active()) nnue::note_hash(hash_key);

    return undo;
}

void Board::unmake_null_move(const NullMoveUndo& undo) {
    position_history_count -= 1;
    side_to_move = undo.old_side_to_move;
    en_passant = undo.old_en_passant;
    halfmove_clock = undo.old_halfmove_clock;
    fullmove_number = undo.old_fullmove_number;
    hash_key = undo.old_hash_key;

    if (nnue::active()) nnue::note_hash(hash_key);
}

bool Board::has_non_pawn_material(int colour) const {
    if (colour == WHITE) {
        return (bitboards[WN] | bitboards[WB] | bitboards[WR] | bitboards[WQ]) != 0;
    }

    return (bitboards[BN] | bitboards[BB] | bitboards[BR] | bitboards[BQ]) != 0;
}

void Board::update_castling_rights(int piece, const Move& move, int captured) {
    if (piece == WK) {
        castling_rights &= ~(CR_WK | CR_WQ);
    } else if (piece == BK) {
        castling_rights &= ~(CR_BK | CR_BQ);
    } else if (piece == WR) {
        if (move.from() == 0) {
            castling_rights &= ~CR_WQ;
        } else if (move.from() == 7) {
            castling_rights &= ~CR_WK;
        }
    } else if (piece == BR) {
        if (move.from() == 56) {
            castling_rights &= ~CR_BQ;
        } else if (move.from() == 63) {
            castling_rights &= ~CR_BK;
        }
    }

    if (captured == WR) {
        if (move.to() == 0) {
            castling_rights &= ~CR_WQ;
        } else if (move.to() == 7) {
            castling_rights &= ~CR_WK;
        }
    } else if (captured == BR) {
        if (move.to() == 56) {
            castling_rights &= ~CR_BQ;
        } else if (move.to() == 63) {
            castling_rights &= ~CR_BK;
        }
    }
}

void Board::print_board() const {
    for (int r = 7; r >= 0; --r) {
        for (int f = 0; f < 8; ++f) {
            std::optional<int> piece = piece_at(r * 8 + f);

            if (piece.has_value()) {
                std::cout << char_from_piece(*piece);
            } else {
                std::cout << '.';
            }

            std::cout << ' ';
        }

        std::cout << " " << r + 1 << '\n';
    }

    std::cout << "a b c d e f g h\n";
    std::cout << "side: " << (side_to_move == WHITE ? "white" : "black") << "\n";
}

long long perft(Board& board, int depth) {
    if (depth == 0) {
        return 1;
    }

    long long nodes = 0;

    for (const Move& move : board.generate_legal_moves()) {
        UndoInfo undo = board.make_move(move);
        nodes += perft(board, depth - 1);
        board.unmake_move(undo);
    }

    return nodes;
}

void divide(Board& board, int depth) {
    long long total = 0;

    for (const Move& move : board.generate_legal_moves()) {
        UndoInfo undo = board.make_move(move);
        long long nodes = perft(board, depth - 1);
        board.unmake_move(undo);

        total += nodes;
        std::cout << move_to_string(move) << ": " << nodes << "\n";
    }

    std::cout << "total: " << total << "\n";
}