#!/usr/bin/env bash
# Build the public Windows release: two binaries with the network compiled in,
# each checked, then zipped with a readme, the licence and checksums.
#
#   tools/release.sh VERSION
#
# Writes dist/sgurr-VERSION-windows.zip. Every binary must reproduce the bench
# fingerprint from its embedded network, pass testing/uci_protocol.py and show
# only the release options. Nothing is uploaded: attach the zip to a GitHub
# release by hand.
set -u

ROOT=$(cd "$(dirname "$0")/.." && pwd)
VERSION=${1:?usage: tools/release.sh VERSION}
NET=nets/gen9_screlu_cos_s1.nnue
BENCH=1149339                  # bench nodes with that network, as BENCH_NNUE in ci.yml
OUT=$ROOT/dist/sgurr-$VERSION
ZIP=$ROOT/dist/sgurr-$VERSION-windows.zip

die() { echo "release: $*" >&2; exit 1; }

# name, CPU level and extra flags. Without AVX2 the scalar path is used. There
# is no AVX-512 build: on Zen 4 it measured 2.7% slower than AVX2, and a tester
# who saw avx512 in a file name would likely pick it.
TARGETS="avx2:x86-64-v3: compat:x86-64-v2:-DSGR_SIMD=0"

cd "$ROOT" || exit 1
[ -f "$NET" ] || die "missing $NET"
rm -rf "$OUT" "$ZIP"
mkdir -p "$OUT"

for target in $TARGETS; do
    IFS=: read -r name arch flags <<< "$target"
    exe=sgurr-$VERSION-$name.exe
    echo "== $exe ($arch)"

    # shellcheck disable=SC2086
    sgurr_cpp/build.sh -r --arch "$arch" --embed-net "$NET" --version "$VERSION" \
        -DSGR_TUNING_OPTIONS=0 $flags -o "$exe" | sed 's/^/   /'
    [ "${PIPESTATUS[0]}" -eq 0 ] || die "$exe did not build"
    mv "sgurr_cpp/$exe" "$OUT/$exe" || die "could not move $exe"

    # From an empty directory with no SGR_EVALFILE, as a GUI would start it.
    check=$(cd "$OUT" && env -u SGR_EVALFILE "./$exe" bench 2>&1)
    echo "$check" | grep -q "nnue: loaded <embedded>" || die "$exe did not load its embedded network"
    nodes=$(echo "$check" | sed -n 's/^nodes \([0-9]*\).*/\1/p' | tail -1)
    [ "$nodes" = "$BENCH" ] || die "$exe bench $nodes, expected $BENCH"
    echo "   bench $nodes from the embedded network"

    python testing/uci_protocol.py "$OUT/$exe" --embedded --public > "$OUT/protocol-$name.txt" \
        || { cat "$OUT/protocol-$name.txt"; die "$exe failed the UCI protocol checks"; }
    echo "   UCI protocol checks passed"
    rm -f "$OUT/protocol-$name.txt"
done

cp LICENSE "$OUT/LICENSE.txt"
cat > "$OUT/README.txt" <<EOF
Sgurr $VERSION, a UCI chess engine by Tom Greenwood

Which build:
  sgurr-$VERSION-avx2.exe
      any CPU with AVX2, which nearly every x86-64 CPU of the last ten years has
  sgurr-$VERSION-compat.exe
      older CPUs without AVX2, about a third slower

Both builds search identically, so the faster one only looks further in the
same time. The neural network is built in, so no other file is needed.

UCI options
  Hash            transposition table size in MB, default 48
  Threads         fixed at 1
  Move Overhead   milliseconds kept back on each move for GUI delays, default 30
  Clear Hash      empties the transposition table

Source and measurements: https://github.com/TomGreenwoodPhysics/sgurr-chess-engine
Licence: LICENSE.txt. Checksums: SHA256SUMS.txt.
EOF
(cd "$OUT" && sha256sum ./*.exe | sed 's| \*\./| |; s| \./| |' > SHA256SUMS.txt)
(cd "$ROOT/dist" && python -m zipfile -c "$(basename "$ZIP")" "sgurr-$VERSION") || die "could not zip"

echo "== $ZIP"
cat "$OUT/SHA256SUMS.txt"
