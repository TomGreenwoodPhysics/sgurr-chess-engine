"""Exporter, independent integer forward, engine identity and legal-move gates."""
import os
from pathlib import Path
import re
import subprocess
import sys
import numpy as np

from common import ROOT, atomic_json, read_json, sha256

sys.path.insert(0, str(ROOT / "nnue"))
sys.path.insert(0, str(ROOT / "testing"))
import nnue_tools as nt
import chesslite as cl

CASES = [cl.START_FEN,
         "8/P7/8/8/8/8/8/K6k w - - 0 1",
         "6K1/8/8/8/8/8/1p6/k7 b - - 0 1",
         "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"]


def forward_float(ftw, ftb, ow, ob, fen, bucket_map=None):
    """Float reference for the coalesced v1/v2 export, including both king views."""
    if bucket_map is None:
        return nt.forward_float(ftw, ftb, ow, ob, fen)
    pieces, stm = nt.pieces_from_fen(fen)
    kings = {c: sq for c, pt, sq in pieces if pt == 5}
    offsets = [int(bucket_map[kings[0]]) * nt.INPUT,
               int(bucket_map[kings[1] ^ 56]) * nt.INPUT]
    acc = [np.array(ftb, dtype=np.float64), np.array(ftb, dtype=np.float64)]
    for colour, ptype, sq in pieces:
        for persp in (0, 1):
            acc[persp] += ftw[offsets[persp] + nt.feat(persp, colour, ptype, sq)]
    return float(np.dot(np.clip(acc[stm], 0, 1), ow[:nt.HL])
                 + np.dot(np.clip(acc[1-stm], 0, 1), ow[nt.HL:]) + ob) * nt.SCALE


def invoke(exe, args=(), text="uci\nisready\nquit\n", net=None, timeout=120):
    env = os.environ.copy()
    env.pop("SGR_EVALFILE", None)
    if net is not None:
        env["SGR_EVALFILE"] = str(net)
    p = subprocess.run([str(exe), *map(str, args)], input=text, text=True,
                       capture_output=True, env=env, timeout=timeout, cwd=ROOT)
    return {"returncode": p.returncode, "stdout": p.stdout, "stderr": p.stderr}


def gate(exe, net, name):
    startup = invoke(exe, net=net)
    if startup["returncode"] or "uciok" not in startup["stdout"] or "readyok" not in startup["stdout"]:
        raise RuntimeError("UCI startup failed")
    if f"id name {name} " not in startup["stdout"] or not loaded_net(startup, net):
        raise RuntimeError("UCI identity/network disagrees")
    moves = []
    for fen in CASES:
        p = invoke(exe, net=net, text=f"uci\nposition fen {fen}\ngo depth 4\nquit\n")
        match = re.search(r"^bestmove (\S+)", p["stdout"], re.M)
        legal = {cl.move_to_uci(m) for m in cl.legal_moves(cl.Position.from_fen(fen))}
        if p["returncode"] or not match or match[1] not in legal:
            raise RuntimeError(f"Illegal/missing bestmove in {fen}")
        moves.append({"fen": fen, "bestmove": match[1]})
    return {"startup": startup, "legal_moves": moves}


def loaded_net(output, expected):
    match = re.search(r"^info string nnue: loaded (.+) \([^)]+\)$", output["stderr"], re.M)
    return bool(match and Path(match[1]).resolve() == Path(expected).resolve())


def verify(w, fixture=False):
    build = w.run / "build"
    receipt = read_json(build / "build.json")
    for name, digest in receipt["binary_sha256"].items():
        if sha256(build / name) != digest:
            raise RuntimeError("Build fingerprint changed")
    net = w._fixture() if fixture else w.net
    if not fixture:
        result = read_json(w.run / "training-result.json")
        if sha256(net) != result["network"]["sha256"]:
            raise RuntimeError("Trained net checksum changed")
    reference = ROOT / "nets/gen8.nnue"
    from workflow import GEN8_SHA
    if sha256(reference) != GEN8_SHA:
        raise RuntimeError("Gen8 changed")
    report = {"scope": "UNTRAINED EXPORT FIXTURE ONLY; not a pilot" if fixture else "External-data pilot",
              "network": str(net), "network_sha256": sha256(net), "gen8_sha256": GEN8_SHA}
    # Gen8 is HL384; the candidate may be another width. Each is checked by a
    # selfcheck binary built at its own width, and nt.HL follows the candidate.
    hl = w.config["training"]["hl"]
    sc = build / "selfcheck.exe"
    sc_net = build / (f"selfcheck-hl{hl}.exe" if hl != 384 else "selfcheck.exe")
    nt.HL = hl
    report["hidden_width"] = hl
    report["selfchecks"] = {}
    for path, exe in ((reference, sc), (net, sc_net)):
        print(f"Selfcheck: {path}", flush=True)
        check = invoke(exe, [path])
        if check["returncode"] or "-> PASS" not in check["stdout"]:
            raise RuntimeError(f"NNUE selfcheck failed: {path}: {check}")
        report["selfchecks"][str(path)] = check
    fens = list(CASES)
    conversion = w.data / "conversion.json"
    if conversion.exists():
        fens += [r["source"]["fen"] for r in read_json(conversion)["independent_samples"]]
    model = nt.load(net)
    if model[4] != w.config["training"]["buckets"]:
        raise RuntimeError("Exported bucket count differs from training configuration")
    floats = np.load(net.with_suffix(".float.npz"))
    export_copy = w.run / ("fixture-export-roundtrip.nnue" if fixture else "export-roundtrip.nnue")
    nt.export(export_copy, **dict(floats))
    if sha256(export_copy) != sha256(net):
        raise RuntimeError("Repeating exporter from saved float weights changed bytes")
    comparisons = []
    for fen in fens:
        raw, cp = nt.forward(model, fen)
        p = invoke(sc_net, [net, "fwd", fen])
        if p["returncode"] or int(p["stdout"].strip().splitlines()[-1]) != raw:
            raise RuntimeError("C++ and Python integer forward disagree")
        float_cp = forward_float(**dict(floats), fen=fen)
        comparisons.append({"fen": fen, "integer_raw": raw, "integer_cp": cp, "float_cp": float_cp, "quantization_error_cp": abs(cp - float_cp)})
    report["export_roundtrip"] = "PASS: byte-identical"
    report["integer_forward"] = comparisons
    report["max_quantization_error_cp"] = max(c["quantization_error_cp"] for c in comparisons)
    report["normal"] = gate(build / "normal.exe", reference, "Sgurr")
    print("Normal engine UCI and legal-move gate passed", flush=True)
    report["external"] = gate(build / "external.exe", net, w.config["edition"])
    print("External engine UCI and legal-move gate passed", flush=True)
    # Actual bare-build default is empty/HCE; do not silently change it to Gen8.
    before = invoke(build / "normal-before.exe")
    after = invoke(build / "normal.exe")
    if before != after or "hand-crafted eval" not in after["stderr"]:
        raise RuntimeError("Normal identity/default network changed from pre-edit main")
    report["normal_default_before_after"] = {"identical": True, "output": after}
    default_external = invoke(build / "external.exe")
    if fixture and not w.net.exists():
        if default_external["returncode"] == 0 or "requires its configured" not in default_external["stderr"]:
            raise RuntimeError("External edition silently fell back without its pilot net")
    elif default_external["returncode"] or not loaded_net(default_external, w.net):
        raise RuntimeError("External default did not load the pilot")
    report["external_default"] = default_external
    report["benches"] = {}
    # Gen8 is HL384, so the edition binary can only bench it when widths match.
    # Otherwise its width-matched twin carries that comparison.
    ext_gen8 = "external.exe" if hl == 384 else "external-gen8width.exe"
    report["external_gen8_binary"] = ext_gen8
    for label, exe, evalnet in [("before_gen8", "normal-before.exe", reference), ("normal_gen8", "normal.exe", reference),
                                ("external_gen8", ext_gen8, reference), ("external_candidate", "external.exe", net)]:
        depth = 4 if fixture and label == "external_candidate" else 10
        print(f"Bench: {label}, depth {depth}", flush=True)
        p = invoke(build / exe, ["bench", str(depth)], net=evalnet)
        if p["returncode"]:
            raise RuntimeError("Bench failed")
        report["benches"][label] = p
    outputs = [report["benches"][k]["stdout"] for k in ("before_gen8", "normal_gen8", "external_gen8")]
    if outputs[0] != outputs[1] or outputs[1] != outputs[2]:
        raise RuntimeError("Identity-only source change altered same-net bench")
    again = invoke(build / "external.exe", ["bench", "4" if fixture else "10"], net=net)
    if again["stdout"] != report["benches"]["external_candidate"]["stdout"]:
        raise RuntimeError("Candidate bench is not deterministic")
    report["same_net_bench_identical"] = True
    report["strength_conclusion"] = None
    atomic_json(w.run / ("fixture-verification.json" if fixture else "verification.json"), report)
    print(json_summary(report), flush=True)
    return report


def json_summary(report):
    import json
    return json.dumps({k: report[k] for k in ("scope", "network_sha256", "export_roundtrip", "max_quantization_error_cp", "same_net_bench_identical")}, indent=2)
