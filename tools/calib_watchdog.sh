#!/usr/bin/env bash
# Watchdog for the calibration. The last run logged "starting" and "finished"
# nine seconds apart and nobody noticed for three hours. This emits a line only
# when something is wrong, or when the run genuinely completes.
set -u
ROOT=/c/coding/Sgurr
# Re-resolve the newest pgn on every poll. Pinning it at startup meant a
# restarted run wrote to a new file while this watched the dead one and
# reported a stall that was not happening.
last=0
stalls=0
while true; do
    sleep 300
    if ! pgrep -f fastchess >/dev/null 2>&1 \
       && ! powershell -NoProfile -Command "exit ((Get-Process -Name fastchess -ErrorAction SilentlyContinue | Measure-Object).Count)" 2>/dev/null; then
        :
    fi
    n=$(powershell -NoProfile -Command "(Get-Process -Name fastchess -ErrorAction SilentlyContinue | Measure-Object).Count" 2>/dev/null | tr -d '\r ')
    PGN=$(ls -t $ROOT/benchmarks/games/calib-v9.1-*.pgn 2>/dev/null | head -1)
    cur=$(stat -c %s "$PGN" 2>/dev/null || echo 0)
    if [ "${n:-0}" = "0" ]; then
        echo "WATCHDOG: fastchess is gone. $(basename "$PGN")=$cur bytes. Run ended or died."
        exit 0
    fi
    if [ "$cur" -eq "$last" ]; then
        stalls=$((stalls + 1))
        if [ "$stalls" -ge 3 ]; then
            echo "WATCHDOG: $(basename "$PGN") stuck at $cur bytes for 15 min while fastchess runs."
            exit 1
        fi
    else
        stalls=0
    fi
    last=$cur
done
