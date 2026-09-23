# SCReLU, prediction registered before the match

Written 2026-09-22, implementation done, no games played. Rule 7 of
`docs/METHODOLOGY.md`.

## Prior from measured results elsewhere

Isolated CReLU -> SCReLU tests on single-hidden-layer 768 -> N -> 1 nets:

| engine | HL | Elo | games | note |
|---|---|---|---|---|
| Leorik 3.0.14 | 640 | +17.1 +/- 4.2 | 9751 | cleanest: same arch, same data, activation only |
| Viridithas PR#19 | **512** | +35.8 +/- 11.6 | 1918 | our exact architecture, same data as prior net |
| Renegade | 384 | +15.7 +/- 9.3 | 2936 | |
| akimbo | 512->768 | +30.6 +/- 10.0 | 2848 | confounded with a width change |

Median ~+17. The Leorik number is the one to anchor on: 9,751 games and
genuinely isolated.

Contrary evidence exists but does not apply here. Obsidian moved OFF SCReLU at
1536 HL with pairwise multiplication (+3.18 +/- 2.10 over 29,514 games for
removing it). The sign flips at large width; at 512 we are in the regime where
it wins.

## Prediction

**+18 Elo, band +5 to +35**, screlu vs crelu, both HL=512, same S1 data, same
40 superbatches, 1000 games at 8+0.08.

Below the +35.8 measured at our exact width because that test ran only 1918
games, and because four predictions registered in the last two days have all
come in under their point estimate.

## The risk is NPS, not the net

Calvin measured 1.7M -> 1.0M nps on a naive SCReLU and scored **-86 Elo** at
STC before fixing the SIMD, then +57 after. Our implementation uses the
mullo-then-madd trick from the start rather than i32 widening, so the extra
cost should be one `mullo` per vector in the output loop, which is a small part
of total eval cost.

**Falsification: if NPS drops more than ~10%, the implementation is wrong, not
the idea.** Check NPS before reading the Elo.

## Known follow-up, deliberately not in this test

Renegade measured **+26.4 +/- 12.5** from re-tuning QA 255 -> 181 *after*
switching to SCReLU -- more than the activation switch itself gained. 181 is
roughly 255/sqrt(2), and 181^2 = 32761 just fits int16. QA is a compile-time
constant that the net header records and the loader validates, so changing it
means retraining and rebuilding together. Worth doing, separately, once SCReLU
itself is measured.
