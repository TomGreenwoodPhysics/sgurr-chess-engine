# King-bucket sweep, prediction registered before the matches

Written 2026-09-21 20:2x, after the trainings and before any of the three
matches reported a result. Rule 7 of `docs/METHODOLOGY.md`.

## Inputs

- Sgurr-X 512, plain 768, vs v9.0: **+86.50 +/- 20.97**
- kb10 vs that same plain 512: **+20.87 +/- 16.79**
- Earlier project result: king buckets ~0 twice at ~7M positions per bucket

## Predictions, all vs v9.0

| candidate | positions/bucket | predicted | band |
|---|---|---|---|
| kb10 | 123M | **+100** | +85 to +115 |
| kb16 | 77M | **+100** | +80 to +120 |
| kb32 | 39M | **+92** | +70 to +115 |

kb10 is below the naive +107 sum of its two parts: Elo does not add cleanly
across different baselines, and both inputs were positive measurements, so
both are likely a little high.

kb16 and kb32 are predicted flat against kb10, not better. The threshold that
mattered sits somewhere between 7M and 123M positions per bucket; 77M and 39M
are both still above where it broke, so extra buckets should buy capacity that
the 768-input feature set cannot use.

## What this cannot settle

kb10 is +/-17 and kb16/kb32 are +/-22, so a kb16-vs-kb10 comparison carries a
joint error near +/-28. **Any true difference between bucket counts smaller
than ~28 Elo is invisible at these sample sizes.** Only a large effect will
show.

## Falsification

- kb32 beating kb10 by more than the joint error: bucket count is still the
  binding constraint and 48/64 are worth testing.
- kb32 clearly below kb10: the floor lies between 39M and 123M per bucket, and
  10-16 buckets is the right range to settle on.
- kb10 below +70: the two component measurements do not compose, and the
  stacked figure should not be quoted from them.
