"""Resumable external-data training using Sgurr's unchanged model and loss."""
from __future__ import annotations

import os
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
import math
from pathlib import Path
import sys
import time

import numpy as np
import torch

from common import ROOT, atomic_json, read_json, sha256, require_idle

sys.path.insert(0, str(ROOT / "nnue"))
import train as sgurr
import nnue_tools as nt


def export_model(model, destination, buckets=1):
    """Keep float parameters for independently repeating the ordinary exporter."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    n_features = nt.INPUT * buckets
    if isinstance(model, sgurr.FactorizedNNUE):
        shared = model.ft_shared.weight[:nt.INPUT].detach().cpu().numpy()
        delta = model.ft_delta.weight[:n_features].detach().cpu().numpy()
        ftw = np.clip(delta + np.tile(shared, (buckets, 1)), -127 / nt.QA, 127 / nt.QA)
    else:
        ftw = model.ft.weight[:n_features].detach().cpu().numpy()
    arrays = {"ftw": ftw,
              "ftb": model.ftb.detach().cpu().numpy(),
              "ow": model.out.weight.detach().cpu().numpy().reshape(-1),
              "ob": model.out.bias.detach().cpu().numpy()[0]}
    if buckets > 1:
        arrays["bucket_map"] = nt.KING_BUCKET_MAP.copy()
    partial = destination.with_name(destination.name + ".partial")
    nt.export(partial, **arrays)
    loaded = nt.load(partial)
    for actual, expected in zip(loaded[:3], (np.rint(arrays["ftw"] * nt.QA), np.rint(arrays["ftb"] * nt.QA), np.rint(arrays["ow"] * nt.QB))):
        if not np.array_equal(actual, np.clip(expected, -32768, 32767)):
            raise RuntimeError("Exporter integer round-trip failed")
    if loaded[3] != round(float(arrays["ob"]) * nt.QA * nt.QB):
        raise RuntimeError("Exporter output bias round-trip failed")
    if destination.exists() and sha256(destination) != sha256(partial):
        raise RuntimeError("Existing network differs; no overwrite permitted")
    if not destination.exists():
        partial.rename(destination)
    else:
        partial.unlink()
    float_path = destination.with_suffix(".float.npz")
    if not float_path.exists():
        with float_path.open("xb") as f:
            np.savez(f, **arrays)
    return {"path": str(destination), "sha256": sha256(destination), "bytes": destination.stat().st_size,
            "float_path": str(float_path), "float_sha256": sha256(float_path), "export_roundtrip": "PASS"}


def train(config, dataset_manifest, data_dir, run_dir, net_path):
    require_idle()
    tr = config["training"]
    buckets = tr["buckets"]
    factorize = tr.get("factorize", False)
    if tr["hl"] not in (128, 256, 384, 512) or buckets not in (1, nt.BUCKETS) or tr["val_frac"] != 0:
        raise ValueError("Require engine-supported HL, one or eight buckets, and deployment val_frac=0")
    if factorize and buckets == 1:
        raise ValueError("Factorisation requires king buckets")
    if not 0 <= tr["lambda"] <= 1:
        raise ValueError("lambda must be in [0,1]")
    if tr["lambda"] != 1 and not dataset_manifest["provenance"]["results_trusted_for_training"]:
        raise ValueError("Unverified result provenance requires score-only lambda=1")
    for k in ("steps", "batch", "checkpoint_every"):
        if not isinstance(tr[k], int) or tr[k] <= 0:
            raise ValueError(f"Invalid {k}")
    if not 0 < tr["lr_min"] <= tr["lr"]:
        raise ValueError("Invalid learning rate schedule")
    conversion = read_json(Path(data_dir) / "conversion.json")
    if conversion["parameters"]["config"] != config["conversion"]:
        raise ValueError("Conversion/calibration settings do not match run")
    source = Path(data_dir) / "train.bin"
    digest = sha256(source)
    if digest != conversion["outputs"]["train.bin"]["sha256"]:
        raise ValueError("Training data checksum changed")
    if source.stat().st_size == 0 or source.stat().st_size % 32:
        raise ValueError("Empty or truncated training data")
    dev = tr["device"]
    if dev == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable; use a new explicit CPU config")
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.manual_seed(tr["seed"])
    files = [ROOT / "nnue/train.py", ROOT / "nnue/nnue_tools.py", Path(__file__)]
    identity = {"config": config, "dataset_manifest": dataset_manifest, "data_sha256": digest,
                "source_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in files},
                "torch": torch.__version__, "numpy": np.__version__, "device": dev,
                "device_name": torch.cuda.get_device_name(0) if dev == "cuda" else "CPU",
                "runtime_scale": nt.SCALE, "target": "lambda*sigmoid(mapped_sgurr_cp/400)+(1-lambda)*stored_result",
                "sampling": "Deterministic epoch permutations; last partial batch retained"}
    run_dir = Path(run_dir)
    manifest = run_dir / "training-inputs.json"
    if manifest.exists() and read_json(manifest) != identity:
        raise RuntimeError("Training inputs/code/environment changed; use a new run ID")
    atomic_json(manifest, identity)
    if (run_dir / "training-result.json").exists():
        result = read_json(run_dir / "training-result.json")
        if sha256(net_path) != result["network"]["sha256"]:
            raise RuntimeError("Completed network changed")
        print("Completed training verified; no work repeated", flush=True)
        return result
    # train.py's own --hl path sets both module globals before construction and
    # export. Do the same so one width flows through the model, the exporter and
    # the loader. The engine side is built with a matching -DSGR_HL.
    sgurr.HL = nt.HL = tr["hl"]
    ds = sgurr.StreamingDataset(source, buckets=buckets)
    def fetch(sel):
        return tuple(torch.from_numpy(x) for x in ds.batch(sel.numpy()))
    model = (sgurr.FactorizedNNUE(buckets) if factorize else sgurr.NNUE(nt.INPUT * buckets)).to(dev)
    opt = torch.optim.Adam(model.parameters(), lr=tr["lr"])
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=tr["steps"], eta_min=tr["lr_min"])
    checkpoint = run_dir / "checkpoint.pt"
    start = 0
    if checkpoint.exists():
        state = torch.load(checkpoint, map_location=dev, weights_only=False)
        if state["identity"] != identity:
            raise RuntimeError("Checkpoint identity differs")
        model.load_state_dict(state["model"])
        opt.load_state_dict(state["optimizer"])
        scheduler.load_state_dict(state["scheduler"])
        start = state["step"]
        torch.set_rng_state(state["rng"].cpu())
        if dev == "cuda":
            torch.cuda.set_rng_state_all([x.cpu() for x in state["cuda_rng"]])
        print(f"Resuming checkpoint at step {start}", flush=True)
    steps_per_epoch = math.ceil(len(ds) / tr["batch"])
    print(f"Positions={len(ds):,}; batch={tr['batch']}; steps={tr['steps']}; lambda={tr['lambda']}; device={dev}", flush=True)
    current_epoch = -1
    t0 = time.monotonic()
    loss = torch.tensor(float("nan"))
    def save(step):
        tmp = checkpoint.with_suffix(".pt.partial")
        torch.save({"identity": identity, "step": step, "model": model.state_dict(), "optimizer": opt.state_dict(),
                    "scheduler": scheduler.state_dict(), "rng": torch.get_rng_state(),
                    "cuda_rng": torch.cuda.get_rng_state_all() if dev == "cuda" else []}, tmp)
        os.replace(tmp, checkpoint)
        atomic_json(run_dir / "training-status.json", {"step": step, "steps": tr["steps"], "loss": loss.detach().item() if torch.isfinite(loss) else None})
    model.train()
    for step in range(start, tr["steps"]):
        epoch, batch_index = divmod(step, steps_per_epoch)
        if epoch != current_epoch:
            generator = torch.Generator().manual_seed(tr["seed"] + epoch)
            # Release the previous multi-GB permutation before allocating another.
            if current_epoch != -1:
                del idx, order
            order = torch.randperm(len(ds), generator=generator)
            current_epoch = epoch
        idx = order[batch_index * tr["batch"]:(batch_index + 1) * tr["batch"]]
        loss = sgurr.batch_loss(model, fetch, idx, dev, tr["lambda"])
        if not torch.isfinite(loss):
            raise RuntimeError("Non-finite training loss; previous checkpoint retained")
        opt.zero_grad()
        loss.backward()
        opt.step()
        scheduler.step()
        with torch.no_grad():
            if factorize:
                model.ft_shared.weight[:nt.INPUT].clamp_(-127 / nt.QA * .75, 127 / nt.QA * .75)
                model.ft_delta.weight[:nt.INPUT * buckets].clamp_(-127 / nt.QA * .25, 127 / nt.QA * .25)
            else:
                model.ft.weight[:nt.INPUT * buckets].clamp_(-127 / nt.QA, 127 / nt.QA)
        if (step + 1) % 10 == 0:
            print(f"step={step+1}/{tr['steps']} loss={loss.detach().item():.7f} lr={scheduler.get_last_lr()[0]:.8f} elapsed={time.monotonic()-t0:.1f}s", flush=True)
        if (step + 1) % tr["checkpoint_every"] == 0 or step + 1 == tr["steps"]:
            save(step + 1)
    net = export_model(model, net_path, buckets=buckets)
    result = {"network": net, "positions": len(ds), "steps": tr["steps"], "seed": tr["seed"],
              "last_loss": loss.detach().item() if torch.isfinite(loss) else None, "strength_conclusion": None}
    atomic_json(run_dir / "training-result.json", result)
    return result
