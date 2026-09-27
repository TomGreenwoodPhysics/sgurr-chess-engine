#!/usr/bin/env bash
# Build Sgurr and verify that the resulting binary starts.
# Smart App Control can reject a newly linked unsigned binary, so a failed
# verification triggers another link with a new file hash.
#
# Usage
#   ./build.sh                        # dev build      -> sgr.exe
#   ./build.sh -r                     # release build  -> sgr.exe  (PGO+ThinLTO)
#   ./build.sh -o sgr_test.exe        # choose the output name
#   ./build.sh -r -o sgr_v8_1.exe
#   ./build.sh -r -o sgr_v9_0.exe --version 9.0
#   ./build.sh -d                     # datagen build  -> datagen.exe (RFP off)
#   ./build.sh -t                     # visual trace   -> sgr_trace.exe
#   ./build.sh -r --arch native       # this machine's own instruction set
#   ./build.sh -r --embed-net ../nets/gen9_screlu_cos_s1.nnue
#                                     # compile the network into the binary
#
set -u

CLANG=/c/msys64/clang64/bin/clang++
PROFDATA=/c/msys64/clang64/bin/llvm-profdata
ENGINE_SRC="main.cpp board.cpp evaluation.cpp search.cpp nnue.cpp"
DATAGEN_SRC="datagen.cpp board.cpp evaluation.cpp search.cpp nnue.cpp"
MAX_LINK_ATTEMPTS=6
# The network release builds are profiled with, unless one is embedded.
PROFILE_NET=../nets/gen9_screlu_cos_s1.nnue

# AVX2. -march=native picks AVX-512 on this Zen 4, which splits 512-bit
# instructions into two 256-bit halves, and measured 2.7% slower.
arch=x86-64-v3
mode=dev
out=""
extra=""
embed=""

while [ $# -gt 0 ]; do
    case "$1" in
        -r|--release) mode=release ;;
        -d|--datagen) mode=datagen ;;
        -t|--trace)   mode=trace ;;
        -o|--out)     out="$2"; shift ;;
        --arch)       arch="$2"; shift ;;
        --embed-net)  embed="$2"; shift ;;
        --version)    extra="$extra -DSGR_VERSION=\"$2\""; shift ;;
        -D*)          extra="$extra $1" ;;
        -h|--help)    sed -n '2,30p' "$0"; exit 0 ;;
        *)            echo "build.sh: unknown option '$1'" >&2; exit 2 ;;
    esac
    shift
done

# A 16 MB stack: the search recurses up to 128 plies, with a frame of about
# 7 KB each, and Windows gives the main thread only 1 MB unless told.
FLAGS="-std=c++20 -O3 -march=$arch -DNDEBUG -static -Wall -Wextra -Wl,--stack,16777216"

# #embed finds a relative path from nnue.cpp, not from here, so pass it whole.
if [ -n "$embed" ]; then
    [ -f "$embed" ] || { echo "build.sh: no network at '$embed'" >&2; exit 2; }
    embed_abs=$(cd "$(dirname "$embed")" && pwd)/$(basename "$embed")
    command -v cygpath >/dev/null 2>&1 && embed_abs=$(cygpath -m "$embed_abs")
    extra="$extra -DSGR_EMBED_NET=\"$embed_abs\""
fi

case "$mode" in
    datagen) src="$DATAGEN_SRC"; [ -n "$out" ] || out=datagen.exe
             # Labeller builds disable RFP because labels require searched scores.
             extra="$extra -DSGR_RFP=0" ;;
    trace)   src="$ENGINE_SRC"; [ -n "$out" ] || out=sgr_trace.exe
             # Separate trace build for the web Search Network.
             # The browser reduces this pool to a connected 120-node subtree.
             extra="$extra -DSGR_TRACE_SEARCH=1 -DSGR_TRACE_NODE_LIMIT=1200" ;;
    *)       src="$ENGINE_SRC";  [ -n "$out" ] || out=sgr.exe ;;
esac

cd "$(dirname "$0")" || exit 1

# Verify startup without requiring SGR_EVALFILE.
# Datagen uses its usage message as the liveness signal because it is not UCI.
verify() {
    if [ "$mode" = datagen ]; then
        "./$1" 2>&1 | grep -q '^usage: datagen'
    else
        printf 'uci\nisready\nquit\n' | "./$1" 2>/dev/null | grep -q uciok
    fi
}

# Relink rejected binaries to give them a new hash.
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
    # Instrument, profile, merge and optimise. See BUILD.md.
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

    # Profile the evaluation the engine plays with. On the hand-crafted eval
    # the network's code counts as cold, and the build ran 1.6% slower.
    if [ -n "$embed" ]; then
        profile=$(env -u SGR_EVALFILE ./sgr_prof.exe bench 13 2>&1)
    else
        profile=$(SGR_EVALFILE="${SGR_EVALFILE:-$PROFILE_NET}" ./sgr_prof.exe bench 13 2>&1)
    fi
    if echo "$profile" | grep -q 'eval nnue'; then
        echo "  [2/4] profiling run (bench 13, network)"
    else
        echo "  [2/4] profiling run (bench 13, hand-crafted eval: no network this build can load)"
    fi

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
