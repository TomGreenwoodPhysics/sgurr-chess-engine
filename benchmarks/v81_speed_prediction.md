# v8.1 vs v8.0 — prediction, registered before the run

Written **2026-08-02**, before any games were played.

---

## What is being measured

v8.1 is the released v8.0 searcher, compiled better and with nine
node-identical data-layout changes. Verified at fixed depth against the shipped
`sgr_gen8.exe` on three positions:

```
info depth 12 score cp 51    nodes 302338   pv e2e4
info depth 12 score cp -169  nodes 669962   pv e2a6
info depth 12 score cp 340   nodes  73272   pv b4f4
info depth 14 score cp 340   nodes 263353   pv b4f4
```

Identical node counts, identical scores, identical moves. **The only difference
between the two binaries is speed.**

| | |
|---|---|
| PGO + ThinLTO build | +11.3% |
| Stage A, nine optimisations | +7.98% |
| compounded | **≈ +20% NPS** |

---

## The question

`METHODOLOGY.md` §5 lists the AVX-512/int16 inference at "~+22% NPS (≈+15 Elo,
*inferred*)" and flags it explicitly: converted through the ~70 Elo per
doubling rule rather than measured in games. It calls it "the most mechanically
defensible inference in the project, and still an inference."

Every speed gain since has been valued the same way. **None has ever been
checked against games.** The current rating therefore rests, in part, on an
untested conversion constant.

This is the only clean opportunity to test it. Once Stage C changes the search,
speed and behaviour are confounded permanently.

---

## Prediction

**+18 to +19 Elo. Confidence ~55% that the measured value lands in
[+10, +27].**

Arithmetic: 70 × log₂(1.20) = **+18.4 Elo**.

Measured as a fixed 4,000-game match rather than an SPRT. The question is
"by how much?", which wants a confidence interval, not an accept/reject
verdict — and early stopping saves nothing on an idle machine. 4,000 games
gives roughly **±10 Elo** at 95%.

### What each outcome means

| measured | reading |
|---|---|
| **+10 to +27** | rule holds. Release v8.1; future speed work stays trustworthy |
| **+28 or more** | speed is worth MORE than assumed here. Re-rank the roadmap — the remaining NPS items get more attractive, staged movegen especially |
| **+3 to +9** | rule overstates by roughly half at this depth and control. Past speed work was oversold, though still positive. Release anyway, and revalue the backlog |
| **below +3** | the conversion rule does not hold for this engine. A significant negative result: the AVX-512 and PGO gains would need restating in the ledger as unmeasured, and the roadmap's whole speed tier drops in priority |
| **negative** | something is wrong with the experiment, not the engine. Two node-identical binaries cannot differ in strength except through speed — suspect the net, the binaries, or the harness before believing it |

### Why only ~55%

The 70-per-doubling figure is a community rule of thumb calibrated on engines
and time controls that are not this one. It is known to shrink at higher depth
and to vary with time control. At 8+0.08 this engine reaches roughly depth
14–18, which is neither the shallow regime where extra speed pays most nor the
deep regime where it saturates.

A ±10 interval also cannot separate +18 from +12 or +25. This tests whether the
rule is *roughly* right, not whether the constant is exactly 70. Claiming more
than that from 4,000 games would be the same overreach the noise-floor result
already caught once.

---

## Falsification

The prediction is wrong if the measured value falls outside **[+10, +27]**.

A result below +3 would be the interesting failure: it would mean several
banked "free Elo" gains were never free, and `METHODOLOGY.md` §5 would need a
correction row rather than a footnote.
