from __future__ import annotations

import random
from dataclasses import dataclass

WHITE, BLACK = 0, 1

PIECES = "PNBRQKpnbrqk"
WP, WN, WB, WR, WQ, WK, BP, BN, BB, BR, BQ, BK = range(12)

PIECE_FROM_CHAR = {c: i for i, c in enumerate(PIECES)}
CHAR_FROM_PIECE = {i: c for i, c in enumerate(PIECES)}

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

FILE_A = 0x0101010101010101
FILE_H = 0x8080808080808080
FULL = 0xFFFFFFFFFFFFFFFF

KNIGHT_DELTAS = [17, 15, 10, 6, -17, -15, -10, -6]
KING_DELTAS = [8, -8, 1, -1, 9, 7, -9, -7]
BISHOP_DELTAS = [9, 7, -9, -7]
ROOK_DELTAS = [8, -8, 1, -1]
QUEEN_DELTAS = BISHOP_DELTAS + ROOK_DELTAS

PIECE_VALUE = {
    WP: 100, WN: 320, WB: 330, WR: 500, WQ: 900, WK: 0,
    BP: 100, BN: 320, BB: 330, BR: 500, BQ: 900, BK: 0,
}

PAWN_PST = [
     0,   0,   0,   0,   0,   0,   0,   0,
     0,   2,   4, -10, -10,   4,   2,   0,
     2,   2,   6,  10,  10,   6,   2,   2,
     4,   4,  10,  22,  22,  10,   4,   4,
     8,   8,  16,  28,  28,  16,   8,   8,
    16,  16,  24,  32,  32,  24,  16,  16,
    45,  45,  45,  45,  45,  45,  45,  45,
     0,   0,   0,   0,   0,   0,   0,   0,
]

KNIGHT_PST = [
   -50, -30, -20, -15, -15, -20, -30, -50,
   -25, -12,   0,   5,   5,   0, -12, -25,
   -15,   8,  18,  22,  22,  18,   8, -15,
   -10,  10,  25,  32,  32,  25,  10, -10,
   -10,  12,  28,  35,  35,  28,  12, -10,
   -15,  10,  20,  28,  28,  20,  10, -15,
   -20, -10,   8,  12,  12,   8, -10, -20,
   -45, -25, -15, -10, -10, -15, -25, -45,
]

BISHOP_PST = [
   -20, -10, -15, -10, -10, -15, -10, -20,
   -10,  12,   8,   8,   8,   8,  12, -10,
   -10,  16,  14,  16,  16,  14,  16, -10,
   -10,  10,  18,  22,  22,  18,  10, -10,
   -10,   8,  18,  22,  22,  18,   8, -10,
   -10,  10,  14,  18,  18,  14,  10, -10,
   -10,   8,   4,   8,   8,   4,   8, -10,
   -20, -10, -10, -10, -10, -10, -10, -20,
]

ROOK_PST = [
     0,   0,   4,   8,   8,   4,   0,   0,
    12,  16,  16,  20,  20,  16,  16,  12,
    -4,   0,   4,   8,   8,   4,   0,  -4,
    -8,  -4,   0,   4,   4,   0,  -4,  -8,
    -8,  -4,   0,   4,   4,   0,  -4,  -8,
    -8,  -4,   0,   4,   4,   0,  -4,  -8,
    -4,   0,   4,   8,   8,   4,   0,  -4,
     0,   0,   4,   8,   8,   4,   0,   0,
]

QUEEN_PST = [
   -20, -10, -10,  -5,  -5, -10, -10, -20,
   -10,   0,   8,   4,   4,   4,   0, -10,
   -10,   8,   8,   8,   8,   8,   4, -10,
     0,   4,   8,  10,  10,   8,   4,  -5,
    -5,   4,   8,  10,  10,   8,   4,  -5,
   -10,   4,   8,   8,   8,   8,   4, -10,
   -10,   0,   4,   4,   4,   4,   0, -10,
   -20, -10, -10,  -5,  -5, -10, -10, -20,
]

KING_PST = [
    40,  50,  30,   0,   0,  30,  50,  40,
    30,  40,  20,   0,   0,  20,  40,  30,
    10,  10, -10, -20, -20, -10,  10,  10,
   -20, -20, -30, -40, -40, -30, -20, -20,
   -30, -30, -40, -50, -50, -40, -30, -30,
   -30, -30, -40, -50, -50, -40, -30, -30,
   -30, -30, -40, -50, -50, -40, -30, -30,
   -30, -30, -40, -50, -50, -40, -30, -30,
]

PIECE_SQUARE_TABLE = [
    PAWN_PST,
    KNIGHT_PST,
    BISHOP_PST,
    ROOK_PST,
    QUEEN_PST,
    KING_PST,
]


TT_RANDOM = random.Random(123456789)

ZOBRIST_PIECES = [
    [TT_RANDOM.getrandbits(64) for _ in range(64)]
    for _ in range(12)
]

ZOBRIST_SIDE = TT_RANDOM.getrandbits(64)

ZOBRIST_CASTLING = [
    TT_RANDOM.getrandbits(64)
    for _ in range(16)
]

ZOBRIST_EN_PASSANT_FILE = [
    TT_RANDOM.getrandbits(64)
    for _ in range(8)
]


def castling_index(castling: str) -> int:
    index = 0

    if "K" in castling:
        index |= 1
    if "Q" in castling:
        index |= 2
    if "k" in castling:
        index |= 4
    if "q" in castling:
        index |= 8

    return index


@dataclass(frozen=True)
class Move:
    from_sq: int
    to_sq: int
    promotion: int | None = None
    is_en_passant: bool = False
    is_castling: bool = False

    def __str__(self) -> str:
        text = square_name(self.from_sq) + square_name(self.to_sq)
        if self.promotion is not None:
            text += CHAR_FROM_PIECE[self.promotion].lower()
        return text


@dataclass(frozen=True)
class UndoInfo:
    move: Move
    moved_piece: int
    placed_piece: int
    captured_piece: int | None
    captured_square: int | None
    old_castling: str
    old_en_passant: int | None
    old_halfmove_clock: int
    old_fullmove_number: int
    old_hash_key: int


@dataclass(frozen=True)
class NullMoveUndo:
    old_side_to_move: int
    old_en_passant: int | None
    old_halfmove_clock: int
    old_fullmove_number: int
    old_hash_key: int


def bit(sq: int) -> int:
    return 1 << sq


def rank_of(sq: int) -> int:
    return sq // 8


def file_of(sq: int) -> int:
    return sq % 8


def square_name(sq: int) -> str:
    return chr(ord("a") + file_of(sq)) + str(rank_of(sq) + 1)


def square_index(name: str) -> int:
    return (int(name[1]) - 1) * 8 + (ord(name[0]) - ord("a"))


def mirror_square(sq: int) -> int:
    return sq ^ 56


def pop_lsb(bb: int) -> tuple[int, int]:
    lsb = bb & -bb
    sq = lsb.bit_length() - 1
    return sq, bb ^ lsb


def on_board(sq: int) -> bool:
    return 0 <= sq < 64


def same_row_or_col_or_diag(a: int, b: int, delta: int) -> bool:
    af, bf = file_of(a), file_of(b)
    ar, br = rank_of(a), rank_of(b)

    if delta in (1, -1):
        return ar == br
    if delta in (8, -8):
        return af == bf

    return abs(af - bf) == abs(ar - br)


def step_ok(a: int, b: int, delta: int) -> bool:
    if not on_board(b):
        return False
    return same_row_or_col_or_diag(a, b, delta)


class Board:
    def __init__(self, fen: str = START_FEN):
        self.bitboards = [0] * 12
        self.side_to_move = WHITE
        self.castling = ""
        self.en_passant: int | None = None
        self.halfmove_clock = 0
        self.fullmove_number = 1
        self.set_fen(fen)

    def copy(self) -> "Board":
        new = Board.__new__(Board)
        new.bitboards = self.bitboards.copy()
        new.side_to_move = self.side_to_move
        new.castling = self.castling
        new.en_passant = self.en_passant
        new.halfmove_clock = self.halfmove_clock
        new.fullmove_number = self.fullmove_number
        new.hash_key = self.hash_key
        return new

    def set_fen(self, fen: str) -> None:
        parts = fen.split()
        placement, side, castling, ep = parts[:4]

        self.bitboards = [0] * 12

        rank = 7
        file = 0

        for char in placement:
            if char == "/":
                rank -= 1
                file = 0
            elif char.isdigit():
                file += int(char)
            else:
                sq = rank * 8 + file
                self.bitboards[PIECE_FROM_CHAR[char]] |= bit(sq)
                file += 1

        self.side_to_move = WHITE if side == "w" else BLACK
        self.castling = "" if castling == "-" else castling
        self.en_passant = None if ep == "-" else square_index(ep)
        self.halfmove_clock = int(parts[4]) if len(parts) > 4 else 0
        self.fullmove_number = int(parts[5]) if len(parts) > 5 else 1
        self.hash_key = self.compute_hash()

    def compute_hash(self) -> int:
        hash_key = 0

        for piece, bb in enumerate(self.bitboards):
            while bb:
                sq, bb = pop_lsb(bb)
                hash_key ^= ZOBRIST_PIECES[piece][sq]

        if self.side_to_move == BLACK:
            hash_key ^= ZOBRIST_SIDE

        hash_key ^= ZOBRIST_CASTLING[castling_index(self.castling)]

        if self.en_passant is not None:
            hash_key ^= ZOBRIST_EN_PASSANT_FILE[file_of(self.en_passant)]

        return hash_key

    def occupancy(self, colour: int | None = None) -> int:
        if colour == WHITE:
            return (
                self.bitboards[WP]
                | self.bitboards[WN]
                | self.bitboards[WB]
                | self.bitboards[WR]
                | self.bitboards[WQ]
                | self.bitboards[WK]
            )

        if colour == BLACK:
            return (
                self.bitboards[BP]
                | self.bitboards[BN]
                | self.bitboards[BB]
                | self.bitboards[BR]
                | self.bitboards[BQ]
                | self.bitboards[BK]
            )

        occ = 0
        for bb in self.bitboards:
            occ |= bb
        return occ

    def piece_at(self, sq: int) -> int | None:
        mask = bit(sq)

        for piece, bb in enumerate(self.bitboards):
            if bb & mask:
                return piece

        return None

    def king_square(self, colour: int) -> int:
        king = WK if colour == WHITE else BK
        bb = self.bitboards[king]

        if bb == 0:
            return -1

        return bb.bit_length() - 1

    def attacks_from_slider(self, sq: int, deltas: list[int], occ: int) -> int:
        attacks = 0

        for delta in deltas:
            cur = sq

            while True:
                nxt = cur + delta

                if not step_ok(cur, nxt, delta):
                    break

                attacks |= bit(nxt)

                if occ & bit(nxt):
                    break

                cur = nxt

        return attacks

    def knight_attacks(self, sq: int) -> int:
        attacks = 0

        for delta in KNIGHT_DELTAS:
            nxt = sq + delta

            if on_board(nxt) and max(
                abs(file_of(sq) - file_of(nxt)),
                abs(rank_of(sq) - rank_of(nxt)),
            ) == 2:
                attacks |= bit(nxt)

        return attacks

    def king_attacks(self, sq: int) -> int:
        attacks = 0

        for delta in KING_DELTAS:
            nxt = sq + delta

            if on_board(nxt) and max(
                abs(file_of(sq) - file_of(nxt)),
                abs(rank_of(sq) - rank_of(nxt)),
            ) == 1:
                attacks |= bit(nxt)

        return attacks

    def pawn_attacks_from(self, sq: int, colour: int) -> int:
        attacks = 0

        if colour == WHITE:
            deltas = (7, 9)
        else:
            deltas = (-7, -9)

        for delta in deltas:
            nxt = sq + delta

            if on_board(nxt) and abs(file_of(sq) - file_of(nxt)) == 1:
                attacks |= bit(nxt)

        return attacks

    def is_square_attacked(self, sq: int, by_colour: int) -> bool:
        occ = self.occupancy()

        pawns = self.bitboards[WP if by_colour == WHITE else BP]
        while pawns:
            psq, pawns = pop_lsb(pawns)
            if self.pawn_attacks_from(psq, by_colour) & bit(sq):
                return True

        knights = self.bitboards[WN if by_colour == WHITE else BN]
        while knights:
            nsq, knights = pop_lsb(knights)
            if self.knight_attacks(nsq) & bit(sq):
                return True

        bishops = (
            self.bitboards[WB if by_colour == WHITE else BB]
            | self.bitboards[WQ if by_colour == WHITE else BQ]
        )
        while bishops:
            bsq, bishops = pop_lsb(bishops)
            if self.attacks_from_slider(bsq, BISHOP_DELTAS, occ) & bit(sq):
                return True

        rooks = (
            self.bitboards[WR if by_colour == WHITE else BR]
            | self.bitboards[WQ if by_colour == WHITE else BQ]
        )
        while rooks:
            rsq, rooks = pop_lsb(rooks)
            if self.attacks_from_slider(rsq, ROOK_DELTAS, occ) & bit(sq):
                return True

        king = self.king_square(by_colour)
        return king != -1 and bool(self.king_attacks(king) & bit(sq))

    def in_check(self, colour: int) -> bool:
        king = self.king_square(colour)
        return self.is_square_attacked(king, colour ^ 1)

    def generate_pseudo_legal_moves(self) -> list[Move]:
        moves: list[Move] = []

        us = self.side_to_move
        them = us ^ 1

        own = self.occupancy(us)
        enemy = self.occupancy(them)
        occ = own | enemy

        if us == WHITE:
            pawns = self.bitboards[WP]

            while pawns:
                sq, pawns = pop_lsb(pawns)

                one = sq + 8
                if on_board(one) and not (occ & bit(one)):
                    self.add_pawn_move(moves, sq, one, WHITE)

                    two = sq + 16
                    if rank_of(sq) == 1 and not (occ & bit(two)):
                        moves.append(Move(sq, two))

                for to_sq in (sq + 7, sq + 9):
                    if not on_board(to_sq):
                        continue

                    if abs(file_of(sq) - file_of(to_sq)) != 1:
                        continue

                    if enemy & bit(to_sq):
                        self.add_pawn_move(moves, sq, to_sq, WHITE)
                    elif self.en_passant == to_sq:
                        moves.append(Move(sq, to_sq, is_en_passant=True))

        else:
            pawns = self.bitboards[BP]

            while pawns:
                sq, pawns = pop_lsb(pawns)

                one = sq - 8
                if on_board(one) and not (occ & bit(one)):
                    self.add_pawn_move(moves, sq, one, BLACK)

                    two = sq - 16
                    if rank_of(sq) == 6 and not (occ & bit(two)):
                        moves.append(Move(sq, two))

                for to_sq in (sq - 7, sq - 9):
                    if not on_board(to_sq):
                        continue

                    if abs(file_of(sq) - file_of(to_sq)) != 1:
                        continue

                    if enemy & bit(to_sq):
                        self.add_pawn_move(moves, sq, to_sq, BLACK)
                    elif self.en_passant == to_sq:
                        moves.append(Move(sq, to_sq, is_en_passant=True))

        self.add_piece_moves(moves, WN if us == WHITE else BN, ["knight"], own, occ)
        self.add_piece_moves(moves, WB if us == WHITE else BB, BISHOP_DELTAS, own, occ)
        self.add_piece_moves(moves, WR if us == WHITE else BR, ROOK_DELTAS, own, occ)
        self.add_piece_moves(moves, WQ if us == WHITE else BQ, QUEEN_DELTAS, own, occ)
        self.add_piece_moves(moves, WK if us == WHITE else BK, ["king"], own, occ)

        self.add_castling_moves(moves)

        return moves

    def add_pawn_move(
        self,
        moves: list[Move],
        from_sq: int,
        to_sq: int,
        colour: int,
    ) -> None:
        promotion_rank = 7 if colour == WHITE else 0

        if rank_of(to_sq) == promotion_rank:
            pieces = (WQ, WR, WB, WN) if colour == WHITE else (BQ, BR, BB, BN)

            for promo in pieces:
                moves.append(Move(from_sq, to_sq, promotion=promo))

        else:
            moves.append(Move(from_sq, to_sq))

    def add_piece_moves(
        self,
        moves: list[Move],
        piece: int,
        kind: list,
        own: int,
        occ: int,
    ) -> None:
        bb = self.bitboards[piece]

        while bb:
            sq, bb = pop_lsb(bb)

            if kind == ["knight"]:
                attacks = self.knight_attacks(sq)
            elif kind == ["king"]:
                attacks = self.king_attacks(sq)
            else:
                attacks = self.attacks_from_slider(sq, kind, occ)

            attacks &= ~own & FULL

            while attacks:
                to_sq, attacks = pop_lsb(attacks)
                moves.append(Move(sq, to_sq))

    def add_castling_moves(self, moves: list[Move]) -> None:
        us = self.side_to_move
        occ = self.occupancy()

        if us == WHITE:
            if "K" in self.castling and not (occ & (bit(5) | bit(6))):
                if (
                    not self.in_check(WHITE)
                    and not self.is_square_attacked(5, BLACK)
                    and not self.is_square_attacked(6, BLACK)
                ):
                    moves.append(Move(4, 6, is_castling=True))

            if "Q" in self.castling and not (occ & (bit(1) | bit(2) | bit(3))):
                if (
                    not self.in_check(WHITE)
                    and not self.is_square_attacked(3, BLACK)
                    and not self.is_square_attacked(2, BLACK)
                ):
                    moves.append(Move(4, 2, is_castling=True))

        else:
            if "k" in self.castling and not (occ & (bit(61) | bit(62))):
                if (
                    not self.in_check(BLACK)
                    and not self.is_square_attacked(61, WHITE)
                    and not self.is_square_attacked(62, WHITE)
                ):
                    moves.append(Move(60, 62, is_castling=True))

            if "q" in self.castling and not (occ & (bit(57) | bit(58) | bit(59))):
                if (
                    not self.in_check(BLACK)
                    and not self.is_square_attacked(59, WHITE)
                    and not self.is_square_attacked(58, WHITE)
                ):
                    moves.append(Move(60, 58, is_castling=True))

    def generate_legal_moves(self) -> list[Move]:
        legal = []
        us = self.side_to_move

        for move in self.generate_pseudo_legal_moves():
            undo = self.make_move(move)

            if not self.in_check(us):
                legal.append(move)

            self.unmake_move(undo)

        return legal

    def make_move(self, move: Move) -> UndoInfo:
        piece = self.piece_at(move.from_sq)

        if piece is None:
            raise ValueError(f"no piece on {square_name(move.from_sq)}")

        captured = self.piece_at(move.to_sq)
        captured_square = move.to_sq if captured is not None else None

        old_castling = self.castling
        old_en_passant = self.en_passant
        old_halfmove_clock = self.halfmove_clock
        old_fullmove_number = self.fullmove_number
        old_hash_key = self.hash_key

        self.hash_key ^= ZOBRIST_CASTLING[castling_index(old_castling)]

        if old_en_passant is not None:
            self.hash_key ^= ZOBRIST_EN_PASSANT_FILE[file_of(old_en_passant)]

        from_mask = bit(move.from_sq)
        to_mask = bit(move.to_sq)

        self.bitboards[piece] &= ~from_mask & FULL
        self.hash_key ^= ZOBRIST_PIECES[piece][move.from_sq]

        if captured is not None:
            self.bitboards[captured] &= ~to_mask & FULL
            self.hash_key ^= ZOBRIST_PIECES[captured][move.to_sq]

        if move.is_en_passant:
            captured_square = move.to_sq - 8 if self.side_to_move == WHITE else move.to_sq + 8
            captured = BP if self.side_to_move == WHITE else WP

            self.bitboards[captured] &= ~bit(captured_square) & FULL
            self.hash_key ^= ZOBRIST_PIECES[captured][captured_square]

        placed_piece = move.promotion if move.promotion is not None else piece

        self.bitboards[placed_piece] |= to_mask
        self.hash_key ^= ZOBRIST_PIECES[placed_piece][move.to_sq]

        if move.is_castling:
            if move.to_sq == 6:
                self.bitboards[WR] &= ~bit(7) & FULL
                self.bitboards[WR] |= bit(5)

                self.hash_key ^= ZOBRIST_PIECES[WR][7]
                self.hash_key ^= ZOBRIST_PIECES[WR][5]

            elif move.to_sq == 2:
                self.bitboards[WR] &= ~bit(0) & FULL
                self.bitboards[WR] |= bit(3)

                self.hash_key ^= ZOBRIST_PIECES[WR][0]
                self.hash_key ^= ZOBRIST_PIECES[WR][3]

            elif move.to_sq == 62:
                self.bitboards[BR] &= ~bit(63) & FULL
                self.bitboards[BR] |= bit(61)

                self.hash_key ^= ZOBRIST_PIECES[BR][63]
                self.hash_key ^= ZOBRIST_PIECES[BR][61]

            elif move.to_sq == 58:
                self.bitboards[BR] &= ~bit(56) & FULL
                self.bitboards[BR] |= bit(59)

                self.hash_key ^= ZOBRIST_PIECES[BR][56]
                self.hash_key ^= ZOBRIST_PIECES[BR][59]

        self.update_castling_rights(piece, move, captured)

        self.en_passant = None

        if piece in (WP, BP) and abs(move.to_sq - move.from_sq) == 16:
            self.en_passant = (move.to_sq + move.from_sq) // 2

        self.hash_key ^= ZOBRIST_CASTLING[castling_index(self.castling)]

        if self.en_passant is not None:
            self.hash_key ^= ZOBRIST_EN_PASSANT_FILE[file_of(self.en_passant)]

        self.hash_key ^= ZOBRIST_SIDE

        if piece in (WP, BP) or captured is not None or move.is_en_passant:
            self.halfmove_clock = 0
        else:
            self.halfmove_clock += 1

        if self.side_to_move == BLACK:
            self.fullmove_number += 1

        self.side_to_move ^= 1

        return UndoInfo(
            move=move,
            moved_piece=piece,
            placed_piece=placed_piece,
            captured_piece=captured,
            captured_square=captured_square,
            old_castling=old_castling,
            old_en_passant=old_en_passant,
            old_halfmove_clock=old_halfmove_clock,
            old_fullmove_number=old_fullmove_number,
            old_hash_key=old_hash_key,
        )

    def unmake_move(self, undo: UndoInfo) -> None:
        move = undo.move

        self.side_to_move ^= 1

        self.bitboards[undo.placed_piece] &= ~bit(move.to_sq) & FULL
        self.bitboards[undo.moved_piece] |= bit(move.from_sq)

        if undo.captured_piece is not None and undo.captured_square is not None:
            self.bitboards[undo.captured_piece] |= bit(undo.captured_square)

        if move.is_castling:
            if move.to_sq == 6:
                self.bitboards[WR] &= ~bit(5) & FULL
                self.bitboards[WR] |= bit(7)
            elif move.to_sq == 2:
                self.bitboards[WR] &= ~bit(3) & FULL
                self.bitboards[WR] |= bit(0)
            elif move.to_sq == 62:
                self.bitboards[BR] &= ~bit(61) & FULL
                self.bitboards[BR] |= bit(63)
            elif move.to_sq == 58:
                self.bitboards[BR] &= ~bit(59) & FULL
                self.bitboards[BR] |= bit(56)

        self.castling = undo.old_castling
        self.en_passant = undo.old_en_passant
        self.halfmove_clock = undo.old_halfmove_clock
        self.fullmove_number = undo.old_fullmove_number
        self.hash_key = undo.old_hash_key

    def make_null_move(self) -> NullMoveUndo:
        undo = NullMoveUndo(
            old_side_to_move=self.side_to_move,
            old_en_passant=self.en_passant,
            old_halfmove_clock=self.halfmove_clock,
            old_fullmove_number=self.fullmove_number,
            old_hash_key=self.hash_key,
        )

        if self.en_passant is not None:
            self.hash_key ^= ZOBRIST_EN_PASSANT_FILE[file_of(self.en_passant)]

        self.en_passant = None
        self.halfmove_clock += 1

        if self.side_to_move == BLACK:
            self.fullmove_number += 1

        self.side_to_move ^= 1
        self.hash_key ^= ZOBRIST_SIDE

        return undo

    def unmake_null_move(self, undo: NullMoveUndo) -> None:
        self.side_to_move = undo.old_side_to_move
        self.en_passant = undo.old_en_passant
        self.halfmove_clock = undo.old_halfmove_clock
        self.fullmove_number = undo.old_fullmove_number
        self.hash_key = undo.old_hash_key

    def has_non_pawn_material(self, colour: int) -> bool:
        if colour == WHITE:
            return bool(
                self.bitboards[WN]
                | self.bitboards[WB]
                | self.bitboards[WR]
                | self.bitboards[WQ]
            )

        return bool(
            self.bitboards[BN]
            | self.bitboards[BB]
            | self.bitboards[BR]
            | self.bitboards[BQ]
        )

    def update_castling_rights(
        self,
        piece: int,
        move: Move,
        captured: int | None,
    ) -> None:
        rights = self.castling

        if piece == WK:
            rights = rights.replace("K", "").replace("Q", "")
        elif piece == BK:
            rights = rights.replace("k", "").replace("q", "")
        elif piece == WR:
            if move.from_sq == 0:
                rights = rights.replace("Q", "")
            elif move.from_sq == 7:
                rights = rights.replace("K", "")
        elif piece == BR:
            if move.from_sq == 56:
                rights = rights.replace("q", "")
            elif move.from_sq == 63:
                rights = rights.replace("k", "")

        if captured == WR:
            if move.to_sq == 0:
                rights = rights.replace("Q", "")
            elif move.to_sq == 7:
                rights = rights.replace("K", "")
        elif captured == BR:
            if move.to_sq == 56:
                rights = rights.replace("q", "")
            elif move.to_sq == 63:
                rights = rights.replace("k", "")

        self.castling = rights

    def evaluate(self) -> int:
        score = 0

        for piece, bb in enumerate(self.bitboards):
            if piece <= WK:
                pst = PIECE_SQUARE_TABLE[piece]
                value = PIECE_VALUE[piece]

                while bb:
                    sq, bb = pop_lsb(bb)
                    score += value + pst[sq]
            else:
                pst = PIECE_SQUARE_TABLE[piece - 6]
                value = PIECE_VALUE[piece]

                while bb:
                    sq, bb = pop_lsb(bb)
                    score -= value + pst[mirror_square(sq)]

        return score if self.side_to_move == WHITE else -score

    def print_board(self) -> None:
        for r in range(7, -1, -1):
            row = []

            for f in range(8):
                piece = self.piece_at(r * 8 + f)
                row.append("." if piece is None else CHAR_FROM_PIECE[piece])

            print(" ".join(row), " ", r + 1)

        print("a b c d e f g h")
        print("side:", "white" if self.side_to_move == WHITE else "black")


def perft(board: Board, depth: int) -> int:
    if depth == 0:
        return 1

    nodes = 0

    for move in board.generate_legal_moves():
        undo = board.make_move(move)
        nodes += perft(board, depth - 1)
        board.unmake_move(undo)

    return nodes


def divide(board: Board, depth: int) -> None:
    total = 0

    for move in board.generate_legal_moves():
        undo = board.make_move(move)
        nodes = perft(board, depth - 1)
        board.unmake_move(undo)
        total += nodes
        print(f"{move}: {nodes}")

    print("total:", total)


def test_make_unmake() -> None:
    board = Board()

    for move in board.generate_legal_moves():
        old_bitboards = board.bitboards.copy()
        old_side = board.side_to_move
        old_castling = board.castling
        old_ep = board.en_passant
        old_halfmove = board.halfmove_clock
        old_fullmove = board.fullmove_number
        old_hash = board.hash_key

        undo = board.make_move(move)
        board.unmake_move(undo)

        assert board.bitboards == old_bitboards
        assert board.side_to_move == old_side
        assert board.castling == old_castling
        assert board.en_passant == old_ep
        assert board.halfmove_clock == old_halfmove
        assert board.fullmove_number == old_fullmove
        assert board.hash_key == old_hash
        assert board.compute_hash() == old_hash

    print("make/unmake test passed")


def test_incremental_hash() -> None:
    board = Board()

    for move in board.generate_legal_moves():
        child = board.copy()
        child.make_move(move)

        recomputed = child.compute_hash()

        if child.hash_key != recomputed:
            print("hash mismatch after move:", move)
            print("incremental:", child.hash_key)
            print("recomputed:  ", recomputed)
            raise AssertionError("incremental hash does not match recomputed hash")

    print("incremental hash test passed")


def test_null_move() -> None:
    board = Board()
    old_hash = board.hash_key
    old_eval = board.evaluate()

    undo = board.make_null_move()
    assert board.side_to_move == BLACK
    assert board.en_passant is None
    assert board.hash_key == board.compute_hash()

    board.unmake_null_move(undo)
    assert board.side_to_move == WHITE
    assert board.hash_key == old_hash
    assert board.evaluate() == old_eval
    assert board.hash_key == board.compute_hash()

    print("null move test passed")


def test_evaluation_and_perft() -> None:
    board = Board()
    assert board.evaluate() == 0

    board.make_move(Move(square_index("e2"), square_index("e4")))
    e4_eval = board.evaluate()
    assert e4_eval < 0, f"expected e2e4 to favour White, got {e4_eval}"

    board = Board()
    expected = {1: 20, 2: 400, 3: 8902, 4: 197281}

    for depth, nodes in expected.items():
        actual = perft(board, depth)
        assert actual == nodes, f"perft({depth}) = {actual}, expected {nodes}"

    print(f"evaluation test passed, e2e4 score for black to move: {e4_eval}")
    print("perft test passed")


if __name__ == "__main__":
    board = Board()
    board.print_board()

    test_incremental_hash()
    test_make_unmake()
    test_null_move()
    test_evaluation_and_perft()
