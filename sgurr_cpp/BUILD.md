# Building Sgurr C++

## Compiler

Use **clang** from the MSYS2 `clang64` environment:

    /c/msys64/clang64/bin/clang++

> **Do not use the MSYS2 UCRT64 `g++ 16.1.0`.** That build miscompiles
> libstdc++ `std::fstream` construction at `-O1` and above, so any optimised
> binary segfaults as soon as it loads a network (`nnue.cpp`) or opens a
> datagen output file (`datagen.cpp`). clang (libc++) is unaffected. Add
> `/c/msys64/clang64/bin` to `PATH`, or invoke it by full path as below.

## Use `build.sh`

    ./build.sh                    # dev build      -> sgr.exe
    ./build.sh -r                 # release build  -> sgr.exe   (PGO + ThinLTO)
    ./build.sh -d                 # datagen build  -> datagen.exe (RFP disabled)
    ./build.sh -r -o sgr_v8_1.exe # choose the output name

It runs the recipes documented below **and then proves the binary starts**,
relinking automatically if it does not. That second part is not optional here:

> **Smart App Control is enforced on this machine** and intermittently refuses
> to start freshly linked unsigned binaries, roughly 2 builds in 6 during one
> session. The block lands on the *file*, not the code: two byte-identical
> binaries under different names, one blocked and one not. It has **no
> exclusion mechanism**, and turning it off is a **one-way switch** (Windows
> cannot re-enable it without an OS reset). A fresh link is normally allowed
> through, and once a binary has started it keeps starting: so relink-and-recheck
> is both the cheap fix and the complete one.

Skipping the check is expensive. A non-spawning engine does not crash a match:
it forfeits every game and still produces a complete, plausible result. DEVLOG
2026-07-29 lost a calibration gauntlet to a transient block 32 seconds in.
`testing/sprt.py` and `pipeline.py` now verify every binary before playing, but
catching it at build time is cheaper still.

The sections below document what the script does, and remain the reference for
building by hand.

## Engine

There is a single engine binary. It uses the hand-crafted evaluation (HCE)
when no network loads, and the NNUE when a network is provided via
`$SGR_EVALFILE` (default `sgurr.nnue` in the working dir). `nnue.cpp` must
always be linked, since the evaluation references `nnue::` symbols even when
no net is loaded.

### Development build (fast to compile)

    /c/msys64/clang64/bin/clang++ -std=c++20 -O3 -march=native -DNDEBUG -static \
        -Wall -Wextra main.cpp board.cpp evaluation.cpp search.cpp nnue.cpp \
        -o sgr.exe

`-static` makes the binary standalone (no clang64 DLLs needed on PATH), which
is convenient for the SPRT harness.

`-march=native` also enables the vectorised NNUE path (`SGR_SIMD`, default
on): AVX-512 when the target has it (Zen 4+, prints `(avx512)` at startup),
AVX2 otherwise (`(avx2)`). It is ~22% faster than and bit-identical to the
scalar eval. Add `-DSGR_SIMD=0` only to build the scalar fallback for an A/B
(prints `(scalar)`). A build for a pre-AVX2 CPU must pass `-DSGR_SIMD=0`
(the SIMD path `#error`s without AVX2). The startup line always names the
active path, check it when a build seems slow.

### Release build: PGO + ThinLTO (**+11.3% NPS**, measured)

Anything released, calibrated, or used as an SPRT baseline should be built
this way. It changes no source and no search behaviour: it is purely faster.

**ThinLTO** lets the optimiser see across `.cpp` boundaries at link time,
which plain per-file compilation cannot. **PGO** replaces the compiler's
guesses about which branches are hot with a recording of which branches this
engine actually takes, so the common paths get laid out for the instruction
cache. Search is extremely branch-heavy, so PGO carries most of the win.

    C=/c/msys64/clang64/bin/clang++
    F="-std=c++20 -O3 -march=native -DNDEBUG -static -Wall -Wextra"
    S="main.cpp board.cpp evaluation.cpp search.cpp nnue.cpp"

    # 1. instrumented build
    $C $F -fprofile-generate=./pgo $S -o sgr_prof.exe

    # 2. run a representative workload (bench is exactly that)
    SGR_EVALFILE=../nets/gen8.nnue ./sgr_prof.exe bench 13

    # 3. merge the raw profile
    /c/msys64/clang64/bin/llvm-profdata merge -output=pgo/sgurr.profdata pgo/*.profraw

    # 4. final build
    $C $F -flto=thin -fuse-ld=lld -fprofile-use=./pgo/sgurr.profdata $S -o sgr.exe

Notes:

* **Regenerate the profile after significant search changes.** clang will warn
  `function control flow change detected (hash mismatch)` and silently drop the
  profile for any function whose shape moved, so a stale profile quietly
  degrades to a plain build for exactly the code you just edited.
* `pgo/` is gitignored. The profile is a build artefact, not source.
* Full LTO (`-flto=full`) and a broader profile (bench at several depths) were
  both measured and neither beat this recipe: all three sat inside the
  measurement noise. ThinLTO is chosen for the faster incremental link.

**Measured on a 7800X3D against the plain `-O3 -march=native` build**, 12
interleaved runs each of `bench 13`, gen8 net:

| build | median NPS |
|---|---|
| `-O3 -march=native` | 2,736,898 |
| **+ PGO + ThinLTO** | **3,045,808** |

**+11.3%**, and the separation is clean: the *slowest* PGO run (2,990,742)
beat the *fastest* baseline run (2,775,630), so the two distributions do not
overlap across 24 runs. At the project's ~70 Elo per doubling that is
**≈ +10.8 Elo, inferred** (an inference from NPS, like the SIMD result: not
a number measured in games).

The `bench` fingerprint is byte-identical between the two builds, which is
what makes the speedup free rather than a behaviour change (see below).

## Datagen

    /c/msys64/clang64/bin/clang++ -std=c++20 -O3 -march=native -DNDEBUG -static \
        datagen.cpp board.cpp evaluation.cpp search.cpp nnue.cpp \
        -o datagen.exe

See the header of `datagen.cpp` for arguments (fixed depth vs `nodes:N`).

> **Labeller builds must pass `-DSGR_RFP=0`.** Reverse futility pruning returns
> a raw static eval where a searched score is expected; under a fixed node
> budget that poisons the labels. It cost gen6 an entire cycle.

PGO applies here too, and matters more than it does for the engine: datagen
is a multi-day CPU-bound job. Generate a *datagen* profile rather than reusing
the engine's: the engine profile has no entry for `datagen.cpp`'s `main`, so
clang warns and discards it for that function (the shared search/board/nnue
code still benefits).

## Verifying a build

    ./sgr.exe bench

`bench` searches a fixed position set to a fixed depth. The search is
deterministic, so its node counts are a fingerprint of search behaviour. Any
change meant to be **speed-only** (the flags above, SIMD, a refactor) must
leave the fingerprint byte-identical:

    diff <(old.exe bench 2>/dev/null) <(new.exe bench 2>/dev/null)

The fingerprint is on stdout; wall time, NPS and the loaded net go to stderr,
so the diff compares only the deterministic part. If the fingerprint moves,
the change altered *what* is searched rather than only how fast, and the
speedup is not free.
