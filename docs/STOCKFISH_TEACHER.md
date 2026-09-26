# Sgurr-StockfishTeacher: external-data experiment

Sgurr-StockfishTeacher trains Sgurr's own NNUE using public external evaluations.
It is still Sgurr: move generation, search, time management, colour-relative
piece-square features, 768 -> 384 shared feature transformer, two-perspective
output, quantisation and incremental accumulator all remain Sgurr's. It is
**not self-contained or exclusively trained on Sgurr self-play**. Stockfish is
the evaluation teacher in the dataset, not the engine running at inference.

The normal line and `nets/gen8.nnue` remain canonical. The unsuccessful
Gen9-20M promotion candidate is not the baseline for this experiment. Nothing
in this workflow starts, stops, repairs or resumes Gen9. It does not invoke
`pipeline.py` or any Gen9 launcher.

## Dataset decision, checked 6 September 2026

The chosen file is **`wrongIsRight_nodes5000pv2.binpack`**, published by
official-stockfish and uploaded by vondele, from
[the official Hugging Face collection](https://huggingface.co/datasets/official-stockfish/master-binpacks).
Revision: `1e095a758c630bc58d0b6dac4da44fcd38ac89c2`.
The [upload record](https://huggingface.co/datasets/official-stockfish/master-binpacks/commit/8987f266dd27b8a2942ef10a7e502e77273d8fa5)
pins its exact size and LFS SHA-256. The machine-readable authority for this
workflow is [`dataset.json`](../nnue/stockfish_teacher/dataset.json).

The [Stockfish network update of 29 November 2021](https://github.com/official-stockfish/Stockfish/commit/e4a0c6c75950bf27b6dc32490a1102499643126b)
explicitly identifies this component as Stockfish data, separately from the
Leela T60/T74 components and tablebase-rescored Farseer data. The
[official training-dataset wiki](https://github.com/official-stockfish/nnue-pytorch/wiki/Training-datasets)
describes the targeted self-play component as originating from openings
Stockfish usually gets wrong. The stated experiment is therefore genuinely
Stockfish-labelled self-play, with a **targeted opening distribution**. A
sample spread across this file is representative of this file, not of all
chess or every Stockfish dataset.

The filename identifies 5,000-node, PV2 generation. The original complete
generator command, exact Stockfish commit/network, adjudication settings and
post-generation filters have not been established. The workflow does not
invent them. In particular, the pinned converter revision is **not** claimed
to be the historical labeller revision.

Candidates were distinguished as follows:

| Artefact | Compressed bytes | Origin/labels and decision |
| --- | ---: | --- |
| `wrongIsRight_nodes5000pv2.binpack` | 7,319,926,088 | Stockfish self-play/search labels, historically attributed; chosen. |
| `nodes5000pv2_UHO.binpack` | 40,292,454,358 | Official wiki identifies Stockfish generation at 5,000 nodes; exceeds the initial download limit. A useful broader later candidate, requiring approval. |
| `dfrc_n5000.binpack` | 37,483,192,507 | Stockfish generation from DFRC openings; above the limit and requires separate Chess960 suitability work. |
| `wrongNNUE_02_d9.binpack` | 5,781,185,404 | Older candidate; exact standalone provenance was less well established in this inspection. Smaller size alone was insufficient to prefer it. |
| `fishpack32.binpack` | 5,579,166,857 | Smallest collection file; standalone origin/label chain not established. Not selected by guessing from its name. |
| `training_data_pylon.binpack` | 14,366,468,016 | Leela T60/T74-derived data, not a pure Stockfish teacher. |
| `farseerT76.binpack` | 6,141,321,549 | Lc0-derived family; no established Stockfish-search relabelling for this artefact. Future separately named experiment only. |
| `T60T70wIsRightFarseer.binpack` | 32,981,564,118 | Explicit mixture of Lc0-derived data and Stockfish self-play. Not a pure Stockfish teacher. |

[Stockfish's Pylon training record](https://github.com/official-stockfish/Stockfish/commit/8ec9e108664ce38fa98ccfb69f048d7d804f99f9)
identifies its Leela origin. Lc0 data converted with the Lc0 rescorer can include
tablebase corrections; that is not evidence that Stockfish produced its search
scores. No sufficiently documented standalone Lc0-position/Stockfish-search-
rescored artefact was selected here. Stockfish's use of a dataset and the
engine that produced its labels are separate facts. RobotMoon was consulted
for historical context; downloads use the official publisher.

The source download is **6.817 GiB** and its verified SHA-256 is
`54cbbfaf528df4c0198f4788823512c0c2dbba2913075c4022992c74247a9e8e`.
The separately pinned converter source archive is 368,329 bytes. Total initial
downloads stay below 20 GiB. Full expanded position count is unknown. Using
the official tool README's approximate 2-3 bytes per generated position gives
an indicative **78.1-117.1 GB** of Sgurr records for the full file; this is an
estimate, not a measured count. The workflow never implicitly expands it all.
The pilot indexes every chunk and expands only eight deterministic selections.
The follow-on experiment targets **56 million unique accepted positions**,
matching Gen8's approximate volume, from the same verified download.
Exact sample, text and 32-byte output sizes are recorded in the run artefacts.

## Licences and the software boundary

The official HF dataset metadata states **ODbL**. The
[same publisher's Kaggle card](https://www.kaggle.com/datasets/joostvandevondele/wrongisright-u-nodes5000pv2)
says CC0, but byte equivalence was not checked; this workflow records and uses
the HF ODbL attribution. Sgurr's proprietary licence does not relicense the
external database or its converted records.

The [ODbL text](https://opendatacommons.org/licenses/odbl/1-0/) distinguishes
database rights, contents, derivative databases and produced works, with
notice and share-alike conditions for applicable public uses. This internal
experiment does not clear redistribution of its data or models. Resolve the
licence-label discrepancy and the obligations for the proposed model/data
distribution before any external release. No claim is made that conversion
or training removes those obligations.

The GPL Stockfish converter is compiled from the unmodified `tools` archive
at `9a4c7cf4e311f8d9526b79295b80c4d0464c07cf` in the ignored cache, with its
complete source, `Copying.txt` and `AUTHORS` retained. `NNUE_EMBEDDING_OFF`
avoids downloading a Stockfish network. It is called only as a standalone
conversion subprocess. None of its search or loader implementation is pasted
into Sgurr or linked into the Sgurr engine. The adapter was written for the
documented framing and text interchange. Installed python-chess is used for
development-time validation; see [third-party notices](THIRD_PARTY_NOTICES.md).

## Representation, filtering and calibration

The [pinned binpack documentation](https://github.com/official-stockfish/Stockfish/blob/9a4c7cf4e311f8d9526b79295b80c4d0464c07cf/docs/binpack.md)
defines compressed stems and move/score continuations. Chunk lengths are
little-endian; stem score/result fields use a signed-to-unsigned mapping and
big-endian words. Scores and stored -1/0/+1 results are side-to-move relative.
The official tool's generator writes native search `Value` scores, and the
converter preserves them. These are not assumed to be today's normalised UCI
centipawns. The exact historical labeller's pawn normalisation is unknown.

The adapter independently checks each selected chunk's first score/result/
ply/rule50 against the raw stem bytes, then parses official `.plain` output.
Every record must have a legal orthodox board with exactly one king per side,
valid metadata and a legal source move. Malformed input fails the conversion,
leaving an explicit failure report and no published training file. Source
castling, en-passant and move legality are checked before discarding metadata
that Sgurr's NNUE features do not use.

Sgurr records use a1=0, ascending occupied squares, `PNBRQKpnbrqk` codes
0..11, low nibble first, stm 0/1, little-endian signed mapped cp, result
`source_result+1`, and zero padding. Every accepted board and its numeric fields
round-trip through the new decoder. Sixteen deterministic real examples are
also reconstructed independently through Sgurr's existing `chesslite` and
`nnue_tools.decode_record`, with FENs, board diagrams and record hex retained.
Tests cover both sides, negative scores, castling, en passant, promotions and
malformation. The official converter round-trip reconstructs FEN fullmove
from the stored ply field; this metadata normalisation is expected.

Pilot filters are explicit: source ply >=8, not in check, source best move
not a capture/promotion, and absolute **mapped** score <2,000 cp. Duplicate
piece-placement+stm keys are dropped deterministically across the selected
sample, keeping the first retained label. This identifies equal Sgurr input
features, even if castling rights or other chess-state metadata differ. It is
not a claim that those positions have identical search values. Counts and
distributions are reported before interpreting training performance.

Sampling ranks every complete chunk using SHA-256 of its index and seed,
then takes the smallest eight ranks. It does not take a source prefix or stop
after the first million acceptable positions. Compression chunks contain
complete compressed chains but do not certify original whole-game boundaries.
No game IDs are present, so the selected pilot uses **val_frac=0**. The generic
text adapter can assign explicit stable game IDs to deterministic disjoint
splits; it refuses a nonzero holdout when IDs are absent rather than inferring
games from ply resets. The pilot calibration table is an in-sample description,
not a game-disjoint validation metric.

Teacher calibration is configurable and separate from the runtime scale:

```
mapped_sgurr_cp = round(raw_teacher_score * 400 / teacher_sigmoid_scale)
target = lambda * sigmoid(mapped_sgurr_cp / 400) + (1-lambda) * stored_result
prediction_probability = sigmoid(model_output)
runtime_cp = quantized_model_output * 400
```

The pilot starts at teacher scale **361**, a provisional value also used as
the initial guess in the [official sigmoid fitter](https://github.com/official-stockfish/nnue-pytorch/blob/master/perf_sigmoid_fitter.py).
It is not claimed to be calibrated for this dataset. Rounding introduces at
most 0.5 Sgurr cp before training. Conversion reports Brier error against
stored outcomes at scales 150, 200, 250, 300, 361, 400, 500, 600 and 800,
score/result bins and phase-specific tables. These diagnose scale mismatch;
they do not automatically choose a scale or establish strength. Unknown
adjudication makes a fitted result curve provisional as well.

The first pilot is **score-only, lambda=1.0**. Real result bytes are retained
for inspection, never replaced with fabricated labels, but contribute zero
weight to its loss. Lambda 0.9 is refused unless the dataset manifest explicitly
records trustworthy result provenance. Normal Sgurr training defaults are
unchanged: neither `train.py` nor `nnue_tools.py` was edited. The external loop
imports their existing NNUE, decoder, loss and exporter.

## Reproduce and resume

Use the existing `.venv` and documented MSYS2 clang64 compiler. Run from
`C:\coding\Sgurr` in PowerShell. `preflight` prints resolved paths, size and
disk space, verifies canonical Gen8 and the independent opening book, and
reports competing processes. Every PowerShell invocation creates a persistent
log under the selected run. Stage subprocess logs are retained alongside it.

```powershell
function teacher {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\stockfish_teacher.ps1 @args
}
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
```

This machine disables direct `.ps1` execution. The invocation above selects an
execution policy for that child PowerShell process only; it does not change
the machine's policy. Each stage can also be called directly with
`.venv\Scripts\python.exe nnue\stockfish_teacher\workflow.py <stage>`.

The pilot config is `nnue/stockfish_teacher/pilot.json`: seed 0, batch 16,384,
2,000 optimiser steps, Adam, cosine LR 1e-3 -> 1e-5, lambda 1, scale 361,
HL384, one bucket, deployment val_frac=0, checkpoint every 100 steps. This is
a bounded plumbing/strength pilot, shorter than the approximately 27,000-step
normal deployment recipe. Exact software, device, code and data hashes enter
the training identity; deterministic epoch permutations and saved model,
Adam, scheduler and RNG state make interruption resumable within that identity.
Changing data, scale, code, environment or hyperparameters requires a new run ID.

Rerun the same stage after an interruption. The downloader checks identity,
Range/Content-Range/ETag/size and final SHA-256 before publishing its partial
file. A changed or corrupt existing artefact is preserved and rejected.
Official conversion resumes at completed chunk files. The streaming Sgurr
adapter restarts its own temporary output/dedup index from the pinned plain
chunks, not the network download. For the 56M run, validation is sharded over
seven processes. Completed shards are immutable; only an interrupted shard
restarts its own validation. The global duplicate index and merge checkpoint
commit after each complete shard. Output is flushed before the database commit;
resume verifies committed segment hashes and truncates only this run's
uncommitted temporary tail. Statistics and duplicate counts resume exactly.
A crash at the final multi-file publication
boundary can leave an unmanifested output; that state is rejected and preserved.
Choose a new run ID to recover that unusual case. OS file locks release when
a process exits, so stale PID files do not need deleting.

Training resumes the last complete checkpoint; at most 99 pilot steps are
replayed. Match completion is stored in ten-opening/twenty-game batches.
Interrupted attempts and their logs/PGNs are preserved, while the entire
unfinished batch is replayed. Only completed colour-paired batches enter the
summary. Repeating a finished stage checks its hashes and skips completed work.

All generated files are ignored in these separate locations:

```
data/stockfish_teacher/cache/                 downloads and separate GPL tool
data/stockfish_teacher/pilot-s0-scale361/      selected chunks, plain files, records, statistics
runs/stockfish_teacher/pilot-s0-scale361/      checkpoints, build/verification/match records
nets/stockfish_teacher/pilot-s0-scale361/      Sgurr pilot and float export parameters
```

For the Gen8-volume comparison requested after the pilot, use the separate
config below. Gen8 used **55,931,801 clean positions** (DEVLOG, 29 July) and its
pipeline config targets 55.9M. The methodology's 14M/28M/56M experiments show
why the small pilot cannot answer the comparable-volume strength question.

`full.json` targets **at least 56,000,000 positions after filtering and global
duplicate removal**, stopping at the end of the complete chunk that crosses
the target. All source chunks are ranked by seeded SHA-256; workers may finish
in any order, but the merger always uses rank order. Up to 384 chunks are
allowed, with only seven in flight. A few prefetched unused shards can finish
and remain in the cache; they do not enter the final training file. This avoids
mistaking source position count for usable training volume or taking an
ordered source prefix. The exact selected indices and final count are retained.

The run reuses the 6.817 GiB download, trains from scratch for **27,000 steps**
(approximately eight epochs at this volume), and keeps scale 361/lambda 1
explicit. No larger download is needed. At 56M, the final Sgurr records occupy
about **1.792 GB**; source text, validated shards, raw-score sidecars and global
duplicate index take additional space. Preflight reserves a conservative
109.9 GB for the bounded conversion; actual sizes enter the results record.

```powershell
$cfg = 'nnue/stockfish_teacher/full.json'
teacher preflight -Config $cfg
teacher convert -Config $cfg
teacher train -Config $cfg
teacher build -Config $cfg
teacher verify -Config $cfg
teacher match -Config $cfg
```

Use the `teacher` function defined above. If the pilot download/tool setup has not been run, add `download` and
`tool-setup` with the same `-Config $cfg` before conversion. The broader
40,292,454,358-byte UHO artefact is outside the initial authorisation; no
command here downloads it. A future dataset manifest and approval are needed.

## Engine and game verification

`build` uses clang64, PGO and ThinLTO, under the isolated run build directory.
It creates a normal build and an external build from the same source. The
external identity is `SGR_ENGINE_NAME` from the config's `edition`, defaulting
to `Sgurr-StockfishTeacher`; the normal macro default stays `Sgurr`.
`SGR_REQUIRE_NET=1` makes the external build fail clearly if its configured
Sgurr-exported network is absent. `SGR_EVALFILE` still overrides the path.

The bare normal source build actually has an empty default network path and
falls back to HCE; canonical release/testing uses Gen8 explicitly. Verification
compares the pre-edit and current normal main builds, proving this default and
the normal UCI identity are unchanged. It also verifies normal+Gen8 explicitly.
No existing executable is replaced. The added external startup branch may
discard the normal `main` PGO counters; search code and its profile are shared.

`verify` requires a completed trained pilot. It repeats export from saved float
weights and compares bytes, checks C++ raw forward against the existing NumPy
reference on known and real FENs, runs NNUE incremental selfchecks for Gen8 and
the candidate, checks UCI name/network and legal moves, and compares fixed-depth
bench fingerprints. With Gen8, pre-edit normal/current normal/external builds
must have identical fingerprints. The candidate's fingerprint can differ
because its evaluation changes, but must repeat exactly.

Before a trained pilot is available, `build` and `verify-fixture` can use the
explicitly labelled **untrained exporter fixture** under
`nets/stockfish_teacher/verification-only/`. It is not an external-data-trained
model and cannot enter the match stage. Fixture results do not satisfy the
pilot strength gate.

Matches compare **the identical external search executable** with only the
network changed to pilot versus canonical Gen8. The transparent Python
launcher sets each child's network and hands it the match pipes directly;
there is no Python protocol forwarding or Stockfish runtime. Both arms use
the same launcher. Fastchess conditions are pinned: `UHO_4060_v4.epd` SHA-256
`3f499996ff0b674a04f85f2634811d102dd53b5115841e8f11d18e1f550ba2ca`, colour-reversed
openings, 8+0.08, concurrency 7, Hash 256, Threads 1, no ponder, 250-move cap.
Both configs initially run 50 opening pairs/100 games as a sanity check.
Neither is a promotion SPRT or a precise Elo measurement.

Training and match launch refuse while Trackmania, datagen or another
fastchess process is running. Match batches additionally sample CPU/GPU idle
load; new named competing work interrupts the batch. They never stop another
application. PGNs are parsed for legal moves, complete results, paired colours
and abnormal terminations before scores are summarised. Unknown warnings are
fatal; only known PV-beyond-repetition/fifty-move warnings are exempted.

## Evidence needed next

Measured implementation results are in
[`STOCKFISH_TEACHER_RESULTS.md`](STOCKFISH_TEACHER_RESULTS.md). A small sanity
match can reveal crashes, disastrous evaluation, or an encouraging direction;
it cannot support a precise Elo claim. Training loss cannot promote a model.
Gen8 stays canonical regardless of the pilot outcome.

The 1.83M/2,000-step pilot passed correctness gates but lost heavily to Gen8,
at 12.5% over 100 games. The user requested the 56M/27,000-step comparison to
address the clear data volume and training-budget differences. That run
completed and scored 48.0% over 100 games, which is statistically
indistinguishable from Gen8 at that sample size: the pilot's collapse was
predominantly a volume and training-budget artefact. It is not a promotion
case, and 100 games cannot separate -14 Elo from zero.
Next, compare teacher scales under the same data, seeds, steps and games.
Keep distribution and label-search-depth differences visible; matching the
position count alone does not isolate the effect of the teacher engine.
Repeat promising configurations with
multiple training seeds: the project's roughly +/-14 Elo seed variation means
small single-seed gains are weak evidence. Establish a stronger result across
seeds and sufficient paired games before considering a larger download or any
separate external-data release. Resolve result provenance before trying the
more comparable lambda=0.9 blend.
