"""Optional integration against the pinned, separately built GPL executable."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import CACHE, read_json, sha256
from records import plain_records, stem_metadata, validate_source, independent_check, pack
from test_pipeline import record, plain
import chess


class OfficialConverterTest(unittest.TestCase):
    @unittest.skipUnless((CACHE / "tool-build.json").exists(), "Run tool-setup for optional official converter integration")
    def test_native_binpack_roundtrip(self):
        tool = CACHE / "stockfish_tool.exe"
        self.assertEqual(sha256(tool), read_json(CACHE / "tool-build.json")["binary_sha256"])
        records = [record(score="-257", result="-1"),
                   record(chess.STARTING_FEN.replace(" w ", " b "), "e7e5", score="513", result="1"),
                   record("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", "e1g1", score="-1", result="0")]
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "source.plain"
            packed, output = Path(tmp) / "test.binpack", Path(tmp) / "decoded.plain"
            src.write_text("".join(map(plain, records)), newline="\n")
            for a, b in ((src, packed), (packed, output)):
                result = subprocess.run([str(tool), "convert", str(a), str(b), "validate"], capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("Finished. Converted 3 positions", result.stdout, result.stdout + result.stderr)
            meta = stem_metadata(packed)
            self.assertEqual(meta, {"score": -257, "result": -1, "ply": 12, "rule50": 0})
            with output.open() as f:
                actual = list(plain_records(f))
            # Binpack reconstructs FEN fullmove from its stored ply field.
            expected = []
            for rec in records:
                fields = rec["fen"].split()
                fields[5] = str(int(rec["ply"]) // 2 + 1)
                expected.append({**rec, "fen": " ".join(fields)})
            self.assertEqual(actual, expected)
            for rec in actual:
                board, _, sc, res, _ = validate_source(rec)
                independent_check(rec, pack(board, sc, res))


if __name__ == "__main__":
    unittest.main()
