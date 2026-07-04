#!/usr/bin/env python3
"""Sgurr generation pipeline: one command from self-play data to a ledger row.

    python pipeline.py pipeline_gen3.json            # run / resume everything
    python pipeline.py pipeline_gen3.json --status   # show stage progress
    python pipeline.py pipeline_gen3.json --until train
    python pipeline.py pipeline_gen3.json --force sprt

Stages (each records completion in runs/<gen>/state.json, so the pipeline is
resumable: Ctrl+C or reboot at any point and re-run to continue):

    datagen    parallel self-play generation to the target position count
               (adopts already-running datagen.exe processes, spawns more if
               none are running; stops them all once the target is reached)
    freeze     raw shards -> data/vX.Y/: trim torn tails, sanity-check, zip,
               write manifest.json (sha256s, settings, provenance)
    train      NNUE training via nnue/train.py, one net per lambda in the
               config grid; loss curves logged to data/vX.Y/training_log.json
    build      clang engine build per net, default net baked in (absolute path)
    select     (only if >1 lambda) round-robin the variants + previous gen,
               deploy the winner as nets/genN.nnue / sgr_genN.exe
    sprt       fastchess SPRT: new gen vs previous gen
    calibrate  fastchess gauntlet vs the CCRL-anchored pool, Ordo over ALL
               accumulated calibration PGNs (append-only games archive)
    ledger     append measured results to benchmarks/ledger.md

Honesty rules baked in: every number written to the ledger is a measured game
result with error bars; manifests record commit hash + dirty flag; nothing is
ever deleted (shards are trimmed only of sub-record torn tails, archives and
ledger rows are append-only).

Windows notes: engine paths handed to fastchess are absolute (relative paths
fail CreateProcess); training runs with KMP_DUPLICATE_LIB_OK=TRUE to dodge the
Anaconda libiomp duplicate; builds use MSYS2 clang64 (ucrt64 g++ miscompiles
fstream -- see sgurr_cpp/BUILD.md).
"""

import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLANG = r"C:\msys64\clang64\bin\clang++.exe"
ENGINE_SRC = ["main.cpp", "board.cpp", "evaluation.cpp", "search.cpp", "nnue.cpp"]
RECORD = 32  # bytes per datagen record


# --------------------------------------------------------------------------
# small utilities
# --------------------------------------------------------------------------

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def run(cmd, log_path=None, cwd=None, env=None, check=True):
    """Run a command, teeing combined output to log_path. Returns stdout text."""
    e = dict(os.environ)
    if env:
        e.update(env)
    proc = subprocess.run(
        [str(c) for c in cmd], cwd=str(cwd or ROOT), env=e,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace",
    )
    if log_path:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n===== {datetime.now().isoformat()} :: {' '.join(map(str, cmd))}\n")
            f.write(proc.stdout or "")
    if check and proc.returncode != 0:
        tail = "\n".join((proc.stdout or "").splitlines()[-15:])
        raise RuntimeError(f"command failed ({proc.returncode}): {cmd[0]}\n{tail}")
    return proc.stdout or ""


def sha256(path, buf=1 << 22):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(buf):
            h.update(chunk)
    return h.hexdigest()


def shards_in(raw_dir):
    return sorted(Path(raw_dir).glob("data_*.bin"))


def positions_in(raw_dir):
    return sum(p.stat().st_size // RECORD for p in shards_in(raw_dir))


def datagen_running():
    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq datagen.exe"],
        capture_output=True, text=True,
    ).stdout
    return out.count("datagen.exe")


def git_describe():
    head = run(["git", "rev-parse", "--short", "HEAD"]).strip()
    dirty = bool(run(["git", "status", "--porcelain"]).strip())
    return head + ("-dirty" if dirty else "")


# --------------------------------------------------------------------------
# pipeline state
# --------------------------------------------------------------------------

class Pipeline:
    STAGES = ["datagen", "freeze", "train", "build", "select", "sprt",
              "calibrate", "ledger"]

    def __init__(self, cfg_path):
        self.cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
        self.gen = self.cfg["generation"]
        self.version = self.cfg["version"]          # e.g. "v3.0"
        self.prev = self.gen - 1
        self.run_dir = ROOT / "runs" / f"gen{self.gen}"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.run_dir / "state.json"
        self.state = (json.loads(self.state_path.read_text(encoding="utf-8"))
                      if self.state_path.exists() else {})
        self.raw_dir = ROOT / self.cfg["raw_dir"]
        self.data_dir = ROOT / "data" / self.version
        self.lambdas = self.cfg["train"]["lambda"]
        if not isinstance(self.lambdas, list):
            self.lambdas = [self.lambdas]

    def mark(self, stage, **info):
        self.state[stage] = {"completed_at": datetime.now().isoformat(), **info}
        self.state_path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    def done(self, stage):
        return stage in self.state

    # ---- naming helpers ----
    def lam_tag(self, lam):
        return f"l{int(round(lam * 100)):03d}"        # 0.7 -> l070

    def variant_net(self, lam):
        return ROOT / "nets" / f"gen{self.gen}-{self.lam_tag(lam)}.nnue"

    def variant_exe(self, lam):
        return ROOT / "sgurr_cpp" / f"sgr_gen{self.gen}_{self.lam_tag(lam)}.exe"

    def final_net(self):
        return ROOT / "nets" / f"gen{self.gen}.nnue"

    def final_exe(self):
        return ROOT / "sgurr_cpp" / f"sgr_gen{self.gen}.exe"

    def prev_exe(self):
        return ROOT / "sgurr_cpp" / f"sgr_gen{self.prev}.exe"

    # ----------------------------------------------------------------------
    # stage: datagen
    # ----------------------------------------------------------------------
    def stage_datagen(self, wait=True):
        target = self.cfg["target_positions"]
        dg = self.cfg["datagen"]
        have = positions_in(self.raw_dir)
        if have >= target:
            if datagen_running():
                log(f"datagen: target reached ({have:,}) -- stopping datagen.exe")
                subprocess.run(["taskkill", "/IM", "datagen.exe", "/F"],
                               capture_output=True)
                time.sleep(2)
            self.mark("datagen", positions=positions_in(self.raw_dir))
            return

        running = datagen_running()
        if running == 0:
            n = dg.get("processes") or os.cpu_count()
            log(f"datagen: spawning {n} processes (nodes:{dg['nodes']}, "
                f"labeller={dg['labeller']})")
            self.raw_dir.mkdir(parents=True, exist_ok=True)
            for i in range(n):
                lf = open(self.run_dir / f"datagen_{i}.log", "ab")
                subprocess.Popen(
                    [str(ROOT / "sgurr_cpp" / "datagen.exe"), str(self.raw_dir),
                     str(target), f"nodes:{dg['nodes']}",
                     str(ROOT / dg["book"]), str(ROOT / dg["labeller"])],
                    stdout=subprocess.DEVNULL, stderr=lf, cwd=str(ROOT))
        else:
            log(f"datagen: adopting {running} already-running processes")

        if not wait:
            log(f"datagen: {have:,}/{target:,} positions -- rerun the pipeline "
                f"to continue (or run with default --wait)")
            sys.exit(0)

        while True:
            have = positions_in(self.raw_dir)
            if have >= target:
                break
            log(f"datagen: {have:,}/{target:,} "
                f"({have / target * 100:.1f}%), {datagen_running()} procs")
            time.sleep(120)
        log(f"datagen: target reached ({have:,}) -- stopping processes")
        subprocess.run(["taskkill", "/IM", "datagen.exe", "/F"], capture_output=True)
        time.sleep(2)
        self.mark("datagen", positions=positions_in(self.raw_dir))

    # ----------------------------------------------------------------------
    # stage: freeze  (versioned dataset + manifest)
    # ----------------------------------------------------------------------
    def stage_freeze(self):
        shards = shards_in(self.raw_dir)
        if not shards:
            raise RuntimeError(f"freeze: no shards in {self.raw_dir}")

        # trim torn tails (possible after a hard kill mid-write); sub-record
        # only, so nothing meaningful is lost and concatenation stays aligned
        for p in shards:
            extra = p.stat().st_size % RECORD
            if extra:
                log(f"freeze: trimming {extra}-byte torn tail from {p.name}")
                with open(p, "r+b") as f:
                    f.truncate(p.stat().st_size - extra)

        # structural sanity on a sample of each shard
        for p in shards:
            data = p.read_bytes()
            n = len(data) // RECORD
            step = max(1, n // 200)
            for i in range(0, n, step):
                r = data[i * RECORD:(i + 1) * RECORD]
                occ = int.from_bytes(r[0:8], "little")
                cnt = bin(occ).count("1")
                pieces = []
                for k in range(cnt):
                    b = r[8 + (k >> 1)]
                    pieces.append((b >> 4) if (k & 1) else (b & 0xF))
                if pieces.count(5) != 1 or pieces.count(11) != 1:
                    raise RuntimeError(f"freeze: bad kings in {p.name} rec {i}")
                if r[24] > 1 or r[27] > 2:
                    raise RuntimeError(f"freeze: bad stm/result in {p.name} rec {i}")
        log(f"freeze: {len(shards)} shards structurally valid")

        self.data_dir.mkdir(parents=True, exist_ok=True)
        archive = self.data_dir / f"positions_{self.version}.zip"
        files = []
        for p in shards:
            files.append({"name": p.name, "bytes": p.stat().st_size,
                          "positions": p.stat().st_size // RECORD,
                          "sha256": sha256(p)})
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for p in shards:
                z.write(p, arcname=p.name)

        dg = self.cfg["datagen"]
        mtimes = [datetime.fromtimestamp(p.stat().st_mtime).date().isoformat()
                  for p in shards]
        manifest = {
            "schema_version": 1,
            "dataset_version": self.version,
            "codename": self.cfg.get("codename", ""),
            "engine": "Sgurr",
            "source": "self-play",
            "positions": sum(f["positions"] for f in files),
            "record_format": {
                "record_bytes": RECORD,
                "reference": "sgurr_cpp/datagen.cpp header; decoder in nnue/nnue_tools.py",
            },
            "generation": {
                "labeller": dg["labeller"],
                "search_limit": f"nodes:{dg['nodes']} per move (hardware-independent)",
                "openings": f"{dg['book']} + 4-9 random plies, eval-balance filter "
                            f"(reject openings beyond +/-200cp at a 5000-node probe)",
                "filters": "quiet positions only, |score| < 2000cp, first 8 plies "
                           "skipped, win adjudication at 2000cp sustained 6 plies",
                "engine_code": git_describe(),
                "dates": f"{min(mtimes)} to {max(mtimes)}",
                "pipeline": "generated and frozen by pipeline.py",
            },
            "shards": files,
            "archive": {"name": archive.name, "bytes": archive.stat().st_size,
                        "sha256": sha256(archive)},
            "manifest_written": str(date.today()),
        }
        (self.data_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8")
        log(f"freeze: {manifest['positions']:,} positions -> {archive.name} "
            f"({archive.stat().st_size / 1e6:.0f} MB)")
        self.mark("freeze", positions=manifest["positions"],
                  archive_sha256=manifest["archive"]["sha256"])

    # ----------------------------------------------------------------------
    # stage: train  (one net per lambda; loss curves logged)
    # ----------------------------------------------------------------------
    def stage_train(self):
        tr = self.cfg["train"]
        concat = self.raw_dir / "all.bin"
        shards = shards_in(self.raw_dir)
        total = sum(p.stat().st_size for p in shards)
        if not concat.exists() or concat.stat().st_size != total:
            log(f"train: concatenating {len(shards)} shards -> all.bin")
            with open(concat, "wb") as out:
                for p in shards:
                    with open(p, "rb") as f:
                        shutil.copyfileobj(f, out)

        curves = {}
        for lam in self.lambdas:
            net = self.variant_net(lam) if len(self.lambdas) > 1 else self.final_net()
            log(f"train: lambda={lam} -> {net.name} ({tr['epochs']} epochs)")
            out = run(
                [sys.executable, "train.py", "--data", concat,
                 "--out", net, "--epochs", str(tr["epochs"]),
                 "--lambda_", str(lam), "--val_frac", str(tr.get("val_frac", 0))],
                log_path=self.run_dir / f"train_{self.lam_tag(lam)}.log",
                cwd=ROOT / "nnue", env={"KMP_DUPLICATE_LIB_OK": "TRUE"})
            curve = [float(m.group(1)) for m in
                     re.finditer(r"epoch\s+\d+/\d+\s+(?:loss|train)\s+([\d.]+)", out)]
            curves[str(lam)] = curve
            log(f"train: lambda={lam} final loss {curve[-1] if curve else '?'}")

        (self.data_dir / "training_log.json").write_text(json.dumps({
            "epochs": tr["epochs"], "val_frac": tr.get("val_frac", 0),
            "loss_curves_by_lambda": curves,
            "note": "train loss per epoch (deploy nets use val_frac 0; "
                    "model selection is by games, not loss)",
        }, indent=2), encoding="utf-8")
        self.mark("train", lambdas=self.lambdas,
                  final_losses={k: (v[-1] if v else None) for k, v in curves.items()})

    # ----------------------------------------------------------------------
    # stage: build
    # ----------------------------------------------------------------------
    def _build(self, net_path, exe_path):
        log(f"build: {exe_path.name} (net={net_path.name})")
        run([CLANG, "-std=c++20", "-O3", "-march=native", "-DNDEBUG", "-static",
             f'-DSGR_DEFAULT_NET="{net_path.as_posix()}"', *ENGINE_SRC,
             "-o", exe_path.name],
            log_path=self.run_dir / "build.log", cwd=ROOT / "sgurr_cpp")
        # piped UCI handshake (never launch without piped stdin: the engine
        # would block reading the console and hang the pipeline)
        p = subprocess.run([str(exe_path)], input="uci\nquit\n",
                           capture_output=True, text=True, timeout=15)
        if "uciok" not in p.stdout:
            raise RuntimeError(f"build: {exe_path.name} failed UCI handshake")

    def stage_build(self):
        if len(self.lambdas) > 1:
            for lam in self.lambdas:
                self._build(self.variant_net(lam), self.variant_exe(lam))
        else:
            self._build(self.final_net(), self.final_exe())
        self.mark("build")

    # ----------------------------------------------------------------------
    # stage: select  (lambda sweep decided by games)
    # ----------------------------------------------------------------------
    def stage_select(self):
        if len(self.lambdas) == 1:
            self.mark("select", skipped=True, winner=str(self.lambdas[0]))
            return
        sel = self.cfg.get("select", {})
        fc = ROOT / "benchmarks" / "tools" / "fastchess.exe"
        cmd = [fc, "-tournament", "roundrobin"]
        names = {}
        for lam in self.lambdas:
            name = f"gen{self.gen}-{self.lam_tag(lam)}"
            names[name] = lam
            cmd += ["-engine", f"cmd={self.variant_exe(lam)}", f"name={name}"]
        cmd += ["-engine", f"cmd={self.prev_exe()}", f"name=gen{self.prev}"]
        cmd += ["-each", f"tc={sel.get('tc', '8+0.08')}",
                "-rounds", str(sel.get("rounds", 30)), "-repeat",
                "-concurrency", str(sel.get("concurrency", 5)),
                "-openings", f"file={ROOT / 'testing' / 'book.epd'}",
                "format=epd", "order=random",
                "-pgnout", f"file={self.run_dir / 'select.pgn'}",
                "-ratinginterval", "60"]
        log(f"select: round-robin {len(self.lambdas)} lambda variants + gen{self.prev}")
        out = run(cmd, log_path=self.run_dir / "select.log", cwd=ROOT / "benchmarks")

        # parse the FINAL standings table only (fastchess prints interim tables
        # every ratinginterval; take the last "Rank ..." block)
        final = out[out.rfind("Rank"):]
        rank = re.findall(r"^\s*\d+\s+(\S+)\s+(-?[\d.]+)", final, re.M)
        table = [(n, float(e)) for n, e in rank if n in names or n == f"gen{self.prev}"]
        winner_name = next(n for n, _ in table if n in names)
        winner = names[winner_name]
        log(f"select: winner lambda={winner}  (standings: {table})")

        shutil.copyfile(self.variant_net(winner), self.final_net())
        self._build(self.final_net(), self.final_exe())
        self.mark("select", winner=str(winner), standings=table)

    # ----------------------------------------------------------------------
    # stage: sprt  (new gen vs previous gen)
    # ----------------------------------------------------------------------
    def stage_sprt(self):
        sp = self.cfg.get("sprt", {})
        fc = ROOT / "benchmarks" / "tools" / "fastchess.exe"
        out = run(
            [fc,
             "-engine", f"cmd={self.final_exe()}", f"name=Sgurr-{self.version}",
             "-engine", f"cmd={self.prev_exe()}", f"name=Sgurr-v{self.prev}.0",
             "-each", f"tc={sp.get('tc', '8+0.08')}",
             "-rounds", str(sp.get("max_rounds", 1000)), "-repeat",
             "-concurrency", str(sp.get("concurrency", 5)),
             "-openings", f"file={ROOT / 'testing' / 'book.epd'}",
             "format=epd", "order=random",
             "-sprt", f"elo0={sp.get('elo0', 0)}", f"elo1={sp.get('elo1', 5)}",
             "alpha=0.05", "beta=0.05",
             "-pgnout", f"file={self.run_dir / 'sprt.pgn'}",
             "-ratinginterval", "50"],
            log_path=self.run_dir / "sprt.log", cwd=ROOT / "benchmarks")

        elo = re.findall(r"Elo\s*:?\s*(-?[\d.]+)\s*\+/-\s*([\d.]+)", out)
        verdict = ("H1" if re.search(r"H1 was accepted", out)
                   else "H0" if re.search(r"H0 was accepted", out)
                   else "inconclusive")
        result = {"verdict": verdict,
                  "elo": float(elo[-1][0]) if elo else None,
                  "pm": float(elo[-1][1]) if elo else None}
        log(f"sprt: {result}")
        self.mark("sprt", **result)

    # ----------------------------------------------------------------------
    # stage: calibrate  (pool gauntlet + Ordo over all accumulated PGNs)
    # ----------------------------------------------------------------------
    def stage_calibrate(self):
        cal = self.cfg.get("calibrate", {})
        bm = ROOT / "benchmarks"
        pool = json.loads((bm / "pool.json").read_text(encoding="utf-8"))
        fc = bm / "tools" / "fastchess.exe"
        pgn = bm / "games" / f"calib-{self.version}-{date.today().isoformat()}.pgn"

        cmd = [fc, "-tournament", "gauntlet", "-seeds", "1",
               "-engine", f"cmd={self.final_exe()}", f"name=Sgurr-{self.version}"]
        for e in pool["engines"]:
            cmd += ["-engine", f"cmd={bm / e['cmd']}", f"name={e['name']}"]
        cmd += ["-each", f"tc={cal.get('tc', '10+0.1')}",
                "-rounds", str(cal.get("rounds", 15)), "-repeat",
                "-concurrency", str(cal.get("concurrency", 5)),
                "-openings", f"file={ROOT / 'testing' / 'book.epd'}",
                "format=epd", "order=random",
                "-pgnout", f"file={pgn}", "-ratinginterval", "60"]
        log(f"calibrate: gauntlet Sgurr-{self.version} vs {len(pool['engines'])} "
            f"pool engines")
        run(cmd, log_path=self.run_dir / "calibrate.log", cwd=bm)

        combined = self.run_dir / "all_calib.pgn"
        with open(combined, "wb") as out_f:
            for p in sorted((bm / "games").glob("calib-*.pgn")):
                out_f.write(p.read_bytes())
        log("calibrate: solving Ordo over all accumulated calibration games")
        run([bm / "tools" / "ordo.exe", "-Q", "-p", combined,
             "-m", bm / "anchors.txt", "-W", "-s", "1500", "-n", "5", "-N", "1",
             "-o", self.run_dir / "ordo.txt"],
            log_path=self.run_dir / "ordo.log", cwd=bm)

        text = (self.run_dir / "ordo.txt").read_text(encoding="utf-8")
        m = re.search(rf"Sgurr-{re.escape(self.version)}\s*:\s*(-?[\d.]+)\s+([\d.]+)",
                      text)
        if not m:
            raise RuntimeError("calibrate: could not find new engine in Ordo output")
        rating, err = float(m.group(1)), float(m.group(2))

        # W-D-L for the new engine from its gauntlet PGN
        results = re.findall(
            rf'\[(White|Black) "Sgurr-{re.escape(self.version)}"\].*?\[Result "([^"]+)"\]',
            pgn.read_text(encoding="utf-8", errors="replace"), re.S)
        w = d = l_ = 0
        for colour, res in results:
            if res == "1/2-1/2":
                d += 1
            elif (res == "1-0") == (colour == "White"):
                w += 1
            else:
                l_ += 1
        log(f"calibrate: Sgurr-{self.version} = {rating:.0f} +/- {err:.0f} "
            f"(+{w} ={d} -{l_})")
        self.mark("calibrate", rating=rating, error=err, wdl=[w, d, l_],
                  games=w + d + l_, ordo_table=text)

    # ----------------------------------------------------------------------
    # stage: ledger
    # ----------------------------------------------------------------------
    def stage_ledger(self):
        cal = self.state["calibrate"]
        sprt = self.state["sprt"]
        sel = self.state.get("select", {})
        ledger = ROOT / "benchmarks" / "ledger.md"
        text = ledger.read_text(encoding="utf-8")

        row = (f"| {date.today().isoformat()} | Sgurr {self.version} "
               f"\"{self.cfg.get('codename', '')}\" | {cal['rating']:.0f} | "
               f"{cal['error']:.0f} | {cal['games']} | "
               f"+{cal['wdl'][0]} ={cal['wdl'][1]} -{cal['wdl'][2]} | "
               f"{self.cfg.get('calibrate', {}).get('tc', '10+0.1')} | "
               f"{json.loads((ROOT / 'benchmarks' / 'pool.json').read_text())['pool_id']} | "
               f"i5-9400F, 5 threads | Pipeline run; SPRT vs v{self.prev}.0: "
               f"{sprt['elo']:+.1f} +/-{sprt['pm']:.1f} ({sprt['verdict']})"
               + (f"; lambda sweep winner {sel.get('winner')}"
                  if not sel.get("skipped") else "") + " |")

        # newest-first: insert right after the table header separator
        lines = text.splitlines()
        sep = next(i for i, ln in enumerate(lines)
                   if set(ln.strip()) <= set("|- ") and "|" in ln and i > 0)
        lines.insert(sep + 1, row)

        section = [
            "",
            f"### {date.today().isoformat()} — {self.version} "
            f"\"{self.cfg.get('codename', '')}\" (pipeline run)",
            "",
            f"- Dataset: `data/{self.version}` "
            f"({self.state['freeze']['positions']:,} positions), "
            f"labels {self.cfg['datagen']['labeller']} @ "
            f"nodes:{self.cfg['datagen']['nodes']}, balance-filtered openings.",
            f"- Training: lambdas {self.state['train']['lambdas']}, "
            f"final losses {self.state['train']['final_losses']}"
            + (f"; selection round-robin winner lambda={sel.get('winner')}."
               if not sel.get("skipped") else "."),
            f"- SPRT vs v{self.prev}.0 @ "
            f"{self.cfg.get('sprt', {}).get('tc', '8+0.08')}: "
            f"{sprt['elo']:+.1f} +/-{sprt['pm']:.1f}, verdict {sprt['verdict']}.",
            f"- Pool calibration: {cal['rating']:.0f} +/-{cal['error']:.0f} "
            f"({cal['games']} games, Ordo over all accumulated calibration PGNs).",
        ]
        ledger.write_text("\n".join(lines + section) + "\n", encoding="utf-8")
        log(f"ledger: appended {self.version} row and run section")
        self.mark("ledger")

    # ----------------------------------------------------------------------
    def status(self):
        print(f"generation {self.gen} ({self.version} "
              f"\"{self.cfg.get('codename', '')}\")")
        have = positions_in(self.raw_dir)
        print(f"  raw positions : {have:,} / {self.cfg['target_positions']:,} "
              f"({datagen_running()} datagen procs running)")
        for s in self.STAGES:
            info = self.state.get(s)
            mark_ = "x" if info else " "
            extra = ""
            if info:
                extra = ", ".join(f"{k}={v}" for k, v in info.items()
                                  if k != "completed_at" and not isinstance(v, (dict, list)))
            print(f"  [{mark_}] {s:10s} {extra}")

    def execute(self, until=None, wait=True):
        for s in self.STAGES:
            if self.done(s):
                log(f"skip {s} (done)")
            else:
                log(f"=== stage: {s} ===")
                getattr(self, f"stage_{s}")(**({"wait": wait} if s == "datagen" else {}))
            if until == s:
                log(f"stopped after '{s}' (--until)")
                return
        log("pipeline complete")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("config", help="pipeline config json (e.g. pipeline_gen3.json)")
    ap.add_argument("--status", action="store_true", help="show progress and exit")
    ap.add_argument("--until", choices=Pipeline.STAGES, help="stop after this stage")
    ap.add_argument("--force", choices=Pipeline.STAGES,
                    help="clear this stage (and all later ones) before running")
    ap.add_argument("--no-wait", action="store_true",
                    help="don't block on datagen; exit and resume later")
    args = ap.parse_args()

    p = Pipeline(args.config)
    if args.status:
        p.status()
        return
    if args.force:
        idx = Pipeline.STAGES.index(args.force)
        for s in Pipeline.STAGES[idx:]:
            p.state.pop(s, None)
        p.state_path.write_text(json.dumps(p.state, indent=2), encoding="utf-8")
        log(f"cleared stages from '{args.force}' onward")
    p.execute(until=args.until, wait=not args.no_wait)


if __name__ == "__main__":
    main()
