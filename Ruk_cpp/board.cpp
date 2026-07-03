#include "board.hpp"
#include "nnue.hpp"

#include <algorithm>
#include <iostream>
#include <random>
#include <sstream>
#include <stdexcept>

const std::string PIECES = "PNBRQKpnbrqk";

const std::vector<int> KNIGHT_DELTAS = {17, 15, 10, 6, -17, -15, -10, -6};
const std::vector<int> KING_DELTAS = {8, -8, 1, -1, 9, 7, -9, -7};
const std::vector<int> BISHOP_DELTAS = {9, 7, -9, -7};
const std::vector<int> ROOK_DELTAS = {8, -8, 1, -1};
const std::vector<int> QUEEN_DELTAS = {9, 7, -9, -7, 8, -8, 1, -1};

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
    position_history.clear();

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
    en_passant = ep == "-" ? std::nullopt : std::optional<int>(square_index(ep));

    if (!(stream >> halfmove_clock)) {
        halfmove_clock = 0;
    }

    if (!(stream >> fullmove_number)) {
        fullmove_number = 1;
    }

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

    if (en_passant.has_value()) {
        key ^= ZOBRIST_EN_PASSANT_FILE[file_of(*en_passant)];
    }

    return key;
}

U64 Board::occupancy(std::optional<int> colour) const {
    if (colour.has_value() && *colour == WHITE) {
        return bitboards[WP] | bitboards[WN] | bitboards[WB] |
               bitboards[WR] | bitboards[WQ] | bitboards[WK];
    }

    if (colour.has_value() && *colour == BLACK) {
        return bitboards[BP] | bitboards[BN] | bitboards[BB] |
               bitboards[BR] | bitboards[BQ] | bitboards[BK];
    }

    U64 occ = 0;

    for (U64 bb : bitboards) {
        occ |= bb;
    }

    return occ;
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

U64 Board::attacks_from_slider(int sq, const std::vector<int>& deltas, U64 occ) const {
    // The delta set identifies the piece type; the lookup itself is magic-based.
    if (deltas.size() >= 8) {
        return bishop_attacks(sq, occ) | rook_attacks(sq, occ);   // queen
    }

    for (int delta : deltas) {
        int ad = delta < 0 ? -delta : delta;
        if (ad == 8 || ad == 1) {
            return rook_attacks(sq, occ);
        }
    }

    return bishop_attacks(sq, occ);
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
    int n = static_cast<int>(position_history.size());
    int limit = std::min(n, halfmove_clock);

    // Same side to move recurs every 2 plies; positions older than the last
    // irreversible move (pawn move / capture) can never repeat.
    for (int i = n - 2; i >= n - limit; i -= 2) {
        if (position_history[i] == hash_key) {
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

void Board::add_piece_moves(
    MoveList& moves,
    int piece,
    const std::vector<int>& deltas,
    U64 own,
    U64 occ
) {
    U64 bb = bitboards[piece];

    while (bb) {
        auto [sq, next] = pop_lsb(bb);
        bb = next;

        int them = piece <= WK ? BLACK : WHITE;
        U64 enemy_king = bitboards[them == WHITE ? WK : BK];
        U64 attacks = attacks_from_slider(sq, deltas, occ) & ~own & ~enemy_king & FULL;

        while (attacks) {
            auto [to_sq, next_attacks] = pop_lsb(attacks);
            attacks = next_attacks;
            moves.add(Move(sq, to_sq));
        }
    }
}

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

            for (int to_sq : {sq + 7, sq + 9}) {
                if (!on_board(to_sq)) {
                    continue;
                }

                if (std::abs(file_of(sq) - file_of(to_sq)) != 1) {
                    continue;
                }

                if (enemy & bit(to_sq)) {
                    add_pawn_move(moves, sq, to_sq, WHITE);
                } else if (en_passant.has_value() && *en_passant == to_sq) {
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

            for (int to_sq : {sq - 7, sq - 9}) {
                if (!on_board(to_sq)) {
                    continue;
                }

                if (std::abs(file_of(sq) - file_of(to_sq)) != 1) {
                    continue;
                }

                if (enemy & bit(to_sq)) {
                    add_pawn_move(moves, sq, to_sq, BLACK);
                } else if (en_passant.has_value() && *en_passant == to_sq) {
                    moves.add(Move(sq, to_sq, 0, MT_EP));
                }
            }
        }
    }

    add_knight_moves(moves, us == WHITE ? WN : BN, own);
    add_piece_moves(moves, us == WHITE ? WB : BB, BISHOP_DELTAS, own, occ);
    add_piece_moves(moves, us == WHITE ? WR : BR, ROOK_DELTAS, own, occ);
    add_piece_moves(moves, us == WHITE ? WQ : BQ, QUEEN_DELTAS, own, occ);
    add_king_moves(moves, us == WHITE ? WK : BK, own);

    add_castling_moves(moves);

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
    std::optional<int> piece_opt = piece_at(move.from());

    if (!piece_opt.has_value()) {
        throw std::runtime_error("no piece on source square");
    }

    int piece = *piece_opt;
    std::optional<int> captured = piece_at(move.to());
    std::optional<int> captured_square = captured.has_value()
        ? std::optional<int>(move.to())
        : std::nullopt;

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

    if (captured.has_value()) {
        bitboards[*captured] &= ~to_mask & FULL;
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

    if (move.is_castling()) {
        if (move.to() == 6) {
            bitboards[WR] &= ~bit(7) & FULL;
            bitboards[WR] |= bit(5);
            mailbox[7] = -1;
            mailbox[5] = WR;
        } else if (move.to() == 2) {
            bitboards[WR] &= ~bit(0) & FULL;
            bitboards[WR] |= bit(3);
            mailbox[0] = -1;
            mailbox[3] = WR;
        } else if (move.to() == 62) {
            bitboards[BR] &= ~bit(63) & FULL;
            bitboards[BR] |= bit(61);
            mailbox[63] = -1;
            mailbox[61] = BR;
        } else if (move.to() == 58) {
            bitboards[BR] &= ~bit(56) & FULL;
            bitboards[BR] |= bit(59);
            mailbox[56] = -1;
            mailbox[59] = BR;
        }
    }

    update_castling_rights(piece, move, captured);

    en_passant = std::nullopt;

    if ((piece == WP || piece == BP) && std::abs(move.to() - move.from()) == 16) {
        en_passant = (move.to() + move.from()) / 2;
    }

    if (piece == WP || piece == BP || captured.has_value() || move.is_en_passant()) {
        halfmove_clock = 0;
    } else {
        halfmove_clock += 1;
    }

    if (side_to_move == BLACK) {
        fullmove_number += 1;
    }

    side_to_move ^= 1;

    position_history.push_back(undo.old_hash_key);

    // Incremental Zobrist update.
    U64 h = undo.old_hash_key;

    h ^= ZOBRIST_PIECES[piece][move.from()];
    h ^= ZOBRIST_PIECES[placed_piece][move.to()];

    if (captured.has_value() && captured_square.has_value()) {
        h ^= ZOBRIST_PIECES[*captured][*captured_square];
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

    if (undo.old_en_passant.has_value()) {
        h ^= ZOBRIST_EN_PASSANT_FILE[file_of(*undo.old_en_passant)];
    }

    if (en_passant.has_value()) {
        h ^= ZOBRIST_EN_PASSANT_FILE[file_of(*en_passant)];
    }

    h ^= ZOBRIST_SIDE;

    hash_key = h;

    if (nnue::active()) nnue::on_make(undo, hash_key);

    return undo;
}

void Board::unmake_move(const UndoInfo& undo) {
    const Move& move = undo.move;

    // hash_key is still the post-move key here; on_unmake reverses the feature
    // deltas before the board state below is restored.
    if (nnue::active()) nnue::on_unmake(undo, hash_key);

    side_to_move ^= 1;
    position_history.pop_back();

    bitboards[undo.placed_piece] &= ~bit(move.to()) & FULL;
    mailbox[move.to()] = -1;

    bitboards[undo.moved_piece] |= bit(move.from());
    mailbox[move.from()] = undo.moved_piece;

    if (undo.captured_piece.has_value() && undo.captured_square.has_value()) {
        bitboards[*undo.captured_piece] |= bit(*undo.captured_square);
        mailbox[*undo.captured_square] = *undo.captured_piece;
    }

    if (move.is_castling()) {
        if (move.to() == 6) {
            bitboards[WR] &= ~bit(5) & FULL;
            bitboards[WR] |= bit(7);
            mailbox[5] = -1;
            mailbox[7] = WR;
        } else if (move.to() == 2) {
            bitboards[WR] &= ~bit(3) & FULL;
            bitboards[WR] |= bit(0);
            mailbox[3] = -1;
            mailbox[0] = WR;
        } else if (move.to() == 62) {
            bitboards[BR] &= ~bit(61) & FULL;
            bitboards[BR] |= bit(63);
            mailbox[61] = -1;
            mailbox[63] = BR;
        } else if (move.to() == 58) {
            bitboards[BR] &= ~bit(59) & FULL;
            bitboards[BR] |= bit(56);
            mailbox[59] = -1;
            mailbox[56] = BR;
        }
    }

    castling_rights = undo.old_castling;
    en_passant = undo.old_en_passant;
    halfmove_clock = undo.old_halfmove_clock;
    fullmove_number = undo.old_fullmove_number;
    hash_key = undo.old_hash_key;
}

NullMoveUndo Board::make_null_move() {
    NullMoveUndo undo;
    undo.old_side_to_move = side_to_move;
    undo.old_en_passant = en_passant;
    undo.old_halfmove_clock = halfmove_clock;
    undo.old_fullmove_number = fullmove_number;
    undo.old_hash_key = hash_key;

    en_passant = std::nullopt;
    halfmove_clock += 1;

    if (side_to_move == BLACK) {
        fullmove_number += 1;
    }

    side_to_move ^= 1;

    position_history.push_back(undo.old_hash_key);

    // Incremental Zobrist update: only en passant and side change.
    U64 h = undo.old_hash_key;

    if (undo.old_en_passant.has_value()) {
        h ^= ZOBRIST_EN_PASSANT_FILE[file_of(*undo.old_en_passant)];
    }

    h ^= ZOBRIST_SIDE;

    hash_key = h;

    if (nnue::active()) nnue::note_hash(hash_key);

    return undo;
}

void Board::unmake_null_move(const NullMoveUndo& undo) {
    position_history.pop_back();
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

void Board::update_castling_rights(
    int piece,
    const Move& move,
    std::optional<int> captured
) {
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

    if (captured.has_value() && *captured == WR) {
        if (move.to() == 0) {
            castling_rights &= ~CR_WQ;
        } else if (move.to() == 7) {
            castling_rights &= ~CR_WK;
        }
    } else if (captured.has_value() && *captured == BR) {
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