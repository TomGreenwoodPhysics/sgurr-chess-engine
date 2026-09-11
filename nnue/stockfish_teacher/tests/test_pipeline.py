import contextlib
import io
import json
import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import download, sha256, atomic_json, lock
from records import (pack, unpack, plain_records, validate_source, score_to_cp,
                     chunk_index, select_chunks, group_split, convert_plain, independent_check)
import chess


def record(fen=chess.STARTING_FEN, move="e2e4", score="-257", result="-1", game=None):
    r = dict(fen=fen, move=move, score=score, result=result, ply="12")
    if game is not None:
        r["game"] = game
    return r


def plain(rec):
    return "".join(f"{k} {v}\n" for k, v in rec.items()) + "e\n"


class RecordsTest(unittest.TestCase):
    def test_bytes_known_position(self):
        b = chess.Board("4k3/8/8/8/8/8/P7/4K3 b - - 0 1")
        r = pack(b, -257, 1)
        self.assertEqual(len(r), 32)
        self.assertEqual(r[:8], struct.pack("<Q", (1 << 4) | (1 << 8) | (1 << 60)))
        self.assertEqual(r[8:10], b"\x05\x0b")
        self.assertEqual(r[24:], b"\x01\xff\xfe\x02\x00\x00\x00\x00")
        self.assertEqual(unpack(r)[0].piece_map(), b.piece_map())

    def test_both_score_and_result_perspectives(self):
        for fen, move in [(chess.STARTING_FEN, "e2e4"), (chess.STARTING_FEN.replace(" w ", " b "), "e7e5")]:
            for score in (-257, 0, 257):
                for result in (-1, 0, 1):
                    rec = record(fen, move, str(score), str(result))
                    b, _, sc, res, _ = validate_source(rec)
                    r = pack(b, sc, res)
                    self.assertEqual(unpack(r)[1:], (score, result))
                    independent_check(rec, r)

    def test_special_moves(self):
        for fen, move in [("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", "e1g1"),
                          ("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2", "e5d6"),
                          ("7k/P7/8/8/8/8/8/K7 w - - 0 1", "a7a8q")]:
            b, m, *_ = validate_source(record(fen, move))
            self.assertIn(m, b.legal_moves)
            independent_check(record(fen, move), pack(b, 5, 0))

    def test_reject_invalid_position_and_labels(self):
        for rec in [record("8/8/8/8/8/8/8/8 w - - 0 1"), record(result="2"),
                    record(score="32768"), record(move="e2e5"),
                    record("8/8/8/8/8/8/4k3/4K3 w - - 0 1", "e1d1")]:
            with self.assertRaises(ValueError):
                validate_source(rec)

    def test_strict_plain(self):
        self.assertEqual(list(plain_records(io.StringIO(plain(record())))), [record()])
        for text in (plain(record())[:-2], "fen x\nfen y\ne\n", "fen x\ne\n", "unexpected x\n"):
            with self.assertRaises(ValueError):
                list(plain_records(io.StringIO(text)))

    def test_invalid_binary(self):
        r = bytearray(pack(chess.Board(), 0, 0))
        for offset, value in [(24, 2), (27, 255), (28, 1), (8, 255)]:
            altered = r.copy(); altered[offset] = value
            with self.assertRaises(ValueError):
                unpack(altered)
        with self.assertRaises(ValueError):
            unpack(bytes(31))

    def test_score_scale_and_splits(self):
        self.assertEqual(score_to_cp(361, 361), 400)
        self.assertEqual(score_to_cp(-361, 361), -400)
        self.assertEqual(score_to_cp(400, 400), 400)
        for scale in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                score_to_cp(100, scale)
        with self.assertRaises(ValueError):
            group_split(None, 0, .1)
        self.assertEqual(group_split("game123", 7, .1), group_split("game123", 7, .1))
        self.assertEqual({group_split(str(i), 7, .5) for i in range(30)}, {"train", "val"})

    def test_chunk_sampler_all_file_not_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "fixture.binpack"
            p.write_bytes((b"BINP" + struct.pack("<I", 34) + bytes(34)) * 100)
            index = chunk_index(p)
            a = select_chunks(index, 20260906, 8)
            self.assertEqual(a, select_chunks(index, 20260906, 8))
            self.assertNotEqual(a, index[:8])
            self.assertGreater(a[-1]["index"], 50)
            p.write_bytes(p.read_bytes()[:-1])
            with self.assertRaises(ValueError):
                chunk_index(p)

    def test_stream_conversion_duplicate_and_idempotence(self):
        cfg = dict(teacher_sigmoid_scale=361, runtime_scale=400, min_ply=0, max_abs_cp=2000, quiet_only=True)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "source.plain"
            p.write_text(plain(record()) * 2 + plain(record(chess.STARTING_FEN.replace(" w ", " b "), "e7e5")))
            out = Path(tmp) / "output"
            report = convert_plain([p], out, cfg)
            self.assertEqual(report["counts"]["train"], 2)
            self.assertEqual(report["counts"]["duplicates"], 1)
            self.assertEqual(report, convert_plain([p], out, cfg))
            with self.assertRaises(RuntimeError):
                convert_plain([p], out, {**cfg, "teacher_sigmoid_scale": 400})

    def test_invalid_conversion_never_publishes(self):
        cfg = dict(teacher_sigmoid_scale=361, runtime_scale=400, min_ply=0, max_abs_cp=2000, quiet_only=True)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad.plain"
            p.write_text(plain(record()) + plain(record(result="5")))
            out = Path(tmp) / "out"
            with self.assertRaises(ValueError):
                convert_plain([p], out, cfg)
            self.assertFalse((out / "train.bin").exists())
            self.assertEqual(json.loads((out / "conversion-failure.json").read_text())["counts"]["invalid"], 1)


class Response(io.BytesIO):
    def __init__(self, data, status=200, **headers):
        super().__init__(data)
        self.status, self.headers = status, headers


class DownloadTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.content = b"verified training fixture data"
        self.spec = dict(url="https://example.invalid/test", file="source.binpack", bytes=len(self.content), sha256=hashlib.sha256(self.content).hexdigest())

    def tearDown(self):
        self.temp.cleanup()

    def opener(self, req, timeout):
        offset = int(req.get_header("Range", "bytes=0-")[6:-1])
        return Response(self.content[offset:], 206 if offset else 200, **{
            "Content-Length": str(len(self.content) - offset), "ETag": '"version1"',
            "Content-Range": f"bytes {offset}-{len(self.content)-1}/{len(self.content)}"})

    def partial(self, n):
        (self.root / "source.binpack.partial").write_bytes(self.content[:n])
        atomic_json(self.root / "source.binpack.download.json", {"identity": self.spec, "etag": '"version1"'})

    def test_fresh_and_existing_verified(self):
        out = download(self.spec, self.root, self.opener)
        self.assertEqual(out.read_bytes(), self.content)
        download(self.spec, self.root, lambda *a, **k: self.fail("Should not download twice"))

    def test_resume_zero_partial_and_complete_partial(self):
        for n in (0, 4, len(self.content)):
            with tempfile.TemporaryDirectory() as tmp:
                self.root = Path(tmp)
                self.partial(n)
                self.assertEqual(download(self.spec, self.root, self.opener).read_bytes(), self.content)

    def test_ignored_range_does_not_append(self):
        self.partial(4)
        with self.assertRaises(RuntimeError):
            download(self.spec, self.root, lambda *a, **k: Response(self.content, 200))
        self.assertEqual((self.root / "source.binpack.partial").read_bytes(), self.content[:4])

    def test_changed_etag_and_wrong_range(self):
        self.partial(4)
        for headers in ({"ETag": '"changed"', "Content-Range": f"bytes 4-{len(self.content)-1}/{len(self.content)}"}, {"Content-Range": "bytes 0-3/4"}):
            with self.assertRaises(RuntimeError):
                download(self.spec, self.root, lambda *a, **k: Response(self.content[4:], 206, **headers))
            self.assertEqual((self.root / "source.binpack.partial").stat().st_size, 4)

    def test_corrupt_existing_and_size_limit(self):
        p = self.root / self.spec["file"]
        p.write_bytes(b"x" * len(self.content))
        with self.assertRaises(RuntimeError):
            download(self.spec, self.root, self.opener)
        self.assertEqual(p.read_bytes(), b"x" * len(self.content))
        with self.assertRaises(ValueError):
            download({**self.spec, "bytes": 20 * 1024**3}, self.root, self.opener)

    def test_short_download_resumes(self):
        with self.assertRaises(RuntimeError):
            download(self.spec, self.root, lambda *a, **k: Response(self.content[:4], 200, ETag='"version1"'))
        self.assertEqual(download(self.spec, self.root, self.opener).read_bytes(), self.content)

    def test_bad_checksum_and_no_disk(self):
        with self.assertRaises(RuntimeError):
            download(self.spec, self.root, lambda *a, **k: Response(b"x" * len(self.content)))
        self.assertFalse((self.root / self.spec["file"]).exists())
        with patch("common.shutil.disk_usage") as disk:
            disk.return_value.free = 0
            with self.assertRaises(RuntimeError):
                download(self.spec, self.root, self.opener)


if __name__ == "__main__":
    unittest.main()
