#!/usr/bin/env bash
# train.py decodes positions on the CPU, so it cannot share the machine with a
# concurrency-7 match: the GPU sat at 0% while the cores were saturated. Wait
# for the first SPRT to finish, then train with the machine to itself.
set -u
ROOT=/c/coding/Sgurr
while ! grep -aq "1. batch+tuned vs v9.0:" "$ROOT/runs/sgurr_x/mainline_sprts.log" 2>/dev/null; do
    sleep 60
done
sleep 10
exec "$ROOT/tools/mainline_screlu_train.sh"
