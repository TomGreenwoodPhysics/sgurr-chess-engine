import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest

import chess
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from records import Stats, pack, validate_source, score_to_cp, convert_plain
from large_conversion import Merge, add_binary_stats, stats_state, restore_stats, ranked_chunks
from test_pipeline import record, plain

CFG = dict(teacher_sigmoid_scale=361, runtime_scale=400, min_ply=0, max_abs_cp=2000, quiet_only=False)


class LargeConversionTest(unittest.TestCase):
    def test_vector_stats_match_board_reference_and_state_roundtrip(self):
        rng = np.random.default_rng(5)
        board = chess.Board()
        expected, actual = Stats(), Stats()
        data, scores = bytearray(), []
        for i in range(350):
            if board.is_game_over():
                board.reset()
            raw, result = int(rng.integers(-1500, 1501)), i % 3 - 1
            cp = score_to_cp(raw, 361)
            data.extend(pack(board, cp, result))
            scores.append(raw)
            expected.add(board, raw, cp, result)
            legal = list(board.legal_moves)
            board.push(legal[int(rng.integers(len(legal)))])
        add_binary_stats(actual, data, scores)
        for key in ('count', 'pieces', 'stm', 'results', 'phase', 'cp', 'scores', 'phase_scores'):
            self.assertEqual(getattr(expected, key), getattr(actual, key))
        for scale, value in expected.report()['calibration']['brier_by_teacher_scale'].items():
            self.assertAlmostEqual(value, actual.report()['calibration']['brier_by_teacher_scale'][scale], places=14)
        self.assertEqual(actual.report(), restore_stats(stats_state(actual)).report())

    def make_shard(self, root, name, records):
        path = root / (name + '.plain')
        path.write_text(''.join(plain(r) for r in records), encoding='ascii')
        directory = root / name
        report = convert_plain([path], directory, CFG, raw_scores=True)
        self.assertEqual(report, convert_plain([path], directory, CFG, raw_scores=True))
        return directory

    def test_global_duplicates_scores_and_interrupted_tail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            white = record(score='-257', result='-1')
            black = record(chess.STARTING_FEN.replace(' w ', ' b '), 'e7e5', '333', '1')
            board = chess.Board(); board.push_uci('e2e4')
            third = record(board.fen(), 'e7e5', '100', '0')
            first = self.make_shard(root, 'first', [white, white, black])
            second = self.make_shard(root, 'second', [black, third])
            output = root / 'merge'
            merge = Merge(output, {'test': True})
            merge.add({'index': 91}, first)
            # Simulate output and dedup writes from a shard that never commits.
            b, _, score, result, _ = validate_source(third)
            uncommitted = pack(b, score_to_cp(score, 361), result)
            merge.db.execute('INSERT INTO seen VALUES (?)', (uncommitted[:25],))
            merge.out.write(uncommitted)
            merge.close()
            with (output / 'train.bin.partial').open('ab') as f:
                f.write(b'interrupted uncommitted output')
            merge = Merge(output, {'test': True})
            self.assertEqual((output / 'train.bin.partial').stat().st_size, 64)
            merge.add({'index': 3}, second)
            self.assertEqual(merge.counts['train'], 3)
            self.assertEqual(merge.counts['source_records'], 5)
            self.assertEqual(merge.counts['duplicates'], 2)
            self.assertEqual(merge.counts['cross_chunk_duplicates'], 1)
            expected = Stats()
            for rec in (white, black, third):
                b, _, score, result, _ = validate_source(rec)
                expected.add(b, score, score_to_cp(score, 361), result)
            self.assertEqual(merge.stats.report(), expected.report())
            merge.close()
            self.assertEqual((output / 'train.bin.partial').stat().st_size, 96)
            # Previously committed data must not be silently accepted after edits.
            with (output / 'train.bin.partial').open('r+b') as f:
                f.write(b'corrupt')
            with self.assertRaisesRegex(RuntimeError, 'segment changed'):
                Merge(output, {'test': True})

    def test_seeded_rank_prefix_is_independent_of_worker_completion(self):
        chunks = [{'index': i} for i in range(100)]
        a = ranked_chunks(chunks, 20260906, 80)
        b = ranked_chunks(list(reversed(chunks)), 20260906, 80)
        self.assertEqual(a, b)
        self.assertEqual(a[:7], ranked_chunks(chunks, 20260906, 7))
        self.assertNotEqual(a[:7], chunks[:7])


if __name__ == '__main__':
    unittest.main()
