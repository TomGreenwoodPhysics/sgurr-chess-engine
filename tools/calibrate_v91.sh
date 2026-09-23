#!/usr/bin/env bash
# Calibrate v9.1 (batch + SPSA tuned + screlu QA=181) against pool-2026-08-D.
#
# NET_FILE is mandatory here. run_calibrate.sh exports SGR_EVALFILE from it,
# which overrides whatever net is baked into the binary; defaulting to gen8
# meant a QA=181 build was handed a QA=255 net, the architecture check rejected
# it, and the preflight aborted. Point it at the matching net instead.
set -u
ROOT=/c/coding/Sgurr
export NET_FILE="$ROOT/nets/gen9_screlu.nnue"
cd "$ROOT" || exit 1
exec ./tools/run_calibrate.sh v9.1 sprt_bundle.exe 1 500 10
