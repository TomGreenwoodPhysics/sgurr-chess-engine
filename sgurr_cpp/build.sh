#!/usr/bin/env bash
#
# Build Sgurr and prove the binary actually runs before handing it back.
#
# Why the verify step exists
# --------------------------
# Smart App Control is ENFORCED on this machine and intermittently refuses to
# start freshly linked unsigned binaries -- observed at roughly 2 in 6 builds.
# The block lands on the file, not the code: two byte-identical binaries under
# different names, one blocked and one not. It has no exclusion mechanism, and
# disabling it is a ONE-WAY switch (Windows cannot re-enable it without an OS
# reset), so the supported remedy is simply to link again and re-check.
#
# Verdicts are sticky in the useful direction: once a binary starts, it keeps
# starting. So verifying once at build time is sufficient, and it is the
# cheapest possible place to catch the problem -- the alternative is finding
# out hours into a gauntlet, where a non-spawning engine forfeits every game
# and still produces a complete, plausible-looking result.
#
# Usage:
#   ./build.sh                        # dev build      -> sgr.exe
#   ./build.sh -r                     # release build  -> sgr.exe  (PGO+ThinLTO)
#   ./build.sh -o sgr_test.exe        # choose the output name
#   ./build.sh -r -o sgr_v8_1.exe
#   ./build.sh -d                     # datagen build  -> datagen.exe (RFP off)
#
set -u

CLANG=/c/msys64/clang64/bin/clang++
PROFDATA=/c/msys64/clang64/bin/llvm-profdata
FLAGS="-std=c++20 -O3 -march=native -DNDEBUG -static -Wall -Wextra"
ENGINE_SRC="main.cpp board.cpp evaluation.cpp search.cpp nnue.cpp"
DATAGEN_SRC="datagen.cpp board.cpp evaluation.cpp search.cpp nnue.cpp"
MAX_LINK_ATTEMPTS=6

mode=dev
out=""
extra=""

while [ $# -gt 0 ]; do
    case "$1" in
        -r|--release) mode=release ;;
        -d|--datagen) mode=datagen ;;
        -o|--out)     out="$2"; shift ;;
        -D*)          extra="$extra $1" ;;
        -h|--help)    sed -n '2,30p' "$0"; exit 0 ;;
        *)            echo "build.sh: unknown option '$1'" >&2; exit 2 ;;
    esac
    shift
done

case "$mode" in
    datagen) src="$DATAGEN_SRC"; [ -n "$out" ] || out=datagen.exe
             # Labeller builds MUST disable RFP: it returns a raw static eval
             # where a searched score is expected, which poisoned gen6 entirely.
             extra="$extra -DSGR_RFP=0" ;;
    *)       src="$ENGINE_SRC";  [ -n "$out" ] || out=sgr.exe ;;
esac

cd "$(dirname "$0")" || exit 1

# Verify a binary actually starts. Deliberately net-independent: the engine
# falls back to the hand-crafted eval with no network, so this works without
# SGR_EVALFILE being set.
#
# The liveness signal differs by target. datagen is NOT a UCI engine -- it
# takes positional arguments and prints a usage line when given none -- so
# probing it with a UCI handshake reports a perfectly good build as broken.
verify() {
    if [ "$mode" = datagen ]; then
        "./$1" 2>&1 | grep -q '^usage: datagen'
    else
        printf 'uci\nisready\nquit\n' | "./$1" 2>/dev/null | grep -q uciok
    fi
}

# Link, then check. On refusal, link again: a fresh link gets a new PE
# timestamp and therefore a new hash, which is normally allowed through.
link_and_verify() {
    local attempt=1
    while [ "$attempt" -le "$MAX_LINK_ATTEMPTS" ]; do
        rm -f "$out"
        # shellcheck disable=SC2086
        if ! $CLANG $FLAGS $extra $1 $src -o "$out"; then
            echo "build.sh: COMPILE FAILED" >&2
            return 1
        fi
        if verify "$out"; then
            [ "$attempt" -gt 1 ] && echo "  (cleared on link attempt $attempt)"
            return 0
        fi
        echo "  link attempt $attempt: '$out' built but will not start -- relinking" >&2
        attempt=$((attempt + 1))
        sleep 2
    done

    cat >&2 <<EOF

build.sh: FAILED -- '$out' compiled but would not start after $MAX_LINK_ATTEMPTS attempts.

This is almost certainly Smart App Control refusing an unsigned binary.
Confirm with:
    powershell -c "& '.\\$out'"
A block reports: "An Application Control policy has blocked this file".

Do NOT ship or benchmark this binary. An engine that cannot spawn does not
crash a match -- it forfeits every game and still produces a full result.
EOF
    return 1
}

echo "build.sh: $mode -> $out"

if [ "$mode" = release ]; then
    # 1. instrumented  2. profile  3. merge  4. optimised. See BUILD.md.
    rm -rf pgo && mkdir -p pgo
    echo "  [1/4] instrumented build"
    # shellcheck disable=SC2086
    $CLANG $FLAGS $extra -fprofile-generate=./pgo $src -o sgr_prof.exe || exit 1
    if ! verify sgr_prof.exe; then
        echo "  instrumented binary blocked -- relinking" >&2
        rm -f sgr_prof.exe
        # shellcheck disable=SC2086
        $CLANG $FLAGS $extra -fprofile-generate=./pgo $src -o sgr_prof.exe || exit 1
        verify sgr_prof.exe || { echo "build.sh: instrumented build will not start" >&2; exit 1; }
    fi

    echo "  [2/4] profiling run (bench 13)"
    ./sgr_prof.exe bench 13 >/dev/null 2>&1

    echo "  [3/4] merging profile"
    $PROFDATA merge -output=pgo/sgurr.profdata pgo/*.profraw || exit 1
    rm -f sgr_prof.exe

    echo "  [4/4] optimised build"
    link_and_verify "-flto=thin -fuse-ld=lld -fprofile-use=./pgo/sgurr.profdata" || exit 1
else
    link_and_verify "" || exit 1
fi

if [ "$mode" = datagen ]; then
    echo "build.sh: OK   $out   (datagen, RFP disabled)"
else
    echo "build.sh: OK   $out   ($(printf 'uci\nquit\n' | "./$out" 2>/dev/null | sed -n 's/^id name //p'))"
fi
