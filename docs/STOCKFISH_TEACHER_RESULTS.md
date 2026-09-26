# Stockfish-teacher experiment results, 6 September 2026

The external-data pipeline is implemented, its small pilot completed, and the
user-requested Gen8-volume comparison completed. Approximately **56M usable
Stockfish positions** were converted to match Gen8's 55,931,801-position
training pool, trained with Gen8's own 27,000-step recipe, and played against
Gen8. It scored **48.0%** over 100 games, which is statistically
indistinguishable from Gen8 at that sample size and a very large improvement
on the 12.5% pipeline pilot. Gen8 remains canonical. No network is promoted by
this workflow.

## Source and provenance

The input is official-stockfish's `wrongIsRight_nodes5000pv2.binpack` at
HF revision `1e095a758c630bc58d0b6dac4da44fcd38ac89c2`:
[pinned download](https://huggingface.co/datasets/official-stockfish/master-binpacks/resolve/1e095a758c630bc58d0b6dac4da44fcd38ac89c2/wrongIsRight_nodes5000pv2.binpack).
It is **Stockfish self-play with Stockfish search labels**, from targeted
openings, not a silently relabelled Lc0 or mixed experiment. The official
historical attribution, candidate comparison and software/licence boundary
are recorded in [the workflow documentation](STOCKFISH_TEACHER.md).

Download: **7,319,926,088 bytes / 6.817 GiB**, completely verified against SHA-256
`54cbbfaf528df4c0198f4788823512c0c2dbba2913075c4022992c74247a9e8e`.
The separate converter source archive adds 368,329 bytes. No additional data
download is needed for 56M accepted records. Expansion of the complete source
was neither performed nor measured; the documentation's 78.1-117.1 GB full
Sgurr-record expansion is only an estimate from typical compression ratios.

The historical exact Stockfish commit/network, full generation command,
adjudication settings and prior filtering remain unknown. Search budget/PV2
are identified by the file and historical documentation. Native score units
are mapped explicitly; they are not assumed to be modern UCI centipawns.
HF states ODbL while the publisher's Kaggle card states CC0; byte equivalence
and redistribution obligations remain unresolved. No data/model release
clearance is claimed. The separate GPL converter retains its original source,
licence and attribution and is absent from Sgurr's runtime.

## Initial pipeline pilot

Run: `pilot-s0-scale361`, eight chunks selected over the whole source by seeded
SHA-256 rank (seed 20260906). Sample compressed bytes: **7,872,876**; expanded
plain text: **239,662,493 bytes**. No source game IDs are available, so no
game-disjoint validation score is claimed and deployment `val_frac=0` is used.

| Conversion outcome | Positions |
| --- | ---: |
| Source records validated | 2,542,955 |
| Accepted unique training records | 1,828,654 |
| Capture/promotion/check filter | 600,460 |
| Extreme mapped score filter | 62,378 |
| Duplicate features removed | 51,463 |
| Invalid records | 0 |

`train.bin` is **58,516,928 bytes**, SHA-256
`843c9320363b0f1b9c1052aedea3b322e68148216b0fb2d6f5dd5357e2a8fe30`.
Side to move: white 914,468 / black 914,186. Phase: opening 80,890,
middlegame 543,815, endgame 1,203,949 (65.8%). Stored STM result distribution:
loss 326,868 / draw 1,178,525 / win 323,261.

All source boards and moves were validated; every accepted record round-tripped.
All eight raw first-stem scalar checks agreed with the official converter.
Sixteen real records were independently reconstructed with `chesslite` and
the existing Sgurr decoder. Complete piece counts, mapped-score histograms,
phase-specific calibration and annotated source examples are in
`data/stockfish_teacher/pilot-s0-scale361/conversion.json`.

A separate read-only 100,000-position sample from Gen8's existing 55,931,801-
record `all.bin` (seed 20260906) contained 38.219% opening, 36.265% middlegame
and 25.516% endgame positions under the same phase definition. Its stored draw
fraction was 15.345%, versus 64.4% in the external pilot. These are descriptive
distribution differences, not proof of why one network wins. The sample
record hash and full counts are retained in
`runs/stockfish_teacher/implementation-audit/gen8-distribution-sample.json`.

In-sample Brier error against stored results was 0.02593 at teacher scale 361
and 0.02429 at scale 250, the lowest tested grid point. This is a diagnostic,
not trusted held-out calibration or playing-strength evidence; adjudication
is unknown. The pilot retained its declared scale of 361.

Training used Sgurr HL384, one bucket, seed 0, batch 16,384, Adam, cosine
LR 1e-3 to 1e-5, **2,000 steps**, lambda **1.0**, runtime scale 400, no holdout,
and checkpoints every 100 steps. Raw score maps to `round(score*400/361)`.
The result component has zero loss weight. This short run was a pipeline
pilot, not a data-volume or training-budget match to Gen8.

On the existing RTX 5080 environment (PyTorch 2.13.0+cu130, NumPy 2.5.1,
python-chess 1.11.2), the training loop took 46.4 seconds. Final minibatch loss
was 0.0104943; it is not a strength measure. Network:
`nets/stockfish_teacher/pilot-s0-scale361/pilot.nnue`, 592,160 bytes, SHA-256
`08d846c523e1863a20ba6ef675f947463e2ea69848912ffccaed70892c3a88aa`.

## Build, correctness and pilot games

Normal, external and pre-edit-reference variants were built with the documented
MSYS2 clang64, PGO and ThinLTO. Both Gen8 and the pilot passed **4,516 NNUE
self-checks each, zero failures**. Export repeated byte-identically. C++ raw
integer forward matched the existing Python/NumPy reference on all 20 known
and real positions; the largest observed float/quantised difference was
29.28 cp. UCI names, loaded networks and legal moves passed, including both
promotion colours. The external engine identifies as `Sgurr-StockfishTeacher
8.2`; the normal engine remains `Sgurr 8.2`.

With Gen8 loaded, pre-edit normal, current normal and external builds all
produced the same **1,857,606-node depth-10 fingerprint**, including all best
moves and scores. The pilot's own 1,754,230-node depth-10 fingerprint repeated
exactly. Normal bare startup still uses its original empty-default/HCE
behaviour; explicit Gen8 loading is unchanged. The external default loads its
own trained net and fails clearly if it is missing.

The final test suite has **25 passing tests**, including the official native
converter integration, interrupted training with bit-identical CPU resume,
cross-chunk duplicates, committed-segment corruption rejection, and rollback
of uncommitted output/dedup writes. Vectorised merge statistics match the
ordinary board-based reference. On real data, the first eight ranked shards
reproduce the original pilot's entire 1,828,654-element feature set exactly;
source/filter/duplicate totals also agree. Record order differs as declared,
so duplicate labels retain the first occurrence in each declared order.

The pilot scored **8 wins, 9 draws and 83 losses in 100 games**, or **12.5%**,
against canonical Gen8. Both arms used the identical external search binary,
with only the Sgurr-exported NNUE changed. Conditions were the pinned UHO book,
50 colour-reversed opening pairs, seed 20260906, 8+0.08, concurrency 7,
Hash 256, Threads 1, no ponder and otherwise idle machine. All five batches
passed legal PGN, complete result, normal termination and paired-opening audits.
There were no crashes, illegal moves or abnormal terminations in the completed
match. Command, binary/book/network hashes, load samples, logs and PGNs remain
under `runs/stockfish_teacher/pilot-s0-scale361/match-*/`.

This is a decisive rejection of this small pilot as a promotion candidate,
not a precise Elo estimate or proof about 56M Stockfish-labelled positions.
The experiment changes data distribution, label source/depth and calibration
as well as training volume and steps, so the result cannot identify one cause.

## Gen8-volume run

Config: `nnue/stockfish_teacher/full.json`; run: `56m-s0-scale361`.
Target: at least 56,000,000 globally unique records after the same filters,
stopping at a whole-chunk boundary. Seven validation processes, seeded chunk
order over the whole source, at most 384 source chunks, durable global merge
checkpoints. This reused the already-downloaded and verified source; no
additional download was needed.

### Conversion

250 chunks were consumed before the accepted target was reached. Conversion
took about 25 minutes end to end.

| Conversion outcome | Positions |
| --- | ---: |
| Source records validated | 81,316,828 |
| Accepted unique training records | **56,119,066** |
| Capture/promotion/check filter | 19,200,403 |
| Extreme mapped score filter | 2,011,032 |
| Duplicate features removed | 3,986,327 |
| — of which cross-chunk duplicates | 2,627,609 |
| Invalid records | **0** |

`train.bin` is **1,795,810,112 bytes** (56,119,066 x 32 exactly), SHA-256
`30093cd41e9de5acae0495d0f27438867b2ba59e01eb42540151afea5bec41b3`.
`val.bin` is empty by design (`val_frac=0`, no source game IDs, no holdout
claimed). The accepted count slightly exceeds 56,000,000 because the run stops
only after the shard that crosses the target is completely merged.

Side to move: white 28,032,433 / black 28,086,633, a 0.10% imbalance.
Stored STM result distribution: loss 10,403,216 / draw 35,422,515 /
win 10,293,335, so 63.1% of stored outcomes are draws. Phase: opening
2,667,142 (4.8%), middlegame 17,204,806 (30.7%), endgame 36,247,118 (64.6%).

This reproduces the pilot's distribution at 30x the scale, and the same caveat
applies with more force: the Gen8 reference sample was 38.2% opening, 36.3%
middlegame and 25.5% endgame with a 15.3% stored draw fraction. **Matching the
position count did not match the position distribution.** That remains the
largest uncontrolled difference between the two training pools.

In-sample Brier error against stored results was 0.02548 at teacher scale 250
and 0.02713 at the configured 361, again lowest at 250 and again only a
descriptive diagnostic on unknown adjudication. Per phase the optimum differs:
opening 361, middlegame 250-300, endgame 250. The run kept its declared scale
of 361 so the comparison stays reproducible against the pilot; the scale
experiment is deliberately left as the next separate run rather than changed
mid-flight. Full statistics are in
`data/stockfish_teacher/56m-s0-scale361/conversion.json`.

### Training

**27,000 steps**, seed 0, batch 16,384, HL384, one bucket, Adam, cosine
LR 1e-3 to 1e-5, lambda **1.0**, teacher scale 361, runtime scale 400,
`val_frac=0`, CUDA, checkpoints every 100 steps. That is 442,368,000 sampled
positions, about **7.9 passes** over the 56,119,066-record pool, and matches
Gen8's step budget rather than only its data volume. Lambda stays explicit and
score-only because the source result adjudication remains unknown.

The loop took **603.2 seconds** on the existing RTX 5080 environment. Final
minibatch loss was **0.0104740**, which is essentially the pilot's 0.0104943
despite 30x the data and 13.5x the steps; loss is not a strength measure and
the near-equality mostly reflects the intrinsic noise of the teacher targets.
Network: `nets/stockfish_teacher/56m-s0-scale361/pilot.nnue`, 592,160 bytes,
SHA-256 `c9704b107890a2c7a83693f3d42a695929be8e5e83d2d36cb571fceecf04901c`.
The file keeps the workflow's fixed `pilot.nnue` name inside its own run
directory; the run ID, not the filename, identifies it.

### Verification

Export round-trip repeated **byte-identically**. Both Gen8 and the candidate
passed **4,516 NNUE self-checks each, zero failures** (`evalsum` -142,859 for
Gen8, -781,404 for the candidate). The C++ raw integer forward matched the
Python/NumPy reference on all known and real positions, largest observed
float/quantised difference **22.22 cp**. Normal, external and pre-edit
reference builds all reproduced the same Gen8 depth-10 bench fingerprint of
**1,857,606 nodes**, and the normal engine's default startup was identical
before and after the edits. The candidate's own depth-10 fingerprint is
**1,565,203 nodes**. UCI identity and legal-move gates passed: the external
engine reports `Sgurr-StockfishTeacher 8.2` and the normal engine still
reports `Sgurr 8.2`.

The full test suite passes: **25 tests, 0 failures**.

### Games against Gen8

The volume-matched network scored **39 wins, 18 draws and 43 losses in 100
games**, or **48.0%**, against canonical Gen8.

| Run | Positions | Steps | W-D-L | Score | Elo (95% CI) |
| --- | ---: | ---: | :---: | ---: | :--- |
| `pilot-s0-scale361` | 1,828,654 | 2,000 | 8-9-83 | 12.5% | -338 |
| `56m-s0-scale361` | 56,119,066 | 27,000 | 39-18-43 | **48.0%** | **-13.9 [-77, +48]** |

Both arms used the identical external search binary with only the Sgurr-exported
NNUE changed, under the pinned UHO book, 50 colour-reversed opening pairs,
seed 20260906, 8+0.08, concurrency 7, Hash 256, Threads 1, no ponder and an
otherwise idle machine. All five batches recorded **20/20 normal terminations**,
100 normal terminations overall, with no crashes, illegal moves or abnormal
endings. Command, binary/book/network hashes, logs and PGNs are under
`runs/stockfish_teacher/56m-s0-scale361/match-*/`.

**How to read this.** At 100 games the 95% interval spans roughly 125 Elo, and
the project's own seed-to-seed variation is about +/-14 Elo, so 48.0% means
this network is **statistically indistinguishable from Gen8** — it is evidence
against a large gap in either direction, not evidence of parity, and certainly
not a promotion case. What it does establish clearly is the volume effect:
moving from 1.8M to 56M Stockfish-labelled positions closed essentially the
entire 338-Elo gap seen in the pilot. The pilot's collapse was a data-volume
and training-budget artefact, not proof that Stockfish-labelled data is
unsuitable for Sgurr's architecture.

It also means the honest headline is modest: **external Stockfish data at
Gen8's volume reproduces roughly Gen8's strength, and has not beaten it.**
Gen8 was trained on Sgurr's own self-play; this network reaches comparable
standing from a completely different, publicly sourced corpus with a markedly
worse phase distribution. That is a meaningful validation of the pipeline and
of the distillation approach, not a strength claim.

## Commands and files

Run from `C:\coding\Sgurr` in PowerShell:

```powershell
function teacher {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\stockfish_teacher.ps1 @args
}
# Small pilot: completed stages verify their receipts and skip work.
teacher preflight
teacher download
teacher tool-setup
teacher test
teacher convert
teacher train
teacher build
teacher verify
teacher match
teacher match-status

# Approximately 56M accepted positions, using the same cached download.
$cfg = 'nnue/stockfish_teacher/full.json'
teacher preflight -Config $cfg
teacher convert -Config $cfg
teacher train -Config $cfg
teacher build -Config $cfg
teacher verify -Config $cfg
teacher match -Config $cfg
teacher match-status -Config $cfg
```

Each stage is sequential within a run. Rerun the same command to resume;
`status` and `match-status` are read-only and can run while another stage runs.
The child-process execution policy does not change the machine policy.
Changing bound settings requires a new run ID. Full resume details are in
[the workflow documentation](STOCKFISH_TEACHER.md).

Existing source files edited for this task:

- `.gitignore`
- `README.md`
- `docs/PROJECT_PROVENANCE.md`
- `docs/THIRD_PARTY_NOTICES.md`
- `sgurr_cpp/main.cpp`

New source/documentation files:

- `docs/STOCKFISH_TEACHER.md`
- `docs/STOCKFISH_TEACHER_RESULTS.md`
- `tools/stockfish_teacher.ps1`
- `nnue/stockfish_teacher/README.md`
- `nnue/stockfish_teacher/dataset.json`
- `nnue/stockfish_teacher/pilot.json`
- `nnue/stockfish_teacher/full.json`
- `nnue/stockfish_teacher/common.py`
- `nnue/stockfish_teacher/records.py`
- `nnue/stockfish_teacher/large_conversion.py`
- `nnue/stockfish_teacher/train_external.py`
- `nnue/stockfish_teacher/workflow.py`
- `nnue/stockfish_teacher/verification.py`
- `nnue/stockfish_teacher/launch_engine.py`
- `nnue/stockfish_teacher/matches.py`
- `nnue/stockfish_teacher/tests/test_pipeline.py`
- `nnue/stockfish_teacher/tests/test_training.py`
- `nnue/stockfish_teacher/tests/test_official_converter.py`
- `nnue/stockfish_teacher/tests/test_matches.py`
- `nnue/stockfish_teacher/tests/test_large_conversion.py`

Generated files are isolated under `data/stockfish_teacher/`,
`runs/stockfish_teacher/` and `nets/stockfish_teacher/`. The complete generated
file inventory, including retained external converter source/licences and
logs, is recorded in `runs/stockfish_teacher/implementation-audit/files.json`.
No source from Stockfish was pasted into Sgurr's proprietary engine.

## Work preservation and next experiment

No commits, staging, pushes or destructive Git operations were performed.
The canonical Gen8 hash remains
`896eb832d74776a42375e7fa152b4e032fff1cf85ba2e529b420fe2d1b4b74bf`.
All pre-existing user-owned source edits and untracked files were preserved.

The user independently resumed Gen9's session `20260906-052359` and later
paused its 16 workers. This task never launched, stopped or changed those
workers, their settings or data. The recorded post-pause state is **33,510,927
positions**, with no datagen process running. The original `active.json`
changed during that user-controlled session, so the initial 28.78M state is
not falsely described as unchanged throughout the conversation. The post-pause
hash/size snapshot is retained for the final audit.

### Recommended next experiments, in priority order

The volume-matched run lands at 48.0%, so the question is no longer whether
this data can work but which of two known, uncontrolled differences is holding
it at parity rather than above it.

1. **Teacher scale 250 versus 361.** The strongest lead. Both the pilot and the
   56M corpus put minimum Brier error at 250, not at the configured 361, and
   the gap widens in the endgame positions that dominate this corpus. Reconvert
   the *same* ranked chunks with `teacher_sigmoid_scale: 250.0`, keeping seed,
   filters, steps and training seed fixed, so only the score mapping moves.
   Board selection must be preserved: `max_abs_cp` filtering happens on the
   mapped score, so a naive scale change would also change which positions
   survive and confound the comparison. Decide it on paired games, not Brier.

2. **Phase distribution.** This corpus is 64.6% endgame and 63.1% drawn; the
   Gen8 reference sample is 25.5% endgame and 15.3% drawn. Resample to Gen8's
   phase proportions at the same 56M accepted volume and rerun unchanged. This
   is now the largest single known difference between the two pools, and it is
   the one most likely to explain a network that evaluates quiet endgames well
   but is no better than Gen8 overall.

3. **Confirm before believing anything.** 100 games cannot separate -14 Elo
   from zero. Any candidate that looks promising in a sanity match needs a
   proper SPRT under the established gate and repetition over multiple training
   seeds, given the project's +/-14 Elo seed variation.

4. **Longer term.** A broader Stockfish UHO corpus (`nodes5000pv2_UHO.binpack`,
   40.3 GB) is the natural scale-up but needs an explicit larger-download
   decision and its own provenance record. Resolve result semantics before any
   lambda 0.9 experiment, and redistribution terms before any external release.

A mixed candidate combining Gen8 self-play with Stockfish-labelled external
data is also now worth considering, since the external pool has demonstrated it
can reach comparable standing on its own.
