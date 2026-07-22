# Building Sgurr C++

## Compiler

Use **clang** from the MSYS2 `clang64` environment:

    /c/msys64/clang64/bin/clang++

> **Do not use the MSYS2 UCRT64 `g++ 16.1.0`.** That build miscompiles
> libstdc++ `std::fstream` construction at `-O1` and above, so any optimised
> binary segfaults as soon as it loads a network (`nnue.cpp`) or opens a
> datagen output file (`datagen.cpp`). clang (libc++) is unaffected. Add
> `/c/msys64/clang64/bin` to `PATH`, or invoke it by full path as below.

## Engine

There is a single engine binary. It uses the hand-crafted evaluation (HCE)
when no network loads, and the NNUE when a network is provided via
`$SGR_EVALFILE` (default `sgurr.nnue` in the working dir). `nnue.cpp` must
always be linked, since the evaluation references `nnue::` symbols even when
no net is loaded.

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
active path — check it when a build seems slow.

Run as HCE (no net) vs NNUE (net) with the same binary:

    ./sgr.exe uci                                  # HCE (no SGR_EVALFILE, no sgurr.nnue)
    SGR_EVALFILE=../nets/gen1.nnue ./sgr.exe uci   # NNUE

## Datagen

    /c/msys64/clang64/bin/clang++ -std=c++20 -O3 -march=native -DNDEBUG -static \
        datagen.cpp board.cpp evaluation.cpp search.cpp nnue.cpp \
        -o datagen.exe

See the header of `datagen.cpp` for arguments (fixed depth vs `nodes:N`).
