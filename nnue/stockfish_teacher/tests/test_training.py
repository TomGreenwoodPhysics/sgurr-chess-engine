import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import HERE, atomic_json, read_json, sha256
from records import pack
import chess
import train_external as training


class TrainingTest(unittest.TestCase):
    def test_interrupted_training_resumes_bit_exact(self):
        self.check_resume(1, False)

    def test_factorized_training_resumes_bit_exact(self):
        self.check_resume(8, True)

    def check_resume(self, buckets, factorize):
        config = copy.deepcopy(read_json(HERE / "pilot.json"))
        config["training"].update(steps=6, batch=4, checkpoint_every=2, device="cpu", buckets=buckets, factorize=factorize)
        dataset = read_json(HERE / "dataset.json")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"; data.mkdir()
            board = chess.Board()
            records = []
            for move, score in zip(("e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6", "d2d3", "f8c5"), (50, -80, 100, -40, 120, -90, 40, -20)):
                records.append(pack(board, score, 0)); board.push_uci(move)
            (data / "train.bin").write_bytes(b"".join(records))
            atomic_json(data / "conversion.json", {"parameters": {"config": config["conversion"]},
                        "outputs": {"train.bin": {"sha256": sha256(data / "train.bin")}}})
            original = training.sgurr.batch_loss
            calls = 0
            def interruption(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise RuntimeError("simulated interruption")
                return original(*args, **kwargs)
            with patch.object(training, "require_idle"):
                training.train(config, dataset, data, root / "continuous", root / "a.nnue")
                with patch.object(training.sgurr, "batch_loss", side_effect=interruption):
                    with self.assertRaisesRegex(RuntimeError, "simulated interruption"):
                        training.train(config, dataset, data, root / "resumed", root / "b.nnue")
                self.assertFalse((root / "b.nnue").exists())
                self.assertEqual(read_json(root / "resumed/training-status.json")["step"], 2)
                training.train(config, dataset, data, root / "resumed", root / "b.nnue")
                self.assertEqual(sha256(root / "a.nnue"), sha256(root / "b.nnue"))
                self.assertEqual(training.nt.load(root / "a.nnue")[4], buckets)
                # A completed run is checked, not retrained.
                training.train(config, dataset, data, root / "resumed", root / "b.nnue")
                # Caught interruption tracebacks can retain a Windows memmap.
                import gc
                gc.collect()

    def test_factorized_export_matches_model_across_king_buckets(self):
        import numpy as np
        import torch
        from verification import forward_float, invoke
        nt, sgurr = training.nt, training.sgurr
        sgurr.HL = nt.HL = 384
        torch.manual_seed(42)
        model = sgurr.FactorizedNNUE(8)
        with torch.no_grad():
            model.ft_delta.weight[:768 * 8].normal_(0, .01)
        fens = ["4k3/8/8/8/8/8/P7/3K4 w - - 0 1",
                "4k3/8/8/8/8/8/P7/4K3 b - - 0 1",
                "2k5/8/8/8/8/5K2/P7/8 b - - 0 1",
                "8/2k5/8/8/8/8/P3K3/8 w - - 0 1"]
        with tempfile.TemporaryDirectory() as tmp:
            net = Path(tmp) / "bucketed.nnue"
            training.export_model(model, net, buckets=8)
            floats = dict(np.load(net.with_suffix('.float.npz')))
            loaded = nt.load(net)
            self.assertEqual(loaded[4], 8)
            for fen in fens:
                raw = np.frombuffer(pack(chess.Board(fen), 0, 0), np.uint8).reshape(1, 32)
                wf, bf, stm, *_ = sgurr._decode_chunk(raw, nt.KING_BUCKET_MAP, 768 * 8)
                with torch.no_grad():
                    expected = model(torch.from_numpy(wf).long(), torch.from_numpy(bf).long(), torch.from_numpy(stm)).item() * 400
                self.assertAlmostEqual(forward_float(**floats, fen=fen), expected, delta=.001)
            # The already built engine reads the same v2 format; no engine edits.
            exe = training.ROOT / 'runs/stockfish_teacher/56m-s0-scale361/build/selfcheck.exe'
            if exe.exists():
                result = invoke(exe, [net])
                self.assertEqual(result['returncode'], 0, result)
                self.assertIn('-> PASS', result['stdout'])
                for fen in fens:
                    result = invoke(exe, [net, 'fwd', fen])
                    self.assertEqual(result['returncode'], 0, result)
                    self.assertEqual(int(result['stdout'].strip().splitlines()[-1]), nt.forward(loaded, fen)[0])

    def test_untrusted_results_cannot_enter_loss(self):
        config = read_json(HERE / "pilot.json")
        config["training"]["lambda"] = .9
        with patch.object(training, "require_idle"):
            with self.assertRaisesRegex(ValueError, "score-only"):
                training.train(config, read_json(HERE / "dataset.json"), Path("unused"), Path("unused"), Path("unused"))


if __name__ == "__main__":
    unittest.main()
