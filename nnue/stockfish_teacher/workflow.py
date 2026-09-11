#!/usr/bin/env python3
"""Isolated external-data stages. See docs/STOCKFISH_TEACHER.md."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

from common import (ROOT, HERE, CACHE, CLANG, atomic_json, read_json, sha256, lock,
                    verified, download, run, space_check, busy_processes, require_idle)

ENGINE = ["main.cpp", "board.cpp", "evaluation.cpp", "search.cpp", "nnue.cpp"]
GEN8_SHA = "896eb832d74776a42375e7fa152b4e032fff1cf85ba2e529b420fe2d1b4b74bf"


class Workflow:
    def __init__(self, config_path):
        self.config = read_json(config_path)
        self.dataset = read_json(HERE / "dataset.json")
        self.name = self.config["run"]
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", self.name):
            raise ValueError("Run ID must contain only letters, digits, underscore or hyphen")
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", self.config["edition"]):
            raise ValueError("Edition must be a simple UCI name")
        # data_from/net_from let a run reuse another run's completed conversion or
        # trained net, so a second experiment on the same corpus does not repeat
        # a 25-minute conversion. Both stay read-only here; the owning run made them.
        self.data = ROOT / "data/stockfish_teacher" / self.config.get("data_from", self.name)
        self.run = ROOT / "runs/stockfish_teacher" / self.name
        self.net = ROOT / "nets/stockfish_teacher" / self.config.get("net_from", self.name) / "pilot.nnue"
        self.tool = CACHE / "stockfish_tool.exe"
        self.artifact = CACHE / self.dataset["file"]
        self.run.mkdir(parents=True, exist_ok=True)
        binding = self.run / "config.json"
        with lock(self.run / "config.lock"):
            if binding.exists():
                if read_json(binding) != self.config:
                    raise RuntimeError("Run ID already bound to other settings; choose a new run ID")
            else:
                atomic_json(binding, self.config)
        print(json.dumps({"config": str(Path(config_path).resolve()), "dataset": str(HERE / 'dataset.json'),
                          "data": str(self.data), "run": str(self.run), "net": str(self.net),
                          "settings": self.config}, indent=2), flush=True)

    def status(self):
        result = {"artifact_bytes_expected": self.dataset["bytes"],
                  "artifact_bytes_present": self.artifact.stat().st_size if self.artifact.exists() else 0,
                  "partial_bytes": self.artifact.with_name(self.artifact.name + ".partial").stat().st_size if self.artifact.with_name(self.artifact.name + ".partial").exists() else 0,
                  "converter_exists": self.tool.exists(), "network_exists": self.net.exists(),
                  "busy_processes": busy_processes(),
                  "conversion": (self.data / "conversion.json").exists(),
                  "conversion_progress": read_json(self.data / "conversion-status.json") if (self.data / "conversion-status.json").exists() else None,
                  "training": read_json(self.run / "training-status.json") if (self.run / "training-status.json").exists() else None,
                  "verification": (self.run / "verification.json").exists(),
                  "match_status": [read_json(p) for p in sorted(self.run.glob("match-*/status.json"))],
                  "matches": [str(p) for p in sorted(self.run.glob("match-*/result.json"))]}
        print(json.dumps(result, indent=2), flush=True)
        return result

    def preflight(self):
        if sha256(ROOT / "nets/gen8.nnue") != GEN8_SHA:
            raise RuntimeError("Canonical Gen8 checksum differs")
        if not CLANG.exists():
            raise RuntimeError(f"Required MSYS2 clang64 compiler missing: {CLANG}")
        book = ROOT / self.config["match"]["book"]
        if sha256(book) != self.config["match"]["book_sha256"]:
            raise RuntimeError("Independent opening book hash differs")
        space_check(CACHE, self.dataset["bytes"] + (2 << 30))
        return self.status()

    def download(self):
        self.preflight()
        download(self.dataset)

    def tool_setup(self):
        with lock(CACHE / "tool-setup.lock"):
            self._tool_setup()

    def _tool_setup(self):
        spec = self.dataset["converter"]
        archive = download(spec)
        src_root = CACHE / "tool-source"
        src_root.mkdir(parents=True, exist_ok=True)
        # Retain the complete original source and licence. Existing files must
        # match the pinned archive; no third-party edits are overwritten.
        with zipfile.ZipFile(archive) as z:
            for item in z.infolist():
                target = (src_root / item.filename).resolve()
                if not target.is_relative_to(src_root.resolve()) or (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("Unsafe archive entry")
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    expected = z.read(item)
                    if target.exists():
                        if target.read_bytes() != expected:
                            raise RuntimeError(f"Existing third-party source differs: {target}")
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with target.open("xb") as f:
                            f.write(expected)
        src = src_root / f"Stockfish-{spec['revision']}" / "src"
        body = (src / "Makefile").read_text()
        sources = re.search(r"SRCS = (.*?)\n\n", body, re.S)[1].replace("\\\n", " ").split()
        cmd = [CLANG, "-std=c++17", "-O2", "-march=native", "-static", "-pthread", "-I.",
               "-DNNUE_EMBEDDING_OFF", "-DIS_64BIT", "-DUSE_POPCNT", *sources, "-o", self.tool]
        receipt = CACHE / "tool-build.json"
        if receipt.exists():
            old = read_json(receipt)
            if old["source_archive_sha256"] != sha256(archive) or old["binary_sha256"] != sha256(self.tool):
                raise RuntimeError("Converter build changed")
            return
        if self.tool.exists():
            raise RuntimeError("Unmanifested converter exists; preserve it and investigate before reuse")
        run(cmd, self.run / "tool-build.log", cwd=src)
        atomic_json(receipt, {"source_archive_sha256": sha256(archive), "binary_sha256": sha256(self.tool),
                              "command": list(map(str, cmd)), "licence": str(src.parent / "Copying.txt")})

    def convert(self):
        if "target_positions" in self.config["sampling"]:
            from large_conversion import convert_target
            return convert_target(self)
        from records import chunk_index, select_chunks, convert_plain, stem_metadata, plain_records
        verified(self.artifact, self.dataset)
        tool_receipt = read_json(CACHE / "tool-build.json")
        if sha256(self.tool) != tool_receipt["binary_sha256"]:
            raise RuntimeError("Converter binary hash changed")
        self.data.mkdir(parents=True, exist_ok=True)
        index = chunk_index(self.artifact)
        selected = select_chunks(index, **{"seed": self.config["sampling"]["seed"], "count": self.config["sampling"]["chunks"]})
        sampling = {"artifact_sha256": self.dataset["sha256"], "total_chunks": len(index),
                    "selected": selected, "seed": self.config["sampling"]["seed"],
                    "sample_bytes": sum(c["bytes"] for c in selected),
                    "converter_sha256": tool_receipt["binary_sha256"],
                    "game_boundaries": "Compression chunks are not guaranteed whole games; no game holdout claimed"}
        binding = self.data / "sampling.json"
        if binding.exists() and read_json(binding) != sampling:
            raise RuntimeError("Existing sample identity differs")
        atomic_json(binding, sampling)
        # At least 5 score bits per continuation, <=65535 continuations/stem:
        # 256x compressed bytes conservatively covers ordinary plain expansion.
        space_check(self.data, sampling["sample_bytes"] * 256 + (512 << 20))
        plains = []
        with self.artifact.open("rb") as source:
            for chunk in selected:
                stem = self.data / f"chunk-{chunk['index']:06d}"
                packed, plain = stem.with_suffix(".binpack"), stem.with_suffix(".plain")
                receipt = stem.with_suffix(".json")
                if receipt.exists():
                    old = read_json(receipt)
                    if sha256(plain) != old["plain_sha256"] or sha256(packed) != old["binpack_sha256"]:
                        raise RuntimeError("Completed chunk changed")
                else:
                    source.seek(chunk["offset"])
                    content = source.read(chunk["bytes"])
                    if packed.exists() and packed.read_bytes() != content:
                        raise RuntimeError("Unidentified chunk exists")
                    if not packed.exists():
                        with packed.open("xb") as f:
                            f.write(content)
                    # Official converter detects format by final extension.
                    partial = stem.with_name(stem.name + ".partial.plain")
                    run([self.tool, "convert", packed, partial, "validate"], self.run / "official-convert.log", timeout=600)
                    output = (self.run / "official-convert.log").read_text()
                    latest = output[output.rfind("command="):]
                    if not re.search(r"Finished\. Converted [1-9][0-9]* positions", latest) or "Invalid" in latest:
                        raise RuntimeError("Official converter did not report a validated complete conversion")
                    if plain.exists():
                        raise RuntimeError("Unmanifested plain output exists")
                    partial.rename(plain)
                    atomic_json(receipt, {"plain_sha256": sha256(plain), "plain_bytes": plain.stat().st_size,
                                         "binpack_sha256": sha256(packed), "chunk": chunk})
                plains.append(plain)
                with plain.open(encoding="ascii") as f:
                    first = next(plain_records(f))
                scalars = stem_metadata(packed)
                if any(int(first[k]) != scalars[k] for k in ("score", "ply", "result")):
                    raise RuntimeError("Independent binpack stem scalar decode disagrees with official converter")
                if int(first["fen"].split()[4]) != scalars["rule50"]:
                    raise RuntimeError("Independent rule50 decode disagrees")
                atomic_json(stem.with_suffix(".stem-check.json"), {"source_scalars": scalars, "first_plain_record": first, "status": "PASS"})
        report = convert_plain(plains, self.data, self.config["conversion"])
        print(json.dumps({"counts": report["counts"], "outputs": report["outputs"], "sample": sampling}, indent=2), flush=True)

    def train(self):
        from train_external import train
        return train(self.config, self.dataset, self.data, self.run, self.net)

    def _compile(self, cmd, exe, log, *, env=None):
        # Re-link only this stage's newly generated binary if Windows blocks it.
        for attempt in range(6):
            run([*cmd, "-o", exe], log, cwd=ROOT / "sgurr_cpp")
            try:
                test_env = os.environ.copy()
                test_env.pop("SGR_EVALFILE", None)
                test_env.update(env or {})
                p = subprocess.run([str(exe)], input="uci\nquit\n", text=True, capture_output=True, env=test_env, timeout=20)
                if p.returncode == 0 and "uciok" in p.stdout:
                    return
            except OSError:
                pass
        raise RuntimeError(f"Binary failed startup after six links: {exe}")

    def build(self):
        build = self.run / "build"
        build.mkdir(parents=True, exist_ok=True)
        inputs = {str(p.relative_to(ROOT)): sha256(p) for p in sorted((ROOT / "sgurr_cpp").glob("*.hpp"))}
        inputs.update({"sgurr_cpp/" + n: sha256(ROOT / "sgurr_cpp" / n) for n in ENGINE})
        receipt = build / "build.json"
        if receipt.exists():
            old = read_json(receipt)
            if old["source_sha256"] != inputs:
                raise RuntimeError("Engine source changed; choose a new run ID for a fresh build")
            for name, digest in old["binary_sha256"].items():
                if sha256(build / name) != digest:
                    raise RuntimeError("Built executable changed")
            return
        # Missing pilot nets do not prevent building. A separately labelled
        # exporter fixture validates the plumbing but is never called a pilot.
        fixture = self._fixture()
        flags = [CLANG, "-std=c++20", "-O3", "-march=native", "-DNDEBUG", "-static", "-Wall", "-Wextra"]
        sources = [ROOT / "sgurr_cpp" / n for n in ENGINE]
        profile = build / "pgo"
        profile.mkdir(exist_ok=True)
        prof = build / "profile.exe"
        self._compile([*flags, f"-fprofile-generate={profile.as_posix()}", *sources], prof, build / "compile.log")
        run([prof, "bench", "13"], build / "profile.log", env={"SGR_EVALFILE": str(ROOT / 'nets/gen8.nnue')}, timeout=120)
        merged = profile / "sgurr.profdata"
        run([CLANG.parent / "llvm-profdata.exe", "merge", f"-output={merged}", *profile.glob("*.profraw")], build / "compile.log")
        release = [*flags, "-flto=thin", "-fuse-ld=lld", f"-fprofile-use={merged.as_posix()}"]
        self._compile([*release, *sources], build / "normal.exe", build / "compile.log")
        # Net width is a build-time define on both sides. Gen8 is HL384, so the
        # plain selfcheck stays 384 and a second one is built for other widths.
        hl = self.config["training"]["hl"]
        width = [f"-DSGR_HL={hl}"] if hl != 384 else []
        edition = [f'-DSGR_ENGINE_NAME="{self.config["edition"]}"', "-DSGR_REQUIRE_NET=1", f'-DSGR_DEFAULT_NET="{self.net.as_posix()}"']
        external = [*edition, *width]
        self._compile([*release, *external, *sources], build / "external.exe", build / "compile.log", env={"SGR_EVALFILE": str(self.net if self.net.exists() else fixture)})
        if width:
            # A width-matched twin of the edition build. An engine built for a
            # different HL cannot load Gen8 at all, so without this the bench
            # proof that the identity defines leave search alone is impossible.
            self._compile([*release, *edition, *sources], build / "external-gen8width.exe", build / "compile.log",
                          env={"SGR_EVALFILE": str(ROOT / "nets/gen8.nnue")})
        sc_sources = [ROOT / "sgurr_cpp" / n for n in ["nnue_selfcheck.cpp", *ENGINE[1:]]]
        run([*flags, *sc_sources, "-o", build / "selfcheck.exe"], build / "compile.log", cwd=ROOT / "sgurr_cpp")
        if width:
            run([*flags, *width, *sc_sources, "-o", build / f"selfcheck-hl{hl}.exe"], build / "compile.log", cwd=ROOT / "sgurr_cpp")
        # Exact pre-edit main from git (it was clean in initial status), compiled
        # against the same current engine sources. No worktree reset/checkouts.
        baseline = build / "baseline_main.cpp"
        original = subprocess.check_output(["git", "show", "HEAD:sgurr_cpp/main.cpp"], cwd=ROOT)
        if baseline.exists() and baseline.read_bytes() != original:
            raise RuntimeError("Baseline source differs")
        if not baseline.exists():
            baseline.write_bytes(original)
        self._compile([*release, "-I", ROOT / "sgurr_cpp", baseline, *sources[1:]], build / "normal-before.exe", build / "compile.log")
        atomic_json(receipt, {"source_sha256": inputs, "compiler": subprocess.check_output([str(CLANG), '--version'], text=True),
                              "flags": list(map(str, release)), "external_defines": external,
                              "binary_sha256": {p.name: sha256(p) for p in build.glob("*.exe")}})

    def _fixture(self):
        path = ROOT / "nets/stockfish_teacher/verification-only/fixture.nnue"
        if not path.exists():
            import torch
            from train_external import export_model, sgurr
            torch.manual_seed(20260906)
            export_model(sgurr.NNUE(), path)
            atomic_json(path.parent / "NOTICE.json", {"purpose": "UNTRAINED deterministic Sgurr exporter fixture; not an external-data pilot and not a playing-strength candidate", "sha256": sha256(path)})
        return path

    def verify(self):
        from verification import verify
        return verify(self, fixture=False)

    def verify_fixture(self):
        from verification import verify
        return verify(self, fixture=True)

    def match(self):
        from matches import launch
        return launch(self)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stage", choices=["preflight", "status", "download", "tool-setup", "convert", "train", "build", "verify", "verify-fixture", "match", "match-status"])
    ap.add_argument("--config", type=Path, default=HERE / "pilot.json")
    ap.add_argument("--opponent", type=Path, help="Pinned opponent JSON for a separate named match")
    args = ap.parse_args()
    w = Workflow(args.config)
    if args.stage in ("status", "match-status"):
        w.status()
        return
    with lock(w.run / "workflow.lock"):
        if args.opponent is not None:
            if args.stage != "match":
                raise ValueError("--opponent is only valid for match")
            from matches import launch
            launch(w, read_json(args.opponent))
        else:
            getattr(w, args.stage.replace("-", "_"))()


if __name__ == "__main__":
    main()
