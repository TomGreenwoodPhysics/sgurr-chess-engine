#!/usr/bin/env bash
# Resume the SPSA tune. Kept as a file rather than an inline bash -lc string:
# the inline form died on launch, this pattern has been reliable all week.
cd /c/coding/Sgurr || exit 1
exec ./.venv/Scripts/python.exe testing/spsa.py \
    --config testing/spsa_v90_batch_gen9.json --resume \
    >> runs/sgurr_x/spsa_driver.log 2>&1
