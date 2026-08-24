#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${1:-$ROOT_DIR/build}"
CXX="${CXX:-c++}"

mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"
cd "$ROOT_DIR"

COMMON_FLAGS=(
    -std=c++20
    -O3
    -DNDEBUG
    -DSGR_SIMD=0
    -Wall
    -Wextra
)
SOURCES=(main.cpp board.cpp evaluation.cpp search.cpp nnue.cpp)

"$CXX" "${COMMON_FLAGS[@]}" "${SOURCES[@]}" -o "$OUT_DIR/sgr_v8_2"
"$CXX" "${COMMON_FLAGS[@]}" \
    -DSGR_TRACE_SEARCH=1 \
    -DSGR_TRACE_NODE_LIMIT=1200 \
    "${SOURCES[@]}" \
    -o "$OUT_DIR/sgr_trace"
