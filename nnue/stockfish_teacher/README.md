# Sgurr-StockfishTeacher

This is a separate external-data experiment, using Sgurr's own 768-input,
384-hidden-unit, two-perspective NNUE and unchanged search/inference.

See [the workflow and provenance record](../../docs/STOCKFISH_TEACHER.md).
Start with `tools/stockfish_teacher.ps1 preflight` from the repository root.

- `dataset.json`: pinned source, bytes, SHA-256, licence, label provenance,
  format and transformations, including unknowns.
- `pilot.json`: eight sampled chunks, scale 361, score-only, 2,000 steps.
- `full.json`: approximately 56M accepted unique positions, 27,000 steps,
  and a separate 100-game sanity match; matches Gen8's approximate data volume.
- `common.py`: verified resumable HTTP download, file locks and process checks.
- `records.py`: original .plain adapter, strict validation, statistics,
  duplicate policy and deterministic chunk/game sampling.
- `large_conversion.py`: seven shard converters, seeded chunk order, global
  duplicate removal, target count and durable per-chunk merge checkpoints.
- `train_external.py`: imports the existing Sgurr model, loss and exporter;
  saves optimizer/scheduler/RNG state for resume.
- `workflow.py`: stage orchestration, isolated official converter and Sgurr builds.
- `verification.py`: exporter/forward/selfcheck/identity/move/bench gates.
- `launch_engine.py`, `matches.py`: same-binary paired match harness and audits.
- `tests/`: unit and optional official-converter integration tests.

No changes to `nnue/train.py`, `nnue/nnue_tools.py`, `pipeline.py`, self-play
defaults, existing networks, or Gen9 data are required.

Sgurr-X's authorized sequence is `x_series.json`: 112M/HL384, then
826M/HL384 with eight factorized king buckets, scale 361 and score-only targets.
Run/resume with `.venv\Scripts\python.exe -u nnue/stockfish_teacher/series.py`.
It finishes 800 paired games against each of the previous X net and Gen8
before advancing. Status/logs: `runs/stockfish_teacher/x-scaling-20260906/`.
These are single-seed experiments, without automatic promotion. The second
changes architecture and volume together. Canonical Sgurr remains self-play.
